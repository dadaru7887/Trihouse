# new_map_2 Waypoint Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace provisional new_map_2 departure and bottleneck coordinates with the newly measured poses while preserving the rule-driven frozen dock flow.

**Architecture:** The JSONL remains the coordinate source of truth, the narrow-zone YAML owns deterministic local motion, and DB seeds mirror operational waypoints. RMF runtime assets are derived from JSONL and use mutex groups for bottlenecks.

**Tech Stack:** JSONL, YAML, MySQL seed SQL, Python 3.12, pytest, ROS 2/RMF configuration

**Spec:** `docs/superpowers/specs/2026-08-22-new-map-2-waypoint-refresh-design.md`

## Global Constraints

- All new runtime waypoint, zone, and mutex names are lowercase snake_case.
- `new_map_2` is the only accepted map name.
- `db/migrations/001_physical_v1_baseline.sql` is immutable.
- Repeated identical AMCL samples count as one measurement.
- Existing ambient and chilled coordinates remain unchanged because the attachment contains no new poses for them.

---

### Task 1: Lock the measured coordinate contract

**Files:**
- Modify: `tests/physical_readiness/test_02_physical_seed_data.py`
- Modify: `trihouse_pinky/test/test_narrow_zone_pilot.py`
- Test: `tests/physical_readiness/test_02_physical_seed_data.py`

**Interfaces:**
- Consumes: the accepted measurements in the spec
- Produces: assertions for JSONL, seed SQL, and narrow-zone YAML

- [ ] **Step 1: Write failing assertions**

Assert the two bottleneck centres, `charging_station_narrow_exit`, frozen entry, and frozen dock values exactly match the spec and every new runtime name matches `^[a-z][a-z0-9_]*$`.

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/physical_readiness/test_02_physical_seed_data.py trihouse_pinky/test/test_narrow_zone_pilot.py`

Expected: FAIL because the JSONL still contains the old bottleneck centres and has no departure waypoint record.

- [ ] **Step 3: Update source data and mirrors**

Modify the JSONL bottleneck records, add one `charging_station_narrow_exit` waypoint, update both seed files, and point both charger `exit_target` entries at the new shared waypoint.

- [ ] **Step 4: Verify GREEN**

Run: `pytest -q tests/physical_readiness/test_02_physical_seed_data.py trihouse_pinky/test/test_narrow_zone_pilot.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add data/map_authoring/import/trihouse_test_01_physical_features.new_map_2.jsonl config/narrow_zones.new_map_2.yaml db/seeds/seed_dev.sql db/seeds/seed_hardware.sql tests/physical_readiness/test_02_physical_seed_data.py trihouse_pinky/test/test_narrow_zone_pilot.py
git commit -m "feat(map): apply measured new_map_2 operating points"
```

### Task 2: Verify derived RMF mutex topology

**Files:**
- Modify: `control_tower/tests/test_p0_runtime_assets.py`
- Modify: `control_tower/bringup/p0_runtime_assets.py`
- Test: `control_tower/tests/test_p0_runtime_assets.py`

**Interfaces:**
- Consumes: `load_features(Path) -> tuple[dict[str, dict], dict[str, dict]]`
- Produces: nav graph containing the shared departure waypoint and two independent mutex vertices

- [ ] **Step 1: Write failing graph test**

Assert the graph contains `charging_station_narrow_exit`, `bottleneck_zone_01`, and `bottleneck_zone_02`; both chargers connect through the departure waypoint; each bottleneck retains its own mutex group.

- [ ] **Step 2: Verify RED**

Run: `pytest -q control_tower/tests/test_p0_runtime_assets.py`

Expected: FAIL because the current topology connects chargers directly to bottleneck 01.

- [ ] **Step 3: Update topology**

Replace direct charger-to-bottleneck lanes with charger-to-departure and departure-to-bottleneck lanes. Keep every lane bidirectional.

- [ ] **Step 4: Verify GREEN**

Run: `pytest -q control_tower/tests/test_p0_runtime_assets.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add control_tower/bringup/p0_runtime_assets.py control_tower/tests/test_p0_runtime_assets.py
git commit -m "feat(rmf): route departures through measured narrow exit"
```
