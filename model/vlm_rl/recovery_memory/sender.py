"""Retry pending recovery messages and remove only a matching application ACK."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from typing import Any, Callable
from urllib import error, request

from .queue import pending


@dataclass(frozen=True)
class SendReport:
    acknowledged: tuple[str, ...]
    pending: tuple[str, ...]
    dead_letter: tuple[str, ...]


Transport = Callable[[str, dict[str, str], dict[str, Any]], tuple[int, dict[str, Any]]]


def _post(url: str, headers: dict[str, str], payload: dict[str, Any]):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    outgoing = request.Request(url, data=body, headers={**headers, "Content-Type": "application/json"}, method="POST")
    try:
        with request.urlopen(outgoing, timeout=10) as response:
            return response.status, json.loads(response.read())
    except error.HTTPError as exc:
        try:
            response_payload = json.loads(exc.read())
        except Exception:
            response_payload = {}
        return exc.code, response_payload


def send_pending(queue_dir: Path, gateway_url: str, *, transport: Transport = _post,
                 max_attempts: int = 3, sleep: Callable[[float], None] = time.sleep) -> SendReport:
    acknowledged, remaining, dead = [], [], []
    dead_dir = queue_dir / "dead_letter"
    for path in pending(queue_dir):
        envelope = json.loads(path.read_text(encoding="utf-8"))
        message_id = envelope["message_id"]
        for attempt in range(max_attempts):
            try:
                status, response = transport(
                    gateway_url.rstrip("/") + envelope["endpoint"],
                    {"Idempotency-Key": message_id}, envelope["payload"],
                )
            except (OSError, TimeoutError):
                status, response = 0, {}
            if 200 <= status < 300 and response.get("message_id") == message_id and response.get("acknowledged") is True:
                path.unlink()
                acknowledged.append(message_id)
                break
            if status == 409:
                dead_dir.mkdir(parents=True, exist_ok=True)
                os.replace(path, dead_dir / path.name)
                dead.append(message_id)
                break
            if attempt + 1 < max_attempts:
                sleep(min(2 ** attempt, 8))
        else:
            remaining.append(message_id)
    return SendReport(tuple(acknowledged), tuple(remaining), tuple(dead))
