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
        "PK_01": {"charger": "charging_station_01"},
        "PK_02": {"charger": "charging_station_02"},
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


def test_fleet_never_asks_rmf_to_move_the_robot_without_a_job() -> None:
    """RMF 가 스스로 만든 이동은 이 로봇이 거부한다 — 애초에 만들게 하지 않는다.

    `trihouse_pinky_fleet/protocol.py` 는 `execute_transport requires an active
    task_context` 로 job 없는 이동을 원천 거부한다. 그런데 `finishing_request`
    (작업 종료 후 주차)와 `responsive_wait`(대기 중 비켜서기)는 RMF 가 원장에
    없는 task 를 스스로 만들게 한다. 그 task 는 command claim 에서 404 를 받고,
    어댑터가 replan 을 걸면 조건이 그대로라 같은 작업을 다시 계획한다.
    2026-08-19 에 초당 13건(누적 2104건)으로 돌았다.

    귀환은 원장 안의 step 70 `return_home` 이 맡는다.
    """
    fleet = _fleet()

    assert fleet["finishing_request"] == "nothing"
    assert fleet["responsive_wait"] is False
