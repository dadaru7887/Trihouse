# FMS Gateway Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the Flutter `control_system` inventory UI to the canonical `trihouse_fms` MySQL schema through an FMS Gateway, including reproducible environment setup and one transactional inventory adjustment.

**Architecture:** A Python FastAPI Gateway in the parent Trihouse repository is the only MySQL writer. It exposes health/read endpoints and an inventory-adjustment command; the Flutter submodule adds an optional asynchronous API mode while retaining SQLite mode for regression tests. Open-RMF integration remains behind a typed adapter boundary and is not executed in this vertical slice.

**Tech Stack:** Ubuntu 24.04 ARM64, Python 3.12, FastAPI 0.141.1, Uvicorn 0.52.1, mysql-connector-python 26.7.0, pytest 9.1.1, MySQL 8.4, Docker Compose, Flutter stable with Dart >=3.12.2, Dart `http` package.

## Global Constraints

- The canonical schema is `db/schema_mysql.sql`; do not use `control_system/db/schema.sql` or `control_system/db/migrate_sqlite_to_mysql.py`.
- Keep the existing 15 domain tables; add columns, constraints, and indexes only.
- All business timestamps are stored and interpreted as `Asia/Seoul`; MySQL sessions use `+09:00`, API timestamps include `+09:00`.
- Only the FMS Gateway writes MySQL. Flutter, RMF, Pinky, and OMX never receive DB credentials.
- Open-RMF owns graph lane traffic; MySQL reservations own docks, workstations, devices, and non-RMF resources.
- Existing SQLite mode remains available; API mode must not run SQLite demo seeding.
- Every behavior change follows red-green-refactor and must have a test that failed for the intended reason before implementation.

---

### Task 1: Reproducible development environment

**Files:**
- Create: `compose.yaml`
- Create: `compose.test.yaml`
- Create: `.env.example`
- Create: `fms_gateway/requirements.txt`
- Create: `fms_gateway/requirements-dev.txt`
- Create: `docs/setup/fms-gateway-setup.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Ubuntu 24.04 ARM64 host with Git and Python 3.12.
- Produces: MySQL development service on `127.0.0.1:3306`, test service on `127.0.0.1:3307`, Python virtual environment commands, Flutter Linux toolchain commands, and a complete installation log/template.

- [ ] **Step 1: Record the pre-installation state**

Run and paste the exact output into `docs/setup/fms-gateway-setup.md` under “Observed starting state”:

```bash
uname -m
sed -n '1,12p' /etc/os-release
python3 --version
python3 -m pip --version
flutter --version || true
docker --version || true
docker compose version || true
mysql --version || true
```

Create a feature branch in the writable `control_system` submodule before its Flutter files change:

```bash
git -C control_system switch -c feat/fms-api-inventory
```

- [ ] **Step 2: Install Flutter Linux and Docker prerequisites**

Run the documented Ubuntu commands:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git unzip xz-utils zip libglu1-mesa clang cmake ninja-build pkg-config libgtk-3-dev libstdc++-12-dev
```

Install Docker Engine from Docker's Ubuntu `noble` ARM64 apt repository and install:

