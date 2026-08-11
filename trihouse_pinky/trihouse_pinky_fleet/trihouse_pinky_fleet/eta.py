"""주행 ETA와 OMX 사전 준비 시각을 계산하는 결정적 정책.

속도는 Pinky 반복 주행으로 정한 설정값이다. Nav2 최대 속도 대신 가속·회전·정차를 포함한
실효 속도를 사용한다.
"""

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
