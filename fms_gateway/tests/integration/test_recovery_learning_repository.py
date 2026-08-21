from contextlib import contextmanager
from datetime import datetime

import pytest

from conftest import mysql_connection
from fms_gateway.app.recovery_repository import MySqlRecoveryRepository


pytestmark = pytest.mark.integration
EPISODE = "44444444-4444-4444-8444-444444444444"
MESSAGE = "55555555-5555-4555-8555-555555555555"


class TestDatabase:
    @contextmanager
    def connection(self):
        connection = mysql_connection(database="trihouse_fms")
        try:
            yield connection
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()


def completion() -> dict:
    return {
        "execution_status": "succeeded", "outcome_class": "safe",
        "completed_at": datetime(2026, 8, 22, 16, 0, 1), "is_terminal": True,
        "reward_components": {"progress": 0.2},
        "transition": {
            "schema_version": 1, "state": [0.0] * 9,
            "skill": 4, "skill_name": "REJOIN", "coord": [0.1, 0.0, 0.0],
            "reward": 0.2, "next_state": [0.1] + [0.0] * 8,
            "done": True, "meta": {"is_execution": True},
        },
    }


def test_completion_atomically_records_one_transition_and_replay_safe_receipt(recovery_mysql_db):
    recovery_mysql_db.execute(
        """
        INSERT INTO recovery_episodes
          (recovery_episode_uuid, device_id, map_name, map_revision, trigger_type,
           recovery_policy_name, recovery_policy_version, started_at)
        VALUES (%s, 'PK_01', 'new_map_2', 'rev-1', 'blocked', 'tgrpo-sac', '1',
                '2026-08-22 16:00:00')
        """, (EPISODE,),
    )
    recovery_mysql_db.execute(
        """
        INSERT INTO recovery_steps
          (recovery_episode_uuid, step_no, action_type, outcome_class,
           execution_status, started_at)
        VALUES (%s, 1, 'rejoin', 'safe', 'running', '2026-08-22 16:00:00')
        """, (EPISODE,),
    )
    recovery_mysql_db.connection.commit()
    repository = MySqlRecoveryRepository(TestDatabase())
    first = repository.complete_recovery_step(EPISODE, 1, completion(), MESSAGE, "a" * 64)
    repeated = repository.complete_recovery_step(EPISODE, 1, completion(), MESSAGE, "a" * 64)
    assert repeated == first
    assert recovery_mysql_db.one("SELECT COUNT(*) AS count FROM recovery_learning_transitions")["count"] == 1
    assert recovery_mysql_db.one("SELECT COUNT(*) AS count FROM recovery_ingestion_receipts")["count"] == 1
    assert recovery_mysql_db.one(
        "SELECT final_status FROM recovery_episodes WHERE recovery_episode_uuid=%s", (EPISODE,)
    )["final_status"] == "succeeded"
    exported = repository.list_training_rows()
    assert len(exported) == 1
    assert exported[0]["skill_id"] == 4
    assert exported[0]["device_id"] == "PK_01"
