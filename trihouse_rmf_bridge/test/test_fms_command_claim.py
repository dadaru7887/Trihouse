"""RMF task와 FMS JobStep을 연결하는 command claim 계약 테스트."""

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trihouse_rmf_bridge.fms_client import (  # noqa: E402
    CommandClaimError,
    FmsCommandClaimClient,
)


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_claim_posts_rmf_identity_and_returns_complete_task_context() -> None:
    captured = {}

    def open_request(request, *, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _Response({
            "task_context": {
                "active": True,
                "job_id": 7,
                "job_step_id": 10,
                "assignment_revision": 2,
                "rmf_task_id": "rmf-7",
                "command_id": "8f93b06f-8e52-4ca7-9e59-c7835d51ea92",
                "map_revision": "map-7",
                "command_source": "rmf",
            }
        })

    client = FmsCommandClaimClient(
        "http://127.0.0.1:8000", timeout_s=1.25, opener=open_request,
    )
    context = client.claim(
        rmf_task_id="rmf-7", robot_id="PK_01",
        execution_id="exec-1", map_revision="map-7",
    )

    assert captured["url"].endswith("/internal/v1/rmf/tasks/rmf-7/commands/claim")
    assert captured["body"] == {
        "robot_id": "PK_01",
        "execution_id": "exec-1",
        "map_revision": "map-7",
    }
    assert captured["timeout"] == 1.25
    assert context.job_id == 7
    assert context.job_step_id == 10
    assert context.assignment_revision == 2
    assert context.command_source == "rmf"


def test_claim_rejects_incomplete_context_instead_of_synthesizing_ids() -> None:
    client = FmsCommandClaimClient(
        "http://127.0.0.1:8000",
        opener=lambda *_args, **_kwargs: _Response({"task_context": {}}),
    )

    with pytest.raises(CommandClaimError):
        client.claim(
            rmf_task_id="rmf-7", robot_id="PK_01",
            execution_id="exec-1", map_revision="map-7",
        )
