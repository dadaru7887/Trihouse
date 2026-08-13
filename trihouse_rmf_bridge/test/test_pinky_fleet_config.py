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


def test_project1_fleet_exposes_no_actions_and_is_not_reversible() -> None:
    fleet = _fleet()

    assert fleet["name"] == "project1_pinky"
    assert fleet["actions"] == []
    assert fleet["reversible"] is False


def test_two_canonical_pinkies_have_distinct_named_chargers() -> None:
    robots = _fleet()["robots"]

    assert robots == {
        "PK_01": {"charger": "충전1"},
        "PK_02": {"charger": "충전2"},
    }


def test_runtime_fleet_config_contains_no_legacy_registry_names() -> None:
    config = CONFIG.read_text(encoding="utf-8")

    for legacy_name in (
        "pinky_fleet",
        "PINKY-01",
        "PINKY-02",
        "PK-01",
        "PK-02",
        "OMX-01",
        "OMX-02",
    ):
        assert legacy_name not in config
