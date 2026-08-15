import hashlib
import json
from pathlib import Path
import threading
import time

from fastapi.testclient import TestClient

from fms_gateway.app.main import create_app
from fms_gateway.app.repositories import InMemoryFmsRepository


ROOT = Path(__file__).resolve().parents[3]
PHYSICAL_JSONL = (
    ROOT
    / "control_ui"
    / "rmf_control_ui"
    / "data"
    / "import"
    / "trihouse_test_01_physical_features.jsonl"
)


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


def _public_draft(
    profile_hash: str,
    *,
    staged_source_tokens: dict[str, str] | None = None,
    source_uuids: dict[str, str] | None = None,
    waypoints: list[dict] | None = None,
    features: list[dict] | None = None,
) -> dict:
    return {
        "map_name": "trihouse_test_01",
        "format_version": 1,
        "draft_revision": 0,
        "source_uuids": source_uuids or {},
        "staged_source_tokens": staged_source_tokens or {},
        "waypoints": waypoints or [],
        "features": features or [],
        "runtime_profile_hash": profile_hash,
    }


def _stage(
    client: TestClient,
    map_name: str,
    source_type: str,
    content: bytes,
    *,
    file_name: str,
    mime_type: str,
) -> dict:
    response = client.post(
        f"/api/v1/map-projects/{map_name}/sources/stage",
        data={"source_type": source_type},
        files={"source": (file_name, content, mime_type)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _profile_hash(client: TestClient) -> str:
    response = client.get("/api/v1/runtime-profiles/pinky-pro-simulation")
    assert response.status_code == 200, response.text
    return response.json()["profile_hash"]


def test_saved_draft_reopens_and_unsaved_edit_does_not_persist(tmp_path: Path):
    client = TestClient(
        create_app(InMemoryFmsRepository(), map_runtime_root=tmp_path)
    )
    profile_hash = _profile_hash(client)

    saved = client.put(
        "/api/v1/map-projects/trihouse_test_01",
        json=_public_draft(
            profile_hash,
            waypoints=[
                {
                    "code": "manual-1",
                    "display_name": "Manual 1",
                    "x": 0.25,
                    "y": -0.5,
                    "yaw": 1.25,
                    "origin": "manual",
                }
            ],
        ),
        headers={"If-Match": "0"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["draft_revision"] == 1

    unsaved_local_copy = saved.json()
    unsaved_local_copy["waypoints"][0]["x"] = 99.0
    reopened = client.get("/api/v1/map-projects/trihouse_test_01")
    assert reopened.status_code == 200
    assert reopened.json()["draft_revision"] == 1
    assert reopened.json()["waypoints"][0]["x"] == 0.25


def test_same_deployed_name_opens_existing_instead_of_duplicate_error(
    tmp_path: Path,
):
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository, map_runtime_root=tmp_path))
    profile_hash = _profile_hash(client)
    saved = client.put(
        "/api/v1/map-projects/trihouse_test_01",
        json=_public_draft(profile_hash),
        headers={"If-Match": "0"},
    )
    assert saved.status_code == 200

    response = client.post(
        "/api/v1/map-projects", json={"map_name": "trihouse_test_01"}
    )

    assert response.status_code == 200
    assert response.json()["open_existing"] is True
    assert response.json()["draft"]["draft_revision"] == 1
    assert response.json()["active_revision"] is None


def test_source_stage_is_db_free_and_save_is_project_scoped_and_replay_safe(
    tmp_path: Path,
):
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository, map_runtime_root=tmp_path))
    profile_hash = _profile_hash(client)
    staged = _stage(
        client,
        "trihouse_test_01",
        "physical_features_import",
        PHYSICAL_JSONL.read_bytes(),
        file_name="operator-selected-source.data",
        mime_type="application/x-ndjson",
    )
    assert repository.list_map_projects() == []

    cross_project = client.put(
        "/api/v1/map-projects/another_project",
        json={
            **_public_draft(
                profile_hash,
                staged_source_tokens={
                    "physical_features_import": staged["upload_token"]
                },
            ),
            "map_name": "another_project",
        },
        headers={"If-Match": "0"},
    )
    assert cross_project.status_code == 422
    assert cross_project.json()["detail"]["code"] == "STAGED_SOURCE_PROJECT_MISMATCH"

    saved = client.put(
        "/api/v1/map-projects/trihouse_test_01",
        json=_public_draft(
            profile_hash,
            staged_source_tokens={
                "physical_features_import": staged["upload_token"]
            },
            waypoints=staged["waypoints"],
            features=staged["features"],
        ),
        headers={"If-Match": "0"},
    )
    assert saved.status_code == 200, saved.text
    source_uuid = saved.json()["source_uuids"]["physical_features_import"]
    assert repository.get_map_project_source("trihouse_test_01", source_uuid)

    replay = client.put(
        "/api/v1/map-projects/trihouse_test_01",
        json=_public_draft(
            profile_hash,
            staged_source_tokens={
                "physical_features_import": staged["upload_token"]
            },
        )
        | {"draft_revision": 1},
        headers={"If-Match": "1"},
    )
    assert replay.status_code == 422
    assert replay.json()["detail"]["code"] == "STAGED_SOURCE_TOKEN_INVALID"


