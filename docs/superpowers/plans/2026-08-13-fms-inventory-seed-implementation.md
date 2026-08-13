# FMS Inventory Seed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the disposable MySQL schema tests and development seed reflect the authoritative `schema_mysql.sql`, the three warehouse/twelve slot layout, and all eleven QR-backed inventory lots.

**Architecture:** `db/schema_mysql.sql` remains the structural source of truth. `db/seed_dev.sql` inserts only known warehouse, slot, inventory, device, worker, and smoke-job data; unknown warehouse RMF waypoint and pose fields remain NULL until the UI publish path projects them. Integration tests query real MySQL metadata and seeded rows instead of asserting brittle table, column, or row counts.

**Tech Stack:** MySQL 8.4, SQL, Python 3.12, pytest, mysql-connector-python, Docker Compose

## Global Constraints

- `db/schema_mysql.sql` is the only new-install schema authority.
- Do not add or remove schema columns for the seed data.
- Do not invent ArUco marker IDs, warehouse waypoint names, or map poses.
- Warehouse display names are `상온창고`, `냉장창고`, and `냉동창고`; stable codes retain the `-01` suffix.
- Warehouse `metadata`, `map_name`, `rmf_waypoint_name`, and `pose_*` values remain NULL in the seed.
- Slot metadata contains only `shelf_level` and `slot_index`.
- `inventory_lots.lot_code` must exactly match `docs/database/item_qr_payloads.json`.
- `received_at` uses the first insert's `CURRENT_TIMESTAMP(6)` and is not overwritten by duplicate-key updates.
- Work only against the disposable local test DB at `127.0.0.1:3307` during automated integration tests.
- Preserve unrelated dirty-worktree changes and stage only files named by each task.
- QR pick-approval API and automatic outbound orchestration are a separate phase after waypoint connection test 1.

## File Structure

- Modify `db/schema_mysql.sql`: add missing English metadata comments only; do not change column definitions or constraints.
- Modify `db/seed_dev.sql`: insert the approved warehouse, slot, inventory, and smoke-job data.
- Modify `fms_gateway/tests/integration/test_schema.py`: assert schema table sets, comment quality, seed hierarchy, QR agreement, and idempotency through real MySQL.
- Modify `fms_gateway/tests/integration/test_read_api.py`: expect the current device IDs and eleven QR lots.
- Modify `fms_gateway/tests/integration/test_inventory_adjustment.py`: use a low-quantity QR lot without assuming the old 100-unit development lot.
- Modify `db/tests/test_schema_comments.py`: remove fixed metadata counts while retaining a fast static English-comment check.
- Modify `docs/deployment/database_demo.md`, `docs/deployment/environment_overview.md`, and `docs/deployment/local_simulation_demo.md`: remove obsolete fixed schema counts and document contract-based verification.

---

### Task 1: Make schema metadata tests express the actual contract

**Files:**
- Modify: `fms_gateway/tests/integration/test_schema.py:1-86`
- Modify: `db/tests/test_schema_comments.py:1-20`
- Modify: `db/schema_mysql.sql:25-172`
- Test: `fms_gateway/tests/integration/test_schema.py`
- Test: `db/tests/test_schema_comments.py`

**Interfaces:**
- Consumes: MySQL `information_schema.tables` and `information_schema.columns` for `trihouse_fms` and `trihouse_recovery`.
- Produces: exact required table-name sets and the invariant that every table/column comment is non-empty ASCII without Korean text.

- [ ] **Step 1: Replace table-count assertions with exact required table sets**

Add these literals to `fms_gateway/tests/integration/test_schema.py`:

```python
FMS_TABLES = {
    "artifacts",
    "device_states",
    "devices",
    "incidents",
    "integration_messages",
    "inventory_lots",
    "inventory_moves",
    "job_items",
    "job_step_attempts",
    "job_steps",
    "jobs",
    "location_recovery_profiles",
    "locations",
    "map_features",
    "map_project_files",
    "map_project_fleets",
    "map_project_lanes",
    "map_project_robots",
    "map_project_waypoints",
    "map_projects",
    "map_revisions",
    "operation_events",
    "reservations",
    "workers",
}
RECOVERY_TABLES = {"recovery_episodes", "recovery_steps"}
```

Query `table_name` instead of `COUNT(*)` and assert set equality:

```python
assert {row["table_name"] for row in fms_tables} == FMS_TABLES
assert {row["table_name"] for row in recovery_tables} == RECOVERY_TABLES
```

The break this catches is a required table being omitted, renamed, or unexpectedly added without an intentional contract update.

