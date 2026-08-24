"""Synchronous ROS Action client used by the central Executor worker."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from .simulation_profile import OmxPhase, PhaseSample, validate_feedback


_DEVICE_ID = re.compile(r"OMX_[0-9]{2,}")
_FEEDBACK_IDENTITIES = (
    "omx_id",
    "job_id",
    "job_step_id",
    "handover_group_id",
    "pinky_id",
)


class OmxExecutionEvidence(dict[str, Any]):
    """Action result plus the ordered feedback evidence, with legacy mapping access."""

    def __init__(
        self,
        result: dict[str, Any],
        feedback: tuple[dict[str, Any], ...],
    ) -> None:
        super().__init__(result)
        self.result = self
        self.feedback = feedback


class OmxFeedbackTracker:
    """Validate and retain one OMX execution's feedback heartbeat stream."""

    def __init__(
        self,
        expected_identity: Mapping[str, object],
        *,
        max_gap_s: float = 2.0,
    ) -> None:
        if max_gap_s <= 0:
            raise ValueError("max_gap_s must be positive")
        missing = [key for key in _FEEDBACK_IDENTITIES if key not in expected_identity]
        if missing:
            raise ValueError(f"missing feedback identities: {', '.join(missing)}")
        self._expected = {key: expected_identity[key] for key in _FEEDBACK_IDENTITIES}
        self._max_gap_s = max_gap_s
        self._events: list[dict[str, Any]] = []
        self._previous: PhaseSample | None = None
        self._previous_joint_stamp_ns: int | None = None

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._events)

    def record_json(self, event_json: str) -> None:
        try:
            event = json.loads(event_json)
        except (json.JSONDecodeError, TypeError) as error:
            raise RuntimeError("INVALID_FEEDBACK_JSON") from error
        if not isinstance(event, dict):
            raise RuntimeError("INVALID_FEEDBACK_JSON")
        if any(event.get(key) != value for key, value in self._expected.items()):
            raise RuntimeError("FEEDBACK_IDENTITY_MISMATCH")
        if event.get("schema_version") != "v1":
            raise RuntimeError("UNSUPPORTED_FEEDBACK_SCHEMA")
        if event.get("trajectory_tracking") is not True:
            raise RuntimeError("TRAJECTORY_NOT_TRACKING")
        try:
            sample = PhaseSample.from_values(
                str(event["phase"]),
                float(event["phase_elapsed_s"]),
                float(event["total_elapsed_s"]),
                float(event["progress"]),
            )
            joint_stamp_ns = int(event["joint_state_stamp_ns"])
            validate_feedback(self._previous, sample)
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError(f"INVALID_FEEDBACK: {error}") from error
        if self._previous is not None:
            gap = sample.total_elapsed_s - self._previous.total_elapsed_s
            if gap > self._max_gap_s:
                raise RuntimeError("FEEDBACK_HEARTBEAT_GAP")
        if (
            self._previous_joint_stamp_ns is not None
            and joint_stamp_ns < self._previous_joint_stamp_ns
        ):
            raise RuntimeError("JOINT_STATE_STAMP_REGRESSION")
        self._events.append(event)
        self._previous = sample
        self._previous_joint_stamp_ns = joint_stamp_ns

    def require_complete(self) -> None:
        if self._previous is None or self._previous.phase is not OmxPhase.SUCCEEDED:
            raise RuntimeError("OMX_FEEDBACK_INCOMPLETE")


def action_endpoint_for_device(device_id: str) -> str:
    """Derive the only allowed ROS route from the canonical DB device ID."""
    if _DEVICE_ID.fullmatch(device_id) is None:
        raise ValueError(f"invalid canonical OMX device ID: {device_id!r}")
    return f"/{device_id.lower()}/execute"


class RosOmxActionExecutor:
    """Block one polling worker until its device-specific Action completes."""

    def __init__(self, node: object, *, device_id: str, timeout_s: float = 300.0) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        from rclpy.action import ActionClient
        from trihouse_interfaces.action import ExecuteOmx

        self._rclpy = __import__("rclpy")
        self._action_type = ExecuteOmx
        self._client = ActionClient(
            node, ExecuteOmx, action_endpoint_for_device(device_id)
        )
        self._node = node
        self._device_id = device_id
        self._timeout_s = timeout_s

    def execute(self, command: dict[str, object]) -> OmxExecutionEvidence:
        if command.get("omx_id") != self._device_id:
            raise RuntimeError("DEVICE_MISMATCH")
        if not self._client.wait_for_server(timeout_sec=self._timeout_s):
            raise TimeoutError(f"{action_endpoint_for_device(self._device_id)} unavailable")
        goal = self._action_type.Goal()
        goal.command_json = json.dumps(
            command, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        tracker = OmxFeedbackTracker(command) if command.get("kind") == "load" else None

        def record_feedback(message: object) -> None:
            if tracker is None:
                raise RuntimeError("UNEXPECTED_OMX_FEEDBACK")
            tracker.record_json(message.feedback.event_json)  # type: ignore[attr-defined]

        sent = self._client.send_goal_async(goal, feedback_callback=record_feedback)
        self._rclpy.spin_until_future_complete(
            self._node, sent, timeout_sec=self._timeout_s
        )
        handle = sent.result()
        if handle is None or not handle.accepted:
            raise RuntimeError("OMX Action goal rejected")
        completed = handle.get_result_async()
        self._rclpy.spin_until_future_complete(
            self._node, completed, timeout_sec=self._timeout_s
        )
        wrapped = completed.result()
        if wrapped is None:
            raise TimeoutError("OMX Action result timeout")
        result = wrapped.result
        try:
            body = json.loads(result.result_json)
        except json.JSONDecodeError as error:
            raise RuntimeError("OMX Action returned invalid result JSON") from error
        if not result.success:
            reason = body.get("reason_code", "OMX_EXECUTION_FAILED")
            raise RuntimeError(f"{reason} (code={result.code})")
        if not isinstance(body, dict):
            raise RuntimeError("OMX Action result must be a JSON object")
        body["success"] = True
        if tracker is not None:
            tracker.require_complete()
        return OmxExecutionEvidence(body, tracker.events if tracker is not None else ())


__all__ = [
    "OmxExecutionEvidence",
    "OmxFeedbackTracker",
    "RosOmxActionExecutor",
    "action_endpoint_for_device",
]