```bash
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Install Flutter stable to `/home/luna/develop/flutter`, add `/home/luna/develop/flutter/bin` to the user's Bash PATH, then run:

```bash
flutter config --enable-linux-desktop
flutter doctor -v
flutter devices
```

- [ ] **Step 3: Create pinned Python dependency files**

`fms_gateway/requirements.txt`:

```text
fastapi==0.141.1
mysql-connector-python==26.7.0
pydantic-settings==2.14.2
uvicorn==0.52.1
```

`fms_gateway/requirements-dev.txt`:

```text
-r requirements.txt
httpx==0.28.1
pytest==9.1.1
pytest-cov==7.1.0
```

- [ ] **Step 4: Create deterministic MySQL Compose services**

`compose.yaml` defines `mysql:8.4`, binds only `127.0.0.1:3306`, persists `/var/lib/mysql`, sets `TZ=Asia/Seoul`, starts MySQL with `--default-time-zone=+09:00`, and mounts `db/schema_mysql.sql` plus `db/seed_dev.sql` into `/docker-entrypoint-initdb.d/`.

`compose.test.yaml` defines a separate `mysql-test` service on `127.0.0.1:3307`, uses `tmpfs: /var/lib/mysql`, applies the same schema, and has no production volume.

- [ ] **Step 5: Create the project virtual environment and install dependencies**

Run:

```bash
python3 -m venv fms_gateway/.venv
fms_gateway/.venv/bin/python -m pip install --upgrade pip
fms_gateway/.venv/bin/python -m pip install -r fms_gateway/requirements-dev.txt
fms_gateway/.venv/bin/python -m pip freeze
```

Record every executed command, installed version, verification output, environment-variable explanation, startup command, teardown command, and troubleshooting note in `docs/setup/fms-gateway-setup.md`. Secrets are represented by placeholders only.

- [ ] **Step 6: Verify configuration and commit**

Run:

```bash
docker compose config
docker compose -f compose.test.yaml config
git diff --check
```

Commit:

```bash
git add .gitignore .env.example compose.yaml compose.test.yaml fms_gateway/requirements.txt fms_gateway/requirements-dev.txt docs/setup/fms-gateway-setup.md
git commit -m "chore: add reproducible FMS development environment"
```

### Task 2: Reinforce and verify the canonical MySQL schema

**Files:**
- Modify: `db/schema_mysql.sql`
- Create: `db/seed_dev.sql`
- Create: `fms_gateway/tests/conftest.py`
- Create: `fms_gateway/tests/integration/test_schema.py`
- Create: `fms_gateway/pytest.ini`

**Interfaces:**
- Consumes: MySQL test service on port 3307 and canonical schema.
- Produces: schema invariants, Seoul session behavior, deterministic development seed, and reusable real-MySQL pytest fixtures.

- [ ] **Step 1: Write failing real-MySQL schema tests**

Create tests that connect to `trihouse_fms` and prove these behaviors:

```python
def test_reserved_quantity_cannot_exceed_available(mysql_db):
    with pytest.raises(mysql.connector.Error) as error:
        mysql_db.execute(
            "UPDATE inventory_lots SET reserved_qty = available_qty + 1 WHERE lot_code = %s",
            ("LOT-DEV-001",),
        )
    assert error.value.errno == 3819


def test_external_reference_is_idempotent(mysql_db):
    insert_job(mysql_db, "request-001")
    with pytest.raises(mysql.connector.IntegrityError) as error:
        insert_job(mysql_db, "request-001")
    assert error.value.errno == 1062


def test_mysql_session_uses_seoul_offset(mysql_db):
    row = mysql_db.one("SELECT TIMEDIFF(NOW(6), UTC_TIMESTAMP(6)) AS offset")
    assert str(row["offset"]) == "9:00:00"
```

Add metadata assertions for `jobs.parent_job_id`, `jobs.revision`, `inventory_moves.reserved_delta`, `inventory_moves.reserved_after`, `integration_messages.next_attempt_at`, incident acknowledgement columns, `operation_events.actor_worker_id`, and the new indexes.

- [ ] **Step 2: Start the test database and verify RED**

Run:

```bash
docker compose -f compose.test.yaml up -d --wait
fms_gateway/.venv/bin/pytest fms_gateway/tests/integration/test_schema.py -v
```

Expected: tests fail because the constraints, columns, or indexes do not yet exist.

- [ ] **Step 3: Apply the minimal schema reinforcements**

Modify `db/schema_mysql.sql` to add:

```text
inventory_lots: CHECK reserved_qty <= available_qty
inventory_moves: reserved_delta, reserved_after and non-negative checks
jobs: parent_job_id self FK, revision, generated priority_rank, unique external_reference
reservations: expires_at > created_at CHECK and feature expiry index
integration_messages: next_attempt_at and delivery index ordering
incidents: acknowledged_by_worker_id, acknowledged_at and worker FK
operation_events: actor_worker_id, worker FK and occurred_at index
```

Change the schema header from UTC to `Asia/Seoul` and document that every Gateway connection executes `SET time_zone = '+09:00'`.

- [ ] **Step 4: Add deterministic seed data**

`db/seed_dev.sql` inserts, with idempotent keys:

```text
locations: one ambient rack slot, one outbound dock, one charger, one OMX workstation
workers: one operator and one safety manager
devices: Pinky-Pro #1/#2 and OMX-AI #1/#2
device_states: one latest state per device
inventory_lots: LOT-DEV-001 and LOT-DEV-002
jobs/job_items/job_steps: one pending outbound demonstration job
```

All timestamps use Seoul wall time and all FK targets exist before child rows.

- [ ] **Step 5: Recreate MySQL and verify GREEN**

Run:

```bash
docker compose -f compose.test.yaml down -v
docker compose -f compose.test.yaml up -d --wait
fms_gateway/.venv/bin/pytest fms_gateway/tests/integration/test_schema.py -v
```

Expected: all schema integration tests pass.

- [ ] **Step 6: Commit**

```bash
git add db/schema_mysql.sql db/seed_dev.sql fms_gateway/pytest.ini fms_gateway/tests
git commit -m "feat: reinforce trihouse FMS schema"
```

### Task 3: Reservation conflict auto-shift service

**Files:**
- Create: `fms_gateway/app/__init__.py`
- Create: `fms_gateway/app/reservations.py`
- Create: `fms_gateway/tests/unit/test_reservations.py`

**Interfaces:**
- Consumes: timezone-aware requested start/end and sorted or unsorted existing `[start, end)` intervals.
- Produces: `find_earliest_slot(requested_start: datetime, requested_end: datetime, occupied: Sequence[TimeWindow]) -> TimeWindow`.

- [ ] **Step 1: Write failing reservation tests**

Cover literal expected values for:

```python
def test_moves_after_a_chain_of_conflicts():
    result = find_earliest_slot(
        seoul("2026-08-03T10:10:00+09:00"),
        seoul("2026-08-03T10:30:00+09:00"),
        [
            TimeWindow(seoul("2026-08-03T10:00:00+09:00"), seoul("2026-08-03T10:20:00+09:00")),
            TimeWindow(seoul("2026-08-03T10:25:00+09:00"), seoul("2026-08-03T10:40:00+09:00")),
        ],
    )
    assert result == TimeWindow(
        seoul("2026-08-03T10:40:00+09:00"),
        seoul("2026-08-03T11:00:00+09:00"),
    )