- [ ] **Step 2: Make runtime comment checks reject empty and non-English comments**

Remove `len(tables) == 18` and `len(columns) == 253`. Use the table-set test for completeness and validate comment content independently:

```python
def _invalid_english_comment(value: object) -> bool:
    comment = str(value).strip()
    return not comment or not comment.isascii() or bool(re.search(r"[가-힣]", comment))


invalid = [
    f"{row['schema_name']}.{row['table_name']}"
    for row in tables
    if _invalid_english_comment(row["table_comment"])
]
```

Apply the same helper to `column_comment`. The break this catches is a real MySQL table or column exposing blank or encoding-sensitive metadata to the web UI.

- [ ] **Step 3: Remove static source-count change detectors**

Change `db/tests/test_schema_comments.py` to assert presence and content without `26` or `326`:

```python
assert table_comments
assert column_comments
comments = table_comments + column_comments
assert all(comment.strip() and comment.isascii() for comment in comments)
assert not any(KOREAN_TEXT.search(comment) for comment in comments)
```

The integration test remains responsible for proving every actual MySQL column has a comment.

- [ ] **Step 4: Run the new tests and verify RED**

Run:

```bash
cd /home/syw/Trihouse
FMS_DB_HOST=127.0.0.1 \
FMS_DB_PORT=3307 \
FMS_DB_USER=fms_gateway \
FMS_DB_PASSWORD=test_gateway_password \
FMS_DB_ADMIN_USER=root \
FMS_DB_ADMIN_PASSWORD=test_root_password \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
/tmp/fms-gateway-venv/bin/python -m pytest -v \
  fms_gateway/tests/integration/test_schema.py::test_all_columns_have_english_comments \
  db/tests/test_schema_comments.py
```

Expected: the runtime test fails and names the 46 currently blank comments under `map_projects`, `map_project_waypoints`, `map_project_lanes`, `map_project_files`, `map_project_fleets`, `map_project_robots`, and `map_revisions`. The static test still passes because it checks comments that already exist.

- [ ] **Step 5: Add comments to the 46 uncommented schema columns**

Add `COMMENT` clauses without changing types, defaults, keys, or constraints. Use these exact descriptions:

```text
map_projects.created_at = Timestamp when the map project was created.
map_projects.updated_at = Timestamp when the map project was last updated.
map_project_waypoints.project_id = Identifier of the parent map project.
map_project_waypoints.active = Indicates whether the waypoint belongs to the active draft.
map_project_lanes.project_id = Identifier of the parent map project.
map_project_lanes.start_waypoint_uuid = UUID of the lane start waypoint.
map_project_lanes.end_waypoint_uuid = UUID of the lane end waypoint.
map_project_lanes.direction = Allowed travel direction for the lane.
map_project_lanes.speed_limit = Optional lane speed limit in meters per second.
map_project_lanes.orientation = Optional robot orientation constraint for the lane.
map_project_lanes.mutex_group = Optional mutual-exclusion group used by the lane.
map_project_lanes.active = Indicates whether the lane belongs to the active draft.
map_project_files.project_id = Identifier of the parent map project.
map_project_files.file_name = File name unique within the map project.
map_project_files.kind = Generated file category.
map_project_files.description = Human-readable description of the generated file.
map_project_files.executable = Indicates whether the generated file must be executable.
map_project_files.content = Text content of the generated file.
map_project_files.generated_at = Timestamp when the file content was generated.
map_project_fleets.project_id = Identifier of the parent map project.
map_project_fleets.fleet_name = Open-RMF fleet name for the map project.
map_project_fleets.settings = JSON object containing draft fleet parameters.
map_project_fleets.updated_at = Timestamp when the fleet settings were last updated.
map_project_robots.project_id = Identifier of the parent map project.
map_project_robots.robot_id = Stable robot identifier within the map project.
map_project_robots.seq = Stable display order within the map project.
map_project_robots.display_name = Robot name displayed in operator interfaces.
map_project_robots.model = Robot model name.
map_project_robots.kind = Robot role: mobile robot or workcell.
map_project_robots.data_source = Runtime source: mock, Gazebo, or real hardware.
map_project_robots.gz_name = Gazebo model and namespace name.
map_project_robots.zones = JSON array of zones the robot may serve.
map_project_robots.charger_waypoint_uuid = UUID of the assigned charger waypoint.
map_project_robots.spawn_x = Optional Gazebo spawn X coordinate in meters.
map_project_robots.spawn_y = Optional Gazebo spawn Y coordinate in meters.
map_project_robots.spawn_heading = Gazebo spawn heading in radians.
map_revisions.map_name = Name of the published map.
map_revisions.source_project_id = Identifier of the source map project.
map_revisions.draft_revision = Draft revision used to create the publication.
map_revisions.state = Publication state: published or retired.
map_revisions.building_sha256 = SHA-256 digest of the building YAML.
map_revisions.nav_graph_sha256 = SHA-256 digest of the navigation graph.
map_revisions.world_sha256 = SHA-256 digest of the Gazebo world.
map_revisions.manifest = JSON object containing the immutable publication manifest.
map_revisions.published_by = Worker or process that published the map.
map_revisions.published_at = Timestamp when the map revision was published.
```

