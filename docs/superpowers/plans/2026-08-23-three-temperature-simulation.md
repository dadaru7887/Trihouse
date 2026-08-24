# Three-Temperature Simulation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 주문 입력부터 단일 Pinky의 온도별·다온도 적재와 복귀, OMX 15초 상태 추적, 부하 기반 두 Pinky 병목 제어까지 Gazebo/RViz에서 반복 검증하고 재현 문서를 만든다.

**Architecture:** MySQL/FMS Gateway는 주문·step·reservation 정본을 유지하고 Open-RMF는 mobile dispatch와 fleet lifecycle을 담당한다. Pinky는 Nav2 접근 뒤 규칙 기반 docking을 완료해 영속 `docked` 증거를 남기며, 그 증거와 OMX readiness가 모두 확인된 뒤에만 15초 `picking → loading` action을 시작한다. 단일 Pinky 네 단계를 각각 3회 연속 합격시킨 뒤 부하를 측정해 GUI 또는 headless 두 Pinky 병목 검증으로 전환한다.

**Tech Stack:** ROS 2 Jazzy, rclpy actions, Nav2, Open-RMF EasyFullControl, Gazebo, RViz, FastAPI, MySQL 8, Docker Compose, pytest, colcon

**Spec:** `docs/superpowers/specs/2026-08-23-single-pinky-three-temperature-simulation-design.md`

## Global Constraints

- Canonical IDs are exactly `PK_01`, `PK_02`, `OMX_01`, and `OMX_02`; ROS namespaces are `/pinky_01`, `/pinky_02`, `/omx_01`, and `/omx_02`.
- Simulation does not start Vision, VLM/RL, or `compose.ai_5080.yaml`.
- `OMX_01` serves `ambient` and `chilled`; `OMX_02` serves `frozen`.
- OMX `picking` plus `loading` uses ROS simulation time and totals exactly `15.0` seconds.
- Safety Supervisor remains the only final mobile velocity publisher.
- MySQL/FMS is the reservation authority; Open-RMF remains the mobile dispatch and fleet-lifecycle path.
- A `docked` observation matching job, step, robot, dock, map revision, and freshness is required before OMX motion.
- Each single-Pinky stage stops after three consecutive successes and prints a review summary before the next stage can start.
- At every stage pause, ask the user to run Codex `/status`; if the displayed weekly usage is at least 60%, stop and ask whether to continue because this agent cannot read the account usage dashboard directly.
- `control_system` is pinned to upstream `main` and treated as read-only; `pinky_pro` additions are preserved; `control_ui/` is unused and untouched.

---

## File Structure

### OMX execution and observation

- `trihouse_omx_adapter/trihouse_omx_adapter/simulation_profile.py`: phase timing, progress calculation, and legal phase transitions independent of ROS.
- `tests/simulation/omx/action_server.py`: deterministic action server, 1 Hz feedback, ROS-time execution, and Gazebo joint command publication.
- `trihouse_omx_adapter/trihouse_omx_adapter/action_client.py`: feedback parsing, heartbeat validation, and terminal evidence returned to the executor.
- `control_tower/task_manager/executor_worker.py`: docked gate consumption and OMX phase metrics persisted with step outcomes.
- `control_tower/tests/test_executor_worker.py`: docked-gate and feedback-evidence tests.
- `trihouse_omx_adapter/tests/test_simulation_profile.py`: exact 15-second phase model tests.
- `trihouse_omx_adapter/tests/test_action_client.py`: feedback order and heartbeat validation tests.

### Docking evidence

- `fms_gateway/app/models.py`: typed dock observation request/response models.
- `fms_gateway/app/main.py`: internal endpoint to record and query dock observations.
- `fms_gateway/app/repositories.py`: MySQL and in-memory implementations with idempotency and freshness checks.
- `control_tower/gateway/fms_client.py`: dock-observation client protocol and HTTP implementation.
- `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py`: publish the verified dock observation only after pose/yaw/stop checks pass.
- `fms_gateway/tests/unit/test_dock_observation_api.py`: identity, freshness, and mismatch tests.
- `trihouse_pinky/test/test_dock_observation_wiring.py`: source contract for post-verification reporting.

### Gazebo OMX integration

- `control_system/robo_pinky/src/robo_pinky_sim/config/arms.yaml`: read-only upstream two-arm placement input.
- `control_system/robo_pinky/src/robo_pinky_sim/launch/warehouse.launch.py`: read-only upstream OMX spawn and joint bridge implementation.
- `trihouse_rmf_bridge/launch/two_pinky_order_demo.launch.py`: include the two OMX models without adding a second mobile robot in the single-Pinky stage.
- `control_tower/bringup/p0_simulation_bringup.sh`: pass one/two robot mode, OMX simulation profile, and explicit Vision-off flags.
- `trihouse_rmf_bridge/test/test_two_pinky_order_demo_launch.py`: entity count, namespace, and OMX bridge launch tests.

