"""
replay_sampler.py

Trihouse §9 "Episodic Memory 위의 replay samplers" 최소 구현.

원본(Memory)과 sampler를 분리한다는 원칙(§9 callout)을 따른다:
- 이 모듈은 원본 buffer(pickle에 쌓인 transition들)를 복제하지 않는다.
- 매 학습 step마다 buffer 전체를 훑어서 "이번엔 뭘 보여줄지"만 골라준다.

지금(2026-08-09) buffer가 8개 transition뿐이라 엄격한 목표 비율 강제는
의미가 없다. 그래서 두 단계로 나눈다:
  1) outcome bucket(safe/boundary/critical) 별 목표 비율로 뽑되,
     버킷이 텅 비어있으면 그냥 있는 것만으로 채운다 (에러 내지 않음).
  2) 뽑을 때 recency/rarity를 importance weight로 살짝 반영한다.
     데이터가 적을 땐 이 weight의 영향이 작고, 데이터가 쌓일수록
     자연히 목표 비율에 가까워진다.

DB(Episodic Memory API)가 완성되면 TransitionRecord를 채우는 부분만
DB 조회로 교체하면 되고, 아래 버킷 분류·샘플링 로직은 그대로 쓸 수 있다.
"""

from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum
from typing import Any, Optional
import math
import random
import time


class OutcomeBucket(Enum):
    SAFE = "safe"
    BOUNDARY = "boundary"
    CRITICAL = "critical"


@dataclass
class TransitionRecord:
    """SAC replay 하나 (EpisodeStep 1개에 대응, §9 D_SAC 정의 그대로)."""
    state: Any
    skill: Any          # z_t: TGRPO가 고른 skill
    coord: Any           # p_t: SAC가 낸 좌표
    reward: float
    next_state: Any
    done: bool
    timestamp: float
    map_zone: str = "unknown"
    terminal_critical: bool = False   # collision/emergency/human intrusion으로 끝났는지
    outcome_margin: Optional[float] = None  # 없으면 reward로 근사 판정
    # database_guide.md job_steps/recovery_episodes 규약: policy_name+policy_version이
    # 있어야 정책 버전별 성과 집계가 가능. recovery_data_collector.py와 동일 규약,
    # 지금은 sampler 동작에 안 쓰이는 메타데이터일 뿐 (필터링/샘플링 로직 변경 없음).
    policy_name: Optional[str] = None
    policy_version: Optional[str] = None

    def bucket(self, boundary_margin: float = 0.2) -> OutcomeBucket:
        if self.terminal_critical:
            return OutcomeBucket.CRITICAL
        margin = self.outcome_margin if self.outcome_margin is not None else self.reward
        if margin < boundary_margin:
            return OutcomeBucket.BOUNDARY
        return OutcomeBucket.SAFE


@dataclass
class BucketRatioConfig:
    """목표 비율. 초반엔 대충 잡고, 데이터 쌓이면서 조정하면 된다."""
    safe: float = 0.5
    boundary: float = 0.3
    critical: float = 0.2

    def as_dict(self) -> dict:
        return {
            OutcomeBucket.SAFE: self.safe,
            OutcomeBucket.BOUNDARY: self.boundary,
            OutcomeBucket.CRITICAL: self.critical,
        }


