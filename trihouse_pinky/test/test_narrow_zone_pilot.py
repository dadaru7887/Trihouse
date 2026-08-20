"""협로 규칙 주행의 계약.

되먹임이 없는 주행이라 순서와 중단 조건이 전부다. 실물에서 잘못 돌면 로봇이 벽에
박히므로, ROS 없이 확인할 수 있는 것은 전부 여기서 확인한다.
"""

import math
import sys
from pathlib import Path

import pytest
import yaml

PINKY = Path(__file__).resolve().parents[1]
REPOSITORY = PINKY.parent
sys.path.insert(0, str(PINKY / "trihouse_pinky_fleet"))

from trihouse_pinky_fleet.narrow_zone_pilot import (  # noqa: E402
    EXIT_ZONE,
    NarrowZoneError,
    NarrowZonePlan,
    ROTATE,
    STRAIGHT,
    ZoneGeometry,
    load_zones,
    select_zone,
    step_velocity,
    verify_pose,
    zone_containing,
)

ZONE_FILE = REPOSITORY / "config" / "narrow_zones.trihouse_map_01.yaml"
FROZEN = "frozen_storage_loading_dock_01"


def _zones():
    document = yaml.safe_load(ZONE_FILE.read_text(encoding="utf-8"))
    return load_zones(document, map_name="trihouse_map_01")


def test_the_shipped_zone_table_loads_and_covers_three_docks() -> None:
    zones = _zones()
    assert set(zones) == {
        "ambient_storage_loading_dock_01",
        "chilled_storage_loading_dock_01",
        FROZEN,
    }
    frozen = zones[FROZEN]
    # 원본 narrow_3 은 [직진 -> 회전 -> 후진] 3단계로 실측 확정된 것이다.
    assert [kind for kind, _ in frozen.enter] == [STRAIGHT, ROTATE, STRAIGHT]
    assert frozen.enter[-1][1] < 0, "도크 진입은 후진이어야 바구니가 안쪽을 향한다"
    assert frozen.exit[-1][0] == EXIT_ZONE


def test_a_zone_table_for_another_map_is_refused() -> None:
    """값이 지도 좌표계에 묶여 있다. 다른 지도에서 쓰면 엉뚱한 자리에서 후진한다."""
    document = yaml.safe_load(ZONE_FILE.read_text(encoding="utf-8"))
    with pytest.raises(NarrowZoneError, match="지도"):
        load_zones(document, map_name="new_map_2")


def test_the_zone_rectangle_is_oriented_not_circular() -> None:
    """좁고 긴 통로에는 원이 맞지 않는다. 진행축으로 정렬해야 실제 여유와 맞는다."""
    geometry = ZoneGeometry(x=0.0, y=0.0, yaw=0.0, length=0.10, width=0.20)
    assert geometry.contains(0.04, 0.0)      # 진행축으로 4 cm — 안
    assert not geometry.contains(0.08, 0.0)  # 8 cm — 밖 (length/2 = 5 cm)
    assert geometry.contains(0.0, 0.09)      # 폭 방향 9 cm — 안
    assert not geometry.contains(0.0, 0.12)  # 12 cm — 밖


def test_a_rotated_zone_follows_its_own_axis() -> None:
    geometry = ZoneGeometry(x=0.0, y=0.0, yaw=math.pi / 2, length=0.10, width=0.20)
    assert geometry.contains(0.0, 0.04)      # 이제 진행축이 y 다
    assert not geometry.contains(0.0, 0.08)
    assert geometry.contains(0.09, 0.0)


def test_only_a_registered_destination_uses_the_rule_based_path() -> None:
    zones = _zones()
    assert select_zone(zones, FROZEN) is not None
    # 포장대는 통로가 넓다. Nav2 가 끝까지 간다.
    assert select_zone(zones, "packing_station_loading_dock_01") is None


def test_the_robot_knows_which_zone_it_is_stuck_in() -> None:
    """이 판정이 없어서 2026-08-19 에 로봇이 냉동창고에서 나오지 못했다."""
    zones = _zones()
    frozen = zones[FROZEN]
    inside = zone_containing(zones, frozen.geometry.x, frozen.geometry.y)
    assert inside is not None and inside.destination_code == FROZEN
    assert zone_containing(zones, 0.0, 0.0) is None


def test_the_plan_hands_out_steps_in_order_and_then_stops() -> None:
    plan = NarrowZonePlan(_zones()[FROZEN], leaving=False)
    kinds = []
    while not plan.done:
        kind, _ = plan.next_step()
        kinds.append(kind)
    assert kinds == [STRAIGHT, ROTATE, STRAIGHT]
    with pytest.raises(NarrowZoneError):
        plan.next_step()


