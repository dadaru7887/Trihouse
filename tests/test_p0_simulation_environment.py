"""P0 simulation must not depend on a transient host LAN address."""

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_p0_ros_domain_uses_the_approved_value_everywhere() -> None:
    """Host ROS and Compose must stay in the same approved DDS domain."""
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    p0_up = (ROOT / "scripts/p0_up.sh").read_text(encoding="utf-8")
    bringup = (
        ROOT / "control_tower/bringup/p0_simulation_bringup.sh"
    ).read_text(encoding="utf-8")
    compose = (ROOT / "compose.simulation.yaml").read_text(encoding="utf-8")

    assert "ROS_DOMAIN_ID=12" in env_example
    assert 'ROS_DOMAIN_ID="$ROS_DOMAIN_ID"' in p0_up
    assert ': "${ROS_DOMAIN_ID:=12}"' in bringup
    assert "ROS_DOMAIN_ID: ${ROS_DOMAIN_ID:-12}" in compose


def test_p0_simulation_gateway_binds_to_loopback_by_default() -> None:
    environment = dict(os.environ)
    environment["FMS_TCP_BIND"] = "192.0.2.99"
    environment["FMS_API_HOST"] = "192.0.2.99"
    environment["EDGE_BIND_ADDRESS"] = "192.0.2.99"

    completed = subprocess.run(
        [
            "bash",
            "-c",
            "source scripts/lib/p0_environment.sh; "
            "configure_p0_simulation_environment; "
            "printf '%s|%s|%s' \"$FMS_TCP_BIND\" \"$FMS_API_HOST\" \"$EDGE_BIND_ADDRESS\"",
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == "127.0.0.1|127.0.0.1|127.0.0.1"


def test_p0_simulation_gateway_accepts_an_explicit_bind_override() -> None:
    environment = dict(os.environ)
    environment["P0_FMS_TCP_BIND"] = "192.168.0.9"

    completed = subprocess.run(
        [
            "bash",
            "-c",
            "source scripts/lib/p0_environment.sh; "
            "configure_p0_simulation_environment; printf '%s' \"$FMS_TCP_BIND\"",
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == "192.168.0.9"


def test_p0_simulation_domain_override_does_not_edit_the_hardware_env(tmp_path) -> None:
    """A clean simulation may use domain 0 while the tracked hardware value stays 12."""
    env_file = tmp_path / ".env"
    env_file.write_text("ROS_DOMAIN_ID=12\n", encoding="utf-8")
    environment = dict(os.environ)
    environment["P0_ROS_DOMAIN_ID"] = "0"

    completed = subprocess.run(
        [
            "bash",
            "-c",
            "source scripts/lib/p0_environment.sh; "
            "configure_p0_ros_domain \"$TEST_ENV_FILE\"; "
            "printf '%s' \"$ROS_DOMAIN_ID\"",
        ],
        cwd=ROOT,
        env={**environment, "TEST_ENV_FILE": str(env_file)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == "0"
    assert env_file.read_text(encoding="utf-8") == "ROS_DOMAIN_ID=12\n"
