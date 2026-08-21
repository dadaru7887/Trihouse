"""Fsync-backed pending-message queue; ACK loss never loses training data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import uuid
from typing import Any


@dataclass(frozen=True)
class RecoveryMessage:
    message_id: str
    message_type: str
    endpoint: str
    payload: dict[str, Any]


def canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def enqueue(queue_dir: Path, message: RecoveryMessage) -> Path:
    uuid.UUID(message.message_id)
    queue_dir.mkdir(parents=True, exist_ok=True)
    envelope = asdict(message)
    envelope["payload_sha256"] = hashlib.sha256(canonical_payload(message.payload)).hexdigest()
    content = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    destination = queue_dir / f"{message.message_id}.json"
    temporary = queue_dir / f".{message.message_id}.{os.getpid()}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, content)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, destination)
    directory_descriptor = os.open(queue_dir, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    return destination


def pending(queue_dir: Path) -> list[Path]:
    return sorted(path for path in queue_dir.glob("*.json") if path.is_file())
