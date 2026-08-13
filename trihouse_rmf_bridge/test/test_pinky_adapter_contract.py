"""Pinky EasyFullControl adapter의 핵심 연결 계약을 고정한다."""

from pathlib import Path


NODE = (
    Path(__file__).resolve().parents[1]
    / "trihouse_rmf_bridge"
    / "pinky_adapter_node.py"
)
PINKY_STATUS_NODE = (
    Path(__file__).resolve().parents[2]
    / "trihouse_pinky"
    / "trihouse_pinky_fleet"
    / "trihouse_pinky_fleet"
    / "status_node.py"
)


def _source() -> str:
    return NODE.read_text(encoding="utf-8")


def test_adapter_uses_pinky_status_and_transport_action() -> None:
    source = _source()

    assert "RobotStatus" in source
    assert "ExecuteTransport" in source
    assert "MODE_RMF_NAVIGATION" in source
    assert "create_subscription" in source
    assert "ActionClient" in source


def test_adapter_updates_rmf_pose_soc_and_lifecycle() -> None:
    source = _source()

    assert "rmf_easy.RobotState" in source
    assert ".rmf_position" in source
    assert ".rmf_soc" in source
    assert "self._registry.stop" in source
    assert "cancel_goal_async" in source
    assert "self._registry.finish" in source
    assert "execution.finished()" in source


def test_invalid_telemetry_controls_rmf_commission() -> None:
    source = _source()

    assert "unstable_decommission" in source
    assert "unstable_recommission" in source
    assert "override_status" in source
    assert "message.dispatchable" in source


def test_rmf_navigation_claims_fms_context_without_synthetic_job_ids() -> None:
    source = _source()

    assert "self._command_claims.claim(" in source
    assert "goal.task_context" in source
    assert 'f"rmf:{command_id}"' not in source
    assert 'f"rmf-nav:{command_id}"' not in source
    assert 'parser.add_argument("--map-revision", required=True)' in source


def test_help_is_parsed_before_ros_logging_initialization() -> None:
    source = _source()
    main_source = source[source.index("def main(") :]

    assert main_source.index("args = _parse_args(argv)") < main_source.index(
        "rclpy.init(args=argv)"
    )


def test_rmf_never_treats_odom_pose_as_map_pose() -> None:
    adapter_source = _source()
    status_source = PINKY_STATUS_NODE.read_text(encoding="utf-8")

    assert 'message.frame_id != "map"' in adapter_source
    assert "PoseWithCovarianceStamped" in status_source
    assert "'/amcl_pose'" in status_source
    assert "now - self.last_map_pose <= self.timeout" in status_source


def test_robot_id_is_sanitized_before_use_as_ros_node_name() -> None:
    source = _source()

    assert 'robot_name.replace("-", "_")' in source
