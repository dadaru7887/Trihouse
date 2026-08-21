"""MySQL transaction tests for product-only outbound order intake."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
import uuid

import pytest

from conftest import mysql_connection
from fms_gateway.app.repositories import MySqlFmsRepository
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
                ON DUPLICATE KEY UPDATE
                  parent_location_id = VALUES(parent_location_id),
                  name = VALUES(name),
                  location_type = VALUES(location_type),
                  temperature_zone = VALUES(temperature_zone),
                  map_name = VALUES(map_name),
                  rmf_waypoint_name = VALUES(rmf_waypoint_name),
                  pose_x = VALUES(pose_x), pose_y = VALUES(pose_y),
                  pose_yaw = VALUES(pose_yaw), metadata = VALUES(metadata),
                  state = 'available'
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


def install_unrelated_newer_map() -> None:
    """Publish a role-complete map that must never supply outbound locations."""
    connection = mysql_connection(database="trihouse_fms")
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO map_projects (map_name, format_version, payload, waypoint_count)
            VALUES ('unrelated_facility', 1, JSON_OBJECT(), %s)
            """,
            (len(ACTIVE_WAYPOINTS),),
        )
        project_id = cursor.lastrowid
        public_waypoints = []
        for index, waypoint in enumerate(ACTIVE_WAYPOINTS, start=1):
            parent_code = waypoint["parent_location_code"]
            parent_id = None
            if parent_code is not None:
                cursor.execute(
                    "SELECT location_id FROM locations WHERE location_code = %s",
                    (parent_code,),
                )
                parent_id = cursor.fetchone()[0]
            code = f"UNRELATED-DOCK-{index:02d}"
            cursor.execute(
                """
                INSERT INTO locations
                  (parent_location_id, location_code, name, location_type,
                   temperature_zone, map_name, rmf_waypoint_name,
                   pose_x, pose_y, pose_yaw, metadata)
                VALUES (%s, %s, %s, 'staging', %s, 'unrelated_facility', %s,
                        99, 99, 0,
                        JSON_OBJECT('authoring_managed', true, 'active', true,
                                    'map_revision', 'unrelated_facility:newer'))
                """,
                (
                    parent_id,
                    code,
                    f"Unrelated Dock {index}",
                    waypoint["temperature_zone"],
                    f"unrelated_dock_{index:02d}",
                ),
            )
            public_waypoints.append(
                {
                    "location_code": code,
                    "display_name": f"Unrelated Dock {index}",
                    "rmf_waypoint_name": f"unrelated_dock_{index:02d}",
                    "operational_role": waypoint["operational_role"],
                    "parent_location_code": parent_code,
                    "temperature_zone": waypoint["temperature_zone"],
                }
            )
        manifest = {"draft_snapshot": {"waypoints": public_waypoints}}
        cursor.execute(
            """
            INSERT INTO map_revisions
              (map_revision, map_name, source_project_id, draft_revision, state,
               building_sha256, nav_graph_sha256, world_sha256, manifest,
               published_by, published_at)
            VALUES ('unrelated_facility:newer', 'unrelated_facility', %s, 1,
                    'published', %s, %s, %s, %s, 'W-OP-01',
                    DATE_ADD(NOW(6), INTERVAL 1 HOUR))
            """,
            (project_id, "3" * 64, "4" * 64, "5" * 64, json.dumps(manifest)),
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


class _LockRecordingCursor:
    def __init__(self, cursor, locked_lot_ids: list[int]) -> None:
        self._cursor = cursor
        self._locked_lot_ids = locked_lot_ids

    def execute(self, operation, params=None, *args, **kwargs):
        normalized = " ".join(str(operation).split())
        if (
            "FROM inventory_lots lot" in normalized
            and "WHERE lot.lot_id = %s" in normalized
            and "FOR UPDATE" in normalized
        ):
            self._locked_lot_ids.append(int(params[0]))
        return self._cursor.execute(operation, params, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _LockRecordingConnection:
    def __init__(self, connection, locked_lot_ids: list[int]) -> None:
        self._connection = connection
        self._locked_lot_ids = locked_lot_ids

    def cursor(self, *args, **kwargs):
        return _LockRecordingCursor(
            self._connection.cursor(*args, **kwargs), self._locked_lot_ids
        )

    def __getattr__(self, name):
        return getattr(self._connection, name)


class _LockRecordingDatabase:
    def __init__(self, locked_lot_ids: list[int]) -> None:
        self._locked_lot_ids = locked_lot_ids

    @contextmanager
    def connection(self):
        connection = mysql_connection(database="trihouse_fms")
        try:
            yield _LockRecordingConnection(connection, self._locked_lot_ids)
        finally:
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


def test_newer_unrelated_published_map_cannot_supply_order_locations(
    seeded_schema,
) -> None:
    install_active_map()
    install_unrelated_newer_map()

    response = real_client().post(
        "/api/v1/orders",
        headers={"Idempotency-Key": "canonical-map-only"},
        json=DEMO_ORDERS[0]["request"],
    )

    assert response.status_code == 201
    job_id = response.json()["job_id"]
    target_maps = rows(
        """
        SELECT DISTINCT location.map_name
        FROM job_steps step
        JOIN locations location ON location.location_id = step.target_location_id
        WHERE step.job_id = %s
        """,
        (job_id,),
    )
    assert target_maps == [{"map_name": "trihouse_test_01"}]


def test_null_reference_orders_get_distinct_replay_stable_handover_groups(
    seeded_schema,
) -> None:
    install_active_map()
    request = {
        "external_reference": None,
        "priority": "normal",
        "allow_partial_fulfillment": False,
        "requested_by": "W-OP-01",
        "items": [{"product_code": "SKU-SANDWICH", "quantity": 1}],
    }
    client = real_client()

    first = client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": "null-reference-one"},
        json=request,
    )
    replay = client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": "null-reference-one"},
        json=request,
    )
    second = client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": "null-reference-two"},
        json=request,
    )

    assert [first.status_code, replay.status_code, second.status_code] == [201, 201, 201]
    assert replay.json() == first.json()

    def handover_group(response) -> str:
        step = rows(
            """
            SELECT input FROM job_steps
            WHERE job_id = %s AND action_type = 'load'
            """,
            (response.json()["job_id"],),
        )[0]
        payload = json.loads(step["input"]) if isinstance(step["input"], str) else step["input"]
        return str(payload["handover_group_id"])

    assert handover_group(first) != handover_group(second)


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


