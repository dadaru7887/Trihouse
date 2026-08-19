"""FMS Gateway command-claim API의 작은 동기 HTTP client."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class CommandClaimError(RuntimeError):
    """FMS가 RMF 실행에 대응하는 유효한 TaskContext를 발급하지 못했다."""


@dataclass(frozen=True)
class ClaimedTaskContext:
    active: bool
    job_id: int
    job_step_id: int
    assignment_revision: int
    rmf_task_id: str
    command_id: str
    map_revision: str
    command_source: str
    # 도착 뒤 인계가 이어지는지. 원장이 알려 준다.
    handover_expected: bool = False


def _parse_context(payload: dict[str, Any]) -> ClaimedTaskContext:
    raw = payload.get("task_context")
    required = (
        "active", "job_id", "job_step_id", "assignment_revision",
        "rmf_task_id", "command_id", "map_revision", "command_source",
    )
    if not isinstance(raw, dict) or any(key not in raw for key in required):
        raise CommandClaimError("FMS command claim 응답에 TaskContext가 없습니다.")
    try:
        context = ClaimedTaskContext(
            active=bool(raw["active"]),
            job_id=int(raw["job_id"]),
            job_step_id=int(raw["job_step_id"]),
            assignment_revision=int(raw["assignment_revision"]),
            rmf_task_id=str(raw["rmf_task_id"]),
            command_id=str(raw["command_id"]),
            map_revision=str(raw["map_revision"]),
            command_source=str(raw["command_source"]),
            # task_context 바깥에 있다 — 문맥이 아니라 이 명령에 대한 지시다.
            # 옛 Gateway 는 이 필드를 주지 않으므로 없으면 거짓으로 둔다.
            handover_expected=bool(payload.get("handover_expected", False)),
        )
    except (TypeError, ValueError) as error:
        raise CommandClaimError("FMS TaskContext 타입이 올바르지 않습니다.") from error
    if (
        not context.active
        or context.job_id <= 0
        or context.job_step_id <= 0
        or context.assignment_revision <= 0
        or not all((context.rmf_task_id, context.command_id,
                    context.map_revision, context.command_source))
    ):
        raise CommandClaimError("FMS TaskContext 불변식이 충족되지 않았습니다.")
    return context


class FmsCommandClaimClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 2.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._opener = opener

    def claim(
        self,
        *,
        rmf_task_id: str,
        robot_id: str,
        execution_id: str,
        map_revision: str,
    ) -> ClaimedTaskContext:
        if not all((rmf_task_id, robot_id, execution_id, map_revision)):
            raise CommandClaimError("command claim 식별자는 빈 값일 수 없습니다.")
        path_task_id = quote(rmf_task_id, safe="")
        body = json.dumps({
            "robot_id": robot_id,
            "execution_id": execution_id,
            "map_revision": map_revision,
        }).encode("utf-8")
        request = Request(
            f"{self._base_url}/internal/v1/rmf/tasks/{path_task_id}/commands/claim",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            raise CommandClaimError(f"FMS command claim 실패: {error}") from error
        if not isinstance(payload, dict):
            raise CommandClaimError("FMS command claim 응답은 JSON 객체여야 합니다.")
        return _parse_context(payload)
