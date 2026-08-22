# Canonical Device Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `devices.name` equal `devices.device_id` and ensure every command boundary routes only with canonical device IDs.

**Architecture:** MySQL owns the invariant through a migration and a schema check constraint. Seed/import writers always persist the canonical ID as `name`; human labels remain map-authoring metadata and never become runtime routing keys. Static and MySQL integration tests prove aliases and display names cannot enter command identity fields.

**Tech Stack:** MySQL 8.4, SQL migrations, Python 3.12, FastAPI/Pydantic, pytest

**Spec:** `docs/superpowers/specs/2026-08-22-role-compose-hardware-deployment-design.md`

## Global Constraints

- Canonical IDs are exactly `PK_01`, `PK_02`, `OMX_01`, and `OMX_02`.
- Runtime aliases such as `PK-01`, `PINKY-01`, `pinky_01`, `OMX-01`, and `omx_01` are rejected rather than normalized.
- `devices.name = devices.device_id` is enforced in MySQL and in every writer.
- Existing user changes under `pinky_pro/**` are preserved.
- No test or migration may create a physical command or move a robot.

---

### Task 1: Persist the DB identity invariant

**Files:**
- Create: `db/migrations/006_enforce_device_name_identity.sql`
- Modify: `db/schema_mysql.sql`
- Modify: `db/seed_dev.sql`
- Modify: `db/tests/test_device_registry_contract.py`
- Test: `fms_gateway/tests/integration/test_schema.py`

**Interfaces:**
- Consumes: existing `devices(device_id, device_type, name, ...)` table.
- Produces: `CONSTRAINT chk_devices_name_matches_device_id CHECK (name = device_id)` and canonical seed rows.

- [ ] **Step 1: Write failing static contract tests**

Add assertions that the schema defines the named check, the new migration first executes
`UPDATE devices SET name = device_id`, and every canonical seed tuple uses the same string
for `device_id` and `name`.

```python
MIGRATION_006 = ROOT / "db/migrations/006_enforce_device_name_identity.sql"

def test_device_name_is_the_canonical_device_id() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    migration = MIGRATION_006.read_text(encoding="utf-8")
    seed = SEED_PATH.read_text(encoding="utf-8")

    assert "CONSTRAINT chk_devices_name_matches_device_id" in schema
    assert "CHECK (name = device_id)" in schema
    assert "UPDATE devices SET name = device_id" in migration
    for device_id in CANONICAL_IDS:
        assert re.search(rf"\('{device_id}', '(?:mobile|arm)', '{device_id}'", seed)
```

- [ ] **Step 2: Run the static test and verify RED**

Run: `pytest -q db/tests/test_device_registry_contract.py::test_device_name_is_the_canonical_device_id`

Expected: FAIL because migration 006 and the check constraint do not exist.

- [ ] **Step 3: Add the migration, schema constraint, and seed values**

The migration must be safe for the current four rows and idempotent at the data level:

```sql
START TRANSACTION;
UPDATE devices SET name = device_id WHERE name <> device_id;
COMMIT;

ALTER TABLE devices
  ADD CONSTRAINT chk_devices_name_matches_device_id
  CHECK (name = device_id);
```

The empty-volume schema receives the same named constraint. Seed names become `PK_01`,
`PK_02`, `OMX_01`, and `OMX_02`.

- [ ] **Step 4: Add a MySQL integration test for INSERT and UPDATE rejection**

Use the existing MySQL fixture in `fms_gateway/tests/integration/test_schema.py`:

```python
def test_devices_reject_a_name_that_differs_from_device_id(mysql_cursor) -> None:
    with pytest.raises(mysql.connector.Error):
        mysql_cursor.execute(
            "UPDATE devices SET name='Pinky-Pro #1' WHERE device_id='PK_01'"
        )
```

Also query all seeded rows and assert `device_id == name`.

- [ ] **Step 5: Apply migration 006 to the integration DB and verify GREEN**

Run:

```bash
pytest -q db/tests/test_device_registry_contract.py
pytest -q fms_gateway/tests/integration/test_schema.py -k device
```

Expected: PASS; MySQL rejects a mismatched name.

- [ ] **Step 6: Commit Task 1**

```bash
git add db/migrations/006_enforce_device_name_identity.sql db/schema_mysql.sql \
  db/seed_dev.sql db/tests/test_device_registry_contract.py \
  fms_gateway/tests/integration/test_schema.py
git commit -m "feat(db): enforce canonical device names"
```

