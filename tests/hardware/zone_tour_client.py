"""상온·냉장·냉동 창고를 한 번씩 돌고 충전소로 복귀하는 실물 순회 시험 client.

`narrow_zone_client.py`가 창고 한 곳의 협로 규칙을 ROS action으로 직접 보정한다면,
이 module은 공개 주문 API **한 건**으로 세 온도 구역을 계획 순서대로 방문시키고
마지막 충전소 복귀까지 원장에서 확인한다. 여기에는 ROS import가 없다. 로봇과의
연결은 다음 사슬이 맡고, 이 파일은 그 결과만 읽는다.

```text
FMS Gateway(주문) -> job runner(배정) -> RMF gateway worker(go_to_place)
-> pinky fleet adapter(ExecuteTransport) -> Pinky fleet_node -> Nav2
```

주행 전 gate는 두 가지를 본다. 첫째, 세 창고 목적지가 지금 설정에서 실제로 주행
가능한가(`nav_only` 또는 실측이 끝난 `narrow_dock`). 둘째, 배정될 로봇의 충전소
탈출 규칙이 실측됐는가. 하나라도 아니면 주문을 만들지 않는다.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import yaml


REPOSITORY = Path(__file__).resolve().parents[2]
# 협로 profile 파서와 증거 기록기는 실기 테스트가 이미 쓰는 것을 그대로 쓴다.
for _entry in (
    str(REPOSITORY / "trihouse_pinky" / "trihouse_pinky_docking"),
    str(Path(__file__).resolve().parent),
):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from trihouse_pinky_docking.narrow_zone import (  # noqa: E402
    ENTER,
    EXIT,
    NarrowZoneProfile,
    load_narrow_zones,
)
from narrow_zone_client import PersistentTrace  # noqa: E402


# 계획기(`control_tower/task_manager/outbound_planner.py`)가 정한 방문 순서다.
ZONE_ORDER = ("ambient", "chilled", "frozen")
DOCK_BY_ZONE = {
    "ambient": "ambient_storage_loading_dock_01",
    "chilled": "chilled_storage_loading_dock_01",
    "frozen": "frozen_storage_loading_dock_01",
}
# `control_tower/task_manager/job_runner.py`의 CHARGER_BY_MOBILE와 같은 짝이다.
CHARGER_BY_DEVICE = {
    "PK_01": "charging_station_01",
    "PK_02": "charging_station_02",
}
# `db/seeds/seed_hardware.sql`에 재고가 있고 구역이 서로 겹치지 않는 기본 품목.
DEFAULT_ZONE_ITEMS = {
    "ambient": "SKU-MANDARIN",
    "chilled": "SKU-YOGURT",
    "frozen": "SKU-ICEBAR",
}
TERMINAL_JOB_STATES = frozenset({"completed", "failed", "cancelled"})


class TourRequestError(ValueError):
    """사람이 준 옵션 자체가 잘못돼 주행을 시작할 수 없다."""


@dataclass(frozen=True)
class TourRequest:
    enable_motion: bool
    enable_full_stack: bool
    device_id: str
    zone_items: Mapping[str, str]
    packing_worker: str


@dataclass(frozen=True)
class ZoneRouting:
    """한 창고 목적지를 지금 설정으로 어떻게 갈 수 있는가."""

    zone: str
    destination_code: str
    mode: str
    reason_code: str

    @property
    def routable(self) -> bool:
        return self.reason_code == "READY"


@dataclass(frozen=True)
class TourGateDecision:
    allowed: bool
    reason_code: str
    reason: str
    routing: tuple[ZoneRouting, ...] = ()


@dataclass(frozen=True)
class TourResult:
    passed: bool
    reason_code: str
    message: str
    job_id: int | None
    job_state: str | None
    visited_zones: tuple[str, ...]
    trace_path: Path
    event_log_path: Path


def parse_zone_items(text: str) -> dict[str, str]:
    """`ambient=SKU-A,chilled=SKU-B,frozen=SKU-C` 형식을 구역별 품목으로 바꾼다."""
    if not text.strip():
        return dict(DEFAULT_ZONE_ITEMS)
    items: dict[str, str] = {}
    for chunk in text.split(","):
        zone, separator, product = chunk.partition("=")
        zone, product = zone.strip(), product.strip()
        if not separator or not zone or not product:
            raise TourRequestError(f"{chunk!r}는 zone=SKU 형식이 아니다")
        if zone not in ZONE_ORDER:
            raise TourRequestError(f"{zone!r}는 {ZONE_ORDER} 중 하나여야 한다")
        if zone in items:
            raise TourRequestError(f"{zone} 구역 품목이 두 번 지정됐다")
        items[zone] = product
    missing = [zone for zone in ZONE_ORDER if zone not in items]
    if missing:
        raise TourRequestError(f"{missing} 구역 품목이 없다")
    if len(set(items.values())) != len(items):
        raise TourRequestError("같은 품목을 두 구역에 쓸 수 없다")
    return items


def load_tour_profiles(path: Path, *, map_name: str) -> dict[str, NarrowZoneProfile]:
    return load_narrow_zones(
        yaml.safe_load(Path(path).read_text(encoding="utf-8")), map_name=map_name
    )


def zone_routing(profiles: Mapping[str, NarrowZoneProfile]) -> tuple[ZoneRouting, ...]:
    """세 창고를 지금 설정 그대로 갈 수 있는지 구역별로 판정한다.

    Fleet의 `select_approach`와 같은 순서로 본다. `approach_required`가 false면
    Nav2가 실측 waypoint까지 그대로 가고 협로 규칙은 실행되지 않는다. true면
    진입과 탈출 실측이 모두 끝난 profile만 통과한다. 진입만 준비된 상태로
    창고에 들여보내면 나올 방법이 없기 때문이다.
    """
    decisions = []
    for zone in ZONE_ORDER:
        destination = DOCK_BY_ZONE[zone]
        profile = profiles.get(destination)
        if profile is None:
            # 창고 목적지는 profile이 없으면 fleet가 NARROW_PROFILE_MISSING으로 거절한다.
            decisions.append(
                ZoneRouting(zone, destination, "unknown", "NARROW_PROFILE_MISSING")
            )
            continue
        if not profile.approach_required:
            decisions.append(ZoneRouting(zone, destination, "nav_only", "READY"))
            continue
        enter_code = profile.direction_readiness_code(ENTER)
        if enter_code != "READY":
            decisions.append(ZoneRouting(zone, destination, "narrow_dock", enter_code))
            continue
        exit_code = profile.direction_readiness_code(EXIT)
        decisions.append(
            ZoneRouting(zone, destination, "narrow_dock", exit_code)
        )
    return tuple(decisions)


def charger_exit_readiness(
    profiles: Mapping[str, NarrowZoneProfile], device_id: str
) -> str:
    """배정될 로봇이 충전소를 빠져나올 수 있는가."""
    destination = CHARGER_BY_DEVICE.get(device_id)
    if destination is None:
        return "DEVICE_CHARGER_UNKNOWN"
    profile = profiles.get(destination)
    if profile is None:
        return "CHARGER_PROFILE_MISSING"
    return profile.direction_readiness_code(EXIT)


def validate_tour_request(
    request: TourRequest, profiles: Mapping[str, NarrowZoneProfile]
) -> TourGateDecision:
    """주문을 만들기 전에 옵션과 실측 상태만으로 판정한다."""
    if not request.enable_full_stack:
        return TourGateDecision(
            False, "FULL_STACK_NOT_ENABLED", "--enable-full-stack이 없다"
        )
    if not request.enable_motion:
        return TourGateDecision(
            False, "MOTION_NOT_ENABLED", "순회 주행은 --enable-motion도 함께 지정한다"
        )
    if request.device_id not in CHARGER_BY_DEVICE:
        return TourGateDecision(
            False,
            "DEVICE_CHARGER_UNKNOWN",
            f"{request.device_id}의 고정 충전소가 없다",
        )
    missing = [zone for zone in ZONE_ORDER if not request.zone_items.get(zone)]
    if missing:
        return TourGateDecision(
            False, "ZONE_ITEM_MISSING", f"{missing} 구역 품목이 없다"
        )
    if not request.packing_worker.strip():
        return TourGateDecision(
            False, "PACKING_WORKER_MISSING", "포장 완료를 확인할 작업자 ID가 없다"
        )
    routing = zone_routing(profiles)
    blocked = [item for item in routing if not item.routable]
    if blocked:
        first = blocked[0]
        return TourGateDecision(
            False,
            first.reason_code,
            f"{first.destination_code}로 갈 수 없다: {first.reason_code}",
            routing,
        )
    charger_code = charger_exit_readiness(profiles, request.device_id)
    if charger_code != "READY":
        return TourGateDecision(
            False,
            charger_code,
            f"{CHARGER_BY_DEVICE[request.device_id]} 탈출 규칙이 준비되지 않았다",
            routing,
        )
    return TourGateDecision(
        True, "READY", "세 창고 목적지와 충전소 탈출이 모두 준비됐다", routing
    )


def tour_order_payload(
    zone_items: Mapping[str, str], *, run_id: str, requested_by: str
) -> dict[str, Any]:
    """한 Pinky가 세 구역을 도는 혼합 구역 주문 한 건."""
    return {
        "external_reference": f"ZONE-TOUR-{run_id}",
        "priority": "normal",
        "allow_partial_fulfillment": False,
        "requested_by": requested_by,
        "items": [
            {"product_code": zone_items[zone], "quantity": 1} for zone in ZONE_ORDER
        ],
    }


def _steps(job: Mapping[str, Any]) -> list[dict[str, Any]]:
    return sorted(job.get("steps") or [], key=lambda step: int(step["step_no"]))


def _zone_of(step: Mapping[str, Any]) -> str | None:
    value = step.get("input") or {}
    zone = value.get("temperature_zone")
    return str(zone) if zone else None


def zone_navigation_steps(job: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """구역별 Pinky 이동 step을 찾는다. 온도 구역은 step 번호가 아니라 input이 정한다."""
    found: dict[str, dict[str, Any]] = {}
    for step in _steps(job):
        zone = _zone_of(step)
        if (
            zone
            and step.get("executor_type") == "mobile"
            and step.get("action_type") == "navigate"
            and zone not in found
        ):
            found[zone] = dict(step)
    return found


def return_home_step(job: Mapping[str, Any]) -> dict[str, Any] | None:
    for step in _steps(job):
        if step.get("action_type") == "return_home":
            return dict(step)
    return None


def worker_completion_pending(job: Mapping[str, Any]) -> bool:
    """포장 인계 뒤 작업자 확인만 남았는가."""
    for step in _steps(job):
        if step.get("action_type") == "wait" and step.get("state") == "running":
            return True
    return False


def visited_zone_order(job: Mapping[str, Any]) -> tuple[str, ...]:
    """실제로 성공한 창고 이동을 step 순서대로 나열한다."""
    order = []
    for step in _steps(job):
        zone = _zone_of(step)
        if (
            zone
            and step.get("executor_type") == "mobile"
            and step.get("action_type") == "navigate"
            and step.get("state") == "succeeded"
            and zone not in order
        ):
            order.append(zone)
    return tuple(order)


def evaluate_tour(job: Mapping[str, Any] | None) -> dict[str, Any]:
    """세 창고 방문과 충전소 복귀를 원장 값만으로 판정한다."""
    if job is None:
        return {"passed": False, "reason_code": "NO_JOB", "visited": ()}
    navigations = zone_navigation_steps(job)
    for zone in ZONE_ORDER:
        step = navigations.get(zone)
        if step is None:
            return {
                "passed": False,
                "reason_code": f"ZONE_{zone.upper()}_STEP_MISSING",
                "visited": visited_zone_order(job),
            }
        state = str(step.get("state"))
        if state != "succeeded":
            return {
                "passed": False,
                "reason_code": f"ZONE_{zone.upper()}_{state.upper()}",
                "visited": visited_zone_order(job),
            }
    visited = visited_zone_order(job)
    if visited != ZONE_ORDER:
        return {
            "passed": False,
            "reason_code": "ZONE_ORDER_MISMATCH",
            "visited": visited,
        }
    home = return_home_step(job)
    if home is None:
        return {"passed": False, "reason_code": "RETURN_HOME_MISSING", "visited": visited}
    home_state = str(home.get("state"))
    if home_state != "succeeded":
        return {
            "passed": False,
            "reason_code": f"RETURN_HOME_{home_state.upper()}",
            "visited": visited,
        }
    job_state = str(job.get("state"))
    if job_state != "completed":
        return {
            "passed": False,
            "reason_code": f"JOB_{job_state.upper()}",
            "visited": visited,
        }
    return {"passed": True, "reason_code": "COMPLETED", "visited": visited}


def step_signature(job: Mapping[str, Any]) -> tuple:
    return (
        job.get("state"),
        tuple((step["step_no"], step["state"]) for step in _steps(job)),
    )


class GatewayClient:
    """FMS Gateway HTTP 경계. 실패는 그대로 올려 순회를 멈춘다."""

    def __init__(self, base_url: str, *, timeout_s: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        request = Request(
            f"{self.base_url}{path}", data=body, headers=headers, method=method
        )
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                raw = response.read().decode("utf-8")
                return response.status, json.loads(raw) if raw else {}
        except HTTPError as error:
            raw = error.read().decode("utf-8")
            return error.code, json.loads(raw) if raw else {}
        except (URLError, TimeoutError) as error:
            raise RuntimeError(f"Gateway 연결 실패 {path}: {error}") from error


class ZoneTourRunner:
    """주문 한 건을 만들고, 작업자 확인만 대신하고, 결과를 증거로 남긴다."""

    def __init__(
        self,
        gateway: GatewayClient,
        request: TourRequest,
        *,
        artifacts_dir: Path,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.gateway = gateway
        self.request = request
        self.sleep = sleep
        self.monotonic = monotonic
        self.run_id = uuid4().hex[:12]
        summary_path = Path(artifacts_dir) / f"zone_tour_{self.run_id}.json"
        self.trace = PersistentTrace(
            summary_path,
            context={
                "device_id": request.device_id,
                "zone_items": dict(request.zone_items),
                "packing_worker": request.packing_worker,
                "gateway": gateway.base_url,
                "run_id": self.run_id,
            },
        )
        self.job_id: int | None = None

    def create_order(self) -> dict[str, Any]:
        payload = tour_order_payload(
            self.request.zone_items,
            run_id=self.run_id,
            requested_by=self.request.packing_worker,
        )
        status, created = self.gateway.request(
            "POST",
            "/api/v1/orders",
            payload=payload,
            idempotency_key=f"zone-tour-{self.run_id}",
        )
        if status not in {200, 201} or "job_id" not in created:
            raise RuntimeError(f"주문 생성 실패: HTTP {status} {created}")
        self.job_id = int(created["job_id"])
        self.trace.record("order_created", job_id=self.job_id, payload=payload)
        return created

    def complete_worker_step(self, job: Mapping[str, Any]) -> dict[str, Any]:
        """사람이 인계를 확인하는 fms/wait step만 대신 닫는다."""
        body = {
            "worker_id": self.request.packing_worker,
            "completion_note": "zone tour hardware run",
            "acknowledged_manual_item_ids": [],
        }
        status, response = self.gateway.request(
            "POST",
            f"/api/v1/jobs/{job['job_id']}/worker-completion",
            payload=body,
            idempotency_key=f"zone-tour-completion-{self.run_id}",
        )
        detail = response.get("detail") or {}
        if status == 409 and detail.get("code") == "MANUAL_ACKNOWLEDGEMENT_REQUIRED":
            body["acknowledged_manual_item_ids"] = detail.get("item_ids") or []
            status, response = self.gateway.request(
                "POST",
                f"/api/v1/jobs/{job['job_id']}/worker-completion",
                payload=body,
                idempotency_key=f"zone-tour-completion-ack-{self.run_id}",
            )
        if status != 200:
            raise RuntimeError(f"작업자 완료 확인 실패: HTTP {status} {response}")
        self.trace.record("worker_completion_sent", acknowledged=body)
        return response

    def cancel(self, reason: str) -> None:
        if self.job_id is None:
            return
        status, response = self.gateway.request(
            "POST",
            f"/internal/v1/jobs/{self.job_id}/cancel",
            payload={"reason": reason, "requested_by": self.request.packing_worker},
            idempotency_key=f"zone-tour-cancel-{self.run_id}",
        )
        self.trace.record("cancel_requested", status=status, response=response)

    def run(self, *, timeout_s: float, poll_interval_s: float = 2.0) -> TourResult:
        """주문 한 건이 세 창고를 돌고 충전소로 돌아올 때까지 지켜본다."""
        job: dict[str, Any] | None = None
        try:
            self.create_order()
            deadline = self.monotonic() + timeout_s
            completion_sent = False
            previous = None
            while self.monotonic() < deadline:
                status, current = self.gateway.request(
                    "GET", f"/api/v1/jobs/{self.job_id}"
                )
                if status != 200:
                    raise RuntimeError(f"job 조회 실패: HTTP {status} {current}")
                job = current
                signature = step_signature(job)
                if signature != previous:
                    self.trace.record(
                        "job_progress",
                        job_state=job.get("state"),
                        steps=[
                            {
                                "step_no": step.get("step_no"),
                                "executor_type": step.get("executor_type"),
                                "action_type": step.get("action_type"),
                                "temperature_zone": _zone_of(step),
                                "state": step.get("state"),
                            }
                            for step in _steps(job)
                        ],
                    )
                    previous = signature
                if not completion_sent and worker_completion_pending(job):
                    self.complete_worker_step(job)
                    completion_sent = True
                if str(job.get("state")) in TERMINAL_JOB_STATES:
                    break
                self.sleep(poll_interval_s)
        except (RuntimeError, KeyError, ValueError) as error:
            return self._finish(job, "RUNNER_ERROR", str(error), passed=False)
        except KeyboardInterrupt:
            self.cancel("zone tour interrupted by the operator")
            return self._finish(job, "INTERRUPTED", "사용자 중단", passed=False)

        evaluation = evaluate_tour(job)
        if not evaluation["passed"]:
            self.cancel(f"zone tour cleanup: {evaluation['reason_code']}")
        return self._finish(
            job,
            evaluation["reason_code"],
            f"방문한 구역: {list(evaluation['visited'])}",
            passed=bool(evaluation["passed"]),
        )

    def _finish(
        self,
        job: Mapping[str, Any] | None,
        reason_code: str,
        message: str,
        *,
        passed: bool,
    ) -> TourResult:
        visited = visited_zone_order(job) if job else ()
        self.trace.record(
            "tour_result", passed=passed, reason_code=reason_code, message=message
        )
        self.trace.finalize(success=passed, code=reason_code, message=message)
        return TourResult(
            passed=passed,
            reason_code=reason_code,
            message=message,
            job_id=self.job_id,
            job_state=None if job is None else str(job.get("state")),
            visited_zones=visited,
            trace_path=self.trace.summary_path,
            event_log_path=self.trace.event_path,
        )
