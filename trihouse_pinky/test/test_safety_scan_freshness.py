"""Safety must not reinterpret delayed LaserScan samples as current obstacles."""

import math

import pytest
import rclpy
from rclpy.duration import Duration
from rclpy.qos import QoSReliabilityPolicy
from sensor_msgs.msg import LaserScan

from trihouse_pinky_safety.safety_supervisor_node import SafetySupervisor


@pytest.fixture
def supervisor():
    if not rclpy.ok():
        rclpy.init()
    node = SafetySupervisor()
    yield node
    node.destroy_node()


def _scan(node: SafetySupervisor, distance_m: float, *, age_s: float) -> LaserScan:
    message = LaserScan()
    message.header.stamp = (node.get_clock().now() - Duration(seconds=age_s)).to_msg()
    # The vendor LiDAR is mounted at pi radians. A scan bearing of -pi therefore
    # becomes the robot's forward direction after the mounting correction.
    message.angle_min = -math.pi
    message.angle_increment = 1.0
    message.range_min = 0.05
    message.range_max = 12.0
    message.ranges = [distance_m]
    return message


def test_a_delayed_scan_cannot_overwrite_the_latest_safety_observation(
    supervisor: SafetySupervisor,
) -> None:
    """A reliable DDS backlog must not move an old wall to the robot's new pose."""
    supervisor._on_scan(_scan(supervisor, 1.0, age_s=0.0))
    current_nearby = supervisor.nearby_range
    current_received_at = supervisor.last_scan_at

    supervisor._on_scan(_scan(supervisor, 0.10, age_s=5.0))

    assert current_nearby is not None and current_nearby > 0.9
    assert supervisor.nearby_range == current_nearby
    assert supervisor.last_scan_at == current_received_at


def test_safety_scan_subscription_drops_backlog_instead_of_replaying_it(
    supervisor: SafetySupervisor,
) -> None:
    subscriptions = supervisor.get_subscriptions_info_by_topic("scan")

    assert len(subscriptions) == 1
    assert subscriptions[0].qos_profile.reliability == QoSReliabilityPolicy.BEST_EFFORT