### Task 2: Stop map publication from writing display names into devices

**Files:**
- Modify: `fms_gateway/app/repositories.py:2230-2285`
- Modify: `fms_gateway/tests/unit/test_map_project_api.py`
- Modify: `fms_gateway/tests/integration/test_map_project_repository.py` if the repository integration fixture lives there

**Interfaces:**
- Consumes: map authoring robot records with `robot_id` and `display_name`.
- Produces: runtime `devices.name=robot_id`; authoring `display_name` remains only in `map_project_robots`.

- [ ] **Step 1: Write a failing publication test**

Publish a map project whose authoring label is not the ID and assert the runtime device keeps
the ID:

```python
robot = {"robot_id": "PK_01", "display_name": "Pinky-Pro #1", "kind": "mobile"}
publication = publish_project_with_robot(robot)
device = fetch_device("PK_01")
assert device["name"] == "PK_01"
assert fetch_map_project_robot("PK_01")["display_name"] == "Pinky-Pro #1"
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `pytest -q fms_gateway/tests -k 'map_project and device_name'`

Expected: FAIL because `publish_map_project` currently inserts `robot["display_name"]`.

- [ ] **Step 3: Use `robot_id` for both INSERT and UPDATE device names**

Change only the runtime device write:

```python
canonical_name = robot["robot_id"]
# INSERT values: robot_id, device_type, canonical_name, ...
# UPDATE values: device_type, canonical_name, ...
```

Do not delete or overwrite `map_project_robots.display_name`.

- [ ] **Step 4: Run unit and integration publication tests**

Run:

```bash
pytest -q fms_gateway/tests/unit/test_map_project_api.py
pytest -q fms_gateway/tests/integration -k map_project
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add fms_gateway/app/repositories.py fms_gateway/tests
git commit -m "fix(fms): keep display labels out of device identity"
```

### Task 3: Prove command routing uses only canonical IDs

**Files:**
- Create: `tests/test_device_command_identity_contract.py`
- Modify: `trihouse_rmf_bridge/README.md`
- Modify: `trihouse_pinky/doc/pinky-sr-implementation.md`
- Modify: `docs/deployment/environment_overview.md`

**Interfaces:**
- Consumes: assignment, RMF claim, Pinky status/event, and OMX simulator/adapter contracts.
- Produces: a regression suite that fails if a human label, ROS namespace, or hyphen alias is used as a machine ID.

- [ ] **Step 1: Write failing source and behavior contract tests**

The test must verify:

```python
def test_machine_identity_examples_use_only_canonical_ids() -> None:
    assert "robot_name:=PK-01" not in RMF_README.read_text()
    assert "robot_id:=PK-01" not in PINKY_DOC.read_text()

def test_namespace_is_not_a_machine_identifier() -> None:
    assert accept_assigned_path(adapter_robot_name="PK_01", request_robot_name="pinky_01").accepted is False
```

Add focused assertions for `_on_status`/command claim exact matching through existing adapter
test helpers instead of mocking the whole ROS graph.

- [ ] **Step 2: Run and verify RED**

Run: `pytest -q tests/test_device_command_identity_contract.py trihouse_rmf_bridge/test/test_pinky_adapter_contract.py`

Expected: FAIL on stale `PK-01` documentation and any alias acceptance found by the test.

- [ ] **Step 3: Correct documentation and fail closed at the existing boundaries**

Replace executable examples with canonical IDs and namespaced topic/action paths:

```bash
robot_id:=PK_01 namespace:=pinky_01
robot_name:=PK_01 \
robot_status_topic:=/pinky_01/trihouse/status \
transport_action:=/pinky_01/trihouse/transport/execute
```

Do not introduce a generic string-normalization helper.

- [ ] **Step 4: Run the identity regression suite**

Run:

```bash
pytest -q db/tests/test_device_registry_contract.py \
  tests/test_device_command_identity_contract.py \
  trihouse_rmf_bridge/test/test_pinky_adapter_contract.py \
  control_tower/tests/test_outbound_sequence.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add tests/test_device_command_identity_contract.py trihouse_rmf_bridge/README.md \
  trihouse_pinky/doc/pinky-sr-implementation.md docs/deployment/environment_overview.md
git commit -m "docs: standardize canonical robot identifiers"
```

