"""SR_03 RobotStatus를 1초 heartbeat와 상태 변경 시 발행하는 ROS node."""

from time import monotonic

import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import BatteryState, LaserScan
from trihouse_interfaces.msg import BatteryPolicyState, CargoState, NavigationState, RobotStatus, SafetyState

from .status import StatusInputs, build_status


class StatusNode(Node):
    def __init__(self) -> None:
        super().__init__('status_node')
        self.declare_parameter('robot_id', 'PK-01'); self.declare_parameter('sensor_timeout_s', 1.5)
        self.robot_id = self.get_parameter('robot_id').value; self.timeout = float(self.get_parameter('sensor_timeout_s').value)
        self.last_scan = self.last_odom = self.last_battery = 0.0
        self.odom: Odometry | None = None; self.battery = 0.0; self.job_id = ''; self.step_id = ''; self.navigation_state = NavigationState.STATE_IDLE; self.task_progress = 0.0
        self.safety = SafetyState(); self.cargo = CargoState(); self.battery_policy = BatteryPolicyState()
        self.create_subscription(LaserScan, '/scan', self._scan, 10)
        self.create_subscription(Odometry, '/odom', self._odom, 10)
        self.create_subscription(BatteryState, '/trihouse/battery', self._battery, 10)
        self.create_subscription(SafetyState, '/trihouse/safety/state', self._safety, 10)
        self.create_subscription(CargoState, '/trihouse/cargo/state', self._cargo, 10)
        self.create_subscription(BatteryPolicyState, '/trihouse/battery/policy_state', lambda m: setattr(self, 'battery_policy', m), 10)
        self.create_subscription(NavigationState, '/trihouse/navigation/state', self._navigation, 10)
        self.publisher = self.create_publisher(RobotStatus, '/trihouse/status', 10); self.create_timer(1.0, self._publish)

    def _scan(self, _: LaserScan) -> None: self.last_scan = monotonic()
    def _odom(self, message: Odometry) -> None: self.odom = message; self.last_odom = monotonic()
    def _battery(self, message: BatteryState) -> None: self.battery = message.percentage * 100.0; self.last_battery = monotonic()
    def _safety(self, message: SafetyState) -> None: self.safety = message; self._publish()
    def _cargo(self, message: CargoState) -> None: self.cargo = message; self._publish()
    def _navigation(self, message: NavigationState) -> None:
        self.job_id = message.job_id; self.step_id = message.job_step_id
        self.navigation_state = message.state; self.task_progress = message.progress; self._publish()

    def _publish(self) -> None:
        now = monotonic(); summary = build_status(StatusInputs(self.robot_id, self.job_id, now-self.last_scan <= self.timeout, now-self.last_odom <= self.timeout, now-self.last_battery <= self.timeout))
        message = RobotStatus(); message.stamp = self.get_clock().now().to_msg(); message.robot_id = self.robot_id; message.current_job_id = self.job_id; message.current_job_step_id = self.step_id
        message.ready = summary.ready; message.errors = list(summary.errors); message.battery_percentage = self.battery; message.battery_policy = self.battery; message.cargo = self.cargo; message.safety = self.safety; message.navigation_state = self.navigation_state; message.task_progress = self.task_progress
        if self.odom is not None: message.pose.pose = self.odom.pose.pose; message.twist = self.odom.twist.twist; message.frame_id = self.odom.header.frame_id
        self.publisher.publish(message)


def main() -> None:
    rclpy.init(); node = StatusNode()
    try: rclpy.spin(node)
    finally: node.destroy_node(); rclpy.shutdown()
