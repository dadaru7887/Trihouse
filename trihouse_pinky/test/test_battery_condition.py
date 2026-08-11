"""BatteryState 원본을 정책 입력으로 검증하는 순수 로직 테스트."""

import math
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "trihouse_pinky_fleet"
sys.path.insert(0, str(PACKAGE_ROOT))

from trihouse_pinky_fleet.battery_condition import BatteryConditionTracker  # noqa: E402


def test_waits_for_first_valid_sample():
    tracker = BatteryConditionTracker(started_at=10.0)

    observation = tracker.evaluate(now=12.0)

    assert observation.has_valid_sample is False
    assert observation.telemetry_fresh is False
    assert observation.reason_code == "WAITING_FOR_FIRST_BATTERY_SAMPLE"


def test_startup_timeout_changes_reason_but_not_readiness():
    tracker = BatteryConditionTracker(started_at=10.0, startup_timeout_s=5.0)

    observation = tracker.evaluate(now=15.0)

    assert observation.has_valid_sample is False
    assert observation.telemetry_fresh is False
    assert observation.reason_code == "BATTERY_STARTUP_TIMEOUT"


def test_valid_sample_converts_fraction_to_percent():
    tracker = BatteryConditionTracker(started_at=10.0)

    observation = tracker.ingest(
        percentage=0.42,
        present=True,
        power_supply_status=2,
        received_at=11.0,
    )

    assert observation.percentage == 42.0
    assert observation.measurement_valid is True
    assert observation.has_valid_sample is True
    assert observation.telemetry_fresh is True
    assert observation.reason_code == "BATTERY_SAMPLE_VALID"


def test_nan_does_not_refresh_last_valid_sample():
    tracker = BatteryConditionTracker(started_at=0.0, telemetry_timeout_s=3.0)
    tracker.ingest(percentage=0.5, present=True, power_supply_status=2, received_at=1.0)

    invalid = tracker.ingest(
        percentage=math.nan,
        present=True,
        power_supply_status=2,
        received_at=3.0,
    )
    stale = tracker.evaluate(now=4.1)

    assert invalid.measurement_valid is False
    assert invalid.reason_code == "BATTERY_PERCENTAGE_INVALID"
    assert stale.telemetry_fresh is False
    assert stale.reason_code == "BATTERY_TELEMETRY_STALE"


def test_absent_battery_is_unknown():
    tracker = BatteryConditionTracker(started_at=0.0)

    observation = tracker.ingest(
        percentage=0.8,
        present=False,
        power_supply_status=0,
        received_at=1.0,
    )

    assert observation.present is False
    assert observation.measurement_valid is False
    assert observation.has_valid_sample is False
    assert observation.reason_code == "BATTERY_NOT_PRESENT"


def test_valid_sample_becomes_stale_after_three_seconds():
    tracker = BatteryConditionTracker(started_at=0.0, telemetry_timeout_s=3.0)
    tracker.ingest(percentage=0.8, present=True, power_supply_status=2, received_at=1.0)

    fresh = tracker.evaluate(now=4.0)
    stale = tracker.evaluate(now=4.001)

    assert fresh.telemetry_fresh is True
    assert stale.telemetry_fresh is False
    assert stale.reason_code == "BATTERY_TELEMETRY_STALE"
