# Pinky Warehouse Entry and Safety Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Make Pinky align before a warehouse doorway, cross it without in-place rotation, turn only after reaching the inside point, and recover in a bounded way only from "swept_stop".

**Architecture:** Add a pure WarehouseEntryController beside the legacy narrow-zone controller and select it only for profiles with "entry_passage". The fleet node orchestrates it, but all velocity commands still flow through cmd_vel_dock and the safety supervisor; safety remains the sole motor authority.

**Tech Stack:** Python 3, ROS 2 Jazzy, rclpy, Nav2, YAML, pytest

**Spec:** docs/superpowers/specs/2026-08-24-pinky-entry-safety-recovery-design.md

## Global Constraints

- Keep frozen-storage and charging on the legacy path.
- Use only existing "entry" and "dock_target" coordinates from config/narrow_zones.new_map_2.yaml.
- Label doorway midpoints as trial-derived, not measured.
- Never publish directly to hardware or cmd_vel_safe.
- Recover only for SafetyState.detail == "swept_stop" during entry alignment.
- Every other STOP reason commands zero and fails safely.
- Preserve unrelated control_system and pinky_pro worktree changes.
- Add a failing behavior test before each production change.

---

## Task 1: Entry-passage schema and trial configuration

**Files:**

- Modify: trihouse_pinky/trihouse_pinky_docking/trihouse_pinky_docking/narrow_zone.py
- Modify: config/narrow_zones.new_map_2.yaml
- Test: trihouse_pinky/test/test_narrow_zone_module.py
- Test: trihouse_pinky/test/test_narrow_zone_profiles.py

- [ ] Add a failing parser test for a complete entry_passage block.

~~~python
def test_profile_parses_entry_passage():
    document = _document()
    document["profiles"]["ambient"]["entry_passage"] = {
        "doorway": {"x": 1.05, "y": 0.82, "yaw": 0.33},
        "inside_turn": {"x": 1.19, "y": 0.87, "yaw": 0.33},
        "dock_yaw": -2.80,
        "entry_yaw_tolerance_rad": 0.05,
        "entry_straight_speed_mps": 0.06,
        "heading_correction_max_rps": 0.15,
        "recovery_distance_m": 0.05,
        "recovery_speed_mps": 0.03,
        "recovery_max_attempts": 2,
        "recovery_timeout_s": 10.0,
    }
    profile = load_profiles(document)["ambient"]
    assert profile.entry_passage.doorway.x == pytest.approx(1.05)
~~~

- [ ] Run and confirm the expected AttributeError/parser failure.

~~~bash
pytest -q trihouse_pinky/test/test_narrow_zone_module.py -k entry_passage
~~~

- [ ] Add immutable EntryPassageConfig data and optional NarrowZoneProfile.entry_passage.

~~~python
@dataclass(frozen=True)
class EntryPassageConfig:
    doorway: Pose2D
    inside_turn: Pose2D
    dock_yaw: float
    entry_yaw_tolerance_rad: float
    entry_straight_speed_mps: float
    heading_correction_max_rps: float
    recovery_distance_m: float
    recovery_speed_mps: float
    recovery_max_attempts: int
    recovery_timeout_s: float
~~~

- [ ] Validate finite poses/yaws, positive tolerances/speeds/timeouts, non-negative recovery distance, and positive integer attempts. Legacy profiles remain valid without the block.
- [ ] Add failing validation tests, then implement until they pass.
- [ ] Configure ambient with these approved trial-derived values:

~~~yaml
entry_passage:
  doorway: {x: 1.0533666718902965, y: 0.8253152649415205, yaw: 0.33587139910098424}
  inside_turn: {x: 1.194985191182392, y: 0.874754065282721, yaw: 0.33587139910098424}
  dock_yaw: -2.805721254488808
  entry_yaw_tolerance_rad: 0.05
  entry_straight_speed_mps: 0.06
  heading_correction_max_rps: 0.15
  recovery_distance_m: 0.05
  recovery_speed_mps: 0.03
  recovery_max_attempts: 2
  recovery_timeout_s: 10.0
~~~

- [ ] Configure chilled with the same limits and these poses:

