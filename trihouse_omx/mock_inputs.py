"""3·4번 인터페이스(상품 정보, 핑키 도착 상태값)를 임의값으로 공급한다.

조사 결과 이 두 값은 실제로는 다음에서 온다 (아직 이 모듈에서 연결하지 않음):
  - 상품 정보: POST /internal/v1/executor/dispatches/claim 의
    payload.input.items[].{product_code, reserved_quantity}
  - 핑키 도착: 전용 필드가 없고, GET /api/v1/jobs/{id} 로 같은 번들의
    "mobile/navigate" 스텝 state를 폴링하는 대리 신호뿐 (robot_arm_safety.md의
    "Pinky 도착 확인 전에 handover zone을 활성화하지 않는다" 금지 연결 참고)

1단계는 이 두 값을 로컬 큐로 대체해서, 로봇팔 쪽 로직(정책 스왑, 추론, 파지
판정)만 따로 검증한다. pinky_arrived=False로 시작하는 항목을 하나 섞어서
"도착 전에는 인계로 안 넘어가는지"도 같이 확인한다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class MockOrderItem:
    line_no: int
    product_code: str
    reserved_quantity: int


@dataclass
class MockPinkyArrival:
    """핑키 도착 상태값 대리 mock.

    already_arrived=True면 즉시 도착. False면 delay_s 이후에 도착한 것으로
    친다(실제 네트워크 폴링을 흉내). never_arrives=True면 타임아웃 경로 테스트용
    — 영원히 도착하지 않는다.
    """

    already_arrived: bool = True
    delay_s: float = 0.0
    never_arrives: bool = False
    _requested_at: float | None = field(default=None, init=False, repr=False)

    def has_arrived(self) -> bool:
        if self.never_arrives:
            return False
        if self.already_arrived:
            return True
        if self._requested_at is None:
            self._requested_at = time.monotonic()
            return False
        return (time.monotonic() - self._requested_at) >= self.delay_s


@dataclass(frozen=True)
class MockOrder:
    order_id: str
    job_step_id: int
    assignment_revision: int
    items: tuple[MockOrderItem, ...]
    pinky: MockPinkyArrival


def parse_items(spec: str) -> tuple[MockOrderItem, ...]:
    """"dumpling:2,porkbelly:1" -> 상품코드:수량 목록. 수량 생략하면 1로 본다."""
    items = []
    for line_no, part in enumerate(spec.split(","), start=1):
        code, _, qty = part.strip().partition(":")
        code = code.strip()
        if not code:
            raise ValueError(f"empty product_code in order spec {spec!r}")
        items.append(MockOrderItem(line_no, code, int(qty) if qty.strip() else 1))
    return tuple(items)


def build_queue_from_specs(
    specs: Sequence[str],
    *,
    start_job_step_id: int,
    id_prefix: str,
    pinky_delay_s: float = 0.0,
) -> tuple[MockOrder, ...]:
    """--order로 받은 문자열들을 MockOrder 큐로 바꾼다.

    pinky_delay_s>0이면 모든 주문의 핑키 도착을 그만큼 지연시켜 안전 게이트
    (핑키 도착 전엔 인계로 안 넘어가는지)를 같이 테스트할 수 있다.
    """
    return tuple(
        MockOrder(
            order_id=f"{id_prefix}-{index + 1}",
            job_step_id=start_job_step_id + index,
            assignment_revision=1,
            items=parse_items(spec),
            pinky=MockPinkyArrival(already_arrived=pinky_delay_s <= 0, delay_s=pinky_delay_s),
        )
        for index, spec in enumerate(specs)
    )


_FROZEN_DELIVER_QUEUE: tuple[MockOrder, ...] = (
    MockOrder(
        order_id="mock-deliver-1",
        job_step_id=1001,
        assignment_revision=1,
        items=(MockOrderItem(1, "dumpling", 2),),
        pinky=MockPinkyArrival(already_arrived=True),
    ),
    MockOrder(
        order_id="mock-deliver-2",
        job_step_id=1002,
        assignment_revision=1,
        items=(MockOrderItem(1, "porkbelly", 1),),
        # 도착 지연 케이스: 3초 뒤 도착 — deliver.py가 그 전에 인계 단계로
        # 안 넘어가는지 확인하는 용도.
        pinky=MockPinkyArrival(already_arrived=False, delay_s=3.0),
    ),
    MockOrder(
        order_id="mock-deliver-3",
        job_step_id=1003,
        assignment_revision=1,
        items=(MockOrderItem(1, "icebar", 1), MockOrderItem(2, "icecorn", 3)),
        pinky=MockPinkyArrival(already_arrived=True),
    ),
)

_FROZEN_STORE_QUEUE: tuple[MockOrder, ...] = (
    MockOrder(
        order_id="mock-store-1",
        job_step_id=2001,
        assignment_revision=1,
        items=(MockOrderItem(1, "icecorn", 1),),
        pinky=MockPinkyArrival(already_arrived=True),
    ),
    MockOrder(
        order_id="mock-store-2",
        job_step_id=2002,
        assignment_revision=1,
        items=(MockOrderItem(1, "dumpling", 1),),
        pinky=MockPinkyArrival(already_arrived=True),
    ),
)

# 냉장(chilled)/상온(ambient) 품목은 아직 정책이 학습되지 않았다
# (policy_catalog.py 참고 — 카탈로그에 zone="chilled"/"ambient" 항목이 하나도
# 없다). 그래서 기본 큐도 비워 둔다. --order로 직접 넣으면 policy_catalog가
# 알아서 zone 불일치/미학습을 fail-closed로 잡아준다. 품목이 추가되면 여기에
# _FROZEN_*_QUEUE와 같은 형태로 채울 것.
_DELIVER_QUEUES: dict[str, tuple[MockOrder, ...]] = {
    "frozen": _FROZEN_DELIVER_QUEUE,
    "chilled": (),
    "ambient": (),
}
_STORE_QUEUES: dict[str, tuple[MockOrder, ...]] = {
    "frozen": _FROZEN_STORE_QUEUE,
    "chilled": (),
    "ambient": (),
}


def default_deliver_queue(zone: str) -> tuple[MockOrder, ...]:
    """출고(deliver.py) 테스트용 임의 주문 큐. zone별로 다르다 (frozen만 채워져 있음)."""
    try:
        return _DELIVER_QUEUES[zone]
    except KeyError:
        raise ValueError(f"unknown zone={zone!r}; known: {sorted(_DELIVER_QUEUES)}") from None


def default_store_queue(zone: str) -> tuple[MockOrder, ...]:
    """입고(store.py) 테스트용 임의 주문 큐. deliver와 동일 골격, zone별로 다르다."""
    try:
        return _STORE_QUEUES[zone]
    except KeyError:
        raise ValueError(f"unknown zone={zone!r}; known: {sorted(_STORE_QUEUES)}") from None
