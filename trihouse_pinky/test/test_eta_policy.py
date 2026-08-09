"""Pinky SR 주행 ETA와 OMX 준비 시각의 인수 테스트."""
from __future__ import annotations

import unittest

from trihouse_pinky_fleet.eta import EtaEstimator, SegmentKind


class EtaEstimatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.estimator = EtaEstimator(
            effective_speed_mps={
                SegmentKind.CORRIDOR: 0.4,
                SegmentKind.NARROW_OR_TURN: 0.2,
                SegmentKind.PRECISE_APPROACH: 0.1,
            },
            uncertainty_margin=0.1,
        )

    def test_nav2_plan_replaces_graph_estimate_instead_of_being_added(self) -> None:
        """A generated plan supersedes, rather than inflates, the graph ETA."""
        graph_eta = self.estimator.estimate_segment(20.0, SegmentKind.CORRIDOR)
        nav2_eta = self.estimator.replace_with_nav2_plan(
            graph_eta_s=graph_eta, path_length_m=8.0, kind=SegmentKind.CORRIDOR
        )
        self.assertEqual(22.0, nav2_eta)

    def test_missing_nav2_plan_holds_start_without_a_confirmed_eta(self) -> None:
        """A task must not claim a completion time before Nav2 can plan it."""
        self.assertIsNone(self.estimator.replace_with_nav2_plan(
            graph_eta_s=55.0, path_length_m=None, kind=SegmentKind.CORRIDOR
        ))

    def test_omx_grasp_is_immediate_only_when_schedule_is_already_past(self) -> None:
        """The grasp request time is arrival minus grasp duration and preparation margin."""
        self.assertEqual(83.0, self.estimator.omx_command_at(arrival_at_s=100.0, grasp_s=12.0, prep_margin_s=5.0, now_s=70.0))
        self.assertEqual(70.0, self.estimator.omx_command_at(arrival_at_s=80.0, grasp_s=12.0, prep_margin_s=5.0, now_s=70.0))

    def test_small_eta_change_does_not_reschedule_omx(self) -> None:
        """One-to-two seconds of plan noise must not churn the OMX schedule."""
        self.assertFalse(self.estimator.should_reschedule_omx(previous_arrival_s=100.0, updated_arrival_s=101.5))
        self.assertTrue(self.estimator.should_reschedule_omx(previous_arrival_s=100.0, updated_arrival_s=102.1))


if __name__ == '__main__':
    unittest.main()
