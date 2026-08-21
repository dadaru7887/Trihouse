"""FastAPI routes owned by the recovery learning boundary."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from .recovery_models import RecoveryStepAcknowledgement, RecoveryStepCompletion
from .recovery_repository import (
    RecoveryIdempotencyConflict,
    RecoveryRepository,
    RecoveryStepConflict,
    RecoveryStepNotFound,
)
from .recovery_export import iter_training_jsonl


def recovery_router(repository: RecoveryRepository) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/internal/v1/recovery/episodes/{episode_uuid}/steps/{step_no}/complete",
        response_model=RecoveryStepAcknowledgement,
    )
    def complete_recovery_step(
        episode_uuid: str,
        step_no: int,
        completion: RecoveryStepCompletion,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        payload = completion.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        try:
            return repository.complete_recovery_step(
                episode_uuid, step_no, payload, str(idempotency_key), digest
            )
        except RecoveryStepNotFound as exc:
            raise HTTPException(status_code=404, detail="recovery step not found") from exc
        except RecoveryIdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail="idempotency key payload conflict") from exc
        except RecoveryStepConflict as exc:
            raise HTTPException(status_code=409, detail="recovery step cannot be completed") from exc

    @router.get("/internal/v1/recovery/training-export.jsonl")
    def export_recovery_training_data() -> StreamingResponse:
        return StreamingResponse(
            iter_training_jsonl(repository.list_training_rows()),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": "attachment; filename=recovery.jsonl"},
        )

    return router
