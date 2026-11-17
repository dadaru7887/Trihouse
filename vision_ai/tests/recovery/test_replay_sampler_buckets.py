"""위험도 버킷은 운영 DB 가 내린 판정을 따른다."""

from vision_ai.data_loader.recovery.replay_sampler import (
    BucketedReplaySampler,
    OutcomeBucket,
    TransitionRecord,
)


def record(**overrides) -> TransitionRecord:
    values = {
        "state": [0.0] * 9, "skill": 0, "coord": [0.0] * 3, "reward": 1.0,
        "next_state": [0.0] * 9, "done": True, "timestamp": 0.0,
    }
    values.update(overrides)
    return TransitionRecord(**values)


def test_the_operational_verdict_wins_over_the_reward_heuristic() -> None:
    """로봇이 관측한 여유가 critical 을 만들었다. 보상이 높아도 critical 이다.

    보상만 보면 이 실행은 SAFE 로 보인다. 그런데 `recovery_steps.outcome_class` 는
    이미 critical 이다. 학습 집합이 운영 기록과 다른 말을 하면 안 된다.
    """
    assert record(reward=5.0, outcome_class="critical").bucket() is OutcomeBucket.CRITICAL
    assert record(reward=-9.0, outcome_class="safe").bucket() is OutcomeBucket.SAFE


def test_records_without_a_class_still_load() -> None:
    """DB 를 거치지 않은 시뮬레이터 버퍼와 옛 export 는 보상 임계값으로 나뉜다."""
    assert record(reward=1.0).bucket() is OutcomeBucket.SAFE
    assert record(reward=0.05).bucket() is OutcomeBucket.BOUNDARY
    assert record(reward=1.0, terminal_critical=True).bucket() is OutcomeBucket.CRITICAL


def test_an_unknown_class_falls_back_instead_of_crashing_training() -> None:
    """새 값이 DB 에 생겨도 학습이 죽지 않고 보수적으로 계속되어야 한다."""
    assert record(reward=0.05, outcome_class="unheard_of").bucket() is OutcomeBucket.BOUNDARY


def test_critical_records_survive_a_buffer_dominated_by_safe_ones() -> None:
    """희소한 위기 사례가 표본에서 사라지지 않게 하는 것이 이 sampler 의 목적이다."""
    sampler = BucketedReplaySampler()
    for _ in range(100):
        sampler.add(record(outcome_class="safe"))
    sampler.add(record(outcome_class="critical", reward=-100.0))

    batch = sampler.sample(10, now=0.0)

    assert any(item.bucket() is OutcomeBucket.CRITICAL for item in batch)
