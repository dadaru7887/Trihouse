from copy import deepcopy

from fastapi.testclient import TestClient

from fms_gateway.app.main import create_app
from fms_gateway.app.repositories import InMemoryFmsRepository
from test_map_project_api import publish_body, save_body


def canonical_body() -> dict:
    body = deepcopy(save_body())
    body["payload"].pop("laneDirections", None)
    charger, chilled = body["payload"]["waypoints"]
    charger.update(
        {
            "category": "charger",
            "operationalRole": "charging_station",
            "temperatureZone": None,
            "parentLocationCode": None,
        }
    )
    chilled.update(
        {
            "category": "holding",
            "operationalRole": "bottleneck_waiting_point",
            "temperatureZone": "chilled",
            "parentLocationCode": "WH-CHL-01",
        }
    )
    body["payload"]["bottleneckZones"] = [
        {
            "featureCode": "PROJECT1-BOTTLENECK-01",
            "featureType": "bottleneck",
            "name": "Bottleneck Zone 01",
            "mapPose": [4.2, -1.3],
            "radiusM": 1.5,
            "mutexGroup": "bottleneck_01",
        }
    ]
    return body


def test_bottleneck_mutex_group_is_independent_of_deprecated_lanes():
    client = TestClient(create_app(InMemoryFmsRepository()))
    body = canonical_body()
    body["payload"]["bottleneckZones"][0]["mutexGroup"] = "unlinked_group"
    client.put("/internal/v1/map-projects/project1", json=body)

    validation = client.post(
        "/internal/v1/map-projects/project1/validate"
    ).json()
    assert validation == {"valid": True, "errors": []}


def test_legacy_lane_fields_are_discarded_without_affecting_bottlenecks():
    for lane_field in ("mutex", "mutexGroup"):
        client = TestClient(create_app(InMemoryFmsRepository()))
        body = canonical_body()
        body["payload"]["laneDirections"] = [
            {lane_field: "legacy_group", "malformedLegacyLane": True}
        ]
        saved = client.put("/internal/v1/map-projects/project1", json=body)

        validation = client.post(
            "/internal/v1/map-projects/project1/validate"
        ).json()

        assert saved.status_code == 200
        assert "laneDirections" not in saved.json()["payload"]
        assert validation == {"valid": True, "errors": []}


def test_draft_preserves_roles_and_returns_canonical_english_categories():
    client = TestClient(create_app(InMemoryFmsRepository()))

    canonical = client.put(
        "/internal/v1/map-projects/project1", json=canonical_body()
    )
    legacy = client.put(
        "/internal/v1/map-projects/legacy", json=save_body()
    )

    assert canonical.status_code == legacy.status_code == 200
    chilled = canonical.json()["payload"]["waypoints"][1]
    assert chilled["category"] == "holding"
    assert chilled["operationalRole"] == "bottleneck_waiting_point"
    assert chilled["temperatureZone"] == "chilled"
    assert chilled["parentLocationCode"] == "WH-CHL-01"
    assert legacy.json()["payload"]["waypoints"][0]["category"] == "charger"
    assert legacy.json()["payload"]["waypoints"][1]["category"] == "holding"


def test_legacy_pickup_and_dropoff_are_both_normalized_to_loading_dock():
    client = TestClient(create_app(InMemoryFmsRepository()))
    body = save_body()
    body["payload"]["waypoints"][0]["category"] = "픽업"
    body["payload"]["waypoints"][1]["category"] = "드랍오프"

    saved = client.put("/internal/v1/map-projects/project1", json=body)

    assert saved.status_code == 200
    for waypoint in saved.json()["payload"]["waypoints"]:
        assert waypoint["category"] == "holding"
        assert waypoint["operationalRole"] == "loading_dock"


