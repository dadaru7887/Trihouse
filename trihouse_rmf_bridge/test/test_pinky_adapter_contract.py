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
    """map 좌표가 확실할 때만 `frame_id` 를 `map` 으로 적어야 한다.

    출처는 `amcl_pose` 토픽에서 `map -> base` 변환으로 바뀌었다. AMCL 은
    `amcl_pose` 를 이벤트로만 내기 때문이다 — 첫 스캔에 한 번, 그 뒤로는 로봇이
    `update_min_d` 만큼 움직여 재표집될 때만이다. 그래서 그 토픽의 신선도는
    위치추정이 살아 있는지가 아니라 로봇이 움직였는지를 잰다. 충전기에 세워 둔
    로봇은 그 때문에 영영 못 움직였다: pose 가 stale 로 떨어져 frame_id 가 odom 이
    되고, adapter 가 로봇을 거부하고, job 이 배정되지 않고, 움직이지 않으니
    `amcl_pose` 도 다시 오지 않는다.

    변환은 AMCL 이 지속적으로 방송하므로 그 신선도는 우리가 실제로 알고 싶은 것을
    잰다. 여기서 지키는 것은 출처가 아니라 규칙이다 — 확실할 때만 `map` 이고,
    아니면 odom 프레임 이름을 그대로 남겨 adapter 가 거절할 수 있게 한다.
    """
    adapter_source = _source()
    status_source = PINKY_STATUS_NODE.read_text(encoding="utf-8")

    assert 'message.frame_id != "map"' in adapter_source

    # map pose 의 출처는 TF 이고, 낡은 변환은 없는 것으로 취급한다.
    assert "lookup_transform" in status_source
    assert "if age_s > self.timeout:" in status_source

    # 변환이 없으면 map 을 적지 않고 odom 프레임 이름을 그대로 남긴다.
    assert "message.frame_id = self.map_frame" in status_source
    assert "message.frame_id = self.odom.header.frame_id" in status_source


def test_robot_id_is_sanitized_before_use_as_ros_node_name() -> None:
    source = _source()

    assert 'robot_name.replace("-", "_")' in source


def test_navigate_checks_the_transport_server_before_touching_the_ledger() -> None:
    """실행할 수 없으면 원장을 건드리지 않는다.

    `claim` 은 Gateway 원장에 명령 행과 시도 행을 남기는 부수효과다. 그것을
    먼저 하고 나중에 실행 가능 여부를 보면, 실패해도 흔적은 남는다. 2026-08-19 에
    action server 가 없던 동안 그 흔적이 step 하나에 463행까지 쌓였다.

    멱등키 재설계로 행이 하나로 묶이지만, 순서 자체가 틀린 것은 그대로다.
    검증이 부수효과보다 앞서야 한다.
    """
    source = _source()
    navigate = source.split("def _navigate(")[1].split("\n    def ")[0]

    server_check = navigate.index("server_is_ready")
    claim_call = navigate.index("self._command_claims.claim(")

    assert server_check < claim_call, (
        "claim 이 server_is_ready 보다 먼저다 — 실행 못 할 명령을 원장에 남긴다"
    )
