"""입고 바구니 하나를 냉동→냉장→상온 고정 순서로 어느 구역까지 들러야 하는지 계산한다.

방문 순서는 고정(냉동→냉장→상온)이지만, 바구니에 없는 구역은 건너뛴다 — 예를
들어 바구니에 냉동 품목만 실려 있으면 냉동만 들렀다가 바로 대기 장소로
돌아간다. 이 파일은 그 "어느 구역을 들를지" 판단만 하는 순수 함수라 하드웨어
없이도(로봇팔·카메라 연결 없이) 바로 테스트할 수 있다 — 실제 pick+place
실행은 store_basket.py가 이어서 맡는다.

zone 판정은 출고용 카탈로그(policy_catalog.lookup, 즉 _CATALOG)를 쓴다 —
입고 정책이 학습됐는지(policy_catalog.lookup_store, 즉 _STORE_CATALOG)와
무관하게, 상품의 물리적 홈 구역은 고정돼 있기 때문이다(상온 3종은 아직
입고 정책이 하나도 없어도 상온 구역 소속인 것은 변하지 않는다). 그래서
카탈로그에 아예 없는 product_code는 policy_catalog.UnknownProductError로
그대로 fail-closed 전파된다 — 어느 구역으로 보내야 할지 모르는 물건을
임의로 아무 구역에나 넣지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import mock_inputs
import policy_catalog

ZONE_VISIT_ORDER = ("frozen", "chilled", "ambient")


@dataclass(frozen=True)
class ZoneVisit:
    zone: str
    items: tuple[mock_inputs.MockOrderItem, ...]


def plan_zone_visits(items: Sequence[mock_inputs.MockOrderItem]) -> tuple[ZoneVisit, ...]:
    """바구니 품목을 물리적 홈 구역별로 묶어 고정 순서로 정렬한다.

    품목이 하나도 없는 구역은 결과에서 아예 빠진다(방문 스킵). 반환 튜플이
    비어 있으면 바구니 자체가 비어 있었다는 뜻이다.
    """
    by_zone: dict[str, list[mock_inputs.MockOrderItem]] = {zone: [] for zone in ZONE_VISIT_ORDER}
    for item in items:
        zone = policy_catalog.lookup(item.product_code).zone
        by_zone[zone].append(item)
    return tuple(
        ZoneVisit(zone, tuple(zone_items))
        for zone in ZONE_VISIT_ORDER
        if (zone_items := by_zone[zone])
    )
