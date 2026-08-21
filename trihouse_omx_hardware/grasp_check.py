"""그리퍼 전류 기반 파지 성공/실패 판정.

OMX 그리퍼(모터 ID 16, xl330-m288)는 Current-based Position Control Mode로
동작한다 (omx_follower.py의 configure()가 OperatingMode.CURRENT_POSITION으로
설정). 완전히 닫으라는 목표를 줘도, 빈 그립은 저항이 없어 전류가 낮게 끝나고
물체를 물면 전류가 올라간 채 목표 위치까지 못 간다.

position은 원래 전류와 함께 보조 신호로 쓰려 했으나, 실측(--debug-gripper로
스텝별 로그 300개 이상 수집)에서 그리퍼가 실제로 열려있을 때나 물건을 향해
접근하는 중이나 위치값이 53~59 사이(전체 폭 6 미만)에서만 움직였다 — 이
그리퍼의 calibration(range_min=0, range_max=4095, 모터 엔코더 전체 회전을
그대로 0~100에 매핑)이 실제 물리적 열림~닫힘 구간을 담지 못해서 position이
사실상 노이즈 수준이다. 그래서 지금은 current만으로 판정한다. position은
계속 로그에 남기지만(향후 재캘리브레이션 시 되살릴 수 있도록), 판정에는
관여하지 않는다.

또한 판정을 매 순간 값 1개로 확정하지 않는다 — 실측에서 단발성 전류 스파이크
(진동/순간 접촉) 때문에 "집었다"가 뜨자마자 2스텝 만에 "놓았다"로 뒤집히는
오탐이 있었다. Debouncer로 같은 판정이 연속 몇 스텝 유지돼야 확정한다.

임계값(current_threshold)은 실물로 몇 번 테스트해서 튜닝해야 하는 값이다 —
지금 값은 추정치일 뿐 신뢰하지 말 것.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lerobot.robots.omx_follower import OmxFollower

GRIPPER_MOTOR = "gripper"

# Dynamixel Present_Current는 부호 있는 raw 카운트(대략 2.69mA/count, XL330 기준).
# 빈 그립 대비 물체를 물었을 때 상승분을 보고 정해야 하며, 지금 값은 미검증 추정치.
DEFAULT_CURRENT_THRESHOLD = 40


def read_gripper(robot: OmxFollower) -> tuple[float, float]:
    """그리퍼 모터의 Present_Current/Present_Position을 한 번만 읽는다.

    디버그 출력과 판정 로직이 서로 다른 시점에 각자 읽으면(수 ms 차이) 빠르게
    움직이는 순간엔 값이 달라져 눈에 보이는 로그와 실제 판정이 어긋난다 —
    호출부(deliver.py/store.py)는 스텝당 이 함수를 한 번만 불러 그 결과를
    출력과 판정 양쪽에 그대로 재사용해야 한다.
    """
    current = robot.bus.sync_read("Present_Current", [GRIPPER_MOTOR])[GRIPPER_MOTOR]
    position = robot.bus.sync_read("Present_Position", [GRIPPER_MOTOR])[GRIPPER_MOTOR]
    return current, position


@dataclass(frozen=True)
class GraspVerdict:
    grasped: bool
    present_current: float
    present_position: float
    reason: str


def evaluate_grasp(
    current: float,
    position: float,
    *,
    current_threshold: float = DEFAULT_CURRENT_THRESHOLD,
) -> GraspVerdict:
    """이미 읽은 current/position 값으로 파지 여부를 판정한다(모터 I/O 없음)."""
    current_high = abs(current) >= current_threshold
    return GraspVerdict(
        grasped=current_high,
        present_current=current,
        present_position=position,
        reason="current_threshold_exceeded" if current_high else "empty_gripper",
    )


def check_grasp(
    robot: OmxFollower,
    *,
    current_threshold: float = DEFAULT_CURRENT_THRESHOLD,
) -> GraspVerdict:
    """read_gripper + evaluate_grasp을 한 번에. 단발성 최종 확인용(루프 밖)."""
    current, position = read_gripper(robot)
    return evaluate_grasp(current, position, current_threshold=current_threshold)


@dataclass(frozen=True)
class ReleaseVerdict:
    released: bool
    present_current: float
    present_position: float
    reason: str


def evaluate_release(
    current: float,
    position: float,
    *,
    current_threshold: float = DEFAULT_CURRENT_THRESHOLD,
) -> ReleaseVerdict:
    """이미 읽은 current/position 값으로 해제(release) 여부를 판정한다.

    물체가 아직 손에 남아 있으면(architecture 8.4의 GRASP_RETAINED에 해당)
    전류가 계속 높게 남는다 — 그렇지 않아야 "놓았다"로 본다. 낙하
    (DROP_DETECTED)와 정상 적재(LOAD_CONFIRMED)를 구분하려면 basket ROI 비전
    확인이 필요한데, 이건 1단계 범위 밖이라 여기선 "그리퍼가 비었다"까지만 본다.
    """
    current_high = abs(current) >= current_threshold
    return ReleaseVerdict(
        released=not current_high,
        present_current=current,
        present_position=position,
        reason="object_still_in_gripper" if current_high else "gripper_empty",
    )


def check_release(
    robot: OmxFollower,
    *,
    current_threshold: float = DEFAULT_CURRENT_THRESHOLD,
) -> ReleaseVerdict:
    """read_gripper + evaluate_release을 한 번에. 단발성 최종 확인용(루프 밖)."""
    current, position = read_gripper(robot)
    return evaluate_release(current, position, current_threshold=current_threshold)


# 연속 몇 스텝 동안 같은 판정이 유지돼야 확정하는지. fps 15 기준 3스텝 ≈ 200ms.
# 실측에서 단발성 전류 스파이크(1~2스텝)로 오탐이 난 것을 근거로 정한 시작값 —
# 여전히 자리표시자이며, 더 테스트하며 조정해야 한다.
DEFAULT_DEBOUNCE_STEPS = 3


@dataclass
class Debouncer:
    """조건이 연속 N스텝 True여야 확정(True)한다. 중간에 한 번이라도 False면 리셋."""

    required_consecutive: int = DEFAULT_DEBOUNCE_STEPS
    _count: int = field(default=0, init=False, repr=False)

    def update(self, condition: bool) -> bool:
        self._count = self._count + 1 if condition else 0
        return self._count >= self.required_consecutive
