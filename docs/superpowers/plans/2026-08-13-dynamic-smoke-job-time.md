# Dynamic Smoke Job Time Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a freshly seeded `JOB-DEV-001` due one hour after its actual seed time without moving that deadline on repeated seed application.

**Architecture:** Keep time ownership inside MySQL so `created_at` and `due_at` use the same database clock and existing Asia/Seoul session configuration. Verify the behavior through the real MySQL integration fixture, including an idempotent second seed application.

**Tech Stack:** MySQL 8.4 SQL, Python 3.12, pytest, mysql-connector-python

## Global Constraints

- `db/schema_mysql.sql` remains the canonical schema and is not modified.
- `created_at` is the first seed application time.
- `due_at` is exactly one hour after `created_at`.
- Reapplying `db/seed_dev.sql` does not change either timestamp.
- Existing Orange lot, source slot, destination, device assignment, and step data remain unchanged.

---

### Task 1: Add the Dynamic-Time Regression Test

**Files:**
- Modify: `fms_gateway/tests/integration/test_schema.py`
- Test: `fms_gateway/tests/integration/test_schema.py`

**Interfaces:**
- Consumes: `execute_sql_script(mysql_db.connection, SEED_PATH)` and `mysql_db.one(sql)`.
- Produces: a regression contract for the `jobs.created_at` and `jobs.due_at` values of `JOB-DEV-001`.

- [ ] **Step 1: Extend the smoke-job test with first-run and rerun timestamps**

Apply the seed once between database time bounds, read the job timestamps, apply it a second time, and read them again:

```python
before = mysql_db.one("SELECT NOW(6) AS now")["now"]
execute_sql_script(mysql_db.connection, SEED_PATH)
after_first_seed = mysql_db.one("SELECT NOW(6) AS now")["now"]
first_times = mysql_db.one(
    "SELECT created_at, due_at FROM jobs WHERE job_code = 'JOB-DEV-001'"
)
execute_sql_script(mysql_db.connection, SEED_PATH)
second_times = mysql_db.one(
    "SELECT created_at, due_at FROM jobs WHERE job_code = 'JOB-DEV-001'"
)

assert before <= first_times["created_at"] <= after_first_seed
assert first_times["due_at"] - first_times["created_at"] == dt.timedelta(hours=1)
assert second_times == first_times
```

Keep the existing QR inventory and Orange source assertions in the same test.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
FMS_DB_HOST=127.0.0.1 FMS_DB_PORT=3307 \
FMS_DB_ADMIN_USER=root FMS_DB_ADMIN_PASSWORD=test_root_password \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
/tmp/fms-gateway-venv/bin/python -m pytest -v \
  fms_gateway/tests/integration/test_schema.py::test_development_seed_smoke_job_uses_qr_inventory
```

Expected: FAIL because the hard-coded `created_at` is earlier than `before`.

### Task 2: Use the Database Clock in the Seed

**Files:**
- Modify: `db/seed_dev.sql`
- Test: `fms_gateway/tests/integration/test_schema.py`

**Interfaces:**
- Consumes: MySQL `CURRENT_TIMESTAMP(6)` and `DATE_ADD(..., INTERVAL 1 HOUR)`.
- Produces: stable timestamps for the existing `JOB-DEV-001` row.

- [ ] **Step 1: Make the initial timestamps relative to seed time**

Replace the two fixed timestamp values in the `INSERT INTO jobs` statement:

```sql
DATE_ADD(CURRENT_TIMESTAMP(6), INTERVAL 1 HOUR), 'PK_01',
JSON_OBJECT('source', 'dev_seed'), CURRENT_TIMESTAMP(6)
```

Remove this line from `ON DUPLICATE KEY UPDATE`:

```sql
due_at = VALUES(due_at),
```

This preserves both original timestamps when the seed is reapplied.

- [ ] **Step 2: Run the focused test and verify GREEN**

Run the Task 1 focused pytest command.

Expected: PASS.

- [ ] **Step 3: Run the complete database and Gateway integration suites**

Run:

```bash
FMS_DB_HOST=127.0.0.1 FMS_DB_PORT=3307 \
FMS_DB_ADMIN_USER=root FMS_DB_ADMIN_PASSWORD=test_root_password \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
/tmp/fms-gateway-venv/bin/python -m pytest -q db/tests
```

Run:

```bash
FMS_DB_HOST=127.0.0.1 FMS_DB_PORT=3307 \
FMS_DB_USER=fms_gateway FMS_DB_PASSWORD=test_gateway_password \
FMS_DB_ADMIN_USER=root FMS_DB_ADMIN_PASSWORD=test_root_password \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
/tmp/fms-gateway-venv/bin/python -m pytest -q fms_gateway/tests/integration
```

Expected: both suites pass.

- [ ] **Step 4: Commit the regression and fix together**

```bash
git add db/seed_dev.sql fms_gateway/tests/integration/test_schema.py
git commit -m "fix: seed smoke job with a current deadline"
```

### Task 3: Refresh the Manual-Test Database

**Files:**
- No repository files change.

**Interfaces:**
- Consumes: `compose.db_test.yaml`, the corrected schema and seed.
- Produces: a fresh disposable MySQL database for the one-PC integration test.

- [ ] **Step 1: Stop the existing Gateway process**

Use `Ctrl+C` in the terminal running PID `2646563`, then verify ports 8080 and 8788 are free:

```bash
ss -ltnp '( sport = :8080 or sport = :8788 )'
```

- [ ] **Step 2: Recreate the disposable database**

```bash
docker compose --project-directory /home/syw/Trihouse \
  -f /home/syw/Trihouse/compose.db_test.yaml down
docker compose --project-directory /home/syw/Trihouse \
  -f /home/syw/Trihouse/compose.db_test.yaml up -d --wait
```

- [ ] **Step 3: Restart Gateway and verify the job time**

Restart the Gateway with the existing local command, call `/ready`, then inspect jobs:

```bash
curl -sS http://127.0.0.1:8080/api/v1/jobs | python3 -m json.tool
```

Expected: `JOB-DEV-001.due_at` is approximately one hour after database initialization and is not in the past.
