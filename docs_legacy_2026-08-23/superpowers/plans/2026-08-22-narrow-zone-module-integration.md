# Narrow-Zone Module Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the dev_driving warehouse entry/exit rules into one fail-closed Trihouse module and provide pure, hardware-module, and full-integration tests.

**Architecture:** `trihouse_pinky_docking.narrow_zone` owns profile parsing and deterministic motion. `fleet_node` owns orchestration only: Nav2 to the entry, narrow enter/exit, pose verification, and then normal Nav2. Physical calibration tests command the existing `ExecuteTransport` boundary and never publish motor velocity directly.

**Tech Stack:** Python 3.12, ROS 2 Jazzy, rclpy actions, Nav2 `NavigateToPose`, YAML, pytest, launch_testing

**Spec:** `docs/superpowers/specs/2026-08-22-narrow-zone-module-integration-design.md`

## Global Constraints

- Preserve all unrelated uncommitted DB, Gateway, compose, and OMX changes.
- Never publish physical motion directly to `cmd_vel`; narrow motion uses `cmd_vel_dock`.
- A narrow warehouse without a complete measured profile fails closed before Nav2 motion.
- A failed or canceled narrow attempt stops once and is never automatically retried.
- `new_map_2` ambient and chilled profiles remain disabled until independently measured.
- Runtime identifiers use canonical destination codes such as `frozen_storage_loading_dock_01`.

---

### Task 1: Canonical narrow-zone profile and controller

**Files:**
- Create: `trihouse_pinky/trihouse_pinky_docking/trihouse_pinky_docking/narrow_zone.py`
- Modify: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/narrow_zone_pilot.py`
- Modify: `trihouse_pinky/trihouse_pinky_docking/trihouse_pinky_docking/sequence.py`
- Test: `trihouse_pinky/test/test_narrow_zone_module.py`

**Interfaces:**
- Consumes: YAML mapping with `map_name` and `zones`
- Produces: `load_narrow_zones(document, map_name) -> dict[str, NarrowZoneProfile]`
- Produces: `NarrowZoneController(profile, direction, limits)` with `begin()`, `advance()`, `cancel()`, `is_complete`, and `failure`

- [ ] **Step 1: Write failing profile tests**

Add literal tests proving that a different map is rejected, disabled profiles are retained as
non-executable metadata, missing `dock_target`/`exit_target` makes a warehouse non-executable,
and frozen has the expected measured enter and exit steps.

- [ ] **Step 2: Run RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q trihouse_pinky/test/test_narrow_zone_module.py
```

Expected: FAIL because `trihouse_pinky_docking.narrow_zone` does not exist.

- [ ] **Step 3: Implement the canonical model and parser**

Create frozen dataclasses `Pose2D`, `OrientedZone`, `MotionStep`, `MeasurementState`,
`NarrowZoneProfile`, `MotionLimits`, and `VelocityCommand`. Parse `enabled`, measurement
booleans, entry, zone, enter, exit, dock target, exit target, and marker id. Expose
`profile.executable` and a Korean readiness reason.

- [ ] **Step 4: Write failing controller tests**

Test shortest-direction rotation, proportional straight-line slowdown, signed reverse motion,
exit-zone completion, step timeout, explicit cancel, and zero command after every terminal state.

- [ ] **Step 5: Run RED, implement, and run GREEN**

Run the command from Step 2. Expected final result: all tests in
`test_narrow_zone_module.py` pass.

- [ ] **Step 6: Replace duplicate implementations with compatibility exports**

Make the old fleet pilot and docking sequence import/re-export the canonical types and helpers.
Keep public names used by existing tests until Task 4 migrates them.

### Task 2: Fail-closed configuration contract

**Files:**
- Modify: `config/narrow_zones.new_map_2.yaml`
- Modify: `config/narrow_zones.trihouse_map_01.yaml`
- Test: `trihouse_pinky/test/test_narrow_zone_profiles.py`
- Test: `tests/physical_readiness/test_02_physical_seed_data.py`

**Interfaces:**
- Consumes: accepted measurements in the spec
- Produces: one explicit readiness state per warehouse profile

- [ ] **Step 1: Write failing shipped-profile tests**

Assert every ambient/chilled/frozen destination is present, every enabled profile is executable,
every warehouse has distinct enter and exit sequences, and unmeasured profiles fail with
`NARROW_PROFILE_NOT_READY` rather than disappearing from the catalog.

- [ ] **Step 2: Run RED**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q trihouse_pinky/test/test_narrow_zone_profiles.py tests/physical_readiness/test_02_physical_seed_data.py
```

Expected: FAIL because current YAML has no explicit measurement booleans and frozen has no
`dock_target`/`exit_target` pair.

- [ ] **Step 3: Normalize the YAML**

Add explicit measurement state and completion targets. Use today's frozen entry/dock values.
Derive the initial frozen exit target by integrating the accepted exit sequence and label it as
computed, not physically measured; keep hardware roundtrip disabled until that target is measured.
Do not enable ambient or chilled.

- [ ] **Step 4: Run GREEN**

Run the Step 2 command. Expected: both files pass.

### Task 3: Fleet orchestration and cancellation

**Files:**
- Modify: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py`
- Test: `trihouse_pinky/test/test_narrow_zone_fleet_orchestration.py`
- Test: `trihouse_pinky/test/test_failed_navigation_can_be_retried.py`

**Interfaces:**
- Consumes: `NarrowZoneProfile` selected by canonical `destination_code`
- Produces: Nav2 entry goal, `cmd_vel_dock` commands, terminal TaskEvent reason codes

