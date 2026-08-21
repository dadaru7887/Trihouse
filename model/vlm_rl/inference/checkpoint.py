"""Load only explicitly approved recovery checkpoints with checksum verification."""

from __future__ import annotations

import hashlib
from pathlib import Path


def verify_checkpoint(path: Path, expected_sha256: str, *, approved: bool) -> Path:
    if not approved:
        raise PermissionError("checkpoint is not approved for physical inference")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected_sha256.lower():
        raise ValueError("checkpoint SHA-256 does not match the approved manifest")
    return path


def load_checkpoint(path: Path, expected_sha256: str, *, approved: bool, map_location: str = "cpu"):
    verified = verify_checkpoint(path, expected_sha256, approved=approved)
    import torch
    return torch.load(verified, map_location=map_location, weights_only=True)
