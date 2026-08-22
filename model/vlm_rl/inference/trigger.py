"""Trigger VLM only after ordinary navigation cannot decide a safe path."""

from __future__ import annotations

from collections.abc import Sequence

from .navigation_context import NavigationContext


UNDECIDABLE_STATES = frozenset({"failed", "stuck", "undecidable"})


def should_trigger_recovery(
    detections: Sequence[object],
    context: NavigationContext,
    *,
    stuck_threshold_seconds: float = 3.0,
) -> bool:
    relevant = any(
        getattr(item, "class_name", "") in {"person", "obstacle"}
        for item in detections
    )
    undecidable = (
        context.navigation_state.lower() in UNDECIDABLE_STATES
        or context.stuck_seconds >= stuck_threshold_seconds
    )
    return relevant and undecidable
