"""운반 action을 받기 전 필요한 interface가 준비됐는지 판정하는 순수 정책."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReadinessInputs:
    scan_fresh: bool
    odom_fresh: bool
    nav_available: bool


@dataclass(frozen=True)
class ReadinessResult:
    ready: bool
    missing: tuple[str, ...]


def evaluate_readiness(inputs: ReadinessInputs) -> ReadinessResult:
    missing = tuple(name for name, present in (
        ('scan', inputs.scan_fresh), ('odom', inputs.odom_fresh), ('navigate_to_pose', inputs.nav_available),
    ) if not present)
    return ReadinessResult(ready=not missing, missing=missing)
