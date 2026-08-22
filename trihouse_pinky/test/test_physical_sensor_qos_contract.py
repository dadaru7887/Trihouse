"""Pinky 실기 센서 발행자와 Trihouse 구독자의 QoS 계약."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_every_fleet_scan_consumer_uses_sensor_data_qos() -> None:
    paths = (
        ROOT / "trihouse_pinky_bringup/trihouse_pinky_bringup/readiness_node.py",
        ROOT / "trihouse_pinky_fleet/trihouse_pinky_fleet/status_node.py",
        ROOT / "trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py",
        ROOT / "trihouse_pinky_fleet/trihouse_pinky_fleet/recovery_health_node.py",
    )

    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "qos_profile_sensor_data" in source, path


def test_battery_adapter_merges_vendor_percentage_into_battery_state() -> None:
    source = (
        ROOT
        / "trihouse_pinky_io/trihouse_pinky_io/battery_adapter.py"
    ).read_text(encoding="utf-8")

    assert "battery/percent" in source
    assert "message.percentage" in source
    assert "message.present" in source
