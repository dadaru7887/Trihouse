from __future__ import annotations

from trihouse_omx_adapter.simulation_profile import feedback_event, sample_phase


def test_feedback_event_carries_execution_identity_and_motion_evidence() -> None:
    command = {
        "omx_id": "OMX_02",
        "job_id": "job-7",
        "job_step_id": "step-9",
        "handover_group_id": "handover-3",
        "pinky_id": "PINKY_01",
    }

    event = feedback_event(command, sample_phase(8.0), joint_state_stamp_ns=123456)

    assert event == {
        "schema_version": "v1",
        **command,
        "phase": "loading",
        "phase_elapsed_s": 0.5,
        "total_elapsed_s": 8.0,
        "progress": 8.0 / 15.0 * 100.0,
        "joint_state_stamp_ns": 123456,
        "trajectory_tracking": True,
    }