def test_same_jsonl_can_be_saved_by_two_projects_with_distinct_source_identity(
    tmp_path: Path,
):
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository, map_runtime_root=tmp_path))
    profile_hash = _profile_hash(client)
    saved_sources = []
    for map_name in ("trihouse_test_01", "another_project"):
        staged = _stage(
            client,
            map_name,
            "physical_features_import",
            PHYSICAL_JSONL.read_bytes(),
            file_name=f"{map_name}.jsonl",
            mime_type="application/x-ndjson",
        )
        body = {
            **_public_draft(
                profile_hash,
                staged_source_tokens={
                    "physical_features_import": staged["upload_token"]
                },
                waypoints=staged["waypoints"],
                features=staged["features"],
            ),
            "map_name": map_name,
        }
        response = client.put(
            f"/api/v1/map-projects/{map_name}",
            json=body,
            headers={"If-Match": "0"},
        )
        assert response.status_code == 200, response.text
        source_uuid = response.json()["source_uuids"][
            "physical_features_import"
        ]
        saved_sources.append(repository.get_map_project_source(map_name, source_uuid))

    assert saved_sources[0]["source_uuid"] != saved_sources[1]["source_uuid"]
    assert saved_sources[0]["sha256"] == saved_sources[1]["sha256"]


def test_source_stage_rejects_path_mime_size_and_expired_tokens(tmp_path: Path):
    client = TestClient(
        create_app(
            InMemoryFmsRepository(),
            map_runtime_root=tmp_path,
            map_source_max_bytes=16,
            map_source_token_ttl_seconds=0.01,
        )
    )
    for file_name, mime_type, content in (
        ("../escape.yaml", "application/x-yaml", b"image: map.pgm\n"),
        ("map.yaml", "text/plain", b"image: map.pgm\n"),
        ("map.yaml", "application/x-yaml", b"x" * 17),
    ):
        response = client.post(
            "/api/v1/map-projects/trihouse_test_01/sources/stage",
            data={"source_type": "slam_yaml"},
            files={"source": (file_name, content, mime_type)},
        )
        assert response.status_code == 422

    staged = _stage(
        client,
        "trihouse_test_01",
        "slam_yaml",
        b"image: map.pgm\n",
        file_name="map.yaml",
        mime_type="application/x-yaml",
    )
    time.sleep(0.02)
    expired = client.put(
        "/api/v1/map-projects/trihouse_test_01",
        json=_public_draft(
            _profile_hash(client),
            staged_source_tokens={"slam_yaml": staged["upload_token"]},
        ),
        headers={"If-Match": "0"},
    )
    assert expired.status_code == 422
    assert expired.json()["detail"]["code"] == "STAGED_SOURCE_TOKEN_EXPIRED"


def test_concurrent_public_save_with_one_token_returns_200_and_stable_409(
    tmp_path: Path, monkeypatch
):
    repository = InMemoryFmsRepository()
    app = create_app(repository, map_runtime_root=tmp_path)
    client = TestClient(app)
    staged = _stage(
        client,
        "trihouse_test_01",
        "slam_yaml",
        b"image: floor.pgm\n",
        file_name="floor.yaml",
        mime_type="application/x-yaml",
    )
    staging = app.state.map_source_staging
    barrier = threading.Barrier(2)
    original = staging._source_from_dir

    def synchronized_read(directory: Path):
        source = original(directory)
        if directory.parent == staging.pending_root:
            barrier.wait(timeout=3)
        return source

    monkeypatch.setattr(staging, "_source_from_dir", synchronized_read)
    body = _public_draft(
        _profile_hash(client),
        staged_source_tokens={"slam_yaml": staged["upload_token"]},
    )
    responses = []

    def save() -> None:
        concurrent_client = TestClient(app)
        responses.append(
            concurrent_client.put(
                "/api/v1/map-projects/trihouse_test_01",
                json=body,
                headers={"If-Match": "0"},
            )
        )

    threads = [threading.Thread(target=save) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert sorted(response.status_code for response in responses) == [200, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["detail"]["code"] == "STAGED_SOURCE_TOKEN_CONSUMED"
    assert repository.get_public_map_draft("trihouse_test_01")["draft_revision"] == 1


def test_delete_without_active_removes_draft_and_unreferenced_sources(tmp_path: Path):
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository, map_runtime_root=tmp_path))
    staged = _stage(
        client,
        "trihouse_test_01",
        "slam_yaml",
        b"image: map.pgm\nresolution: 0.05\norigin: [0, 0, 0]\n",
        file_name="map.yaml",
        mime_type="application/x-yaml",
    )
    saved = client.put(
        "/api/v1/map-projects/trihouse_test_01",
        json=_public_draft(
            _profile_hash(client),
            staged_source_tokens={"slam_yaml": staged["upload_token"]},
        ),
        headers={"If-Match": "0"},
    )
    source_uuid = saved.json()["source_uuids"]["slam_yaml"]

    deleted = client.delete("/api/v1/map-projects/trihouse_test_01/draft")

    assert deleted.status_code == 204
    assert client.get("/api/v1/map-projects/trihouse_test_01").status_code == 404
    assert repository.get_map_project_source("trihouse_test_01", source_uuid) is None


