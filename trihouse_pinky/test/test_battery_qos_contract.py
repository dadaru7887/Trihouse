"""배터리 관측 노드의 ROS 토픽과 QoS 계약 테스트."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE = (
    ROOT
    / "trihouse_pinky_fleet"
    / "trihouse_pinky_fleet"
    / "battery_condition_node.py"
)


def test_battery_condition_node_uses_approved_topics_timeouts_and_qos():
    source = NODE.read_text(encoding="utf-8")

    assert "'/trihouse/battery'" in source
    assert "'/trihouse/battery/condition'" in source
    assert "'startup_timeout_s', 5.0" in source
    assert "'telemetry_timeout_s', 3.0" in source
    assert "QoSHistoryPolicy.KEEP_LAST" in source
    assert "QoSReliabilityPolicy.RELIABLE" in source
    assert "QoSDurabilityPolicy.VOLATILE" in source
    assert "depth=5" in source


def test_battery_condition_node_is_registered_in_package_and_launches():
    setup_source = (ROOT / "trihouse_pinky_fleet" / "setup.py").read_text(
        encoding="utf-8"
    )
    real_launch = (ROOT / "trihouse_pinky_bringup" / "launch" / "trihouse_pinky.launch.py").read_text(encoding="utf-8")
    sim_launch = (ROOT / "trihouse_pinky_bringup" / "launch" / "trihouse_pinky_sim.launch.py").read_text(encoding="utf-8")

    assert "battery_condition = trihouse_pinky_fleet.battery_condition_node:main" in setup_source
    assert "executable='battery_condition'" in real_launch
    assert "executable='battery_condition'" in sim_launch


def test_simulator_raw_battery_uses_same_reliable_volatile_qos():
    source = (
        ROOT
        / "trihouse_pinky_bringup"
        / "trihouse_pinky_bringup"
        / "sim_hardware_node.py"
    ).read_text(encoding="utf-8")
    assert "QoSHistoryPolicy.KEEP_LAST" in source
    assert "QoSReliabilityPolicy.RELIABLE" in source
    assert "QoSDurabilityPolicy.VOLATILE" in source
    assert "depth=5" in source
