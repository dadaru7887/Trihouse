"""Outcome-balanced replay sampler ported unchanged from dev_driving."""

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
import math
import random
import time
from typing import Any, Optional


class OutcomeBucket(Enum):
    SAFE = "safe"
    BOUNDARY = "boundary"
    CRITICAL = "critical"


@dataclass
class TransitionRecord:
    state: Any
    skill: Any
    coord: Any
    reward: float
    next_state: Any
    done: bool
    timestamp: float
    map_zone: str = "unknown"
    terminal_critical: bool = False
    outcome_margin: Optional[float] = None
    policy_name: Optional[str] = None
    policy_version: Optional[str] = None

    def bucket(self, boundary_margin: float = 0.2) -> OutcomeBucket:
        if self.terminal_critical:
            return OutcomeBucket.CRITICAL
        margin = self.outcome_margin if self.outcome_margin is not None else self.reward
        return OutcomeBucket.BOUNDARY if margin < boundary_margin else OutcomeBucket.SAFE


@dataclass
class BucketRatioConfig:
    safe: float = 0.5
    boundary: float = 0.3
    critical: float = 0.2

    def as_dict(self) -> dict[OutcomeBucket, float]:
        return {OutcomeBucket.SAFE: self.safe, OutcomeBucket.BOUNDARY: self.boundary,
                OutcomeBucket.CRITICAL: self.critical}


class BucketedReplaySampler:
    def __init__(self, ratio_config: Optional[BucketRatioConfig] = None):
        self.ratio_config = ratio_config or BucketRatioConfig()
        self._records: list[TransitionRecord] = []

    def add(self, record: TransitionRecord) -> None:
        self._records.append(record)

    def _grouped(self):
        groups = defaultdict(list)
        for record in self._records:
            groups[record.bucket()].append(record)
        return groups

    def _importance_weight(self, record, now, zone_counts) -> float:
        age_s = max(now - record.timestamp, 0.0)
        return math.exp(-age_s / 3600.0) / math.sqrt(zone_counts.get(record.map_zone, 1))

    def sample(self, batch_size: int, now: Optional[float] = None) -> list[TransitionRecord]:
        if not self._records:
            return []
        now = now if now is not None else time.time()
        groups = self._grouped()
        zone_counts = defaultdict(int)
        for record in self._records:
            zone_counts[record.map_zone] += 1
        available = {bucket: ratio for bucket, ratio in self.ratio_config.as_dict().items() if groups.get(bucket)}
        norm = sum(available.values())
        available = {bucket: ratio / norm for bucket, ratio in available.items()}
        batch = []
        for bucket, ratio in available.items():
            count = max(1, round(batch_size * ratio))
            pool = groups[bucket]
            weights = [self._importance_weight(record, now, zone_counts) for record in pool]
            chosen = (random.choices(pool, weights=weights, k=count) if len(pool) < count
                      else _weighted_sample_without_replacement(pool, weights, count))
            batch.extend(chosen)
        random.shuffle(batch)
        return batch[:batch_size] if len(batch) > batch_size else batch


def _weighted_sample_without_replacement(pool, weights, count):
    pairs = list(zip(pool, weights))
    chosen = []
    for _ in range(min(count, len(pairs))):
        target = random.uniform(0, sum(weight for _, weight in pairs))
        upto = 0.0
        for index, (item, weight) in enumerate(pairs):
            upto += weight
            if upto >= target:
                chosen.append(item)
                pairs.pop(index)
                break
    return chosen
