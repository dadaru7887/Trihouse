"""FastAPI routes owned by the recovery learning boundary."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from .recovery_models import (
    RecoveryProposalCreate,
    RecoveryProposalDecision,
    RecoveryStepAcknowledgement,
    RecoveryStepCompletion,
)
from .recovery_repository import (
    RecoveryApprovalForbidden,
    RecoveryIdempotencyConflict,
    RecoveryProposalConflict,
    RecoveryProposalNotFound,
    RecoveryRepository,
    RecoveryStepConflict,
    RecoveryStepNotFound,
)
from .recovery_export import iter_training_jsonl


def recovery_router(repository: RecoveryRepository) -> APIRouter:
    router = APIRouter()

    @router.post("/internal/v1/recovery/proposals", status_code=201)
    def create_recovery_proposal(
        proposal: RecoveryProposalCreate,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        payload = proposal.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        try:
            return repository.create_proposal(payload, str(idempotency_key), digest)
        except RecoveryProposalConflict as exc:
            raise HTTPException(status_code=409, detail="recovery proposal conflict") from exc

    @router.post("/api/v1/recovery/proposals/{proposal_id}/decision")
    def decide_recovery_proposal(
        proposal_id: UUID,
        request: RecoveryProposalDecision,
    ) -> dict[str, object]:
        try:
            return repository.decide_proposal(
                str(proposal_id), request.worker_id, request.decision, request.reason
            )
        except RecoveryProposalNotFound as exc:
            raise HTTPException(status_code=404, detail="recovery proposal not found") from exc
        except RecoveryApprovalForbidden as exc:
            raise HTTPException(status_code=403, detail="safety_manager role required") from exc
        except RecoveryProposalConflict as exc:
            raise HTTPException(status_code=409, detail="recovery proposal decision conflict") from exc

    @router.get("/internal/v1/recovery/proposals/{proposal_id}/execution")
    def get_recovery_execution(proposal_id: UUID) -> dict[str, object]:
        try:
            return repository.get_proposal_execution(str(proposal_id))
        except RecoveryProposalNotFound as exc:
            raise HTTPException(status_code=404, detail="recovery proposal not found") from exc

    @router.get("/internal/v1/recovery/devices/{device_id}/open")
    def list_open_recoveries(device_id: str) -> list[dict[str, object]]:
        return repository.list_open_recoveries(device_id)

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