```

Also test touching boundaries, unsorted intervals, unchanged duration, invalid zero/negative duration, and non-Seoul-aware timestamps.

- [ ] **Step 2: Verify RED**

```bash
fms_gateway/.venv/bin/pytest fms_gateway/tests/unit/test_reservations.py -v
```

Expected: import or symbol failure because the service does not exist.

- [ ] **Step 3: Implement the minimal pure scheduler**

Implement immutable `TimeWindow` validation and a loop that sorts occupied intervals, shifts the candidate to each overlapping end, and preserves duration. Reject naive datetimes and offsets other than `+09:00`.

- [ ] **Step 4: Verify GREEN and commit**

```bash
fms_gateway/.venv/bin/pytest fms_gateway/tests/unit/test_reservations.py -v
git add fms_gateway/app fms_gateway/tests/unit/test_reservations.py
git commit -m "feat: schedule reservations after conflicts"
```

### Task 4: FMS Gateway health and read API

**Files:**
- Create: `fms_gateway/app/config.py`
- Create: `fms_gateway/app/database.py`
- Create: `fms_gateway/app/models.py`
- Create: `fms_gateway/app/repositories.py`
- Create: `fms_gateway/app/main.py`
- Create: `fms_gateway/tests/unit/test_api_contract.py`
- Create: `fms_gateway/tests/integration/test_read_api.py`

**Interfaces:**
- Consumes: `FMS_DB_HOST`, `FMS_DB_PORT`, `FMS_DB_USER`, `FMS_DB_PASSWORD`, `FMS_DB_NAME`.
- Produces: `GET /health`, `GET /ready`, `GET /api/v1/devices`, `GET /api/v1/inventory/lots`, and `GET /api/v1/jobs`.

- [ ] **Step 1: Write failing API contract tests**

Use a concrete in-memory fake repository implementing the same protocol and assert complete response objects. Required response shapes:

```json
{
  "lot_id": 1,
  "lot_code": "LOT-DEV-001",
  "product_code": "SKU-AMBIENT-001",
  "item_name": "개발용 상온 상품",
  "temperature_zone": "ambient",
  "location_code": "A-SLOT-01",
  "expiry_date": "2026-12-31",
  "available_qty": 100,
  "reserved_qty": 5,
  "state": "stored"
}
```

Device responses combine `devices` and `device_states`; job responses include job header state, assignment, due time with `+09:00`, and item/step counts.

- [ ] **Step 2: Verify unit RED**

```bash
fms_gateway/.venv/bin/pytest fms_gateway/tests/unit/test_api_contract.py -v
```

- [ ] **Step 3: Implement configuration, pooled DB sessions, models, repositories, and routes**

Every checked-out MySQL connection executes:

```sql
SET time_zone = '+09:00';
```

`/ready` executes `SELECT 1`; `/health` never touches MySQL. Repository SQL uses explicit column lists and parameter binding.

- [ ] **Step 4: Write and run real-MySQL read integration tests**

Tests call the real FastAPI app with the seeded test DB and assert Pinky, OMX, inventory, and job rows. Run:

```bash
FMS_DB_PORT=3307 fms_gateway/.venv/bin/pytest fms_gateway/tests/integration/test_read_api.py -v
```

Expected before final implementation: route or mapping failures. Expected after implementation: PASS.

- [ ] **Step 5: Run all Gateway tests and commit**

```bash
FMS_DB_PORT=3307 fms_gateway/.venv/bin/pytest fms_gateway/tests -v
git add fms_gateway/app fms_gateway/tests
git commit -m "feat: expose FMS Gateway read API"
```

### Task 5: Transactional inventory adjustment command

**Files:**
- Modify: `fms_gateway/app/models.py`
- Modify: `fms_gateway/app/repositories.py`
- Create: `fms_gateway/app/services.py`
- Modify: `fms_gateway/app/main.py`
- Create: `fms_gateway/tests/integration/test_inventory_adjustment.py`

**Interfaces:**
- Consumes: `POST /api/v1/inventory/adjustments` with body fields `lot_id`, `quantity_delta`, `recorded_by`, and `note`, plus a required `Idempotency-Key` header.
- Produces: updated lot response and one atomic `inventory_moves` plus `operation_events` record.

- [ ] **Step 1: Write failing real-MySQL transaction tests**

Tests prove:

```text
+10 updates available_qty, inserts one inventory move, and inserts one operation event
a decrease below reserved_qty returns 409 and writes neither ledger nor event
an unknown lot returns 404
the same idempotency_key returns the original result without applying the delta twice
```

Use a literal before/after count and quantity in assertions; do not assert on mocks.

- [ ] **Step 2: Verify RED**

```bash
FMS_DB_PORT=3307 fms_gateway/.venv/bin/pytest fms_gateway/tests/integration/test_inventory_adjustment.py -v
```

- [ ] **Step 3: Implement the minimal transaction**

Derive `operation_events.event_uuid` as UUIDv5 from the `Idempotency-Key`, so the existing unique key on `event_uuid` is the database-level deduplication guard. Within one MySQL transaction:

```text
check operation_events.event_uuid for the deterministic UUID
SELECT inventory_lots ... FOR UPDATE
validate available_qty + delta >= reserved_qty
UPDATE inventory_lots
INSERT inventory_moves
INSERT operation_events with category='inventory' and the deterministic event_uuid
COMMIT
```

The original idempotency key is also stored in `operation_events.payload` for audit. Concurrent duplicates targeting different lots are still protected because only one transaction can insert the unique deterministic `event_uuid`; the losing transaction rolls back its lot and ledger changes.

- [ ] **Step 4: Verify GREEN and commit**

```bash
FMS_DB_PORT=3307 fms_gateway/.venv/bin/pytest fms_gateway/tests/integration/test_inventory_adjustment.py -v
FMS_DB_PORT=3307 fms_gateway/.venv/bin/pytest fms_gateway/tests -v
git add fms_gateway/app fms_gateway/tests/integration/test_inventory_adjustment.py
git commit -m "feat: add transactional inventory adjustment"
```

### Task 6: Flutter API-mode inventory UI

**Files:**
- Modify: `control_system/robo_control/pubspec.yaml`
- Create: `control_system/robo_control/lib/fms_api/fms_models.dart`
- Create: `control_system/robo_control/lib/fms_api/fms_api_client.dart`
- Create: `control_system/robo_control/lib/fms_api/fms_inventory_controller.dart`
- Create: `control_system/robo_control/lib/fms_api/fms_scope.dart`
- Modify: `control_system/robo_control/lib/main.dart`
- Modify: `control_system/robo_control/lib/ui/pages/inventory_page.dart`
- Create: `control_system/robo_control/test/fms_api_client_test.dart`
- Create: `control_system/robo_control/test/fms_inventory_controller_test.dart`

**Interfaces:**
- Consumes: `--dart-define=FMS_API_BASE_URL=http://127.0.0.1:8080` and Gateway JSON contracts.
- Produces: remote inventory list, adjustment command, refresh, connection/error state, and unchanged SQLite behavior when the define is absent.

