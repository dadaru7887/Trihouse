"""공개 주문 한 건으로 상온·냉장·냉동을 돌고 충전소로 복귀하는 실기 순회 테스트.

`test_narrow_zone_full_stack.py`가 냉동 협로 한 곳의 진입·탈출을 본다면, 이 파일은
세 온도 구역을 한 대의 Pinky가 계획 순서대로 방문하고 마지막에 충전소로 돌아오는지를
본다. 기본 pytest에서는 gate와 판정 계약만 실행되고 실제 주행은 skip된다. 실제 주행은
`--enable-full-stack --enable-motion`을 함께 준 경우에만 시작한다.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest


REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from zone_tour_client import (  # noqa: E402
    CHARGER_BY_DEVICE,
    DEFAULT_ZONE_ITEMS,
    DOCK_BY_ZONE,
    ZONE_ORDER,
    GatewayClient,
    TourRequest,
    TourRequestError,
    ZoneTourRunner,
    charger_exit_readiness,
    evaluate_tour,
    load_tour_profiles,
    parse_zone_items,
    tour_order_payload,
    validate_tour_request,
    visited_zone_order,
    worker_completion_pending,
    zone_routing,
)


OPERATIONAL_PROFILE_FILE = REPOSITORY / "config" / "narrow_zones.new_map_2.yaml"
TOUR_PROFILE_FILE = REPOSITORY / "config" / "narrow_zones.new_map_2.zone_tour.yaml"
FROZEN_DOCK = DOCK_BY_ZONE["frozen"]


def _operational_profiles():
    return load_tour_profiles(OPERATIONAL_PROFILE_FILE, map_name="new_map_2")


def _tour_profiles():
    return load_tour_profiles(TOUR_PROFILE_FILE, map_name="new_map_2")


def _request(**changes) -> TourRequest:
    base = TourRequest(
        enable_motion=True,
        enable_full_stack=True,
        device_id="PK_01",
        zone_items=dict(DEFAULT_ZONE_ITEMS),
        packing_worker="W-FIELD-01",
    )
    return replace(base, **changes)


def _job(states: dict[str, str], *, job_state: str = "completed") -> dict:
    """구역별 이동 상태와 복귀 상태만 담은 최소 job 문서를 만든다."""
    steps = []
    step_no = 10
    stalled = False
    for zone in ZONE_ORDER:
        common = {"temperature_zone": zone}
        # 앞 구역이 끝나지 않으면 다음 구역은 시작되지 않는다.
        navigate_state = "pending" if stalled else states.get(zone, "succeeded")
        stalled = stalled or navigate_state != "succeeded"
        steps.append(
            {
                "step_no": step_no,
                "executor_type": "arm",
                "action_type": "prepare",
                "state": "succeeded",
                "input": common,
            }
        )
        steps.append(
            {
                "step_no": step_no + 10,
                "executor_type": "mobile",
                "action_type": "navigate",
                "state": navigate_state,
                "input": common,
            }
        )
        steps.append(
            {
                "step_no": step_no + 20,
                "executor_type": "fms",
                "action_type": "load",
                "state": "succeeded",
                "input": common,
            }
        )
        step_no += 30
    steps.extend(
        (
            {
                "step_no": step_no,
                "executor_type": "mobile",
                "action_type": "navigate",
                "state": "succeeded",
                "input": {},
            },
            {
                "step_no": step_no + 10,
                "executor_type": "fms",
                "action_type": "handover",
                "state": "succeeded",
                "input": {},
            },
            {
                "step_no": step_no + 20,
                "executor_type": "fms",
                "action_type": "wait",
                "state": states.get("wait", "succeeded"),
                "input": {"wait_for": "worker_completion"},
            },
            {
                "step_no": step_no + 30,
                "executor_type": "mobile",
                "action_type": "return_home",
                "state": states.get("return_home", "succeeded"),
                "input": {},
            },
        )
    )
    return {"job_id": 7, "state": job_state, "steps": steps}


# --- 옵션 파싱 ------------------------------------------------------------


def test_zone_items_default_to_one_product_per_temperature_zone() -> None:
    assert parse_zone_items("") == DEFAULT_ZONE_ITEMS
    assert set(DEFAULT_ZONE_ITEMS) == set(ZONE_ORDER)


def test_zone_items_require_every_temperature_zone() -> None:
    with pytest.raises(TourRequestError):
        parse_zone_items("ambient=SKU-MANDARIN,chilled=SKU-YOGURT")


def test_the_same_product_cannot_serve_two_zones() -> None:
    with pytest.raises(TourRequestError):
        parse_zone_items(
            "ambient=SKU-MANDARIN,chilled=SKU-MANDARIN,frozen=SKU-ICEBAR"
        )


def test_an_unknown_zone_name_is_rejected_before_the_order() -> None:
    with pytest.raises(TourRequestError):
        parse_zone_items("ambient=SKU-A,chilled=SKU-B,room=SKU-C")


def test_the_order_visits_one_product_per_zone_in_planner_order() -> None:
    payload = tour_order_payload(
        DEFAULT_ZONE_ITEMS, run_id="abc123", requested_by="W-FIELD-01"
    )

    assert [item["product_code"] for item in payload["items"]] == [
        DEFAULT_ZONE_ITEMS[zone] for zone in ZONE_ORDER
    ]
    assert payload["allow_partial_fulfillment"] is False


# --- 주행 gate ------------------------------------------------------------


def test_the_tour_is_disabled_without_both_explicit_flags() -> None:
    profiles = _tour_profiles()

    assert (
        validate_tour_request(_request(enable_full_stack=False), profiles).reason_code
        == "FULL_STACK_NOT_ENABLED"
    )
    assert (
        validate_tour_request(_request(enable_motion=False), profiles).reason_code
        == "MOTION_NOT_ENABLED"
    )


def test_a_robot_without_a_fixed_charger_cannot_run_the_tour() -> None:
    decision = validate_tour_request(_request(device_id="PK_09"), _tour_profiles())

    assert decision.allowed is False
    assert decision.reason_code == "DEVICE_CHARGER_UNKNOWN"


def test_the_tour_profile_file_routes_every_zone_without_docking() -> None:
    decision = validate_tour_request(_request(), _tour_profiles())

    assert decision.allowed is True, decision.reason
    assert [item.mode for item in decision.routing] == ["nav_only"] * 3
    assert [item.zone for item in decision.routing] == list(ZONE_ORDER)


def test_the_operational_profiles_still_block_the_tour_before_dock_calibration() -> None:
    """상온·냉장은 disabled고 냉동은 탈출 실측 전이므로 운영 표로는 순회하지 않는다."""
    decision = validate_tour_request(_request(), _operational_profiles())

    assert decision.allowed is False
    assert decision.reason_code == "NARROW_PROFILE_DISABLED"
    assert [item.reason_code for item in decision.routing] == [
        "NARROW_PROFILE_DISABLED",
        "NARROW_PROFILE_DISABLED",
        "NARROW_PROFILE_UNMEASURED",
    ]


def test_a_missing_storage_profile_blocks_the_tour() -> None:
    profiles = dict(_tour_profiles())
    del profiles[DOCK_BY_ZONE["chilled"]]

    decision = validate_tour_request(_request(), profiles)

    assert decision.allowed is False
    assert decision.reason_code == "NARROW_PROFILE_MISSING"


def test_a_dock_that_can_be_entered_but_not_left_is_not_routable() -> None:
    """진입만 실측된 창고로는 보내지 않는다. 들어가면 나올 규칙이 없다."""
    profiles = dict(_operational_profiles())
    frozen = profiles[FROZEN_DOCK]
    profiles[FROZEN_DOCK] = frozen.with_measurement(exit=False)

    routing = {item.zone: item for item in zone_routing(profiles)}

    assert routing["frozen"].mode == "narrow_dock"
    assert routing["frozen"].reason_code == "NARROW_PROFILE_UNMEASURED"


def test_a_fully_measured_dock_is_routable_through_the_narrow_rules() -> None:
    profiles = dict(_operational_profiles())
    profiles[FROZEN_DOCK] = profiles[FROZEN_DOCK].with_measurement(exit=True)

    routing = {item.zone: item for item in zone_routing(profiles)}

    assert routing["frozen"].mode == "narrow_dock"
    assert routing["frozen"].routable is True


def test_the_assigned_charger_exit_must_be_measured() -> None:
    profiles = dict(_tour_profiles())
    charger = CHARGER_BY_DEVICE["PK_01"]
    profiles[charger] = profiles[charger].with_measurement(exit=False)

    decision = validate_tour_request(_request(), profiles)

    assert decision.allowed is False
    assert decision.reason_code == "NARROW_PROFILE_UNMEASURED"
    assert charger_exit_readiness(profiles, "PK_01") == "NARROW_PROFILE_UNMEASURED"


# --- 완주 판정 ------------------------------------------------------------


def test_a_finished_tour_reports_every_zone_and_the_return_home() -> None:
    evaluation = evaluate_tour(_job({}))

    assert evaluation["passed"] is True
    assert evaluation["reason_code"] == "COMPLETED"
    assert evaluation["visited"] == ZONE_ORDER


def test_a_zone_that_never_arrived_names_that_zone() -> None:
    evaluation = evaluate_tour(_job({"chilled": "failed"}, job_state="failed"))

    assert evaluation["passed"] is False
    assert evaluation["reason_code"] == "ZONE_CHILLED_FAILED"
    assert evaluation["visited"] == ("ambient",)


def test_a_tour_without_the_charger_return_is_not_a_pass() -> None:
    evaluation = evaluate_tour(_job({"return_home": "running"}, job_state="running"))

    assert evaluation["passed"] is False
    assert evaluation["reason_code"] == "RETURN_HOME_RUNNING"
    assert evaluation["visited"] == ZONE_ORDER


def test_a_completed_ledger_is_required_even_when_every_step_succeeded() -> None:
    evaluation = evaluate_tour(_job({}, job_state="running"))

    assert evaluation["passed"] is False
    assert evaluation["reason_code"] == "JOB_RUNNING"


def test_zone_arrivals_are_read_from_the_step_input_not_the_step_number() -> None:
    job = _job({})
    for step in job["steps"]:
        step["step_no"] += 1000

    assert visited_zone_order(job) == ZONE_ORDER


def test_only_a_running_wait_step_asks_for_the_worker_confirmation() -> None:
    assert worker_completion_pending(_job({"wait": "running"})) is True
    assert worker_completion_pending(_job({"wait": "pending"})) is False
    assert worker_completion_pending(_job({})) is False


# --- 실기 순회 ------------------------------------------------------------


@pytest.mark.hardware
@pytest.mark.integration
def test_one_pinky_tours_three_zones_and_returns_to_the_charger(pytestconfig) -> None:
    """주문 한 건으로 상온→냉장→냉동을 돌고 충전소까지 복귀하는지 확인한다.

    사람이 하는 일은 두 가지다. 각 창고 도착 뒤 물건을 바구니에 올리는 것과,
    실패했을 때 물리 비상정지를 누르는 것이다. 포장 완료 확인(fms/wait)만 이
    테스트가 대신 호출하며, 실패·중단 시 만든 주문은 반드시 취소한다.
    """
    enable_full_stack = pytestconfig.getoption("--enable-full-stack")
    enable_motion = pytestconfig.getoption("--enable-motion")
    if not enable_full_stack:
        pytest.skip("--enable-full-stack이 없어 실기 주문을 만들지 않는다")

    profile_file = Path(pytestconfig.getoption("--narrow-zones-file"))
    if not profile_file.is_absolute():
        profile_file = REPOSITORY / profile_file
    profiles = load_tour_profiles(
        profile_file, map_name=pytestconfig.getoption("--narrow-map-name")
    )
    request = TourRequest(
        enable_motion=enable_motion,
        enable_full_stack=enable_full_stack,
        device_id=pytestconfig.getoption("--device-id"),
        zone_items=parse_zone_items(pytestconfig.getoption("--zone-items")),
        packing_worker=pytestconfig.getoption("--packing-worker"),
    )
    decision = validate_tour_request(request, profiles)
    assert decision.allowed, f"{decision.reason_code}: {decision.reason}"

    artifacts = Path(pytestconfig.getoption("--tour-artifacts"))
    if not artifacts.is_absolute():
        artifacts = REPOSITORY / artifacts
    runner = ZoneTourRunner(
        GatewayClient(pytestconfig.getoption("--fms-url")),
        request,
        artifacts_dir=artifacts,
    )
    result = runner.run(timeout_s=pytestconfig.getoption("--full-stack-timeout"))

    assert result.passed, (
        f"{result.reason_code}: {result.message}; job={result.job_id} "
        f"trace={result.trace_path}"
    )
