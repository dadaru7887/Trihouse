"""safety test에서도 쓸 수 있도록 ROS와 분리한 작은 geometry 함수."""
import math
from collections.abc import Sequence

# 라이다가 로봇 정면에 대해 얼마나 돌아 달려 있는가.
#
# `pinky.urdf.xacro` 의 `rplidar_link_fixed_joint` 가 `rpy="0 0 ${pi}"` 다 —
# **스캔각 0 이 로봇 뒤를 가리킨다.** 이 보정 없이 빔 각도로 정면을 고르면
# 정확히 반대쪽을 재고, 안전 gate 는 뒤쪽 벽을 보고 정면이 막혔다고 말한다.
SCAN_FORWARD_OFFSET_RAD = math.pi

# 라이다가 회전 중심(base_footprint)보다 얼마나 앞/뒤에 있는가. 음수는 뒤.
# 뒤에 있으므로 정면 장애물은 스캔이 말하는 것보다 그만큼 **가깝다**.
SCAN_ORIGIN_OFFSET_X_M = -0.017

# 보호 필드(직사각형)의 반폭. 로봇 반폭 0.06 m + 여유 0.02 m.
#
# 폭 0.20 m 통로에서 옆벽은 측면 0.10 m 에 있다. 이 값보다 크므로 통로를 지날 수
# 있다. 이 값을 키우면 통로를 한 번도 못 지난다.
PROTECTIVE_HALF_WIDTH_M = 0.08

# 회전 중심에서 로봇 앞 끝·뒤 끝까지. `nav2_params.yaml` 의 footprint 와 같아야
# 하고 `test_safety_fields_match_the_robot.py` 가 묶는다.
#
# **앞뒤가 대칭이 아니다.** 바퀴 축이 앞쪽에 치우쳐 있고 바구니가 뒤에 달린다.
# 그래서 여유를 회전 중심에서 재면 같은 숫자가 앞에서는 범퍼까지 0.26 m, 뒤에서는
# 바구니까지 0.13 m 를 뜻하게 된다. 방향마다 몸 길이를 빼야 `stop_distance_m` 이
# 앞뒤에서 같은 뜻이 된다.
FOOTPRINT_FRONT_M = 0.04
FOOTPRINT_REAR_M = 0.16

# 제자리 회전이 쓸고 지나가는 원의 반지름. 발자국에서 **파생한다** — 따로 적어
# 두면 발자국을 고쳤을 때 둘이 갈라지고, 그 갈라짐은 "회전이 막힌다" 또는
# "회전하다 벽을 친다" 로 나타나 원인에서 멀다.
SWEPT_RADIUS_M = math.hypot(max(FOOTPRINT_FRONT_M, FOOTPRINT_REAR_M), PROTECTIVE_HALF_WIDTH_M)

# 회전인지 주행인지 가르는 문턱. 원호 주행(직진 성분이 있는 회전)은 회전으로
# 보지 않는다 — 그때는 경로가 있고, 원으로 판정하면 이 방에서는 늘 막힌다.
ROTATION_LINEAR_EPSILON_MPS = 0.02
ROTATION_ANGULAR_EPSILON_RPS = 0.05


