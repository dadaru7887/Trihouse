"""센서 신선도를 발행자와 같은 시계로 재는지 확인한다.

`use_sim_time` 이 켜지면 노드의 타이머는 sim 시간으로 뛴다. `sim_hardware` 는
`create_timer(1.0)` 으로 배터리를 내보내므로 1 **sim초** 마다 발행한다. 그런데
`status_node` 가 신선도를 `time.monotonic()`(벽시계)으로 재면 두 값이 다른 시계에
있게 된다.

P0 시뮬레이션이 실제로 그렇게 막혔다. 시뮬이 실시간보다 느리게 돌아
(측정값으로 배터리 간격이 6.24 벽시계초) 임계값 1.5초를 늘 넘겼고, 배터리는
영구히 `battery_stale` 이었다. 그러면 `telemetry_valid` 가 false 라서
`dispatchable` 도 false 이고, adapter 는 그 로봇을 RMF 에 내보내지 않는다.
주행과 위치추정이 정상이어도 주문은 배정되지 않는다.

ROS 시계를 쓰면 두 값이 같은 시계에 놓인다. 실기에서는 ROS 시계가 곧 벽시계이므로
동작이 달라지지 않는다.

두 시계는 자릿수로 구별된다. `monotonic()` 은 부팅 후 경과 시간이고 ROS system
clock 은 Unix epoch 이라 10억을 훌쩍 넘는다.
"""

import rclpy
import pytest

from sensor_msgs.msg import BatteryState, LaserScan
from nav_msgs.msg import Odometry

from trihouse_pinky_fleet.status_node import StatusNode


UNIX_EPOCH_SCALE = 1_000_000_000.0  # 2001년 이후의 어떤 순간도 이보다 크다.


@pytest.fixture
def node():
    if not rclpy.ok():
        rclpy.init()
    created = StatusNode()
    yield created
    created.destroy_node()


def test_sensor_arrival_times_are_recorded_on_the_ros_clock(node) -> None:
    """`monotonic()` 으로 기록하면 이 값은 부팅 후 경과 시간이 되어 훨씬 작다."""
    node._battery(BatteryState())
    node._scan(LaserScan())
    node._odom(Odometry())

    for label, recorded in (
        ("battery", node.last_battery),
        ("scan", node.last_scan),
        ("odom", node.last_odom),
    ):
        assert recorded > UNIX_EPOCH_SCALE, (
            f"{label} 의 수신 시각이 ROS 시계 위에 없다: {recorded}"
        )


def test_a_just_received_battery_message_is_not_stale(node) -> None:
    """같은 시계를 쓰면 방금 받은 값은 임계값과 무관하게 신선하다."""
    node._battery(BatteryState())

    message = node._build_message()

    assert "battery_stale" not in message.errors


def test_a_sensor_never_seen_is_stale(node) -> None:
    """초기값이 신선하다고 판정되면 아무 telemetry 없이도 배차 가능해진다."""
    message = node._build_message()

    assert "battery_stale" in message.errors
    assert "scan_stale" in message.errors
    assert "odom_stale" in message.errors
