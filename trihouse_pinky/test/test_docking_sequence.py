"""좁은 도크에 후진으로 들어가는 규칙 기반 시퀀스.

## 왜 규칙인가

Nav2 의 RPP 로는 못 들어간다. `allow_reversing` 은 전역 경로에 이미 방향 전환점이
있을 때만 쓸모가 있는데 NavFn 은 그런 경로를 만들지 않고, `use_rotate_to_heading`
과는 동시에 켤 수도 없다. 그리고 애초에 냉동 도크 통로는 0.20 m 이고 로봇 회전
지름은 0.34 m 라 **통로 안에서 도는 것 자체가 불가능**하다.

풀이는 회전과 후진을 나누는 것이다 — 넓은 곳에서 돌고, 좁은 통로는 곧게 후진으로
들어간다. 후진에는 회전 원이 필요 없고 로봇 폭만 필요하다.

## 무엇이 달라졌나

원본 `narrow3_rule_based_docking.py` 는 `/cmd_vel` 을 직접 쐈다. 충돌 감지가 없어
*"반드시 사람이 로봇 옆에서 지켜보다가 이상하면 Ctrl+C"* 를 전제했다. 여기서는
`cmd_vel_dock` 으로 내보내 `safety_supervisor` 아래로 들어간다 — 사람이 지켜보던
자리를 안전 gate 가 대신한다.
"""

import math
import sys
from pathlib import Path

import pytest

PINKY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PINKY / "trihouse_pinky_docking"))

from trihouse_pinky_docking.sequence import (  # noqa: E402
    DockSequence,
    DockStep,
    SequenceLimits,
    in_oriented_zone,
)

LIMITS = SequenceLimits()


def _sequence(*steps: DockStep) -> DockSequence:
    return DockSequence(steps, LIMITS)


# ------------------------------------------------------------ 진입 판정


ZONE = {"cx": 0.92, "cy": -1.19, "yaw": -0.032, "length": 0.10, "width": 0.20}


def test_the_zone_is_an_oriented_rectangle_not_a_circle() -> None:
    """통로 진입은 방향이 정해진 좁고 긴 형태다. 원으로 잡으면 옆에서도 걸린다.

    병목(mutex) 구역이 원인 것과 성격이 다르다 — 그쪽은 방향과 무관하다.
    """
    assert in_oriented_zone(0.92, -1.19, ZONE)
    # 통로 축을 따라 6 cm (길이 반 0.05 밖)
    assert not in_oriented_zone(0.92 + 0.06, -1.19, ZONE)
    # 통로에 수직으로 6 cm (폭 반 0.10 안)
    assert in_oriented_zone(0.92, -1.19 + 0.06, ZONE)


def test_a_robot_outside_the_zone_does_not_start_the_sequence() -> None:
    """Nav2 가 아직 데려다주지 못했는데 시작하면 엉뚱한 곳에서 후진한다."""
    sequence = _sequence(DockStep("straight", 0.10))
    assert sequence.begin(x=0.0, y=0.0, yaw=0.0, zone=ZONE) is False
    assert sequence.begin(x=0.92, y=-1.19, yaw=-0.032, zone=ZONE) is True


# ------------------------------------------------------------ 회전 단계


def test_rotation_turns_the_shorter_way() -> None:
    """+179 도에서 -170 도로 가는 짧은 길은 11 도다. 접지 않으면 349 도를 돈다.

    좁은 통로 입구에서 한 바퀴를 돌면 그 자체로 벽을 친다.
    """
    sequence = _sequence(DockStep("rotate", math.radians(-170)))
    sequence.begin(x=0.92, y=-1.19, yaw=math.radians(179), zone=ZONE)
    command = sequence.advance(x=0.92, y=-1.19, yaw=math.radians(179))
    assert command.angular_z > 0, "짧은 쪽(양의 방향, 11 도)으로 돌아야 한다"
    assert abs(command.angular_z) <= LIMITS.max_angular_rps


def test_rotation_has_no_linear_component() -> None:
    """제자리 회전이 아니면 좁은 통로 입구에서 옆으로 밀린다."""
    sequence = _sequence(DockStep("rotate", 1.0))
    sequence.begin(x=0.92, y=-1.19, yaw=0.0, zone=ZONE)
    assert sequence.advance(x=0.92, y=-1.19, yaw=0.0).linear_x == 0.0


