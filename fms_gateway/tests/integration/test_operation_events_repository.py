from datetime import datetime, timedelta
import json
import os

from fms_gateway.app.config import Settings
from fms_gateway.app.database import Database
from fms_gateway.app.repositories import MySqlFmsRepository


def repository() -> MySqlFmsRepository:
    return MySqlFmsRepository(
        Database(
            Settings(
                host=os.environ.get("FMS_DB_HOST", "127.0.0.1"),
                port=int(os.environ.get("FMS_DB_PORT", "3307")),
                user=os.environ.get("FMS_DB_USER", "fms_gateway"),
                password=os.environ.get(
                    "FMS_DB_PASSWORD", "test_gateway_password"
                ),
                database="trihouse_fms",
                pool_size=2,
            )
        )
    )


def test_mysql_map_changes_append_canonical_operation_events(mysql_db):
    gateway = repository()
    gateway.save_map_project(
        "event-map",
        {
            "format_version": 2,
            "payload": {
                "format": "robosapiens-map-project",
                "version": 2,
                "mapName": "event-map",
                "waypoints": [],
                "laneDirections": [],
            },
            "building_yaml": None,
            "building_yaml_name": None,
            "files": [],
            "fleet": None,
            "robots": [],
        },
        None,
    )
    changes = [
        {
            "category": "waypoint",
            "action": "updated",
            "target": "inspection_point_01",
            "summary": "Moved inspection point",
        },
        {
            "category": "lane",
            "action": "created",
            "target": "lane-02",
            "summary": "Added lane",
        },
    ]

    recorded = gateway.record_map_project_changes("event-map", changes)
    feed = gateway.list_operation_events(
        recorded[0]["occurred_at"],
        recorded[-1]["occurred_at"] + timedelta(microseconds=1),
        10,
    )

    assert [event["event_type"] for event in feed] == [
        "MAP_PROJECT_CHANGED",
        "MAP_PROJECT_CHANGED",
    ]
    rows = mysql_db.all(
        "SELECT category, event_type, message, payload FROM operation_events "
        "ORDER BY event_id"
    )
    assert len(rows) == 2
    assert rows[0]["category"] == "system"
    assert rows[0]["event_type"] == "MAP_PROJECT_CHANGED"
    payload = (
        json.loads(rows[0]["payload"])
        if isinstance(rows[0]["payload"], str)
        else rows[0]["payload"]
    )
    assert payload == {"map_name": "event-map", "change": changes[0]}


def test_mysql_operation_event_keyset_cursor_breaks_timestamp_ties(mysql_db):
    gateway = repository()
    gateway.save_map_project(
        "cursor-map",
        {
            "format_version": 2,
            "payload": {
                "format": "robosapiens-map-project",
                "version": 2,
                "mapName": "cursor-map",
                "waypoints": [],
                "laneDirections": [],
            },
            "building_yaml": None,
            "building_yaml_name": None,
            "files": [],
            "fleet": None,
            "robots": [],
        },
        None,
    )
    recorded = gateway.record_map_project_changes(
        "cursor-map",
        [
            {
                "category": "map",
                "action": "saved",
                "target": f"cursor-map-{number}",
                "summary": f"Saved map {number}",
            }
            for number in range(3)
        ],
    )
    tied_at = datetime(2026, 8, 13, 12, 0, 0)
    mysql_db.execute(
        "UPDATE operation_events SET occurred_at = %s", (tied_at,)
    )
    mysql_db.connection.commit()

    first_page = gateway.list_operation_events(None, None, 2)
    second_page = gateway.list_operation_events(
        None, None, 2, tied_at, first_page[-1]["event_id"]
    )

    assert [event["event_id"] for event in first_page] == [
        recorded[2]["event_id"],
        recorded[1]["event_id"],
    ]
    assert [event["event_id"] for event in second_page] == [recorded[0]["event_id"]]
