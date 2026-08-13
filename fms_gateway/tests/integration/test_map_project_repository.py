import hashlib
import json

from fms_gateway.app.config import get_settings
from fms_gateway.app.database import Database
from fms_gateway.app.repositories import MySqlFmsRepository


def _project() -> dict:
    return {
        "format_version": 2,
        "payload": {
            "format": "robosapiens-map-project",
            "version": 2,
            "mapName": "project1",
            "waypoints": [
                {"point": [200.0, 200.0], "mapPose": [2.0, -2.0, 0.0], "name": "충전1", "category": "충전"},
                {"point": [500.0, 200.0], "mapPose": [5.0, -2.0, 0.0], "name": "대기1", "category": "대기"},
            ],
            "laneDirections": [
                {"start": [200.0, 200.0], "end": [500.0, 200.0], "direction": "양방향"}
            ],
        },
        "building_yaml": "name: project1\nlevels:\n  L1: {}\n",
        "building_yaml_name": "project1.building.yaml",
        "files": [],
        "fleet": {"fleet_name": "project1_pinky", "settings": {}},
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
                "spawn_x": 2.0,
                "spawn_y": 2.0,
                "spawn_heading": 0.0,
            }
        ],
    }


def test_mysql_project_publish_updates_authoring_and_operational_projection(
    mysql_db,
):
    get_settings.cache_clear()
    repository = MySqlFmsRepository(Database(get_settings()))

    saved = repository.save_map_project("project1", _project(), None)
    assert saved["draft_revision"] == 1
    assert saved["payload"]["waypoints"][0]["locationCode"] == "CHG-01"

    building = _project()["building_yaml"]
    nav_graph = """levels:\n  L1:\n    vertices:\n      - [2.0, -2.0, {name: 충전1}]\n      - [5.0, -2.0, {name: 대기1}]\n"""
    world = "<sdf version='1.9'></sdf>"
    hashes = {
        "building_sha256": hashlib.sha256(building.encode()).hexdigest(),
        "nav_graph_sha256": hashlib.sha256(nav_graph.encode()).hexdigest(),
        "world_sha256": hashlib.sha256(world.encode()).hexdigest(),
    }
    revision = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    publication = repository.publish_map_project(
        "project1",
        {
            "map_revision": "project1:" + revision,
            **hashes,
            "building_yaml_content": building,
            "nav_graph_yaml_content": nav_graph,
            "world_content": world,
            "published_by": "W-OP-01",
            "manifest": {"project": "project1"},
        },
    )
    assert publication["state"] == "published"

    charger = mysql_db.one(
        "SELECT map_name, rmf_waypoint_name, pose_x, pose_y, metadata "
        "FROM locations WHERE location_code = 'CHG-01'"
    )
    assert charger["map_name"] == "project1"
    assert charger["rmf_waypoint_name"] == "충전1"
    assert charger["pose_x"] == 2.0
    assert charger["pose_y"] == -2.0

    robot = mysql_db.one(
        "SELECT fleet_name, home_location_id, current_location_id, control_mode "
        "FROM devices WHERE device_id = 'PK_01'"
    )
    assert robot["fleet_name"] == "project1_pinky"
    assert robot["home_location_id"] == mysql_db.one(
        "SELECT location_id FROM locations WHERE location_code = 'CHG-01'"
    )["location_id"]
    assert robot["current_location_id"] is None
    assert robot["control_mode"] == "automatic"