class BucketedReplaySampler:
    def __init__(self, ratio_config: Optional[BucketRatioConfig] = None):
        self.ratio_config = ratio_config or BucketRatioConfig()
        self._records: list[TransitionRecord] = []

    def add(self, record: TransitionRecord) -> None:
        self._records.append(record)

    def _grouped(self) -> dict[OutcomeBucket, list[TransitionRecord]]:
        groups: dict[OutcomeBucket, list[TransitionRecord]] = defaultdict(list)
        for r in self._records:
            groups[r.bucket()].append(r)
        return groups

    def _importance_weight(self, record: TransitionRecord, now: float,
                            zone_counts: dict[str, int]) -> float:
        """recency + rarity를 곱해서 하나의 weight로. 데이터가 적을 땐 zone_counts가
        다 작아서 이 weight가 거의 균일하게 나오고, 데이터가 쌓일수록
        희귀한 map_zone/오래된 기록에 자연스럽게 더 가중치가 실린다."""
        age_s = max(now - record.timestamp, 0.0)
        recency_w = math.exp(-age_s / 3600.0)  # 1시간 반감기 정도, 프로젝트에 맞게 조정
        rarity_w = 1.0 / math.sqrt(zone_counts.get(record.map_zone, 1))
        return recency_w * rarity_w

    def sample(self, batch_size: int, now: Optional[float] = None) -> list[TransitionRecord]:
        if not self._records:
            return []
        now = now if now is not None else time.time()
        groups = self._grouped()
        zone_counts: dict[str, int] = defaultdict(int)
        for r in self._records:
            zone_counts[r.map_zone] += 1

        target_ratios = self.ratio_config.as_dict()
        # 실제로 존재하는 버킷만 남기고 비율을 재정규화 (텅 빈 버킷 때문에 에러나지 않게)
        available = {b: ratio for b, ratio in target_ratios.items() if groups.get(b)}
        if not available:
            return []
        norm = sum(available.values())
        available = {b: ratio / norm for b, ratio in available.items()}

        batch: list[TransitionRecord] = []
        for bucket, ratio in available.items():
            n = max(1, round(batch_size * ratio))
            pool = groups[bucket]
            weights = [self._importance_weight(r, now, zone_counts) for r in pool]
            # 뽑을 개수가 pool보다 많으면 중복 허용(데이터 적을 때 흔함)
            k = min(n, len(pool)) if len(pool) >= n else n
            chosen = random.choices(pool, weights=weights, k=k) if len(pool) < n else \
                _weighted_sample_without_replacement(pool, weights, n)
            batch.extend(chosen)

        random.shuffle(batch)
        return batch[:batch_size] if len(batch) > batch_size else batch

    def bucket_report(self) -> str:
        groups = self._grouped()
        lines = [f"buffer 총 {len(self._records)}개"]
        for b in OutcomeBucket:
            lines.append(f"  {b.value}: {len(groups.get(b, []))}개")
        return "\n".join(lines)


def _weighted_sample_without_replacement(pool, weights, k):
    # random.sample은 weight를 지원 안 하므로 간단한 weighted reservoir 방식
    pairs = list(zip(pool, weights))
    chosen = []
    pairs = pairs[:]
    for _ in range(min(k, len(pairs))):
        total = sum(w for _, w in pairs)
        r = random.uniform(0, total)
        upto = 0.0
        for i, (item, w) in enumerate(pairs):
            upto += w
            if upto >= r:
                chosen.append(item)
                pairs.pop(i)
                break
    return chosen


if __name__ == "__main__":
    # 지금 buffer 규모(8개)를 흉내낸 최소 예시
    sampler = BucketedReplaySampler()
    now = time.time()
    mock = [
        TransitionRecord(state=None, skill="back_up", coord=(0.1, 0.0), reward=0.8,
                          next_state=None, done=True, timestamp=now - 60, map_zone="zoneA"),
        TransitionRecord(state=None, skill="spin", coord=(0.0, 0.3), reward=0.6,
                          next_state=None, done=True, timestamp=now - 120, map_zone="zoneA"),
        TransitionRecord(state=None, skill="drive", coord=(0.2, 0.1), reward=0.1,
                          next_state=None, done=False, timestamp=now - 30, map_zone="zoneB"),
        TransitionRecord(state=None, skill="drive", coord=(0.15, 0.05), reward=-0.5,
                          next_state=None, done=True, timestamp=now - 10, map_zone="zoneB",
                          terminal_critical=True),
    ]
    for m in mock:
        sampler.add(m)

    print(sampler.bucket_report())
    print()
    batch = sampler.sample(batch_size=4)
    print(f"샘플된 {len(batch)}개:")
    for r in batch:
        print(f"  skill={r.skill}, bucket={r.bucket().value}, zone={r.map_zone}")
