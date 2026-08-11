"""SR-28·SR-29 작업 상태와 실행 시도 이력의 MySQL 계약 테스트."""

import re
from pathlib import Path


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "db" / "schema_mysql.sql"
SEED_PATH = Path(__file__).resolve().parents[2] / "db" / "seed_dev.sql"


def _table(schema: str, name: str) -> str:
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS {name} \((.*?)\n\) ENGINE=InnoDB",
        schema,
        re.DOTALL,
    )
    assert match is not None, f"missing table: {name}"
    return match.group(1)


def test_current_job_and_step_states_match_the_domain_model() -> None:
    """과거 planning/blocked/held-step 값이 새 상태 모델에 다시 섞이지 않게 한다."""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    jobs = _table(schema, "jobs")
    steps = _table(schema, "job_steps")

    assert re.search(
        r"chk_jobs_state CHECK \(state IN\s*\(\s*'queued','assigned','running','held','completed','failed',\s*'cancelled'\s*\)\)",
        jobs,
    )
    assert re.search(
        r"chk_job_steps_state CHECK \(state IN\s*\(\s*'pending','running','succeeded','failed','cancelled'\s*\)\)",
        steps,
    )
    assert "assignment_revision" in steps
    assert "final_outcome_reason_code" in steps
    assert "final_method_code" in steps


def test_attempt_history_keeps_structured_success_failure_and_lineage() -> None:
    """completed/failed 한 단어만 저장하는 빈약한 학습 기록으로 회귀하지 않게 한다."""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    attempts = _table(schema, "job_step_attempts")

    required_columns = {
        "attempt_uuid",
        "job_step_id",
        "assignment_revision",
        "actor_role",
        "actor_device_id",
        "attempt_no",
        "event_uuid",
        "command_uuid",
        "state",
        "outcome",
        "success",
        "method_code",
        "selection_reason_code",
        "outcome_reason_code",
        "failure_domain",
        "detail",
        "parameters",
        "criteria",
        "metrics",
        "before_observation",
        "after_observation",
        "evidence_refs",
        "policy_source",
        "policy_name",
        "policy_version",
        "model_name",
        "model_version",
        "data_quality_status",
        "started_at",
        "completed_at",
    }
    actual_columns = set(
        re.findall(r"^\s{2}([a-z][a-z0-9_]*)\s+[A-Z]", attempts, re.MULTILINE)
    )

    assert required_columns <= actual_columns
    assert "UNIQUE KEY uq_attempts_event (event_uuid)" in attempts
    assert "UNIQUE KEY uq_attempts_command (command_uuid)" in attempts
    assert "UNIQUE KEY uq_attempts_sequence" in attempts
    assert "(job_step_id, assignment_revision, actor_role, attempt_no)" in attempts
    assert "chk_attempts_terminal" in attempts


def test_audit_correlation_and_transactional_outbox_dedupe_remain_available() -> None:
    """실행 이력과 감사 이벤트를 잇고 외부 명령 생성 중복을 막는 키를 보장한다."""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    events = _table(schema, "operation_events")
    messages = _table(schema, "integration_messages")

    assert "correlation_uuid" in events
    assert "causation_event_uuid" in events
    assert "attempt_uuid" in events
    assert "UNIQUE KEY uq_messages_dedupe (direction, channel, idempotency_key)" in messages


def test_development_seed_uses_a_job_state_allowed_by_the_new_schema() -> None:
    """일회용 MySQL 초기화가 과거 pending job 값 때문에 실패하지 않게 한다."""
    seed = SEED_PATH.read_text(encoding="utf-8")

    assert "('JOB-DEV-001', 'outbound', 'normal', 'queued'" in seed
