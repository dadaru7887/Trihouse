"""1번 인터페이스(로봇팔 임무 완료 상태값).

실제로는 POST /internal/v1/job-steps/{job_step_id}/outcome (control_tower의
StepOutcomeRequest와 동일한 필드: outcome, assignment_revision, method_code,
actor_device_id, reason_code, metrics)로 나가야 한다. deliver.py/store.py를
CLI로 손으로 돌릴 때는 여전히 로컬 JSONL 로그로만 남는다 — `gateway`를 넘기지
않으면(기본값) 이 함수는 지금까지와 100% 동일하게 동작한다.

`gateway`를 넘기면(job_loop.py가 실제로 이렇게 쓴다) 같은 필드를 그대로
control_tower.gateway.fms_client.StepOutcomeRequest로 변환해 실제 Gateway에도
보고한다 — 로컬 JSONL 기록은 그때도 계속 남는다(감사 로그). HTTP 호출이
실패하면 예외를 그대로 올린다(삼키지 않음) — 호출부가 사이클 단위로 잡아서
처리하게 둔다(job_loop.py의 catch-log-continue 참고).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

DEFAULT_LOG_PATH = Path(__file__).resolve().parent / "var" / "outcomes.jsonl"


class ExecutorGatewayClient(Protocol):
    """control_tower.gateway.fms_client.ExecutorGatewayClient와 같은 모양.

    실제 타입을 import하지 않고 구조적 타입(Protocol)으로만 받는다 — 이 파일이
    control_tower에 대한 import-time 의존성을 갖지 않게 하기 위해서다(호출자,
    즉 job_loop.py만 실제로 import한다).
    """

    def record_executor_outcome(
        self, job_step_id: int, request: Any, *, idempotency_key: str
    ) -> Any: ...


@dataclass(frozen=True)
class StepOutcome:
    """control_tower/gateway/fms_client.py의 StepOutcomeRequest와 필드를 맞춘 로컬 스텁."""

    job_step_id: int
    outcome: Literal["succeeded", "failed"]
    assignment_revision: int
    method_code: str
    actor_device_id: str
    reason_code: str
    detail: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    reported_at: float = field(default_factory=time.time)


def report_outcome(
    outcome: StepOutcome,
    *,
    log_path: Path = DEFAULT_LOG_PATH,
    gateway: ExecutorGatewayClient | None = None,
    worker_id: str = "trihouse-omx",
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(asdict(outcome), ensure_ascii=False)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(f"[outcome] job_step_id={outcome.job_step_id} outcome={outcome.outcome} "
          f"reason={outcome.reason_code} detail={outcome.detail!r}")

    if gateway is None:
        return

    import sys

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from control_tower.gateway.fms_client import StepOutcomeRequest

    request = StepOutcomeRequest(
        outcome=outcome.outcome,
        assignment_revision=outcome.assignment_revision,
        method_code=outcome.method_code,
        actor_device_id=outcome.actor_device_id,
        reason_code=outcome.reason_code,
        detail=outcome.detail or None,
        metrics=outcome.metrics,
    )
    idempotency_key = f"{worker_id}-step-{outcome.job_step_id}-rev-{outcome.assignment_revision}"
    gateway.record_executor_outcome(outcome.job_step_id, request, idempotency_key=idempotency_key)
