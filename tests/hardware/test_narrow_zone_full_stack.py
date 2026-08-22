"""공개 주문 API부터 창고 진입·탈출까지 잇는 opt-in 실기 통합 테스트."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest
import yaml


REPOSITORY = Path(__file__).resolve().parents[2]
PINKY = REPOSITORY / "trihouse_pinky"
sys.path.insert(0, str(PINKY / "trihouse_pinky_docking"))

from trihouse_pinky_docking.narrow_zone import load_narrow_zones  # noqa: E402


PROFILE_FILE = REPOSITORY / "config" / "narrow_zones.new_map_2.yaml"
FROZEN = "frozen_storage_loading_dock_01"


def _json_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    headers = {"Content-Type": "application/json"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers=headers,
        method=method,
    )
    with urlopen(request, timeout=10.0) as response:
        return json.loads(response.read().decode("utf-8"))


def _is_frozen_navigation(step: dict) -> bool:
    value = step.get("input") or {}
    return (
        step.get("executor_type") == "mobile"
        and step.get("action_type") == "navigate"
        and value.get("temperature_zone") == "frozen"
    )


def _full_stack_flags_allowed(enable_full_stack: bool, enable_motion: bool) -> bool:
    return enable_full_stack and enable_motion


def test_full_stack_requires_both_explicit_motion_flags() -> None:
    assert _full_stack_flags_allowed(False, False) is False
    assert _full_stack_flags_allowed(True, False) is False
    assert _full_stack_flags_allowed(False, True) is False
    assert _full_stack_flags_allowed(True, True) is True


def test_default_fms_url_matches_the_p0_gateway(pytestconfig) -> None:
    assert pytestconfig.getoption("--fms-url") == "http://127.0.0.1:8080"


@pytest.mark.hardware
@pytest.mark.integration
def test_public_order_enters_and_then_exits_the_frozen_narrow_zone(pytestconfig) -> None:
    """한 주문만 만들고, 냉동 도착과 그 다음 mobile 이동 성공까지 기다린다.

    다음 mobile 이동이 성공하려면 Fleet가 냉동 zone을 먼저 탈출해야 한다. 성공/실패와
    무관하게 생성한 테스트 주문은 마지막에 취소해 자원과 예약을 반환한다.
    """
    enable_full_stack = pytestconfig.getoption("--enable-full-stack")
    enable_motion = pytestconfig.getoption("--enable-motion")
    if not enable_full_stack:
        pytest.skip("--enable-full-stack이 없어 공개 API 실기 주문을 만들지 않는다")
    assert _full_stack_flags_allowed(enable_full_stack, enable_motion), (
        "전체 통합 테스트는 --enable-motion도 함께 지정해야 한다"
    )

    profiles = load_narrow_zones(
        yaml.safe_load(PROFILE_FILE.read_text(encoding="utf-8")),
        map_name="new_map_2",
    )
    assert profiles[FROZEN].executable, (
        "냉동 exit 실측을 완료하고 measured.exit=true로 승인하기 전에는 전체 주문을 "
        "실기로 실행하지 않는다"
    )

    base_url = pytestconfig.getoption("--fms-url")
    timeout_s = pytestconfig.getoption("--full-stack-timeout")
    run_id = str(uuid4())
    created = _json_request(
        base_url,
        "/api/v1/orders",
        method="POST",
        idempotency_key=f"narrow-full-stack-{run_id}",
        payload={
            "external_reference": f"NARROW-FULL-STACK-{run_id}",
            "priority": "normal",
            "allow_partial_fulfillment": False,
            "requested_by": "codex-hardware-test",
            "items": [{"product_code": "SKU-DUMPLING", "quantity": 1}],
        },
    )
    job_id = int(created["job_id"])
    completed_frozen = False
    completed_after_frozen = False
    try:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            detail = _json_request(base_url, f"/api/v1/jobs/{job_id}")
            steps = sorted(detail["steps"], key=lambda item: item["step_no"])
            frozen_indexes = [
                index for index, step in enumerate(steps) if _is_frozen_navigation(step)
            ]
            if frozen_indexes:
                frozen_index = frozen_indexes[0]
                completed_frozen = steps[frozen_index]["state"] == "succeeded"
                completed_after_frozen = completed_frozen and any(
                    step.get("executor_type") == "mobile"
                    and step.get("action_type") == "navigate"
                    and step.get("state") == "succeeded"
                    for step in steps[frozen_index + 1 :]
                )
            assert detail["state"] not in {"failed", "cancelled"}, detail
            if completed_after_frozen:
                break
            time.sleep(1.0)
        assert completed_frozen, "냉동 창고 진입 단계가 제한 시간 안에 성공하지 않았다"
        assert completed_after_frozen, "냉동 zone 탈출 뒤 다음 이동이 성공하지 않았다"
    finally:
        _json_request(
            base_url,
            f"/internal/v1/jobs/{job_id}/cancel",
            method="POST",
            idempotency_key=f"narrow-full-stack-cancel-{run_id}",
            payload={
                "reason": "narrow-zone full-stack test cleanup",
                "requested_by": "codex-hardware-test",
            },
        )
