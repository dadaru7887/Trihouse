import hashlib
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


def test_mysql_publish_projects_operational_role_parent_and_bottleneck(
    seeded_schema, mysql_db
):
    gateway = repository()
    building = "name: project1\nlevels:\n  L1: {}\n"
    project = {
        "format_version": 2,
        "payload": {
            "format": "robosapiens-map-project",
            "version": 2,
            "mapName": "project1",
            "waypoints": [
                {
                    "point": [100.0, 200.0],
                    "mapPose": [1.0, -2.0, 0.0],
                    "name": "Charging Station 01",
                    "rmfWaypointName": "charging_station_01",
                    "locationCode": "PROJECT1-CHG-01",
                    "category": "charger",
                    "operationalRole": "charging_station",
                    "temperatureZone": None,
                    "parentLocationCode": None,
                },
                {
                    "point": [300.0, 200.0],
                    "mapPose": [3.0, -2.0, 0.0],
                    "name": "Chilled Storage Loading Dock 02",
                    "rmfWaypointName": "chilled_loading_dock_02",
                    "locationCode": "WH-CHL-01-DOCK-02",
                    "category": "holding",
                    "operationalRole": "loading_dock",
                    "temperatureZone": "chilled",
                    "parentLocationCode": "WH-CHL-01",
                },
            ],
            "laneDirections": [
                {
                    "start": [100.0, 200.0],
                    "end": [300.0, 200.0],
                    "direction": "양방향",
                    "mutex": "bottleneck_01",
                }
            ],
            "bottleneckZones": [
                {
                    "featureCode": "PROJECT1-BOTTLENECK-01",
                    "featureType": "bottleneck",
                    "name": "Bottleneck Zone 01",
                    "mapPose": [4.2, -1.3],
                    "radiusM": 1.5,
                    "mutexGroup": "bottleneck_01",
                }
            ],
        },
        "building_yaml": building,
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
                "zones": ["chilled"],
                "charger_waypoint_name": "charging_station_01",
                "spawn_x": 1.0,
                "spawn_y": -2.0,
                "spawn_heading": 0.0,
            }
        ],
    }
    gateway.save_map_project("project1", project, None)
    nav_graph = """levels:
  L1:
    vertices:
      - [1.0, -2.0, {name: charging_station_01}]
      - [3.0, -2.0, {name: chilled_loading_dock_02}]
"""
    world = "<sdf version='1.9'></sdf>"
    hashes = {
        "building_sha256": hashlib.sha256(building.encode()).hexdigest(),
        "nav_graph_sha256": hashlib.sha256(nav_graph.encode()).hexdigest(),
        "world_sha256": hashlib.sha256(world.encode()).hexdigest(),
    }
    revision_hash = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    publication = gateway.publish_map_project(
        "project1",
        {
            "map_revision": f"project1:{revision_hash}",
            **hashes,
            "building_yaml_content": building,
            "nav_graph_yaml_content": nav_graph,
            "world_content": world,
            "published_by": "W-OP-01",
            "manifest": {"project": "project1"},
        },
    )

    draft = mysql_db.one(
        "SELECT category, operational_role, temperature_zone, parent_location_code "
        "FROM map_project_waypoints WHERE location_code = 'WH-CHL-01-DOCK-02'"
    )
    assert draft == {
        "category": "holding",
        "operational_role": "loading_dock",
        "temperature_zone": "chilled",
        "parent_location_code": "WH-CHL-01",
    }
    location = mysql_db.one(
        "SELECT location_type, temperature_zone, parent_location_id, metadata "
        "FROM locations WHERE location_code = 'WH-CHL-01-DOCK-02'"
    )
    assert location["location_type"] == "loading_dock"
    assert location["temperature_zone"] == "chilled"
    assert location["parent_location_id"] == mysql_db.one(
        "SELECT location_id FROM locations WHERE location_code = 'WH-CHL-01'"
    )["location_id"]
    metadata = (
        json.loads(location["metadata"])
        if isinstance(location["metadata"], str)
        else location["metadata"]
    )
    assert metadata["operational_role"] == "loading_dock"
    feature = mysql_db.one(
        "SELECT feature_type, geometry, properties FROM map_features "
        "WHERE map_revision = %s AND feature_code = 'PROJECT1-BOTTLENECK-01'",
        (publication["map_revision"],),
    )
    geometry = json.loads(feature["geometry"]) if isinstance(feature["geometry"], str) else feature["geometry"]
    properties = json.loads(feature["properties"]) if isinstance(feature["properties"], str) else feature["properties"]
    assert feature["feature_type"] == "bottleneck"
    assert geometry == {"type": "Point", "coordinates": [4.2, -1.3]}
    assert properties == {"radius_m": 1.5, "mutex_group": "bottleneck_01"}