### Scenario execution and evidence

- `tests/simulation/scenarios.yaml`: canonical ambient, chilled, frozen, and multi-temperature order fixtures.
- `tests/simulation/run_temperature_stage.py`: clean-start gates, order creation, live state capture, consecutive-success counter, stage pause, and summary output.
- `tests/simulation/evidence.py`: per-attempt JSON/JSONL evidence writer and invariant checker.
- `tests/simulation/test_temperature_stage_runner.py`: stage reset, pause, and summary tests.
- `scripts/simulation_stage`: stable operator CLI.

### Bottleneck runtime

- `fms_gateway/app/models.py`: bottleneck acquire, heartbeat, release, and holder response models.
- `fms_gateway/app/main.py`: internal bottleneck lease endpoints.
- `fms_gateway/app/repositories.py`: transactional `reservations.reservation_mode='bottleneck_lock'` operations.
- `control_tower/gateway/fms_client.py`: bottleneck lease client methods.
- `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/bottleneck_gate.py`: approach, waiting-pose, hold, heartbeat, and release state machine.
- `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py`: gate navigation before bottleneck entry.
- `data/map_authoring/import/trihouse_test_01_physical_features.new_map_2.jsonl`: approved waiting poses only if absent from the published source.
- `fms_gateway/tests/unit/test_bottleneck_lease_api.py`: atomic holder and safe release tests.
- `trihouse_pinky/test/test_bottleneck_gate.py`: robot-side waiting behavior tests.
- `tests/e2e/test_two_pinky_bottleneck_runtime.py`: two-process runtime contention test.

### Load measurement and documentation

- `tests/simulation/resource_monitor.py`: CPU, RAM, swap, GPU, Gazebo RTF, and ROS latency sampler.
- `tests/simulation/test_resource_monitor.py`: threshold and GUI/headless decision tests.
- `docs/guides/three-temperature-simulation-runbook.md`: successful simulation setup and stage commands.
- `docs/guides/distributed-physical-vision-runbook.md`: 4060, 5080, OMX_02 server, OMX_01 PC, and Pinky setup, completed only from measured hardware values.

---

### Task 1: OMX 15-Second Phase Model

**Files:**
- Create: `trihouse_omx_adapter/trihouse_omx_adapter/simulation_profile.py`
- Create: `trihouse_omx_adapter/tests/test_simulation_profile.py`

**Interfaces:**
- Produces: `OmxPhase(str, Enum)`, `PhaseSample`, `sample_phase(elapsed_s: float) -> PhaseSample`, `validate_feedback(previous: PhaseSample | None, current: PhaseSample) -> None`
- Timing: `PICKING_DURATION_S = 7.5`, `LOADING_DURATION_S = 7.5`, `TRANSFER_DURATION_S = 15.0`

- [ ] **Step 1: Write the failing exact-boundary tests**

```python
@pytest.mark.parametrize(
    ("elapsed", "phase", "progress"),
    [(0.0, "picking", 0.0), (7.499, "picking", pytest.approx(49.99, abs=0.02)),
     (7.5, "loading", 50.0), (15.0, "succeeded", 100.0)],
)
def test_phase_boundaries(elapsed, phase, progress):
    sample = sample_phase(elapsed)
    assert sample.phase.value == phase
    assert sample.progress == progress
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest -q trihouse_omx_adapter/tests/test_simulation_profile.py`

Expected: FAIL because `simulation_profile` does not exist.

- [ ] **Step 3: Implement the pure phase model**

```python
class OmxPhase(str, Enum):
    PICKING = "picking"
    LOADING = "loading"
    SUCCEEDED = "succeeded"

def sample_phase(elapsed_s: float) -> PhaseSample:
    if elapsed_s < 0:
        raise ValueError("elapsed_s must be non-negative")
    if elapsed_s < PICKING_DURATION_S:
        return PhaseSample(OmxPhase.PICKING, elapsed_s, elapsed_s / TRANSFER_DURATION_S * 100)
    if elapsed_s < TRANSFER_DURATION_S:
        return PhaseSample(OmxPhase.LOADING, elapsed_s - PICKING_DURATION_S, elapsed_s / TRANSFER_DURATION_S * 100)
    return PhaseSample(OmxPhase.SUCCEEDED, LOADING_DURATION_S, 100.0)
```

- [ ] **Step 4: Add transition rejection tests**

Verify progress regression, `loading → picking`, values above 100, and a terminal sample before 15 seconds all raise `ValueError`.

- [ ] **Step 5: Run the focused tests**

Run: `pytest -q trihouse_omx_adapter/tests/test_simulation_profile.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add trihouse_omx_adapter/trihouse_omx_adapter/simulation_profile.py trihouse_omx_adapter/tests/test_simulation_profile.py
git commit -m "feat(omx): define deterministic simulation phases"
```

