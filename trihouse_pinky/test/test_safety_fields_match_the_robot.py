"""안전 필드는 로봇의 실제 모양과 그때의 움직임을 따라야 한다.

## 왜 필드가 둘인가

산업용 안전 스캐너와 같은 구조다 — **보호 필드(STOP)** 와 **경고 필드(SLOW)**.

`safety_supervisor` 는 원래 스캔 **360도 전체의 최솟값**을 `front_distance_m`
이라고 부르며 STOP 판정에 썼다. 2.20 x 2.70 m 방에서는 어느 방향이든 벽이 늘
`stop_distance_m` 안에 있으므로 영구 STOP 이 된다. 2026-08-20 실측: 벽을 세우자
`detail=front_stop`, `dispatchable=False` 로 굳어 주문이 얹히지 않았다.

늘 울리는 경보는 정보가 0 이다. 사람이 실제로 옆에 서도 값이 바뀌지 않는다.

## 왜 모양이 움직임에 따라 바뀌는가

**직진할 때** 위험한 것은 경로 위에 있는 것이다. 폭 0.20 m 통로의 옆벽은 로봇
옆을 스쳐 지나갈 뿐이라 STOP 대상이 아니다.

**제자리 회전할 때는 다르다.** 로봇이 외접원 전체를 쓸고 지나가므로, 옆에 있는
것이 곧 부딪히는 것이다. 이때는 원이 맞다.

## 라이다 장착 보정

`rplidar_link` 는 `rpy="0 0 ${pi}"` 로 달려 있어 **스캔각 0 이 로봇 뒤**를
가리키고, base_footprint 보다 0.017 m 뒤에 있다. 2026-08-20 실측 TF:
`xyz=(-0.017, 0, 0.125) yaw=3.1416`. 이 보정 없이 빔 각도로 정면을 고르면 정확히
반대쪽을 재게 된다.
"""

import math
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import yaml

PINKY = Path(__file__).resolve().parents[1]
REPOSITORY = PINKY.parent
URDF = REPOSITORY / "pinky_pro" / "pinky_description" / "urdf" / "pinky.urdf.xacro"
NAV2_PARAMS = (
    REPOSITORY / "pinky_pro" / "pinky_navigation" / "params" / "nav2_params.yaml"
)

sys.path.insert(0, str(PINKY / "trihouse_pinky_safety"))

from trihouse_pinky_safety.geometry import (  # noqa: E402
    PROTECTIVE_HALF_WIDTH_M,
    SCAN_FORWARD_OFFSET_RAD,
    SCAN_ORIGIN_OFFSET_X_M,
    SWEPT_RADIUS_M,
    forward_path_distance,
    nearest_range,
    rotating_in_place,
)


# ---------------------------------------------------------------- 장착 계약


def _yaw(expression: str) -> float:
    """xacro rpy 의 세 번째 값. `${pi}` 같은 짧은 식만 허용한다."""
    token = expression.split()[2]
    inner = token[2:-1] if token.startswith("${") and token.endswith("}") else token
    return float(eval(inner, {"__builtins__": {}}, {"pi": math.pi}))  # noqa: S307


def _lidar_mounting() -> tuple[float, float]:
    """벤더 URDF 에서 base_footprint 기준 라이다의 (x, yaw) 를 따라간다."""
    root = ElementTree.parse(URDF).getroot()
    parent: dict[str, str] = {}
    pose: dict[str, tuple[float, float]] = {}
    for joint in root.iter():
        if not joint.tag.endswith("joint"):
            continue
        child, mother, origin = joint.find("child"), joint.find("parent"), joint.find("origin")
        if child is None or mother is None:
            continue
        xyz = (origin.get("xyz", "0 0 0") if origin is not None else "0 0 0").split()
        parent[child.get("link")] = mother.get("link")
        pose[child.get("link")] = (
            float(xyz[0]),
            _yaw(origin.get("rpy", "0 0 0") if origin is not None else "0 0 0"),
        )

    link, x, yaw = "rplidar_link", 0.0, 0.0
    assert link in parent, "URDF 에 rplidar_link 가 없다"
    while link in parent:
        # 체인의 yaw 가 전부 0 또는 pi 라 x 는 그대로 더해도 된다. 그 전제를
        # 아래 test_the_mounting_chain_stays_axis_aligned 가 지킨다.
        x += pose[link][0]
        yaw += pose[link][1]
        link = parent[link]
    assert link == "base_footprint", f"체인이 base_footprint 에 닿지 않는다: {link}"
    return x, yaw


