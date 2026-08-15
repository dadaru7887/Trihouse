import hashlib
import json

from fastapi.testclient import TestClient

from fms_gateway.app.main import create_app
from fms_gateway.app.repositories import InMemoryFmsRepository


def project1_payload() -> dict:
    return {
        "format": "robosapiens-map-project",
        "version": 2,
        "mapName": "project1",
        "drawing": {
            "name": "project1.png",
            "extension": "png",
            "pixelWidth": 100,
            "pixelHeight": 80,
        },
        "waypoints": [
            {"point": [100.0, 200.0], "mapPose": [1.0, -2.0, 0.0], "name": "충전1", "category": "충전"},
            {"point": [300.0, 200.0], "mapPose": [3.0, -2.0, 0.0], "name": "대기1", "category": "대기"},
        ],
        "laneDirections": [
            {
                "start": [100.0, 200.0],
                "end": [300.0, 200.0],
                "direction": "양방향",
            }
        ],
    }


def save_body() -> dict:
    return {
        "format_version": 2,
        "payload": project1_payload(),
        "building_yaml": "name: project1\nlevels:\n  L1: {}\n",
        "building_yaml_name": "project1.building.yaml",
        "files": [],
        "fleet": {
            "fleet_name": "project1_pinky",
            "settings": {"fleetName": "project1_pinky"},
        },
        "robots": [
            {
                "robot_id": "PK_01",
                "seq": 1,
                "display_name": "Pinky 1",
                "model": "Pinky-Pro",
                "kind": "mobile",
                "data_source": "gazebo",
                "gz_name": "pinky_01",
                "zones": ["ambient"],
                "charger_waypoint_name": "충전1",
                "spawn_x": 1.0,
                "spawn_y": 2.0,
                "spawn_heading": 0.0,
            }
        ],
    }


def publish_body(world_content: str = "<sdf version='1.9'></sdf>") -> dict:
    building = save_body()["building_yaml"]
    nav_graph = """building_name: project1
levels:
  L1:
    vertices:
      - [1.0, -2.0, {name: 충전1}]
      - [3.0, -2.0, {name: 대기1}]
    lanes: [[0, 1, {}], [1, 0, {}]]
"""
    hashes = {
        "building_sha256": hashlib.sha256(building.encode()).hexdigest(),
        "nav_graph_sha256": hashlib.sha256(nav_graph.encode()).hexdigest(),
        "world_sha256": hashlib.sha256(world_content.encode()).hexdigest(),
    }
    revision_hash = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "map_revision": "project1:" + revision_hash,
        **hashes,
        "building_yaml_content": building,
        "nav_graph_yaml_content": nav_graph,
        "world_content": world_content,
        "published_by": "W-OP-01",
        "manifest": {"project": "project1"},
    }


def test_draft_save_assigns_stable_ids_and_project1_location_codes():
    client = TestClient(create_app(InMemoryFmsRepository()))

    created = client.put("/internal/v1/map-projects/project1", json=save_body())
    assert created.status_code == 200
    body = created.json()
    assert body["draft_revision"] == 1
    waypoints = body["payload"]["waypoints"]
    assert waypoints[0]["locationCode"] == "CHG-01"
    assert waypoints[1]["locationCode"] == "IN-WAIT-01"
    assert len(waypoints[0]["waypointUuid"]) == 36
    assert "laneDirections" not in body["payload"]
    assert body["lane_count"] == 0

    second = client.put(
        "/internal/v1/map-projects/project1",
        headers={"If-Match": '"1"'},
        json={**save_body(), "payload": body["payload"]},
    )
    assert second.status_code == 200
    assert second.json()["draft_revision"] == 2
    assert second.json()["payload"]["waypoints"][0]["waypointUuid"] == waypoints[0]["waypointUuid"]
    assert "laneDirections" not in second.json()["payload"]
    assert second.json()["lane_count"] == 0


