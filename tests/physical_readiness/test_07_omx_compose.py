from pathlib import Path

import yaml

from .conftest import REPOSITORY_ROOT


COMPOSE = REPOSITORY_ROOT / "compose.roles/omx.yaml"


def test_omx_role_runs_ros_bridge_and_lerobot_worker_in_separate_containers() -> None:
    document = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    services = document["services"]

    assert set(services) == {"omx_bridge", "lerobot_worker"}
    assert services["omx_bridge"]["network_mode"] == "host"
    assert "network_mode" not in services["lerobot_worker"]
    assert services["omx_bridge"]["environment"]["ROS_DOMAIN_ID"] == "12"
    assert services["lerobot_worker"]["environment"]["DEVICE_ID"] == "${DEVICE_ID:?DEVICE_ID is required}"


def test_worker_gets_only_declared_devices_and_read_only_host_assets() -> None:
    worker = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"][
        "lerobot_worker"
    ]

    assert worker.get("privileged") is not True
    assert len(worker["devices"]) == 3
    assert all("${OMX_" in device for device in worker["devices"])
    assert any("${OMX_CALIBRATION_DIR" in volume and volume.endswith(":ro") for volume in worker["volumes"])
    assert any("${OMX_MODEL_CACHE_DIR" in volume and volume.endswith(":ro") for volume in worker["volumes"])
    assert "healthcheck" in worker
    assert "healthcheck" in yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["omx_bridge"]


def test_hardware_build_context_never_copies_simulation_modules() -> None:
    bridge = (REPOSITORY_ROOT / "docker/ros/Dockerfile.omx_bridge").read_text(
        encoding="utf-8"
    )
    worker = (REPOSITORY_ROOT / "docker/omx/Dockerfile.lerobot").read_text(
        encoding="utf-8"
    )

    assert "tests/simulation" not in bridge + worker
    assert "COPY ." not in bridge + worker
    assert "python3.12" in bridge
    assert "python3.10" in worker


def test_env_example_fixes_domain_and_documents_every_omx_host_value() -> None:
    env = (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "ROS_DOMAIN_ID=12" in env
    for name in (
        "DEVICE_ID",
        "ROS_NAMESPACE",
        "OMX_TEMPERATURE_ZONES",
        "OMX_SERIAL_DEVICE",
        "OMX_FRONT_CAMERA",
        "OMX_WRIST_CAMERA",
        "OMX_CALIBRATION_ID",
        "OMX_CALIBRATION_DIR",
        "OMX_MODEL_CACHE_DIR",
    ):
        assert f"{name}=" in env


def test_omx_role_has_one_command_lifecycle_and_doctor() -> None:
    script = REPOSITORY_ROOT / "scripts/omx_stack"

    assert script.is_file()
    assert script.stat().st_mode & 0o111
    source = script.read_text(encoding="utf-8")
    for command in ("up", "down", "logs", "doctor"):
        assert command in source
    for check in ("ROS_DOMAIN_ID", "OMX_SERIAL_DEVICE", "OMX_FRONT_CAMERA", "OMX_WRIST_CAMERA"):
        assert check in source