def test_validation_reports_role_temperature_parent_and_bottleneck_errors():
    client = TestClient(create_app(InMemoryFmsRepository()))
    body = canonical_body()
    body["payload"]["waypoints"][0]["operationalRole"] = "unknown_role"
    chilled = body["payload"]["waypoints"][1]
    chilled["temperatureZone"] = "hot"
    chilled["parentLocationCode"] = None
    body["payload"]["bottleneckZones"][0].update(
        {"mapPose": [4.2], "radiusM": 0, "mutexGroup": ""}
    )
    client.put("/internal/v1/map-projects/project1", json=body)

    validation = client.post(
        "/internal/v1/map-projects/project1/validate"
    ).json()

    assert validation["valid"] is False
    assert any("operationalRole" in error for error in validation["errors"])
    assert any("temperatureZone" in error for error in validation["errors"])
    assert any("parentLocationCode" in error for error in validation["errors"])
    assert any("mapPose" in error for error in validation["errors"])
    assert any("radiusM" in error for error in validation["errors"])
    assert any("mutexGroup" in error for error in validation["errors"])


def test_validation_rejects_duplicate_gazebo_namespaces():
    client = TestClient(create_app(InMemoryFmsRepository()))
    body = canonical_body()
    duplicate = deepcopy(body["robots"][0])
    duplicate.update(
        {
            "robot_id": "PK_02",
            "seq": 2,
            "gz_name": duplicate["gz_name"].upper(),
        }
    )
    body["robots"].append(duplicate)
    client.put("/internal/v1/map-projects/project1", json=body)

    validation = client.post(
        "/internal/v1/map-projects/project1/validate"
    ).json()

    assert validation["valid"] is False
    assert any("gz_name" in error and "중복" in error for error in validation["errors"])


def test_publish_projects_canonical_location_and_bottleneck_feature():
    repository = InMemoryFmsRepository(
        seed_locations=[
            {
                "location_id": 41,
                "location_code": "WH-CHL-01",
                "name": "Chilled Warehouse",
                "location_type": "rack",
                "temperature_zone": "chilled",
                "metadata": {},
            }
        ]
    )
    client = TestClient(create_app(repository))
    client.put("/internal/v1/map-projects/project1", json=canonical_body())

    published = client.post(
        "/internal/v1/map-projects/project1/publish", json=publish_body()
    )

    assert published.status_code == 200
    chilled = repository.get_projected_location("IN-WAIT-01")
    assert chilled == {
        "location_id": chilled["location_id"],
        "parent_location_id": 41,
        "location_code": "IN-WAIT-01",
        "name": "대기1",
        "location_type": "staging",
        "temperature_zone": "chilled",
        "map_name": "project1",
        "rmf_waypoint_name": "대기1",
        "pose_x": 3.0,
        "pose_y": -2.0,
        "pose_yaw": 0.0,
        "metadata": {
            "authoring_managed": True,
            "active": True,
            "waypoint_uuid": chilled["metadata"]["waypoint_uuid"],
            "map_revision": published.json()["map_revision"],
            "operational_role": "bottleneck_waiting_point",
            "rmf_category": "holding",
            "parent_location_code": "WH-CHL-01",
        },
    }
    assert repository.list_projected_map_features(published.json()["map_revision"]) == [
        {
            "map_name": "project1",
            "map_revision": published.json()["map_revision"],
            "feature_code": "PROJECT1-BOTTLENECK-01",
            "feature_type": "bottleneck",
            "geometry": {"type": "Point", "coordinates": [4.2, -1.3]},
            "properties": {"radius_m": 1.5, "mutex_group": "bottleneck_01"},
            "active": True,
        }
    ]


