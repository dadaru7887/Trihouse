"""HTTP clients for the 5080-to-4060 recovery boundary."""

from __future__ import annotations

import json
from typing import Any, Callable
from urllib import request


HttpCall = Callable[[request.Request], tuple[int, Any]]


def _urlopen(call: request.Request) -> tuple[int, Any]:
    with request.urlopen(call, timeout=3.0) as response:
        return response.status, json.loads(response.read())


class GatewayProposalClient:
    def __init__(self, gateway_url: str, transport: HttpCall = _urlopen):
        self.gateway_url = gateway_url.rstrip("/")
        self.transport = transport

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        outgoing = request.Request(
            self.gateway_url + "/internal/v1/recovery/proposals",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": payload["proposal_id"],
            },
            method="POST",
        )
        status, response = self.transport(outgoing)
        if not 200 <= status < 300:
            raise RuntimeError(f"Gateway rejected recovery proposal with HTTP {status}")
        return response

    def execution(self, proposal_id: str) -> dict[str, Any]:
        outgoing = request.Request(
            self.gateway_url + f"/internal/v1/recovery/proposals/{proposal_id}/execution",
            method="GET",
        )
        status, response = self.transport(outgoing)
        if not 200 <= status < 300:
            raise RuntimeError(f"Gateway recovery status failed with HTTP {status}")
        return response

    def open_recoveries(self, device_id: str) -> list[dict[str, Any]]:
        outgoing = request.Request(
            self.gateway_url + f"/internal/v1/recovery/devices/{device_id}/open",
            method="GET",
        )
        status, response = self.transport(outgoing)
        if not 200 <= status < 300 or not isinstance(response, list):
            raise RuntimeError(f"Gateway open recovery lookup failed with HTTP {status}")
        return response

    def complete(self, proposal: dict[str, Any], payload: dict[str, Any], message_id: str) -> dict[str, Any]:
        url = (
            self.gateway_url
            + f"/internal/v1/recovery/episodes/{proposal['recovery_episode_uuid']}"
            + f"/steps/{proposal['step_no']}/complete"
        )
        outgoing = request.Request(
            url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json", "Idempotency-Key": message_id},
            method="POST",
        )
        status, response = self.transport(outgoing)
        if not 200 <= status < 300:
            raise RuntimeError(f"Gateway recovery completion failed with HTTP {status}")
        return response
