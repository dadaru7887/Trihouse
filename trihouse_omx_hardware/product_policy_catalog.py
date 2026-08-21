"""Validate the canonical DB-product to ACT-policy mapping."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


KNOWN_ZONES = frozenset({"ambient", "chilled", "frozen"})


class ProductPolicyError(ValueError):
    """The catalog cannot identify one safe policy for the requested product."""


@dataclass(frozen=True)
class ProductPolicy:
    product_code: str
    policy_key: str
    policy_repo_id: str
    temperature_zone: str


class ProductPolicyCatalog:
    """One-to-one mapping kept outside DB command identity.

    EN: The DB SKU remains the audit identity; only the hardware-policy boundary
    translates it to the teammate's trained policy name.
    KO: DB SKU는 감사·주문 식별자로 유지하고, 하드웨어 정책 경계에서만 팀원이
    학습한 정책 이름으로 변환한다.
    """

    def __init__(self, entries: dict[str, ProductPolicy]) -> None:
        self._entries = dict(entries)

    @classmethod
    def load(cls, path: Path) -> "ProductPolicyCatalog":
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("schema_version") != 1:
            raise ProductPolicyError("UNSUPPORTED_SCHEMA")
        raw_products = document.get("products")
        if not isinstance(raw_products, dict) or not raw_products:
            raise ProductPolicyError("EMPTY_CATALOG")

        entries: dict[str, ProductPolicy] = {}
        policy_keys: set[str] = set()
        for product_code, raw in raw_products.items():
            if not isinstance(product_code, str) or not product_code.startswith("SKU-"):
                raise ProductPolicyError("INVALID_PRODUCT_CODE")
            if not isinstance(raw, dict):
                raise ProductPolicyError(f"INVALID_POLICY_ENTRY:{product_code}")
            policy_key = str(raw.get("policy_key", "")).strip()
            repo_id = str(raw.get("policy_repo_id", "")).strip()
            zone = str(raw.get("temperature_zone", "")).strip()
            if not policy_key or not repo_id or zone not in KNOWN_ZONES:
                raise ProductPolicyError(f"INCOMPLETE_POLICY_ENTRY:{product_code}")
            if policy_key in policy_keys:
                raise ProductPolicyError(f"DUPLICATE_POLICY_KEY:{policy_key}")
            policy_keys.add(policy_key)
            entries[product_code] = ProductPolicy(
                product_code=product_code,
                policy_key=policy_key,
                policy_repo_id=repo_id,
                temperature_zone=zone,
            )
        return cls(entries)

    @property
    def product_codes(self) -> tuple[str, ...]:
        return tuple(self._entries)

    def lookup(
        self, product_code: str, *, temperature_zone: str | None = None
    ) -> ProductPolicy:
        try:
            entry = self._entries[product_code]
        except KeyError:
            raise ProductPolicyError(f"UNKNOWN_PRODUCT:{product_code}") from None
        if temperature_zone is not None and entry.temperature_zone != temperature_zone:
            raise ProductPolicyError(
                f"ZONE_MISMATCH:{product_code}:{entry.temperature_zone}:{temperature_zone}"
            )
        return entry


__all__ = ["ProductPolicy", "ProductPolicyCatalog", "ProductPolicyError"]
