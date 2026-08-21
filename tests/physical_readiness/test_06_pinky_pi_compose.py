import re
import subprocess
from pathlib import Path

from .conftest import REPOSITORY_ROOT


OVERLAY_ROOT = REPOSITORY_ROOT / "pinky_pro_alpha"
APPLY_SCRIPT = REPOSITORY_ROOT / "scripts/apply_pinky_pro_alpha"


def test_overlay_applies_measured_navigation_configuration(tmp_path: Path):
    vendor_checkout = tmp_path / "pinky_pro"
    navigation = vendor_checkout / "pinky_navigation"
    navigation.mkdir(parents=True)
    (navigation / "package.xml").write_text("<package/>", encoding="utf-8")

    subprocess.run([str(APPLY_SCRIPT), str(vendor_checkout)], check=True)
    subprocess.run([str(APPLY_SCRIPT), str(vendor_checkout)], check=True)

    nav2 = (navigation / "params/nav2_params.yaml").read_text(encoding="utf-8")
    map_yaml = (navigation / "map/new_map_2.yaml").read_text(encoding="utf-8")
    assert nav2.count("'[[0.04, 0.06], [0.04, -0.06], [-0.16, -0.06], [-0.16, 0.06]]'") == 2
    assert nav2.count("resolution: 0.03") >= 3
    assert nav2.count("cost_scaling_factor: 10.0") == 2
    assert nav2.count("inflation_radius: 0.25") == 2
    assert re.search(r"xy_goal_tolerance:\s*0\.1\b", nav2)
    assert "image: new_map_2.pgm" in map_yaml
    assert (navigation / "map/new_map_2.pgm").is_file()
    assert (navigation / "params/amcl_params.yaml").is_file()


def test_overlay_records_reproducible_upstream_provenance():
    readme = (OVERLAY_ROOT / "README.md").read_text(encoding="utf-8")
    lidar_ref = (OVERLAY_ROOT / "vendor/sllidar_ros2.gitref").read_text(encoding="utf-8")

    assert "https://github.com/pinklab-art/pinky_pro.git" in readme
    assert "https://github.com/Slamtec/sllidar_ros2.git" in lidar_ref
    assert re.search(r"\b[0-9a-f]{40}\b", lidar_ref)


def test_overlay_never_tracks_generated_or_backup_artifacts():
    forbidden = {"build", "install", "log"}
    for path in OVERLAY_ROOT.rglob("*"):
        assert path.name not in forbidden
        assert not path.name.endswith(".bak")


def test_overlay_refuses_an_unrelated_destination(tmp_path: Path):
    result = subprocess.run(
        [str(APPLY_SCRIPT), str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "not a Pinky Pro checkout" in result.stderr