- [ ] **Step 6: Run metadata tests and verify GREEN**

Run the command from Step 4 again.

Expected: both targets pass; the runtime test reports no blank/non-English column comments.

- [ ] **Step 7: Commit only schema metadata and contract tests**

```bash
git add db/schema_mysql.sql db/tests/test_schema_comments.py \
  fms_gateway/tests/integration/test_schema.py
git commit -m "test: verify schema contracts by content"
```

---

### Task 2: Write failing warehouse and QR inventory seed contracts

**Files:**
- Modify: `fms_gateway/tests/conftest.py:8-10`
- Modify: `fms_gateway/tests/integration/test_schema.py:336-355`
- Test: `fms_gateway/tests/integration/test_schema.py`

**Interfaces:**
- Consumes: `SEED_PATH`, `docs/database/item_qr_payloads.json`, and real seeded MySQL rows.
- Produces: literal contracts for warehouse hierarchy, slot metadata/state, eleven lot records, QR agreement, NULL waypoint fields, current received timestamps, and idempotency.

- [ ] **Step 1: Expose the QR payload path to integration tests**

Add to `fms_gateway/tests/conftest.py`:

```python
QR_PAYLOAD_PATH = REPOSITORY_ROOT / "docs" / "database" / "item_qr_payloads.json"
```

Import it with `json` in `test_schema.py`:

```python
import json
from conftest import QR_PAYLOAD_PATH, SEED_PATH, execute_sql_script
```

- [ ] **Step 2: Replace seed row-count assertions with warehouse and slot behavior assertions**

After applying the seed twice, query warehouse and slot rows. Assert these exact warehouse values:

```python
expected_warehouses = {
    "WH-AMB-01": ("상온창고", "ambient", "available"),
    "WH-CHL-01": ("냉장창고", "chilled", "available"),
    "WH-FRZ-01": ("냉동창고", "frozen", "available"),
}
```

Assert the exact slot contract using `(parent_code, shelf_level, slot_index, state)`:

```python
expected_slots = {
    "AMB-L1-S01": ("WH-AMB-01", 1, 1, "occupied"),
    "AMB-L1-S02": ("WH-AMB-01", 1, 2, "available"),
    "AMB-L2-S01": ("WH-AMB-01", 2, 1, "occupied"),
    "AMB-L2-S02": ("WH-AMB-01", 2, 2, "occupied"),
    "CHL-L1-S01": ("WH-CHL-01", 1, 1, "occupied"),
    "CHL-L1-S02": ("WH-CHL-01", 1, 2, "occupied"),
    "CHL-L2-S01": ("WH-CHL-01", 2, 1, "occupied"),
    "CHL-L2-S02": ("WH-CHL-01", 2, 2, "occupied"),
    "FRZ-L1-S01": ("WH-FRZ-01", 1, 1, "occupied"),
    "FRZ-L1-S02": ("WH-FRZ-01", 1, 2, "occupied"),
    "FRZ-L2-S01": ("WH-FRZ-01", 2, 1, "occupied"),
    "FRZ-L2-S02": ("WH-FRZ-01", 2, 2, "occupied"),
}
```

Query `JSON_UNQUOTE(JSON_EXTRACT(child.metadata, '$.shelf_level'))` and `slot_index` so MySQL returns scalar values. Assert warehouse metadata and all new warehouse/slot `map_name`, `rmf_waypoint_name`, and `pose_*` fields are NULL.

- [ ] **Step 3: Add the exact eleven-lot contract**

Assert each `lot_code` maps to `(product_code, item_name, temperature_zone, location_code, expiry_date, unit_weight_kg, available_qty, reserved_qty, state)` using these literals:

