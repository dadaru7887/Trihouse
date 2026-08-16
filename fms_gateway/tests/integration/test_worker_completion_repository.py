"""MySQL assignment and worker-completion transaction tests."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import json
import threading

import pytest

from conftest import mysql_connection
from fms_gateway.app.repositories import (
    IdempotencyConflict,
    JobStepNotDispatchable,
    ManualAcknowledgementRequired,
    MySqlFmsRepository,
    ResourceAssignmentConflict,
    ResourceUnavailable,
)
from test_outbound_order_repository import DEMO_ORDERS, install_active_map, rows, scalar
from test_read_api import real_client


pytestmark = pytest.mark.integration


ASSIGNMENT = {
    "revision": 1,
    "mobile_id": "PK_01",
    "omx_id": "OMX_01",
    "packing_dock_code": "PACKING-01-DOCK-01",
    "charger_code": "TRIHOUSE-TEST-01-CHG-01",
}

DOCK_2_ASSIGNMENT = {
    **ASSIGNMENT,
    "packing_dock_code": "PACKING-01-DOCK-02",
}


class _ConnectionDatabase:
    @contextmanager
    def connection(self):
        connection = mysql_connection(database="trihouse_fms")
        try:
            yield connection
        finally:
            connection.close()


class _CursorProxy:
    def __init__(self, cursor, *, locks: list[str] | None = None, fail_return=False):
        self._cursor = cursor
        self._locks = locks
        self._fail_return = fail_return

    def execute(self, operation, params=None, *args, **kwargs):
        normalized = " ".join(str(operation).split())
        if self._locks is not None and "FOR UPDATE" in normalized:
            table = next(
                (
                    name
                    for marker, name in (
                        ("FROM jobs", "job"),
                        ("FROM job_steps", "steps"),
                        ("FROM job_items", "items"),
                        ("FROM inventory_lots", "lots"),
                        ("FROM reservations", "reservations"),
                        ("FROM job_step_attempts", "attempts"),
                    )
                    if marker in normalized
                ),
                None,
            )
            if table is not None:
                self._locks.append(table)
        if (
            self._fail_return
            and "INSERT INTO integration_messages" in normalized
            and params is not None
            and "return_home" in params
        ):
            raise RuntimeError("injected return enqueue failure")
        return self._cursor.execute(operation, params, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _ConnectionProxy:
    def __init__(self, connection, *, locks=None, fail_return=False):
        self._connection = connection
        self._locks = locks
        self._fail_return = fail_return

    def cursor(self, *args, **kwargs):
        return _CursorProxy(
            self._connection.cursor(*args, **kwargs),
            locks=self._locks,
            fail_return=self._fail_return,
        )

    def __getattr__(self, name):
        return getattr(self._connection, name)


class _InstrumentedDatabase:
    def __init__(self, *, locks: list[str] | None = None, fail_return=False):
        self._locks = locks
        self._fail_return = fail_return

    @contextmanager
    def connection(self):
        connection = mysql_connection(database="trihouse_fms")
        try:
            yield _ConnectionProxy(
                connection, locks=self._locks, fail_return=self._fail_return
            )
        finally:
            connection.close()


def _repository(database=None) -> MySqlFmsRepository:
    return MySqlFmsRepository(database or _ConnectionDatabase())


def _create_order(
    key: str, *, external_reference: str, product_code: str | None = None
) -> int:
    request = deepcopy(DEMO_ORDERS[5]["request"])
    request["external_reference"] = external_reference
    if product_code is not None:
        request["items"] = [{"product_code": product_code, "quantity": 1}]
    response = real_client().post(
        "/api/v1/orders",
        headers={"Idempotency-Key": f"task6-order-{key}"},
        json=request,
    )
    assert response.status_code == 201, response.text
    return int(response.json()["job_id"])


def _prepare_job(key: str, *, manual_required: bool = False) -> int:
    job_id = _create_order(key, external_reference=f"TASK6-{key}")
    _repository().assign_job_resources(job_id, ASSIGNMENT)
    connection = mysql_connection(database="trihouse_fms")
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            UPDATE job_steps
            SET state = CASE
              WHEN action_type = 'wait' THEN 'running'
              WHEN action_type = 'return_home' THEN 'pending'
              ELSE 'succeeded'
            END
            WHERE job_id = %s
            """,
            (job_id,),
        )
        cursor.execute(
            "UPDATE jobs SET state = 'running' WHERE job_id = %s", (job_id,)
        )
        if manual_required:
            cursor.execute(
                """
                UPDATE job_items
                SET verification_state = 'manual_review',
                    metadata = JSON_SET(
                      COALESCE(metadata, JSON_OBJECT()),
                      '$.fulfillment_state', 'MANUAL_FULFILLMENT_REQUIRED'
                    )
                WHERE job_id = %s
                """,
                (job_id,),
            )
        connection.commit()
    finally:
        cursor.close()
        connection.close()
    _record_item_load_states(job_id, manual_required=manual_required)
    return job_id


