"""Gazebo에서만 쓰는 Pinky 하드웨어 입력의 명시적 대체 publisher."""

from dataclasses import dataclass
from time import monotonic

import rclpy
from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)
from sensor_msgs.msg import BatteryState, Range


POWER_SUPPLY_STATUS_CHARGING = 1
POWER_SUPPLY_STATUS_DISCHARGING = 2
POWER_SUPPLY_STATUS_FULL = 4


@dataclass(frozen=True)
class SimulatedBattery:
    percentage: float
    power_supply_status: int


def advance_battery(
    percentage: float,
    *,
    charging: bool,
    elapsed_s: float,
    charge_percent_per_second: float,
    discharge_percent_per_second: float = 0.0,
) -> SimulatedBattery:
    """경과 시간과 simulation-only 충·방전률로 상태를 결정한다."""

    if (
        elapsed_s < 0
        or charge_percent_per_second < 0
        or discharge_percent_per_second < 0
    ):
        raise ValueError(
            "elapsed time and charge/discharge rates must be non-negative"
        )
    level = min(1.0, max(0.0, percentage))
    if charging:
        level = min(1.0, level + charge_percent_per_second / 100.0 * elapsed_s)
    else:
        level = max(
            0.0,
            level - discharge_percent_per_second / 100.0 * elapsed_s,
        )
    if level >= 1.0:
        status = POWER_SUPPLY_STATUS_FULL
    elif charging:
        status = POWER_SUPPLY_STATUS_CHARGING
    else:
        status = POWER_SUPPLY_STATUS_DISCHARGING
    return SimulatedBattery(level, status)


class SimHardware(Node):
    def __init__(self) -> None:
        super().__init__('sim_hardware')
        self.declare_parameter('front_distance_m', 3.0)
        self.declare_parameter('battery_percentage', 1.0)
        self.declare_parameter('charging', False)
        self.declare_parameter('charge_percent_per_second', 1.0)
        self.declare_parameter('discharge_percent_per_second', 0.0)
        self._battery_percentage = float(self.get_parameter('battery_percentage').value)
        self._last_update_at = monotonic()

        qos = QoSProfile(
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=5,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.VOLATILE,
        )
        self.range_pub = self.create_publisher(Range, '/trihouse/proximity/front', 10)
        self.battery_pub = self.create_publisher(BatteryState, '/trihouse/battery', qos)
        self.create_timer(1.0, self._publish)

    def _publish(self) -> None:
        now = monotonic()
        elapsed_s = now - self._last_update_at
        self._last_update_at = now
        simulated = advance_battery(
            self._battery_percentage,
            charging=bool(self.get_parameter('charging').value),
            elapsed_s=elapsed_s,
            charge_percent_per_second=float(
                self.get_parameter('charge_percent_per_second').value
            ),
            discharge_percent_per_second=float(
                self.get_parameter('discharge_percent_per_second').value
            ),
        )
        self._battery_percentage = simulated.percentage

        distance = float(self.get_parameter('front_distance_m').value)
        proximity = Range()
        proximity.header.stamp = self.get_clock().now().to_msg()
        proximity.header.frame_id = 'ultrasonic_link'
        proximity.radiation_type = Range.ULTRASOUND
        proximity.min_range = 0.02
        proximity.max_range = 3.0
        proximity.range = distance

        battery = BatteryState()
        battery.header.stamp = proximity.header.stamp
        battery.percentage = simulated.percentage
        battery.present = True
        battery.power_supply_status = simulated.power_supply_status
        self.range_pub.publish(proximity)
        self.battery_pub.publish(battery)


def main() -> None:
    rclpy.init()
    node = SimHardware()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
