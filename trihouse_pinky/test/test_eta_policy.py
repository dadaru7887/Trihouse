"""Pinky SR 주행 ETA와 OMX 준비 시각의 인수 테스트."""

from dataclasses import FrozenInstanceError
import unittest

from trihouse_pinky_fleet.eta import EtaEstimator, OmxPreparationSchedule, SegmentKind


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

    def test_prepare_at_refreshes_from_nav2_eta_and_rmf_delay(self) -> None:
        """A material path or traffic delay moves preparation without changing identity."""
        schedule = OmxPreparationSchedule(grasp_duration_s=12.0, prep_margin_s=5.0)

        first = schedule.refresh(
            now_s=50.0, nav2_eta_s=40.0, rmf_delay_s=10.0,
            assignment_revision=4, handover_group_id="group-ambient",
        )
        delayed = schedule.refresh(
            now_s=55.0, nav2_eta_s=45.0, rmf_delay_s=12.0,
            assignment_revision=4, handover_group_id="group-ambient",
        )

        self.assertEqual(83.0, first.prepare_at_s)
        self.assertEqual(95.0, delayed.prepare_at_s)
        self.assertEqual(112.0, delayed.eta_at_s)

    def test_ready_omx_episode_is_never_reset_by_later_eta_refresh(self) -> None:
        """Traffic replanning cannot restart a pick that is already OMX_READY."""
        schedule = OmxPreparationSchedule(grasp_duration_s=12.0, prep_margin_s=5.0)
        schedule.refresh(
            now_s=50.0, nav2_eta_s=40.0, rmf_delay_s=10.0,
            assignment_revision=4, handover_group_id="group-ambient",
        )
        ready = schedule.mark_omx_ready()

        unchanged = schedule.refresh(
            now_s=60.0, nav2_eta_s=90.0, rmf_delay_s=30.0,
            assignment_revision=4, handover_group_id="group-ambient",
        )

        self.assertEqual(ready, unchanged)
        self.assertTrue(unchanged.omx_ready)

    def test_preparation_window_is_immutable_and_bound_to_assignment_episode(self) -> None:
        schedule = OmxPreparationSchedule(grasp_duration_s=12.0, prep_margin_s=5.0)
        first = schedule.refresh(
            now_s=100.0, nav2_eta_s=30.0, rmf_delay_s=4.0,
            assignment_revision=4, handover_group_id="group-ambient",
        )
        ready = schedule.mark_omx_ready()

        with self.assertRaises(FrozenInstanceError):
            ready.omx_ready = False
        with self.assertRaisesRegex(ValueError, "preparation episode identity"):
            schedule.refresh(
                now_s=110.0, nav2_eta_s=50.0, rmf_delay_s=8.0,
                assignment_revision=5, handover_group_id="group-frozen",
            )

        self.assertIs(schedule.current, ready)
        self.assertEqual(4, first.assignment_revision)
        self.assertEqual("group-ambient", first.handover_group_id)


if __name__ == '__main__':
    unittest.main()
