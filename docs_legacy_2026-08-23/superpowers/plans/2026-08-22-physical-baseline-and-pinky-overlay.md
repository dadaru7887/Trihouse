# Physical Baseline and Pinky Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze the first physical-test database as migration 001, add an ordered root readiness suite, and preserve Pinky vendor provenance while tracking only Trihouse-specific overlays.

**Architecture:** The final pre-physical schema becomes immutable migration `001`; historical upgrade scripts move to an archive and future changes start at `002`. Ordered tests under `tests/physical_readiness` validate one deployment boundary at a time. The official `pinky_pro` remains a clean submodule while `pinky_pro_alpha` stores maps, measured navigation overrides, pinned third-party dependencies, and reproducible application instructions.

**Tech Stack:** MySQL 8.4, Docker Compose, Python 3.12, pytest, ROS 2 Jazzy, colcon, Git submodules

**Spec:** `docs/superpowers/specs/2026-08-22-role-compose-hardware-deployment-design.md`

## Global Constraints

- `001_physical_v1_baseline.sql` contains the complete schema required by a new physical DB and is immutable after this task.
- Future schema changes use `002_*.sql`, `003_*.sql`, and so on.
- `devices.name = devices.device_id`; routing accepts only `PK_01`, `PK_02`, `OMX_01`, and `OMX_02`.
- Runtime build products, `.bak`, `install/`, `build/`, and `log/` are never copied into `pinky_pro_alpha`.
- The measured footprint and inflation values from the dirty Pinky Nav2 file are retained as Trihouse overrides.
- Explanatory comments are bilingual only when they clarify a non-obvious system boundary, safety invariant, or failure mode.
- Work happens only on `feat/physical-integration-v1` in the isolated worktree.

---

### Task 1: Add the ordered physical-readiness test harness

**Files:**
- Create: `tests/physical_readiness/README.md`
- Create: `tests/physical_readiness/conftest.py`
- Create: `tests/physical_readiness/test_01_database_baseline.py`
- Create: `tests/physical_readiness/test_02_device_identity.py`

**Interfaces:**
- Produces: ordered, independently runnable pytest boundaries with `hardware` marker registration.
- Consumes: repository paths and SQL artifacts; no physical motion or DB mutation.

- [x] Write `test_01_database_baseline.py` against the desired `001` path, archive path, migration ledger, and Compose mount.
- [x] Run it and observe failure because the baseline has not been created.
- [x] Write `test_02_device_identity.py` against canonical seed tuples and the DB check constraint.
- [x] Run it and observe failure because names are still human labels.
- [x] Add `README.md` with exact one-file-at-a-time commands and PASS scope.
- [x] Register the `hardware` marker without adding collection-time hardware probes.

### Task 2: Consolidate the first physical DB baseline

**Files:**
- Create: `db/migrations/001_physical_v1_baseline.sql` from the current final `db/schema_mysql.sql`
- Move: `db/migrations/004_*.sql` through `012_*.sql` to `db/archive/pre_physical_v1/`
- Create: `db/seeds/seed_hardware.sql`
- Move: `db/seed_dev.sql` to `db/seeds/seed_dev.sql`
- Modify: `compose.yaml`
- Modify: `compose.db.yaml`
- Modify: `compose.db_test.yaml`
- Modify: DB tests that reference the old schema/seed/migration paths

**Interfaces:**
- Produces: empty-volume initialization from migration 001 plus the selected seed.
- Consumes: current final schema, with no loss of DDL represented by migrations 004–012.

- [x] Copy the full current schema into migration 001 and add `schema_migrations(version, filename, sha256, applied_at)`.
- [x] Set every seeded device name to its canonical ID and add `chk_devices_name_matches_device_id`.
- [x] Split operational hardware seed data from demo inventory/test data.
- [x] Update Compose so hardware/development uses explicit seed files and test Compose uses the development seed.
- [x] Update existing DB tests to treat migration 001 as current truth while archived migration tests point to the archive only when they test historical upgrade behavior.
- [x] Run `test_01`, `test_02`, and all executable `db/tests`; expect GREEN.

### Task 3: Make map publication preserve canonical device names

**Files:**
- Modify: `fms_gateway/app/repositories.py`
- Modify: relevant map publication tests
- Extend: `tests/physical_readiness/test_02_device_identity.py`

**Interfaces:**
- Consumes: `map_project_robots.robot_id` and human `display_name`.
- Produces: runtime device row with `name=robot_id`; authoring display name remains in the map project.

- [x] Write a failing publication test using `PK_01` and `Pinky-Pro #1`.
- [x] Change runtime device INSERT/UPDATE to use `robot_id` for `name`.
- [x] Verify human display metadata remains queryable from map authoring.
- [x] Run the focused static publication and identity suites.

### Task 4: Create the `pinky_pro_alpha` overlay

**Files:**
- Create: `pinky_pro_alpha/README.md`
- Create: `pinky_pro_alpha/pinky_navigation/map/new_map_2.yaml`
- Create: `pinky_pro_alpha/pinky_navigation/map/new_map_2.pgm`
- Create: `pinky_pro_alpha/pinky_navigation/params/amcl_params.yaml`
- Create: `pinky_pro_alpha/pinky_navigation/params/nav2_params.yaml`
- Create: `pinky_pro_alpha/vendor/sllidar_ros2.gitref`
- Create: `scripts/apply_pinky_pro_alpha`
- Create: `tests/physical_readiness/test_06_pinky_pi_compose.py` initially covering overlay application/provenance

**Interfaces:**
- Consumes: clean official `https://github.com/pinklab-art/pinky_pro.git` checkout.
- Produces: deterministic overlay application followed by `rosdep`/`colcon build`; no generated build products.

- [x] Write a failing test that applies the overlay to a temporary clean Pinky-like tree and checks map, AMCL, footprint, resolution, cost scaling, and inflation values.
- [x] Copy only approved source/config assets from the dirty original worktree.
- [x] Record the SLAMTEC repository URL and exact commit in `sllidar_ros2.gitref`; do not copy its `.git`, `build`, `install`, or `log` trees.
- [x] Implement `apply_pinky_pro_alpha` with source/destination validation and no implicit clone or network access.
- [x] Document clone path, overlay command, `rosdep`, `colcon build`, upstream URL, license retention, and update workflow.
- [x] Run the overlay test and verify the original `pinky_pro` submodule remains untouched.

### Task 5: Verify and checkpoint this implementation slice

**Files:**
- Update: plan checkboxes and deployment documentation paths affected by the baseline rename.

**Interfaces:**
- Produces: commits on `feat/physical-integration-v1`; no remote push.

- [ ] Run all `tests/physical_readiness` tests that do not require actual hardware.
- [ ] Run executable `db/tests` and focused FMS publication tests.
- [ ] Run `git diff --check` and confirm both parent repo and `pinky_pro` worktree status.
- [ ] Commit each verified task separately.
- [ ] Report MySQL/Docker/hardware checks that remain unverified locally.
