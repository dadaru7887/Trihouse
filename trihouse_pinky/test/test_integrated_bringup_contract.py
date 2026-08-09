"""ROS 설치 없이 최상위 Gazebo·실기 launch의 공통 인자와 안전 연결을 점검한다."""
from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class IntegratedBringupContractTest(unittest.TestCase):
    """실행 전 launch source가 공통 계약을 드러내는지 확인한다."""

    def test_physical_and_sim_launch_expose_same_core_parameters(self) -> None:
        physical = (ROOT / "trihouse_pinky_bringup/launch/trihouse_pinky.launch.py").read_text()
        simulation = (ROOT / "trihouse_pinky_bringup/launch/trihouse_pinky_sim.launch.py").read_text()
        required = ("robot_id", "map_revision", "map", "control_host", "control_port", "use_sim_time", "vision_enabled", "docking_enabled", "omx_station_id")
        for name in required:
            self.assertIn(f"DeclareLaunchArgument('{name}'", physical)
            self.assertIn(f"DeclareLaunchArgument('{name}'", simulation)

    def test_combined_gazebo_demo_starts_pinky_omx_and_mock_sensors(self) -> None:
        launch = (ROOT / "trihouse_pinky_bringup/launch/trihouse_gazebo_demo.launch.py").read_text()
        self.assertIn("trihouse_pinky_sim.launch.py", launch)
        self.assertIn("gazebo_omx_adapter", launch)
        self.assertIn("sim_hardware", launch)
        self.assertIn("/cmd_vel_nav", launch)