- [ ] **Step 1: Add the HTTP dependency and fetch packages**

Add `http` to `pubspec.yaml`, then run:

```bash
cd control_system/robo_control
flutter pub get
```

- [ ] **Step 2: Write failing model/client tests**

Use an injected `http.Client` with a local fake transport and assert:

```text
Gateway JSON maps lot_id and Seoul dates correctly
non-200 responses throw FmsApiException with status and body
adjustment sends the exact JSON contract and Idempotency-Key value
```

Run and confirm RED:

```bash
flutter test test/fms_api_client_test.dart
```

- [ ] **Step 3: Implement models and client, then verify GREEN**

Implement:

```dart
abstract interface class FmsInventoryApi {
  Future<List<FmsInventoryLot>> fetchLots();
  Future<FmsInventoryLot> adjustInventory(FmsInventoryAdjustment command);
}
```

Run:

```bash
flutter test test/fms_api_client_test.dart
```

- [ ] **Step 4: Write failing controller tests**

Use a concrete fake `FmsInventoryApi` and assert initial load, successful adjustment refresh, loading state, and preserved error message. Verify the tests fail before the controller exists.

- [ ] **Step 5: Implement controller and API scope**

`main.dart` reads `FMS_API_BASE_URL`. Empty value constructs the existing `SqliteDataStore`/`FleetEngine` path. Non-empty value creates `FmsInventoryController`, does not use remote credentials, and exposes it through `FmsScope` while retaining the local engine only for non-migrated pages during this slice.