def _record_item_load_states(job_id: int, *, manual_required: bool = False) -> None:
    repository = _repository()
    item_steps = rows(
        """
        SELECT item.job_item_id, step.job_step_id, step.input
        FROM job_items item
        JOIN inventory_lots lot ON lot.lot_id=item.lot_id
        JOIN job_steps step ON step.job_id=item.job_id AND step.action_type='load'
          AND JSON_UNQUOTE(JSON_EXTRACT(step.input, '$.temperature_zone'))
              = lot.temperature_zone
        WHERE item.job_id=%s ORDER BY item.job_item_id
        """,
        (job_id,),
    )
    for row in item_steps:
        item_id = int(row["job_item_id"])
        payload = json.loads(row["input"]) if isinstance(row["input"], str) else row["input"]
        result = "LOAD_UNCERTAIN" if manual_required else "LOAD_CONFIRMED"
        repository.record_load_attempt(
            int(row["job_step_id"]),
            {
                "attempt_id": f"10000000-0000-0000-0000-{item_id:012d}",
                "job_id": job_id,
                "item_id": item_id,
                "handover_group_id": payload["handover_group_id"],
                "assignment_revision": 1,
                "pinky_id": "PK_01",
                "omx_id": "OMX_01",
                "result": result,
                "criteria": {"expected_item": True},
                "observations": {"fixture": "worker-completion"},
                "metrics": {"confidence": 1.0},
                "evidence_refs": [f"fixture://worker-completion/{item_id}"],
                "policy_name": "load-contract",
                "policy_version": "1",
                "model_name": "fixture-observer",
                "model_version": "1",
            },
            f"worker-load-{job_id}-{item_id}",
        )
        if manual_required:
            repository.record_pick_recovery(
                int(row["job_step_id"]),
                {
                    "job_id": job_id,
                    "item_id": item_id,
                    "operator_id": "W-OP-01",
                    "choice": "포장대에서 처리",
                },
                f"worker-manual-{job_id}-{item_id}",
            )


def _request(*, acknowledgements: list[int] | None = None, note="packed") -> dict:
    return {
        "worker_id": "W-OP-01",
        "completion_note": note,
        "acknowledged_manual_item_ids": acknowledgements or [],
    }


def _quantities(job_id: int) -> list[dict]:
    return rows(
        """
        SELECT lot.lot_id, lot.available_qty, lot.reserved_qty,
               item.completed_qty
        FROM job_items item
        JOIN inventory_lots lot ON lot.lot_id = item.lot_id
        WHERE item.job_id = %s
        ORDER BY lot.lot_id, item.job_item_id
        """,
        (job_id,),
    )


def test_assignment_persists_every_resource_and_revision_before_dispatch(
    seeded_schema,
) -> None:
    install_active_map()
    job_id = _create_order("assignment", external_reference="TASK6-ASSIGNMENT")

    result = _repository().assign_job_resources(job_id, ASSIGNMENT)

    assert result == {"job_id": job_id, **ASSIGNMENT}
    job = rows(
        "SELECT assigned_mobile_id, destination_location_id, context FROM jobs WHERE job_id=%s",
        (job_id,),
    )[0]
    context = json.loads(job["context"]) if isinstance(job["context"], str) else job["context"]
    assert job["assigned_mobile_id"] == "PK_01"
    assert context["assignment"] == ASSIGNMENT
    assert scalar(
        "SELECT COUNT(*) FROM reservations WHERE job_id=%s AND state='reserved'",
        (job_id,),
    ) == 3
    assert {
        row["assigned_device_id"]
        for row in rows(
            "SELECT DISTINCT assigned_device_id FROM job_steps WHERE job_id=%s",
            (job_id,),
        )
    } == {"PK_01", "OMX_01", None}


