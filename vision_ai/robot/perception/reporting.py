"""무엇을 언제 관제로 올릴지 정한다.

추론은 10~15 Hz 로 돈다. 그것을 그대로 올리면 안 된다 — 관측이 로봇에 닿는 길이
TCP 8788 이고 **주행 명령이 같은 링크를 쓴다.** 초당 열몇 건의 관측으로 채우면
`execute_transport` 가 뒤로 밀린다.

올릴 가치가 있는 것은 둘뿐이다.

1. **바뀐 것** — 사람이 나타났다/사라졌다, 낙상 상태가 넘어갔다
2. **아직 유효하다는 신호** — 관측에는 `ttl_ms` 수명이 있고 만료되면 안전 gate 가
   사람을 잊는다. 그 전에 한 번 새로고침하면 된다

그래서 상태가 그대로면 `ttl_ms` 의 절반 주기로만 보낸다. 600 ms 수명이면 약
3 Hz 다. 절반인 이유는 한 번 유실돼도 다음 갱신이 만료 전에 닿기 때문이다.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReportPolicy:
    ttl_ms: int = 600

    def __post_init__(self) -> None:
        if self.ttl_ms <= 0:
            raise ValueError("ttl_ms must be positive")

    @property
    def refresh_interval_s(self) -> float:
        """수명의 절반. 한 번 유실돼도 다음 갱신이 만료 전에 닿는다."""
        return self.ttl_ms / 2000.0


class ReportThrottle:
    """같은 상태가 이어지는 동안 전송을 수명의 절반 주기로 줄인다."""

    def __init__(self, policy: ReportPolicy) -> None:
        self.policy = policy
        self._last_state: str | None = None
        self._last_sent_at: float | None = None

    def should_report(self, timestamp_s: float, state: str) -> bool:
        """지금 이 상태를 올려야 하는가.

        `state` 는 사람 유무와 낙상 상태를 합친 문자열이다 — 둘 중 하나만 바뀌어도
        관제가 알아야 한다. 사람이 사라진 것(`NO_DETECTION`)도 상태 변화이므로
        여기서 True 가 나오지만, **보내는 쪽은 그것을 전송하지 않는다.** 안전
        gate 는 만료로 잊는 것이 계약이고, confidence 0 은 받지 않는다.
        """
        changed = state != self._last_state
        stale = (
            self._last_sent_at is None
            or timestamp_s - self._last_sent_at >= self.policy.refresh_interval_s
        )
        if not (changed or stale):
            return False
        self._last_state = state
        self._last_sent_at = timestamp_s
        return True

    def reset(self) -> None:
        self._last_state = None
        self._last_sent_at = None
