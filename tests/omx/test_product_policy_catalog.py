from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
CATALOG_FILE = ROOT / "config" / "omx_product_policies.yaml"
EXPECTED = {
    "SKU-ORANGE": ("orange", "ambient"),
    "SKU-STRAWBERRY": ("strawberry", "ambient"),
    "SKU-MANDARIN": ("mandarin", "ambient"),
    "SKU-COFFEE": ("coffee", "chilled"),
    "SKU-SANDWICH": ("sandwich", "chilled"),
    "SKU-YOGURT": ("yogurt", "chilled"),
    "SKU-MILK": ("milk", "chilled"),
    "SKU-PORKBELLY": ("porkbelly", "frozen"),
    "SKU-DUMPLING": ("dumpling", "frozen"),
    "SKU-ICEBAR": ("icebar", "frozen"),
    "SKU-ICECONE": ("icecorn", "frozen"),
}


def _types():
    assert CATALOG_FILE.is_file(), "the canonical OMX product catalog is missing"
    from trihouse_omx_hardware.product_policy_catalog import (
        ProductPolicyCatalog,
        ProductPolicyError,
    )

    return ProductPolicyCatalog, ProductPolicyError


def test_every_seeded_sku_maps_one_to_one_to_the_trained_policy_name() -> None:
    ProductPolicyCatalog, _ = _types()
    catalog = ProductPolicyCatalog.load(CATALOG_FILE)

    assert set(catalog.product_codes) == set(EXPECTED)
    actual = {
        code: (catalog.lookup(code).policy_key, catalog.lookup(code).temperature_zone)
        for code in catalog.product_codes
    }
    assert actual == EXPECTED
    assert len({catalog.lookup(code).policy_key for code in catalog.product_codes}) == 11


def test_lookup_rejects_a_product_from_the_wrong_temperature_zone() -> None:
    ProductPolicyCatalog, ProductPolicyError = _types()
    catalog = ProductPolicyCatalog.load(CATALOG_FILE)

    with pytest.raises(ProductPolicyError, match="ZONE_MISMATCH"):
        catalog.lookup("SKU-DUMPLING", temperature_zone="chilled")


def test_catalog_rejects_duplicate_policy_keys(tmp_path: Path) -> None:
    ProductPolicyCatalog, ProductPolicyError = _types()
    path = tmp_path / "duplicate.yaml"
    path.write_text(
        "schema_version: 1\n"
        "products:\n"
        "  SKU-A:\n"
        "    policy_key: shared\n"
        "    policy_repo_id: repo/a\n"
        "    temperature_zone: ambient\n"
        "  SKU-B:\n"
        "    policy_key: shared\n"
        "    policy_repo_id: repo/b\n"
        "    temperature_zone: chilled\n",
        encoding="utf-8",
    )

    with pytest.raises(ProductPolicyError, match="DUPLICATE_POLICY_KEY"):
        ProductPolicyCatalog.load(path)


def test_unknown_product_fails_closed() -> None:
    ProductPolicyCatalog, ProductPolicyError = _types()
    catalog = ProductPolicyCatalog.load(CATALOG_FILE)

    with pytest.raises(ProductPolicyError, match="UNKNOWN_PRODUCT"):
        catalog.lookup("SKU-NOT-TRAINED")