### Task 2: Continuous ExecuteOmx Feedback

**Files:**
- Modify: `tests/simulation/omx/action_server.py`
- Modify: `trihouse_omx_adapter/trihouse_omx_adapter/action_client.py`
- Create: `trihouse_omx_adapter/tests/test_action_client.py`
- Create: `tests/simulation/test_omx_action_feedback.py`

**Interfaces:**
- Consumes: `sample_phase(elapsed_s)` from Task 1
- Produces: `OmxExecutionEvidence(result: dict[str, Any], feedback: tuple[dict[str, Any], ...])`
- Feedback JSON keys: `schema_version`, `omx_id`, `job_id`, `job_step_id`, `handover_group_id`, `pinky_id`, `phase`, `phase_elapsed_s`, `total_elapsed_s`, `progress`, `joint_state_stamp_ns`, `trajectory_tracking`

- [ ] **Step 1: Write failing parser and ordering tests**

```python
def test_feedback_must_move_from_picking_to_loading():
    tracker = OmxFeedbackTracker(max_gap_s=2.0)
    tracker.accept({"phase": "picking", "total_elapsed_s": 6.0, "progress": 40.0})
    tracker.accept({"phase": "loading", "total_elapsed_s": 8.0, "progress": 53.3})
    with pytest.raises(RuntimeError, match="PHASE_REGRESSION"):
        tracker.accept({"phase": "picking", "total_elapsed_s": 9.0, "progress": 60.0})
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `pytest -q trihouse_omx_adapter/tests/test_action_client.py tests/simulation/test_omx_action_feedback.py`

Expected: FAIL because feedback tracking is absent.

- [ ] **Step 3: Add a feedback callback to the ROS action client**

Pass `feedback_callback=tracker.callback` to `send_goal_async`, parse `feedback.event_json`, enforce identity, monotonic phase/progress, heartbeat gaps, and return `OmxExecutionEvidence` instead of discarding feedback.

- [ ] **Step 4: Make the simulator use ROS time and publish at 1 Hz or faster**

For `kind == "load"`, sample `self.get_clock().now()` until `15.0` simulated seconds have elapsed. Publish every `0.5` simulated seconds so the 2-second heartbeat gate has margin. `prepare` remains a short deterministic state transition and never claims a completed transfer.

- [ ] **Step 5: Verify exact duration and feedback identity**

Assert the first feedback phase is `picking`, `loading` appears at 7.5 seconds, terminal success is not emitted before 15 seconds, and every event contains the command identities.

- [ ] **Step 6: Run focused tests**

Run: `pytest -q trihouse_omx_adapter/tests/test_action_client.py tests/simulation/test_omx_action_feedback.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/simulation/omx/action_server.py tests/simulation/test_omx_action_feedback.py trihouse_omx_adapter/trihouse_omx_adapter/action_client.py trihouse_omx_adapter/tests/test_action_client.py
git commit -m "feat(omx): stream picking and loading feedback"
```

### Task 3: Persist Verified Dock Observations

**Files:**
- Modify: `fms_gateway/app/models.py`
- Modify: `fms_gateway/app/main.py`
- Modify: `fms_gateway/app/repositories.py`
- Modify: `control_tower/gateway/fms_client.py`
- Create: `fms_gateway/tests/unit/test_dock_observation_api.py`
- Modify: `control_tower/tests/test_fms_gateway_client.py`

**Interfaces:**
- Produces: `POST /internal/v1/job-steps/{job_step_id}/dock-observation`
- Request: `{idempotency_key, robot_id, destination_code, map_revision, observed_at, pose, linear_speed, angular_speed, docked}`
- Produces: `GET /internal/v1/job-steps/{job_step_id}/dock-observation`
- Valid only when `docked=true`, destination and assigned robot match the step, speeds are within stop thresholds, and age is at most 5 seconds when consumed.

- [ ] **Step 1: Write failing repository/API tests**

Cover idempotent replay, conflicting replay, wrong robot, wrong destination, non-mobile step, stale observation, and the latest matching observation.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -q fms_gateway/tests/unit/test_dock_observation_api.py`

Expected: FAIL because the endpoints and models are absent.

- [ ] **Step 3: Implement models and repository ports**

Store the observation as an append-only operational event keyed by the supplied idempotency key; do not add a second current-state table. Query the latest event for the step and deserialize its payload into the response model.

- [ ] **Step 4: Add HTTP client methods**

```python
def record_dock_observation(self, job_step_id: int, request: DockObservationRequest) -> DockObservation: ...
def get_dock_observation(self, job_step_id: int) -> DockObservation | None: ...
```

- [ ] **Step 5: Run Gateway and client tests**

