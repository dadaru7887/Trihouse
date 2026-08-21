import json
import re

from .conftest import DEV_SEED_SQL, HARDWARE_SEED_SQL, REPOSITORY_ROOT


FEATURES_JSONL = (
    REPOSITORY_ROOT
    / "control_ui/rmf_control_ui/data/import"
    / "trihouse_test_01_physical_features.new_map_2.jsonl"
)
SEED_PATHS = (DEV_SEED_SQL, HARDWARE_SEED_SQL)
EXPECTED_WORKERS = {
    "W-FIELD-01": "operator",
    "W-FIELD-02": "operator",
    "W-CONTROL-01": "safety_manager",
}
EXPECTED_INVENTORY_LOTS = {
    "LOT-AMB-ORANGE-001",
    "LOT-AMB-STRAWBERRY-001",
    "LOT-AMB-MANDARIN-001",
    "LOT-CHL-COFFEE-001",
    "LOT-CHL-SANDWICH-001",
    "LOT-CHL-YOGURT-001",
    "LOT-CHL-MILK-001",
    "LOT-FRZ-PORKBELLY-001",
    "LOT-FRZ-DUMPLING-001",
    "LOT-FRZ-ICEBAR-001",
    "LOT-FRZ-ICECONE-001",
}


def _records() -> list[dict]:
    return [
        json.loads(line)
        for line in FEATURES_JSONL.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _insert_values(sql: str, table: str) -> str:
    match = re.search(
        rf"INSERT INTO\s+{table}\b.*?VALUES\s*(.*?)\s*ON DUPLICATE KEY UPDATE",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    assert match is not None, f"missing INSERT for {table}"
    return match.group(1)


def _sql_number(value: float) -> str:
    return str(float(value)).rstrip("0").rstrip(".") if "." in str(float(value)) else str(int(value))


def test_physical_feature_source_uses_new_map_2_as_its_operating_map() -> None:
    records = _records()

    assert len(records) == 13
    assert {record["target_map_name"] for record in records} == {"new_map_2"}


def test_both_seeds_copy_all_measured_waypoint_poses_from_new_map_2() -> None:
    waypoints = [record for record in _records() if record["record_type"] == "waypoint"]
    assert len(waypoints) == 8

    for seed_path in SEED_PATHS:
        sql = seed_path.read_text(encoding="utf-8")
        for waypoint in waypoints:
            pose = waypoint["map_pose"]
            expected_fields = (
                waypoint["location_code"],
                waypoint["rmf_waypoint_name"],
                _sql_number(pose["x"]),
                _sql_number(pose["y"]),
                _sql_number(pose["yaw"]),
            )
            assert all(value in sql for value in expected_fields), (
                f"{seed_path.name} does not match {waypoint['location_code']}"
            )
        assert sql.count("'new_map_2'") >= len(waypoints)


def test_physical_waypoints_reuse_parent_ids_without_reading_the_insert_target() -> None:
    for seed_path in SEED_PATHS:
        sql = seed_path.read_text(encoding="utf-8")
        physical_start = sql.index("-- EN: These provisional poses")
        final_slot_markers = (
            marker
            for marker in ("-- EN: Final storage slots", "-- Each final storage slot")
            if marker in sql[physical_start:]
        )
        physical_end = min(sql.index(marker, physical_start) for marker in final_slot_markers)
        physical_insert = sql[physical_start:physical_end]

        assert sql.index("SET @wh_amb_id") < physical_start
        assert "(SELECT location_id FROM locations" not in physical_insert
        assert "@wh_amb_id" in physical_insert
        assert "@wh_chl_id" in physical_insert
        assert "@wh_frz_id" in physical_insert


def test_both_seeds_define_two_field_workers_and_one_control_safety_manager() -> None:
    for seed_path in SEED_PATHS:
        workers = _insert_values(seed_path.read_text(encoding="utf-8"), "workers")
        pairs = dict(
            re.findall(
                r"\('([^']+)',\s*'[^']+',\s*'[^']+',\s*'(operator|safety_manager)'",
                workers,
            )
        )
        assert pairs == EXPECTED_WORKERS
        for worker_id in EXPECTED_WORKERS:
            assert f"('{worker_id}', '{worker_id}'," in workers
        assert "'W-CONTROL-01', 'W-CONTROL-01', 'AI-Server-4060 Control Operator'" in workers


def test_real_inventory_is_identical_in_development_and_hardware_seeds() -> None:
    seeded_lots = []
    for seed_path in SEED_PATHS:
        inventory = _insert_values(
            seed_path.read_text(encoding="utf-8"), "inventory_lots"
        )
        lot_codes = set(re.findall(r"'((?:LOT)-(?:AMB|CHL|FRZ)-[^']+)'", inventory))
        assert lot_codes == EXPECTED_INVENTORY_LOTS
        seeded_lots.append(re.sub(r"\s+", " ", inventory).strip())

    assert seeded_lots[0] == seeded_lots[1]


def test_hardware_seed_waits_for_real_device_heartbeats() -> None:
    sql = HARDWARE_SEED_SQL.read_text(encoding="utf-8")

    assert not re.search(r"INSERT INTO\s+device_states\b", sql, re.IGNORECASE)


def test_mobile_devices_use_new_map_2_fleet_and_measured_chargers() -> None:
    for seed_path in SEED_PATHS:
        devices = _insert_values(seed_path.read_text(encoding="utf-8"), "devices")
        assert devices.count("'new_map_2_pinky'") == 2
        assert "location_code = 'TRIHOUSE-TEST-01-CHG-01'" in devices
        assert "location_code = 'TRIHOUSE-TEST-01-CHG-02'" in devices