```python
expected_lots = {
    "LOT-AMB-ORANGE-001": ("SKU-ORANGE", "Orange", "ambient", "AMB-L2-S01", "2026-08-28", "0.200", 1, 0, "stored"),
    "LOT-AMB-STRAWBERRY-001": ("SKU-STRAWBERRY", "Strawberry", "ambient", "AMB-L2-S02", "2026-08-27", "0.250", 1, 0, "stored"),
    "LOT-AMB-MANDARIN-001": ("SKU-MANDARIN", "Mandarin", "ambient", "AMB-L1-S01", "2026-09-02", "0.120", 2, 0, "stored"),
    "LOT-CHL-COFFEE-001": ("SKU-COFFEE", "Coffee", "chilled", "CHL-L2-S01", "2026-10-31", "0.250", 1, 0, "stored"),
    "LOT-CHL-SANDWICH-001": ("SKU-SANDWICH", "Sandwich", "chilled", "CHL-L2-S02", "2026-09-10", "0.180", 2, 0, "stored"),
    "LOT-CHL-YOGURT-001": ("SKU-YOGURT", "Yogurt", "chilled", "CHL-L1-S01", "2026-09-30", "0.100", 2, 0, "stored"),
    "LOT-CHL-MILK-001": ("SKU-MILK", "Milk", "chilled", "CHL-L1-S02", "2026-09-20", "0.200", 1, 0, "stored"),
    "LOT-FRZ-PORKBELLY-001": ("SKU-PORKBELLY", "Pork belly", "frozen", "FRZ-L2-S01", "2027-08-13", "0.500", 2, 0, "stored"),
    "LOT-FRZ-DUMPLING-001": ("SKU-DUMPLING", "Dumpling", "frozen", "FRZ-L2-S02", "2027-08-20", "0.400", 1, 0, "stored"),
    "LOT-FRZ-ICEBAR-001": ("SKU-ICEBAR", "Ice bar", "frozen", "FRZ-L1-S01", "2027-08-25", "0.080", 2, 0, "stored"),
    "LOT-FRZ-ICECONE-001": ("SKU-ICECONE", "Ice cone", "frozen", "FRZ-L1-S02", "2027-08-31", "0.150", 2, 0, "stored"),
}
```

Convert returned `expiry_date` and `unit_weight_kg` with `str()` before tuple comparison.

- [ ] **Step 4: Assert QR agreement, current received time, empty-slot behavior, and smoke-job mapping**

Use literal assertions:

```python
qr_lots = {entry["lot"] for entry in json.loads(QR_PAYLOAD_PATH.read_text())}
assert set(actual_lots) == qr_lots == set(expected_lots)
assert mysql_db.one(
    "SELECT COUNT(*) AS count FROM inventory_lots lot "
    "JOIN locations loc ON loc.location_id = lot.location_id "
    "WHERE loc.location_code = 'AMB-L1-S02'"
)["count"] == 0
```

Capture `SELECT NOW(6) AS now` before the first seed and after the second seed, then assert every `received_at` lies within that DB-clock interval. Assert `JOB-DEV-001` joins to `LOT-AMB-ORANGE-001`, requested quantity `1`, and source `AMB-L2-S01`.

- [ ] **Step 5: Run the seed contract and verify RED**

Run:

```bash
cd /home/syw/Trihouse
FMS_DB_HOST=127.0.0.1 \
FMS_DB_PORT=3307 \
FMS_DB_USER=fms_gateway \
FMS_DB_PASSWORD=test_gateway_password \
FMS_DB_ADMIN_USER=root \
FMS_DB_ADMIN_PASSWORD=test_root_password \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
/tmp/fms-gateway-venv/bin/python -m pytest -v \
  fms_gateway/tests/integration/test_schema.py::test_development_seed_is_idempotent_and_complete
```

Expected: FAIL because `WH-AMB-01` and the QR lot set are absent from the current seed.

- [ ] **Step 6: Commit the verified failing seed contract**

```bash
git add fms_gateway/tests/conftest.py fms_gateway/tests/integration/test_schema.py
git commit -m "test: define warehouse QR seed contract"
```

---

### Task 3: Implement the approved locations and inventory seed

**Files:**
- Modify: `db/seed_dev.sql:4-153`
- Test: `fms_gateway/tests/integration/test_schema.py`

**Interfaces:**
- Consumes: the exact warehouse, slot, and lot literals from Task 2 and the tables defined by `db/schema_mysql.sql`.
- Produces: an idempotent development seed with 3 parent racks, 12 child slots, 11 QR lots, and an Orange smoke job.

- [ ] **Step 1: Preserve existing RMF operational Location rows**

Keep `A-SLOT-01`, `OUT-DOCK-01`, `CHG-01`, `CHG-02`, `IN-WAIT-01`, `NARROW-WAIT-01`, `OMX-WS-01`, and `OMX-WS-02` with their current `project1` waypoint mappings. Do not attach inventory lots to `A-SLOT-01`.

