"""Runtime configuration for the pre-execution recovery Safety gate."""

from __future__ import annotations

from collections.abc import Mapping


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def parse_boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"expected a boolean value, received {value!r}")


def resolve_safety_gate(
    runtime_mode: str,
    cli_value: bool | None,
    env: Mapping[str, str],
) -> bool:
    """Resolve CLI > environment > safe default and enforce physical policy."""
    if runtime_mode not in {"physical", "simulation", "training_exploration"}:
        raise ValueError(f"unsupported runtime mode: {runtime_mode}")
    enabled = cli_value
    if enabled is None and "VLM_RL_SAFETY_GATE_ENABLED" in env:
        enabled = parse_boolean(env["VLM_RL_SAFETY_GATE_ENABLED"])
    if enabled is None:
        enabled = True
    if runtime_mode == "physical" and not enabled:
        raise ValueError("physical runtime cannot disable the Safety gate")
    return enabled
