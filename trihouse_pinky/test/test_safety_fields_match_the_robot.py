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

import pytest
import yaml

PINKY = Path(__file__).resolve().parents[1]
REPOSITORY = PINKY.parent
URDF = REPOSITORY / "pinky_pro" / "pinky_description" / "urdf" / "pinky.urdf.xacro"
NAV2_PARAMS = (
    REPOSITORY
    / "pinky_pro_alpha"
    / "pinky_navigation"
    / "params"
    / "nav2_params.yaml"
)

sys.path.insert(0, str(PINKY / "trihouse_pinky_safety"))

from trihouse_pinky_safety.geometry import (  # noqa: E402
    FOOTPRINT_FRONT_M,
    FOOTPRINT_REAR_M,
    PROTECTIVE_HALF_WIDTH_M,
    SCAN_FORWARD_OFFSET_RAD,
    SCAN_ORIGIN_OFFSET_X_M,
    SWEPT_CONTACT_M,
    SWEPT_RADIUS_M,
    nearest_range,
    path_clearance,
    rotating_in_place,
    swept_clearance_blocked,
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


def _nav2_footprint() -> tuple[float, float, float]:
    """벤더 params 의 발자국에서 (앞, 뒤, 반폭) 을 읽는다. 뒤는 크기다."""
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
    corners = [
        tuple(float(v) for v in pair.split(","))
        for text in footprints
        for pair in text.strip()[2:-2].split("], [")
    ]
    return (
        max(x for x, _ in corners),
        -min(x for x, _ in corners),
        max(abs(y) for _, y in corners),
    )


def test_the_safety_footprint_matches_the_nav2_footprint() -> None:
    """안전 gate 와 Nav2 가 **같은 몸**을 봐야 한다.

    둘이 갈라지면 Nav2 가 낸 회전을 gate 가 거절하거나(주행 불가), gate 가
    통과시킨 회전에서 로봇이 벽을 친다. 앞뒤를 따로 묶는 이유는 이 로봇이
    앞뒤로 대칭이 아니기 때문이다 — 바퀴 축이 앞쪽에 치우쳐 있고 바구니가 뒤에
    달린다. 후진 여유를 앞 기준으로 재면 실제보다 13 cm 넉넉하게 나온다.
    """
    if not NAV2_PARAMS.exists():
        return
    front, rear, half_width = _nav2_footprint()
    assert abs(front - FOOTPRINT_FRONT_M) < 5e-3, (
        f"Nav2 발자국의 앞 끝은 {front:.4f} m 인데 "
        f"FOOTPRINT_FRONT_M 는 {FOOTPRINT_FRONT_M:.4f} m 다"
    )
    assert abs(rear - FOOTPRINT_REAR_M) < 5e-3, (
        f"Nav2 발자국의 뒤 끝은 {rear:.4f} m 인데 "
        f"FOOTPRINT_REAR_M 는 {FOOTPRINT_REAR_M:.4f} m 다"
    )
    assert PROTECTIVE_HALF_WIDTH_M >= half_width, (
        f"보호 필드 반폭 {PROTECTIVE_HALF_WIDTH_M} m 가 발자국 반폭 "
        f"{half_width} m 보다 좁다 — 몸이 지나가는 자리를 안 본다"
    )


def test_the_swept_radius_is_derived_not_maintained_by_hand() -> None:
    """회전 원은 발자국에서 나온다. 따로 적어 두면 둘이 갈라진다."""
    assert SWEPT_RADIUS_M == pytest.approx(
        math.hypot(max(FOOTPRINT_FRONT_M, FOOTPRINT_REAR_M), PROTECTIVE_HALF_WIDTH_M)
    )


@pytest.mark.parametrize(
    ("nearby", "expected"),
    [
        (SWEPT_RADIUS_M - 0.001, True),
        (SWEPT_RADIUS_M, True),
        (SWEPT_RADIUS_M + 0.001, False),
    ],
)
def test_swept_clearance_boundary(nearby: float, expected: bool) -> None:
    assert swept_clearance_blocked(nearby, SWEPT_RADIUS_M) is expected


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


def test_an_obstacle_behind_the_robot_is_not_on_the_forward_path() -> None:
    """뒤쪽 벽이 전진을 막으면 로봇은 영원히 못 움직인다."""
    assert path_clearance(**_scan({180.0: 0.30})) is None


def test_an_obstacle_ahead_is_not_on_the_reverse_path() -> None:
    """후진할 때 앞쪽 벽은 멀어지는 방향이다."""
    assert path_clearance(**_scan({0.0: 0.30}), reverse=True) is None


def test_the_field_flips_with_the_direction_of_travel() -> None:
    """같은 장애물이 전진에는 위험하고 후진에는 아니다. 그 반대도 같다.

    후진 도킹을 넣으면 위험은 뒤에 있다. 필드가 앞만 보면 로봇은 뒤를 못 보고
    벽으로 들어간다 — 라이다는 이미 360 도를 보고 있고 판정만 앞을 보고 있었다.
    """
    ahead = _scan({0.0: 0.30})
    behind = _scan({180.0: 0.30})
    assert path_clearance(**ahead) is not None
    assert path_clearance(**ahead, reverse=True) is None
    assert path_clearance(**behind) is None
    assert path_clearance(**behind, reverse=True) is not None


def test_clearance_is_measured_from_the_robot_edge_not_its_centre() -> None:
    """`stop_distance_m` 이 앞뒤에서 같은 뜻이어야 한다.

    회전 중심에서 재면 앞은 범퍼에서 0.26 m, 뒤는 바구니에서 0.13 m 가 되어
    같은 숫자가 방향마다 다른 안전 여유를 뜻하게 된다. 로봇이 뒤로 훨씬
    길기 때문이다.
    """
    ahead = path_clearance(**_scan({0.0: 0.30}))
    behind = path_clearance(**_scan({180.0: 0.30}), reverse=True)
    assert abs(ahead - (0.30 - FOOTPRINT_FRONT_M)) < 1e-3
    assert abs(behind - (0.30 - FOOTPRINT_REAR_M)) < 1e-3
    assert behind < ahead, "로봇이 뒤로 더 길므로 같은 벽이 뒤에서 더 가깝다"


def test_something_already_touching_the_robot_reads_zero_not_negative() -> None:
    """음수 여유는 뜻이 없고, 비교 연산에서 조용히 통과할 수 있다."""
    touching = path_clearance(**_scan({180.0: 0.10}), reverse=True)
    assert touching == 0.0


def test_a_wall_alongside_a_narrow_corridor_is_not_on_the_path() -> None:
    """폭 0.20 m 통로의 옆벽은 측면 0.10 m 다. 로봇 반폭 밖이라 스쳐 지나간다.

    이것이 STOP 을 걸면 통로를 한 번도 지날 수 없다. 부채꼴로는 반각을 아무리
    좁혀도 평행한 옆벽이 결국 들어온다 — 그래서 직사각형이어야 한다.
    """
    lateral, forward = 0.10, 0.25
    bearing = math.degrees(math.atan2(lateral, forward))
    assert path_clearance(**_scan({bearing: math.hypot(lateral, forward)})) is None
    assert path_clearance(**_scan({-bearing: math.hypot(lateral, forward)})) is None


def test_the_reverse_corridor_is_the_same_width() -> None:
    """후진해서 도크에 들어갈 때도 옆벽은 스치는 것이지 부딪히는 것이 아니다."""
    lateral, behind = 0.10, 0.25
    bearing = 180.0 - math.degrees(math.atan2(lateral, behind))
    assert path_clearance(**_scan({bearing: math.hypot(lateral, behind)}), reverse=True) is None


def test_something_inside_the_robot_width_is_on_the_path() -> None:
    """반폭 안쪽으로 들어오면 정면이 아니어도 부딪힌다."""
    lateral, forward = PROTECTIVE_HALF_WIDTH_M - 0.01, 0.20
    bearing = math.degrees(math.atan2(lateral, forward))
    distance = path_clearance(**_scan({bearing: math.hypot(lateral, forward)}))
    assert distance is not None and abs(distance - (forward - FOOTPRINT_FRONT_M)) < 1e-3


def test_the_scan_origin_offset_brings_obstacles_closer() -> None:
    """라이다가 뒤에 있으므로 회전 중심에서 잰 거리는 더 짧다."""
    plain = _scan({0.0: 0.30})
    plain["origin_offset_x_m"] = SCAN_ORIGIN_OFFSET_X_M
    expected = 0.30 + SCAN_ORIGIN_OFFSET_X_M - FOOTPRINT_FRONT_M
    assert abs(path_clearance(**plain) - expected) < 1e-3


def test_readings_outside_the_sensor_range_are_discarded() -> None:
    """`inf` 나 0 은 측정이 아니다. 그것을 최솟값으로 쓰면 없는 벽이 생긴다."""
    assert path_clearance(**_scan({0.0: float("inf"), 1.0: 0.40})) is not None
    assert path_clearance(**_scan({0.0: 0.0, 1.0: 0.40})) is not None


def test_an_empty_path_gives_none() -> None:
    """측정이 없는 것과 0 m 는 다르다. gate 는 그 둘을 구분해야 한다."""
    empty = _scan({})
    empty["ranges"] = [float("inf")] * len(empty["ranges"])
    assert path_clearance(**empty) is None


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


def test_distance_alone_no_longer_slows_the_robot() -> None:
    """거리 기반 감속은 Nav2 가 맡는다. 여기서 또 하면 감속이 3 중이 된다.

    Nav2 는 costmap 위에서 `use_cost_regulated_linear_velocity_scaling`
    (cost_scaling_dist 0.6) 과 `approach_velocity_scaling_dist`(0.6) 두 개를
    이미 돌리고 있다. 2.20 x 2.70 m 방에서는 어느 지점이든 목적지 또는 장애물의
    0.6 m 안이라 셋이 항상 동시에 걸리고, `desired_linear_vel: 0.2` 가 실제로는
    0.05~0.08 로 떨어진다.

    이 게이트가 거리로 하는 일은 이제 **STOP 하나뿐**이다 — 예고 없이 선다.
    그 예고는 Nav2 쪽 감속이 대신한다.
    """
    result = apply_safety_gate(
        MotionCommand(0.12, 0.0), SafetyInputs(front_distance_m=0.50)
    )
    assert result.level == SafetyLevel.CLEAR
    assert result.command.linear_x == 0.12


def test_a_person_far_away_does_not_slow_the_robot() -> None:
    """감속의 근거는 "사람이 있다" 가 아니라 "사람이 가까이 있다" 다.

    이전에는 `person_detected or (거리 <= 임계)` 라 `or` 이 거리 조건을 무력화했고,
    방 반대편 참관자나 신뢰도 0.01 짜리 오검출까지 감속을 걸었다. 운영 테스트는
    사람이 옆에서 지켜보므로 그대로 상시 감속이 된다.
    """
    far = SafetyConfig().person_protective_distance_m + 0.5
    result = apply_safety_gate(
        MotionCommand(0.12, 0.0),
        SafetyInputs(person_detected=True, person_distance_m=far),
    )
    assert result.level == SafetyLevel.CLEAR


def test_a_person_at_an_unknown_distance_still_slows_the_robot() -> None:
    """거리를 모르는 것을 안전하다고 읽으면 안 된다."""
    result = apply_safety_gate(
        MotionCommand(0.12, 0.0),
        SafetyInputs(person_detected=True, person_distance_m=None),
    )
    assert result.level == SafetyLevel.SLOW


def test_reversing_is_slowed_too() -> None:
    """`min(-0.20, 0.08)` 은 -0.20 을 그대로 통과시킨다.

    부호는 진행 방향이고 상한은 빠르기다. 둘을 한 번에 `min` 으로 처리하면
    **후진에서는 감속이 아예 걸리지 않는다.**
    """
    limit = SafetyConfig().slow_linear_speed_mps
    result = apply_safety_gate(
        MotionCommand(-0.20, 0.0),
        SafetyInputs(person_detected=True, person_distance_m=0.5),
    )
    assert result.level == SafetyLevel.SLOW
    assert result.command.linear_x == -limit, "후진이 감속되지 않았다"


def test_slowing_never_speeds_the_robot_up() -> None:
    """상한은 상한이다. 원 명령이 이미 느리면 그대로 둔다."""
    result = apply_safety_gate(
        MotionCommand(0.03, 0.0),
        SafetyInputs(person_detected=True, person_distance_m=0.5),
    )
    assert result.command.linear_x == 0.03


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
        MotionCommand(0.20, 0.0), SafetyInputs(front_distance_m=0.04)
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


# ------------------------------------------------- 후진 시 센서 근거

import inspect  # noqa: E402

from trihouse_pinky_safety.safety_supervisor_node import SafetySupervisor  # noqa: E402

PATH_DISTANCE = inspect.getsource(SafetySupervisor._path_distance)
ON_SCAN = inspect.getsource(SafetySupervisor._on_scan)
SUPERVISOR_INIT = inspect.getsource(SafetySupervisor.__init__)


def test_supervisor_defaults_to_the_contact_threshold_not_the_swept_radius() -> None:
    """회전 충돌 방지는 Nav2 가 맡고, 여기 남은 것은 접촉 감지다.

    두 계층이 같은 판정을 하면 더 안전해지지 않고, 어긋날 때만 교착이 생긴다.
    2026-08-24 실측: 협로 탈출부에서 `swept_stop` 과 `front_stop` 이 110 초 동안
    24 회 번갈아 나오는 사이 자세가 0.1 도도 바뀌지 않았다.

    문턱을 **값으로 적지 않고 이름으로 묶는** 이유는, 두 상수가 서로 다른 것을
    뜻하기 때문이다 — `SWEPT_RADIUS_M` 은 발자국에서 나오는 물리량이고,
    `SWEPT_CONTACT_M` 은 그보다 낮게 **의도적으로** 정한 운영값이다.
    """
    assert "'swept_clearance_m', SWEPT_CONTACT_M)" in SUPERVISOR_INIT
    assert "'swept_clearance_m', SWEPT_RADIUS_M)" not in SUPERVISOR_INIT
    assert "SWEPT_CONTACT_M +" not in SUPERVISOR_INIT


def test_the_contact_threshold_separates_a_wall_from_a_dragged_cable() -> None:
    """운영값은 2026-08-24 실측 세 값 사이에서만 뜻이 있다.

    벽(0.176)을 잡으면 회전이 영구히 막히고, 케이블(0.088)을 놓치면 그것을 감고
    돈다. 이 시험이 지키는 것은 숫자가 아니라 **그 사이에 있다**는 사실이다.
    """
    wall, cable, charger = 0.176, 0.088, 0.036
    assert not swept_clearance_blocked(wall, SWEPT_CONTACT_M), "정상 벽에서 회전이 막힌다"
    assert swept_clearance_blocked(cable, SWEPT_CONTACT_M), "끌려 나온 케이블을 놓친다"
    assert swept_clearance_blocked(charger, SWEPT_CONTACT_M)
    # 라이다 잡음(RPLidar +-1~2 cm)을 견디려면 양쪽으로 여유가 필요하다.
    assert wall - SWEPT_CONTACT_M >= 0.03, "벽까지 여유가 잡음보다 작다"
    assert SWEPT_CONTACT_M - cable >= 0.03, "케이블까지 여유가 잡음보다 작다"


def test_the_contact_threshold_is_a_deliberate_concession() -> None:
    """접촉 방지를 포기한 폭을 코드가 스스로 말하게 한다.

    이 값이 `SWEPT_RADIUS_M` 이상이 되면 Nav2 와 다시 이중이 되고, 지나치게
    낮아지면 접촉 감지라는 이름값도 못 한다.
    """
    assert SWEPT_CONTACT_M < SWEPT_RADIUS_M
    assert SWEPT_RADIUS_M - SWEPT_CONTACT_M < 0.08, (
        f"포기한 폭이 {SWEPT_RADIUS_M - SWEPT_CONTACT_M:.3f} m 다 — "
        "회전 접촉을 사실상 감지하지 못한다"
    )


def test_the_ultrasonic_is_not_used_as_evidence_when_reversing() -> None:
    """초음파는 정면(`ultrasonic_link`)만 본다. 후진 근거가 되지 못한다.

    섞으면 뒤가 막혔는데 초음파의 "정면 3 m" 가 최솟값 경쟁에서 이겨 gate 를
    통과해 버린다. 시뮬의 `sim_hardware` 는 실제로 3.0 m 상수를 낸다.
    """
    assert "if not reversing and self.front_range" in PATH_DISTANCE


def test_the_direction_comes_from_the_command_not_the_scan() -> None:
    """스캔이 올 때는 어느 쪽으로 갈지 모른다. 명령이 정한다."""
    assert "commanded_linear_x < 0.0" in PATH_DISTANCE
    assert "reverse=False" in ON_SCAN and "reverse=True" in ON_SCAN


def test_in_place_rotation_uses_only_the_swept_clearance_field() -> None:
    """제자리 회전에 전진 정지거리를 겹치면 안전한 회전도 영구 정지한다."""
    assert "rotating_in_place(commanded_linear_x, commanded_angular_z)" in PATH_DISTANCE


def test_both_directions_are_measured_from_one_scan() -> None:
    """스캔 한 번에 두 방향을 다 재 둔다. 명령마다 다시 훑지 않는다."""
    assert "self.forward_clearance" in ON_SCAN and "self.reverse_clearance" in ON_SCAN
