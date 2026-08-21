"""Contract tests for the worker that closes OMX and FMS steps."""

import pytest

from control_tower.gateway.fms_client import (
    ExecutorDispatch,
    StepOutcomeResponse,
)
from control_tower.task_manager.executor_worker import (
    EXECUTOR_CHANNELS,
    ExecutorWorker,
)


def _dispatch(
    job_step_id=100,
    *,
    action_type="prepare",
    executor_type="arm",
    channel="omx",
    device="OMX_01",
    revision=1,
    payload=None,
):
    return ExecutorDispatch(
        message_id=f"message-{job_step_id}",
        job_id=7,
        job_step_id=job_step_id,
        channel=channel,
        message_type="execute_action",
        action_type=action_type,
        executor_type=executor_type,
        payload=payload
        if payload is not None
        else {"input": {"temperature_zone": "chilled", "product_codes": ["SKU-1"]}},
        assigned_device_id=device,
        assignment_revision=revision,
        assignment={"omx_id": "OMX_01", "mobile_id": "PK_01"},
    )


class FakeSimulator:
    def __init__(self, omx_id="OMX_01", fail_with=None, result=None):
        self._omx_id = omx_id
        self.commands = []
        self._fail_with = fail_with
        self._result = result

    @property
    def state(self):
        return "OMX_READY"

    def execute(self, command):
        if self._fail_with is not None:
            raise self._fail_with
        self.commands.append(command)
        if self._result is not None:
            return self._result
        return {
            "success": True,
            "policy_completed": True,
            "items": [
                {
                    "job_item_id": item["job_item_id"],
                    "grasp_confirmed": True,
                    "release_confirmed": True,
                    "policy_completed": True,
                    "evidence_refs": [f"omx_result:{item['job_item_id']}"],
                }
                for item in command["items"]
            ],
        }


class FakeGateway:
    def __init__(self, dispatches, fail_outcome_with=None, items=None):
        self._dispatches = tuple(dispatches)
        self.claims = []
        self.outcomes = []
        self.fail_outcome_with = fail_outcome_with
        self._items = items if items is not None else [
            {"job_item_id": 11, "product_code": "SKU-1", "requested_qty": 1}
        ]

    def claim_executor_dispatches(self, request):
        self.claims.append(request)
        return self._dispatches

    def record_executor_outcome(self, job_step_id, request, *, idempotency_key):
        if self.fail_outcome_with is not None:
            raise self.fail_outcome_with
        self.outcomes.append((job_step_id, request, idempotency_key))
        return StepOutcomeResponse(
            job_step_id=job_step_id,
            job_id=7,
            state="succeeded" if request.outcome == "succeeded" else "failed",
            attempt_uuid="attempt-1",
            attempt_no=1,
        )

    def get_job(self, job_id):
        return JobDetailResponse(
            job_id=job_id,
            job_code="JOB-1",
            state="assigned",
            items=tuple(self._items),
        )


def _worker(gateway, simulators=None, **kwargs):
    return ExecutorWorker(
        gateway,
        simulators=simulators if simulators is not None else {"OMX_01": FakeSimulator()},
        **kwargs,
    )


def test_a_pick_is_executed_by_the_arm_and_then_closed() -> None:
    """The gap this worker closes: an arm step could never leave `pending`."""
    simulator = FakeSimulator()
    gateway = FakeGateway([_dispatch()])

    report = _worker(gateway, {"OMX_01": simulator}).run_once()

    assert report.succeeded == (100,)
    assert len(simulator.commands) == 1
    assert simulator.commands[0]["kind"] == "prepare"
    assert simulator.commands[0]["omx_id"] == "OMX_01"
    _, request, _ = gateway.outcomes[0]
    assert request.outcome == "succeeded"
    assert request.assignment_revision == 1


def test_the_worker_claims_only_its_own_channels() -> None:
    """`rmf` belongs to the RMF worker; claiming it would steal navigation."""
    gateway = FakeGateway([])

    _worker(gateway).run_once()

    assert gateway.claims[0].channels == EXECUTOR_CHANNELS
    assert "rmf" not in gateway.claims[0].channels