`InventoryPage` uses the remote controller when present and the existing engine-backed view otherwise. Remote adjustments call Gateway and refresh the visible row; the UI shows loading, retry, and API-connected indicators.

- [ ] **Step 6: Run Flutter tests and static analysis**

```bash
flutter test test/fms_api_client_test.dart test/fms_inventory_controller_test.dart
flutter test
flutter analyze
```

- [ ] **Step 7: Commit inside the submodule and update the parent pointer**

```bash
git -C control_system add robo_control
git -C control_system commit -m "feat: connect inventory UI to FMS Gateway"
git add control_system
git commit -m "chore: update control_system for FMS API mode"
```

### Task 7: End-to-end verification and reproducibility record

**Files:**
- Modify: `docs/setup/fms-gateway-setup.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: completed Gateway, MySQL, seed, and Flutter API mode.
- Produces: copy-paste setup/run/test instructions and captured verification results for a clean Ubuntu 24.04 ARM64 environment.

- [ ] **Step 1: Start the development stack**

```bash
cp .env.example .env
docker compose up -d --wait mysql
fms_gateway/.venv/bin/uvicorn fms_gateway.app.main:app --host 127.0.0.1 --port 8080
```

- [ ] **Step 2: Verify Gateway endpoints and transaction**

```bash
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8080/ready
curl -fsS http://127.0.0.1:8080/api/v1/devices
curl -fsS http://127.0.0.1:8080/api/v1/inventory/lots
curl -fsS http://127.0.0.1:8080/api/v1/jobs
curl -fsS -X POST http://127.0.0.1:8080/api/v1/inventory/adjustments -H 'Content-Type: application/json' -H 'Idempotency-Key: setup-smoke-001' -d '{"lot_id":1,"quantity_delta":1,"recorded_by":"W-OP-01","note":"setup smoke test"}'
```

- [ ] **Step 3: Run the Flutter UI in API mode**

```bash
cd control_system/robo_control
flutter run -d linux --dart-define=FMS_API_BASE_URL=http://127.0.0.1:8080
```

Verify that the seeded lots appear, one adjustment updates the row after refresh, and MySQL contains matching `inventory_moves` and `operation_events` rows.

- [ ] **Step 4: Run the complete automated suite**

```bash
FMS_DB_PORT=3307 fms_gateway/.venv/bin/pytest fms_gateway/tests -v
cd control_system/robo_core && flutter test && flutter analyze
cd ../robo_control && flutter test && flutter analyze
```

- [ ] **Step 5: Complete the setup document and commit**

Add actual installed versions, all commands that were executed, expected outputs, clean-machine procedure, environment variables, start/stop/reset commands, and known ARM64 notes to `docs/setup/fms-gateway-setup.md`.

```bash
git add README.md docs/setup/fms-gateway-setup.md
git commit -m "docs: document FMS Gateway setup and verification"
```
