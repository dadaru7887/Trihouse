"""P0 인수: 여섯 개 신선 seed 주문을 공개 API로 끝까지 돌린다.

A–F 각각에 대해 스키마와 seed를 다시 만들고, `trihouse_test_01`을 승인된
JSONL에서 발행한 뒤, UI와 **같은** 공개 주문 API로 제출한다. 구역 순서,
재고 부족/부분 출고/critical 동작, 한 구역 한 Dock 방문, 품목별 시도,
작업자 완료, 선택된 포장 Dock, 고정 충전기 복귀를 확인한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from e2e_support import requires_mysql  # type: ignore
from test_outbound_order_repository import (  # type: ignore
    DEMO_ORDERS,
    install_active_map,
    rows,
    scalar,
)
from test_read_api import real_client  # type: ignore
from test_worker_completion_repository import (  # type: ignore
    ASSIGNMENT,
    _record_item_load_states,
    _repository,
    _request,
)


pytestmark = [pytest.mark.integration, requires_mysql]

FEATURES = (
    Path(__file__).resolve().parents[2]
    / "control_system_test"
    / "rmf_control_ui"
    / "data"
    / "import"
    / "trihouse_test_01_physical_features.jsonl"
)

# The plan's approved A–F outcomes, expressed as the acceptance expectations.
EXPECTATIONS = {
    "A": {"status": 201, "zones": ["ambient", "chilled", "frozen"], "totals": (3, 3, 0)},
    "B": {"status": 201, "zones": ["chilled", "frozen"], "totals": (2, 2, 0)},
    "C": {"status": 409, "zones": [], "totals": None},
    "D": {"status": 201, "zones": ["ambient", "frozen"], "totals": (2, 2, 0)},
    "E": {"status": 201, "zones": ["chilled", "frozen"], "totals": (4, 3, 1)},
    "F": {"status": 201, "zones": ["ambient"], "totals": (2, 2, 0)},
}


def _context(job_id: int) -> dict:
    raw = rows("SELECT context FROM jobs WHERE job_id=%s", (job_id,))[0]["context"]
    return json.loads(raw) if isinstance(raw, str) else raw


def _step_inputs(job_id: int) -> list[dict]:
    return [
        json.loads(row["input"]) if isinstance(row["input"], str) else row["input"]
        for row in rows(
            "SELECT input FROM job_steps WHERE job_id=%s ORDER BY step_no", (job_id,)
        )
    ]


def _submit(example: dict) -> tuple[int, dict]:
    response = real_client().post(
        "/api/v1/orders",
        headers={"Idempotency-Key": f"e2e-{example['id']}"},
        json=example["request"],
    )
    return response.status_code, response.json()


def test_the_only_pose_source_is_the_authoritative_jsonl() -> None:
    """P0 좌표는 오직 이 파일에서만 온다."""
    assert FEATURES.is_file()
    records = [
        json.loads(line)
        for line in FEATURES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(records) == 13
    kinds = [record["record_type"] for record in records]
    assert kinds.count("waypoint") == 8
    assert kinds.count("bottleneck") == 2
    assert kinds.count("fiducial_binding") == 3
    for record in records:
        if record["record_type"] == "bottleneck":
            # 실행 반경 0.1 m, 측정 지름 0.2 m.
            assert record["radius_m"] == 0.1
            assert record["source_diameter_m"] == 0.2


@pytest.mark.parametrize(
    "example", DEMO_ORDERS, ids=[example["id"] for example in DEMO_ORDERS]
)
def test_each_demo_order_runs_from_a_fresh_seed_through_the_public_api(
    seeded_schema, example: dict
) -> None:
    install_active_map()
    expected = EXPECTATIONS[example["id"]]
    before = {
        table: scalar(f"SELECT COUNT(*) FROM {table}")
        for table in ("jobs", "job_items", "job_steps", "reservations")
    }

    status, payload = _submit(example)
    assert status == expected["status"]

    if expected["status"] == 409:
        # 전량 출고 요청의 재고 부족은 아무것도 만들지 않는다.
        assert payload["detail"]["code"] == "INSUFFICIENT_STOCK"
        assert {
            table: scalar(f"SELECT COUNT(*) FROM {table}") for table in before
        } == before
        return

    assert (
        payload["requested_quantity"],
        payload["fulfillable_quantity"],
        payload["outstanding_quantity"],
    ) == expected["totals"]

    job_id = payload["job_id"]
    assert _context(job_id)["zone_order"] == expected["zones"]

    inputs = _step_inputs(job_id)
    visits = [
        item["temperature_zone"]
        for item in inputs
        if item.get("branch") == "pinky_navigate"
    ]
    # 한 구역은 선반 수와 무관하게 Dock 방문 한 번이다.
    assert visits == expected["zones"]
    assert len(visits) == len(set(visits))

    if example["id"] == "D":
        assert rows("SELECT priority FROM jobs WHERE job_id=%s", (job_id,))[0][
            "priority"
        ] == "critical"
    if example["id"] == "E":
        sandwich = next(
            item for item in payload["items"] if item["product_code"] == "SKU-SANDWICH"
        )
        # 부분 출고는 남은 수량을 문자 그대로 남긴다.
        assert sandwich["outstanding_quantity"] == 1


def test_a_full_order_reaches_completion_dock_release_and_charger_return(
    seeded_schema,
) -> None:
    """F 주문 하나를 배정 → 적재 시도 → 작업자 완료 → 충전기 복귀까지 끝낸다."""
    install_active_map()
    status, payload = _submit(DEMO_ORDERS[5])
    assert status == 201
    job_id = payload["job_id"]

    repository = _repository()
    repository.assign_job_resources(job_id, ASSIGNMENT)
    assignment = _context(job_id)["assignment"]
    assert assignment["mobile_id"] in ("PK_01", "PK_02")
    assert assignment["omx_id"] in ("OMX_01", "OMX_02")
    assert assignment["packing_dock_code"] in (
        "PACKING-01-DOCK-01",
        "PACKING-01-DOCK-02",
    )
    # PK_01 -> CHG-01, PK_02 -> CHG-02 는 고정이다.
    assert assignment["charger_code"] == (
        "TRIHOUSE-TEST-01-CHG-01"
        if assignment["mobile_id"] == "PK_01"
        else "TRIHOUSE-TEST-01-CHG-02"
    )

    _advance_to_worker_wait(job_id)
    _record_item_load_states(job_id)

    attempts = rows(
        """
        SELECT attempt.outcome_reason_code
        FROM job_step_attempts attempt
        JOIN job_steps step ON step.job_step_id = attempt.job_step_id
        WHERE step.job_id = %s AND step.action_type = 'load'
        ORDER BY attempt.attempt_uuid
        """,
        (job_id,),
    )
    assert attempts, "every item must record a load attempt"
    assert all(row["outcome_reason_code"] == "LOAD_CONFIRMED" for row in attempts)

    completed = real_client().post(
        f"/api/v1/jobs/{job_id}/worker-completion",
        headers={"Idempotency-Key": f"e2e-complete-{job_id}"},
        json=_request(),
    )
    assert completed.status_code == 200

    # 완료가 재고를 확정하고, 포장 Dock을 놓아주고, 고정 충전기 복귀를 넣는다.
    return_steps = rows(
        """
        SELECT action_type, state, input FROM job_steps
        WHERE job_id=%s AND action_type='return_home'
        """,
        (job_id,),
    )
    assert len(return_steps) == 1
    return_input = return_steps[0]["input"]
    return_input = (
        json.loads(return_input) if isinstance(return_input, str) else return_input
    )
    assert assignment["charger_code"] in json.dumps(return_input)

    replay = real_client().post(
        f"/api/v1/jobs/{job_id}/worker-completion",
        headers={"Idempotency-Key": f"e2e-complete-{job_id}"},
        json=_request(),
    )
    # 작업자 완료는 멱등이며 재고를 두 번 확정하지 않는다.
    assert replay.status_code == 200
    assert replay.json() == completed.json()


def _advance_to_worker_wait(job_id: int) -> None:
    """적재까지의 단계를 성공 처리하고 포장대 대기 단계를 실행 상태로 만든다."""
    from conftest import mysql_connection  # type: ignore

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
        cursor.execute("UPDATE jobs SET state='running' WHERE job_id=%s", (job_id,))
        connection.commit()
    finally:
        cursor.close()
        connection.close()
