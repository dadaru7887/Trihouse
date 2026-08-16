from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from fms_gateway.app.main import create_app
from fms_gateway.app.repositories import InMemoryFmsRepository
from test_map_project_api import save_body


def test_map_changes_append_system_events_and_global_feed_includes_job_events():
    client = TestClient(create_app(InMemoryFmsRepository()))
    client.put("/internal/v1/map-projects/project1", json=save_body())
    client.post(
        "/internal/v1/jobs",
        json={
            "job_code": "OUT-EVENT-1",
            "steps": [
                {
                    "step_no": 1,
                    "action_type": "navigate",
                    "executor_type": "mobile",
                    "input": {},
                }
            ],
        },
    )
    changes = {
        "changes": [
            {
                "category": "waypoint",
                "action": "updated",
                "target": "chilled_storage_02",
                "summary": "Moved Chilled Storage 02",
            },
            {
                "category": "lane",
                "action": "created",
                "target": "lane-07",
                "summary": "Added one-way lane",
            },
        ]
    }

    response = client.post(
        "/internal/v1/map-projects/project1/changes", json=changes
    )
    feed = client.get("/api/v1/operation-events")

    assert response.status_code == 201
    assert response.json()["map_name"] == "project1"
    assert len(response.json()["events"]) == 2
    first = response.json()["events"][0]
    assert first["category"] == "system"
    assert first["event_type"] == "MAP_PROJECT_CHANGED"
    assert first["message"] == "Moved Chilled Storage 02"
    assert first["payload"] == {
        "map_name": "project1",
        "change": changes["changes"][0],
    }
    assert feed.status_code == 200
    assert [event["event_type"] for event in feed.json()] == [
        "MAP_PROJECT_CHANGED",
        "MAP_PROJECT_CHANGED",
        "job.created",
    ]


def test_operation_event_feed_supports_inclusive_from_exclusive_to_and_limit():
    client = TestClient(create_app(InMemoryFmsRepository()))
    client.put("/internal/v1/map-projects/project1", json=save_body())
    created = client.post(
        "/internal/v1/map-projects/project1/changes",
        json={
            "changes": [
                {
                    "category": "map",
                    "action": "saved",
                    "target": "project1",
                    "summary": "Saved map",
                }
            ]
        },
    ).json()["events"][0]
    occurred_at = datetime.fromisoformat(created["occurred_at"])

    assert client.get(
        "/api/v1/operation-events",
        params={"from": occurred_at.isoformat(), "limit": 1},
    ).json() == [created]
    assert client.get(
        "/api/v1/operation-events",
        params={"to": occurred_at.isoformat()},
    ).json() == []
    assert client.get(
        "/api/v1/operation-events",
        params={"from": (occurred_at + timedelta(seconds=1)).isoformat()},
    ).json() == []


def test_operation_event_feed_keyset_cursor_is_stable_for_equal_timestamps():
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository))
    client.put("/internal/v1/map-projects/project1", json=save_body())
    recorded = client.post(
        "/internal/v1/map-projects/project1/changes",
        json={
            "changes": [
                {
                    "category": "map",
                    "action": "saved",
                    "target": f"project1-{number}",
                    "summary": f"Saved map {number}",
                }
                for number in range(3)
            ]
        },
    ).json()["events"]
    tied_at = datetime.fromisoformat(recorded[0]["occurred_at"])
    for event in repository._operation_events:
        event["occurred_at"] = tied_at

    first_page = client.get(
        "/api/v1/operation-events", params={"limit": 2}
    ).json()
    second_page = client.get(
        "/api/v1/operation-events",
        params={
            "from": tied_at.isoformat(),
            "to": (tied_at + timedelta(seconds=1)).isoformat(),
            "before_at": first_page[-1]["occurred_at"],
            "before_event_id": first_page[-1]["event_id"],
            "limit": 2,
        },
    ).json()

    assert [event["event_id"] for event in first_page] == [3, 2]
    assert [event["event_id"] for event in second_page] == [1]
    assert client.get(
        "/api/v1/operation-events", params={"before_event_id": 2}
    ).status_code == 422


def test_changes_require_existing_project_and_nonempty_change_list():
    client = TestClient(create_app(InMemoryFmsRepository()))
    body = {
        "changes": [
            {
                "category": "map",
                "action": "saved",
                "target": "missing",
                "summary": "Saved map",
            }
        ]
    }

    assert client.post(
        "/internal/v1/map-projects/missing/changes", json=body
    ).status_code == 404
    client.put("/internal/v1/map-projects/project1", json=save_body())
    assert client.post(
        "/internal/v1/map-projects/project1/changes", json={"changes": []}
    ).status_code == 422
    assert client.get("/api/v1/operation-events", params={"limit": 0}).status_code == 422