def test_draft_list_get_and_revision_conflict_are_explicit():
    client = TestClient(create_app(InMemoryFmsRepository()))
    client.put("/internal/v1/map-projects/project1", json=save_body())

    summaries = client.get("/internal/v1/map-projects").json()
    assert len(summaries) == 1
    assert summaries[0]["map_name"] == "project1"
    assert summaries[0]["drawing_name"] == "project1.png"
    assert summaries[0]["format_version"] == 2
    assert summaries[0]["waypoint_count"] == 2
    assert summaries[0]["lane_count"] == 0
    assert summaries[0]["draft_revision"] == 1
    assert summaries[0]["has_building_yaml"] is True
    assert summaries[0]["updated_at"].endswith("+09:00")
    assert client.get("/internal/v1/map-projects/project1").status_code == 200
    conflict = client.put(
        "/internal/v1/map-projects/project1",
        headers={"If-Match": '"9"'},
        json=save_body(),
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "map draft revision conflict"


def test_publish_is_validated_idempotent_and_content_fenced():
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository))
    client.put("/internal/v1/map-projects/project1", json=save_body())

    validation = client.post("/internal/v1/map-projects/project1/validate")
    assert validation.status_code == 200
    assert validation.json() == {"valid": True, "errors": []}

    first = client.post(
        "/internal/v1/map-projects/project1/publish", json=publish_body()
    )
    replay = client.post(
        "/internal/v1/map-projects/project1/publish", json=publish_body()
    )
    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["map_revision"] == publish_body()["map_revision"]
    assert client.get("/internal/v1/maps/project1/published").json() == first.json()

    changed_world = publish_body(world_content="<sdf version='1.8'></sdf>")
    conflict = client.post(
        "/internal/v1/map-projects/project1/publish",
        json={**changed_world, "map_revision": publish_body()["map_revision"]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "map revision content conflict"

    manifest_conflict = client.post(
        "/internal/v1/map-projects/project1/publish",
        json={**publish_body(), "manifest": {"project": "다른 원본"}},
    )
    assert manifest_conflict.status_code == 409


def test_publish_rejects_operational_waypoint_without_location_code():
    client = TestClient(create_app(InMemoryFmsRepository()))
    body = save_body()
    body["payload"]["waypoints"][1]["name"] = "새 대기점"
    client.put("/internal/v1/map-projects/project2", json=body)

    validation = client.post("/internal/v1/map-projects/project2/validate")
    assert validation.status_code == 200
    assert validation.json()["valid"] is False
    assert "새 대기점: locationCode가 필요합니다" in validation.json()["errors"]
    published = client.post(
        "/internal/v1/map-projects/project2/publish",
        json={**publish_body(), "map_revision": "project2:" + "d" * 64},
    )
    assert published.status_code == 422


def test_ui_resave_preserves_map_pose_only_while_drawing_point_is_unchanged():
    client = TestClient(create_app(InMemoryFmsRepository()))
    created = client.put("/internal/v1/map-projects/project1", json=save_body()).json()

    ui_body = save_body()
    for waypoint in ui_body["payload"]["waypoints"]:
        waypoint.pop("mapPose", None)
        waypoint.pop("locationCode", None)
        waypoint.pop("waypointUuid", None)
        waypoint.pop("rmfWaypointName", None)
    preserved = client.put(
        "/internal/v1/map-projects/project1",
        headers={"If-Match": f'"{created["draft_revision"]}"'},
        json=ui_body,
    ).json()
    assert preserved["payload"]["waypoints"][0]["mapPose"] == [1.0, -2.0, 0.0]

    moved_body = save_body()
    moved_body["payload"]["waypoints"][0]["point"] = [101.0, 200.0]
    moved_body["payload"]["waypoints"][0].pop("mapPose")
    moved = client.put(
        "/internal/v1/map-projects/project1",
        headers={"If-Match": f'"{preserved["draft_revision"]}"'},
        json=moved_body,
    ).json()
    assert "mapPose" not in moved["payload"]["waypoints"][0]
    assert (
        moved["payload"]["waypoints"][0]["waypointUuid"]
        != preserved["payload"]["waypoints"][0]["waypointUuid"]
    )
    validation = client.post("/internal/v1/map-projects/project1/validate").json()
    assert "충전1: publish용 mapPose(m)가 필요합니다" in validation["errors"]


def test_publish_rejects_mobile_robot_without_a_charger_waypoint():
    client = TestClient(create_app(InMemoryFmsRepository()))
    body = save_body()
    body["robots"][0]["charger_waypoint_name"] = "없는 충전기"
    client.put("/internal/v1/map-projects/project1", json=body)

    validation = client.post("/internal/v1/map-projects/project1/validate").json()
    assert "PK_01: 충전 Waypoint 연결이 필요합니다" in validation["errors"]


def test_publish_revision_must_be_namespaced_by_map_name():
    client = TestClient(create_app(InMemoryFmsRepository()))
    client.put("/internal/v1/map-projects/project1", json=save_body())
    body = {**publish_body(), "map_revision": "other:" + "d" * 64}

    response = client.post("/internal/v1/map-projects/project1/publish", json=body)

    assert response.status_code == 409
    assert response.json()["detail"] == "map revision content conflict"


def test_published_project_cannot_be_deleted():
    client = TestClient(create_app(InMemoryFmsRepository()))
    client.put("/internal/v1/map-projects/project1", json=save_body())
    client.post("/internal/v1/map-projects/project1/publish", json=publish_body())

    response = client.delete("/internal/v1/map-projects/project1")
    assert response.status_code == 409
    assert response.json()["detail"] == "published map project cannot be deleted"
