"""상품 코드 -> ACT 정책 HF repo_id 매핑.

냉동 4종(dumpling/porkbelly/icebar/icecorn)에 이어 냉장 4종(milk/yogurt/
sandwich/coffee), 상온 3종(mandarin/strawberry/orange)까지 총 11종 학습
완료(2026-08-21, https://huggingface.co/2usang 에서 확인 — 사용자 확인).
product_code는 policy_repo_id의 "act_trihouse-" 뒤 부분과 그대로 맞췄다.

주의: 여기 쓰는 product_code("dumpling" 등)는 실제 DB `job_items.product_code`와
같은 문자열인지 아직 확인되지 않았다 (조사 결과 3번 항목 참고 — DB엔 별도
상품명 카탈로그 테이블이 없고 product_code는 비즈니스 코드일 뿐이다). 실제
관제 연동 시 이 매핑 테이블의 key를 팀이 쓰는 실제 product_code로 맞춰야 한다.
지금은 mock_inputs.py도 이 key를 그대로 쓰므로 1단계 자체 테스트에는 문제없다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyEntry:
    product_code: str
    label_ko: str
    policy_repo_id: str
    dataset_repo_id: str
    zone: str


_CATALOG: dict[str, PolicyEntry] = {
    entry.product_code: entry
    for entry in (
        PolicyEntry("dumpling", "냉동만두", "2usang/act_trihouse-dumpling", "2usang/trihouse-dumpling", "frozen"),
        PolicyEntry("porkbelly", "삼겹살", "2usang/act_trihouse-porkbelly", "2usang/trihouse-porkbelly", "frozen"),
        PolicyEntry("icebar", "핑크 하드 아이스크림", "2usang/act_trihouse-icebar", "2usang/trihouse-icebar", "frozen"),
        PolicyEntry("icecorn", "아이스콘", "2usang/act_trihouse-icecorn", "2usang/trihouse-icecorn", "frozen"),
        PolicyEntry("milk", "우유", "2usang/act_trihouse-milk", "2usang/trihouse-milk", "chilled"),
        PolicyEntry("yogurt", "요거트", "2usang/act_trihouse-yogurt", "2usang/trihouse-yogurt", "chilled"),
        PolicyEntry("sandwich", "샌드위치", "2usang/act_trihouse-sandwich", "2usang/trihouse-sandwich", "chilled"),
        PolicyEntry("coffee", "커피", "2usang/act_trihouse-coffee", "2usang/trihouse-coffee", "chilled"),
        PolicyEntry("mandarin", "귤", "2usang/act_trihouse-mandarin", "2usang/trihouse-mandarin", "ambient"),
        PolicyEntry("strawberry", "딸기", "2usang/act_trihouse-strawberry", "2usang/trihouse-strawberry", "ambient"),
        PolicyEntry("orange", "오렌지", "2usang/act_trihouse-orange", "2usang/trihouse-orange", "ambient"),
    )
}


class UnknownProductError(KeyError):
    """정책이 없는 상품 코드. 모르는 물체를 임의로 집으러 가지 않도록 fail-closed."""


def lookup(product_code: str, *, zone: str | None = None) -> PolicyEntry:
    """출고(deliver, 선반→바구니) 정책 조회.

    zone을 주면 deliver.py --zone이 자기 구역이 아닌 품목을 실수로 집으러
    가지 않도록 막는다 — 예를 들어 --zone chilled로 "dumpling"(frozen 품목)을
    주문하면 카탈로그에 있어도 zone 불일치로 fail-closed 한다.
    """
    try:
        entry = _CATALOG[product_code]
    except KeyError:
        raise UnknownProductError(
            f"no trained pick policy for product_code={product_code!r}; "
            f"known: {sorted(_CATALOG)}"
        ) from None
    if zone is not None and entry.zone != zone:
        raise UnknownProductError(
            f"product_code={product_code!r} belongs to zone={entry.zone!r}, not zone={zone!r}; "
            f"known for zone={zone!r}: {known_product_codes(zone=zone)}"
        )
    return entry


def known_product_codes(*, zone: str | None = None) -> tuple[str, ...]:
    if zone is None:
        return tuple(_CATALOG)
    return tuple(code for code, entry in _CATALOG.items() if entry.zone == zone)


# 입고(store, 바구니→선반) 전용 카탈로그. 냉동만두 입고(2026-08-23, 사용자
# 확인)를 시작으로 하나씩 채워진다 — 출고용 체크포인트(_CATALOG)를 방향만
# 바꿔서 쓰면 안 된다(집는 것과 내려놓는 것은 다른 모션이라 학습이 따로 필요).
# 아직 없는 product_code는 store.py가 UnknownStorePolicyError로 fail-closed
# 하고, --policy-repo-id-override로만(배관 테스트 목적 한정, 의미상 올바른
# 동작 아님) 우회 가능하다.
_STORE_CATALOG: dict[str, PolicyEntry] = {
    entry.product_code: entry
    for entry in (
        PolicyEntry(
            "dumpling", "냉동만두",
            "2usang/act_trihouse-dumpling-inbound", "2usang/trihouse-dumpling-inbound",
            "frozen",
        ),
    )
}


class UnknownStorePolicyError(KeyError):
    """아직 입고(place) 정책이 학습되지 않은 상품 코드."""


def lookup_store(product_code: str, *, zone: str | None = None) -> PolicyEntry:
    try:
        entry = _STORE_CATALOG[product_code]
    except KeyError:
        raise UnknownStorePolicyError(
            f"no trained place policy for product_code={product_code!r} yet "
            "(입고 데이터 미녹화 — trihouse_arm_context_summary.md 9번 항목). "
            "plumbing 테스트만 하려면 --policy-repo-id-override로 pick 체크포인트를 "
            "강제 지정할 것 (의미상 올바른 동작이 아님)."
        ) from None
    if zone is not None and entry.zone != zone:
        raise UnknownStorePolicyError(
            f"product_code={product_code!r} belongs to zone={entry.zone!r}, not zone={zone!r}"
        )
    return entry
