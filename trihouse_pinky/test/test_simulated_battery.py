"""무선 충전 시연용 BatteryState 계산 테스트."""

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "trihouse_pinky_bringup"
sys.path.insert(0, str(PACKAGE_ROOT))

from trihouse_pinky_bringup.sim_hardware_node import (  # noqa: E402
    POWER_SUPPLY_STATUS_CHARGING,
    POWER_SUPPLY_STATUS_DISCHARGING,
    POWER_SUPPLY_STATUS_FULL,
    advance_battery,
)


def test_charging_adds_configured_percent_per_second():
    result = advance_battery(0.50, charging=True, elapsed_s=2.0, charge_percent_per_second=1.0)
    assert result.percentage == 0.52
    assert result.power_supply_status == POWER_SUPPLY_STATUS_CHARGING


def test_full_battery_is_clamped_and_reported_full():
    result = advance_battery(0.995, charging=True, elapsed_s=2.0, charge_percent_per_second=1.0)
    assert result.percentage == 1.0
    assert result.power_supply_status == POWER_SUPPLY_STATUS_FULL


def test_not_charging_reports_discharging_without_changing_level():
    result = advance_battery(0.5, charging=False, elapsed_s=10.0, charge_percent_per_second=1.0)
    assert result.percentage == 0.5
    assert result.power_supply_status == POWER_SUPPLY_STATUS_DISCHARGING


def test_input_percentage_is_clamped():
    assert advance_battery(-1, charging=False, elapsed_s=0, charge_percent_per_second=1).percentage == 0.0
    assert advance_battery(2, charging=False, elapsed_s=0, charge_percent_per_second=1).percentage == 1.0
