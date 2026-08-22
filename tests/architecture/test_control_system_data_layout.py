from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
IMPORT_DIR = ROOT / "data/map_authoring/import"
PINKY_MAP_DIR = ROOT / "pinky_pro_alpha/pinky_navigation/map"


def test_legacy_control_ui_directory_is_removed() -> None:
    assert not (ROOT / "control_ui").exists()


def test_map_authoring_data_is_independent_from_the_web_ui() -> None:
    assert (IMPORT_DIR / "trihouse_test_01_physical_features.jsonl").is_file()
    assert (
        IMPORT_DIR / "trihouse_test_01_physical_features.new_map_2.jsonl"
    ).is_file()


def test_pinky_alpha_owns_the_new_map_2_occupancy_map() -> None:
    assert (PINKY_MAP_DIR / "new_map_2.yaml").is_file()
    assert (PINKY_MAP_DIR / "new_map_2.pgm").is_file()


def test_compose_uses_only_the_control_system_web_dashboard() -> None:
    control_compose = (ROOT / "compose.control.yaml").read_text(encoding="utf-8")
    simulation_compose = (ROOT / "compose.simulation.yaml").read_text(
        encoding="utf-8"
    )

    assert "\n  control_ui:" not in control_compose
    assert "control_ui/rmf_control_ui/Dockerfile" not in control_compose
    assert "control_system/openrmf/docker/rmf-web-dashboard" in simulation_compose


def test_runtime_entrypoints_do_not_reference_legacy_control_ui_data() -> None:
    for relative_path in (
        "scripts/p0_publish_map.py",
        "scripts/p0_reset.sh",
        "scripts/p0_up.sh",
        "control_tower/bringup/p0_simulation_bringup.sh",
    ):
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "control_ui/rmf_control_ui/data" not in content, relative_path


def test_bringup_uses_the_selected_map_as_the_gateway_project() -> None:
    up = (ROOT / "scripts/p0_up.sh").read_text(encoding="utf-8")
    bringup = (
        ROOT / "control_tower/bringup/p0_simulation_bringup.sh"
    ).read_text(encoding="utf-8")

    assert 'TRIHOUSE_PROJECT="$MAP_NAME"' in up
    assert 'TRIHOUSE_PROJECT:=new_map_2' in bringup