def test_a_wait_step_is_left_for_the_packing_worker() -> None:
    """A background process must never sign off work a human confirms."""
    gateway = FakeGateway(
        [_dispatch(action_type="wait", executor_type="fms", channel="pinky", device=None)]
    )

    report = _worker(gateway).run_once()

    assert gateway.outcomes == []
    assert report.succeeded == ()
    assert any("awaits the worker" in item for item in report.deferred)


def test_an_fms_step_is_closed_without_an_arm() -> None:
    gateway = FakeGateway(
        [_dispatch(action_type="handover", executor_type="fms", channel="pinky", device=None)]
    )

    report = _worker(gateway).run_once()

    assert report.succeeded == (100,)
    _, request, _ = gateway.outcomes[0]
    assert request.method_code == "FMS_LEDGER_CONTRACT"
    assert request.actor_device_id is None


def test_the_outcome_key_is_stable_for_the_same_step_and_revision() -> None:
    """A retry after a lost response must not close the step twice."""
    gateway = FakeGateway([_dispatch()])
    worker = _worker(gateway)

    worker.run_once()
    worker.run_once()

    keys = {key for _, _, key in gateway.outcomes}
    assert len(gateway.outcomes) == 2
    assert len(keys) == 1


def test_a_new_assignment_revision_gets_a_new_key() -> None:
    """A reassigned step is different work and deserves its own attempt."""
    gateway = FakeGateway([_dispatch(revision=1), _dispatch(revision=2)])

    _worker(gateway).run_once()

    keys = {key for _, _, key in gateway.outcomes}
    assert len(keys) == 2


def test_every_sample_carries_its_environment() -> None:
    """Simulated runs must never calibrate the hardware duration model."""
    gateway = FakeGateway([_dispatch()])

    _worker(gateway, environment="simulation").run_once()

    _, request, _ = gateway.outcomes[0]
    assert request.metrics["duration"]["environment"] == "simulation"


def test_a_pick_records_its_grasp_segment() -> None:
    """Decomposed time is what the duration baseline is built from."""
    # total 은 바깥에서, grasp 는 팔 실행 구간에서 각각 두 번 읽는다.
    ticks = iter((1_000, 1_020, 1_050, 1_080))
    gateway = FakeGateway([_dispatch()])

    _worker(gateway, clock_ms=lambda: next(ticks)).run_once()

    duration = gateway.outcomes[0][1].metrics["duration"]
    assert duration["segments"]["grasp_ms"] == 30
    assert duration["total_ms"] == 80


def test_a_missing_simulator_is_reported_not_silently_succeeded() -> None:
    """Reporting success for an arm that never ran would corrupt the samples."""
    gateway = FakeGateway([_dispatch(device="OMX_09")])

    report = _worker(gateway).run_once()

    assert gateway.outcomes == []
    assert any("step 100" in error for error in report.errors)


def test_one_failing_dispatch_does_not_stop_the_cycle() -> None:
    gateway = FakeGateway([_dispatch(101, device="OMX_09"), _dispatch(102)])

    report = _worker(gateway).run_once()

    assert report.succeeded == (102,)
    assert len(report.errors) == 1


def test_an_arm_falls_back_to_the_job_assignment_for_its_identity() -> None:
    simulator = FakeSimulator()
    gateway = FakeGateway([_dispatch(device=None)])

    _worker(gateway, {"OMX_01": simulator}).run_once()

    assert simulator.commands[0]["omx_id"] == "OMX_01"


def test_expected_items_come_from_the_step_input() -> None:
    simulator = FakeSimulator()
    gateway = FakeGateway(
        [
            _dispatch(
                payload={
                    "input": {
                        "temperature_zone": "chilled",
                        "product_codes": ["SKU-A", "SKU-B"],
                    }
                }
            )
        ],
        items=[
            {"job_item_id": 11, "product_code": "SKU-A", "requested_qty": 1},
            {"job_item_id": 12, "product_code": "SKU-B", "requested_qty": 2},
        ],
    )

    _worker(gateway, {"OMX_01": simulator}).run_once()

    assert simulator.commands[0]["items"] == [
        {"job_item_id": 11, "product_code": "SKU-A", "quantity": 1},
        {"job_item_id": 12, "product_code": "SKU-B", "quantity": 2},
    ]


