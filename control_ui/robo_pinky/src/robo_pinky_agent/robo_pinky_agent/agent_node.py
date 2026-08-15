"""Pinky 1대를 관제센터에 물려 주는 온보드 에이전트.

Gazebo 안의 로봇이 실제 현장 로봇처럼 행동하게 만든다.

  · odom을 받아 창고 좌표(unit)로 환산해 관제에 상태 보고
  · 관제가 내려준 웨이포인트를 cmd_vel로 추종
  · 라이다 전방 감시 — 장애물이 가까우면 관제 명령보다 우선해 정지
  · 배터리 모델(주행량 · 구획 온도 반영, 충전 명령 시 회복)

관제와 끊기면 즉시 정지한다. 관제 없이 스스로 움직이지 않는다.
"""

from __future__ import annotations

import math

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String

from .control_link import ControlLink
from .frames import WarehouseFrame, compose, yaw_from_quaternion
from .waypoint_follower import WaypointFollower

# 배터리 모델 — robo_control FleetEngine의 소모율과 같은 축척.
DRAIN_IDLE = 0.012  # %/s
DRAIN_MOVING = 0.085  # %/s (정격 속도 주행 시)
CHARGE_RATE = 0.55  # %/s
COLD_FACTOR = {"ambient": 1.0, "chilled": 1.12, "frozen": 1.35}


