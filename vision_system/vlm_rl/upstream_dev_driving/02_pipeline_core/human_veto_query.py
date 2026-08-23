"""recovery_filters.py의 R3-05(HUMAN_HARD_VETO) 콜백을 실제로 채운다.
DB(Reference/Episodic Memory) 없이도 지금 바로 연결 가능 -- VLM이 이미 사람 감지·
대략적 위치를 주고 있기 때문.

한계(정직하게 명시): 실제 카메라->맵 좌표 투영(깊이, extrinsic calibration)이 없어서,
bbox의 이미지 내 수평 위치만으로 로봇 기준 "대략적인 방향(bearing)"만 근사한다.
거리 정보가 없으므로 veto_range_m 안의 모든 거리를 다 막는 보수적 처리 --
"사람 안전은 점수로 흥정하지 않는다"(§7) 원칙에 따라 정밀도보다 안전 마진을 우선함.
나중에 깊이/TF 기반 정밀 투영으로 교체 가능하도록 함수 경계를 분리해둠.
"""
from __future__ import annotations

import math
from typing import Callable

# 2026-08-07 밤 실측 카메라 캘리브레이션값 (fx=747.90, 이미지 폭 기준 640px 가정)
CAMERA_FX = 747.90
CAMERA_IMAGE_WIDTH_PX = 640
CAMERA_HFOV_DEG = math.degrees(2 * math.atan2(CAMERA_IMAGE_WIDTH_PX / 2, CAMERA_FX))

VETO_RANGE_M = 2.0          # 이 거리 안은 방향만 맞으면 전부 veto (깊이 정보 없어서 보수적으로)
VETO_WIDTH_MARGIN_DEG = 15.0  # bbox 폭 근사 + 안전 마진


def _normalize_angle(a: float) -> float:
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def build_human_occupied_query(
    vlm_json: dict,
    robot_x: float,
    robot_y: float,
    robot_yaw: float,
    camera_hfov_deg: float = CAMERA_HFOV_DEG,
    veto_range_m: float = VETO_RANGE_M,
    veto_width_margin_deg: float = VETO_WIDTH_MARGIN_DEG,
) -> Callable[[float, float], bool]:
    """VLM JSON(§4.1 계약) + 현재 로봇 pose로, FilterContext.query_human_occupied_region에
    그대로 바인딩할 수 있는 (x,y)->bool 함수를 만든다.

    VLM이 risk를 "low"로 매겨도 사람이면 무조건 veto 후보에 넣는다 -- risk 판단을
    신뢰해서 사람을 봐주지 않는다는 게 §7 원칙("사람 안전은 학습 점수로 흥정하지 않는다").
    """
    persons = [o for o in vlm_json.get("observations", [])
               if o.get("semantic_label") == "person"]

    if not persons:
        return lambda x, y: False

    veto_sectors: list[tuple[float, float]] = []
    for p in persons:
        bbox = p.get("bbox_norm", [0.4, 0.4, 0.6, 0.6])
        center_x_norm = (bbox[0] + bbox[2]) / 2.0
        bbox_width_norm = abs(bbox[2] - bbox[0])

        # 이미지 중심(0.5) 기준 좌우 offset -> 각도. 이미지 왼쪽(center_x_norm<0.5)을
        # 로봇 기준 양(+)의 yaw 방향(반시계, REP103)으로 매핑.
        bearing_offset_deg = (0.5 - center_x_norm) * camera_hfov_deg
        bbox_half_width_deg = (bbox_width_norm * camera_hfov_deg) / 2.0

        person_bearing = robot_yaw + math.radians(bearing_offset_deg)
        half_width = math.radians(bbox_half_width_deg + veto_width_margin_deg)
        veto_sectors.append((person_bearing - half_width, person_bearing + half_width))

    def query(x: float, y: float) -> bool:
        dx, dy = x - robot_x, y - robot_y
        dist = math.hypot(dx, dy)
        if dist > veto_range_m:
            return False  # 범위 밖은 방향이 맞아도 지금은 안전하다고 봄
        bearing = math.atan2(dy, dx)
        for lo, hi in veto_sectors:
            # 각도 wraparound 처리 위해 bearing을 lo 기준으로 정규화해서 비교
            rel = _normalize_angle(bearing - lo)
            span = _normalize_angle(hi - lo)
            if span < 0:
                span += 2 * math.pi
            if 0 <= rel <= span:
                return True
        return False

    return query


if __name__ == "__main__":
    """단위 테스트 -- 실제 VLM/로봇 없이 합성 데이터로 기하 로직만 검증.
    시나리오: 로봇이 원점에서 정면(yaw=0)을 보고 있고, VLM이 이미지 왼쪽에서
    사람을 감지(risk=low로 낮게 나와도 veto 되어야 함)."""
    mock_vlm_json = {
        "observations": [
            {
                "region_id": "r1",
                "bbox_norm": [0.05, 0.3, 0.25, 0.9],  # 이미지 왼쪽에 크게 잡힌 사람
                "semantic_label": "person",
                "risk": "low",  # 일부러 낮은 risk -- 그래도 veto 되어야 함
                "confidence": 0.8,
                "motion_evidence": "none",
            }
        ],
        "uncertainty": 0.2,
    }

    query = build_human_occupied_query(mock_vlm_json, robot_x=0.0, robot_y=0.0, robot_yaw=0.0)
    print(f"추정 camera HFOV: {CAMERA_HFOV_DEG:.1f}deg (fx={CAMERA_FX}, width={CAMERA_IMAGE_WIDTH_PX}px)")

    # bbox center_x_norm=0.15 -> bearing_offset=(0.5-0.15)*46.3≈16.2deg,
    # half_width=(0.2*46.3/2 + 15)≈19.6deg -> veto sector ≈ [-3.4deg, +35.8deg]
    def polar(dist, deg):
        return (dist * math.cos(math.radians(deg)), dist * math.sin(math.radians(deg)))

    test_points = [
        ("sector 중심(16deg), 1m", *polar(1.0, 16.0)),
        ("sector 안쪽 경계(30deg), 1m", *polar(1.0, 30.0)),
        ("sector 밖(60deg, 순수 왼쪽 too far)", *polar(1.0, 60.0)),
        ("sector 안쪽이지만 range 밖(16deg, 3m)", *polar(3.0, 16.0)),
        ("반대 방향(오른쪽, -60deg)", *polar(1.0, -60.0)),
        ("정면(0deg) -- sector 경계 근처라 margin에 걸림", *polar(1.0, 0.0)),
    ]
    print("\n=== R3-05 인간 veto 지오메트리 테스트 (risk=low여도 veto 되는지 확인) ===")
    for label, x, y in test_points:
        occupied = query(x, y)
        mark = "VETO(사람 있음으로 판정)" if occupied else "통과"
        print(f"  {label:42s} (x={x:.2f}, y={y:.2f}) -> {mark}")

    print("\n=== 사람이 감지 안 된 경우 (모든 후보 통과해야 함) ===")
    empty_query = build_human_occupied_query({"observations": []}, 0.0, 0.0, 0.0)
    for label, x, y in test_points:
        print(f"  {label:32s} -> {'VETO' if empty_query(x, y) else '통과'}")
