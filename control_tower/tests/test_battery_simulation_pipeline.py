"""Gazebo mock SOC부터 Control Tower 정책까지의 순수 통합 시나리오."""

import sys
from pathlib import Path

PINKY_BRINGUP = (
    Path(__file__).resolve().parents[2]
    / "trihouse_pinky"
    / "trihouse_pinky_bringup"
)
PINKY_FLEET = (
    Path(__file__).resolve().parents[2]
    / "trihouse_pinky"
    / "trihouse_pinky_fleet"
)
sys.path.insert(0, str(PINKY_BRINGUP))
sys.path.insert(0, str(PINKY_FLEET))

from trihouse_pinky_bringup.sim_hardware_node import (  # noqa: E402
    POWER_SUPPLY_STATUS_DISCHARGING,
    advance_battery,
)
from trihouse_pinky_fleet.battery_condition import (  # noqa: E402
    BatteryConditionTracker,
)

from control_tower.fleet_manager.battery_policy import (  # noqa: E402
    BatteryAction,
    BatteryConditionInput,
    BatteryPolicyState,
    WorkflowContext,
    classify_condition,
    decide_action,
)


def _snapshot_from_simulation(
    initial_soc: float, *, elapsed_s: float, drain_percent_per_second: float
):
    simulated = advance_battery(
        initial_soc,
        charging=False,
        elapsed_s=elapsed_s,
        charge_percent_per_second=0.0,
        discharge_percent_per_second=drain_percent_per_second,
    )
    tracker = BatteryConditionTracker(started_at=0.0)
    observation = tracker.ingest(
        percentage=simulated.percentage,
        present=True,
        power_supply_status=simulated.power_supply_status,
        received_at=elapsed_s,
    )
    return classify_condition(
        BatteryConditionInput(
            percentage=observation.percentage,
            present=observation.present,
            power_supply_status=observation.power_supply_status,
            measurement_valid=observation.measurement_valid,
            has_valid_sample=observation.has_valid_sample,
            telemetry_fresh=observation.telemetry_fresh,
        )
    )


def test_drain_crosses_local_only_and_uses_rmf_finish_soc() -> None:
    """ROS SOC 단위가 중복 변환되거나 RMF finish SOC가 무시되는 회귀를 막는다."""
    snapshot = _snapshot_from_simulation(
        0.21, elapsed_s=1.0, drain_percent_per_second=1.0
    )

    decision = decide_action(
        snapshot,
        WorkflowContext(
            "FROZEN", "PACKING", finish_state_of_charge=0.12
        ),
    )

    assert snapshot.percentage == 20.0
    assert snapshot.state == BatteryPolicyState.LOCAL_ONLY
    assert decision.action == BatteryAction.ALLOW_LOCAL_JOB


def test_rmf_finish_soc_at_hard_stop_returns_to_charge() -> None:
    """현재 SOC만 보고 RMF 예상 종료 SOC 5%를 무시하는 회귀를 막는다."""
    snapshot = _snapshot_from_simulation(
        0.20, elapsed_s=1.0, drain_percent_per_second=1.0
    )

    decision = decide_action(
        snapshot,
        WorkflowContext(
            "FROZEN", "PACKING", finish_state_of_charge=0.05
        ),
    )

    assert snapshot.state == BatteryPolicyState.LOCAL_ONLY
    assert decision.action == BatteryAction.RETURN_TO_CHARGE


def test_return_threshold_with_cargo_and_safe_handover_finishes_then_returns() -> None:
    """화물 안전 인계를 생략하고 즉시 충전 복귀하는 회귀를 막는다."""
    snapshot = _snapshot_from_simulation(
        0.11, elapsed_s=1.0, drain_percent_per_second=1.0
    )

    decision = decide_action(
        snapshot,
        WorkflowContext(
            has_cargo=True,
            handover_finish_soc=0.04,
            charger_reachable=True,
        ),
    )

    assert snapshot.state == BatteryPolicyState.RETURN_REQUIRED
    assert decision.action == BatteryAction.COMPLETE_THEN_RETURN


def test_simulated_status_is_discharging_during_threshold_test() -> None:
    """방전 SOC인데 charging 상태로 분류되어 업무가 영구 대기하는 회귀를 막는다."""
    simulated = advance_battery(
        0.5,
        charging=False,
        elapsed_s=1.0,
        charge_percent_per_second=0.0,
        discharge_percent_per_second=1.0,
    )

    assert simulated.power_supply_status == POWER_SUPPLY_STATUS_DISCHARGING