Run: `pytest -q fms_gateway/tests/unit/test_dock_observation_api.py control_tower/tests/test_fms_gateway_client.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add fms_gateway/app/models.py fms_gateway/app/main.py fms_gateway/app/repositories.py fms_gateway/tests/unit/test_dock_observation_api.py control_tower/gateway/fms_client.py control_tower/tests/test_fms_gateway_client.py
git commit -m "feat(fms): persist verified dock observations"
```

### Task 4: Report Docking Only After Physical Invariants Pass

**Files:**
- Modify: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py`
- Create: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/dock_observer.py`
- Create: `trihouse_pinky/test/test_dock_observation_wiring.py`
- Modify: `trihouse_pinky/trihouse_pinky_fleet/setup.py`

**Interfaces:**
- Consumes: successful narrow target verification already performed by `_verify_narrow_target()`
- Produces: one idempotent dock observation for the current `TaskContext` and destination

- [ ] **Step 1: Write failing observation-gate tests**

Assert navigation success alone does not report docking, pose/yaw mismatch does not report docking, nonzero velocity does not report docking, and a matching stopped pose reports exactly once.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -q trihouse_pinky/test/test_dock_observation_wiring.py`

Expected: FAIL because `dock_observer` is absent.

- [ ] **Step 3: Implement the isolated reporter**

Derive the idempotency key from `job_step_id`, `execution_id`, destination, and map revision. Send through the existing gateway boundary after `_verify_narrow_target` and zero-velocity confirmation succeed.

- [ ] **Step 4: Ensure action success follows the observation acknowledgement**

If the Gateway cannot record the observation, return a retryable dock failure rather than allowing the load dependency to open with no evidence.

- [ ] **Step 5: Run Pinky focused tests**

Run: `pytest -q trihouse_pinky/test/test_dock_observation_wiring.py trihouse_pinky/test/test_entry_zone_fleet_wiring.py trihouse_pinky/test/test_entry_zone_nav_handoff.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/dock_observer.py trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py trihouse_pinky/trihouse_pinky_fleet/setup.py trihouse_pinky/test/test_dock_observation_wiring.py
git commit -m "feat(pinky): report verified docking evidence"
```

### Task 5: Gate OMX Load and Persist Phase Evidence

**Files:**
- Modify: `control_tower/task_manager/executor_worker.py`
- Modify: `control_tower/task_manager/executor_worker_node.py`
- Modify: `control_tower/tests/test_executor_worker.py`

**Interfaces:**
- Consumes: `get_dock_observation(job_step_id)` and `OmxExecutionEvidence`
- Produces: outcome metrics keys `omx.feedback_count`, `omx.picking_duration_ms`, `omx.loading_duration_ms`, `omx.transfer_duration_ms`, `omx.heartbeat_max_gap_ms`, `dock_observation_id`
- Changes: `OmxExecutor.execute(command: dict[str, object]) -> OmxExecutionEvidence`; result validation reads `evidence.result` and phase validation reads `evidence.feedback`.

- [ ] **Step 1: Write failing load-gate tests**

```python
def test_load_does_not_start_without_matching_fresh_dock_observation():
    worker = make_worker(dock_observation=None)
    report = worker.run_once(limit=1)
    assert report.succeeded == ()
    assert "DOCK_OBSERVATION_MISSING" in report.errors[0]
    assert omx.execute_calls == []
```

Add stale, robot mismatch, destination mismatch, map mismatch, and successful matching cases.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -q control_tower/tests/test_executor_worker.py`

Expected: at least the new dock-gate test fails.

- [ ] **Step 3: Resolve the mobile dependency and validate docking before `_run_arm_load`**

Use the load step's dependency list to locate the matching mobile navigate step. Reject absent or stale evidence before calling the OMX executor.

- [ ] **Step 4: Validate and persist OMX feedback metrics**

Require at least one `picking` and one `loading` heartbeat, total transfer duration `15000 ± 500 ms` in simulation time, no gap above 2000 ms, and terminal trajectory state `tracking` or `settled`.

- [ ] **Step 5: Run worker tests**

Run: `pytest -q control_tower/tests/test_executor_worker.py control_tower/tests/test_job_runner.py control_tower/tests/test_outbound_sequence.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add control_tower/task_manager/executor_worker.py control_tower/task_manager/executor_worker_node.py control_tower/tests/test_executor_worker.py
git commit -m "feat(control): gate loading on verified docking"
```

### Task 6: Spawn and Animate Exactly Two OMX Arms

**Files:**
- Inspect only: `control_system/robo_pinky/src/robo_pinky_sim/config/arms.yaml`
- Inspect only: `control_system/robo_pinky/src/robo_pinky_sim/launch/warehouse.launch.py`
- Modify: `trihouse_rmf_bridge/launch/two_pinky_order_demo.launch.py`
- Modify: `tests/simulation/omx/action_server.py`
- Modify: `trihouse_rmf_bridge/test/test_two_pinky_order_demo_launch.py`

