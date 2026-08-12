import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
import rclpy
from rmf_fleet_msgs.msg import FleetState, RobotState
from trihouse_interfaces.srv import EstimateTaskEnergy


@pytest.fixture(scope="module")
def ros_context():
    os.environ["ROS_LOG_DIR"] = tempfile.mkdtemp(prefix="trihouse-rmf-test-")
    rclpy.init()
    node = rclpy.create_node("test_office_energy_service")
    graph = str(Path(__file__).parent / "fixtures" / "test_graph.yaml")
    process = subprocess.Popen(
        [
            "ros2",
            "run",
            "trihouse_rmf_bridge",
            "trihouse_rmf_bridge_node",
            "--ros-args",
            "-p",
            f"nav_graph_file:={graph}",
        ]
    )
    publisher = node.create_publisher(FleetState, "/fleet_states", 10)
    client = node.create_client(
        EstimateTaskEnergy, "/trihouse/rmf/estimate_task_energy"
    )
    if not client.wait_for_service(timeout_sec=5.0):
        process.terminate()
        process.wait(timeout=3.0)
        pytest.fail("energy estimate service did not become available")
    yield node, publisher, client
    node.destroy_node()
    process.terminate()
    process.wait(timeout=3.0)
    rclpy.shutdown()


def publish_state(node, publisher, *, battery_percent=80.0):
    fleet = FleetState()
    fleet.name = "tinyRobot"
    robot = RobotState()
    robot.name = "tinyRobot1"
    robot.battery_percent = battery_percent
    robot.location.level_name = "L1"
    robot.location.x = 0.0
    robot.location.y = 0.0
    robot.location.yaw = 0.0
    fleet.robots = [robot]
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        publisher.publish(fleet)
        rclpy.spin_once(node, timeout_sec=0.05)


def call_service(node, client, waypoints):
    request = EstimateTaskEnergy.Request()
    request.robot_id = "tinyRobot1"
    request.task_id = "office-test"
    request.map_revision = "office"
    request.waypoint_ids = waypoints
    request.expected_loading_duration_s = 30.0
    request.expected_handover_duration_s = 30.0
    request.task_time_buffer_s = 15.0
    future = client.call_async(request)
    rclpy.spin_until_future_complete(node, future, timeout_sec=5.0)
    assert future.done()
    return future.result()


def test_service_estimates_pickup_to_dropoff(ros_context):
    node, publisher, client = ros_context
    publish_state(node, publisher)
    response = call_service(node, client, ["pickup", "dropoff"])
    assert response.success
    assert response.travel_duration_s > 0.0
    assert response.total_duration_s == pytest.approx(
        response.travel_duration_s + 75.0
    )
    assert 0.0 < response.change_in_charge < 0.8
    assert response.finish_state_of_charge == pytest.approx(
        0.8 - response.change_in_charge
    )
    assert response.reason_code == "OK"


def test_office_service_rejects_unknown_waypoint(ros_context):
    node, publisher, client = ros_context
    publish_state(node, publisher)
    response = call_service(node, client, ["not_a_waypoint"])
    assert not response.success
    assert response.reason_code == "RMF_WAYPOINT_NOT_FOUND"
