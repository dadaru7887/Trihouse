"""MySQL transaction tests for product-only outbound order intake."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import threading

import pytest

from conftest import mysql_connection
from test_read_api import real_client


pytestmark = pytest.mark.integration

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "demo_orders.json"
DEMO_ORDERS = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


ACTIVE_WAYPOINTS = [
    {
        "location_code": "WH-AMB-01-DOCK-01",
        "display_name": "Ambient Storage Loading Dock 01",
        "rmf_waypoint_name": "ambient_storage_loading_dock_01",
        "operational_role": "loading_dock",
        "parent_location_code": "WH-AMB-01",
        "temperature_zone": "ambient",
        "pose": (1.234, 0.743, 2.255),
    },
    {
        "location_code": "WH-CHL-01-DOCK-01",
        "display_name": "Chilled Storage Loading Dock 01",
        "rmf_waypoint_name": "chilled_storage_loading_dock_01",
        "operational_role": "loading_dock",
        "parent_location_code": "WH-CHL-01",
        "temperature_zone": "chilled",
        "pose": (1.260, 0.193, -2.258),
    },
    {
        "location_code": "WH-FRZ-01-DOCK-01",
        "display_name": "Frozen Storage Loading Dock 01",
        "rmf_waypoint_name": "frozen_storage_loading_dock_01",
        "operational_role": "loading_dock",
        "parent_location_code": "WH-FRZ-01",
        "temperature_zone": "frozen",
        "pose": (1.201, -0.799, -1.408),
    },
    {
        "location_code": "PACKING-01-DOCK-01",
        "display_name": "Packing Station Loading Dock 01",
        "rmf_waypoint_name": "packing_station_loading_dock_01",
        "operational_role": "loading_dock",
        "parent_location_code": "PACKING-01",
        "temperature_zone": "ambient",
        "pose": (0.351, -0.490, 0.231),
    },
    {
        "location_code": "PACKING-01-DOCK-02",
        "display_name": "Packing Station Loading Dock 02",
        "rmf_waypoint_name": "packing_station_loading_dock_02",
        "operational_role": "loading_dock",
        "parent_location_code": "PACKING-01",
        "temperature_zone": "ambient",
        "pose": (0.351, -1.017, 0.231),
    },
    {
        "location_code": "TRIHOUSE-TEST-01-CHG-01",
        "display_name": "Charging Station 01",
        "rmf_waypoint_name": "charging_station_01",
        "operational_role": "charging_station",
        "parent_location_code": None,
        "temperature_zone": None,
        "pose": (0.065, 0.227, -0.005),
    },
    {
        "location_code": "TRIHOUSE-TEST-01-CHG-02",
        "display_name": "Charging Station 02",
        "rmf_waypoint_name": "charging_station_02",
        "operational_role": "charging_station",
        "parent_location_code": None,
        "temperature_zone": None,
        "pose": (0.076, -0.013, 0.239),
    },
]


def install_active_map() -> None:
    """Install canonical active-map projections without defining a route graph."""
    connection = mysql_connection(database="trihouse_fms")
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO locations
              (location_code, name, location_type, zone_code, temperature_zone, state)
            VALUES ('PACKING-01', 'Packing Station', 'workstation',
                    'packing', 'ambient', 'available')
            ON DUPLICATE KEY UPDATE
              location_type = VALUES(location_type),
              zone_code = VALUES(zone_code),
              temperature_zone = VALUES(temperature_zone),
              state = VALUES(state)
            """
        )
        cursor.execute(
            """
            INSERT INTO map_projects (map_name, format_version, payload, waypoint_count)
            VALUES ('trihouse_test_01', 1, JSON_OBJECT(), %s)
            """,
            (len(ACTIVE_WAYPOINTS),),
        )
        project_id = cursor.lastrowid
        public_waypoints = []
        for waypoint in ACTIVE_WAYPOINTS:
            parent_code = waypoint["parent_location_code"]
            parent_id = None
            if parent_code is not None:
                cursor.execute(
                    "SELECT location_id FROM locations WHERE location_code = %s",
                    (parent_code,),
                )
                parent_id = cursor.fetchone()[0]
            x, y, yaw = waypoint["pose"]
            cursor.execute(
                """
                INSERT INTO locations
                  (parent_location_id, location_code, name, location_type,
                   temperature_zone, map_name, rmf_waypoint_name,
                   pose_x, pose_y, pose_yaw, metadata)
                VALUES (%s, %s, %s, 'staging', %s, 'trihouse_test_01', %s,
                        %s, %s, %s,
                        JSON_OBJECT('authoring_managed', true, 'active', true,
                                    'map_revision', 'trihouse_test_01:test'))
                """,
                (
                    parent_id,
                    waypoint["location_code"],
                    waypoint["display_name"],
                    waypoint["temperature_zone"],
                    waypoint["rmf_waypoint_name"],
                    x,
                    y,
                    yaw,
                ),
            )
            public_waypoints.append(
                {
                    key: waypoint[key]
                    for key in (
                        "location_code",
                        "display_name",
                        "rmf_waypoint_name",
                        "operational_role",
                        "parent_location_code",
                        "temperature_zone",
                    )
                }
            )
        manifest = {"draft_snapshot": {"waypoints": public_waypoints}}
        cursor.execute(
            """
            INSERT INTO map_revisions
              (map_revision, map_name, source_project_id, draft_revision, state,
               building_sha256, nav_graph_sha256, world_sha256, manifest, published_by)
            VALUES ('trihouse_test_01:test', 'trihouse_test_01', %s, 1, 'published',
                    %s, %s, %s, %s, 'W-OP-01')
            """,
            (project_id, "0" * 64, "1" * 64, "2" * 64, json.dumps(manifest)),
        )
        connection.commit()
    finally:
        cursor.close()
        connection.close()


