import hashlib
import json

import pytest
from pydantic import ValidationError

from fms_gateway.app.main import create_app
from fms_gateway.app.recovery_repository import InMemoryRecoveryRepository
from fms_gateway.app.repositories import InMemoryFmsRepository


EPISODE = "11111111-1111-4111-8111-111111111111"
MESSAGE = "22222222-2222-4222-8222-222222222222"


def payload() -> dict:
    return {
        "execution_status": "succeeded",
        "outcome_class": "safe",
        "completed_at": "2026-08-22T16:00:01+09:00",
        "is_terminal": True,
        "reward_components": {"progress": 0.2, "clearance_cost": 0.0},
        "transition": {
            "schema_version": 1,
            "state": [0.0] * 9,
            "skill": 4,
            "skill_name": "REJOIN",
            "coord": [0.1, 0.0, 0.0],
            "reward": 0.2,
            "next_state": [0.1] + [0.0] * 8,
            "done": True,
            "meta": {"is_execution": True},
        },
    }


def repository():
    recovery = InMemoryRecoveryRepository()
    recovery.add_running_step(EPISODE, 1)
    return recovery


def test_completed_execution_is_acknowledged_and_idempotent() -> None:
    from fms_gateway.app.recovery_models import RecoveryStepCompletion

    recovery = repository()
    body = RecoveryStepCompletion.model_validate(payload()).model_dump(mode="json")
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    first = recovery.complete_recovery_step(EPISODE, 1, body, MESSAGE, digest)
    repeated = recovery.complete_recovery_step(EPISODE, 1, body, MESSAGE, digest)
    assert repeated == first
    assert first["acknowledged"] is True
    assert len(recovery.transitions) == 1


def test_wrong_dimensions_skill_pair_and_nonexecution_are_rejected() -> None:
    from fms_gateway.app.recovery_models import RecoveryStepCompletion

    for index, mutate in enumerate((
        lambda body: body["transition"].update(state=[0.0] * 8),
        lambda body: body["transition"].update(skill_name="BACKUP"),
        lambda body: body["transition"]["meta"].update(is_execution=False),
        lambda body: body["transition"].update(reward="NaN"),
    )):
        body = payload()
        mutate(body)
        with pytest.raises(ValidationError):
            RecoveryStepCompletion.model_validate(body)


def test_done_must_match_the_final_episode_step() -> None:
    from fms_gateway.app.recovery_models import RecoveryStepCompletion

    body = payload()
    body["is_terminal"] = False
    with pytest.raises(ValidationError, match="final episode step"):
        RecoveryStepCompletion.model_validate(body)


def test_same_message_with_different_payload_conflicts() -> None:
    from fms_gateway.app.recovery_models import RecoveryStepCompletion
    from fms_gateway.app.recovery_repository import RecoveryIdempotencyConflict

    recovery = repository()
    body = RecoveryStepCompletion.model_validate(payload()).model_dump(mode="json")
    recovery.complete_recovery_step(EPISODE, 1, body, MESSAGE, "a" * 64)
    with pytest.raises(RecoveryIdempotencyConflict):
        recovery.complete_recovery_step(EPISODE, 1, body, MESSAGE, "b" * 64)


def test_recovery_route_is_registered_on_the_gateway_app() -> None:
    app = create_app(InMemoryFmsRepository(), recovery_repository=repository())
    paths = {getattr(route, "path", None) for route in app.routes}
    for route in app.routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            paths.update(getattr(child, "path", None) for child in included.routes)
    assert "/internal/v1/recovery/episodes/{episode_uuid}/steps/{step_no}/complete" in paths
    assert "/internal/v1/recovery/training-export.jsonl" in paths