**Interfaces:**
- Gazebo entities: `omx_01`, `omx_02`
- ROS joint command topics: `/omx_01/{joint1,joint2,joint3,joint4,gripper_left_joint,gripper_right_joint}_cmd` and matching `/omx_02/...`
- Joint feedback topics: `/omx_01/joint_states`, `/omx_02/joint_states`

- [ ] **Step 1: Verify the upstream `control_system` input is clean and pinned**

Run: `git -C control_system status --short && git -C control_system branch --show-current && git -C control_system rev-parse HEAD`

Expected: no internal changes, branch `main`, and the reviewed upstream revision recorded in the evidence manifest. Do not edit or commit inside this submodule.

- [ ] **Step 2: Write failing launch contract tests**

Assert one Pinky stage produces one mobile entity and exactly two OMX entities, every joint topic is namespaced, and no `PK_02` nodes are created when `robots:=PK_01`.

- [ ] **Step 3: Run the launch tests and verify failure**

Run: `pytest -q trihouse_rmf_bridge/test/test_two_pinky_order_demo_launch.py`

Expected: the new OMX entity assertions fail.

- [ ] **Step 4: Include the upstream selective two-arm spawn and bridges from the root launch**

Reuse the upstream `warehouse.launch.py` and `omx.urdf.xacro`; do not copy or edit them. Pass canonical two-arm selection and published three-temperature placement from the root launch, and fail bringup when either upstream asset or placement is missing.

- [ ] **Step 5: Map simulator phases to deterministic joint trajectories**

Publish interpolated joint targets at 20 Hz. `picking` closes the gripper after the shelf approach; `loading` moves to Pinky load pose and opens the gripper. Read `/joint_states` and include freshness/tracking in action feedback.

- [ ] **Step 6: Run launch and simulator tests**

Run: `pytest -q trihouse_rmf_bridge/test/test_two_pinky_order_demo_launch.py tests/simulation/test_omx_action_feedback.py`

Expected: PASS.

- [ ] **Step 7: Commit root integration changes only**

```bash
git add trihouse_rmf_bridge/launch/two_pinky_order_demo.launch.py trihouse_rmf_bridge/test/test_two_pinky_order_demo_launch.py tests/simulation/omx/action_server.py
git commit -m "feat(sim): animate two OMX stations"
```

### Task 7: Temperature Stage Runner and Evidence Bundles

**Files:**
- Create: `tests/simulation/scenarios.yaml`
- Create: `tests/simulation/evidence.py`
- Create: `tests/simulation/run_temperature_stage.py`
- Create: `tests/simulation/test_temperature_stage_runner.py`
- Create: `scripts/simulation_stage`

**Interfaces:**
- CLI: `./scripts/simulation_stage ambient|chilled|frozen|multi --required-consecutive 3 --evidence-root artifacts/simulation_runs`
- Exit `0`: stage reached three consecutive successes and summary was written
- Exit `1`: attempt failed and clean-start recovery is required
- Exit `2`: preflight/configuration failure

- [ ] **Step 1: Write failing stage-state tests**

Cover `PASS,PASS,PASS → stop`, `PASS,FAIL → streak reset`, no automatic next stage, unique external references, and summary contents.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -q tests/simulation/test_temperature_stage_runner.py`

Expected: FAIL because the runner is absent.

- [ ] **Step 3: Define canonical fixtures**

Use one seeded product per temperature and one line from each zone for `multi`. Assert planner output assigns `OMX_01` to ambient/chilled, `OMX_02` to frozen, and visits zones in canonical order.

- [ ] **Step 4: Implement preflight and per-attempt evidence**

Preflight checks Docker health, one Pinky, two OMX entities, Nav2 lifecycle, TF/map revision, Vision process absence, action endpoints, and zero stale active jobs/reservations. Capture request/response, steps, dock observation, OMX feedback, poses, return-home result, node list, service list, and PASS/FAIL reason.

- [ ] **Step 5: Implement stage pause and summary**

Write `stage-summary.json` and print the next-stage command, but never execute it. Reset the streak to zero after any failed attempt.

- [ ] **Step 6: Run unit tests**

Run: `pytest -q tests/simulation/test_temperature_stage_runner.py control_tower/tests/test_outbound_planner.py control_tower/tests/test_outbound_sequence.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/simulation/scenarios.yaml tests/simulation/evidence.py tests/simulation/run_temperature_stage.py tests/simulation/test_temperature_stage_runner.py scripts/simulation_stage
git commit -m "feat(sim): add staged temperature validation runner"
```

### Task 8: Single-Pinky Bringup and Four Stage Validations

**Files:**
- Modify: `control_tower/bringup/p0_simulation_bringup.sh`
- Modify: `scripts/control_stack`
- Create: `control_tower/tests/test_p0_bringup_contract.py`
- Modify: `tests/test_control_stack_cli.py`
- Create: `artifacts/simulation_runs/<run-id>/...` at runtime only

**Interfaces:**
- Bringup environment: `TRIHOUSE_ROBOTS=PK_01`, `TRIHOUSE_VISION_ENABLED=false`
- `control_stack doctor` must report one mobile, two OMX, RMF, job runner, executor, and `ai_5080_started=false`

- [ ] **Step 1: Write failing bringup/doctor tests**

Assert simulation defaults to `PK_01`, forbids Vision compose/processes, expects two OMX entities, and exposes exact stage commands.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -q control_tower/tests/test_p0_bringup_contract.py tests/test_control_stack_cli.py`