def test_candidate_lots_are_locked_one_by_one_in_global_lot_id_order(
    seeded_schema,
) -> None:
    install_active_map()
    expected = [
        row["lot_id"]
        for row in rows(
            """
            SELECT lot_id FROM inventory_lots
            WHERE product_code IN ('SKU-MANDARIN', 'SKU-YOGURT', 'SKU-DUMPLING')
              AND state = 'stored'
            ORDER BY lot_id
            """
        )
    ]
    locked_lot_ids: list[int] = []
    repository = MySqlFmsRepository(_LockRecordingDatabase(locked_lot_ids))

    response = repository.create_outbound_order(
        DEMO_ORDERS[0]["request"], "global-lot-lock-order"
    )

    assert response["state"] == "queued"
    assert locked_lot_ids == expected


@pytest.mark.parametrize("round_no", range(4))
def test_overlapping_single_and_reverse_multi_product_orders_do_not_deadlock(
    seeded_schema,
    round_no: int,
) -> None:
    install_active_map()
    barrier = threading.Barrier(2)
    requests = (
        {
            "external_reference": f"OVERLAP-SINGLE-{round_no}",
            "priority": "normal",
            "allow_partial_fulfillment": False,
            "requested_by": "W-OP-01",
            "items": [{"product_code": "SKU-SANDWICH", "quantity": 1}],
        },
        {
            "external_reference": f"OVERLAP-MULTI-{round_no}",
            "priority": "normal",
            "allow_partial_fulfillment": False,
            "requested_by": "W-OP-01",
            "items": [
                {"product_code": "SKU-ICEBAR", "quantity": 1},
                {"product_code": "SKU-SANDWICH", "quantity": 1},
            ],
        },
    )

    def submit(index: int):
        barrier.wait()
        return real_client().post(
            "/api/v1/orders",
            headers={"Idempotency-Key": f"overlap-{round_no}-{index}"},
            json=requests[index],
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(submit, (0, 1)))

    assert [response.status_code for response in responses] == [201, 201]


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


@pytest.mark.skipif(
    os.environ.get("FMS_RUN_DOCKER_SMOKE") != "1",
    reason="set FMS_RUN_DOCKER_SMOKE=1 to build the canonical Gateway image",
)
def test_canonical_compose_image_starts_ready_and_serves_product_orders(
    seeded_schema,
) -> None:
    """Dropping the shared planner from the image must break this real boundary."""
    install_active_map()
    repository_root = Path(__file__).resolve().parents[3]
    container_name = f"trihouse-task5-smoke-{uuid.uuid4().hex[:12]}"
    port = 18085
    subprocess.run(
        ["docker", "compose", "--file", "compose.control.yaml", "build", "fms_gateway"],
        cwd=repository_root,
        check=True,
    )
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--rm",
                "--name",
                container_name,
                "--network",
                "host",
                "--env",
                "FMS_DB_HOST=127.0.0.1",
                "--env",
                "FMS_DB_PORT=3307",
                "--env",
                "FMS_DB_USER=fms_gateway",
                "--env",
                "FMS_DB_PASSWORD=test_gateway_password",
                "--env",
                "FMS_DB_DATABASE=trihouse_fms",
                "--env",
                "FMS_TCP_ENABLED=false",
                "trihouse_fms_gateway:local",
                "python",
                "-m",
                "uvicorn",
                "fms_gateway.app.main:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        for _ in range(100):
            try:
                with urlopen(f"http://127.0.0.1:{port}/ready", timeout=0.5) as response:
                    if response.status == 200:
                        break
            except URLError:
                time.sleep(0.1)
        else:
            logs = subprocess.run(
                ["docker", "logs", container_name],
                capture_output=True,
                text=True,
            )
            pytest.fail(f"Gateway image never became ready:\n{logs.stdout}\n{logs.stderr}")

        with urlopen(f"http://127.0.0.1:{port}/openapi.json") as response:
            openapi = json.load(response)
        assert "post" in openapi["paths"]["/api/v1/orders"]

        request = Request(
            f"http://127.0.0.1:{port}/api/v1/orders",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": "canonical-image-order",
            },
            data=json.dumps(DEMO_ORDERS[5]["request"]).encode(),
        )
        with urlopen(request) as response:
            payload = json.load(response)
        assert response.status == 201
        assert payload["fulfillable_quantity"] == 2
    finally:
        subprocess.run(
            ["docker", "rm", "--force", container_name],
            check=False,
            capture_output=True,
        )
