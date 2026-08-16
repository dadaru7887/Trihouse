"""Real MySQL load evidence, recovery, replay, and completion gates."""

import json

import pytest

from conftest import mysql_connection
from fms_gateway.app.repositories import (
    IdempotencyConflict,
    MySqlFmsRepository,
    PickRecoveryConflict,
    WorkerCompletionConflict,
)
from test_outbound_order_repository import install_active_map, rows, scalar
from test_worker_completion_repository import (
    ASSIGNMENT,
    _ConnectionDatabase,
    _create_order,
    _repository,
    _request,
)


pytestmark = pytest.mark.integration


def _identity(job_id: int) -> tuple[int, int, str]:
    item = rows(
        """
        SELECT item.job_item_id, lot.temperature_zone
        FROM job_items item JOIN inventory_lots lot ON lot.lot_id=item.lot_id
        WHERE item.job_id=%s ORDER BY item.job_item_id LIMIT 1
        """,
        (job_id,),
    )[0]
    step = rows(
        """
        SELECT job_step_id, input FROM job_steps
        WHERE job_id=%s AND action_type='load'
          AND JSON_UNQUOTE(JSON_EXTRACT(input, '$.temperature_zone'))=%s
        """,
        (job_id, item["temperature_zone"]),
    )[0]
    payload = json.loads(step["input"]) if isinstance(step["input"], str) else step["input"]
    return int(item["job_item_id"]), int(step["job_step_id"]), payload["handover_group_id"]


def _attempt(job_id: int, item_id: int, group: str, *, result="LOAD_CONFIRMED") -> dict:
    return {
        "attempt_id": "00000000-0000-0000-0000-000000000201",
        "job_id": job_id,
        "item_id": item_id,
        "handover_group_id": group,
        "assignment_revision": 1,
        "pinky_id": "PK_01",
        "omx_id": "OMX_01",
        "result": result,
        "criteria": {"expected_item": True, "inside_payload": True},
        "observations": {"qr": "observed", "aruco": 17},
        "metrics": {"confidence": 0.99, "latency_ms": 12},
        "evidence_refs": ["fixture://load/201"],
        "policy_name": "load-contract",
        "policy_version": "1",
        "model_name": "fixture-observer",
        "model_version": "1",
    }


def test_attempt_persists_complete_canonical_ledger_and_restarts_idempotently(
    seeded_schema,
) -> None:
    install_active_map()
    job_id = _create_order("attempt-ledger", external_reference="TASK6-ATTEMPT")
    _repository().assign_job_resources(job_id, ASSIGNMENT)
    item_id, step_id, group = _identity(job_id)
    request = _attempt(job_id, item_id, group)

    first = _repository().record_load_attempt(step_id, request, "load-attempt-201")
    replay = MySqlFmsRepository(_ConnectionDatabase()).record_load_attempt(
        step_id, request, "load-attempt-201"
    )

    assert replay == first
    ledger = rows(
        """
        SELECT criteria, metrics, before_observation, evidence_refs,
               policy_name, policy_version, model_name, model_version,
               outcome_reason_code, parameters
        FROM job_step_attempts WHERE attempt_uuid=%s
        """,
        (request["attempt_id"],),
    )[0]
    assert ledger["outcome_reason_code"] == "LOAD_CONFIRMED"
    assert all(ledger[field] is not None for field in (
        "criteria", "metrics", "before_observation", "evidence_refs",
        "policy_name", "policy_version", "model_name", "model_version",
    ))
    params = json.loads(ledger["parameters"]) if isinstance(ledger["parameters"], str) else ledger["parameters"]
    assert params["handover_group_id"] == group
    with pytest.raises(IdempotencyConflict):
        _repository().record_load_attempt(
            step_id, {**request, "metrics": {"confidence": 0.5}}, "load-attempt-201"
        )