Expected: at least the one-mobile and two-OMX checks fail.

- [ ] **Step 3: Update bringup and doctor**

Remove the two-Pinky default from this phase, add entity/action/lifecycle checks, and keep the existing RMF core and worker path.

- [ ] **Step 4: Run static verification**

Run: `pytest -q control_tower/tests/test_p0_bringup_contract.py tests/test_control_stack_cli.py trihouse_rmf_bridge/test/test_two_pinky_order_demo_launch.py`

Expected: PASS.

- [ ] **Step 5: Start Docker and ROS layers**

Run in terminal 1: `./scripts/control_stack up --mode simulation --build`

Run in terminal 2: `TRIHOUSE_ROBOTS=PK_01 TRIHOUSE_VISION_ENABLED=false ./scripts/control_stack ros --mode simulation --gui --rviz`

Run in terminal 3: `./scripts/control_stack doctor --mode simulation`

Expected: every required check is `healthy`, exactly one Pinky and two OMX entities exist, and no Vision process exists.

- [ ] **Step 6: Execute and pause after each stage**

Run one command at a time, report its summary, and do not start the next until the summary is handed to the user:

```bash
./scripts/simulation_stage ambient --required-consecutive 3
./scripts/simulation_stage chilled --required-consecutive 3
./scripts/simulation_stage frozen --required-consecutive 3
./scripts/simulation_stage multi --required-consecutive 3
```

Expected: each command eventually exits `0` with a three-success streak. On failure, diagnose, restore clean-start state, and repeat that same stage from streak zero.

- [ ] **Step 7: Commit bringup changes and evidence manifest**

```bash
git add control_tower/bringup/p0_simulation_bringup.sh scripts/control_stack control_tower/tests/test_p0_bringup_contract.py tests/test_control_stack_cli.py artifacts/simulation_runs/manifest.json
git commit -m "feat(sim): validate single-Pinky temperature stages"
```

### Task 9: Transactional Bottleneck Lease API

**Files:**
- Modify: `fms_gateway/app/models.py`
- Modify: `fms_gateway/app/main.py`
- Modify: `fms_gateway/app/repositories.py`
- Modify: `control_tower/gateway/fms_client.py`
- Create: `fms_gateway/tests/unit/test_bottleneck_lease_api.py`

**Interfaces:**
- `POST /internal/v1/bottlenecks/{feature_uuid}/acquire`
- `POST /internal/v1/bottlenecks/{feature_uuid}/heartbeat`
- `POST /internal/v1/bottlenecks/{feature_uuid}/release`
- Response: `{acquired, reservation_id, holder_robot_id, expires_at, reason_code}`

- [ ] **Step 1: Write failing atomicity tests**

Use two repository connections/threads to acquire the same feature. Assert exactly one succeeds, replay by the holder is idempotent, a non-holder cannot heartbeat/release, and an E-stop/held lease is not expired automatically.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -q fms_gateway/tests/unit/test_bottleneck_lease_api.py`

Expected: FAIL because runtime lease endpoints are absent.

- [ ] **Step 3: Implement the reservation transaction**

Resolve published `feature_uuid` to `map_feature_id`, insert `bottleneck_lock`, rely on `uq_reservations_active_resource`, and translate duplicate-key contention into `BOTTLENECK_OCCUPIED` with current holder identity. Heartbeats extend expiry only for the holder.

- [ ] **Step 4: Implement pose-aware release**

Require the latest robot map pose to be outside feature radius plus robot radius and safety margin. Reject release while safety state is held or E-stop.

- [ ] **Step 5: Run Gateway reservation tests**

Run: `pytest -q fms_gateway/tests/unit/test_bottleneck_lease_api.py fms_gateway/tests/unit/test_reservation_expiry_api.py db/tests/test_orchestration_schema.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add fms_gateway/app/models.py fms_gateway/app/main.py fms_gateway/app/repositories.py fms_gateway/tests/unit/test_bottleneck_lease_api.py control_tower/gateway/fms_client.py
git commit -m "feat(fms): add transactional bottleneck leases"
```

### Task 10: Pinky Bottleneck Waiting Gate

**Files:**
- Create: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/bottleneck_gate.py`
- Modify: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py`
- Create: `trihouse_pinky/test/test_bottleneck_gate.py`
- Modify: `control_tower/bringup/p0_runtime_assets.py`
- Modify: `control_tower/tests/test_p0_runtime_assets.py`

**Interfaces:**
- Produces: `BottleneckGate.before_entry(robot_id, feature_uuid, pose) -> GateDecision`
- `GateDecision`: `PROCEED`, `NAVIGATE_TO_WAIT`, `WAIT`, `HOLD`
- Waiting pose is loaded from the same published map revision as the bottleneck feature.

- [ ] **Step 1: Write failing state-machine tests**

Assert no holder → acquire/proceed; another holder → waiting pose/zero velocity; release observed → acquire/proceed; stale heartbeat alone does not steal; E-stop holder keeps lease; map revision mismatch holds.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -q trihouse_pinky/test/test_bottleneck_gate.py`

