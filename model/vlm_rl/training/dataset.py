"""Strict JSONL input adapter for offline recovery-policy training."""

from __future__ import annotations

import json
from pathlib import Path

from model.vlm_rl.shared.contracts import LearningTransition, validate_transition


FIELDS = {"state", "skill", "coord", "reward", "next_state", "done", "meta"}


def load_training_jsonl(path: Path) -> list[LearningTransition]:
    transitions: list[LearningTransition] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                if not isinstance(item, dict) or set(item) != FIELDS:
                    raise ValueError(f"fields must be exactly {sorted(FIELDS)}")
                transition = LearningTransition(
                    state=tuple(item["state"]),
                    skill=item["skill"],
                    coord=tuple(item["coord"]),
                    reward=item["reward"],
                    next_state=tuple(item["next_state"]),
                    done=item["done"],
                    meta=item["meta"],
                )
                validate_transition(transition)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid recovery transition on line {line_number}: {exc}") from exc
            transitions.append(transition)
    return transitions
