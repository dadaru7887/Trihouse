"""작업 수명주기와 단계 실행 상태를 분리하는 StageEngine 테스트."""

import pytest

from control_tower.task_manager.stage_engine import JobState, StageEngine, StageState


def _engine() -> StageEngine:
    engine = StageEngine()
    engine.create("job-1", stages=("PICK", "LOAD"))
    return engine


def test_assign_and_start_are_explicit_transitions() -> None:
    """생성만 된 작업을 실행 중으로 오인해 로봇 명령을 보내지 못하게 한다."""
    engine = _engine()

    assert engine.state_of("job-1") is JobState.QUEUED
    assert engine.stage_state("job-1", "PICK") is StageState.PENDING
    engine.assign("job-1")
    assert engine.state_of("job-1") is JobState.ASSIGNED
    assert engine.start("job-1") == "PICK"
    assert engine.state_of("job-1") is JobState.RUNNING
    assert engine.stage_state("job-1", "PICK") is StageState.RUNNING


def test_matching_completion_advances_once_and_leaves_next_step_pending() -> None:
    """중복 완료가 다음 단계를 건너뛰거나 자동 실행하는 회귀를 막는다."""
    engine = _engine()
    engine.assign("job-1")
    engine.start("job-1")

    assert engine.complete("job-1", stage_id="PICK", result_id="event-1") is True
    assert engine.complete("job-1", stage_id="PICK", result_id="event-1") is False
    assert engine.stage_state("job-1", "PICK") is StageState.SUCCEEDED
    assert engine.current_stage("job-1") == "LOAD"
    assert engine.stage_state("job-1", "LOAD") is StageState.PENDING


def test_hold_and_resume_preserve_the_running_step() -> None:
    """일시정지 해제 시 완료되지 않은 단계가 초기화되는 회귀를 막는다."""
    engine = _engine()
    engine.assign("job-1")
    engine.start("job-1")

    engine.hold("job-1", reason="operator check")
    assert engine.state_of("job-1") is JobState.HELD
    assert engine.stage_state("job-1", "PICK") is StageState.RUNNING
    engine.resume("job-1")

    assert engine.state_of("job-1") is JobState.RUNNING
    assert engine.current_stage("job-1") == "PICK"
    assert engine.stage_state("job-1", "PICK") is StageState.RUNNING


def test_failure_and_cancellation_align_job_and_current_step_terminal_states() -> None:
    """작업과 단계의 terminal 상태가 서로 모순되는 저장을 막는다."""
    failed = _engine()
    failed.assign("job-1")
    failed.start("job-1")
    failed.fail("job-1", stage_id="PICK", reason="GRASP_FAILED")

    assert failed.state_of("job-1") is JobState.FAILED
    assert failed.stage_state("job-1", "PICK") is StageState.FAILED

    cancelled = _engine()
    cancelled.assign("job-1")
    cancelled.cancel("job-1")

    assert cancelled.state_of("job-1") is JobState.CANCELLED
    assert cancelled.stage_state("job-1", "PICK") is StageState.CANCELLED


def test_final_completion_marks_job_completed() -> None:
    """마지막 단계 전에는 전체 작업 완료가 되지 않도록 보장한다."""
    engine = _engine()
    engine.assign("job-1")
    engine.start("job-1")
    engine.complete("job-1", stage_id="PICK", result_id="pick-done")
    engine.start("job-1")
    engine.complete("job-1", stage_id="LOAD", result_id="load-done")

    assert engine.state_of("job-1") is JobState.COMPLETED
    assert engine.stage_state("job-1", "LOAD") is StageState.SUCCEEDED
    assert engine.current_stage("job-1") is None


def test_invalid_transition_is_rejected_instead_of_rewriting_history() -> None:
    """미배정 작업 실행과 terminal 작업 재개를 허용하는 회귀를 막는다."""
    engine = _engine()

    with pytest.raises(ValueError, match="assigned"):
        engine.start("job-1")
    engine.cancel("job-1")
    with pytest.raises(ValueError, match="held"):
        engine.resume("job-1")
