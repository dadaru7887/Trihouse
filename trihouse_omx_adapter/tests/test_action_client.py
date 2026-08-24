from __future__ import annotations

import json

import pytest

from trihouse_omx_adapter.action_client import (
    OmxExecutionEvidence,
    OmxFeedbackTracker,
)


EXPECTED = {
    "omx_id": "OMX_01",
    "job_id": "job-1",
    "job_step_id": "step-1",
    "handover_group_id": "handover-1",
    "pinky_id": "PINKY_01",
}


def event(*, phase: str, elapsed: float, progress: float) -> str:
    return json.dumps(
        {
            "schema_version": "v1",
            **EXPECTED,
            "phase": phase,
            "phase_elapsed_s": elapsed if phase == "picking" else elapsed - 7.5,
            "total_elapsed_s": elapsed,
            "progress": progress,
            "joint_state_stamp_ns": int(elapsed * 1_000_000_000),
            "trajectory_tracking": True,
        }
    )


def test_tracker_accepts_complete_monotonic_transfer() -> None:
    tracker = OmxFeedbackTracker(EXPECTED, max_gap_s=2.0)

    timeline = (
        ("picking", 0.0),
        ("picking", 2.0),
        ("picking", 4.0),
        ("picking", 6.0),
        ("loading", 7.5),
        ("loading", 9.5),
        ("loading", 11.5),
        ("loading", 13.5),
        ("succeeded", 15.0),
    )
    for phase, elapsed in timeline:
        payload = event(
            phase=phase,
            elapsed=elapsed,
            progress=elapsed / 15.0 * 100.0,
        )
        tracker.record_json(payload)

    assert [sample["phase"] for sample in tracker.events] == [
        "picking",
        "picking",
        "picking",
        "picking",
        "loading",
        "loading",
        "loading",
        "loading",
        "succeeded",
    ]
    tracker.require_complete()


def test_tracker_rejects_identity_mismatch() -> None:
    tracker = OmxFeedbackTracker(EXPECTED)
    payload = json.loads(event(phase="picking", elapsed=0.0, progress=0.0))
    payload["pinky_id"] = "PINKY_02"

    with pytest.raises(RuntimeError, match="FEEDBACK_IDENTITY_MISMATCH"):
        tracker.record_json(json.dumps(payload))


def test_tracker_rejects_heartbeat_gap_over_two_seconds() -> None:
    tracker = OmxFeedbackTracker(EXPECTED, max_gap_s=2.0)
    tracker.record_json(event(phase="picking", elapsed=0.0, progress=0.0))

    with pytest.raises(RuntimeError, match="FEEDBACK_HEARTBEAT_GAP"):
        tracker.record_json(event(phase="picking", elapsed=2.001, progress=13.34))


def test_evidence_preserves_legacy_result_mapping_interface() -> None:
    evidence = OmxExecutionEvidence(
        result={"success": True, "policy_completed": True},
        feedback=({"phase": "succeeded"},),
    )

    assert evidence.get("policy_completed") is True
    assert evidence["success"] is True
    assert dict(evidence) == {"success": True, "policy_completed": True}
