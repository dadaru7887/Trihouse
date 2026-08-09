"""OMX 장비 종류와 무관한 적재·하차·비상 hold 정책.

실제 MoveIt, gripper, load-cell endpoint는 이 저장소에서 확인되지 않았다. 따라서 이
정책은 endpoint 이름을 가정하지 않고 adapter가 검증한 readiness/물리 확인 결과만 받는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OmxState(str, Enum):
    IDLE = "IDLE"
    LOADING = "LOADING"
    LOADED = "LOADED"
    UNLOADING = "UNLOADING"
    HELD = "HELD"
    EMERGENCY = "EMERGENCY"


@dataclass(frozen=True)
class OmxResult:
    accepted: bool
    state: OmxState
    detail: str


class OmxAdapter:
    """Pinky·OMX 공동 준비와 물리 확인을 통과할 때만 상태를 바꾸는 adapter 정책이다."""

    def __init__(self, omx_id: str) -> None:
        self.omx_id = omx_id
        self.state = OmxState.IDLE

    def start_loading(self, *, pinky_ready: bool, omx_ready: bool) -> OmxResult:
        """Pinky 정차와 OMX 준비가 모두 참일 때만 적재 motion을 시작한다."""
        if self.state is not OmxState.IDLE:
            return OmxResult(False, self.state, "OMX is not idle")
        if not (pinky_ready and omx_ready):
            return OmxResult(False, self.state, "joint handover readiness is required")
        self.state = OmxState.LOADING
        return OmxResult(True, self.state, "loading started")

    def complete_loading(self, *, gripper_open: bool, safely_retracted: bool, cargo_confirmed: bool) -> OmxResult:
        """성공 callback 뒤에도 물리 확인과 안전 후퇴가 있어야 적재 완료로 만든다."""
        if self.state is not OmxState.LOADING:
            return OmxResult(False, self.state, "OMX is not loading")
        if not (gripper_open and safely_retracted and cargo_confirmed):
            return OmxResult(False, self.state, "gripper, retreat, and cargo confirmation are required")
        self.state = OmxState.LOADED
        return OmxResult(True, self.state, "loading physically confirmed")

    def timeout(self) -> OmxResult:
        """motion timeout은 자동 재시도가 아니라 운영자 판단용 HELD로 전환한다."""
        if self.state not in (OmxState.LOADING, OmxState.UNLOADING):
            return OmxResult(False, self.state, "no OMX motion is active")
        self.state = OmxState.HELD
        return OmxResult(True, self.state, "motion timed out; operator decision required")

    def emergency_stop(self) -> OmxResult:
        """비상은 장비 motion을 보류하며, 일반 reset으로 해제되지 않는다."""
        self.state = OmxState.EMERGENCY
        return OmxResult(True, self.state, "OMX emergency hold")

    def operator_reset(self) -> OmxResult:
        """HELD만 명시적 운영자 확인 뒤 IDLE로 되돌린다; EMERGENCY는 별도 안전 절차다."""
        if self.state is not OmxState.HELD:
            return OmxResult(False, self.state, "only held OMX can be reset here")
        self.state = OmxState.IDLE
        return OmxResult(True, self.state, "operator reset accepted")
