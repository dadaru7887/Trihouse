"""구획 적재 스테이션의 OMX 로봇팔 에이전트.

관제센터에 **적재 장비**로 등록하고, 적재 지시를 받으면 화물을 집어 로봇
데크에 올린 뒤 완료를 보고한다.

  관제 → 팔 : {"t":"load","robot":"PK-01","task":"TSK-0042",
               "item":"우유 3개","qty":3,"x":65.0,"y":38.0}
  팔  → 관제: {"t":"loaded","id":"OMX-C","task":"TSK-0042"}

로봇의 실제 위치(관제 좌표)를 함께 받으므로, 팔은 로봇이 정확히 어디에 섰든
그쪽으로 역기구학을 풀어 내려놓는다. 팔이 닿지 않는 자리면 사거리 안으로
잘라 접근하고, 그래도 불가능하면 실패를 보고한다.

화물의 물리적 파지는 모사하지 않는다(그리퍼 개폐와 궤적은 실제로 움직이지만
화물 객체가 손에 붙지는 않는다). 화물 인수인계는 관제 원장에서 관리한다.
"""

from __future__ import annotations

import math

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64, String

from . import arm_kinematics as ik
from .control_link import ControlLink
from .frames import WarehouseFrame

# 팔 사거리(m). 로봇이 이 범위 밖에 서면 잘라서 접근한다.
REACH_MIN, REACH_MAX = 0.15, 0.28

# 화물을 내려놓을 때 끝단이 향하는 각도(rad). 음수 = 위에서 아래로.
PLACE_PITCH = -1.2


