from pathlib import Path

from db.tools.import_control_system_project import build_project_request, sha256_file


def test_project1_building_is_converted_to_pixel_draft_and_meter_map_pose(tmp_path: Path):
    drawing = tmp_path / "floor.png"
    drawing.write_bytes(b"png")
    building = tmp_path / "project1.building.yaml"
    building.write_text(
        """
coordinate_system: reference_image
name: project1
reference_level_name: L1
levels:
  L1:
    drawing: {filename: floor.png}
    measurements:
      - [0, 1, {distance: [3, 2.0]}]
    vertices:
      - [0.0, 0.0, 0.0, m0]
      - [1000.0, 0.0, 0.0, m1]
      - [500.0, 100.0, 0.0, 충전1, {is_charger: [4, true]}]
      - [800.0, 100.0, 0.0, 대기1, {is_holding_point: [4, true]}]
    lanes:
      - [2, 3, {bidirectional: [4, true], graph_idx: [2, 0]}]
""",
        encoding="utf-8",
    )
    fleet = tmp_path / "fleet.yaml"
    fleet.write_text(
        """
robots:
  - id: PK_01
    name: Pinky 1
    kind: mobile
    model: PINKY-GZ
    gz_name: pinky_01
    zones: [ambient]
    home_charger: 충전1
    spawn_x: 1.0
    spawn_y: -0.2
""",
        encoding="utf-8",
    )

    request = build_project_request(building, fleet)

    charger = request["payload"]["waypoints"][0]
    assert charger["point"] == [500.0, 100.0]
    assert charger["mapPose"] == [1.0, -0.2, 0.0]
    assert charger["locationCode"] == "CHG-01"
    assert request["payload"]["waypoints"][1]["locationCode"] == "IN-WAIT-01"
    assert request["payload"]["version"] == 2
    assert request["payload"]["recommendedLanes"] == [
        [[500.0, 100.0], [800.0, 100.0]]
    ]
    assert request["fleet"]["fleet_name"] == "project1_pinky"
    assert request["robots"][0]["robot_id"] == "PK_01"


def test_hash_is_content_based(tmp_path: Path):
    artifact = tmp_path / "artifact"
    artifact.write_bytes(b"abc")
    assert sha256_file(artifact) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