class PinkyAgent(Node):
    def __init__(self) -> None:
        super().__init__("pinky_agent")

        p = self.declare_parameter
        p("robot_id", "PK-01")
        p("robot_name", "핑키 1호")
        p("robot_model", "PINKY-GZ")
        p("zones", ["ambient", "chilled", "frozen"])
        p("home_charger", "CHG-1")
        p("gz_name", "pinky_01")
        p("spawn_x", 50.0)  # 관제 좌표(unit)
        p("spawn_y", 22.0)
        p("spawn_heading", 0.0)  # 관제 좌표계 기준 radian
        p("control_host", "127.0.0.1")
        p("control_port", 8788)
        p("scale", 0.1)
        p("map_width", 120.0)
        p("map_height", 72.0)
        p("telemetry_hz", 5.0)
        p("control_hz", 20.0)
        p("obstacle_stop_distance", 0.15)
        p("goal_tolerance", 5.0)  # unit
        p("obstacle_fov_deg", 70.0)
        p("max_linear", 0.34)

        g = lambda k: self.get_parameter(k).value  # noqa: E731

        self.robot_id = g("robot_id")
        self.robot_name = g("robot_name")
        self.gz_name = g("gz_name")
        self.frame = WarehouseFrame(
            scale=float(g("scale")),
            width=float(g("map_width")),
            height=float(g("map_height")),
        )

        # 스폰 포즈를 월드 좌표로 미리 환산해 둔다. Gazebo odom은 스폰 지점을
        # 원점으로 하므로, 월드 포즈 = 스폰 포즈 ⊕ odom.
        sx, sy = self.frame.to_world(float(g("spawn_x")), float(g("spawn_y")))
        self._spawn = (sx, sy, self.frame.yaw_of(float(g("spawn_heading"))))
        self._pose = self._spawn
        self._have_odom = False

        self.follower = WaypointFollower(
            reach=self.frame.length_to_world(1.2),
            goal_reach=self.frame.length_to_world(float(g("goal_tolerance"))),
            max_linear=float(g("max_linear")),
        )

        self.battery = 100.0
        self.odometer = 0.0  # unit
        self.speed = 0.0  # m/s
        self.charging = False
        self.hold_reason: str | None = None
        self.speed_limit = float(g("max_linear"))  # m/s
        self.path_seq = -1
        self.blocked_note: str | None = None
        self._stalled = 0.0
        self._stall_reported = False
        self._front_range = math.inf
        self._stop_distance = float(g("obstacle_stop_distance"))
        self._fov = math.radians(float(g("obstacle_fov_deg"))) / 2.0

        # ── ROS 인터페이스
        sensor_qos = QoSProfile(
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=5,
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            durability=QoSDurabilityPolicy.VOLATILE,
        )
        self.cmd_pub = self.create_publisher(Twist, f"/{self.gz_name}/cmd_vel", 10)
        self.status_pub = self.create_publisher(String, f"/{self.gz_name}/link_status", 10)
        self.create_subscription(Odometry, f"/{self.gz_name}/odom", self._on_odom, sensor_qos)
        self.create_subscription(LaserScan, f"/{self.gz_name}/scan", self._on_scan, sensor_qos)

        # ── 관제 링크
        x_u, y_u = self.frame.to_units(sx, sy)
        self.link = ControlLink(
            host=g("control_host"),
            port=int(g("control_port")),
            hello={
                "id": self.robot_id,
                "name": self.robot_name,
                "model": g("robot_model"),
                "zones": list(g("zones")),
                "charger": g("home_charger"),
                "x": round(x_u, 3),
                "y": round(y_u, 3),
                "heading": float(g("spawn_heading")),
                "battery": self.battery,
            },
            on_message=self._on_control,
            on_state=self._on_link_state,
            logger=self.get_logger(),
        )
        self.link.start()

        self._last_control = self.get_clock().now()
        self.create_timer(1.0 / float(g("control_hz")), self._control_tick)
        self.create_timer(1.0 / float(g("telemetry_hz")), self._telemetry_tick)

        self.get_logger().info(
            f"{self.robot_id}({self.robot_name}) 기동 — gz `{self.gz_name}`, "
            f"스폰 ({g('spawn_x')}, {g('spawn_y')}) unit = ({sx:.2f}, {sy:.2f}) m"
        )

    # ────────────────────────────────────────────────────── 센서 입력

    def _on_odom(self, msg: Odometry) -> None:
        q = msg.pose.pose.orientation
        local = (
            msg.pose.pose.position.x,
            msg.pose.pose.position.y,
            yaw_from_quaternion(q.x, q.y, q.z, q.w),
        )
        self._pose = compose(self._spawn, local)
        self._have_odom = True
        v = msg.twist.twist.linear
        self.speed = math.hypot(v.x, v.y)

    def _on_scan(self, msg: LaserScan) -> None:
        """전방 부채꼴의 최소 거리. 관제가 모르는 장애물에 대한 최후 방어선."""
        best = math.inf
        angle = msg.angle_min
        for r in msg.ranges:
            if abs(angle) <= self._fov and msg.range_min < r < msg.range_max:
                best = min(best, r)
            angle += msg.angle_increment
        self._front_range = best

    # ────────────────────────────────────────────────────── 관제 입력

    def _on_link_state(self, connected: bool) -> None:
        if not connected:
            self.follower.clear()
            self.hold_reason = "관제 링크 단절 — 안전 정지"

    def _on_control(self, msg: dict) -> None:
        kind = msg.get("t")
        if kind == "welcome":
            self.frame = WarehouseFrame(
                scale=float(msg.get("scale", self.frame.scale)),
                width=float(msg.get("width", self.frame.width)),
                height=float(msg.get("height", self.frame.height)),
            )
            self.hold_reason = None
            self.get_logger().info("관제 등록 완료 — 명령 수신 시작")
        elif kind == "path":
            seq = int(msg.get("seq", self.path_seq + 1))
            pts = [
                self.frame.to_world(float(wp[0]), float(wp[1]))
                for wp in msg.get("waypoints", [])
            ]
            tol = msg.get("goalTol")
            self.follower.set_path(
                pts,
                goal_reach=None
                if tol is None
                else self.frame.length_to_world(float(tol)),
            )
            self.path_seq = seq
        elif kind == "hold":
            self.hold_reason = msg.get("reason", "관제 정지 명령") if msg.get("on") else None
        elif kind == "speed":
            self.speed_limit = self.frame.length_to_world(float(msg.get("limit", 3.4)))
        elif kind == "charge":
            self.charging = bool(msg.get("on"))
            if self.charging:
                self.follower.clear()

    # ────────────────────────────────────────────────────── 주기 동작

    def _control_tick(self) -> None:
        now = self.get_clock().now()
        dt = (now - self._last_control).nanoseconds / 1e9
        self._last_control = now
        if dt <= 0 or dt > 1.0:
            dt = 0.05

        v = w = 0.0
        self.blocked_note = None

        if not self.link.connected:
            self.blocked_note = "관제 링크 단절 — 안전 정지"
        elif self.hold_reason is not None:
            self.blocked_note = self.hold_reason
        elif self.charging:
            self.blocked_note = "충전 중"
        elif self._have_odom:
            v, w = self.follower.step(self._pose, self.speed_limit)
            # 전방 장애물은 **전진만** 막는다. 회전까지 막으면 슬롯 앞에
            # 정지한 로봇이 선반을 마주본 채 영영 돌아서지 못한다.
            if v > 0 and self._front_range < self._stop_distance:
                self.blocked_note = (
                    f"라이다 전방 {self._front_range:.2f} m 장애물 — 전진 정지"
                )
                v = 0.0

        cmd = Twist()
        cmd.linear.x = v
        cmd.angular.z = w
        self.cmd_pub.publish(cmd)

        self._update_battery(dt)
        self._report_stall(dt)

    def _report_stall(self, dt: float) -> None:
        """전방 장애물로 오래 멈춰 있으면 관제 이력에 한 번 올린다."""
        if self.blocked_note is None or "장애물" not in self.blocked_note:
            self._stalled = 0.0
            self._stall_reported = False
            return
        self._stalled += dt
        if self._stalled > 10.0 and not self._stall_reported:
            self._stall_reported = True
            self.link.send({
                "t": "log",
                "id": self.robot_id,
                "sev": "warning",
                "msg": f"전방 장애물로 {self._stalled:.0f}초째 정지 "
                       f"(라이다 {self._front_range:.2f} m). 경로 재계획이 필요합니다.",
            })

    def _update_battery(self, dt: float) -> None:
        x_u, _ = self.frame.to_units(self._pose[0], self._pose[1])
        cold = COLD_FACTOR[self.frame.zone_of(x_u)]
        if self.charging:
            self.battery = min(100.0, self.battery + CHARGE_RATE * dt)
            return
        ratio = min(1.0, self.speed / max(1e-3, self.follower.max_linear))
        rate = DRAIN_IDLE + DRAIN_MOVING * ratio
        self.battery = max(0.0, self.battery - rate * cold * dt)
        self.odometer += self.frame.length_to_units(self.speed * dt)

    def _telemetry_tick(self) -> None:
        x_u, y_u = self.frame.to_units(self._pose[0], self._pose[1])
        payload = {
            "t": "telemetry",
            "id": self.robot_id,
            "x": round(x_u, 3),
            "y": round(y_u, 3),
            "heading": round(self.frame.heading_of(self._pose[2]), 4),
            "battery": round(self.battery, 2),
            "speed": round(self.frame.length_to_units(self.speed), 3),
            "odom": round(self.odometer, 2),
            "wpLeft": self.follower.remaining,
            "charging": self.charging,
            "note": self.blocked_note,
            "seq": self.path_seq,
        }
        self.link.send(payload)

        status = String()
        status.data = (
            f"{self.robot_id} {'연결' if self.link.connected else '단절'} "
            f"| ({x_u:.1f}, {y_u:.1f}) unit | 배터리 {self.battery:.1f}% "
            f"| 잔여 WP {self.follower.remaining} | {self.blocked_note or '정상'}"
        )
        self.status_pub.publish(status)

    def destroy_node(self) -> bool:
        try:
            self.cmd_pub.publish(Twist())
            self.link.stop()
        finally:
            return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = PinkyAgent()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
