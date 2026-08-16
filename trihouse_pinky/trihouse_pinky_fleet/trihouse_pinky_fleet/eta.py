"""주행 ETA와 OMX 사전 준비 시각을 계산하는 결정적 정책.

속도는 Pinky 반복 주행으로 정한 설정값이다. Nav2 최대 속도 대신 가속·회전·정차를 포함한
실효 속도를 사용한다.
"""

from dataclasses import dataclass, replace
from enum import StrEnum


class SegmentKind(StrEnum):
    CORRIDOR = 'corridor'
    NARROW_OR_TURN = 'narrow_or_turn'
    PRECISE_APPROACH = 'precise_approach'


class EtaEstimator:
    def __init__(
        self,
        *,
        effective_speed_mps: dict[SegmentKind, float],
        uncertainty_margin: float = 0.15,
        omx_reschedule_threshold_s: float = 2.0,
    ) -> None:
        if not 0 <= uncertainty_margin <= 1:
            raise ValueError('uncertainty_margin must be between zero and one')
        if omx_reschedule_threshold_s < 0:
            raise ValueError('omx_reschedule_threshold_s must be non-negative')
        if any(speed <= 0 for speed in effective_speed_mps.values()):
            raise ValueError('all effective speeds must be positive')
        self._speed = effective_speed_mps
        self._margin = uncertainty_margin
        self._omx_reschedule_threshold_s = omx_reschedule_threshold_s

    def estimate_segment(self, length_m: float, kind: SegmentKind) -> float:
        """Return a conservative duration for one route segment."""
        if length_m < 0:
            raise ValueError('length_m must be non-negative')
        try:
            speed = self._speed[kind]
        except KeyError as error:
            raise ValueError(f'no effective speed for {kind}') from error
        return (length_m / speed) * (1 + self._margin)

    def replace_with_nav2_plan(
        self,
        *,
        graph_eta_s: float,
        path_length_m: float | None,
        kind: SegmentKind,
    ) -> float | None:
        """Replace a graph estimate once Nav2 supplies a route.

        A missing path has no trustworthy completion ETA, so the caller must
        leave the job pending instead of combining both estimates.
        """
        if graph_eta_s < 0:
            raise ValueError('graph_eta_s must be non-negative')
        if path_length_m is None:
            return None
        return self.estimate_segment(path_length_m, kind)

    @staticmethod
    def omx_command_at(*, arrival_at_s: float, grasp_s: float, prep_margin_s: float, now_s: float) -> float:
        """Return the planned OMX grasp time, or ``now`` when it is overdue."""
        if grasp_s < 0 or prep_margin_s < 0:
            raise ValueError('OMX durations must be non-negative')
        return max(now_s, arrival_at_s - grasp_s - prep_margin_s)

    def should_reschedule_omx(self, *, previous_arrival_s: float, updated_arrival_s: float) -> bool:
        return abs(updated_arrival_s - previous_arrival_s) > self._omx_reschedule_threshold_s


@dataclass(frozen=True)
class PreparationWindow:
    assignment_revision: int
    handover_group_id: str
    eta_at_s: float
    prepare_at_s: float
    omx_ready: bool = False


class OmxPreparationSchedule:
    """Refresh Nav2/RMF timing until the OMX episode reaches READY."""

    def __init__(self, *, grasp_duration_s: float, prep_margin_s: float) -> None:
        if grasp_duration_s < 0 or prep_margin_s < 0:
            raise ValueError('OMX durations must be non-negative')
        self._grasp_duration_s = grasp_duration_s
        self._prep_margin_s = prep_margin_s
        self._current: PreparationWindow | None = None

    def refresh(
        self,
        *,
        now_s: float,
        nav2_eta_s: float,
        rmf_delay_s: float,
        assignment_revision: int,
        handover_group_id: str,
    ) -> PreparationWindow:
        if min(now_s, nav2_eta_s, rmf_delay_s) < 0:
            raise ValueError('ETA inputs must be non-negative')
        if assignment_revision <= 0 or not handover_group_id:
            raise ValueError('preparation episode identity is required')
        identity = (assignment_revision, handover_group_id)
        if self._current is not None and identity != (
            self._current.assignment_revision,
            self._current.handover_group_id,
        ):
            raise ValueError('preparation episode identity cannot be replaced')
        if self._current is not None and self._current.omx_ready:
            return self._current
        eta_at_s = now_s + nav2_eta_s + rmf_delay_s
        self._current = PreparationWindow(
            assignment_revision=assignment_revision,
            handover_group_id=handover_group_id,
            eta_at_s=eta_at_s,
            prepare_at_s=max(
                now_s,
                eta_at_s - self._grasp_duration_s - self._prep_margin_s,
            ),
        )
        return self._current

    def mark_omx_ready(self) -> PreparationWindow:
        if self._current is None:
            raise ValueError('prepare schedule has not been calculated')
        self._current = replace(self._current, omx_ready=True)
        return self._current

    @property
    def current(self) -> PreparationWindow | None:
        return self._current