def test_a_non_positive_limit_is_rejected() -> None:
    with pytest.raises(ValueError):
        _worker(FakeGateway([])).run_once(limit=0)


# --- 적재 확정 경로 -----------------------------------------------------------
#
# 2026-08-19: 이 경로에 테스트가 없어서 오타 수준의 실수 세 개가 실제 주행에서만
# 드러났고, 그때마다 outbox 5회를 소진해 회차를 통째로 잃었다.
#   - `list_devices()` 를 중복 정의해 기존 `DeviceSummary` 반환이 이겼다
#   - `get_job()` 도 같은 실수. `JobDetailResponse` 에 dict 처럼 접근했다
#   - `record_load_attempt` 구현이 Protocol 클래스 안에 들어가 실제 클라이언트에 없었다
#
# 앞의 둘은 **진짜 반환 타입을 쓰는 fake** 로 잡고, 셋째는 **Protocol 이행 검사**로
# 잡는다. 손으로 만든 fake 는 셋째를 절대 못 잡는다.

from dataclasses import replace

from control_tower.gateway.fms_client import (
    ExecutorGatewayClient,
    FMSGatewayHttpClient,
    JobDetailResponse,
    LoadAttemptResponse,
)

def _load_dispatch(**overrides):
    base = _dispatch(
        4,
        action_type="load",
        executor_type="fms",
        channel="pinky",
        device="PK_01",
        payload={
            "input": {
                "handover_group_id": "group-1",
                "temperature_zone": "chilled",
                "dock_location_id": 26,
            }
        },
    )
    return replace(base, **overrides)


class LoadGateway(FakeGateway):
    """적재 경로를 위한 fake. **진짜 반환 타입**을 쓴다 — dict 로 흉내 내면
    운영에서만 터지는 속성 접근 오류를 테스트가 놓친다."""

    def __init__(self, dispatches, *, items=None):
        resolved_items = items if items is not None else [
            {"job_item_id": 11, "product_code": "SKU-A", "requested_qty": 1},
            {"job_item_id": 12, "product_code": "SKU-B", "requested_qty": 1},
        ]
        super().__init__(dispatches, items=resolved_items)
        self.load_attempts = []

    def list_devices(self):
        raise AssertionError("load evidence must not read Pinky cargo state")

    def record_load_attempt(self, job_step_id, request, *, idempotency_key):
        self.load_attempts.append((job_step_id, request, idempotency_key))
        return LoadAttemptResponse(departure_allowed=request.result == "LOAD_CONFIRMED")


def test_a_confirmed_omx_result_closes_the_load_step_with_one_attempt_per_item() -> None:
    gateway = LoadGateway([_load_dispatch()])

    report = _worker(gateway).run_once()

    assert report.succeeded == (4,)
    assert [attempt[0] for attempt in gateway.load_attempts] == [4, 4]
    submitted = [attempt[1] for attempt in gateway.load_attempts]
    assert [request.item_id for request in submitted] == [11, 12]
    assert {request.result for request in submitted} == {"LOAD_CONFIRMED"}
    assert submitted[0].criteria == {
        "grasp_confirmed": True,
        "release_confirmed": True,
        "policy_completed": True,
    }
    assert submitted[0].observations["job_item_id"] == 11
    assert submitted[0].evidence_refs == ("omx_result:11",)
    assert submitted[0].pinky_id == "PK_01"
    assert submitted[0].omx_id == "OMX_01"
    assert submitted[0].handover_group_id == "group-1"


def test_a_load_step_commands_the_prepared_omx_before_recording_cargo() -> None:
    """Removing the OMX ``load`` command must leave Step 30 open.

    Step 10 prepares the item and Step 20 confirms Pinky's arrival.  Step 30
    is the only point that authorizes the arm to transfer the prepared item.
    A cargo observation alone must not make that transfer look as if it ran.
    """
    simulator = FakeSimulator(omx_id="OMX_01")
    gateway = LoadGateway(
        [
            _dispatch(
                payload={
                    "input": {
                        "temperature_zone": "chilled",
                        "product_codes": ["SKU-A", "SKU-B"],
                    }
                }
            ),
            _load_dispatch(),
        ]
    )

    report = _worker(gateway, {"OMX_01": simulator}).run_once()

    assert report.succeeded == (100, 4)
    assert [command["kind"] for command in simulator.commands] == ["prepare", "load"]


