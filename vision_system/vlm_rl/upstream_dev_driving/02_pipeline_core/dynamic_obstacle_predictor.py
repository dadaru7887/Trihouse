"""geometric_6c_lite.py가 못 하는 것("동적 장애물의 미래 움직임 예측 안 함")을 보완하는
경량 모듈.

학습된 모델이 아니라 **등속 운동 가정(constant velocity model)**의 단순 선형 외삽이다 --
자율주행/보행자 경로 예측에서 가장 기본이 되는 baseline과 같은 방식(칼만필터의 예측 단계와도
개념적으로 동일, 다만 여긴 노이즈 보정 없이 순수 외삽만). `orchestrate_live_teleop.py`의
`ObjectWatcher`가 이미 매 SEG_INTERVAL_SEC(0.2s)마다 쌓아온 track history(cx, cy, area --
카메라 픽셀 좌표계)만 갖고 계산하므로 **새 데이터도 학습도 필요 없다.**

한계 (정직하게 명시):
- 카메라 픽셀 좌표계에서만 동작한다. world frame(x,y 미터)으로 정확히 변환하려면 camera
  calibration/homography가 필요한데 아직 안 붙어있어서(`camera_calibration.npz`는 로봇에
  있지만 이 모듈엔 연결 안 함), "화면 중앙/하단으로 향하는 추세"처럼 상대적인 신호만 본다.
  geometric_6c_lite.py(world frame)와 좌표계가 달라서 직접 합산은 안 되고, 별도의 보조
  advisory 신호로만 쓴다.
- 등속 가정이라 갑자기 방향을 트는 물체는 못 잡는다.
- 최근 TRACK_WINDOW(기본 5)개 관측치만 보고 판단하는 짧은 시야다.
- 그래도 없는 것보다 나은 이유: 최소한 "빠르게 다가오면서 화면 중앙으로 향하는 물체"를
  정적 스냅샷 체크(geometric_6c_lite)보다 한두 스텝 먼저 잡을 수 있다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class DynamicRiskAssessment:
    predicted_cx: float
    predicted_cy: float
    predicted_position: str  # 예: "MIDDLE-CENTER" (segment_image()의 위치 라벨과 동일 규약)
    approaching_path: bool   # 화면 중앙(경로 방향)으로 다가오는 추세인지
    area_trend: str          # "growing" | "shrinking" | "stable"
    velocity_px_per_frame: tuple[float, float]
    n_observations_used: int
    note: str


def _classify_position(cx: float, cy: float, w: int, h: int) -> str:
    """vlm_contract_to_rl_state.segment_image()와 동일한 3x3 구역 분류 규약 재사용."""
    h_pos = "LEFT" if cx < w / 3 else ("RIGHT" if cx > 2 * w / 3 else "CENTER")
    v_pos = "TOP" if cy < h / 3 else ("BOTTOM" if cy > 2 * h / 3 else "MIDDLE")
    return f"{v_pos}-{h_pos}"


def predict_track_risk(hist: list[dict], img_w: int, img_h: int,
                        n_steps_ahead: int = 3) -> DynamicRiskAssessment | None:
    """ObjectWatcher.tracks[tid]["hist"](cx, cy, area 순으로 쌓인 리스트)를 받아서
    n_steps_ahead(기본 3 = SEG_INTERVAL_SEC 0.2s 기준 약 0.6초 뒤) 후 위치를 등속
    외삽으로 예측. hist가 2개 미만이면 속도를 계산할 수 없어 None 반환."""
    if len(hist) < 2:
        return None

    # 연속 관측치 간 평균 프레임당 변화량(속도 근사) -- SEG_INTERVAL_SEC 간격이 일정하다고
    # 가정(ObjectWatcher가 고정 주기로 프레임을 처리하므로 근사적으로 타당).
    dcx_list, dcy_list, darea_list = [], [], []
    for i in range(1, len(hist)):
        dcx_list.append(hist[i]["cx"] - hist[i - 1]["cx"])
        dcy_list.append(hist[i]["cy"] - hist[i - 1]["cy"])
        darea_list.append(hist[i]["area"] - hist[i - 1]["area"])

    vx = sum(dcx_list) / len(dcx_list)
    vy = sum(dcy_list) / len(dcy_list)
    v_area = sum(darea_list) / len(darea_list)

    last = hist[-1]
    pred_cx = last["cx"] + vx * n_steps_ahead
    pred_cy = last["cy"] + vy * n_steps_ahead
    # 화면 밖으로 나가는 예측은 화면 경계로 clamp (그 방향으로 나가고 있다는 뜻은 유지)
    pred_cx_clamped = max(0.0, min(img_w, pred_cx))
    pred_cy_clamped = max(0.0, min(img_h, pred_cy))

    predicted_position = _classify_position(pred_cx_clamped, pred_cy_clamped, img_w, img_h)

    # "경로 쪽으로 다가오는 추세"의 단순 근사: 화면 중앙(가로) 쪽으로 향하는 "방향"인지를
    # 속도 부호로 직접 판단 (거리 스냅샷 두 개를 비교하면 물체가 중앙을 가로질러 반대편으로
    # 넘어갈 때 거리 값이 우연히 비슷해져서 방향을 놓치는 버그가 있었음 -- 방향 벡터로 수정).
    img_center_x = img_w / 2
    offset_now = img_center_x - last["cx"]  # 양수면 중앙이 오른쪽에 있음(물체가 왼쪽)
    moving_toward_center = (offset_now * vx) > 0  # 물체 위치 기준 중앙 방향과 속도 방향이 같은 부호
    moving_toward_bottom = vy > 0  # 이미지 좌표계는 아래로 갈수록 y 증가 = 화면 하단 = 로봇과 가까움
    approaching_path = moving_toward_center and moving_toward_bottom

    if v_area > last["area"] * 0.05:
        area_trend = "growing"
    elif v_area < -last["area"] * 0.05:
        area_trend = "shrinking"
    else:
        area_trend = "stable"

    note = (f"{n_steps_ahead}스텝 뒤 예측: ({pred_cx:.0f},{pred_cy:.0f}) [{predicted_position}], "
            f"면적추세={area_trend}, 경로접근={'예' if approaching_path else '아니오'} "
            f"(등속 외삽, world frame 아님 -- 픽셀 좌표계 상대 추세만)")

    return DynamicRiskAssessment(
        predicted_cx=pred_cx, predicted_cy=pred_cy, predicted_position=predicted_position,
        approaching_path=approaching_path, area_trend=area_trend,
        velocity_px_per_frame=(vx, vy), n_observations_used=len(hist), note=note,
    )


if __name__ == "__main__":
    IMG_W, IMG_H = 640, 480

    print("=== 테스트 1: 화면 중앙 쪽으로 빠르게 다가오는 물체 ===")
    hist_approaching = [
        {"cx": 500, "cy": 100, "area": 1000, "class": "person"},
        {"cx": 460, "cy": 140, "area": 1400, "class": "person"},
        {"cx": 420, "cy": 180, "area": 1900, "class": "person"},
        {"cx": 380, "cy": 220, "area": 2500, "class": "person"},
    ]
    r1 = predict_track_risk(hist_approaching, IMG_W, IMG_H)
    print(f"  approaching_path={r1.approaching_path}, area_trend={r1.area_trend}")
    print(f"  {r1.note}")

    print("\n=== 테스트 2: 화면 가장자리로 멀어지는 물체 ===")
    hist_leaving = [
        {"cx": 300, "cy": 300, "area": 2000, "class": "obstacle"},
        {"cx": 250, "cy": 280, "area": 1600, "class": "obstacle"},
        {"cx": 200, "cy": 260, "area": 1200, "class": "obstacle"},
    ]
    r2 = predict_track_risk(hist_leaving, IMG_W, IMG_H)
    print(f"  approaching_path={r2.approaching_path}, area_trend={r2.area_trend}")
    print(f"  {r2.note}")

    print("\n=== 테스트 3: 관측치 1개뿐(속도 계산 불가) ===")
    r3 = predict_track_risk([{"cx": 300, "cy": 300, "area": 1000, "class": "person"}], IMG_W, IMG_H)
    print(f"  결과: {r3} (None이어야 정상 -- 속도 계산할 데이터 부족)")

    print("\n=== 테스트 4: 정지된 물체(속도 거의 0) ===")
    hist_static = [
        {"cx": 320, "cy": 240, "area": 1000, "class": "obstacle"},
        {"cx": 321, "cy": 239, "area": 1005, "class": "obstacle"},
        {"cx": 320, "cy": 241, "area": 998, "class": "obstacle"},
    ]
    r4 = predict_track_risk(hist_static, IMG_W, IMG_H)
    print(f"  approaching_path={r4.approaching_path}, area_trend={r4.area_trend}")
    print(f"  {r4.note}")