def test_rotation_stops_inside_tolerance_and_turns_the_short_way() -> None:
    common = dict(
        max_linear=0.06, max_angular=0.5, yaw_tolerance=0.05, position_tolerance=0.02
    )
    # 이미 맞으면 멈춘다.
    assert step_velocity(ROTATE, 1.0, (0, 0, 1.02), (0, 0, 0), **common) == (0.0, 0.0, True)
    # -3.0 에서 3.0 으로 갈 때 짧은 쪽은 음의 방향이다. 긴 쪽으로 돌면 벽을 친다.
    _, angular, done = step_velocity(ROTATE, 3.0, (0, 0, -3.0), (0, 0, 0), **common)
    assert not done and angular < 0


def test_a_negative_distance_drives_backward() -> None:
    common = dict(
        max_linear=0.06, max_angular=0.5, yaw_tolerance=0.05, position_tolerance=0.02
    )
    linear, _, done = step_velocity(STRAIGHT, -0.315, (0, 0, 0), (0, 0, 0), **common)
    assert linear < 0 and not done
    # 목표 거리만큼 갔으면 멈춘다. 방향과 무관하게 이동한 거리로 판정한다.
    assert step_velocity(
        STRAIGHT, -0.315, (-0.315, 0, 0), (0, 0, 0), **common
    ) == (0.0, 0.0, True)


def test_exit_zone_drives_until_it_leaves_the_rectangle() -> None:
    geometry = ZoneGeometry(x=0.0, y=0.0, yaw=0.0, length=0.10, width=0.20)
    common = dict(
        max_linear=0.06, max_angular=0.5, yaw_tolerance=0.05,
        position_tolerance=0.02, zone=geometry,
    )
    linear, _, done = step_velocity(EXIT_ZONE, None, (0.0, 0.0, 0.0), (0, 0, 0), **common)
    assert linear > 0 and not done
    assert step_velocity(
        EXIT_ZONE, None, (0.30, 0.0, 0.0), (0, 0, 0), **common
    ) == (0.0, 0.0, True)


def test_the_final_pose_is_checked_against_the_dock() -> None:
    """규칙 주행에는 되먹임이 없다. 시퀀스가 "다 했다" 고 해도 그 자리가 도크인지는
    따로 봐야 한다 — 바구니가 로봇팔에 닿는지를 판정하는 유일한 근거다."""
    dock = (1.201, -0.799, -1.408)
    ok, distance, yaw_error = verify_pose(
        (1.205, -0.795, -1.400), dock, xy_tolerance_m=0.15, yaw_tolerance_rad=0.35
    )
    assert ok and distance < 0.01

    # 자리는 맞는데 방향이 반대면 바구니가 반대쪽을 본다. 통과시키면 안 된다.
    ok, _, yaw_error = verify_pose(
        (1.201, -0.799, -1.408 + math.pi), dock,
        xy_tolerance_m=0.15, yaw_tolerance_rad=0.35,
    )
    assert not ok and yaw_error > 3.0


def test_an_empty_sequence_is_refused_rather_than_silently_skipped() -> None:
    zones = _zones()
    broken = zones[FROZEN].__class__(
        destination_code=FROZEN,
        geometry=zones[FROZEN].geometry,
        enter=(),
        exit=zones[FROZEN].exit,
        measured={},
    )
    with pytest.raises(NarrowZoneError, match="비어 있다"):
        NarrowZonePlan(broken, leaving=False)


# --- 존 표가 그 지도에서 실제로 성립하는가 -------------------------------------
#
# 2026-08-19 에 `trihouse_map_01` 용 표를 `new_map_2` 에서 돌려 로봇이 사이클을 못
# 돌았다. 좌표는 지도 좌표계에 묶여 있는데 지도만 바뀌었기 때문이다. 그때 냉동 도크의
# 벽 여유는 0.03 m 였고 로봇 폭은 0.12 m 였다 — 애초에 들어갈 수 없는 자리였다.
# 아래 검사는 **표에 적힌 자리에 로봇이 설 수 있는지**를 지도 격자로 직접 확인한다.

MAPS = REPOSITORY / "control_ui" / "rmf_control_ui" / "data" / "rmf_maps"
INSCRIBED_RADIUS_M = 0.04          # 발자국 원점에서 가장 가까운 변까지. 이보다 좁으면 치명.
STAND_CLEARANCE_M = 0.07           # 그 위에 여유를 둔 실사용 하한.