- [ ] **Step 2: Insert the three parent warehouse rows before child slots**

Use a separate idempotent statement so the self-referencing FK is satisfied:

```sql
INSERT INTO locations
  (location_code, name, location_type, zone_code, temperature_zone, state)
VALUES
  ('WH-AMB-01', '상온창고', 'rack', 'ambient', 'ambient', 'available'),
  ('WH-CHL-01', '냉장창고', 'rack', 'chilled', 'chilled', 'available'),
  ('WH-FRZ-01', '냉동창고', 'rack', 'frozen', 'frozen', 'available')
ON DUPLICATE KEY UPDATE
  name = VALUES(name),
  location_type = VALUES(location_type),
  zone_code = VALUES(zone_code),
  temperature_zone = VALUES(temperature_zone),
  state = VALUES(state);
```

Do not include `metadata`, map, waypoint, or pose columns so they remain NULL on a fresh seed.

- [ ] **Step 3: Insert all twelve child slots**

Use `parent_location_id` subqueries and only the approved metadata:

```sql
INSERT INTO locations
  (parent_location_id, location_code, name, location_type, zone_code,
   temperature_zone, state, metadata)
VALUES
  ((SELECT location_id FROM locations WHERE location_code = 'WH-AMB-01'),
   'AMB-L1-S01', '상온창고 1층 구역 1', 'slot', 'ambient', 'ambient',
   'occupied', JSON_OBJECT('shelf_level', 1, 'slot_index', 1)),
  ((SELECT location_id FROM locations WHERE location_code = 'WH-AMB-01'),
   'AMB-L1-S02', '상온창고 1층 구역 2', 'slot', 'ambient', 'ambient',
   'available', JSON_OBJECT('shelf_level', 1, 'slot_index', 2)),
  ((SELECT location_id FROM locations WHERE location_code = 'WH-AMB-01'),
   'AMB-L2-S01', '상온창고 2층 구역 1', 'slot', 'ambient', 'ambient',
   'occupied', JSON_OBJECT('shelf_level', 2, 'slot_index', 1)),
  ((SELECT location_id FROM locations WHERE location_code = 'WH-AMB-01'),
   'AMB-L2-S02', '상온창고 2층 구역 2', 'slot', 'ambient', 'ambient',
   'occupied', JSON_OBJECT('shelf_level', 2, 'slot_index', 2)),
  ((SELECT location_id FROM locations WHERE location_code = 'WH-CHL-01'),
   'CHL-L1-S01', '냉장창고 1층 구역 1', 'slot', 'chilled', 'chilled',
   'occupied', JSON_OBJECT('shelf_level', 1, 'slot_index', 1)),
  ((SELECT location_id FROM locations WHERE location_code = 'WH-CHL-01'),
   'CHL-L1-S02', '냉장창고 1층 구역 2', 'slot', 'chilled', 'chilled',
   'occupied', JSON_OBJECT('shelf_level', 1, 'slot_index', 2)),
  ((SELECT location_id FROM locations WHERE location_code = 'WH-CHL-01'),
   'CHL-L2-S01', '냉장창고 2층 구역 1', 'slot', 'chilled', 'chilled',
   'occupied', JSON_OBJECT('shelf_level', 2, 'slot_index', 1)),
  ((SELECT location_id FROM locations WHERE location_code = 'WH-CHL-01'),
   'CHL-L2-S02', '냉장창고 2층 구역 2', 'slot', 'chilled', 'chilled',
   'occupied', JSON_OBJECT('shelf_level', 2, 'slot_index', 2)),
  ((SELECT location_id FROM locations WHERE location_code = 'WH-FRZ-01'),
   'FRZ-L1-S01', '냉동창고 1층 구역 1', 'slot', 'frozen', 'frozen',
   'occupied', JSON_OBJECT('shelf_level', 1, 'slot_index', 1)),
  ((SELECT location_id FROM locations WHERE location_code = 'WH-FRZ-01'),
   'FRZ-L1-S02', '냉동창고 1층 구역 2', 'slot', 'frozen', 'frozen',
   'occupied', JSON_OBJECT('shelf_level', 1, 'slot_index', 2)),
  ((SELECT location_id FROM locations WHERE location_code = 'WH-FRZ-01'),
   'FRZ-L2-S01', '냉동창고 2층 구역 1', 'slot', 'frozen', 'frozen',
   'occupied', JSON_OBJECT('shelf_level', 2, 'slot_index', 1)),
  ((SELECT location_id FROM locations WHERE location_code = 'WH-FRZ-01'),
   'FRZ-L2-S02', '냉동창고 2층 구역 2', 'slot', 'frozen', 'frozen',
   'occupied', JSON_OBJECT('shelf_level', 2, 'slot_index', 2))
ON DUPLICATE KEY UPDATE
  parent_location_id = VALUES(parent_location_id),
  name = VALUES(name),
  location_type = VALUES(location_type),
  zone_code = VALUES(zone_code),
  temperature_zone = VALUES(temperature_zone),
  state = VALUES(state),
  metadata = VALUES(metadata);
```

