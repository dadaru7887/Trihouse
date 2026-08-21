"""주문별 "정책 로드 시작 -> 첫 액션 산출" 지연시간을 기록/비교한다.

발표자료(OMX_로봇팔_학습추론_자료.html) 6번 항목이 주장하는 "로봇·카메라는
한 번만 연결하고 물품마다 정책만 교체하면 빠르다"는 것을 이 로그로 실측 검증한다.
큐의 첫 주문은 로봇 connect 비용까지 포함된 콜드 스타트이므로 따로 표시한다.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass(frozen=True)
class BenchRecord:
    order_id: str
    product_code: str
    is_first_order: bool
    policy_load_s: float
    first_action_s: float

    @property
    def total_s(self) -> float:
        return self.policy_load_s + self.first_action_s


@dataclass
class Bench:
    _records: list[BenchRecord] = field(default_factory=list)

    @contextmanager
    def measure(self, *, order_id: str, product_code: str, is_first_order: bool):
        """with bench.measure(...) as tick: ... tick("policy_loaded") ... tick("first_action")"""
        marks: dict[str, float] = {}
        start = time.perf_counter()

        def tick(label: str) -> None:
            marks[label] = time.perf_counter() - start

        yield tick
        policy_load_s = marks.get("policy_loaded", 0.0)
        first_action_s = marks.get("first_action", policy_load_s) - policy_load_s
        self._records.append(
            BenchRecord(order_id, product_code, is_first_order, policy_load_s, first_action_s)
        )

    @property
    def records(self) -> tuple[BenchRecord, ...]:
        return tuple(self._records)

    def summary(self) -> str:
        if not self._records:
            return "(no bench records)"
        lines = ["order_id            product_code  first  policy_load_s  first_action_s  total_s"]
        for r in self._records:
            lines.append(
                f"{r.order_id:<20}{r.product_code:<14}{str(r.is_first_order):<7}"
                f"{r.policy_load_s:>13.3f}{r.first_action_s:>16.3f}{r.total_s:>9.3f}"
            )
        warm = [r for r in self._records if not r.is_first_order]
        if warm:
            avg_swap = sum(r.policy_load_s for r in warm) / len(warm)
            lines.append(f"\navg policy-swap-only load time (n={len(warm)}): {avg_swap:.3f}s")
        cold = [r for r in self._records if r.is_first_order]
        if cold and warm:
            lines.append(
                f"cold start (order #1, incl. robot connect): {cold[0].policy_load_s:.3f}s "
                f"vs warm avg: {avg_swap:.3f}s"
            )
        return "\n".join(lines)