def _wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def test_the_forward_offset_matches_the_vendor_urdf() -> None:
    """벤더가 라이다를 돌려 달았다면 우리 기본값도 그만큼 돌아야 한다."""
    _, mounted_yaw = _lidar_mounting()
    assert abs(_wrap(mounted_yaw - SCAN_FORWARD_OFFSET_RAD)) < 1e-6, (
        f"URDF 의 라이다 yaw 는 {mounted_yaw:.6f} rad 인데 "
        f"SCAN_FORWARD_OFFSET_RAD 는 {SCAN_FORWARD_OFFSET_RAD:.6f} rad 다 — "
        "안전 gate 가 정면이 아닌 방향을 재게 된다"
    )


def test_the_scan_origin_offset_matches_the_vendor_urdf() -> None:
    """라이다는 회전 중심보다 뒤에 있다. 그만큼 장애물은 생각보다 가깝다."""
    mounted_x, _ = _lidar_mounting()
    assert abs(mounted_x - SCAN_ORIGIN_OFFSET_X_M) < 1e-6, (
        f"URDF 의 라이다 x 는 {mounted_x:.6f} m 인데 "
        f"SCAN_ORIGIN_OFFSET_X_M 는 {SCAN_ORIGIN_OFFSET_X_M:.6f} m 다"
    )


def test_the_mounting_chain_stays_axis_aligned() -> None:
    """체인에 0/pi 아닌 yaw 가 끼면 x 를 단순히 더할 수 없다."""
    root = ElementTree.parse(URDF).getroot()
    parent, yaws = {}, {}
    for joint in root.iter():
        if not joint.tag.endswith("joint"):
            continue
        child, mother, origin = joint.find("child"), joint.find("parent"), joint.find("origin")
        if child is None or mother is None:
            continue
        parent[child.get("link")] = mother.get("link")
        yaws[child.get("link")] = _yaw(
            origin.get("rpy", "0 0 0") if origin is not None else "0 0 0"
        )
    link = "rplidar_link"
    while link in parent:
        assert abs(_wrap(2 * yaws[link])) < 1e-6, (
            f"{link} 의 yaw 가 {yaws[link]} 다 — 0 이나 pi 가 아니면 "
            "x 오프셋을 단순 합산할 수 없고 이 테스트의 전제가 깨진다"
        )
        link = parent[link]


def test_the_swept_radius_matches_the_nav2_footprint() -> None:
    """회전이 쓸고 가는 원은 Nav2 가 쓰는 발자국에서 나와야 한다.

    Nav2 는 이 발자국으로 경로를 만들고 안전 gate 는 같은 몸으로 회전을 막는다.
    둘이 갈라지면 Nav2 가 낸 회전을 gate 가 거절하거나(주행 불가), gate 가
    통과시킨 회전에서 로봇이 벽을 친다.
    """
    if not NAV2_PARAMS.exists():
        return
    document = yaml.safe_load(NAV2_PARAMS.read_text(encoding="utf-8"))
    footprints: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "footprint" and isinstance(value, str):
                    footprints.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(document)
    assert footprints, "nav2 params 에 footprint 가 없다"
    circumscribed = max(
        math.hypot(x, y)
        for text in footprints
        for x, y in [tuple(float(v) for v in pair.split(","))
                     for pair in text.strip()[2:-2].split("], [")]
    )
    assert abs(circumscribed - SWEPT_RADIUS_M) < 5e-3, (
        f"Nav2 발자국의 외접반경은 {circumscribed:.4f} m 인데 "
        f"SWEPT_RADIUS_M 는 {SWEPT_RADIUS_M:.4f} m 다"
    )


# ---------------------------------------------------------------- 필드 모양


def _scan(bearings: dict[float, float], beams: int = 720) -> dict:
    """정면 기준 각도(도) -> 거리. 라이다 오프셋 0 으로 순수 기하만 본다.

    지정하지 않은 빔은 **측정 없음**(`inf`)이다. 먼 거리로 채우면 그 빔들이
    정당하게 경로 안에 들어와 무엇을 재는 시험인지 흐려진다.
    """
    increment = 2 * math.pi / beams
    ranges = [float("inf")] * beams
    for degree, distance in bearings.items():
        # 스캔각 = 정면기준각 - forward_offset
        index = int(round(_wrap(math.radians(degree) - SCAN_FORWARD_OFFSET_RAD) / increment)) % beams
        ranges[index] = distance
    return {
        "ranges": ranges,
        "angle_min": 0.0,
        "angle_increment": increment,
        "range_min": 0.05,
        "range_max": 12.0,
        "origin_offset_x_m": 0.0,
    }


