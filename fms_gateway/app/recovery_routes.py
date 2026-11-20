"""FastAPI routes owned by the recovery learning boundary."""

from __future__ import annotations

import hashlib
import json
import logging
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
from .recovery_autoapproval import classify
from .recovery_export import iter_training_jsonl


logger = logging.getLogger(__name__)


def recovery_router(repository: RecoveryRepository) -> APIRouter:
    router = APIRouter()

    @router.post("/internal/v1/recovery/proposals", status_code=201)
    def create_recovery_proposal(
        proposal: RecoveryProposalCreate,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        """Store the proposal, then let the bounded policy decide it if it may.

        The unexpected situations this system exists for happen where nobody is
        standing by, so waiting for a person is itself a failure mode. The policy
        only decides *whether to try*; the robot still refuses the command if the
        path is not clear, and the safety supervisor still stops it mid-motion.
        """
        payload = proposal.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        try:
            created = repository.create_proposal(payload, str(idempotency_key), digest)
        except RecoveryProposalConflict as exc:
            raise HTTPException(status_code=409, detail="recovery proposal conflict") from exc
        if created.get("status") != "pending":
            return created
        if payload["policy_lineage"].get("execution_mode") != "auto_bounded":
            # operator_approved (또는 모드를 밝히지 않은 런타임): 전 건 사람이 결정한다.
            return created
        # Attempts during this stop, counted by the 5080 (every proposal is its own episode).
        attempt_no = int(payload["policy_lineage"].get("attempt_no") or payload.get("step_no", 1))
        verdict = classify(payload, attempt_no=attempt_no)
        created["decision_tier"] = verdict.tier
        created["decision_reason"] = verdict.reason
        created["requires_operator"] = verdict.requires_operator
        if verdict.notify:
            # 알림이 실패해도 복구 판단은 계속되어야 한다. 관제에 못 알렸다는 이유로
            # 로봇을 멈춰 세우면, 정작 알려야 할 상황에서 아무 일도 안 하게 된다.
            try:
                repository.record_recovery_notice(
                    payload, verdict.tier, verdict.reason,
                    requires_operator=verdict.requires_operator,
                )
            except Exception:
                logger.exception("recovery notice could not be recorded")
        if not verdict.approve:
            # tier C 는 실패가 아니라 정상 경로다. 로봇은 안전 정지 상태로 남고,
            # 제안은 만료 시각까지 관제의 판단을 기다린다.
            return created
        try:
            decided = repository.auto_decide_proposal(
                created["proposal_id"], verdict.tier, verdict.reason
            )
        except (RecoveryProposalNotFound, RecoveryProposalConflict):
            # 그 사이 사람이 이미 결정했거나 제안이 만료됐다. 사람의 결정이 이긴다.
            return created
        return {**created, **decided}

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