def scalar(sql: str, params: tuple[object, ...] = ()) -> int:
    connection = mysql_connection(database="trihouse_fms")
    cursor = connection.cursor()
    try:
        cursor.execute(sql, params)
        return int(cursor.fetchone()[0])
    finally:
        cursor.close()
        connection.close()


def rows(sql: str, params: tuple[object, ...] = ()) -> list[dict]:
    connection = mysql_connection(database="trihouse_fms")
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        return list(cursor.fetchall())
    finally:
        cursor.close()
        connection.close()


@pytest.mark.parametrize(
    ("example", "status", "zones", "totals"),
    [
        (DEMO_ORDERS[0], 201, ["ambient", "chilled", "frozen"], (3, 3, 0)),
        (DEMO_ORDERS[1], 201, ["chilled", "frozen"], (2, 2, 0)),
        (DEMO_ORDERS[2], 409, [], None),
        (DEMO_ORDERS[3], 201, ["ambient", "frozen"], (2, 2, 0)),
        (DEMO_ORDERS[4], 201, ["chilled", "frozen"], (4, 3, 1)),
        (DEMO_ORDERS[5], 201, ["ambient"], (2, 2, 0)),
    ],
    ids=["A-all-zones", "B-empty-zone", "C-reject", "D-critical", "E-partial", "F-one-dock"],
)
def test_each_approved_demo_order_runs_from_a_fresh_seed(
    seeded_schema,
    example: dict,
    status: int,
    zones: list[str],
    totals: tuple[int, int, int] | None,
) -> None:
    install_active_map()
    before = {
        table: scalar(f"SELECT COUNT(*) FROM {table}")
        for table in ("jobs", "job_items", "job_steps", "inventory_moves", "operation_events")
    }

    response = real_client().post(
        "/api/v1/orders",
        headers={"Idempotency-Key": f"demo-{example['id']}"},
        json=example["request"],
    )

    assert response.status_code == status
    if status == 409:
        assert response.json()["detail"]["code"] == "INSUFFICIENT_STOCK"
        assert {
            table: scalar(f"SELECT COUNT(*) FROM {table}")
            for table in before
        } == before
        return

    payload = response.json()
    assert (
        payload["requested_quantity"],
        payload["fulfillable_quantity"],
        payload["outstanding_quantity"],
    ) == totals
    job_id = payload["job_id"]
    job = rows("SELECT priority, context FROM jobs WHERE job_id = %s", (job_id,))[0]
    context = json.loads(job["context"]) if isinstance(job["context"], str) else job["context"]
    assert context["zone_order"] == zones
    assert job["priority"] == example["request"]["priority"]
    step_inputs = rows(
        "SELECT action_type, input FROM job_steps WHERE job_id = %s ORDER BY step_no",
        (job_id,),
    )
    parsed_inputs = [
        json.loads(row["input"]) if isinstance(row["input"], str) else row["input"]
        for row in step_inputs
    ]
    visits = [
        item["temperature_zone"]
        for item in parsed_inputs
        if item.get("branch") == "pinky_navigate"
    ]
    assert visits == zones
    assert all("route" not in item and "pose" not in item for item in parsed_inputs)
    if example["id"] == "E":
        sandwich = next(
            item
            for item in payload["items"]
            if item["product_code"] == "SKU-SANDWICH"
        )
        assert sandwich["outstanding_quantity"] == 1
    if example["id"] == "F":
        ambient_visits = [item for item in parsed_inputs if item.get("branch") == "pinky_navigate"]
        assert len(ambient_visits) == 1
        assert ambient_visits[0]["product_codes"] == ["SKU-ORANGE", "SKU-MANDARIN"]