def test_dock_2_assignment_rebinds_packing_steps_payload_completion_and_release(
    seeded_schema,
) -> None:
    install_active_map()
    job_id = _create_order("dock-2", external_reference="TASK6-DOCK-2")
    dock_ids = {
        row["location_code"]: row["location_id"]
        for row in rows(
            "SELECT location_id, location_code FROM locations "
            "WHERE location_code IN ('PACKING-01-DOCK-01','PACKING-01-DOCK-02')"
        )
    }

    _repository().assign_job_resources(job_id, DOCK_2_ASSIGNMENT)

    packing_steps = rows(
        """
        SELECT action_type, target_location_id, input
        FROM job_steps
        WHERE job_id=%s AND action_type IN ('navigate','handover','wait')
        ORDER BY step_no DESC LIMIT 3
        """,
        (job_id,),
    )
    assert {row["action_type"] for row in packing_steps} == {"navigate", "handover", "wait"}
    assert {int(row["target_location_id"]) for row in packing_steps} == {dock_ids["PACKING-01-DOCK-02"]}
    for step in packing_steps:
        payload = json.loads(step["input"]) if isinstance(step["input"], str) else step["input"]
        assert payload["packing_dock_location_id"] == dock_ids["PACKING-01-DOCK-02"]

    connection = mysql_connection(database="trihouse_fms")
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            UPDATE job_steps SET state = CASE
              WHEN action_type='wait' THEN 'running'
              WHEN action_type='return_home' THEN 'pending'
              ELSE 'succeeded' END
            WHERE job_id=%s
            """,
            (job_id,),
        )
        cursor.execute("UPDATE jobs SET state='running' WHERE job_id=%s", (job_id,))
        connection.commit()
    finally:
        cursor.close()
        connection.close()

    _record_item_load_states(job_id)

    response = _repository().complete_worker_packing(
        job_id, _request(), "task6-dock-2-complete"
    )

    assert response["destination_location_id"] == dock_ids["PACKING-01-DOCK-02"]
    assert rows(
        "SELECT state FROM reservations WHERE job_id=%s AND location_id=%s",
        (job_id, dock_ids["PACKING-01-DOCK-02"]),
    ) == [{"state": "released"}]


def test_reassignment_retains_own_resources_and_requires_exact_next_revision(
    seeded_schema,
) -> None:
    install_active_map()
    job_id = _create_order("reassign-retain", external_reference="TASK6-REASSIGN-RETAIN")
    repository = _repository()
    repository.assign_job_resources(job_id, ASSIGNMENT)

    retained = repository.assign_job_resources(job_id, {**ASSIGNMENT, "revision": 2})

    assert retained["revision"] == 2
    assert scalar(
        "SELECT COUNT(*) FROM reservations WHERE job_id=%s AND state='reserved'",
        (job_id,),
    ) == 3
    with pytest.raises(ResourceAssignmentConflict, match="ASSIGNMENT_REVISION_GAP"):
        repository.assign_job_resources(job_id, {**ASSIGNMENT, "revision": 4})


def test_reassignment_conflict_rolls_back_old_assignment_and_active_steps_block_it(
    seeded_schema,
) -> None:
    install_active_map()
    job_a = _create_order("reassign-a", external_reference="TASK6-REASSIGN-A")
    job_b = _create_order(
        "reassign-b",
        external_reference="TASK6-REASSIGN-B",
        product_code="SKU-STRAWBERRY",
    )
    repository = _repository()
    repository.assign_job_resources(job_a, ASSIGNMENT)
    repository.assign_job_resources(
        job_b,
        {
            "revision": 1,
            "mobile_id": "PK_02",
            "omx_id": "OMX_02",
            "packing_dock_code": "PACKING-01-DOCK-02",
            "charger_code": "TRIHOUSE-TEST-01-CHG-02",
        },
    )
    with pytest.raises(ResourceUnavailable):
        repository.assign_job_resources(
            job_a, {**ASSIGNMENT, "revision": 2, "packing_dock_code": "PACKING-01-DOCK-02"}
        )
    assignment = rows("SELECT context FROM jobs WHERE job_id=%s", (job_a,))[0]["context"]
    assignment = json.loads(assignment) if isinstance(assignment, str) else assignment
    assert assignment["assignment"] == ASSIGNMENT
    assert scalar(
        "SELECT COUNT(*) FROM reservations WHERE job_id=%s AND state='reserved'",
        (job_a,),
    ) == 3

    connection = mysql_connection(database="trihouse_fms")
    cursor = connection.cursor()
    try:
        cursor.execute(
            "UPDATE job_steps SET state='running' WHERE job_id=%s ORDER BY step_no LIMIT 1",
            (job_a,),
        )
        connection.commit()
    finally:
        cursor.close(); connection.close()
    with pytest.raises(ResourceAssignmentConflict, match="ASSIGNMENT_ALREADY_EXECUTING"):
        repository.assign_job_resources(job_a, {**ASSIGNMENT, "revision": 2})


def test_concurrent_reassignment_commits_exactly_one_revision_two(seeded_schema) -> None:
    install_active_map()
    job_id = _create_order("reassign-race", external_reference="TASK6-REASSIGN-RACE")
    _repository().assign_job_resources(job_id, ASSIGNMENT)
    barrier = threading.Barrier(2)

    def reassign(dock):
        barrier.wait()
        try:
            return _repository().assign_job_resources(
                job_id, {**ASSIGNMENT, "revision": 2, "packing_dock_code": dock}
            )
        except ResourceAssignmentConflict as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reassign, ("PACKING-01-DOCK-01", "PACKING-01-DOCK-02")))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ResourceAssignmentConflict) for result in results) == 1


@pytest.mark.parametrize(
    ("code", "state", "location_type", "reason"),
    [
        ("PACKING-01-DOCK-01", "blocked", None, "PACKING_DOCK_UNAVAILABLE"),
        ("PACKING-01-DOCK-01", None, "waypoint", "PACKING_DOCK_TYPE_MISMATCH"),
        ("TRIHOUSE-TEST-01-CHG-01", "maintenance", None, "CHARGER_UNAVAILABLE"),
        ("TRIHOUSE-TEST-01-CHG-01", None, "waypoint", "CHARGER_TYPE_MISMATCH"),
    ],
)
def test_assignment_validates_location_role_and_availability(
    seeded_schema, code, state, location_type, reason
) -> None:
    install_active_map()
    job_id = _create_order(f"location-{reason}", external_reference=f"TASK6-{reason}")
    connection = mysql_connection(database="trihouse_fms")
    cursor = connection.cursor()
    try:
        if state is not None:
            cursor.execute("UPDATE locations SET state=%s WHERE location_code=%s", (state, code))
        if location_type is not None:
            cursor.execute("UPDATE locations SET location_type=%s WHERE location_code=%s", (location_type, code))
        connection.commit()
    finally:
        cursor.close()
        connection.close()

    with pytest.raises(ResourceAssignmentConflict, match=reason):
        _repository().assign_job_resources(job_id, ASSIGNMENT)


def test_packing_dock_and_charger_must_be_distinct(seeded_schema) -> None:
    install_active_map()
    job_id = _create_order("same-location", external_reference="TASK6-SAME-LOCATION")
    changed = {**ASSIGNMENT, "packing_dock_code": ASSIGNMENT["charger_code"]}

    with pytest.raises(ResourceAssignmentConflict, match="PACKING_DOCK_CHARGER_MUST_DIFFER"):
        _repository().assign_job_resources(job_id, changed)


def test_public_order_step_cannot_dispatch_before_complete_assignment(
    seeded_schema,
) -> None:
    install_active_map()
    job_id = _create_order("pre-dispatch", external_reference="TASK6-PRE-DISPATCH")
    step_id = scalar(
        "SELECT job_step_id FROM job_steps WHERE job_id=%s ORDER BY step_no LIMIT 1",
        (job_id,),
    )

    with pytest.raises(JobStepNotDispatchable):
        _repository().dispatch_step(
            step_id,
            {"actor": "control-tower", "assigned_device_id": "OMX_01"},
            "task6-dispatch-before-assignment",
        )


def test_concurrent_jobs_cannot_reserve_the_same_assignment_resources(
    seeded_schema,
) -> None:
    install_active_map()
    jobs = (
        _create_order(
            "collision-a",
            external_reference="TASK6-COLLISION-A",
            product_code="SKU-STRAWBERRY",
        ),
        _create_order(
            "collision-b",
            external_reference="TASK6-COLLISION-B",
            product_code="SKU-MANDARIN",
        ),
    )
    barrier = threading.Barrier(2)

    def assign(job_id: int):
        barrier.wait()
        try:
            return _repository().assign_job_resources(job_id, ASSIGNMENT)
        except ResourceUnavailable as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(assign, jobs))

    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ResourceUnavailable) for result in results) == 1
    assert scalar(
        "SELECT COUNT(*) FROM reservations WHERE state='reserved' AND device_id='PK_01'"
    ) == 1


def test_wrong_fixed_charger_rejects_the_whole_assignment(seeded_schema) -> None:
    install_active_map()
    job_id = _create_order("charger", external_reference="TASK6-CHARGER")
    changed = {**ASSIGNMENT, "charger_code": "TRIHOUSE-TEST-01-CHG-02"}

    with pytest.raises(ResourceAssignmentConflict, match="FIXED_CHARGER_MISMATCH"):
        _repository().assign_job_resources(job_id, changed)

    assert scalar("SELECT COUNT(*) FROM reservations WHERE job_id=%s", (job_id,)) == 0
    assert rows(
        "SELECT assigned_mobile_id FROM jobs WHERE job_id=%s", (job_id,)
    ) == [{"assigned_mobile_id": None}]


def test_completion_finalizes_inventory_releases_dock_and_enqueues_fixed_return_once(
    seeded_schema,
) -> None:
    install_active_map()
    job_id = _prepare_job("complete")
    before = _quantities(job_id)

    response = _repository().complete_worker_packing(
        job_id, _request(), "task6-complete-once"
    )

    after = _quantities(job_id)
    assert [row["available_qty"] for row in after] == [
        row["available_qty"] - row["reserved_qty"] for row in before
    ]
    assert [row["reserved_qty"] for row in after] == [0 for _ in before]
    assert [row["completed_qty"] for row in after] == [
        row["reserved_qty"] for row in before
    ]
    assert response["context"]["assignment"]["charger_code"] == (
        "TRIHOUSE-TEST-01-CHG-01"
    )
    assert scalar(
        "SELECT COUNT(*) FROM inventory_moves WHERE job_id=%s AND move_type='outbound'",
        (job_id,),
    ) == len(before)
    assert rows(
        "SELECT state FROM job_steps WHERE job_id=%s AND action_type='wait'", (job_id,)
    ) == [{"state": "succeeded"}]
    assert rows(
        "SELECT state FROM reservations WHERE job_id=%s AND location_id IS NOT NULL",
        (job_id,),
    ) == [{"state": "released"}]
    messages = rows(
        "SELECT message_type, idempotency_key, payload FROM integration_messages WHERE job_step_id IN (SELECT job_step_id FROM job_steps WHERE job_id=%s AND action_type='return_home')",
        (job_id,),
    )
    assert len(messages) == 1
    payload = json.loads(messages[0]["payload"]) if isinstance(messages[0]["payload"], str) else messages[0]["payload"]
    assert messages[0]["message_type"] == "return_home"
    assert payload["charger_code"] == "TRIHOUSE-TEST-01-CHG-01"


def test_completion_replay_returns_first_response_and_changed_body_conflicts(
    seeded_schema,
) -> None:
    install_active_map()
    job_id = _prepare_job("replay")
    repository = _repository()

    first = repository.complete_worker_packing(
        job_id, _request(note="first"), "task6-completion-replay"
    )
    quantities = _quantities(job_id)
    connection = mysql_connection(database="trihouse_fms")
    cursor = connection.cursor()
    try:
        cursor.execute("UPDATE workers SET active = FALSE WHERE worker_id = 'W-OP-01'")
        connection.commit()
    finally:
        cursor.close()
        connection.close()
    replay = repository.complete_worker_packing(
        job_id, _request(note="first"), "task6-completion-replay"
    )
    with pytest.raises(IdempotencyConflict):
        repository.complete_worker_packing(
            job_id, _request(note="changed"), "task6-completion-replay"
        )

    assert replay == first
    assert _quantities(job_id) == quantities
    assert scalar(
        "SELECT COUNT(*) FROM integration_messages WHERE message_type='return_home'"
    ) == 1


def test_missing_manual_acknowledgement_rolls_back_every_effect(seeded_schema) -> None:
    install_active_map()
    job_id = _prepare_job("manual", manual_required=True)
    item_ids = tuple(
        row["job_item_id"]
        for row in rows(
            "SELECT job_item_id FROM job_items WHERE job_id=%s ORDER BY job_item_id",
            (job_id,),
        )
    )
    before = _quantities(job_id)

    with pytest.raises(ManualAcknowledgementRequired) as captured:
        _repository().complete_worker_packing(
            job_id, _request(), "task6-completion-manual"
        )

    assert captured.value.item_ids == item_ids
    assert _quantities(job_id) == before
    assert scalar(
        "SELECT COUNT(*) FROM integration_messages WHERE message_type='return_home'"
    ) == 0


def test_mid_transaction_failure_rolls_back_stock_steps_reservation_and_message(
    seeded_schema,
) -> None:
    install_active_map()
    job_id = _prepare_job("rollback")
    before = _quantities(job_id)
    moves_before = scalar(
        "SELECT COUNT(*) FROM inventory_moves WHERE job_id=%s", (job_id,)
    )

    with pytest.raises(RuntimeError, match="injected return enqueue failure"):
        _repository(_InstrumentedDatabase(fail_return=True)).complete_worker_packing(
            job_id, _request(), "task6-completion-rollback"
        )

    assert _quantities(job_id) == before
    assert rows(
        "SELECT state FROM job_steps WHERE job_id=%s AND action_type='wait'", (job_id,)
    ) == [{"state": "running"}]
    assert rows(
        "SELECT state FROM reservations WHERE job_id=%s AND location_id IS NOT NULL",
        (job_id,),
    ) == [{"state": "reserved"}]
    assert scalar(
        "SELECT COUNT(*) FROM integration_messages WHERE message_type='return_home'"
    ) == 0
    assert scalar(
        "SELECT COUNT(*) FROM inventory_moves WHERE job_id=%s", (job_id,)
    ) == moves_before
    assert scalar(
        "SELECT COUNT(*) FROM operation_events WHERE job_id=%s AND event_type='worker.packing.completed'",
        (job_id,),
    ) == 0
    assert scalar(
        "SELECT COUNT(*) FROM job_items WHERE job_id=%s AND JSON_EXTRACT(metadata, '$.worker_completion_acknowledged')=true",
        (job_id,),
    ) == 0
    return_step = rows(
        "SELECT target_location_id, assigned_device_id, input FROM job_steps WHERE job_id=%s AND action_type='return_home'",
        (job_id,),
    )[0]
    return_input = json.loads(return_step["input"]) if isinstance(return_step["input"], str) else return_step["input"]
    assert return_step["target_location_id"] is None
    assert return_step["assigned_device_id"] == "PK_01"
    assert "charger_code" not in return_input


def test_concurrent_completion_replay_finalizes_every_effect_once(seeded_schema) -> None:
    install_active_map()
    job_id = _prepare_job("concurrent-completion")
    moves_before = scalar(
        "SELECT COUNT(*) FROM inventory_moves WHERE job_id=%s", (job_id,)
    )
    barrier = threading.Barrier(2)

    def complete():
        barrier.wait()
        return _repository().complete_worker_packing(
            job_id, _request(), "task6-concurrent-completion"
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.map(lambda _: complete(), range(2))

    assert first == second
    assert scalar(
        "SELECT COUNT(*) FROM inventory_moves WHERE job_id=%s", (job_id,)
    ) == moves_before + len(_quantities(job_id))
    assert scalar(
        "SELECT COUNT(*) FROM integration_messages WHERE message_type='return_home'"
    ) == 1
    assert scalar(
        "SELECT COUNT(*) FROM operation_events WHERE job_id=%s AND event_type='worker.packing.completed'",
        (job_id,),
    ) == 1


def test_completion_locks_rows_in_one_global_order(seeded_schema) -> None:
    install_active_map()
    job_id = _prepare_job("locks")
    locks: list[str] = []

    _repository(_InstrumentedDatabase(locks=locks)).complete_worker_packing(
        job_id, _request(), "task6-completion-locks"
    )

    assert locks == ["job", "steps", "items", "lots", "reservations", "attempts"]