def test_drop_hold_blocks_retry_departure_and_completion_until_both_clear_facts(
    seeded_schema,
) -> None:
    install_active_map()
    job_id = _create_order("drop-hold", external_reference="TASK6-DROP")
    repository = _repository()
    repository.assign_job_resources(job_id, ASSIGNMENT)
    item_id, step_id, group = _identity(job_id)
    repository.record_load_attempt(
        step_id, _attempt(job_id, item_id, group, result="DROP_DETECTED"), "drop-201"
    )
    recovery = {"job_id": job_id, "item_id": item_id, "operator_id": "W-OP-01"}

    with pytest.raises(PickRecoveryConflict, match="ACTIVE_DROP_HOLD"):
        repository.record_pick_recovery(step_id, {**recovery, "choice": "재시도"}, "retry-held")
    repository.record_pick_recovery(
        step_id, {**recovery, "fact": "object-recovered"}, "drop-object"
    )
    with pytest.raises(PickRecoveryConflict, match="ACTIVE_DROP_HOLD"):
        repository.record_pick_recovery(step_id, {**recovery, "choice": "재시도"}, "retry-half")
    cleared = repository.record_pick_recovery(
        step_id, {**recovery, "fact": "area-clear"}, "drop-area"
    )
    retry = repository.record_pick_recovery(
        step_id, {**recovery, "choice": "재시도"}, "retry-cleared"
    )

    assert cleared["drop_hold"] is False
    assert retry["retry_no"] == 1
    assert retry["reobserve_qr_aruco"] is True
    assert retry["reset_act_episode"] is True


def test_worker_completion_requires_load_confirmed_or_acknowledged_manual_path(
    seeded_schema,
) -> None:
    install_active_map()
    job_id = _create_order("completion-gate", external_reference="TASK6-COMPLETE-GATE")
    repository = _repository()
    repository.assign_job_resources(job_id, ASSIGNMENT)
    connection = mysql_connection(database="trihouse_fms")
    cursor = connection.cursor()
    try:
        cursor.execute(
            "UPDATE job_steps SET state=CASE WHEN action_type='wait' THEN 'running' "
            "WHEN action_type='return_home' THEN 'pending' ELSE 'succeeded' END WHERE job_id=%s",
            (job_id,),
        )
        cursor.execute("UPDATE jobs SET state='running' WHERE job_id=%s", (job_id,))
        connection.commit()
    finally:
        cursor.close(); connection.close()

    with pytest.raises(WorkerCompletionConflict, match="LOAD_CONFIRMATION_REQUIRED"):
        repository.complete_worker_packing(job_id, _request(), "completion-without-load")

    for item in rows("SELECT job_item_id FROM job_items WHERE job_id=%s", (job_id,)):
        item_id = int(item["job_item_id"])
        _, step_id, group = _identity_for_item(job_id, item_id)
        request = _attempt(job_id, item_id, group)
        request["attempt_id"] = f"00000000-0000-0000-0000-{item_id:012d}"
        repository.record_load_attempt(step_id, request, f"load-item-{item_id}")

    completed = repository.complete_worker_packing(job_id, _request(), "completion-with-load")
    assert completed["state"] == "running"
    assert scalar(
        "SELECT COUNT(*) FROM job_steps WHERE job_id=%s AND action_type='wait' AND state='succeeded'",
        (job_id,),
    ) == 1


def _identity_for_item(job_id: int, item_id: int) -> tuple[int, int, str]:
    zone = rows(
        "SELECT lot.temperature_zone FROM job_items item JOIN inventory_lots lot ON lot.lot_id=item.lot_id WHERE item.job_item_id=%s",
        (item_id,),
    )[0]["temperature_zone"]
    step = rows(
        "SELECT job_step_id, input FROM job_steps WHERE job_id=%s AND action_type='load' AND JSON_UNQUOTE(JSON_EXTRACT(input, '$.temperature_zone'))=%s",
        (job_id, zone),
    )[0]
    payload = json.loads(step["input"]) if isinstance(step["input"], str) else step["input"]
    return item_id, int(step["job_step_id"]), payload["handover_group_id"]