Expected: FAIL because the gate is absent.

- [ ] **Step 3: Add published waiting-pose derivation**

Fail asset publication when a bottleneck used by a two-robot route has no waiting pose on each approach. Do not use the current arbitrary robot pose as a waiting target.

- [ ] **Step 4: Wire the gate before corridor entry**

Stop Nav2 before the footprint reaches the acquire boundary. Navigate to the approved waiting pose when denied, publish zero safe command while waiting, heartbeat while holding, and release only after pose-aware clearance succeeds.

- [ ] **Step 5: Run Pinky and asset tests**

Run: `pytest -q trihouse_pinky/test/test_bottleneck_gate.py control_tower/tests/test_p0_runtime_assets.py control_tower/tests/test_bottleneck.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/bottleneck_gate.py trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py trihouse_pinky/test/test_bottleneck_gate.py control_tower/bringup/p0_runtime_assets.py control_tower/tests/test_p0_runtime_assets.py data/map_authoring/import/trihouse_test_01_physical_features.new_map_2.jsonl
git commit -m "feat(pinky): gate bottleneck entry with persistent lease"
```

### Task 11: Resource Monitor and Two-Pinky Runtime Validation

**Files:**
- Create: `tests/simulation/resource_monitor.py`
- Create: `tests/simulation/test_resource_monitor.py`
- Create: `tests/e2e/test_two_pinky_bottleneck_runtime.py`
- Modify: `tests/simulation/run_temperature_stage.py`
- Modify: `control_tower/bringup/p0_simulation_bringup.sh`

**Interfaces:**
- Resource summary keys: `cpu_peak_percent`, `ram_peak_percent`, `swap_delta_bytes`, `gpu_peak_percent`, `vram_peak_percent`, `gazebo_rtf_min`, `heartbeat_gap_ms_max`
- `choose_two_robot_mode(summary) -> Literal['gui', 'headless']`

- [ ] **Step 1: Write failing threshold tests**

Assert GUI is selected only at CPU ≤75, RAM ≤80, swap delta 0, VRAM ≤85, and RTF ≥0.8. Every boundary violation selects headless.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -q tests/simulation/test_resource_monitor.py`

Expected: FAIL because the monitor is absent.

- [ ] **Step 3: Implement measurement collection**

Read `/proc`, `nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total`, Gazebo stats, and action heartbeat timestamps. Emit JSON even when GPU is absent; absence selects headless rather than inventing zero load.

- [ ] **Step 4: Write the two-Pinky runtime test**

Start two opposite approaches, assert one active DB holder, verify the denied robot reaches its waiting pose and remains stopped, verify pose-aware release, then verify the waiter acquires and crosses. Repeat with ownership reversed.

- [ ] **Step 5: Run pure and integration tests**

Run: `pytest -q tests/simulation/test_resource_monitor.py tests/e2e/test_two_pinky_bottleneck_runtime.py`

Expected: PASS with the integration fixture; the live ROS test remains separately marked `simulation_runtime`.

- [ ] **Step 6: Run live two-Pinky validation three times**

Use the mode selected from the single-Pinky resource summary:

```bash
TRIHOUSE_ROBOTS=PK_01,PK_02 ./scripts/control_stack ros --mode simulation --gui --rviz
TRIHOUSE_ROBOTS=PK_01,PK_02 ./scripts/control_stack ros --mode simulation
```

Run exactly one of those commands, not both. Execute the two-Pinky scenario until three consecutive successes, capturing holder/waiter/release evidence and resource metrics.

- [ ] **Step 7: Commit**

```bash
git add tests/simulation/resource_monitor.py tests/simulation/test_resource_monitor.py tests/e2e/test_two_pinky_bottleneck_runtime.py tests/simulation/run_temperature_stage.py control_tower/bringup/p0_simulation_bringup.sh artifacts/simulation_runs/manifest.json
git commit -m "feat(sim): validate two-Pinky bottleneck execution"
```

### Task 12: Reproducible Simulation and Physical-Vision Runbooks

**Files:**
- Create: `docs/guides/three-temperature-simulation-runbook.md`
- Create: `docs/guides/distributed-physical-vision-runbook.md`
- Create: `tests/physical_readiness/test_distributed_runbook.py`

**Interfaces:**
- The simulation runbook reproduces the exact successful Docker, ROS, stage, evidence, shutdown, and recovery commands.
- The physical runbook has separate terminal tables for 4060 server, 5080 server, OMX_02 server, OMX_01 general PC, and Pinky onboard.

- [ ] **Step 1: Write failing documentation contract tests**

Assert both documents name every PC role, Docker/host boundary, terminal number, working directory, source/export commands, expected output, PASS condition, shutdown, stale-process recovery, and evidence path. Assert the physical document contains no unverified placeholder SSID/IP.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -q tests/physical_readiness/test_distributed_runbook.py`