- [ ] **Step 1: Write failing orchestration tests**

Use a real profile and narrow controller with fake action boundaries. Assert an executable
warehouse changes the Nav2 goal to `entry_pose`; disabled/unmeasured warehouses reject before
`send_goal_async`; a robot inside a zone executes exit before sending its next Nav2 goal; and
exit target mismatch prevents that goal.

- [ ] **Step 2: Run RED**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q trihouse_pinky/test/test_narrow_zone_fleet_orchestration.py
```

Expected: FAIL because the current fleet silently omits disabled profiles and publishes narrow
commands to `cmd_vel_nav`.

- [ ] **Step 3: Implement minimal orchestration changes**

Load the complete catalog, distinguish ordinary destinations from required-but-not-ready narrow
destinations, publish controller output only to `cmd_vel_dock`, check action cancellation inside
each control iteration, and preserve the existing emergency/pose/timeout stops.

- [ ] **Step 4: Run GREEN and focused regression tests**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  trihouse_pinky/test/test_narrow_zone_fleet_orchestration.py \
  trihouse_pinky/test/test_failed_navigation_can_be_retried.py \
  trihouse_pinky/test/test_narrow_zone_pilot.py
```

Expected: PASS.

### Task 4: Hardware module calibration test

**Files:**
- Create: `tests/hardware/conftest.py`
- Create: `tests/hardware/test_narrow_zone_drive.py`
- Create: `tests/hardware/narrow_zone_client.py`
- Modify: `pytest.ini`

**Interfaces:**
- Consumes: CLI options `--enable-motion`, `--robot-namespace`, `--destination`, `--phase`
- Produces: one bounded `ExecuteTransport` attempt and a JSON trace in `/tmp`

- [ ] **Step 1: Write collection and gate tests**

Test that motion is skipped without `--enable-motion`, unknown destinations are rejected,
non-executable profiles are rejected, and the client refuses to send a goal until readiness,
safety, sole motor publisher, pose, and action-server checks pass.

- [ ] **Step 2: Run RED**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/hardware/test_narrow_zone_drive.py
```

Expected: FAIL because the hardware test helpers do not exist.

- [ ] **Step 3: Implement the bounded client**

Create a real rclpy action client for `ExecuteTransport`; subscribe to Readiness, SafetyState,
RobotStatus, NavigationState, and TaskEvent; use ROS graph publisher inspection for `cmd_vel`;
cancel on timeout or Ctrl+C; never publish Twist. Support exactly one phase per invocation.

- [ ] **Step 4: Run non-motion GREEN**

Run Step 2 without `--enable-motion`. Expected: gate tests pass and the physical scenario is
skipped without sending any action goal.

### Task 5: ROS and full-stack integration tests

**Files:**
- Create: `trihouse_pinky/test/test_narrow_zone_launch_integration.py`
- Create: `tests/e2e/test_narrow_zone_order_cycle.py`
- Modify: `trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_pinky.launch.py`
- Modify: `trihouse_rmf_bridge/launch/two_pinky_order_demo.launch.py`

**Interfaces:**
- Consumes: real ROS nodes/actions with simulated pose and safety inputs
- Produces: deterministic module integration result and full job event sequence

- [ ] **Step 1: Write failing ROS integration test**

Launch the real fleet and safety nodes with fake Nav2/TF/sensor boundaries. Send one frozen goal,
advance pose through literal enter points, and assert `cmd_vel_dock` is gated to `cmd_vel`, arrival
is reported once, next transport runs exit first, and cancel produces zero velocity.

- [ ] **Step 2: Run RED, complete launch wiring, run GREEN**

Run:

```bash
colcon test --packages-select trihouse_pinky_docking trihouse_pinky_fleet trihouse_pinky_bringup \
  --event-handlers console_direct+
```

Expected final result: selected ROS packages have zero test failures.

- [ ] **Step 3: Write full-order integration test**

Create an order whose route includes frozen storage. Assert the persisted step target is the
warehouse destination, RMF dispatch reaches the assigned Pinky, Pinky sends Nav2 only to the
entry, enter/exit events precede OMX/packing/return, and the charger return begins only after a
verified exit.

- [ ] **Step 4: Run the full non-hardware suite**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  trihouse_pinky/test/test_narrow_zone_module.py \
  trihouse_pinky/test/test_narrow_zone_profiles.py \
  trihouse_pinky/test/test_narrow_zone_fleet_orchestration.py \
  tests/e2e/test_narrow_zone_order_cycle.py
```

Expected: PASS; MySQL-dependent cases skip only when the documented test database fixture is
unavailable.

### Task 6: Runbook and final verification

**Files:**
- Modify: `docs/runbooks/p0-narrow-zone-measurement.md`
- Modify: `docs/runbooks/p0-hardware-camera-gated-run.md`

**Interfaces:**
- Consumes: the three test commands from Tasks 1, 4, and 5
- Produces: one safe calibration loop and PASS/FAIL interpretation

- [ ] **Step 1: Document the calibration loop**

Document `approach → enter → exit → roundtrip`, the required E-stop operator and clear path,
the no-auto-retry rule, trace location, and how a measured value moves a profile from disabled to
executable.

- [ ] **Step 2: Run plan self-review and verification**

Check spec coverage, scan the plan for placeholders, run the pure/module/full commands, run
`git diff --check`, and record exact pass/skip/failure counts without claiming physical readiness
unless a hardware-marked run was actually performed.