class PinkyArmAgent(Node):
    def __init__(self) -> None:
        super().__init__("pinky_arm_agent")

        p = self.declare_parameter
        p("arm_id", "OMX-A")
        p("arm_model", "OMX-LOADER")
        p("gz_name", "omx_a")
        p("station", "WS-1")
        p("zone", "ambient")
        # 팔 받침대의 설치 위치(관제 좌표 unit)와 방위(관제 좌표계 rad)
        p("mount_x", 35.0)
        p("mount_y", 35.5)
        p("mount_heading", 1.5708)
        p("pedestal_height", 0.18)
        # 로봇 적재 데크 높이(m, 월드 기준)
        p("deck_height", 0.076)
        p("control_host", "127.0.0.1")
        p("control_port", 8788)
        p("scale", 0.1)
        p("map_width", 120.0)
        p("map_height", 72.0)

        g = lambda k: self.get_parameter(k).value  # noqa: E731

        self.arm_id = g("arm_id")
        self.gz_name = g("gz_name")
        self.station = g("station")
        self.pedestal_height = float(g("pedestal_height"))
        self.deck_height = float(g("deck_height"))
        self.frame = WarehouseFrame(
            scale=float(g("scale")),
            width=float(g("map_width")),
            height=float(g("map_height")),
        )

        mx, my = self.frame.to_world(float(g("mount_x")), float(g("mount_y")))
        self._mount = (mx, my)
        self._mount_yaw = self.frame.yaw_of(float(g("mount_heading")))

        self.joints = [
            "joint1",
            "joint2",
            "joint3",
            "joint4",
            "gripper_left_joint",
            "gripper_right_joint",
        ]

        self.status = "idle"
        self.current_task: str | None = None
        self.loads_done = 0

        # 실행 중인 궤적: (목표 6축, 구간 소요 시간) 목록을 20 Hz로 보간한다.
        self._segments: list[tuple[list[float], float]] = []
        self._seg_elapsed = 0.0
        self._from = list(self._home_pose()) + [ik.GRIPPER_OPEN] * 2
        self._target = list(self._from)

        self.cmd_pubs = {
            j: self.create_publisher(Float64, f"/{self.gz_name}/{j}_cmd", 10)
            for j in self.joints
        }
        self.status_pub = self.create_publisher(
            String, f"/{self.gz_name}/arm_status", 10
        )

        self.link = ControlLink(
            host=g("control_host"),
            port=int(g("control_port")),
            hello={
                "kind": "arm",
                "id": self.arm_id,
                "model": g("arm_model"),
                "station": self.station,
                "zone": g("zone"),
            },
            on_message=self._on_control,
            on_state=self._on_link_state,
            logger=self.get_logger(),
        )
        self.link.start()

        self._last_tick = self.get_clock().now()
        self.create_timer(0.05, self._tick)
        self.create_timer(1.0, self._publish_status)

        self.get_logger().info(
            f"{self.arm_id} 적재 스테이션 기동 — {self.station}, gz `{self.gz_name}`, "
            f"설치 위치 ({mx:.2f}, {my:.2f}) m"
        )
        # 시작 자세로 정렬.
        self._send_trajectory([(self._home_pose(), ik.GRIPPER_OPEN, 1.5)])

    # ────────────────────────────────────────────────────── 자세 계산

    def _home_pose(self) -> tuple[float, float, float, float]:
        return (0.0, -0.292, 0.375, 0.817)

    def _bin_pose(self, z: float) -> tuple[float, float, float, float] | None:
        return ik.inverse(-0.19, 0.0, z, PLACE_PITCH)

    def _place_pose(
        self, robot_xy: tuple[float, float] | None, z: float
    ) -> tuple[float, float, float, float] | None:
        """로봇이 선 자리를 팔 베이스 좌표로 옮겨 역기구학을 푼다."""
        target = (REACH_MAX * 0.85, 0.0)
        if robot_xy is not None:
            wx, wy = self.frame.to_world(robot_xy[0], robot_xy[1])
            dx, dy = wx - self._mount[0], wy - self._mount[1]
            # 월드 → 팔 베이스 프레임(설치 방위만큼 되돌린다)
            c, s = math.cos(-self._mount_yaw), math.sin(-self._mount_yaw)
            lx, ly = c * dx - s * dy, s * dx + c * dy
            dist = math.hypot(lx, ly)
            if dist > 1e-6:
                clipped = max(REACH_MIN, min(REACH_MAX, dist))
                target = (lx / dist * clipped, ly / dist * clipped)

        for pitch in (PLACE_PITCH, -0.9, -1.4, -0.6):
            sol = ik.inverse(target[0], target[1], z, pitch)
            if sol is not None:
                return sol
        return None

    # ────────────────────────────────────────────────────── 관제 입력

    def _on_link_state(self, connected: bool) -> None:
        if not connected and self.current_task is not None:
            self.get_logger().warn("관제 링크 단절 — 진행 중 적재 취소")
            self._abort()

    def _on_control(self, msg: dict) -> None:
        kind = msg.get("t")
        if kind == "welcome":
            self.get_logger().info(f"{self.station} 적재 스테이션 등록 완료")
        elif kind == "load":
            self._start_load(msg)
        elif kind == "abort":
            if msg.get("task") in (None, self.current_task):
                self._abort()

    def _start_load(self, msg: dict) -> None:
        task = msg.get("task")
        if self.current_task is not None:
            self.link.send({
                "t": "loadFailed", "id": self.arm_id, "task": task,
                "reason": f"{self.current_task} 적재 진행 중",
            })
            return

        robot_xy = None
        if msg.get("x") is not None and msg.get("y") is not None:
            robot_xy = (float(msg["x"]), float(msg["y"]))

        # 데크 높이를 팔 베이스(link1) 기준으로 환산한다.
        deck_z = self.deck_height - self.pedestal_height
        place = self._place_pose(robot_xy, deck_z + 0.045)
        hover = self._place_pose(robot_xy, deck_z + 0.13)
        grasp = self._bin_pose(0.005)
        approach = self._bin_pose(0.06)
        lift = self._bin_pose(0.09)

        if None in (place, hover, grasp, approach, lift):
            self.link.send({
                "t": "loadFailed", "id": self.arm_id, "task": task,
                "reason": "적재 위치가 팔 사거리를 벗어남",
            })
            self.get_logger().warn(f"{task} 적재 위치 도달 불가")
            return

        self.current_task = task
        self.status = "loading"
        item = msg.get("item", "화물")
        home = self._home_pose()

        # (자세, 그리퍼, 구간 소요 시간)
        self._send_trajectory([
            (approach, ik.GRIPPER_OPEN, 1.2),
            (grasp, ik.GRIPPER_OPEN, 1.0),
            (grasp, ik.GRIPPER_CLOSED, 0.8),   # 파지
            (lift, ik.GRIPPER_CLOSED, 1.0),
            (hover, ik.GRIPPER_CLOSED, 1.6),   # 로봇 위로 선회
            (place, ik.GRIPPER_CLOSED, 1.0),
            (place, ik.GRIPPER_OPEN, 0.8),     # 적재
            (hover, ik.GRIPPER_OPEN, 0.9),
            (home, ik.GRIPPER_OPEN, 1.3),
        ])
        self.get_logger().info(
            f"{msg.get('robot')} 적재 시작 — {item} (태스크 {task})"
        )

    def _abort(self) -> None:
        self.current_task = None
        self.status = "idle"
        self._send_trajectory([(self._home_pose(), ik.GRIPPER_OPEN, 1.5)])

    # ────────────────────────────────────────────────────── 궤적 실행

    def _send_trajectory(self, waypoints) -> None:
        """(자세, 그리퍼, 구간 시간) 목록을 실행 대기열에 올린다."""
        self._segments = [
            ([float(v) for v in joints] + [float(grip)] * 2, float(dt))
            for joints, grip, dt in waypoints
        ]
        self._seg_elapsed = 0.0
        self._from = list(self._target)

    @property
    def _moving(self) -> bool:
        return bool(self._segments)

    def _step_motion(self, dt: float) -> bool:
        """구간을 보간해 목표각을 갱신한다. 궤적을 모두 끝냈으면 True."""
        if not self._segments:
            return False
        goal, span = self._segments[0]
        self._seg_elapsed += dt
        ratio = 1.0 if span <= 0 else min(1.0, self._seg_elapsed / span)
        # 시작·끝에서 부드럽게(코사인 이징) — 실제 매니퓰레이터의 가감속에 가깝다.
        smooth = 0.5 - 0.5 * math.cos(math.pi * ratio)
        self._target = [
            a + (b - a) * smooth for a, b in zip(self._from, goal)
        ]
        if ratio >= 1.0:
            self._segments.pop(0)
            self._from = list(goal)
            self._seg_elapsed = 0.0
            return not self._segments
        return False

    def _publish_targets(self) -> None:
        for name, value in zip(self.joints, self._target):
            self.cmd_pubs[name].publish(Float64(data=float(value)))

    # ────────────────────────────────────────────────────── 주기 동작

    def _tick(self) -> None:
        now = self.get_clock().now()
        dt = (now - self._last_tick).nanoseconds / 1e9
        self._last_tick = now
        if dt <= 0 or dt > 1.0:
            dt = 0.05

        finished = self._step_motion(dt)
        self._publish_targets()

        if not finished or self.current_task is None:
            return

        # 궤적을 모두 소화했다 — 적재 완료 보고.
        task = self.current_task
        self.current_task = None
        self.status = "idle"
        self.loads_done += 1
        self.link.send({"t": "loaded", "id": self.arm_id, "task": task})
        self.get_logger().info(f"{task} 적재 완료 (누적 {self.loads_done}건)")

    def _publish_status(self) -> None:
        self.link.send({
            "t": "armStatus",
            "id": self.arm_id,
            "status": self.status,
            "done": self.loads_done,
        })
        msg = String()
        msg.data = (
            f"{self.arm_id}@{self.station} "
            f"{'연결' if self.link.connected else '단절'} | {self.status} | "
            f"누적 {self.loads_done}건"
            + (f" | 진행 {self.current_task}" if self.current_task else "")
        )
        self.status_pub.publish(msg)

    def destroy_node(self) -> bool:
        try:
            self.link.stop()
        finally:
            return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = PinkyArmAgent()
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