Expected: FAIL because the runbooks are absent.

- [ ] **Step 3: Write the simulation runbook from successful evidence**

Use only commands that passed Tasks 8 and 11. Include one-Pinky and selected two-Pinky mode, Docker image revisions, map revision, environment, terminal ownership, stage pauses, evidence interpretation, and clean shutdown.

- [ ] **Step 4: Write the physical/Vision runbook framework from measured sources**

Document 4060 as FMS/Control Tower/MediaMTX/recording, 5080 as central Vision/VLM/RL, OMX_02 as local wrist-camera inference with video stored on 4060, OMX_01 as arm/camera runtime, and Pinky camera as person/obstacle detection. Fill SSID, IP, interface, camera path, Docker image digest, and mount values only after reading them from the actual machines; if hardware is unavailable, explicitly keep the physical runbook unapproved rather than inventing values.

- [ ] **Step 5: Add camera safety and identity checks**

Specify Pinky person/obstacle events, OMX wrist OpenCV QR matching, fixed-camera arm/person observation, fail-safe behavior, and the rule that Vision never publishes raw velocity, arbitrary pose, or unverified joint commands.

- [ ] **Step 6: Validate from clean shells**

Reboot or clear all owned processes, open only the documented terminals, and reproduce the simulation stack. Run the document contract test and record the reviewer/date in the runbook.

- [ ] **Step 7: Run final documentation tests**

Run: `pytest -q tests/physical_readiness/test_distributed_runbook.py tests/physical_readiness`

Expected: PASS for the simulation runbook. Physical/Vision readiness remains false until actual hardware values and camera/model checks are measured in the later phase.

- [ ] **Step 8: Commit**

```bash
git add docs/guides/three-temperature-simulation-runbook.md docs/guides/distributed-physical-vision-runbook.md tests/physical_readiness/test_distributed_runbook.py
git commit -m "docs: add reproducible simulation and vision runbooks"
```

### Task 13: Completion Audit

**Files:**
- Inspect: `docs/superpowers/specs/2026-08-23-single-pinky-three-temperature-simulation-design.md`
- Inspect: all evidence manifests and runbooks created above

**Interfaces:**
- Produces: requirement-by-requirement audit with authoritative file, test, runtime, and evidence paths.

- [ ] **Step 1: Run the complete automated test suite in scoped groups**

```bash
pytest -q trihouse_omx_adapter/tests control_tower/tests fms_gateway/tests/unit trihouse_pinky/test tests/simulation tests/e2e tests/physical_readiness
colcon test --packages-select trihouse_interfaces trihouse_omx_adapter trihouse_pinky_fleet trihouse_rmf_bridge
colcon test-result --verbose
```

Expected: all selected tests pass and `colcon test-result` reports zero failures.

- [ ] **Step 2: Audit every design completion criterion**

For each numbered criterion, link the exact automated test plus live evidence record. Treat a missing live Gazebo/RViz/ROS graph record as incomplete even if unit tests pass.

- [ ] **Step 3: Confirm staged summaries and two-Pinky evidence**

Verify four single-Pinky stage summaries each end with `consecutive_successes: 3`, the two-Pinky summary ends with three successes, and every attempt contains docking, OMX feedback, packing, return-home, Vision-off, and resource evidence.

- [ ] **Step 4: Confirm documentation reproducibility**

Verify the simulation runbook was executed from clean shells. Keep the overall goal active for the later physical/Vision phase until its actual network, cameras, inference, OMX and Pinky tests pass.

- [ ] **Step 5: Commit final manifests and audit**

```bash
git add artifacts/simulation_runs/manifest.json docs/guides/three-temperature-simulation-runbook.md docs/guides/distributed-physical-vision-runbook.md
git commit -m "test(sim): record three-temperature acceptance evidence"
```