def point_in_polygon(x: float, y: float, polygon: Sequence[tuple[float, float]]) -> bool:
    """자기 교차하지 않는 polygon 안에 점이 있으면 true를 반환한다."""
    inside = False
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[index - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _base_frame_points(
    ranges: Sequence[float],
    angle_min: float,
    angle_increment: float,
    range_min: float,
    range_max: float,
    forward_offset_rad: float,
    origin_offset_x_m: float,
):
    """유효 반사를 회전 중심 기준 (전방, 측면) 으로 낸다."""
    for index, distance in enumerate(ranges):
        if not (range_min <= distance <= range_max) or not math.isfinite(distance):
            continue
        bearing = angle_min + index * angle_increment + forward_offset_rad
        yield (
            origin_offset_x_m + distance * math.cos(bearing),
            distance * math.sin(bearing),
        )


def path_clearance(
    ranges: Sequence[float],
    *,
    angle_min: float,
    angle_increment: float,
    range_min: float,
    range_max: float,
    forward_offset_rad: float = SCAN_FORWARD_OFFSET_RAD,
    origin_offset_x_m: float = SCAN_ORIGIN_OFFSET_X_M,
    half_width_m: float = PROTECTIVE_HALF_WIDTH_M,
    reverse: bool = False,
    front_extent_m: float = FOOTPRINT_FRONT_M,
    rear_extent_m: float = FOOTPRINT_REAR_M,
) -> float | None:
    """진행 방향의 보호 필드 안에서 **로봇 몸에서부터** 가장 가까운 여유. 없으면 `None`.

    필드는 진행 방향을 따라 뒤집힌다. 후진 도킹에서는 위험이 뒤에 있고, 필드가
    앞만 보면 로봇은 뒤를 못 본 채 벽으로 들어간다. 라이다는 이미 360 도를 보고
    있으므로 센서를 더할 필요는 없다 — 판정만 방향을 따라가면 된다.

    여유를 회전 중심이 아니라 **몸 끝**에서 재는 이유는 이 로봇이 앞뒤로 대칭이
    아니기 때문이다. 중심에서 재면 같은 `stop_distance_m` 이 앞에서는 범퍼까지
    0.26 m, 뒤에서는 바구니까지 0.13 m 를 뜻하게 된다.

    부채꼴이 아니라 직사각형인 이유: 폭 0.20 m 통로의 평행한 옆벽은 반각을
    아무리 좁혀도 결국 부채꼴 안으로 들어온다. 위험한지는 각도가 아니라 **옆으로
    얼마나 비껴 있는가**로 갈린다.

    `None` 과 0 m 는 다르다 — 앞의 것은 "경로가 비었다" 이고 뒤의 것은 "닿았다"
    이다. 둘을 섞으면 센서가 빠졌을 때 로봇이 그냥 달린다.
    """
    if angle_increment == 0.0:
        return None
    direction = -1.0 if reverse else 1.0
    body = rear_extent_m if reverse else front_extent_m
    nearest: float | None = None
    for forward, lateral in _base_frame_points(
        ranges, angle_min, angle_increment, range_min, range_max,
        forward_offset_rad, origin_offset_x_m,
    ):
        along = forward * direction
        if along <= 0.0 or abs(lateral) > half_width_m:
            continue
        # 이미 몸에 닿은 것은 음수가 아니라 0 이다. 음수 여유는 뜻이 없고
        # `<= stop_distance_m` 비교를 조용히 통과할 수도 있다.
        clearance = max(0.0, along - body)
        if nearest is None or clearance < nearest:
            nearest = clearance
    return nearest


def nearest_range(
    ranges: Sequence[float],
    *,
    angle_min: float,
    angle_increment: float,
    range_min: float,
    range_max: float,
    forward_offset_rad: float = SCAN_FORWARD_OFFSET_RAD,
    origin_offset_x_m: float = SCAN_ORIGIN_OFFSET_X_M,
) -> float | None:
    """방향과 무관한 최단 거리. 경고 필드(SLOW)와 회전 판정에 쓴다.

    경로 밖에 선 사람을 잡는 것이 이 값이다. 보호 필드가 직사각형이 되면서
    잃은 옆쪽 시야를 여기서 되찾되, 동작은 STOP 이 아니라 SLOW 다.
    """
    if angle_increment == 0.0:
        return None
    nearest: float | None = None
    for forward, lateral in _base_frame_points(
        ranges, angle_min, angle_increment, range_min, range_max,
        forward_offset_rad, origin_offset_x_m,
    ):
        distance = math.hypot(forward, lateral)
        if nearest is None or distance < nearest:
            nearest = distance
    return nearest


def rotating_in_place(
    linear_x: float,
    angular_z: float,
    *,
    linear_epsilon: float = ROTATION_LINEAR_EPSILON_MPS,
    angular_epsilon: float = ROTATION_ANGULAR_EPSILON_RPS,
) -> bool:
    """명령이 제자리 회전인가. 그렇다면 보호 필드는 직사각형이 아니라 원이다.

    원호 주행은 회전으로 보지 않는다. 2.20 x 2.70 m 방에서 원 판정을 상시로 쓰면
    벽이 늘 외접반경 안에 있어 로봇이 아예 움직이지 못한다. 그 대신 원호에서는
    경고 필드가 속도를 낮춰 제동 거리를 짧게 만든다.
    """
    return abs(linear_x) <= linear_epsilon and abs(angular_z) > angular_epsilon


def swept_clearance_blocked(nearby_m: float, clearance_m: float) -> bool:
    """회전 외접원 경계도 충돌 영역에 포함한다."""
    return nearby_m <= clearance_m
