"""실물 협로 보정용 ExecuteTransport client.

ROS import는 실제 motion scenario를 만들 때만 수행한다. 일반 pytest 수집과 gate
테스트는 ROS interface build 없이도 실행돼야 한다.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from trihouse_pinky_docking.narrow_zone import (
    ENTER,
    EXIT,
    NarrowZoneProfile,
    Pose2D,
)


PHASES = (ENTER, EXIT, "roundtrip")
NAMESPACE = re.compile(r"^[a-z][a-z0-9_]*$")


def ros_boolean_parameter_is_true(output: str) -> bool:
    """`ros2 param get`의 boolean true 응답만 허용한다."""
    return output.strip() == "Boolean value is: True"


@dataclass(frozen=True)
class MotionRequest:
    enable_motion: bool
    robot_namespace: str
    destination_code: str
    phase: str


@dataclass(frozen=True)
class MotionGateDecision:
    allowed: bool
    reason_code: str
    reason: str
    profile: NarrowZoneProfile | None = None


@dataclass(frozen=True)
class MotionResult:
    success: bool
    code: str
    message: str
    trace_path: Path
    event_log_path: Path


class PersistentTrace:
    """각 단계가 끝날 때마다 JSONL에 즉시 기록하고 마지막에 요약을 만든다."""

    def __init__(self, summary_path: Path, *, context: Mapping[str, Any]) -> None:
        self.summary_path = summary_path
        self.event_path = summary_path.with_suffix(".jsonl")
        self.context = dict(context)
        self.started_monotonic = time.monotonic()
        self.events: list[dict[str, Any]] = []
        self.summary_path.parent.mkdir(parents=True, exist_ok=True)
        self.record("attempt_started", **self.context)

    def record(self, event: str, **fields: Any) -> dict[str, Any]:
        item = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "elapsed_s": round(time.monotonic() - self.started_monotonic, 3),
            "event": event,
            **fields,
        }
        self.events.append(item)
        line = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        # 매 event마다 파일을 닫아 pytest/Fleet가 비정상 종료돼도 앞 단계가 남는다.
        with self.event_path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
            stream.flush()
        print(f"[narrow-trace] {line}", flush=True)
        return item

    def finalize(self, *, success: bool, code: str, message: str) -> None:
        document = {
            "context": self.context,
            "success": success,
            "code": code,
            "message": message,
            "event_log_path": str(self.event_path),
            "events": self.events,
        }
        temporary = self.summary_path.with_suffix(self.summary_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.summary_path)


def validate_motion_request(
    request: MotionRequest,
    profiles: Mapping[str, NarrowZoneProfile],
) -> MotionGateDecision:
    if not request.enable_motion:
        return MotionGateDecision(False, "MOTION_NOT_ENABLED", "--enable-motion이 없다")
    if not NAMESPACE.fullmatch(request.robot_namespace):
        return MotionGateDecision(
            False,
            "ROBOT_NAMESPACE_INVALID",
            "namespace는 pinky_01 같은 소문자 snake_case여야 한다",
        )
    if request.phase not in PHASES:
        return MotionGateDecision(False, "PHASE_INVALID", f"허용 phase: {PHASES}")
    profile = profiles.get(request.destination_code)
    if profile is None:
        return MotionGateDecision(
            False,
            "NARROW_PROFILE_UNKNOWN",
            f"{request.destination_code} profile이 없다",
        )
    directions = (ENTER, EXIT) if request.phase == "roundtrip" else (request.phase,)
    if any(not profile.calibration_ready(direction) for direction in directions):
        return MotionGateDecision(
            False,
            "NARROW_CALIBRATION_NOT_READY",
            f"{request.destination_code}의 {request.phase} 후보값이 온전하지 않다",
            profile,
        )
    return MotionGateDecision(True, "READY", "실기 보정 요청 구조가 온전하다", profile)


def validate_simulation_request(
    request: MotionRequest,
    profiles: Mapping[str, NarrowZoneProfile],
    *,
    ros_domain_id: str,
    calibration_enabled: bool,
) -> MotionGateDecision:
    """실기 DDS에 오접속하거나 일반 주문 gate로 후보값을 실행하지 못하게 한다."""
    decision = validate_motion_request(request, profiles)
    if not decision.allowed:
        return decision
    if ros_domain_id.strip() != "0":
        return MotionGateDecision(
            False,
            "SIMULATION_DOMAIN_MISMATCH",
            "협로 시뮬레이션은 ROS_DOMAIN_ID=0에서만 실행한다",
            decision.profile,
        )
    if not calibration_enabled:
        return MotionGateDecision(
            False,
            "SIMULATION_CALIBRATION_DISABLED",
            "Fleet의 allow_narrow_calibration을 먼저 true로 설정해야 한다",
            decision.profile,
        )
    return MotionGateDecision(
        True,
        "READY",
        "시뮬레이션 domain과 보정 gate가 준비됐다",
        decision.profile,
    )


class PhysicalNarrowZoneClient:
    """한 번의 enter/exit/roundtrip만 실행하고 항상 action을 정리한다."""

    def __init__(self, request: MotionRequest, profile: NarrowZoneProfile) -> None:
        try:
            import rclpy
            from rclpy.action import ActionClient
            from trihouse_interfaces.action import ExecuteTransport
            from trihouse_interfaces.msg import Readiness, RobotStatus, SafetyState
        except ImportError as error:
            raise RuntimeError(
                "ROS workspace를 colcon build하고 install/setup.bash를 source해야 한다"
            ) from error

        self.rclpy = rclpy
        self.ExecuteTransport = ExecuteTransport
        self.Readiness = Readiness
        self.SafetyState = SafetyState
        self.request = request
        self.profile = profile
        self._owns_context = not rclpy.ok()
        if self._owns_context:
            rclpy.init()
        self.node = rclpy.create_node(
            "narrow_zone_hardware_test", namespace=request.robot_namespace
        )
        self.client = ActionClient(
            self.node, ExecuteTransport, "trihouse/transport/execute"
        )
        self.readiness_state: int | None = None
        self.safety_state: int | None = None
        self.map_revision = ""
        self.active_goal = None
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", request.destination_code)
        self.trace_path = Path(
            f"/tmp/trihouse_narrow_{request.robot_namespace}_{safe_name}_"
            f"{request.phase}_{time.time_ns()}.json"
        )
        self.trace_recorder = PersistentTrace(
            self.trace_path,
            context={
                "robot_namespace": request.robot_namespace,
                "destination_code": request.destination_code,
                "phase": request.phase,
            },
        )
        self.trace = self.trace_recorder.events
        self.node.create_subscription(
            Readiness, "trihouse/readiness", self._on_readiness, 10
        )
        self.node.create_subscription(
            SafetyState, "trihouse/safety/state", self._on_safety, 10
        )
        self.node.create_subscription(
            RobotStatus, "trihouse/status", self._on_status, 10
        )

    def _on_readiness(self, message) -> None:
        state = int(message.state)
        if state != self.readiness_state:
            self.trace_recorder.record("readiness", state=state)
        self.readiness_state = state

    def _on_safety(self, message) -> None:
        state = int(message.state)
        if state != self.safety_state:
            self.trace_recorder.record(
                "safety", state=state, detail=str(message.detail)
            )
        self.safety_state = state

    def _on_status(self, message) -> None:
        self.map_revision = str(message.map_revision)
        position = message.pose.pose.position
        orientation = message.pose.pose.orientation
        yaw = math.atan2(
            2.0
            * (
                orientation.w * orientation.z
                + orientation.x * orientation.y
            ),
            1.0
            - 2.0
            * (
                orientation.y * orientation.y
                + orientation.z * orientation.z
            ),
        )
        self.trace_recorder.record(
            "pose",
            frame_id=str(message.frame_id),
            map_revision=self.map_revision,
            x=round(float(position.x), 6),
            y=round(float(position.y), 6),
            yaw=round(yaw, 6),
        )

    def wait_for_motion_gate(self, *, timeout_s: float) -> MotionGateDecision:
        self.trace_recorder.record("motion_gate_wait_started", timeout_s=timeout_s)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self.rclpy.spin_once(self.node, timeout_sec=0.1)
            if (
                self.readiness_state == self.Readiness.STATE_READY
                and self.safety_state is not None
                and self.safety_state < self.SafetyState.STATE_STOP
                and self.map_revision
                and self.client.wait_for_server(timeout_sec=0.0)
            ):
                motor_topic = self.node.resolve_topic_name("cmd_vel")
                publishers = self.node.get_publishers_info_by_topic(motor_topic)
                if len(publishers) != 1:
                    continue
                publisher_name = str(publishers[0].node_name)
                if "safety" not in publisher_name:
                    self.trace_recorder.record(
                        "motion_gate_failed",
                        reason_code="MOTOR_PUBLISHER_UNSAFE",
                        motor_topic=motor_topic,
                        publisher=publisher_name,
                    )
                    return MotionGateDecision(
                        False,
                        "MOTOR_PUBLISHER_UNSAFE",
                        f"{motor_topic} 발행자가 safety가 아니다: {publisher_name}",
                        self.profile,
                    )
                self.trace_recorder.record(
                    "motion_gate_passed",
                    map_revision=self.map_revision,
                    motor_topic=motor_topic,
                    publisher=publisher_name,
                )
                return MotionGateDecision(
                    True, "READY", "readiness/safety/action/motor gate 통과", self.profile
                )
        self.trace_recorder.record(
            "motion_gate_failed",
            reason_code="MOTION_GATE_TIMEOUT",
            readiness_state=self.readiness_state,
            safety_state=self.safety_state,
            map_revision=self.map_revision,
        )
        return MotionGateDecision(
            False,
            "MOTION_GATE_TIMEOUT",
            "readiness, safety, map revision, action server, 단일 motor publisher 중 하나가 준비되지 않았다",
            self.profile,
        )

    def execute_once(self, *, timeout_s: float) -> MotionResult:
        try:
            if self.request.phase in (ENTER, "roundtrip"):
                enter = self._send_goal(
                    self.profile.destination_code,
                    self.profile.dock_target,
                    timeout_s=timeout_s,
                )
                if not enter.success or self.request.phase == ENTER:
                    return enter
            return self._send_goal(
                "narrow_calibration_exit_target",
                self.profile.exit_target,
                timeout_s=timeout_s,
            )
        except KeyboardInterrupt:
            self._cancel_active()
            return self._result(False, "INTERRUPTED", "사용자 중단으로 action을 취소했다")

    def _send_goal(
        self, destination_code: str, target: Pose2D | None, *, timeout_s: float
    ) -> MotionResult:
        if target is None:
            return self._result(False, "TARGET_MISSING", "목표 pose가 없다")
        goal = self.ExecuteTransport.Goal()
        now = self.node.get_clock().now().to_msg()
        goal.task_context.active = True
        goal.task_context.job_id = int(time.time())
        goal.task_context.job_step_id = goal.task_context.job_id
        goal.task_context.assignment_revision = 1
        goal.task_context.rmf_task_id = f"calibration-{uuid4()}"
        goal.task_context.command_id = str(uuid4())
        goal.task_context.map_revision = self.map_revision
        goal.task_context.command_source = "hardware_calibration"
        goal.destination_code = destination_code
        goal.dropoff_location_id = destination_code
        goal.dropoff_pose.header.frame_id = "map"
        goal.dropoff_pose.header.stamp = now
        goal.dropoff_pose.pose.position.x = target.x
        goal.dropoff_pose.pose.position.y = target.y
        goal.dropoff_pose.pose.orientation.z = __import__("math").sin(target.yaw / 2.0)
        goal.dropoff_pose.pose.orientation.w = __import__("math").cos(target.yaw / 2.0)
        goal.requires_precise_stop = True
        goal.handover_expected = False
        goal.mode = self.ExecuteTransport.Goal.MODE_RMF_NAVIGATION

        self.trace_recorder.record(
            "goal_sent",
            destination_code=destination_code,
            map_revision=self.map_revision,
            x=target.x,
            y=target.y,
            yaw=target.yaw,
            timeout_s=timeout_s,
        )

        send = self.client.send_goal_async(goal)
        if not self._wait(send, timeout_s=10.0):
            return self._result(False, "GOAL_SEND_TIMEOUT", "goal 전송이 시간 안에 끝나지 않았다")
        self.active_goal = send.result()
        if self.active_goal is None or not self.active_goal.accepted:
            return self._result(False, "GOAL_REJECTED", "ExecuteTransport goal이 거절됐다")
        self.trace_recorder.record("goal_accepted", destination_code=destination_code)
        result_future = self.active_goal.get_result_async()
        if not self._wait(result_future, timeout_s=timeout_s):
            self._cancel_active()
            return self._result(False, "GOAL_TIMEOUT", "bounded attempt 시간이 끝나 action을 취소했다")
        wrapped = result_future.result()
        result = wrapped.result
        self.active_goal = None
        return self._result(bool(result.success), str(result.code), str(result.message))

    def _wait(self, future, *, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while not future.done() and time.monotonic() < deadline:
            self.rclpy.spin_once(self.node, timeout_sec=0.1)
        return future.done()

    def _cancel_active(self) -> None:
        if self.active_goal is None:
            return
        self.trace_recorder.record("goal_cancel_requested")
        cancel = self.active_goal.cancel_goal_async()
        self._wait(cancel, timeout_s=5.0)
        self.active_goal = None

    def _result(self, success: bool, code: str, message: str) -> MotionResult:
        self.trace_recorder.record(
            "result", success=success, code=code, message=message
        )
        self.trace_recorder.finalize(
            success=success, code=code, message=message
        )
        return MotionResult(
            success, code, message, self.trace_path, self.trace_recorder.event_path
        )

    def close(self) -> None:
        self._cancel_active()
        self.node.destroy_node()
        if self._owns_context:
            self.rclpy.try_shutdown()
