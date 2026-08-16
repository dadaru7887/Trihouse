"""P0 OMX 명령 시뮬레이터.

Gateway가 보내는 prepare/load/hold/reset 명령을 **생산 메시지 계약 그대로**
검증하고 결정적인 상태 전이를 낸다. `OMX_01`, `OMX_02` 두 인스턴스로
돌리며, P0에서는 물리 OMX의 ROS endpoint를 흉내내지 않는다. 실제 모터
명령은 나가지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class OmxSimulatorError(ValueError):
    """명령이 계약을 만족하지 못했다. 어떤 상태도 바뀌지 않는다."""


REQUIRED_FIELDS = (
    "command_uuid",
    "kind",
    "job_step_id",
    "assignment_revision",
    "omx_id",
    "expected_items",
    "marker_id",
)

SUPPORTED_KINDS = ("prepare", "load", "hold", "reset")

_TRANSITIONS = {
    "prepare": ("PREPARING", "PICKING", "OMX_READY"),
    "load": ("LOADING", "LOAD_COMPLETE"),
    "hold": ("HELD",),
    "reset": ("IDLE",),
}


@dataclass(frozen=True)
class OmxEvent:
    sequence_no: int
    command_uuid: str
    omx_id: str
    job_step_id: int
    assignment_revision: int
    state: str
    expected_items: tuple[str, ...]
    marker_id: int


class OmxProtocolSimulator:
    """한 OMX 장비의 명령 계약과 상태 전이를 결정적으로 재현한다."""

    def __init__(self, *, omx_id: str) -> None:
        if not omx_id.strip():
            raise ValueError("omx_id is required")
        self._omx_id = omx_id.strip()
        self._state = "IDLE"
        self._sequence_no = 0
        self._latest_revision = 0
        self._replies: dict[str, tuple[OmxEvent, ...]] = {}

    @property
    def omx_id(self) -> str:
        return self._omx_id

    @property
    def state(self) -> str:
        return self._state

    def published_ros_topics(self) -> tuple[str, ...]:
        """P0 시뮬레이터는 물리 OMX ROS endpoint를 발행하지 않는다."""
        return ()

    def execute(self, command: Mapping[str, Any]) -> tuple[OmxEvent, ...]:
        parsed = self._validate(command)
        command_uuid = parsed["command_uuid"]
        replayed = self._replies.get(command_uuid)
        if replayed is not None:
            # 같은 command_uuid는 같은 응답을 돌려준다. 재실행하지 않는다.
            return replayed

        kind = parsed["kind"]
        if kind == "load" and self._state != "OMX_READY":
            raise OmxSimulatorError(
                f"NOT_PREPARED: load requires OMX_READY, current state is {self._state}"
            )

        events: list[OmxEvent] = []
        for state in _TRANSITIONS[kind]:
            self._sequence_no += 1
            events.append(
                OmxEvent(
                    sequence_no=self._sequence_no,
                    command_uuid=command_uuid,
                    omx_id=self._omx_id,
                    job_step_id=parsed["job_step_id"],
                    assignment_revision=parsed["assignment_revision"],
                    state=state,
                    expected_items=parsed["expected_items"],
                    marker_id=parsed["marker_id"],
                )
            )
        self._state = events[-1].state
        self._latest_revision = parsed["assignment_revision"]
        frozen = tuple(events)
        self._replies[command_uuid] = frozen
        return frozen

    def _validate(self, command: Mapping[str, Any]) -> dict[str, Any]:
        missing = [field for field in REQUIRED_FIELDS if field not in command]
        if missing:
            raise OmxSimulatorError(
                f"INCOMPLETE_COMMAND: missing {', '.join(sorted(missing))}"
            )

        command_uuid = str(command["command_uuid"]).strip()
        if not command_uuid:
            raise OmxSimulatorError("INCOMPLETE_COMMAND: command_uuid is required")

        kind = str(command["kind"]).strip()
        if kind not in SUPPORTED_KINDS:
            raise OmxSimulatorError(f"UNSUPPORTED_COMMAND: {kind}")

        omx_id = str(command["omx_id"]).strip()
        if omx_id != self._omx_id:
            raise OmxSimulatorError(
                f"OMX_ID_MISMATCH: {self._omx_id} cannot execute work for {omx_id}"
            )

        job_step_id = _positive_int(command["job_step_id"], "job_step_id")
        revision = _positive_int(command["assignment_revision"], "assignment_revision")
        # 이미 처리한 배정보다 오래된 명령은 실행하지 않는다.
        if revision < self._latest_revision:
            raise OmxSimulatorError(
                f"STALE_ASSIGNMENT: revision {revision} is older than "
                f"{self._latest_revision}"
            )

        raw_items = command["expected_items"]
        if isinstance(raw_items, (str, bytes)) or not isinstance(raw_items, (list, tuple)):
            raise OmxSimulatorError("INCOMPLETE_COMMAND: expected_items must be a list")
        items = tuple(str(item).strip() for item in raw_items)
        if not items or any(not item for item in items):
            raise OmxSimulatorError("INCOMPLETE_COMMAND: expected_items must be named")

        marker_id = command["marker_id"]
        if isinstance(marker_id, bool) or not isinstance(marker_id, int) or marker_id < 0:
            raise OmxSimulatorError("INCOMPLETE_COMMAND: marker_id must be a marker ID")

        return {
            "command_uuid": command_uuid,
            "kind": kind,
            "job_step_id": job_step_id,
            "assignment_revision": revision,
            "expected_items": items,
            "marker_id": marker_id,
        }


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise OmxSimulatorError(f"INCOMPLETE_COMMAND: {field} must be a positive integer")
    return value


__all__ = [
    "OmxEvent",
    "OmxProtocolSimulator",
    "OmxSimulatorError",
    "REQUIRED_FIELDS",
    "SUPPORTED_KINDS",
]
