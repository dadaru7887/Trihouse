"""소요시간 예측·실측·보정을 담는 스키마 계약.

이 파일이 지키는 것은 두 가지다. 하나는 "예측을 저장하지 않으면 오차를 영원히
계산할 수 없다"는 사실이고, 다른 하나는 새 테이블이 **어느 데이터베이스에**
생기는지다. 스키마 중간에 `USE trihouse_recovery` 로 대상이 바뀌기 때문에,
파일 끝에 테이블을 붙이면 조용히 다른 DB 로 들어간다. 실제로 그렇게 만들었다가
잡았다.
"""

import os
import re
from pathlib import Path

import mysql.connector
import pytest


CHECK_CONSTRAINT_VIOLATED = 3819
DUPLICATE_KEY = 1062


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPOSITORY_ROOT / "db" / "migrations" / "001_physical_v1_baseline.sql"
MIGRATION_PATH = (
    REPOSITORY_ROOT / "db" / "archive" / "pre_physical_v1"
    / "012_add_duration_prediction_and_baselines.sql"
)
TEST_DATABASE = "trihouse_duration_baseline_test"


def _table(schema: str, name: str) -> str:
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS {name} \((.*?)\n\) ENGINE=InnoDB",
        schema,
        re.DOTALL,
    )
    assert match is not None, f"missing table: {name}"
    return match.group(1)


def _connect(database: str | None = None):
    options: dict[str, object] = {
        "host": os.environ.get("FMS_DB_HOST", "127.0.0.1"),
        "port": int(os.environ.get("FMS_DB_PORT", "3307")),
        "user": os.environ.get("FMS_DB_ADMIN_USER", "root"),
        "password": os.environ.get("FMS_DB_ADMIN_PASSWORD", "test_root_password"),
        "autocommit": True,
    }
    if database is not None:
        options["database"] = database
    return mysql.connector.connect(**options)


def _execute_script(connection, sql: str) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute(sql)
        while cursor.nextset():
            pass
    finally:
        cursor.close()


# 정적 검사 -----------------------------------------------------------------


def test_a_dispatched_step_can_record_what_it_was_expected_to_take() -> None:
    """예측을 남기지 않으면 실측이 아무리 쌓여도 오차를 만들 수 없다."""
    steps = _table(SCHEMA_PATH.read_text(encoding="utf-8"), "job_steps")

    assert "predicted_duration_ms" in steps
    assert "prediction_source" in steps
    assert "predicted_at" in steps
    # 셋은 함께 있거나 함께 없어야 한다. 예측값만 있고 출처가 없으면 나중에
    # 그 숫자를 신뢰해도 되는지 판단할 근거가 사라진다.
    assert "chk_job_steps_prediction" in steps


def test_measured_duration_is_projected_for_aggregation() -> None:
    """구간 분해는 JSON 에 두되, 집계가 쓰는 값은 인덱스를 탈 수 있어야 한다."""
    attempts = _table(SCHEMA_PATH.read_text(encoding="utf-8"), "job_step_attempts")

    for column in ("metric_total_ms", "metric_environment", "metric_scope_key"):
        assert column in attempts
        assert f"{column} " in attempts
    assert "GENERATED ALWAYS AS" in attempts
    assert "idx_attempts_calibration" in attempts


def test_the_baseline_table_lives_in_the_fms_database() -> None:
    """스키마 중간에 `USE trihouse_recovery` 가 있다. 그 뒤에 붙으면 다른 DB 다."""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")

    baseline_at = schema.index("CREATE TABLE IF NOT EXISTS duration_baselines")
    recovery_at = schema.index("USE `trihouse_recovery`")

    assert baseline_at < recovery_at


def test_scheduling_only_ever_reads_an_approved_baseline() -> None:
    """집계가 곧바로 일정을 바꾸면 창고가 조용히 자기 시간을 다시 쓴다."""
    baselines = _table(SCHEMA_PATH.read_text(encoding="utf-8"), "duration_baselines")

    assert "chk_baseline_state" in baselines
    assert "chk_baseline_approval" in baselines
    assert "chk_baseline_environment" in baselines


# 실제 MySQL 계약 -----------------------------------------------------------


