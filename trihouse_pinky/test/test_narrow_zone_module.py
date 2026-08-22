"""창고 협로 규칙 주행의 단일 도메인 모듈 계약."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest


PINKY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PINKY / "trihouse_pinky_docking"))

from trihouse_pinky_docking.narrow_zone import (  # noqa: E402
    ENTER,
    EXIT,
    EntryPoseController,
    MotionLimits,
    NarrowZoneConfigError,
    NarrowZoneController,
    Pose2D,
    load_narrow_zones,
)


def _document(*, enabled: bool = True, measured: bool = True) -> dict:
    return {
        "map_name": "new_map_2",
        "zones": {
            "frozen_storage_loading_dock_01": {
                "enabled": enabled,
                "entry": {"x": 1.0, "y": -1.0, "yaw": 0.0},
                "entry_zone": {
                    "x": 1.0,
                    "y": -1.0,
                    "yaw": 0.0,
                    "length": 0.20,
                    "width": 0.20,
                },
                "zone": {
                    "x": 1.2,
                    "y": -0.7,
                    "yaw": -math.pi / 2,
                    "length": 0.30,
                    "width": 0.24,
                },
                "enter": [
                    ["straight", 0.20],
                    ["rotate", -math.pi / 2],
                    ["straight", -0.30],
                ],
                "exit": [
                    ["straight", 0.30],
                    ["rotate", 0.0],
                    ["straight", -0.20],
                ],
                "dock_target": {"x": 1.2, "y": -0.7, "yaw": -math.pi / 2},
                "exit_target": {"x": 1.0, "y": -1.0, "yaw": 0.0},
                "measured": {
                    "entry_pose": measured,
                    "dock_pose": measured,
                    "enter": measured,
                    "exit": measured,
                },
            },
            "ambient_storage_loading_dock_01": {
                "enabled": False,
                "entry": None,
                "zone": None,
                "enter": [],
                "exit": [],
                "dock_target": None,
                "exit_target": None,
                "measured": {
                    "entry_pose": False,
                    "dock_pose": False,
                    "enter": False,
                    "exit": False,
                },
            },
        },
    }


def test_catalog_keeps_disabled_warehouses_but_refuses_to_execute_them() -> None:
    zones = load_narrow_zones(_document(), map_name="new_map_2")

    assert set(zones) == {
        "ambient_storage_loading_dock_01",
        "frozen_storage_loading_dock_01",
    }
    assert zones["frozen_storage_loading_dock_01"].executable is True
    ambient = zones["ambient_storage_loading_dock_01"]
    assert ambient.executable is False
    assert ambient.readiness_code == "NARROW_PROFILE_DISABLED"


def test_catalog_rejects_a_profile_from_another_map() -> None:
    with pytest.raises(NarrowZoneConfigError, match="지도"):
        load_narrow_zones(_document(), map_name="trihouse_map_01")


@pytest.mark.parametrize("missing", ["dock_target", "exit_target"])
def test_warehouse_requires_both_completion_targets(missing: str) -> None:
    document = _document()
    document["zones"]["frozen_storage_loading_dock_01"][missing] = None

    profile = load_narrow_zones(document, map_name="new_map_2")[
        "frozen_storage_loading_dock_01"
    ]

    assert profile.executable is False
    assert profile.readiness_code == "NARROW_PROFILE_INCOMPLETE"


def test_unmeasured_motion_is_not_executable_even_when_values_exist() -> None:
    profile = load_narrow_zones(
        _document(measured=False), map_name="new_map_2"
    )["frozen_storage_loading_dock_01"]

    assert profile.executable is False
    assert profile.readiness_code == "NARROW_PROFILE_UNMEASURED"


def test_unmeasured_motion_requires_an_explicit_calibration_controller() -> None:
    profile = load_narrow_zones(
        _document(measured=False), map_name="new_map_2"
    )["frozen_storage_loading_dock_01"]

    normal = NarrowZoneController(profile, direction=ENTER)
    calibration = NarrowZoneController(profile, direction=ENTER, calibration=True)

    assert normal.begin(profile.entry_pose, now_s=0.0) is False
    assert normal.failure == "NARROW_PROFILE_UNMEASURED"
    assert calibration.begin(profile.entry_pose, now_s=0.0) is True


def test_entry_zone_is_distinct_from_the_docked_zone() -> None:
    """입구 handoff 구역이 도크 체류 구역으로 잘못 대체되는 결함을 잡는다."""
    profile = load_narrow_zones(_document(), map_name="new_map_2")[
        "frozen_storage_loading_dock_01"
    ]

    assert profile.entry_zone is not None
    assert profile.entry_zone.contains(Pose2D(0.91, -1.0, 2.0))
    assert not profile.zone.contains(Pose2D(0.91, -1.0, 2.0))


def test_entry_alignment_reaches_position_before_matching_entry_yaw() -> None:
    """구역 경계에서 기존 enter 거리를 시작해 최종 도크가 어긋나는 결함을 잡는다."""
    profile = load_narrow_zones(_document(), map_name="new_map_2")[
        "frozen_storage_loading_dock_01"
    ]
    controller = EntryPoseController(
        profile.entry_pose,
        limits=MotionLimits(
            max_linear_mps=0.06,
            max_angular_rps=0.5,
            linear_tolerance_m=0.02,
            angular_tolerance_rad=0.05,
        ),
    )
    assert controller.begin(Pose2D(0.91, -1.0, math.pi / 2), now_s=0.0)

    face_entry = controller.advance(
        Pose2D(0.91, -1.0, math.pi / 2), now_s=0.1
    )
    drive_entry = controller.advance(Pose2D(0.91, -1.0, 0.0), now_s=0.2)
    match_entry_yaw = controller.advance(Pose2D(0.99, -1.0, 0.40), now_s=0.3)

    assert face_entry.linear_x == 0.0
    assert face_entry.angular_z < 0.0
    assert drive_entry.linear_x > 0.0
    assert match_entry_yaw.linear_x == 0.0
    assert match_entry_yaw.angular_z < 0.0

    stopped = controller.advance(Pose2D(0.99, -1.0, 0.01), now_s=0.4)
    assert stopped.is_zero
    assert controller.is_complete


def test_controller_rotates_the_short_way_without_linear_motion() -> None:
    profile = load_narrow_zones(_document(), map_name="new_map_2")[
        "frozen_storage_loading_dock_01"
    ]
    # 회전 단계 하나만 쓰는 별도 controller를 만들 수 있도록 profile helper를 제공한다.
    controller = NarrowZoneController.for_steps(
        profile,
        direction=ENTER,
        steps=(("rotate", 3.0),),
        limits=MotionLimits(max_angular_rps=0.5),
    )
    controller.begin(Pose2D(0.0, 0.0, -3.0), now_s=0.0)

    command = controller.advance(Pose2D(0.0, 0.0, -3.0), now_s=0.1)

    assert command.linear_x == 0.0
    assert command.angular_z < 0.0
    assert abs(command.angular_z) <= 0.5


def test_controller_uses_signed_distance_and_slows_near_the_target() -> None:
    profile = load_narrow_zones(_document(), map_name="new_map_2")[
        "frozen_storage_loading_dock_01"
    ]
    controller = NarrowZoneController.for_steps(
        profile,
        direction=ENTER,
        steps=(("straight", -0.30),),
        limits=MotionLimits(max_linear_mps=0.06, linear_tolerance_m=0.02),
    )
    controller.begin(Pose2D(0.0, 0.0, 0.0), now_s=0.0)

    fast = controller.advance(Pose2D(0.0, 0.0, 0.0), now_s=0.1)
    slow = controller.advance(Pose2D(-0.27, 0.0, 0.0), now_s=0.2)

    assert fast.linear_x == pytest.approx(-0.06)
    assert -0.06 < slow.linear_x < 0.0


def test_exit_zone_stops_only_after_the_oriented_rectangle_is_left() -> None:
    profile = load_narrow_zones(_document(), map_name="new_map_2")[
        "frozen_storage_loading_dock_01"
    ]
    controller = NarrowZoneController.for_steps(
        profile,
        direction=EXIT,
        steps=(("exit_zone", None),),
    )
    controller.begin(Pose2D(1.2, -0.7, 0.0), now_s=0.0)

    inside = controller.advance(Pose2D(1.2, -0.7, 0.0), now_s=0.1)
    outside = controller.advance(Pose2D(1.2, -0.40, 0.0), now_s=0.2)

    assert inside.linear_x > 0.0
    assert outside.is_zero
    assert controller.is_complete


def test_timeout_and_cancel_are_terminal_zero_command_states() -> None:
    profile = load_narrow_zones(_document(), map_name="new_map_2")[
        "frozen_storage_loading_dock_01"
    ]
    timed_out = NarrowZoneController.for_steps(
        profile,
        direction=ENTER,
        steps=(("straight", 1.0),),
        limits=MotionLimits(step_timeout_s=1.0),
    )
    timed_out.begin(Pose2D(0.0, 0.0, 0.0), now_s=0.0)

    timeout_command = timed_out.advance(Pose2D(0.0, 0.0, 0.0), now_s=1.1)

    assert timeout_command.is_zero
    assert timed_out.failure == "step_timeout"
    assert timed_out.advance(Pose2D(0.0, 0.0, 0.0), now_s=1.2).is_zero

    canceled = NarrowZoneController(profile, direction=ENTER)
    canceled.begin(profile.entry_pose, now_s=0.0)
    canceled.cancel("operator_cancel")
    assert canceled.failure == "operator_cancel"
    assert canceled.advance(profile.entry_pose, now_s=0.1).is_zero


def test_timeout_is_a_no_progress_watchdog_not_a_total_step_deadline() -> None:
    """안전 gate가 간헐 정지시켜도 실제로 전진 중이면 timeout하지 않는다."""
    profile = load_narrow_zones(_document(), map_name="new_map_2")[
        "frozen_storage_loading_dock_01"
    ]
    controller = NarrowZoneController.for_steps(
        profile,
        direction=ENTER,
        steps=(("straight", 1.0),),
        limits=MotionLimits(step_timeout_s=1.0, linear_tolerance_m=0.02),
    )
    controller.begin(Pose2D(0.0, 0.0, 0.0), now_s=0.0)

    assert not controller.advance(Pose2D(0.05, 0.0, 0.0), now_s=0.9).is_zero
    assert not controller.advance(Pose2D(0.10, 0.0, 0.0), now_s=1.8).is_zero
    assert controller.failure is None

    stopped = controller.advance(Pose2D(0.10, 0.0, 0.0), now_s=2.9)
    assert stopped.is_zero
    assert controller.failure == "step_timeout"
