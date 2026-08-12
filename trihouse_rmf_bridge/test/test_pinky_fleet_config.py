"""실물 Pinky RMF fleet 설정의 안전 필수값을 검증한다."""

from pathlib import Path

import yaml


CONFIG = Path(__file__).resolve().parents[1] / "config" / "pinky_fleet.yaml"


def _fleet() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["rmf_fleet"]


def test_pinky_fleet_has_battery_and_safe_profile_defaults() -> None:
    fleet = _fleet()

    assert fleet["recharge_threshold"] == 0.10
    assert fleet["account_for_battery_drain"] is True
    assert fleet["profile"]["footprint"] > 0
    assert fleet["profile"]["vicinity"] >= fleet["profile"]["footprint"]
    assert fleet["publish_fleet_state"] > 0


def test_single_pinky_has_a_named_charger() -> None:
    robots = _fleet()["robots"]

    assert list(robots) == ["PK-01"]
    assert robots["PK-01"]["charger"] == "충전1"
