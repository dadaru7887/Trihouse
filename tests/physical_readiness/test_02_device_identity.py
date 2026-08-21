import re

from .conftest import BASELINE_SQL, DEV_SEED_SQL, HARDWARE_SEED_SQL, REPOSITORY_ROOT


CANONICAL_DEVICE_IDS = {"PK_01", "PK_02", "OMX_01", "OMX_02"}


def _seeded_device_id_name_pairs(sql: str) -> set[tuple[str, str]]:
    devices_insert = re.search(
        r"INSERT INTO devices\b.*?VALUES\s*(.*?)\s*ON DUPLICATE KEY UPDATE",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    assert devices_insert is not None
    return set(re.findall(r"\('([^']+)',\s*'(?:mobile|arm)',\s*'([^']+)'", devices_insert.group(1)))


def test_every_seed_routes_and_displays_devices_by_the_same_canonical_id():
    for seed_path in (HARDWARE_SEED_SQL, DEV_SEED_SQL):
        pairs = _seeded_device_id_name_pairs(seed_path.read_text(encoding="utf-8"))
        assert {device_id for device_id, _ in pairs} == CANONICAL_DEVICE_IDS
        assert all(device_id == name for device_id, name in pairs)


def test_database_rejects_a_device_name_that_differs_from_its_id():
    sql = BASELINE_SQL.read_text(encoding="utf-8")

    assert re.search(
        r"CONSTRAINT\s+chk_devices_name_matches_device_id\s+CHECK\s*\(\s*name\s*=\s*device_id\s*\)",
        sql,
        re.IGNORECASE,
    )


def test_database_accepts_only_the_approved_command_ids():
    sql = BASELINE_SQL.read_text(encoding="utf-8")
    constraint = re.search(
        r"CONSTRAINT\s+chk_devices_command_id\s+CHECK\s*\(\s*device_id\s+IN\s*\((.*?)\)\s*\)",
        sql,
        re.IGNORECASE | re.DOTALL,
    )

    assert constraint is not None
    assert set(re.findall(r"'([^']+)'", constraint.group(1))) == CANONICAL_DEVICE_IDS


def test_hardware_seed_does_not_create_demo_orders_or_inventory():
    sql = HARDWARE_SEED_SQL.read_text(encoding="utf-8")

    for table in ("orders", "order_lines", "inventory_lots", "jobs", "job_steps"):
        assert not re.search(rf"INSERT INTO\s+{table}\b", sql, re.IGNORECASE)
    assert "'project1'," not in sql
    assert not any(name in sql for name in ("'픽업1'", "'드랍오프1'", "'충전1'", "'충전2'"))


def test_map_publication_projects_the_command_id_not_the_authoring_label():
    source = (REPOSITORY_ROOT / "fms_gateway/app/repositories.py").read_text(encoding="utf-8")
    projection = source[source.index("INSERT INTO devices") : source.index("SELECT map_revision", source.index("INSERT INTO devices"))]

    assert 'robot["display_name"]' not in projection
    assert projection.count('robot["robot_id"]') >= 3