~~~yaml
doorway: {x: 1.0561239087157392, y: 0.2881874148726256, yaw: -1.1394165202222937}
inside_turn: {x: 1.3263418779273253, y: -0.2988701614809928, yaw: -1.1394165202222937}
dock_yaw: 2.4189105956431427
~~~

- [ ] Assert exact ambient/chilled values and that frozen has no entry_passage.
- [ ] Run:

~~~bash
pytest -q trihouse_pinky/test/test_narrow_zone_module.py trihouse_pinky/test/test_narrow_zone_profiles.py
~~~

- [ ] Commit only these files with message: feat(pinky): define warehouse entry passage profiles

## Task 2: Normal warehouse-entry state machine

**Files:**

- Modify: trihouse_pinky/trihouse_pinky_docking/trihouse_pinky_docking/narrow_zone.py
- Test: trihouse_pinky/test/test_narrow_zone_module.py

- [ ] Add a failing deterministic phase-sequence test.

~~~python
def test_warehouse_entry_aligns_crosses_then_turns():
    c = WarehouseEntryController(_entry_passage_profile())
    c.begin(Pose2D(0.91, 0.77, 0.0), now_s=10.0)
    align = c.advance(Pose2D(0.91, 0.77, 0.0), now_s=10.1)
    assert align.linear_x == 0.0 and align.angular_z > 0.0
    straight = c.advance(Pose2D(0.91, 0.77, 0.33), now_s=10.2)
    assert straight.linear_x > 0.0
    assert abs(straight.angular_z) <= 0.15
    turn = c.advance(Pose2D(1.19, 0.87, 0.33), now_s=10.3)
    assert turn.linear_x == 0.0
~~~

- [ ] Confirm failure because WarehouseEntryController is missing.
- [ ] Implement phases ENTRY_ALIGNMENT, ENTER_STRAIGHT, INSIDE_CLEAR, TURN_TO_DOCK, DOCK_APPROACH, RECOVER_ROTATION_SPACE, COMPLETE, FAILED.
- [ ] Enforce these behaviors:
  - ENTRY_ALIGNMENT: zero linear; shortest-angle rotation to doorway heading.
  - ENTER_STRAIGHT: positive configured linear speed; bounded angular correction; no in-place doorway turn.
  - INSIDE_CLEAR: stop at inside_turn before transitioning.
  - TURN_TO_DOCK: rotate toward dock_yaw only inside.
  - DOCK_APPROACH: bounded approach using existing dock tolerances.
  - COMPLETE/FAILED: exact zero command.
- [ ] Add tests for angle wrap, angular clamp, tolerances, timeout, completion, and the no-doorway-rotation invariant.
- [ ] Run: pytest -q trihouse_pinky/test/test_narrow_zone_module.py
- [ ] Commit with message: feat(pinky): add straight-through warehouse entry controller

## Task 3: Bounded swept_stop recovery

**Files:**

- Modify: trihouse_pinky/trihouse_pinky_docking/trihouse_pinky_docking/narrow_zone.py
- Test: trihouse_pinky/test/test_narrow_zone_module.py

- [ ] Add pure SafetyObservation(stopped=False, emergency=False, detail="clear").
- [ ] Add a failing recovery test proving the first swept_stop tick is zero and the next clear tick reverses with zero angular velocity.
- [ ] Implement these invariants:
  - Recovery can start only from ENTRY_ALIGNMENT.
  - First observed swept_stop tick commands zero.
  - Reverse at -recovery_speed_mps with angular_z == 0.
  - Return to alignment after recovery_distance_m and CLEAR/SLOW.
  - Fail after recovery_timeout_s or recovery_max_attempts.
  - Never reverse for emergency, front_stop, keep_out, sensor timeout, or control-link loss.
- [ ] Add tests for each excluded STOP class, attempt exhaustion, timeout, and successful retry.
- [ ] Run:

~~~bash
pytest -q trihouse_pinky/test/test_narrow_zone_module.py -k 'recovery or swept_stop or warehouse_entry'
~~~

- [ ] Commit with message: feat(pinky): recover boundedly from entry swept stop

## Task 4: Fleet wiring and guaranteed workflow cleanup

**Files:**

- Modify: trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py
- Test: trihouse_pinky/test/test_entry_zone_fleet_wiring.py
- Test: trihouse_pinky/test/test_narrow_zone_fleet_orchestration.py

