"""Append-only datasets for nominal driving and executed recovery learning.

Normal Nav2 and rule-based driving are useful operational data, but do not have
the frozen VLM/RL state/action fields.  They are intentionally stored apart
from trainable recovery transitions so a routine navigation record can never be
silently used to train the recovery policy.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Lock
from typing import Any, Mapping

from model.vlm_rl.shared.contracts import LearningTransition, validate_transition


NAVIGATION_SCHEMA_ID = "trihouse.navigation-event.v1"
TRAINING_SCHEMA_ID = "trihouse.recovery-transition.v1"
_NAVIGATION_SOURCES = {"nav2", "rule"}
_NAVIGATION_EVENT_TYPES = {"state", "decision", "intervention", "outcome"}


class DriveDatasetCollector:
    """Persist two append-only JSONL datasets below one run directory."""

    def __init__(self, dataset_dir: Path):
        self.dataset_dir = Path(dataset_dir)
        self._lock = Lock()

    @property
    def navigation_path(self) -> Path:
        return self.dataset_dir / "navigation_events.jsonl"

    @property
    def recovery_path(self) -> Path:
        return self.dataset_dir / "recovery_transitions.jsonl"

    def record_navigation_event(self, event: Mapping[str, Any]) -> None:
        """Record routine Nav2/rule-based driving metadata continuously.

        Required fields are deliberately compact so the ROS/Gateway bridge can
        call this for every state change without serializing camera frames.
        `frame_ref` may point to a separately governed recording if needed.
        """
        source = event.get("source")
        event_type = event.get("event_type")
        device_id = event.get("device_id")
        if source not in _NAVIGATION_SOURCES:
            raise ValueError("navigation source must be 'nav2' or 'rule'")
        if event_type not in _NAVIGATION_EVENT_TYPES:
            raise ValueError("navigation event_type is invalid")
        if not isinstance(device_id, str) or not device_id:
            raise ValueError("navigation event requires a non-empty device_id")
        self._append(self.navigation_path, {
            "schema_id": NAVIGATION_SCHEMA_ID,
            "recorded_at": _utc_now(),
            **dict(event),
        })

    def record_recovery_completion(self, completion: Mapping[str, Any]) -> None:
        """Append only a real executed recovery transition for offline RL.

        `completion` is the response from
        ``model.vlm_rl.inference.completion_runtime.build_completion``.  The
        strict model contract rejects observation-only or unexecuted proposals.
        """
        transition = completion.get("transition")
        if not isinstance(transition, Mapping):
            raise ValueError("completion must contain a transition")
        item = LearningTransition(
            state=tuple(transition.get("state", ())),
            skill=transition.get("skill"),
            coord=tuple(transition.get("coord", ())),
            reward=transition.get("reward"),
            next_state=tuple(transition.get("next_state", ())),
            done=transition.get("done"),
            meta=dict(transition.get("meta", {})),
        )
        validate_transition(item)
        self._append(self.recovery_path, {
            "state": list(item.state), "skill": item.skill,
            "coord": list(item.coord), "reward": item.reward,
            "next_state": list(item.next_state), "done": item.done,
            "meta": {**item.meta, "dataset_schema_id": TRAINING_SCHEMA_ID},
        })

    def _append(self, path: Path, record: Mapping[str, Any]) -> None:
        payload = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, path.open("ab", buffering=0) as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