def test_publish_rejects_location_code_owned_by_another_map_without_metadata_flag():
    contested = {
        "location_id": 40,
        "location_code": "CHG-01",
        "name": "Other Map Charger",
        "location_type": "charging",
        "temperature_zone": None,
        "map_name": "other-map",
        "rmf_waypoint_name": "other_map_charger",
        "pose_x": 9.0,
        "pose_y": 8.0,
        "pose_yaw": 0.0,
        "metadata": {},
    }
    repository = InMemoryFmsRepository(
        seed_locations=[
            contested,
            {
                "location_id": 41,
                "location_code": "WH-CHL-01",
                "name": "Chilled Warehouse",
                "location_type": "rack",
                "temperature_zone": "chilled",
                "map_name": None,
                "metadata": {},
            },
        ]
    )
    client = TestClient(create_app(repository))
    client.put("/internal/v1/map-projects/project1", json=canonical_body())

    published = client.post(
        "/internal/v1/map-projects/project1/publish", json=publish_body()
    )

    assert published.status_code == 422
    assert published.json()["detail"] == {
        "code": "map project invalid",
        "errors": ["CHG-01: 다른 published map이 소유합니다"]
    }
    assert repository.get_projected_location("CHG-01") == contested


def _repository_with_chilled_parent() -> InMemoryFmsRepository:
    return InMemoryFmsRepository(
        seed_locations=[
            {
                "location_id": 41,
                "location_code": "WH-CHL-01",
                "name": "Chilled Storage",
                "location_type": "rack",
                "temperature_zone": "chilled",
                "metadata": {},
            }
        ]
    )


def test_loading_dock_is_direction_neutral_and_waiting_point_is_staging():
    for role, expected_type in (
        ("loading_dock", "loading_dock"),
        ("bottleneck_waiting_point", "staging"),
    ):
        repository = _repository_with_chilled_parent()
        client = TestClient(create_app(repository))
        body = deepcopy(save_body())
        waypoint = body["payload"]["waypoints"][1]
        waypoint.update(
            {
                "name": f"Chilled {role}",
                "rmfWaypointName": "대기1",
                "category": "holding",
                "operationalRole": role,
                "temperatureZone": "chilled",
                "parentLocationCode": "WH-CHL-01",
            }
        )
        client.put("/internal/v1/map-projects/project1", json=body)

        published = client.post(
            "/internal/v1/map-projects/project1/publish", json=publish_body()
        )

        assert published.status_code == 200
        location = repository.get_projected_location("IN-WAIT-01")
        assert location["location_type"] == expected_type
        assert location["parent_location_id"] == 41
        assert location["metadata"]["operational_role"] == role
        assert location["metadata"]["rmf_category"] == "holding"


def test_explicit_transit_waypoint_cannot_become_an_operational_location():
    client = TestClient(create_app(InMemoryFmsRepository()))
    body = deepcopy(save_body())
    body["payload"]["waypoints"][1].update(
        {
            "category": "waypoint",
            "operationalRole": "transit_waypoint",
            "temperatureZone": None,
            "parentLocationCode": None,
            "locationCode": "PROJECT1-TRANSIT-01",
        }
    )
    client.put("/internal/v1/map-projects/project1", json=body)

    validation = client.post(
        "/internal/v1/map-projects/project1/validate"
    ).json()

    assert validation["valid"] is False
    assert "대기1: Transit Waypoint에는 locationCode를 지정할 수 없습니다" in validation["errors"]


def test_bottleneck_projects_waiting_point_links_and_aruco_marker():
    repository = _repository_with_chilled_parent()
    client = TestClient(create_app(repository))
    body = canonical_body()
    body["payload"]["waypoints"][1].update(
        {
            "category": "holding",
            "operationalRole": "bottleneck_waiting_point",
        }
    )
    body["payload"]["bottleneckZones"][0].update(
        {
            "entryWaitingPoint": "IN-WAIT-01",
            "exitWaitingPoint": "IN-WAIT-01",
            "arucoMarkerId": 201,
        }
    )
    client.put("/internal/v1/map-projects/project1", json=body)

    published = client.post(
        "/internal/v1/map-projects/project1/publish", json=publish_body()
    )

    assert published.status_code == 200
    feature = repository.list_projected_map_features(
        published.json()["map_revision"]
    )[0]
    assert feature["properties"] == {
        "radius_m": 1.5,
        "mutex_group": "bottleneck_01",
        "entry_waiting_point": "IN-WAIT-01",
        "exit_waiting_point": "IN-WAIT-01",
        "aruco_marker_id": 201,
    }