- [ ] **Step 4: Replace the two legacy lots with the eleven QR lots**

Use every literal in Task 2, include `unit_weight_kg`, and set `received_at` with `CURRENT_TIMESTAMP(6)` in every VALUES row. The duplicate-key update must update product, name, temperature, location, expiry, weight, available quantity, reserved quantity, and state, but must omit `received_at`:

```sql
ON DUPLICATE KEY UPDATE
  product_code = VALUES(product_code),
  item_name = VALUES(item_name),
  temperature_zone = VALUES(temperature_zone),
  location_id = VALUES(location_id),
  expiry_date = VALUES(expiry_date),
  unit_weight_kg = VALUES(unit_weight_kg),
  available_qty = VALUES(available_qty),
  reserved_qty = VALUES(reserved_qty),
  state = VALUES(state);
```

Remove `LOT-DEV-001` and `LOT-DEV-002`; leaving them would violate the exact QR-set contract.

- [ ] **Step 5: Point the smoke job at Orange without pre-verifying it**

Change `JOB-DEV-001.source_location_id` to `AMB-L2-S01`. Change its one `job_items` row to `SKU-ORANGE`, requested quantity `1`, and `LOT-AMB-ORANGE-001`; keep `verification_state='pending'`. Keep the navigation Step target as `A-SLOT-01` because warehouse-specific UI waypoints do not exist yet.

Extend the `jobs` duplicate-key clause so reapplying the seed also corrects its source and destination:

```sql
  source_location_id = VALUES(source_location_id),
  destination_location_id = VALUES(destination_location_id),
  due_at = VALUES(due_at),
  assigned_mobile_id = VALUES(assigned_mobile_id),
  context = VALUES(context);
```

`job_items` has no UNIQUE key on `(job_id, product_code)`, so do not use an ineffective
`ON DUPLICATE KEY UPDATE`. Update the existing smoke row first, then insert only when absent:

```sql
UPDATE job_items ji
JOIN jobs j ON j.job_id = ji.job_id
JOIN inventory_lots lot ON lot.lot_code = 'LOT-AMB-ORANGE-001'
SET ji.product_code = 'SKU-ORANGE',
    ji.requested_qty = 1,
    ji.completed_qty = 0,
    ji.lot_id = lot.lot_id,
    ji.verification_state = 'pending',
    ji.metadata = JSON_OBJECT('source', 'dev_seed')
WHERE j.job_code = 'JOB-DEV-001';

INSERT INTO job_items
  (job_id, product_code, requested_qty, completed_qty, lot_id,
   verification_state, metadata)
SELECT j.job_id, 'SKU-ORANGE', 1, 0, lot.lot_id, 'pending',
       JSON_OBJECT('source', 'dev_seed')
FROM jobs j
JOIN inventory_lots lot ON lot.lot_code = 'LOT-AMB-ORANGE-001'
WHERE j.job_code = 'JOB-DEV-001'
  AND NOT EXISTS (
    SELECT 1 FROM job_items existing WHERE existing.job_id = j.job_id
  );
```

- [ ] **Step 6: Run the seed contract and verify GREEN**

Run the command from Task 2 Step 5.

Expected: PASS with warehouses, slots, eleven lots, QR agreement, current received timestamps, and the Orange smoke job.

- [ ] **Step 7: Commit the seed implementation**

```bash
git add db/seed_dev.sql
git commit -m "feat: seed warehouse QR inventory"
```

---

### Task 4: Align read and inventory-adjustment integration tests

**Files:**
- Modify: `fms_gateway/tests/integration/test_read_api.py:29-51`
- Modify: `fms_gateway/tests/integration/test_inventory_adjustment.py:10-79`
- Test: `fms_gateway/tests/integration/test_read_api.py`
- Test: `fms_gateway/tests/integration/test_inventory_adjustment.py`

