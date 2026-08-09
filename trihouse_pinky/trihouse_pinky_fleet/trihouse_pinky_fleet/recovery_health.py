"""SR_57 비상 해제 후 재투입 전 점검 조건을 판정하는 순수 정책."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryHealthInputs:
    odom_fresh: bool
    scan_fresh: bool
    ultrasonic_fresh: bool
    battery_fresh: bool
    cargo_present: bool


@dataclass(frozen=True)
class RecoveryHealthResult:
    ready: bool
    failures: tuple[str, ...]


def evaluate_recovery_health(inputs: RecoveryHealthInputs) -> RecoveryHealthResult:
    failures = tuple(name for name, passed in (
        ('odom', inputs.odom_fresh), ('scan', inputs.scan_fresh), ('ultrasonic', inputs.ultrasonic_fresh),
        ('battery', inputs.battery_fresh), ('cargo', not inputs.cargo_present),
    ) if not passed)
    return RecoveryHealthResult(not failures, failures)