def test_order_idempotency_returns_the_original_response_without_reserving_twice(
    seeded_schema,
) -> None:
    install_active_map()
    request = DEMO_ORDERS[5]["request"]
    client = real_client()

    first = client.post(
        "/api/v1/orders", headers={"Idempotency-Key": "same-order"}, json=request
    )
    second = client.post(
        "/api/v1/orders", headers={"Idempotency-Key": "same-order"}, json=request
    )
    changed = deepcopy(request)
    changed["items"][0]["quantity"] = 2
    conflict = client.post(
        "/api/v1/orders", headers={"Idempotency-Key": "same-order"}, json=changed
    )

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert conflict.status_code == 409
    assert scalar(
        "SELECT reserved_qty FROM inventory_lots WHERE lot_code='LOT-AMB-ORANGE-001'"
    ) == 1


def test_concurrent_retries_with_the_same_key_replay_one_order(seeded_schema) -> None:
    install_active_map()
    barrier = threading.Barrier(2)
    request = DEMO_ORDERS[5]["request"]

    def submit():
        barrier.wait()
        return real_client().post(
            "/api/v1/orders",
            headers={"Idempotency-Key": "concurrent-same-order"},
            json=request,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: submit(), (1, 2)))

    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()
    assert scalar(
        "SELECT reserved_qty FROM inventory_lots WHERE lot_code='LOT-AMB-ORANGE-001'"
    ) == 1
    assert scalar(
        "SELECT COUNT(*) FROM jobs WHERE external_reference = %s",
        (request["external_reference"],),
    ) == 1


def test_concurrent_orders_cannot_over_reserve_the_same_lot(seeded_schema) -> None:
    install_active_map()
    barrier = threading.Barrier(2)
    base = DEMO_ORDERS[2]["request"]

    def submit(index: int):
        body = deepcopy(base)
        body["external_reference"] = f"CONCURRENT-ORANGE-{index}"
        body["items"][0]["quantity"] = 1
        barrier.wait()
        return real_client().post(
            "/api/v1/orders",
            headers={"Idempotency-Key": f"concurrent-orange-{index}"},
            json=body,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(submit, (1, 2)))

    assert sorted(response.status_code for response in responses) == [201, 409]
    assert scalar(
        "SELECT reserved_qty FROM inventory_lots WHERE lot_code='LOT-AMB-ORANGE-001'"
    ) == 1
    assert scalar(
        "SELECT COALESCE(SUM(reserved_delta), 0) FROM inventory_moves "
        "WHERE lot_id=(SELECT lot_id FROM inventory_lots WHERE lot_code='LOT-AMB-ORANGE-001')"
    ) == 1