@pytest.fixture
def database():
    admin = _connect()
    try:
        _execute_script(admin, f"DROP DATABASE IF EXISTS `{TEST_DATABASE}`")
        _execute_script(admin, f"CREATE DATABASE `{TEST_DATABASE}`")
    finally:
        admin.close()
    schema = SCHEMA_PATH.read_text(encoding="utf-8").replace(
        "`trihouse_fms`", f"`{TEST_DATABASE}`"
    )
    connection = _connect(TEST_DATABASE)
    _execute_script(connection, schema)
    # 스키마 마지막이 `USE trihouse_recovery` 라 세션의 현재 DB 가 바뀐다.
    # 되돌리지 않으면 이후 INSERT 가 엉뚱한 DB 로 가고, 그 실패가 제약 위반처럼
    # 보여 검사가 거짓으로 통과한다.
    _execute_script(connection, f"USE `{TEST_DATABASE}`")
    try:
        yield connection
    finally:
        connection.close()
        admin = _connect()
        try:
            _execute_script(admin, f"DROP DATABASE IF EXISTS `{TEST_DATABASE}`")
        finally:
            admin.close()


def _insert_baseline(connection, **overrides) -> None:
    row = {
        "scope_kind": "pick",
        "scope_key": "zone=frozen",
        "environment": "simulation",
        "origin": "aggregated",
        "sample_count": 30,
        "p50_ms": 4000,
        "p90_ms": 7000,
        "state": "proposed",
        "approved_by": None,
        "approved_at": None,
    }
    row.update(overrides)
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO duration_baselines
              (scope_kind, scope_key, environment, origin, sample_count,
               p50_ms, p90_ms, state, approved_by, approved_at)
            VALUES (%(scope_kind)s, %(scope_key)s, %(environment)s, %(origin)s,
                    %(sample_count)s, %(p50_ms)s, %(p90_ms)s, %(state)s,
                    %(approved_by)s, %(approved_at)s)
            """,
            row,
        )
    finally:
        cursor.close()


def test_the_full_schema_creates_the_baseline_table_in_this_database(database) -> None:
    cursor = database.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=%s AND TABLE_NAME='duration_baselines'",
            (TEST_DATABASE,),
        )
        assert cursor.fetchone()[0] == 1
    finally:
        cursor.close()


def test_an_approved_baseline_must_name_who_approved_it(database) -> None:
    """승인이 스케줄링의 신뢰 근거이므로 익명 승인은 받지 않는다."""
    with pytest.raises(mysql.connector.Error) as error:
        _insert_baseline(database, state="approved")

    assert error.value.errno == CHECK_CONSTRAINT_VIOLATED



def test_an_aggregated_baseline_without_samples_is_rejected(database) -> None:
    """표본 없는 집계값은 실측이 아니라 지어낸 숫자다."""
    with pytest.raises(mysql.connector.Error) as error:
        _insert_baseline(database, origin="aggregated", sample_count=0)

    assert error.value.errno == CHECK_CONSTRAINT_VIOLATED



def test_an_operator_seed_may_have_no_samples(database) -> None:
    """콜드 스타트에는 사람이 잰 값밖에 없다. 그건 허용해야 한다."""
    _insert_baseline(database, origin="seed", sample_count=0, note="tape measure")


def test_percentiles_must_be_ordered(database) -> None:
    with pytest.raises(mysql.connector.Error) as error:
        _insert_baseline(database, p50_ms=9000, p90_ms=1000)

    assert error.value.errno == CHECK_CONSTRAINT_VIOLATED



def test_a_simulated_sample_never_lands_in_the_hardware_scope(database) -> None:
    """RTF 가 1 이 아닌 시뮬레이션 시간으로 실물 일정을 보정하면 안 된다."""
    _insert_baseline(database, environment="simulation", state="proposed")
    _insert_baseline(database, environment="hardware", state="proposed", revision=1)

    cursor = database.cursor()
    try:
        cursor.execute(
            "SELECT environment, COUNT(*) FROM duration_baselines GROUP BY environment"
        )
        assert dict(cursor.fetchall()) == {"simulation": 1, "hardware": 1}
    finally:
        cursor.close()


def test_an_unknown_environment_is_rejected(database) -> None:
    with pytest.raises(mysql.connector.Error) as error:
        _insert_baseline(database, environment="staging")

    assert error.value.errno == CHECK_CONSTRAINT_VIOLATED



def test_recalibrating_the_same_scope_needs_a_new_revision(database) -> None:
    _insert_baseline(database, revision=1)

    with pytest.raises(mysql.connector.Error) as error:
        _insert_baseline(database, revision=1)

    assert error.value.errno == DUPLICATE_KEY