**Interfaces:**
- Consumes: the eleven-lot seed and current `PK_01`, `PK_02`, `OMX_01`, `OMX_02` device IDs.
- Produces: API integration tests that validate QR inventory without relying on list position or a 100-unit legacy lot.

- [ ] **Step 1: Update the read API expectations**

Assert the device set exactly as seeded:

```python
assert {row["device_id"] for row in devices.json()} == {
    "PK_01", "PK_02", "OMX_01", "OMX_02"
}
```

Assert the inventory lot-code set equals the eleven QR lots. For ordering behavior, assert the first three codes are the literal FEFO order:

```python
assert [row["lot_code"] for row in inventory.json()[:3]] == [
    "LOT-AMB-STRAWBERRY-001",
    "LOT-AMB-ORANGE-001",
    "LOT-AMB-MANDARIN-001",
]
```

- [ ] **Step 2: Make adjustment tests select a named lot**

Add:

```python
def inventory_lot_id(client, lot_code: str) -> int:
    return next(
        row["lot_id"]
        for row in client.get("/api/v1/inventory/lots").json()
        if row["lot_code"] == lot_code
    )
```

Use `LOT-AMB-MANDARIN-001` in all three tests. Change successful deltas from `-10` and `-7` to `-1`, expected quantities from `90`/`93` to `1`, and the conflict delta from `-96` to `-3`; assert the unchanged quantity is `2`.

- [ ] **Step 3: Run the API integration tests**

Run:

```bash
cd /home/syw/Trihouse
FMS_DB_HOST=127.0.0.1 \
FMS_DB_PORT=3307 \
FMS_DB_USER=fms_gateway \
FMS_DB_PASSWORD=test_gateway_password \
FMS_DB_ADMIN_USER=root \
FMS_DB_ADMIN_PASSWORD=test_root_password \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
/tmp/fms-gateway-venv/bin/python -m pytest -v \
  fms_gateway/tests/integration/test_read_api.py \
  fms_gateway/tests/integration/test_inventory_adjustment.py
```

Expected: all readiness, device, inventory, job, adjustment, idempotency, and atomic-conflict tests pass.

- [ ] **Step 4: Commit API integration-test alignment**

```bash
git add fms_gateway/tests/integration/test_read_api.py \
  fms_gateway/tests/integration/test_inventory_adjustment.py
git commit -m "test: align APIs with QR inventory seed"
```

---

### Task 5: Verify the full DB contract and update stale deployment documentation

**Files:**
- Modify: `docs/deployment/database_demo.md`
- Modify: `docs/deployment/environment_overview.md`
- Modify: `docs/deployment/local_simulation_demo.md`
- Test: `db/tests`
- Test: `fms_gateway/tests/integration`

**Interfaces:**
- Consumes: completed schema metadata, seed, and integration tests.
- Produces: a full passing disposable-DB verification and documentation that does not encode obsolete table/column counts.

- [ ] **Step 1: Replace obsolete fixed counts in deployment docs**

Replace claims such as `FMS 16개 + recovery 2개`, `18개 table`, and `253개 column` with this contract language:

```text
`db/schema_mysql.sql`에 선언된 FMS/Recovery 테이블 이름 집합과 모든 영문 metadata
주석을 통합 테스트로 검증한다. 테이블·컬럼 추가는 기준 스키마와 이름 집합을 함께
변경하며, 문서에는 쉽게 낡는 총개수를 운영 계약으로 사용하지 않는다.
```

Add the eleven QR lots and warehouse/slot query to `database_demo.md`:

```sql
SELECT
  lot.lot_code, lot.product_code, lot.item_name,
  lot.available_qty, lot.reserved_qty,
  slot.location_code AS slot_code,
  parent.location_code AS warehouse_code,
  JSON_UNQUOTE(JSON_EXTRACT(slot.metadata, '$.shelf_level')) AS shelf_level,
  JSON_UNQUOTE(JSON_EXTRACT(slot.metadata, '$.slot_index')) AS slot_index
FROM trihouse_fms.inventory_lots lot
JOIN trihouse_fms.locations slot ON slot.location_id = lot.location_id
LEFT JOIN trihouse_fms.locations parent
  ON parent.location_id = slot.parent_location_id
ORDER BY warehouse_code, shelf_level, slot_index;
```

- [ ] **Step 2: Run static DB tests**

```bash
cd /home/syw/Trihouse
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
/tmp/fms-gateway-venv/bin/python -m pytest -v db/tests
```

Expected: all static schema, migration, import, device, map-authoring, orchestration, and comment tests pass.

- [ ] **Step 3: Run the complete disposable MySQL integration suite**