def test_rotation_finishes_within_tolerance_and_moves_on() -> None:
    sequence = _sequence(DockStep("rotate", 1.0), DockStep("straight", -0.30))
    sequence.begin(x=0.92, y=-1.19, yaw=0.0, zone=ZONE)
    sequence.advance(x=0.92, y=-1.19, yaw=0.0)
    sequence.advance(x=0.92, y=-1.19, yaw=1.0)
    assert sequence.step_index == 1, "허용오차 안에 들어오면 다음 단계로 넘어간다"


# ------------------------------------------------------------ 직진/후진


def test_a_negative_distance_drives_backwards() -> None:
    """도크 진입은 후진이다. 부호가 방향이다."""
    sequence = _sequence(DockStep("straight", -0.30))
    sequence.begin(x=0.92, y=-1.19, yaw=0.0, zone=ZONE)
    assert sequence.advance(x=0.92, y=-1.19, yaw=0.0).linear_x < 0


def test_travel_is_measured_by_distance_not_by_time() -> None:
    """시간이 흘러도 안 움직였으면 안 간 것이다.

    `safety_supervisor` 는 사람이 가까우면 0.08 m/s 로 낮추고, 보호 필드가
    걸리면 0 으로 만든다. 시간으로 재면 그동안 거리가 줄어든 것으로 착각해
    도크에 닿기 전에 끝난다.
    """
    sequence = _sequence(DockStep("straight", -0.30))
    sequence.begin(x=0.92, y=-1.19, yaw=0.0, zone=ZONE, now_s=0.0)
    assert sequence.advance(x=0.92, y=-1.19, yaw=0.0, now_s=0.0).linear_x < 0
    # gate 에 막혀 10 초 동안 제자리였다 -> 여전히 가야 한다
    assert sequence.advance(x=0.92, y=-1.19, yaw=0.0, now_s=10.0).linear_x < 0
    assert not sequence.is_complete
    sequence.advance(x=0.92 - 0.30, y=-1.19, yaw=0.0, now_s=12.0)
    assert sequence.is_complete


def test_the_command_slows_down_near_the_end() -> None:
    """끝까지 최고 속도로 가면 허용오차를 넘겨 지나친다."""
    sequence = _sequence(DockStep("straight", -0.30))
    sequence.begin(x=0.92, y=-1.19, yaw=0.0, zone=ZONE)
    far = sequence.advance(x=0.92, y=-1.19, yaw=0.0)
    near = sequence.advance(x=0.92 - 0.28, y=-1.19, yaw=0.0)
    assert abs(near.linear_x) < abs(far.linear_x)


def test_speeds_never_exceed_the_configured_limits() -> None:
    """좁은 통로에서 빠르면 안전 gate 가 멈출 틈이 없다."""
    sequence = _sequence(DockStep("straight", -5.0), DockStep("rotate", 3.0))
    sequence.begin(x=0.92, y=-1.19, yaw=0.0, zone=ZONE)
    command = sequence.advance(x=0.92, y=-1.19, yaw=0.0)
    assert abs(command.linear_x) <= LIMITS.max_linear_mps
    sequence.advance(x=0.92 - 5.0, y=-1.19, yaw=0.0)
    turning = sequence.advance(x=0.92 - 5.0, y=-1.19, yaw=0.0)
    assert abs(turning.angular_z) <= LIMITS.max_angular_rps


# ------------------------------------------------------------ 종료 조건


def test_a_completed_sequence_commands_zero() -> None:
    """끝났는데 마지막 속도가 남으면 로봇이 계속 간다."""
    sequence = _sequence(DockStep("straight", -0.10))
    sequence.begin(x=0.92, y=-1.19, yaw=0.0, zone=ZONE)
    sequence.advance(x=0.92, y=-1.19, yaw=0.0)
    sequence.advance(x=0.82, y=-1.19, yaw=0.0)
    assert sequence.is_complete
    stopped = sequence.advance(x=0.82, y=-1.19, yaw=0.0)
    assert stopped.linear_x == 0.0 and stopped.angular_z == 0.0


def test_a_step_that_never_finishes_times_out() -> None:
    """바퀴가 헛돌면 목표 거리에 영원히 못 닿는다. 그때 멈춰야 한다."""
    sequence = _sequence(DockStep("straight", -0.30))
    sequence.begin(x=0.92, y=-1.19, yaw=0.0, zone=ZONE, now_s=0.0)
    sequence.advance(x=0.92, y=-1.19, yaw=0.0, now_s=0.0)
    sequence.advance(x=0.92, y=-1.19, yaw=0.0, now_s=LIMITS.step_timeout_s + 0.1)
    assert sequence.is_failed
    assert sequence.failure == "step_timeout"


