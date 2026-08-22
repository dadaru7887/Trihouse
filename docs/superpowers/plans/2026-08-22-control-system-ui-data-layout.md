# Control System UI Data Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the legacy `control_ui/`, make `control_system/` the only web-control source, and separate map-authoring data from UI code.

**Architecture:** Measured JSONL assets move to `data/map_authoring/import/`, while Nav2 maps come only from `pinky_pro_alpha/pinky_navigation/map/`. The legacy custom UI Compose service is removed; the existing `rmf_dashboard` service continues to build from the protected `control_system` submodule.

**Tech Stack:** Bash, Python 3.12, pytest, Docker Compose, ROS 2 Jazzy, MySQL

**Spec:** `docs/superpowers/specs/2026-08-22-control-system-ui-and-map-data-layout-design.md`

## Global Constraints

- Do not modify files inside the `control_system/` submodule.
- The only Nav2 source for `new_map_2` is `pinky_pro_alpha/pinky_navigation/map/`.
- Preserve all 15 measured records in the `new_map_2` JSONL.
- Terminal order creation through `POST /api/v1/orders` remains independent of every UI container.
- Do not stage or overwrite unrelated user changes.

---

### Task 1: Lock the new ownership boundaries

**Files:**
- Create: `tests/architecture/test_control_system_data_layout.py`
- Modify: `tests/physical_readiness/test_02_physical_seed_data.py`

**Interfaces:**
- Consumes: repository root paths
- Produces: path and Compose invariants used by all later tasks

- [ ] **Step 1: Write failing layout tests**