```bash
cd /home/syw/Trihouse
FMS_DB_HOST=127.0.0.1 \
FMS_DB_PORT=3307 \
FMS_DB_USER=fms_gateway \
FMS_DB_PASSWORD=test_gateway_password \
FMS_DB_ADMIN_USER=root \
FMS_DB_ADMIN_PASSWORD=test_root_password \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
/tmp/fms-gateway-venv/bin/python -m pytest -v fms_gateway/tests/integration
```

Expected: zero failures. The fixture intentionally drops `trihouse_fms` and `trihouse_recovery` after each test.

- [ ] **Step 4: Recreate the disposable DB for manual inspection**

```bash
cd /home/syw/Trihouse
docker compose -f compose.db_test.yaml down
docker compose -f compose.db_test.yaml up -d --wait mysql_test
```

Inspect only; do not run pytest while preserving this inspection state:

```bash
docker compose -f compose.db_test.yaml exec -T mysql_test \
  mysql -uroot -ptest_root_password trihouse_fms -e "
SELECT location_code, name, location_type, state, map_name, rmf_waypoint_name
FROM locations
WHERE location_code LIKE 'WH-%' OR location_code REGEXP '^(AMB|CHL|FRZ)-L[12]-S0[12]'
ORDER BY location_code;
SELECT lot_code, product_code, item_name, available_qty, received_at
FROM inventory_lots ORDER BY lot_code;"
```

Expected: 3 warehouse rows, 12 slot rows, and 11 inventory rows; warehouse/slot waypoint fields are NULL and `received_at` reflects container initialization time.

- [ ] **Step 5: Commit documentation updates**

```bash
git add docs/deployment/database_demo.md \
  docs/deployment/environment_overview.md \
  docs/deployment/local_simulation_demo.md
git commit -m "docs: describe QR inventory database verification"
```

---

### Task 6: Perform waypoint connection test 1 with the user

**Files:**
- No repository file changes unless the test exposes a Gateway defect.
- Inspect: `fms_gateway/app/repositories.py:856-925`
- Inspect: `fms_gateway/tests/integration/test_map_project_repository.py:47-99`

**Interfaces:**
- Consumes: a running DB/Gateway/UI, UI-created waypoints with location codes `WH-AMB-01`, `WH-CHL-01`, and `WH-FRZ-01`, and the existing map publication endpoint.
- Produces: evidence that UI draft save and publish automatically project waypoint name and pose into the matching parent warehouse Location rows.

- [ ] **Step 1: Record the pre-publish warehouse state**

```sql
SELECT location_code, map_name, rmf_waypoint_name, pose_x, pose_y, pose_yaw, metadata
FROM trihouse_fms.locations
WHERE location_code IN ('WH-AMB-01', 'WH-CHL-01', 'WH-FRZ-01')
ORDER BY location_code;
```

Expected: map, waypoint, and pose columns are NULL.

- [ ] **Step 2: Create one UI waypoint first**

In the Control System UI, create the ambient warehouse waypoint, set its operational Location code to `WH-AMB-01`, give it the desired RMF waypoint name, save the draft, validate it, and publish it. Testing one row first isolates mapping errors before repeating the workflow.

- [ ] **Step 3: Query draft and operational projections**

```sql
SELECT w.location_code, w.rmf_waypoint_name, w.map_x, w.map_y, w.map_yaw
FROM trihouse_fms.map_project_waypoints w
JOIN trihouse_fms.map_projects p ON p.project_id = w.project_id
WHERE p.map_name = 'project1' AND w.location_code = 'WH-AMB-01';

SELECT location_code, map_name, rmf_waypoint_name, pose_x, pose_y, pose_yaw, metadata
FROM trihouse_fms.locations
WHERE location_code = 'WH-AMB-01';
```

Expected: the draft row matches the UI values, and the Location row receives `project1`, the UI waypoint name, and published map pose. Its original `parent_location_id`, `zone_code`, `temperature_zone`, and `state` remain unchanged.

- [ ] **Step 4: Repeat for chilled and frozen warehouses**

Repeat Steps 2-3 with `WH-CHL-01` and `WH-FRZ-01`. Query the twelve child slots and verify their waypoint and pose fields remain NULL.

- [ ] **Step 5: Stop and diagnose if projection fails**

If `map_project_waypoints` is correct but `locations` remains NULL, reproduce the failure in `test_map_project_repository.py` before changing `publish_map_project()`. If the draft lacks `location_code`, diagnose UI save serialization before modifying Gateway publication. Do not manually UPDATE Location rows because that would hide the broken integration boundary.
