"""입고·출고·비상 공통 작업 계약의 순수 단위 테스트."""
from __future__ import annotations

import unittest

from control_tower.task_manager.transport_job import (
    JobEvent,
    JobPhase,
    JobStateMachine,
    LinkReconciler,
    ProtocolEnvelope,
    ProtocolError,
)


def envelope(message_id: str, message_type: str = "job_event") -> ProtocolEnvelope:
    """테스트마다 동일한 관제 전송 필수 필드를 만들기 위한 helper다."""
    return ProtocolEnvelope.create(
        schema_version="1.0",
        message_id=message_id,
        type=message_type,
        sent_at="2026-08-09T00:00:00Z",
        robot_id="PK-01",
        job_id="job-1",
        order_id="order-1",
        job_step_id="step-1",
    )


class TransportJobContractTest(unittest.TestCase):
    """장비와 ROS 없이도 위험한 순서 위반을 막는 계약을 검증한다."""

    def test_requires_all_standard_envelope_fields(self) -> None:
        with self.assertRaises(ProtocolError):
            ProtocolEnvelope.create(
                schema_version="1.0", message_id="m-1", type="job_event",
                sent_at="", robot_id="PK-01", job_id="job-1", order_id="order-1", job_step_id="step-1",
            )

    def test_happy_path_requires_physical_handover_evidence(self) -> None:
        job = JobStateMachine("job-1")
        for message_id, event in (
            ("m-1", JobEvent.RESERVE), ("m-2", JobEvent.OMX_PICKED),
            ("m-3", JobEvent.PINKY_AT_STATION), ("m-4", JobEvent.HANDOVER_READY),
        ):
            self.assertTrue(job.apply(envelope(message_id), event).accepted)
        self.assertFalse(job.apply(envelope("m-5"), JobEvent.OMX_LOAD_SUCCEEDED).accepted)
        self.assertTrue(job.apply(envelope("m-6"), JobEvent.OMX_LOAD_SUCCEEDED, cargo_confirmed=True).accepted)
        self.assertEqual(JobPhase.LOADED, job.phase)
        self.assertTrue(job.apply(envelope("m-7"), JobEvent.PINKY_DEPARTED).accepted)
        self.assertTrue(job.apply(envelope("m-8"), JobEvent.PINKY_AT_DESTINATION).accepted)
        self.assertTrue(job.apply(envelope("m-9"), JobEvent.OMX_UNLOAD_SUCCEEDED, cargo_confirmed=True).accepted)
        self.assertEqual(JobPhase.COMPLETED, job.phase)

    def test_rejects_order_violation_and_duplicate_is_idempotent(self) -> None:
        job = JobStateMachine("job-1")
        self.assertFalse(job.apply(envelope("m-1"), JobEvent.PINKY_DEPARTED).accepted)
        first = job.apply(envelope("m-2"), JobEvent.RESERVE)
        duplicate = job.apply(envelope("m-2"), JobEvent.RESERVE)
        self.assertTrue(first.accepted)
        self.assertTrue(duplicate.accepted)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(JobPhase.RESERVED, job.phase)

    def test_emergency_requires_explicit_recovery_decision(self) -> None:
        job = JobStateMachine("job-1")
        job.apply(envelope("m-1"), JobEvent.RESERVE)
        self.assertTrue(job.apply(envelope("m-2"), JobEvent.EMERGENCY).accepted)
        self.assertEqual(JobPhase.EMERGENCY, job.phase)
        self.assertFalse(job.apply(envelope("m-3"), JobEvent.PINKY_DEPARTED).accepted)
        self.assertTrue(job.apply(envelope("m-4"), JobEvent.RECOVERY_REQUIRED).accepted)
        self.assertEqual(JobPhase.RECOVERY, job.phase)
        self.assertTrue(job.apply(envelope("m-5"), JobEvent.HOLD).accepted)
        self.assertEqual(JobPhase.HELD, job.phase)

    def test_link_loss_rejects_new_work_and_reconcile_requires_checkpoint_match(self) -> None:
        link = LinkReconciler()
        self.assertTrue(link.accept_new_work())
        link.disconnect(job_id="job-1", phase=JobPhase.LOADING, checkpoint="step-5")
        self.assertFalse(link.accept_new_work())
        self.assertFalse(link.reconnect(job_id="job-1", phase=JobPhase.LOADING, checkpoint="different"))
        self.assertTrue(link.reconnect(job_id="job-1", phase=JobPhase.LOADING, checkpoint="step-5"))
        self.assertTrue(link.accept_new_work())