def test_an_obstacle_behind_the_robot_is_not_on_the_path() -> None:
    """뒤쪽 벽이 STOP 을 걸면 로봇은 영원히 못 움직인다."""
    assert forward_path_distance(**_scan({180.0: 0.10})) is None


def test_an_obstacle_straight_ahead_is_on_the_path() -> None:
    assert abs(forward_path_distance(**_scan({0.0: 0.25})) - 0.25) < 1e-3


def test_a_wall_alongside_a_narrow_corridor_is_not_on_the_path() -> None:
    """폭 0.20 m 통로의 옆벽은 측면 0.10 m 다. 로봇 반폭 밖이라 스쳐 지나간다.

    이것이 STOP 을 걸면 통로를 한 번도 지날 수 없다. 부채꼴로는 반각을 아무리
    좁혀도 평행한 옆벽이 결국 들어온다 — 그래서 직사각형이어야 한다.
    """
    lateral, forward = 0.10, 0.25
    bearing = math.degrees(math.atan2(lateral, forward))
    assert forward_path_distance(**_scan({bearing: math.hypot(lateral, forward)})) is None
    assert forward_path_distance(**_scan({-bearing: math.hypot(lateral, forward)})) is None


def test_something_inside_the_robot_width_is_on_the_path() -> None:
    """반폭 안쪽으로 들어오면 정면이 아니어도 부딪힌다."""
    lateral, forward = PROTECTIVE_HALF_WIDTH_M - 0.01, 0.20
    bearing = math.degrees(math.atan2(lateral, forward))
    distance = forward_path_distance(**_scan({bearing: math.hypot(lateral, forward)}))
    assert distance is not None and abs(distance - forward) < 1e-3


def test_the_path_distance_is_measured_forward_not_along_the_beam() -> None:
    """비스듬한 빔의 길이가 아니라 전방 성분이 남은 거리다."""
    lateral, forward = 0.05, 0.20
    bearing = math.degrees(math.atan2(lateral, forward))
    beam = math.hypot(lateral, forward)
    distance = forward_path_distance(**_scan({bearing: beam}))
    assert abs(distance - forward) < 1e-3 and forward < beam


def test_the_scan_origin_offset_brings_obstacles_closer() -> None:
    """라이다가 뒤에 있으므로 회전 중심에서 잰 거리는 더 짧다."""
    plain = _scan({0.0: 0.30})
    plain["origin_offset_x_m"] = SCAN_ORIGIN_OFFSET_X_M
    assert abs(forward_path_distance(**plain) - (0.30 + SCAN_ORIGIN_OFFSET_X_M)) < 1e-3


def test_readings_outside_the_sensor_range_are_discarded() -> None:
    """`inf` 나 0 은 측정이 아니다. 그것을 최솟값으로 쓰면 없는 벽이 생긴다."""
    assert abs(forward_path_distance(**_scan({0.0: float("inf"), 1.0: 0.40})) - 0.40) < 5e-3
    assert abs(forward_path_distance(**_scan({0.0: 0.0, 1.0: 0.40})) - 0.40) < 5e-3


def test_an_empty_path_gives_none() -> None:
    """측정이 없는 것과 0 m 는 다르다. gate 는 그 둘을 구분해야 한다."""
    empty = _scan({})
    empty["ranges"] = [float("inf")] * len(empty["ranges"])
    assert forward_path_distance(**empty) is None


# ------------------------------------------------------- 경고 필드와 회전


def test_the_warning_field_sees_every_direction() -> None:
    """옆에 선 사람은 경로 밖이지만 경고 대상이다. 이것이 SLOW 의 근거다."""
    scan = _scan({90.0: 0.40})
    assert abs(nearest_range(**scan) - 0.40) < 1e-3


def test_rotation_in_place_is_told_from_driving() -> None:
    """제자리 회전은 외접원 전체를 쓴다. 직진과 같은 필드를 쓰면 안 된다."""
    assert rotating_in_place(0.0, 0.8)
    assert rotating_in_place(0.005, -0.8)
    assert not rotating_in_place(0.15, 0.8)   # 원호 주행
    assert not rotating_in_place(0.0, 0.0)    # 정지 — 회전이 아니다
    assert not rotating_in_place(0.15, 0.0)   # 직진