def test_publish_failure_preserves_active_without_audit_and_delete_restores_it(
    tmp_path: Path,
):
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository, map_runtime_root=tmp_path))
    profile_hash = _profile_hash(client)
    staged_physical = _stage(
        client,
        "trihouse_test_01",
        "physical_features_import",
        PHYSICAL_JSONL.read_bytes(),
        file_name="physical.data",
        mime_type="application/x-ndjson",
    )
    staged_yaml = _stage(
        client,
        "trihouse_test_01",
        "slam_yaml",
        (
            b"image: floor.pgm\nresolution: 0.05\norigin: [0, 0, 0]\n"
            b"negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n"
        ),
        file_name="floor.yaml",
        mime_type="application/x-yaml",
    )
    staged_image = _stage(
        client,
        "trihouse_test_01",
        "slam_image",
        b"P5\n1 1\n255\n\x00",
        file_name="floor.pgm",
        mime_type="image/x-portable-graymap",
    )
    tokens = {
        value["source_type"]: value["upload_token"]
        for value in (staged_physical, staged_yaml, staged_image)
    }
    saved = client.put(
        "/api/v1/map-projects/trihouse_test_01",
        json=_public_draft(
            profile_hash,
            staged_source_tokens=tokens,
            waypoints=staged_physical["waypoints"],
            features=staged_physical["features"],
        ),
        headers={"If-Match": "0"},
    )
    assert saved.status_code == 200, saved.text
    first_draft = saved.json()
    published = client.post(
        "/api/v1/map-projects/trihouse_test_01/publish",
        json={"expected_draft_revision": 1, "published_by": "W-OP-01"},
    )
    assert published.status_code == 200, published.text
    active_revision = published.json()["map_revision"]
    repeated = client.post(
        "/api/v1/map-projects/trihouse_test_01/publish",
        json={"expected_draft_revision": 1, "published_by": "W-OP-01"},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["map_revision"] == active_revision
    assert repeated.json()["published_at"] == published.json()["published_at"]
    assert list((tmp_path / "staging").glob("*")) == []

    edited_body = {
        **first_draft,
        "source_uuids": {
            key: value
            for key, value in first_draft["source_uuids"].items()
            if key != "slam_image"
        },
        "waypoints": first_draft["waypoints"]
        + [
            {
                "code": "manual-unsaved-from-active",
                "display_name": "Manual after active",
                "x": 9.0,
                "y": 9.0,
                "yaw": 0.0,
                "origin": "manual",
            }
        ],
    }
    edited = client.put(
        "/api/v1/map-projects/trihouse_test_01",
        json=edited_body,
        headers={"If-Match": "1"},
    )
    assert edited.status_code == 200, edited.text

    failed = client.post(
        "/api/v1/map-projects/trihouse_test_01/publish",
        json={"expected_draft_revision": 2, "published_by": "W-OP-01"},
    )
    assert failed.status_code == 422
    assert "SOURCE_SLAM_IMAGE_MISSING" in failed.json()["detail"]["error_codes"]
    assert repository.active_revision("trihouse_test_01") == active_revision
    assert repository.deployment_failure_events("trihouse_test_01") == []

    deleted = client.delete("/api/v1/map-projects/trihouse_test_01/draft")
    assert deleted.status_code == 204
    restored = client.get("/api/v1/map-projects/trihouse_test_01").json()
    assert restored["draft_revision"] == 1
    assert restored["source_uuids"] == first_draft["source_uuids"]
    assert all(
        value["code"] != "manual-unsaved-from-active"
        for value in restored["waypoints"]
    )
    opened = client.post(
        "/api/v1/map-projects", json={"map_name": "trihouse_test_01"}
    )
    assert opened.status_code == 200
    assert opened.json()["open_existing"] is True
    assert opened.json()["active_revision"] == active_revision