Add assertions that `control_ui/` does not exist, both JSONL files exist under
`data/map_authoring/import/`, `new_map_2.yaml` exists under `pinky_pro_alpha`,
`compose.control.yaml` has no `control_ui` service, and `compose.simulation.yaml`
still references `control_system/openrmf/docker/rmf-web-dashboard`.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
pytest -q tests/architecture/test_control_system_data_layout.py tests/physical_readiness/test_02_physical_seed_data.py
```

Expected: FAIL because the JSONL path and Compose service still use `control_ui`.

- [ ] **Step 3: Commit only after Tasks 2–4 make the contract green**

No commit in the red phase.

### Task 2: Move measured data and update runtime paths

**Files:**
- Move: `control_ui/rmf_control_ui/data/import/trihouse_test_01_physical_features.jsonl` → `data/map_authoring/import/trihouse_test_01_physical_features.jsonl`
- Move: `control_ui/rmf_control_ui/data/import/trihouse_test_01_physical_features.new_map_2.jsonl` → `data/map_authoring/import/trihouse_test_01_physical_features.new_map_2.jsonl`
- Modify: `scripts/p0_publish_map.py`
- Modify: `scripts/p0_reset.sh`
- Modify: `scripts/p0_up.sh`
- Modify: `control_tower/bringup/p0_simulation_bringup.sh`

**Interfaces:**
- Consumes: `pinky_pro_alpha/pinky_navigation/map/<map>.yaml`, `data/map_authoring/import/*.jsonl`
- Produces: `.trihouse/map_yaml`, `.trihouse/map_revision`, published map revision

- [ ] **Step 1: Move both JSONL files without changing their contents**

Use Git-aware moves so history remains traceable.

- [ ] **Step 2: Change map and import constants**

Set the publisher map directory to `pinky_pro_alpha/pinky_navigation/map` and
the import directory to `data/map_authoring/import`. Make the reset script
resolve named maps from the same Pinky Alpha directory. Make `p0_up.sh` pass
the new JSONL path to bringup.

- [ ] **Step 3: Validate shell and Python syntax**

Run:

```bash
bash -n scripts/p0_reset.sh scripts/p0_up.sh control_tower/bringup/p0_simulation_bringup.sh
python3 -m py_compile scripts/p0_publish_map.py scripts/p0_map_publish_config.py
```

Expected: exit code 0.

### Task 3: Remove the legacy web service and directory

**Files:**
- Modify: `compose.control.yaml`
- Modify: `.dockerignore`
- Modify: `.gitignore`
- Delete: `control_ui/`

**Interfaces:**
- Consumes: `control_system/openrmf/docker/rmf-web-dashboard/Dockerfile`
- Produces: Compose services `mysql`, `fms_gateway`, `mediamtx`, `rmf_api`, `rmf_dashboard`

- [ ] **Step 1: Remove the `control_ui` service from `compose.control.yaml`**

Keep Gateway networks and volumes unchanged. Do not change the existing
`rmf_dashboard` service in `compose.simulation.yaml`.

- [ ] **Step 2: Remove obsolete ignore rules and the remaining directory**

Delete legacy UI files only after both JSONL assets exist at the new path.

- [ ] **Step 3: Validate merged Compose configuration**

Run:

```bash
docker compose --project-name trihouse_p0 --env-file .env \
  -f compose.yaml -f compose.control.yaml \
  -f compose.edge_4060.yaml -f compose.simulation.yaml config --quiet
```

Expected: exit code 0 and no `control_ui` service in `docker compose ... config --services`.

### Task 4: Update operational references

**Files:**
- Modify: `docs/runbooks/p0-simulation-quick-run.md`
- Modify: `docs/runbooks/p0-new-map-waypoint-measurement.md`
- Modify: `docs/runbooks/p0-narrow-zone-measurement.md`
- Modify: `docs/runbooks/p0-glb-world-alignment.md`
- Modify: `docs/runbooks/p0-hardware-quick-run.md`
- Modify: `docs/runbooks/waypoint.md`
- Modify: `docs/database/database_guide.md`
- Modify: `docs/superpowers/plans/2026-08-22-new-map-2-waypoint-refresh.md`
- Modify: `docs/superpowers/specs/2026-08-22-new-map-2-waypoint-refresh-design.md`
- Modify: `notebooks/narrow_zone_measurement.ipynb`

**Interfaces:**
- Consumes: the canonical paths established in Tasks 2–3
- Produces: terminal instructions that resolve to existing files

- [ ] **Step 1: Replace operational `control_ui/.../data` references**

Use `data/map_authoring/import/` for JSONL and
`pinky_pro_alpha/pinky_navigation/map/` for occupancy maps. Historical prose
may name the removed component only when explicitly labeled as legacy.

- [ ] **Step 2: Verify executable references**

Run:

```bash
grep -RIn --exclude-dir=.git --exclude-dir=build --exclude-dir=install \
  'control_ui/rmf_control_ui/data' scripts tests control_tower docs
```

Expected: no output.

### Task 5: Verify publication and simulation entrypoints

**Files:**
- Test: `tests/architecture/test_control_system_data_layout.py`
- Test: `tests/physical_readiness/test_02_physical_seed_data.py`
- Test: `tests/test_p0_map_publish_config.py`

**Interfaces:**
- Consumes: new data layout and existing Docker services
- Produces: a published `new_map_2:*` revision and runnable five-terminal procedure

- [ ] **Step 1: Run focused automated tests**

```bash
pytest -q tests/architecture/test_control_system_data_layout.py \
  tests/physical_readiness/test_02_physical_seed_data.py \
  tests/test_p0_map_publish_config.py \
  fms_gateway/tests/unit/test_physical_features.py::test_new_map_2_physical_fixture_is_publishable
```

Expected: all tests pass.

- [ ] **Step 2: Initialize the protected UI submodule in this worktree**

```bash
git submodule update --init -- control_system
```

Expected: `control_system/openrmf/docker/rmf-web-dashboard/Dockerfile` exists.

- [ ] **Step 3: Publish the canonical map**

```bash
scripts/p0_reset.sh /home/newuser/Trihouse/.worktrees/physical-integration-v1/pinky_pro_alpha/pinky_navigation/map/new_map_2.yaml
```

Expected: a `new_map_2:<sha256>` revision is written to DB and `.trihouse/map_revision`.

- [ ] **Step 4: Run simulation bringup and inspect the existing LiDAR blocker**

```bash
scripts/p0_up.sh
```

Expected completion criterion: Nav2 lifecycle 2, lifecycle abort 0, LiDAR publisher present. If this remains red, report it separately from the completed directory migration.

- [ ] **Step 5: Commit the verified layout change**

Stage only files named by this plan and commit with:

```bash
git commit -m "refactor: centralize control UI and map data"
```