# ------------------------------------------------------------- gate 결합

from trihouse_pinky_safety.policy import (  # noqa: E402
    MotionCommand,
    SafetyConfig,
    SafetyInputs,
    SafetyLevel,
    apply_safety_gate,
)


def test_a_wall_beside_the_robot_does_not_slow_it_down() -> None:
    """벽은 지도에 있는 정적 장애물이다. 옆을 스친다고 느려질 이유가 없다.

    2.20 x 2.70 m 방에서 라이다 전방위 최솟값으로 SLOW 를 걸면 늘 걸린다 —
    영구 SLOW 는 영구 배정 불가로 이어지고, 그러면 필드를 나눈 의미가 없다.
    감속의 근거는 벽이 아니라 **사람**이다.
    """
    result = apply_safety_gate(
        MotionCommand(0.12, 0.0), SafetyInputs(front_distance_m=None)
    )
    assert result.level == SafetyLevel.CLEAR
    assert result.command.linear_x == 0.12


def test_a_person_near_the_robot_slows_it_down() -> None:
    """감속은 카메라의 사람 감지가 만든다. 경로 밖에 서 있어도 마찬가지다."""
    result = apply_safety_gate(
        MotionCommand(0.12, 0.0),
        SafetyInputs(front_distance_m=None, person_detected=True, person_distance_m=0.6),
    )
    assert result.level == SafetyLevel.SLOW
    assert result.command.linear_x == SafetyConfig().slow_linear_speed_mps


def test_something_far_ahead_on_the_path_slows_before_it_stops() -> None:
    """경로 위의 물체는 STOP 전에 먼저 SLOW 로 예고된다."""
    result = apply_safety_gate(
        MotionCommand(0.12, 0.0), SafetyInputs(front_distance_m=0.50)
    )
    assert result.level == SafetyLevel.SLOW


def test_rotating_into_something_beside_the_robot_stops() -> None:
    """제자리 회전은 외접원을 쓸고 지나간다. 옆에 있는 것이 곧 부딪히는 것이다."""
    result = apply_safety_gate(
        MotionCommand(0.0, 0.8), SafetyInputs(front_distance_m=None, swept_blocked=True)
    )
    assert result.level == SafetyLevel.STOP
    assert result.command.angular_z == 0.0
    assert result.reason == "swept_stop"


def test_the_path_still_stops_the_robot() -> None:
    """직사각형 안으로 들어온 것은 여전히 STOP 이다."""
    result = apply_safety_gate(
        MotionCommand(0.20, 0.0), SafetyInputs(front_distance_m=0.20)
    )
    assert result.level == SafetyLevel.STOP
    assert result.reason == "front_stop"


def test_a_keep_out_zone_says_so() -> None:
    """진입금지 구역을 `front_stop` 으로 보고하면 원인이 흐려진다."""
    result = apply_safety_gate(MotionCommand(0.20, 0.0), SafetyInputs(keep_out=True))
    assert result.level == SafetyLevel.STOP
    assert result.reason == "keep_out"


# ------------------------------------------------------- 작업 배정 판정

sys.path.insert(0, str(PINKY / "trihouse_pinky_fleet"))

from trihouse_pinky_fleet.status_node import safety_allows_work  # noqa: E402
from trihouse_interfaces.msg import SafetyState as SafetyStateMsg  # noqa: E402


def test_a_slowed_robot_still_accepts_work() -> None:
    """사람이 지나갈 때마다 작업이 멈추면 안전이 아니라 가용성 손실이다.

    2026-08-20 실측: 경고가 SLOW 를 걸자 `safety_clear=False` 로 이어져
    `dispatchable=False` 가 되었다. 정지도 아닌 상태에서 로봇이 일을 못 받았다.
    """
    assert safety_allows_work(SafetyStateMsg.STATE_CLEAR)
    assert safety_allows_work(SafetyStateMsg.STATE_SLOW)


def test_a_stopped_robot_does_not_accept_work() -> None:
    """STOP·EMERGENCY 는 실제 차단이다."""
    assert not safety_allows_work(SafetyStateMsg.STATE_STOP)
    assert not safety_allows_work(SafetyStateMsg.STATE_EMERGENCY)