def test_a_frozen_load_uses_its_zone_workcell_instead_of_the_job_default() -> None:
    """냉동 ZoneBundle의 Step 30은 OMX_02에만 load를 보낸다."""
    simulator = FakeSimulator(omx_id="OMX_02")
    gateway = LoadGateway(
        [
            _load_dispatch(
                payload={
                    "input": {
                        "handover_group_id": "group-frozen",
                        "temperature_zone": "frozen",
                        "omx_id": "OMX_02",
                    }
                }
            )
        ]
    )

    report = _worker(gateway, {"OMX_02": simulator}).run_once()

    assert report.succeeded == (4,)
    assert simulator.commands[0]["kind"] == "load"
    assert simulator.commands[0]["omx_id"] == "OMX_02"
    assert gateway.load_attempts[0][1].omx_id == "OMX_02"


def test_partial_omx_evidence_blocks_departure_without_writing_attempts() -> None:
    result = {
        "success": True,
        "policy_completed": True,
        "items": [
            {
                "job_item_id": 11,
                "grasp_confirmed": True,
                "release_confirmed": False,
                "policy_completed": True,
                "evidence_refs": [],
            }
        ],
    }
    gateway = LoadGateway([_load_dispatch()])

    report = _worker(
        gateway, {"OMX_01": FakeSimulator(result=result)}
    ).run_once()

    assert report.succeeded == ()
    assert report.failed == ()
    assert any("incomplete OMX load evidence" in error for error in report.errors)
    assert gateway.load_attempts == []
    assert gateway.outcomes == []


def test_a_load_step_without_handover_identity_is_an_error() -> None:
    gateway = LoadGateway(
        [_load_dispatch(payload={"input": {"temperature_zone": "chilled"}})]
    )

    report = _worker(gateway).run_once()

    assert report.succeeded == ()
    assert any("handover identity" in error for error in report.errors)
    assert gateway.load_attempts == []


def test_the_http_client_implements_every_executor_method() -> None:
    """Protocol 에 선언한 것이 실제 클라이언트에 있는지 본다.

    손으로 만든 fake 는 이것을 못 잡는다 — fake 가 메서드를 갖고 있으면 통과하고,
    운영에서 진짜 클라이언트만 터진다. 2026-08-19 에 `record_load_attempt` 구현이
    Protocol 클래스 안으로 들어가 실제 클라이언트에 없던 사고가 그것이다.
    """
    declared = {
        name
        for name, value in vars(ExecutorGatewayClient).items()
        if callable(value) and not name.startswith("_")
    }
    assert declared, "Protocol 에서 메서드를 하나도 읽지 못했다"
    missing = [name for name in sorted(declared) if not hasattr(FMSGatewayHttpClient, name)]
    assert missing == [], f"실제 클라이언트에 없는 메서드: {missing}"


def test_the_load_request_satisfies_the_gateway_schema() -> None:
    """실행기가 만든 요청을 **Gateway 의 진짜 pydantic 모델**로 검증한다.

    가짜 게이트웨이는 무엇을 받든 통과시키므로, 서버가 요구하는 필드가 빠진 것을
    못 잡는다. 2026-08-19 에 `metrics`·`evidence_refs`·`policy_name`·
    `policy_version`·`model_name`·`model_version` 여섯 개를 빠뜨려 실제 주행에서만
    `HTTP 422` 로 드러났고, 그 회차를 통째로 잃었다.
    """
    from dataclasses import asdict

    from control_tower.gateway.fms_client import _omit_none

    pydantic_model = pytest.importorskip("fms_gateway.app.models")

    gateway = LoadGateway([_load_dispatch()], items=[{"job_item_id": 11}])
    _worker(gateway).run_once()
    assert gateway.load_attempts, "적재 증거가 제출되지 않았다"

    _, request, _ = gateway.load_attempts[0]
    body = _omit_none(asdict(request))
    # 검증이 통과하지 못하면 어떤 필드가 문제인지 그대로 드러낸다.
    pydantic_model.LoadAttemptRequest.model_validate(body)