# 그 지도에서는 못 쓰지만 좌표 자체는 실측이라 지우지 않은 것들.
KNOWN_UNUSABLE = {
    ("trihouse_map_01", "chilled_storage_loading_dock_01"):
        "진입점 여유 0.05 m, 도크까지 최선 통로 0.10 m. 로봇 폭 0.12 m 가 안 들어간다.",
}


def _occupancy(map_name):
    """지도 하나를 읽어 (자유 여부, 벽까지 거리 m) 를 돌려준다."""
    Image = pytest.importorskip("PIL.Image", reason="Pillow 없이는 지도를 못 읽는다")
    from collections import deque

    meta = yaml.safe_load((MAPS / f"{map_name}.yaml").read_text(encoding="utf-8"))
    image = Image.open(MAPS / meta["image"]).convert("L")
    width, height = image.size
    pixels = list(image.getdata())
    resolution = float(meta["resolution"])
    origin_x, origin_y = (float(v) for v in meta["origin"][:2])
    free = [[pixels[r * width + c] > 200 for c in range(width)] for r in range(height)]

    far = 10 ** 6
    distance = [[0 if not free[r][c] else far for c in range(width)] for r in range(height)]
    queue = deque((r, c) for r in range(height) for c in range(width) if not free[r][c])
    while queue:
        r, c = queue.popleft()
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < height and 0 <= nc < width and distance[nr][nc] > distance[r][c] + 1:
                distance[nr][nc] = distance[r][c] + 1
                queue.append((nr, nc))

    def clearance(x, y):
        c = int((x - origin_x) / resolution)
        r = height - 1 - int((y - origin_y) / resolution)
        if not (0 <= r < height and 0 <= c < width):
            return None                      # 지도 밖. 계획기가 모든 경로를 거절한다.
        return distance[r][c] * resolution

    return clearance


def _apply(steps, x, y, yaw):
    """시퀀스를 그대로 적분해 끝나는 자리를 구한다. 되먹임 없는 주행이므로 이것이 예상 자리다."""
    for kind, value in steps:
        if kind == ROTATE:
            yaw = value
        elif kind == STRAIGHT:
            x += value * math.cos(yaw)
            y += value * math.sin(yaw)
    return x, y, yaw


@pytest.mark.parametrize("zone_file", sorted((REPOSITORY / "config").glob("narrow_zones.*.yaml")))
def test_every_shipped_zone_table_fits_its_own_map(zone_file) -> None:
    map_name = zone_file.name[len("narrow_zones.") : -len(".yaml")]
    document = yaml.safe_load(zone_file.read_text(encoding="utf-8"))
    assert document["map_name"] == map_name, "파일 이름과 map_name 이 갈라지면 아무도 못 알아챈다"
    if not (MAPS / f"{map_name}.yaml").is_file():
        pytest.skip(f"{map_name} 지도가 저장소에 없다")

    clearance = _occupancy(map_name)
    for name, zone in load_zones(document, map_name=map_name).items():
        entry = clearance(zone.geometry.x, zone.geometry.y)
        assert entry is not None, f"{name}: 진입점이 지도 밖이다"
        if (map_name, name) in KNOWN_UNUSABLE:
            # 좌표는 실측이라 지우지 않는다. 대신 "여전히 못 쓴다"는 사실을 못 박아,
            # 지도를 다시 그려 쓸 만해지면 이 검사가 실패해 목록을 지우게 만든다.
            assert entry < STAND_CLEARANCE_M, (
                f"{name}: 이제 쓸 수 있게 됐다(여유 {entry:.2f} m). "
                f"KNOWN_UNUSABLE 에서 빼라 — {KNOWN_UNUSABLE[(map_name, name)]}"
            )
            continue
        assert entry >= STAND_CLEARANCE_M, (
            f"{name}: 진입점 여유 {entry:.2f} m — 로봇이 설 수 없다"
        )
        x, y, _ = _apply(zone.enter, zone.geometry.x, zone.geometry.y, zone.geometry.yaw)
        dock = clearance(x, y)
        assert dock is not None, f"{name}: enter 시퀀스가 지도 밖으로 나간다"
        assert dock >= INSCRIBED_RADIUS_M, (
            f"{name}: enter 시퀀스 끝({x:.3f}, {y:.3f}) 여유 {dock:.2f} m — 발자국이 벽에 박힌다"
        )
        assert zone.geometry.contains(x, y), (
            f"{name}: 도크가 존 직사각형 밖이다. 그러면 다음 명령 때 빠져나오기가 안 돈다"
        )
