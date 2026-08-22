"""Opt-in physical WAIT_REOBSERVE approval-path test; disabled by default."""

import json
import os
import time
from urllib import request

import pytest


pytestmark = pytest.mark.hardware


def _json_call(url: str, *, payload: dict | None = None) -> dict:
    outgoing = request.Request(
        url,
        data=(json.dumps(payload).encode() if payload is not None else None),
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with request.urlopen(outgoing, timeout=3.0) as response:
        return json.loads(response.read())


def test_operator_approved_wait_reaches_pinky_without_translation() -> None:
    if os.environ.get("TRIHOUSE_RUN_RECOVERY_WAIT") != "1":
        pytest.skip("set TRIHOUSE_RUN_RECOVERY_WAIT=1 only with an E-stop operator present")
    gateway = os.environ["FMS_GATEWAY_URL"].rstrip("/")
    proposal_id = os.environ["RECOVERY_WAIT_PROPOSAL_ID"]
    approved = _json_call(
        gateway + f"/api/v1/recovery/proposals/{proposal_id}/decision",
        payload={
            "worker_id": os.environ.get("SAFETY_MANAGER_ID", "W-CONTROL-01"),
            "decision": "approved",
            "reason": "opt-in physical WAIT_REOBSERVE smoke",
        },
    )
    assert approved["command"]["selected_skill_id"] == 3
    assert approved["command"]["canonical_action"]["coord"] == [0.0, 0.0, 0.0]

    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        state = _json_call(
            gateway + f"/internal/v1/recovery/proposals/{proposal_id}/execution"
        )
        if state.get("result") is not None:
            assert state["result"]["success"] is True
            assert state["result"]["status"] == "succeeded"
            return
        time.sleep(0.5)
    raise AssertionError("Pinky did not return a WAIT_REOBSERVE result within 30 seconds")