- [ ] Add a failing behavior test that profiles with entry_passage select WarehouseEntryController and profiles without it select the legacy controller.
- [ ] Add a failing test proving _on_safety preserves SafetyState.detail, not only STOP/emergency flags.
- [ ] Store an immutable latest safety observation and pass it to the controller every rule-control tick.
- [ ] Route execution as:

~~~text
Nav2 reaches profile.entry
  -> Nav2 handoff/cancel
  -> entry_passage present: WarehouseEntryController
  -> absent: existing EntryPoseController + NarrowZoneController
~~~

- [ ] Keep output on cmd_vel_dock so the safety supervisor still filters every command.
- [ ] Add a failing orchestration test showing controller failure clears the active workflow and allows the next command instead of "robot is not idle".
- [ ] Centralize local-rule failure cleanup: publish zero, record failure, perform the valid workflow failure transition, verify IDLE, then return.
- [ ] Log only phase/recovery transitions with robot ID, profile, old/new phase, safety detail, attempt, and failure reason.
- [ ] Run:

~~~bash
pytest -q trihouse_pinky/test/test_entry_zone_fleet_wiring.py trihouse_pinky/test/test_narrow_zone_fleet_orchestration.py
~~~

- [ ] Commit with message: feat(pinky): orchestrate warehouse entry and clean failed tasks

## Task 5: Swept-clearance default and diagnostics

**Files:**

- Modify: trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/geometry.py
- Modify: trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/safety_supervisor_node.py
- Test: trihouse_pinky/test/test_safety_fields_match_the_robot.py

- [ ] Add failing pure boundary tests at SWEPT_RADIUS_M - 0.001, exactly SWEPT_RADIUS_M, and + 0.001.
- [ ] Add swept_clearance_blocked(nearby_m, clearance_m), preserving the inclusive <= boundary.
- [ ] Change the default declaration only:

~~~python
self.declare_parameter("swept_clearance_m", SWEPT_RADIUS_M)
~~~

Explicit YAML overrides remain authoritative.

- [ ] Use the pure predicate and add a throttled swept_stop warning containing requested linear/angular velocity, nearby distance, and threshold.
- [ ] Run: pytest -q trihouse_pinky/test/test_safety_fields_match_the_robot.py
- [ ] Commit with message: fix(pinky): use physical swept radius and log stops

## Task 6: Update physical-test documentation

**Files:**

- Modify: docs/guides/pinky-runtime-recovery.md
- Modify: docs/guides/pinky-ambient-chilled-calibration.md

- [ ] Record the root cause:
  - Legacy entry yaw matching rotated at the entry pose and the first narrow-zone step could rotate again.
  - Safety correctly rejected an unsafe rotation as swept_stop.
  - Fleet discarded SafetyState.detail and could not distinguish swept_stop from other STOP reasons.
  - A failed local rule phase could leave workflow active, causing "robot is not idle".
- [ ] Document the new phase sequence, bounded recovery, excluded STOP causes, and midpoint-derived trial coordinates.
- [ ] Separate deployment/run commands by development PC, Pinky terminal 1 bringup, and Pinky terminal 2 observation.
- [ ] Add staged checks: stationary validation, ambient coordinate goal, chilled coordinate goal, frozen legacy regression, then order tests. Require physical clearance review of the long chilled segment before motion.
- [ ] Commit with message: docs(pinky): add doorway entry and swept stop recovery runbook

## Task 7: Complete verification

- [ ] Compile modified modules:

~~~bash
python -m py_compile \
  trihouse_pinky/trihouse_pinky_docking/trihouse_pinky_docking/narrow_zone.py \
  trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py \
  trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/geometry.py \
  trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/safety_supervisor_node.py
~~~

- [ ] Run all Pinky tests:

~~~bash
pytest -q trihouse_pinky/test
~~~

Expected: zero failures.

- [ ] Inspect status and diff:

~~~bash
git status --short
git diff --check
git diff --stat HEAD~5..HEAD
git diff HEAD~5..HEAD -- trihouse_pinky config/narrow_zones.new_map_2.yaml docs/guides
~~~

- [ ] Confirm control_system and pinky_pro were neither staged nor committed.
- [ ] Report exact test results. Do not claim physical motion is verified until deployment and staged robot testing complete.
