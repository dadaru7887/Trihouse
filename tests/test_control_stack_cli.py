"""`scripts/control_stack` lifecycle 명령의 공개 계약."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "control_stack"
sys.path.insert(0, str(ROOT))


@pytest.fixture
def run_control_stack():
    def _run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["scripts/control_stack", *args],
            text=True,
            capture_output=True,
            check=False,
            cwd=ROOT,
        )

    return _run


def _module():
    import importlib.util
    from importlib.machinery import SourceFileLoader

    # `control_stack` intentionally has no .py suffix, so name the loader.
    spec = importlib.util.spec_from_file_location(
        "control_stack", SCRIPT, loader=SourceFileLoader("control_stack", str(SCRIPT))
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_lifecycle_script_is_executable() -> None:
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & 0o111, "control_stack must be executable"


def test_every_documented_subcommand_exists(run_control_stack) -> None:
    completed = run_control_stack("--help")

    assert completed.returncode == 0
    for command in ("up", "status", "logs", "doctor", "down", "ros"):
        assert command in completed.stdout


def test_simulation_doctor_lists_every_required_service(run_control_stack) -> None:
    completed = run_control_stack("doctor", "--mode", "simulation")
    checks = json.loads(completed.stdout)["checks"]

    assert set(checks) >= {
        "mysql", "fms_gateway", "control_tower", "mediamtx", "rmf_schedule",
        "gazebo", "nav2:PK_01", "nav2:PK_02", "omx:OMX_01", "omx:OMX_02",
        "control_ui",
    }


def test_doctor_reports_the_fake_model_contract_and_no_ai_stack(
    run_control_stack,
) -> None:
    report = json.loads(run_control_stack("doctor", "--mode", "simulation").stdout)

    assert report["mode"] == "simulation"
    assert report["act_contract"] == "deterministic_fake"
    # compose.ai_5080.yaml은 시뮬레이션에서 시작하지 않는다.
    assert report["ai_5080_started"] is False


def test_doctor_says_which_layer_owns_each_check(run_control_stack) -> None:
    report = json.loads(run_control_stack("doctor", "--mode", "simulation").stdout)

    assert set(report["layers"]) == {"docker", "host_ros"}
    assert "control_ui" in report["layers"]["docker"]
    assert "gazebo" in report["layers"]["host_ros"]
    assert set(report["layers"]["docker"]) | set(report["layers"]["host_ros"]) == set(
        report["checks"]
    )


def test_doctor_fails_while_a_required_service_is_absent(run_control_stack) -> None:
    """스택이 떠 있지 않으면 doctor는 성공을 보고하지 않는다."""
    completed = run_control_stack("doctor", "--mode", "simulation")
    report = json.loads(completed.stdout)

    if not report["healthy"]:
        assert completed.returncode == 1
        assert "absent" in set(report["checks"].values())


def test_one_compose_project_covers_the_whole_stack() -> None:
    module = _module()
    command = module.compose_command("ps")

    assert command[:4] == ["docker", "compose", "--project-name", "trihouse_p0"]
    assert command.count("--project-name") == 1
    files = [command[index + 1] for index, part in enumerate(command) if part == "-f"]
    assert [Path(path).name for path in files] == [
        "compose.yaml",
        "compose.control.yaml",
        "compose.edge_4060.yaml",
        "compose.simulation.yaml",
    ]


def test_the_ai_5080_stack_is_never_composed_in_simulation() -> None:
    module = _module()

    assert "compose.ai_5080.yaml" in module.FORBIDDEN_IN_SIMULATION
    assert not any(
        "ai_5080" in part for part in module.compose_command("up", mode="simulation")
    )


def test_docker_services_start_in_the_designed_dependency_order() -> None:
    order = _module().STARTUP_ORDER

    assert order == (
        "mysql", "fms_gateway", "mediamtx", "rmf_api", "rmf_dashboard",
        "control_ui",
    )
    # UI 는 Gateway 를 reverse proxy 하므로 Gateway 뒤에 와야 한다.
    assert order.index("mysql") < order.index("fms_gateway")
    assert order.index("fms_gateway") < order.index("control_ui")


def test_the_ros_layer_is_started_by_the_control_tower_bringup() -> None:
    """rclpy 가 필요한 구성요소는 Docker 가 아니라 호스트에서 돈다."""
    module = _module()

    assert module.ROS_BRINGUP.is_file()
    assert module.ROS_BRINGUP.stat().st_mode & 0o111
    assert module.ROS_BRINGUP.parts[-3:] == (
        "control_tower", "bringup", "p0_simulation_bringup.sh",
    )
    # 두 층이 겹치지 않아야 한다.
    assert set(module.DOCKER_CHECKS) & set(module.ROS_CHECKS) == set()
    assert set(module.DOCKER_CHECKS) | set(module.ROS_CHECKS) == set(
        module.REQUIRED_CHECKS
    )


def test_the_bringup_starts_every_ros_component_together() -> None:
    source = _module().ROS_BRINGUP.read_text(encoding="utf-8")

    assert "rmf_core.launch.py" in source
    assert "two_pinky_order_demo.launch.py" in source
    assert "trihouse_omx_adapter.simulator_node" in source
    assert "control_tower.rmf_adapter.rmf_gateway_worker_node" in source
    # 러너와 worker 는 짝이다. 러너가 빠지면 outbox 가 비어 worker 가 claim 할
    # 것이 없고, 주문은 `queued` 에서 멈춘다.
    assert "control_tower.task_manager.job_runner_node" in source
    # 실행기가 빠지면 주문이 첫 `pick` 에서 멈춘다.
    assert "control_tower.task_manager.executor_worker_node" in source
    for omx in ("OMX_01", "OMX_02"):
        assert omx in source


def test_gazebo_is_headless_unless_a_flag_asks_for_the_gui() -> None:
    parser = _module().build_parser()

    for command in ("up", "ros"):
        default = parser.parse_args([command, "--mode", "simulation"])
        assert default.gui is False
        assert default.rviz is False

        explicit = parser.parse_args(
            [command, "--mode", "simulation", "--gui", "--rviz"]
        )
        assert explicit.gui is True
        assert explicit.rviz is True


def test_up_defaults_to_the_canonical_p0_project() -> None:
    args = _module().build_parser().parse_args(["up"])

    assert args.project == "trihouse_test_01"
    assert args.mode == "simulation"


def test_an_unknown_subcommand_is_rejected(run_control_stack) -> None:
    completed = run_control_stack("teleport")

    assert completed.returncode != 0


def test_every_started_service_is_defined_in_the_compose_files() -> None:
    """control_stack이 없는 서비스를 올리려다 실패하는 회귀를 막는다."""
    yaml = pytest.importorskip("yaml")
    module = _module()

    defined: set[str] = set()
    for name in module.COMPOSE_FILES:
        document = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
        defined |= set((document or {}).get("services", {}))

    assert set(module.STARTUP_ORDER) <= defined


def test_the_simulation_stack_defines_no_ai_5080_service() -> None:
    yaml = pytest.importorskip("yaml")
    module = _module()

    for name in module.COMPOSE_FILES:
        document = yaml.safe_load((ROOT / name).read_text(encoding="utf-8")) or {}
        assert "ai_5080" not in str(document.get("services", {}))
