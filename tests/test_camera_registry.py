"""카메라 등록 정본(`config/cameras.yaml`)과 그 적재 규칙을 검증한다.

정본은 이 YAML 한 곳뿐이다. `map_revisions.manifest.cameras` 는 발행 시점의
감사용 사본이고, `operations_feed` 는 이 파일을 읽을 뿐 카메라 값을 직접
들고 있지 않는다.
"""

from pathlib import Path

import pytest

from control_tower.gateway.camera_registry import (
    CameraRecord,
    CameraRegistryError,
    load_camera_registry,
    parse_camera_registry,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "cameras.yaml"


def _document(**overrides) -> dict:
    camera = {
        "camera_id": "CAM-PK-01",
        "role": "pinky_travel",
        "attached_to": "PK_01",
        "simulation_path": "fixtures/pinky_01_travel",
        "map_pose": None,
    }
    camera.update(overrides)
    return {"cameras": [camera]}


def test_registry_file_registers_the_six_known_cameras() -> None:
    records = load_camera_registry(REGISTRY)

    assert [record.camera_id for record in records] == [
        "CAM-PK-01",
        "CAM-PK-02",
        "CAM-OMX-01-WRIST",
        "CAM-OMX-02-WRIST",
        "CAM-FIXED-01",
        "CAM-FIXED-02",
    ]


def test_registry_file_invents_no_map_pose_before_calibration() -> None:
    # P1 캘리브레이션 전까지 좌표를 지어내지 않는다.
    assert all(record.map_pose is None for record in load_camera_registry(REGISTRY))


def test_stream_path_is_derived_from_role_prefix_and_camera_id() -> None:
    paths = {record.camera_id: record.stream_path for record in load_camera_registry(REGISTRY)}

    assert paths["CAM-PK-01"] == "pinky/CAM-PK-01"
    assert paths["CAM-OMX-01-WRIST"] == "omx/CAM-OMX-01-WRIST"
    assert paths["CAM-FIXED-01"] == "fixed/CAM-FIXED-01"


def test_stream_path_last_segment_always_equals_camera_id() -> None:
    # Pinky 송신부의 검증 규칙(`경로 마지막 == camera_id`)과 대칭을 이룬다.
    for record in load_camera_registry(REGISTRY):
        assert record.stream_path.rsplit("/", 1)[-1] == record.camera_id


def test_duplicate_camera_id_is_rejected() -> None:
    document = {"cameras": [_document()["cameras"][0], _document()["cameras"][0]]}

    with pytest.raises(CameraRegistryError, match="duplicate"):
        parse_camera_registry(document)


def test_unsafe_camera_id_is_rejected() -> None:
    with pytest.raises(CameraRegistryError, match="camera_id"):
        parse_camera_registry(_document(camera_id="CAM/PK-01"))


def test_unknown_role_is_rejected() -> None:
    with pytest.raises(CameraRegistryError, match="role"):
        parse_camera_registry(_document(role="ceiling_drone"))


def test_robot_mounted_camera_may_not_carry_a_map_pose() -> None:
    # 로봇에 붙어 다니는 카메라는 고정된 맵 좌표를 가질 수 없다.
    with pytest.raises(CameraRegistryError, match="map_pose"):
        parse_camera_registry(_document(map_pose=[1.0, 2.0, 0.0]))


def test_fixed_camera_accepts_a_measured_map_pose() -> None:
    records = parse_camera_registry(
        _document(
            camera_id="CAM-FIXED-01",
            role="warehouse_fixed",
            attached_to=None,
            map_pose=[1.0, 2.0, 0.0],
        )
    )

    assert records[0].map_pose == (1.0, 2.0, 0.0)


def test_empty_registry_is_rejected() -> None:
    with pytest.raises(CameraRegistryError, match="cameras"):
        parse_camera_registry({"cameras": []})


def test_record_is_immutable() -> None:
    record = load_camera_registry(REGISTRY)[0]

    with pytest.raises(Exception):
        record.camera_id = "CAM-PK-99"  # type: ignore[misc]


def test_camera_record_type_is_exported() -> None:
    assert issubclass(CameraRecord, object)


def test_every_camera_carries_a_simulation_path() -> None:
    # P0 는 실물 카메라를 연결하지 않으므로 fixture 스트림을 쓴다. 이름 규칙이
    # 카메라마다 달라 파생할 수 없으므로 정본에 적는다.
    paths = {record.camera_id: record.simulation_path for record in load_camera_registry(REGISTRY)}

    assert paths["CAM-PK-01"] == "fixtures/pinky_01_travel"
    assert paths["CAM-OMX-01-WRIST"] == "fixtures/omx_01_wrist"
    assert paths["CAM-FIXED-01"] == "fixtures/warehouse_fixed_01"


def test_simulation_paths_stay_under_the_fixtures_prefix() -> None:
    # 실스트림(`pinky/`)과 fixture(`fixtures/`)는 경로만으로 구분되어야 한다.
    for record in load_camera_registry(REGISTRY):
        assert record.simulation_path.startswith("fixtures/")
        assert not record.stream_path.startswith("fixtures/")


def test_simulation_path_outside_the_fixtures_prefix_is_rejected() -> None:
    with pytest.raises(CameraRegistryError, match="simulation_path"):
        parse_camera_registry(_document(simulation_path="pinky/CAM-PK-01"))


def test_missing_simulation_path_is_rejected() -> None:
    document = _document()
    del document["cameras"][0]["simulation_path"]

    with pytest.raises(CameraRegistryError, match="simulation_path"):
        parse_camera_registry(document)
