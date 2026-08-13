"""Pinky SR 정책의 동작 테스트.

ROS 없이 실행한다: python3 -m unittest trihouse_pinky.test.test_pinky_sr_policies
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "trihouse_pinky_safety"))
sys.path.insert(0, str(ROOT / "trihouse_pinky_fleet"))
sys.path.insert(0, str(ROOT / "trihouse_pinky_io"))
sys.path.insert(0, str(ROOT / "trihouse_pinky_bringup"))

from trihouse_pinky_fleet.workflow import (  # noqa: E402
    JobCommand,
    JobPhase,
    TransportWorkflow,
)
from trihouse_pinky_fleet.status import StatusInputs, build_status  # noqa: E402
from trihouse_pinky_fleet.battery_policy import classify_battery  # noqa: E402
from trihouse_pinky_fleet.recovery_health import RecoveryHealthInputs, evaluate_recovery_health  # noqa: E402
from trihouse_pinky_fleet.protocol import ProtocolError, classify_gateway_response, parse_clear_keep_out_zone, parse_emergency_command, parse_keep_out_zone, parse_transport_command  # noqa: E402
from trihouse_pinky_fleet.arrival import within_tolerance  # noqa: E402
from trihouse_pinky_io.indicator import Indicator, select_indicator  # noqa: E402
from trihouse_pinky_io.destination_display import destination_label  # noqa: E402
from trihouse_pinky_bringup.readiness import ReadinessInputs, evaluate_readiness  # noqa: E402
from trihouse_pinky_safety.policy import (  # noqa: E402
    MotionCommand,
    SafetyConfig,
    SafetyInputs,
    SafetyLevel,
    apply_safety_gate,
)
from trihouse_pinky_safety.geometry import point_in_polygon  # noqa: E402


class SafetyPolicyTest(unittest.TestCase):
    def test_front_sensor_stop_overrides_person_and_preserves_goal(self) -> None:
        """A near front obstacle must stop, even when the person rule only slows."""
        result = apply_safety_gate(
            MotionCommand(0.20, 0.10),
            SafetyInputs(front_distance_m=0.20, person_detected=True),
        )
        self.assertEqual(SafetyLevel.STOP, result.level)
        self.assertEqual(0.0, result.command.linear_x)
        self.assertTrue(result.goal_may_continue)


class KeepOutGeometryTest(unittest.TestCase):
    def test_keep_out_applies_only_when_robot_is_inside_zone(self) -> None:
        """A global zone broadcast must not stop a Pinky outside that zone."""
        zone = ((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0))
        self.assertTrue(point_in_polygon(1.0, 1.0, zone))
        self.assertFalse(point_in_polygon(3.0, 1.0, zone))

    def test_emergency_latch_blocks_motion_until_explicit_clear(self) -> None:
        """Restarting normal observations cannot clear an emergency latch."""
        stopped = apply_safety_gate(
            MotionCommand(0.20, 0.0), SafetyInputs(emergency_latched=True)
        )
        still_stopped = apply_safety_gate(
            MotionCommand(0.20, 0.0), SafetyInputs(emergency_latched=True)
        )
        self.assertEqual(SafetyLevel.EMERGENCY, stopped.level)
        self.assertEqual(0.0, still_stopped.command.linear_x)

    def test_stale_sensor_data_fails_safe_to_stop(self) -> None:
        """A timeout must never pass a non-zero motor command."""
        result = apply_safety_gate(
            MotionCommand(0.20, 0.0), SafetyInputs(sensor_fresh=False)
        )
        self.assertEqual(SafetyLevel.STOP, result.level)
        self.assertEqual(0.0, result.command.linear_x)

    def test_control_link_loss_fails_safe_to_stop(self) -> None:
        """관제 단절 중에는 새 작업뿐 아니라 진행 중 주행도 안전 정지한다."""
        result = apply_safety_gate(
            MotionCommand(0.20, 0.0), SafetyInputs(sensor_fresh=True, control_link_fresh=False)
        )
        self.assertEqual(SafetyLevel.STOP, result.level)
        self.assertEqual(0.0, result.command.linear_x)

    def test_stop_distance_is_a_deployable_parameter(self) -> None:
        """A measured robot-specific stopping distance must change the gate boundary."""
        result = apply_safety_gate(
            MotionCommand(0.20, 0.0), SafetyInputs(front_distance_m=0.40), SafetyConfig(stop_distance_m=0.45)
        )
        self.assertEqual(SafetyLevel.STOP, result.level)

    def test_person_outside_protective_distance_does_not_slow_robot(self) -> None:
        """A base-frame detection outside the configured protection range is not a speed gate."""
        result = apply_safety_gate(
            MotionCommand(0.20, 0.0), SafetyInputs(person_distance_m=2.0), SafetyConfig(person_protective_distance_m=1.0)
        )
        self.assertEqual(SafetyLevel.CLEAR, result.level)


class IndicatorTest(unittest.TestCase):
    def test_emergency_has_priority_over_person_and_handover(self) -> None:
        """A red emergency indication must win over every ordinary indication."""
        self.assertEqual(
            Indicator.EMERGENCY,
            select_indicator(person_detected=True, emergency=True, handover_waiting=True),
        )

    def test_handover_waiting_is_not_a_hazard_indicator(self) -> None:
        """Ordinary handover waiting must not turn on a person/emergency LED."""
        self.assertEqual(
            Indicator.OFF,
            select_indicator(person_detected=False, emergency=False, handover_waiting=True),
        )


class DestinationDisplayTest(unittest.TestCase):
    def test_only_approved_destination_codes_render_korean_labels(self) -> None:
        """An unknown FMS location code must clear the LCD instead of showing invented text."""
        self.assertEqual('냉동창고', destination_label('FROZEN'))
        self.assertEqual('대기/충전소\n복귀', destination_label('RETURN'))
        self.assertIsNone(destination_label('warehouse-secret'))


class TransportWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = TransportWorkflow(robot_id="PK-01", expected_map_revision="map-7")
        self.command = JobCommand(
            command_id="cmd-1",
            job_id="job-1",
            map_revision="map-7",
            destination_kind="PACKING",
        )

    def test_rejects_transport_before_cargo_and_readiness_are_confirmed(self) -> None:
        """Transport must not leave before OMX handover and Pinky readiness."""
        rejected = self.workflow.accept(self.command, ready=False, cargo_confirmed=False)
        self.assertFalse(rejected.accepted)
        self.assertEqual(JobPhase.REJECTED, rejected.phase)

    def test_arrival_requires_nav2_and_stationary_before_handover_waiting(self) -> None:
        """Nav2 success alone is insufficient if the robot is still moving."""
        self.workflow.accept(self.command, ready=True, cargo_confirmed=True)
        moving = self.workflow.nav_result(succeeded=True, stationary=False)
        parked = self.workflow.nav_result(succeeded=True, stationary=True)
        self.assertEqual(JobPhase.NAVIGATING, moving.phase)
        self.assertEqual(JobPhase.WAITING_HANDOVER, parked.phase)

    def test_emergency_clear_requires_return_and_health_before_new_job(self) -> None:
        """A cleared emergency never resumes the interrupted transport automatically."""
        self.workflow.accept(self.command, ready=True, cargo_confirmed=True)
        self.workflow.enter_emergency("fall event")
        returned = self.workflow.clear_emergency(return_location_id="wait-1")
        healthy = self.workflow.finish_return(health_ok=True, cargo_present=False)
        self.assertEqual(JobPhase.RETURNING, returned.phase)
        self.assertEqual(JobPhase.IDLE, healthy.phase)
        self.assertEqual("wait-1", returned.return_location_id)

    def test_recovery_return_arrival_requires_health_check_before_idle(self) -> None:
        """An emergency-cleared robot must not become assignable at its return waypoint."""
        self.workflow.accept(self.command, ready=True, cargo_confirmed=True)
        self.workflow.enter_emergency('fall event')
        self.workflow.clear_emergency(return_location_id='wait-1')
        self.workflow.accept(JobCommand('cmd-return', 'recovery-1', 'map-7', 'RETURN_TO_WAIT', requires_cargo=False), ready=True, cargo_confirmed=False)
        arrived = self.workflow.nav_result(succeeded=True, stationary=True)
        self.assertEqual(JobPhase.HEALTH_CHECK, arrived.phase)

    def test_duplicate_command_is_idempotent(self) -> None:
        """A retried control message must not create another navigation task."""
        first = self.workflow.accept(self.command, ready=True, cargo_confirmed=True)
        duplicate = self.workflow.accept(self.command, ready=True, cargo_confirmed=True)
        self.assertTrue(first.accepted)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(JobPhase.NAVIGATING, duplicate.phase)

    def test_empty_return_to_charge_is_accepted_without_cargo(self) -> None:
        """A low-battery Pinky must be able to return empty to its FMS location."""
        returning = JobCommand('cmd-return', 'return-1', 'map-7', 'RETURN_TO_CHARGE', requires_cargo=False)
        accepted = self.workflow.accept(returning, ready=True, cargo_confirmed=False)
        arrived = self.workflow.nav_result(succeeded=True, stationary=True)
        self.assertTrue(accepted.accepted)
        self.assertEqual(JobPhase.IDLE, arrived.phase)

    def test_rmf_navigation_needs_readiness_not_cargo_and_returns_idle(self) -> None:
        """RMF의 일반 이동은 빈 바구니로 수행하고 인계 대기 없이 끝난다."""
        command = JobCommand(
            'rmf-cmd', 'rmf-task', 'map-7', 'RMF_NAVIGATION',
            requires_cargo=False,
        )

        accepted = self.workflow.accept(
            command, ready=True, cargo_confirmed=False
        )
        arrived = self.workflow.nav_result(succeeded=True, stationary=True)

        self.assertTrue(accepted.accepted)
        self.assertEqual(JobPhase.IDLE, arrived.phase)
        self.assertEqual('', self.workflow.job_id)

    def test_cancel_navigation_releases_the_active_rmf_command(self) -> None:
        """RMF cancel 뒤 늦은 Nav2 결과가 현재 작업으로 남지 않아야 한다."""
        command = JobCommand(
            'rmf-cmd', 'rmf-task', 'map-7', 'RMF_NAVIGATION',
            requires_cargo=False,
        )
        self.workflow.accept(command, ready=True, cargo_confirmed=False)

        canceled = self.workflow.cancel_navigation()

        self.assertTrue(canceled.accepted)
        self.assertEqual(JobPhase.IDLE, canceled.phase)
        self.assertEqual('', self.workflow.command_id)
        self.assertEqual('', self.workflow.job_id)

    def test_waiting_handover_can_move_to_fms_reassigned_packing_station(self) -> None:
        """A reassign command preserves the job and resumes movement from waiting."""
        self.workflow.accept(self.command, ready=True, cargo_confirmed=True)
        self.workflow.nav_result(succeeded=True, stationary=True)
        moved = self.workflow.reassign('cmd-2', 'map-7')
        self.assertTrue(moved.accepted)
        self.assertEqual(JobPhase.NAVIGATING, moved.phase)
        self.assertEqual('job-1', self.workflow.job_id)

    def test_confirmed_handover_releases_robot_and_clears_active_job(self) -> None:
        """Pinky must remain waiting until a real cargo-unlock confirmation arrives."""
        self.workflow.accept(self.command, ready=True, cargo_confirmed=True)
        self.workflow.nav_result(succeeded=True, stationary=True)
        finished = self.workflow.complete_handover()
        self.assertTrue(finished.accepted)
        self.assertEqual(JobPhase.IDLE, finished.phase)
        self.assertEqual('', self.workflow.job_id)


class StatusPolicyTest(unittest.TestCase):
    def test_stale_required_sensor_marks_robot_unready_and_reports_error(self) -> None:
        """FMS must see work unavailable when a mandatory sensor stops reporting."""
        status = build_status(
            StatusInputs(robot_id="PK_01", scan_fresh=False, odom_fresh=True, battery_fresh=True)
        )
        self.assertFalse(status.ready)
        self.assertEqual(("scan_stale",), status.errors)

    def test_readiness_is_split_into_telemetry_execution_and_dispatch_layers(self) -> None:
        """상태 조회 가능, 실행 가능, 신규 할당 가능은 서로 다른 판단이어야 한다."""
        telemetry_only = build_status(StatusInputs(
            robot_id="PK_01", control_link_online=False,
        ))
        execution_only = build_status(StatusInputs(
            robot_id="PK_01", battery_dispatchable=False,
        ))

        self.assertTrue(telemetry_only.telemetry_valid)
        self.assertFalse(telemetry_only.execution_ready)
        self.assertFalse(telemetry_only.dispatchable)
        self.assertTrue(execution_only.execution_ready)
        self.assertFalse(execution_only.dispatchable)
        self.assertFalse(execution_only.ready)


class BatteryPolicyProjectionTest(unittest.TestCase):
    def test_valid_condition_projects_same_threshold_states_as_control_tower(self) -> None:
        self.assertEqual("NORMAL", classify_battery(20.1, valid=True).state)
        self.assertEqual("LOCAL_ONLY", classify_battery(20.0, valid=True).state)
        self.assertEqual("RETURN_REQUIRED", classify_battery(10.0, valid=True).state)

    def test_invalid_or_charging_condition_is_not_dispatchable(self) -> None:
        self.assertFalse(classify_battery(80.0, valid=False).ready)
        charging = classify_battery(80.0, valid=True, charging=True)
        self.assertEqual("CHARGING", charging.state)
        self.assertFalse(charging.ready)


class RecoveryHealthTest(unittest.TestCase):
    def test_stale_battery_or_remaining_cargo_blocks_redeployment(self) -> None:
        """After emergency, all required telemetry and an empty basket are mandatory."""
        result = evaluate_recovery_health(RecoveryHealthInputs(odom_fresh=True, scan_fresh=True, ultrasonic_fresh=True, battery_fresh=False, cargo_present=True))
        self.assertFalse(result.ready)
        self.assertEqual(('battery', 'cargo'), result.failures)


class FleetProtocolTest(unittest.TestCase):
    def test_gateway_ack_and_rejection_are_control_messages_not_robot_commands(self) -> None:
        self.assertEqual("ack", classify_gateway_response({"type": "ack", "action": "robot_status"}))
        self.assertEqual(
            "event_rejected",
            classify_gateway_response({"type": "event_rejected", "reason_code": "STALE_SEQUENCE"}),
        )
        self.assertEqual("command", classify_gateway_response({"type": "execute_transport"}))

    def test_transport_command_requires_message_id_and_pose(self) -> None:
        """Malformed network data must not become a Nav2 action goal."""
        with self.assertRaises(ProtocolError):
            parse_transport_command({'type': 'execute_transport', 'job_id': 'job-1'})

    def test_transport_command_preserves_return_mode_and_destination_code(self) -> None:
        """Gateway conversion must retain FMS intent rather than infer a destination."""
        command = parse_transport_command({
            'type': 'execute_transport', 'message_id': 'msg-1',
            'task_context': {
                'active': True, 'job_id': 7, 'job_step_id': 10,
                'assignment_revision': 3, 'rmf_task_id': 'rmf-task-1',
                'command_id': 'cmd-1', 'map_revision': 'map-7',
                'command_source': 'FMS_GATEWAY',
            },
            'dropoff_location_id': 'wait-1', 'destination_code': 'RETURN',
            'dropoff_pose': {'frame_id': 'map', 'x': 1.0, 'y': 2.0, 'yaw': 0.0}, 'mode': 'RETURN_TO_WAIT',
        })
        self.assertEqual('RETURN_TO_WAIT', command.mode)
        self.assertEqual('RETURN', command.destination_code)
        self.assertEqual(7, command.task_context.job_id)
        self.assertEqual(3, command.task_context.assignment_revision)

    def test_clear_emergency_requires_operator_identity(self) -> None:
        """A network packet cannot clear an emergency latch anonymously."""
        with self.assertRaises(ProtocolError):
            parse_emergency_command({'type': 'clear_emergency', 'message_id': 'clear-1'})

    def test_keep_out_zone_requires_a_real_polygon(self) -> None:
        """Malformed emergency areas must not block arbitrary warehouse space."""
        with self.assertRaises(ProtocolError):
            parse_keep_out_zone({'type': 'keep_out_zone', 'message_id': 'zone-1', 'zone_id': 'fall-1', 'points': [[0, 0], [1, 0]]})

    def test_clear_keep_out_zone_requires_operator_identity(self) -> None:
        """Emergency-zone removal is an operator-approved control action."""
        with self.assertRaises(ProtocolError):
            parse_clear_keep_out_zone({'type': 'clear_keep_out_zone', 'message_id': 'zone-clear-1', 'zone_id': 'fall-1'})


class ArrivalToleranceTest(unittest.TestCase):
    def test_precise_omx_stop_rejects_nav2_default_tolerance_position(self) -> None:
        """A Nav2 25cm success must not be used as a 5cm OMX handover success."""
        self.assertFalse(within_tolerance(current=(0.12, 0.0, 0.0), target=(0.0, 0.0, 0.0), xy_tolerance_m=0.05, yaw_tolerance_rad=0.0873))
        self.assertTrue(within_tolerance(current=(0.04, 0.0, 0.05), target=(0.0, 0.0, 0.0), xy_tolerance_m=0.05, yaw_tolerance_rad=0.0873))


class ReadinessPolicyTest(unittest.TestCase):
    def test_missing_nav_and_stale_scan_hold_robot_not_ready(self) -> None:
        """Fleet may accept work only after both motion safety and Nav2 are available."""
        result = evaluate_readiness(ReadinessInputs(scan_fresh=False, odom_fresh=True, nav_available=False))
        self.assertFalse(result.ready)
        self.assertEqual(("scan", "navigate_to_pose"), result.missing)

    def test_required_interfaces_make_robot_ready_without_optional_vision(self) -> None:
        """The base transport flow must remain usable when optional RTSP is disabled."""
        result = evaluate_readiness(ReadinessInputs(scan_fresh=True, odom_fresh=True, nav_available=True))
        self.assertTrue(result.ready)
        self.assertEqual((), result.missing)


if __name__ == "__main__":
    unittest.main()
