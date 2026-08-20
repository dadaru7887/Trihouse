"""규칙 기반 후진 도킹을 `cmd_vel_dock` 으로 내보내는 노드.

원본 `narrow3_rule_based_docking.py` 는 `/cmd_vel` 을 직접 쐈고 충돌 감지가 없어
*"사람이 옆에서 지켜보다가 Ctrl+C"* 를 전제했다. 여기서는 `cmd_vel_dock` 으로
내보내 `safety_supervisor` 아래로 들어간다 — 사람이 지켜보던 자리를 안전 gate 가
대신한다. 그 gate 는 후진할 때 보호 필드를 뒤로 뒤집는다.

pose 는 TF `map -> base_footprint` 에서 읽는다. 구역 좌표가 지도 위의 값이므로
odom 으로는 안 된다 — 지도 원점 기준이어야 같은 자리를 가리킨다.
"""

import math

import rclpy
import tf2_ros
from geometry_msgs.msg import Twist
from rclpy.node import Node

from .sequence import DockCommand, DockSequence, SequenceLimits
from .zones import load_zones


def yaw_from_quaternion(q) -> float:
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


class DockNode(Node):
    def __init__(self) -> None:
        super().__init__("rule_based_dock")
        self.declare_parameter("zones_file", "")
        self.declare_parameter("base_frame", "base_footprint")
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("control_period_s", 0.05)
        self.declare_parameter("allow_unverified_zones", False)

        zones_file = str(self.get_parameter("zones_file").value)
        if not zones_file:
            raise RuntimeError("zones_file 파라미터가 필요합니다")
        self.zones = load_zones(zones_file)
        self.base_frame = str(self.get_parameter("base_frame").value)
        self.map_frame = str(self.get_parameter("map_frame").value)
        self.allow_unverified = bool(self.get_parameter("allow_unverified_zones").value)

        self.limits = SequenceLimits()
        self.sequence: DockSequence | None = None
        self.active_zone: str | None = None

        self.buffer = tf2_ros.Buffer()
        tf2_ros.TransformListener(self.buffer, self)
        self.cmd_pub = self.create_publisher(Twist, "cmd_vel_dock", 10)
        self.create_timer(float(self.get_parameter("control_period_s").value), self._tick)

    def start(self, zone_name: str, *, leaving: bool = False) -> bool:
        """구역 시퀀스를 시작한다. 구역 밖이거나 미검증이면 시작하지 않는다."""
        zone = self.zones.get(zone_name)
        if zone is None:
            self.get_logger().error(f"알 수 없는 구역: {zone_name}")
            return False
        if not zone["verified"] and not self.allow_unverified:
            # 검증 안 된 시퀀스로 후진하면 로봇이 벽에 들어간다. 명시적으로
            # 허용하지 않는 한 시작하지 않는다.
            self.get_logger().error(
                f"{zone_name} 은 실물 검증되지 않았습니다. "
                "allow_unverified_zones 로 명시해야 실행됩니다"
            )
            return False
        pose = self._pose()
        if pose is None:
            self.get_logger().error("map -> base_footprint TF 가 없습니다")
            return False
        steps = zone["exit"] if leaving else zone["entry"]
        sequence = DockSequence(steps, self.limits)
        x, y, yaw = pose
        if not sequence.begin(x=x, y=y, yaw=yaw, zone=zone["geometry"], now_s=self._now()):
            self.get_logger().warn(
                f"{zone_name} 구역 밖입니다 ({x:.3f}, {y:.3f}) — Nav2 로 더 접근하세요"
            )
            return False
        self.sequence, self.active_zone = sequence, zone_name
        self.get_logger().info(f"{zone_name} {'출고' if leaving else '입고'} 시퀀스 시작")
        return True

    def cancel(self) -> None:
        """즉시 멈춘다. 마지막 속도가 남으면 로봇이 계속 간다."""
        self.sequence = None
        self.active_zone = None
        self.cmd_pub.publish(Twist())

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds / 1e9

    def _pose(self) -> tuple[float, float, float] | None:
        try:
            transform = self.buffer.lookup_transform(
                self.map_frame, self.base_frame, rclpy.time.Time()
            )
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException,
                tf2_ros.ExtrapolationException):
            return None
        translation = transform.transform.translation
        return translation.x, translation.y, yaw_from_quaternion(transform.transform.rotation)

    def _tick(self) -> None:
        if self.sequence is None:
            return
        pose = self._pose()
        if pose is None:
            # pose 를 잃은 채 계속 밀면 어디로 가는지 모른 채 움직인다.
            self.get_logger().warn("TF 를 잃어 도킹을 멈춥니다")
            self.cancel()
            return
        x, y, yaw = pose
        command = self.sequence.advance(x=x, y=y, yaw=yaw, now_s=self._now())
        self._publish(command)
        if self.sequence.is_failed:
            self.get_logger().error(f"{self.active_zone} 도킹 실패: {self.sequence.failure}")
            self.cancel()
        elif self.sequence.is_complete:
            self.get_logger().info(f"{self.active_zone} 시퀀스 완료")
            self.cancel()

    def _publish(self, command: DockCommand) -> None:
        message = Twist()
        message.linear.x = command.linear_x
        message.angular.z = command.angular_z
        self.cmd_pub.publish(message)


def main() -> None:
    rclpy.init()
    node = DockNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.cancel()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