def test_exit_zone_drives_until_the_rectangle_is_behind() -> None:
    """출고는 나갈 거리를 미리 잴 필요가 없다. 구역을 벗어나면 끝이다."""
    sequence = _sequence(DockStep("exit_zone", 0.0))
    sequence.begin(x=0.92, y=-1.19, yaw=0.0, zone=ZONE)
    assert sequence.advance(x=0.92, y=-1.19, yaw=0.0).linear_x > 0
    sequence.advance(x=0.92 + 0.30, y=-1.19, yaw=0.0)
    assert sequence.is_complete


def test_an_unknown_step_kind_is_refused_at_construction() -> None:
    """오타가 주행 중에 드러나면 로봇이 도크 안에서 멈춘다."""
    with pytest.raises(ValueError):
        DockStep("rotate_slowly", 1.0)


# ------------------------------------------------- 실측 구역 설정

from trihouse_pinky_docking.zones import ZoneError, load_zones  # noqa: E402

ZONES_FILE = PINKY / "trihouse_pinky_docking" / "config" / "zones.yaml"
ZONES = load_zones(ZONES_FILE)


def test_every_dock_has_a_way_in_and_a_way_out() -> None:
    """들어가기만 하고 못 나오면 로봇이 도크에 갇힌다."""
    assert set(ZONES) == {"ambient", "chilled", "frozen"}
    for name, zone in ZONES.items():
        assert zone["entry"] and zone["exit"], name


def test_entering_a_dock_ends_by_reversing() -> None:
    """진입은 후진이다. 전진으로 끝나면 도크를 지나쳐 벽을 민다."""
    for name, zone in ZONES.items():
        last = zone["entry"][-1]
        assert last.kind == "straight" and last.value < 0, name


def test_leaving_a_dock_starts_by_driving_out() -> None:
    """출고 첫 동작이 회전이면 도크 안에서 도는 것이라 벽을 친다."""
    for name, zone in ZONES.items():
        first = zone["exit"][0]
        assert first.kind == "straight" and first.value > 0, name


def test_the_frozen_dock_makes_room_before_turning() -> None:
    """냉동 진입 지점은 여유가 0.20 m 뿐이라 그 자리에서 못 돈다.

    10 cm 앞으로 나가 자리를 확보한 뒤 돈다 — 2026-08-15 실측으로 확정된 순서다.
    """
    steps = ZONES["frozen"]["entry"]
    assert steps[0].kind == "straight" and steps[0].value > 0
    assert steps[1].kind == "rotate"


def test_the_unverified_dock_says_so() -> None:
    """냉장은 상온 값을 그대로 재사용했고 실물 검증되지 않았다.

    지우면 다음 사람이 값이 없는 줄 알고 다시 재고, 조용히 쓰면 검증 안 된
    시퀀스로 로봇이 벽에 들어간다. 실어 두되 표시를 남긴다.
    """
    assert ZONES["chilled"]["verified"] is False
    assert ZONES["ambient"]["verified"] is True
    assert ZONES["frozen"]["verified"] is True


def test_the_reverse_distance_fits_inside_the_dock() -> None:
    """후진 거리가 통로보다 길면 벽을 민다. 실측 통로는 20~30 cm 다."""
    for name, zone in ZONES.items():
        for step in zone["entry"]:
            if step.kind == "straight" and step.value < 0:
                assert abs(step.value) <= 0.40, f"{name}: {step.value} m 는 너무 깊다"


def test_a_zone_without_geometry_is_refused(tmp_path: Path) -> None:
    """모양이 없으면 어디서 시작할지 판정할 수 없다."""
    bad = tmp_path / "zones.yaml"
    bad.write_text("zones:\n  x:\n    entry: [{kind: rotate, value: 0}]\n", encoding="utf-8")
    with pytest.raises(ZoneError):
        load_zones(bad)


def test_a_zone_with_a_typo_in_a_step_is_refused(tmp_path: Path) -> None:
    """오타가 주행 중에 드러나면 로봇이 도크 안에서 멈춘다."""
    bad = tmp_path / "zones.yaml"
    bad.write_text(
        "zones:\n  x:\n"
        "    geometry: {cx: 0, cy: 0, yaw: 0, length: 0.1, width: 0.2}\n"
        "    entry: [{kind: revers, value: -0.3}]\n"
        "    exit: [{kind: straight, value: 0.3}]\n",
        encoding="utf-8",
    )
    with pytest.raises(ZoneError):
        load_zones(bad)
