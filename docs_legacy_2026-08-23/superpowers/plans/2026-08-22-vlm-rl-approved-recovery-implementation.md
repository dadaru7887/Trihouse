# VLM+RL Operator-Approved Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect 5080 perception/VLM/RL inference to an auditable 4060 operator-approval boundary and a namespace-compatible Pinky recovery action without changing the frozen model architecture.

**Architecture:** The 5080 reads the 4060 MediaMTX stream, combines person/obstacle evidence with an undecidable navigation condition, and posts a bounded recovery proposal. The 4060 persists and approves the proposal, routes the approved command by DB `device_id`, and Pinky executes it through Nav2 while Safety Supervisor remains the only final `cmd_vel` publisher.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, MySQL 8, ROS 2 Jazzy actions, Nav2, PyTorch 2.7.1/CUDA 12.8, Ultralytics, Qwen2.5-VL, Docker Compose, pytest

**Spec:** `docs/architecture/2026-08-22-approved-vlm-rl-recovery-integration-design.md`

## Global Constraints

- Use `ROS_DOMAIN_ID=12` and route commands only with DB `device_id`.
- Keep the frozen `state[9]`, five skills, `coord[3]`, TGRPO+SAC layers, and checkpoint tensor shapes unchanged.
- Store `action_family=detour` for skills 1 and 2 while preserving `selected_skill_id` and `selected_skill_name` for direction.
- Treat `coord` as relative `(dx, dy, dyaw)` and canonicalize it once before safety checks, execution, and persistence.
- Default the Safety gate to enabled; allow disabling only in `training_exploration` mode.
- Require operator approval before physical recovery and keep Safety Supervisor as the sole final `cmd_vel` publisher.
- Keep 4060 responsible for video ingest/archive, Gateway, control, and DB; keep 5080 responsible for inference.
- Pin the 5080 base image to `pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime`.

---

### Task 1: Versioned state and canonical motion contracts

**Files:**
- Modify: `model/vlm_rl/shared/contracts.py`
- Create: `model/vlm_rl/shared/motion_plan.py`
- Modify: `model/vlm_rl/tests/test_inference_boundary.py`
- Create: `model/vlm_rl/tests/test_motion_plan.py`

**Interfaces:**
- Produces: `RecoveryStateV1.to_vector() -> tuple[float, ...]`
- Produces: `canonicalize_recovery_action(skill: int, coord: tuple[float, float, float], pose: Pose2D) -> CanonicalRecoveryAction`
- Produces: `SKILL_TO_ACTION_FAMILY`, `SKILL_NAMES`

- [ ] **Step 1: Write failing tests for named State V1 validation, skill-family naming, dy-aware detour, relative REJOIN conversion, and bounded coordinates.**

```python
state = RecoveryStateV1(robot_x_m=1.0, robot_y_m=2.0, robot_yaw_rad=0.0,
                        goal_x_m=3.0, goal_y_m=4.0,
                        risk_bbox_center_x_norm=0.5,
                        risk_bbox_center_y_norm=0.25,
                        risk_confidence=0.8, vlm_uncertainty=0.1)
assert state.to_vector() == (1.0, 2.0, 0.0, 3.0, 4.0, 0.5, 0.25, 0.8, 0.1)
assert canonicalize_recovery_action(1, (0.1, 0.1, 0.0), Pose2D(0, 0, 0)).heading_rad > 0
```

- [ ] **Step 2: Run `pytest -q model/vlm_rl/tests/test_inference_boundary.py model/vlm_rl/tests/test_motion_plan.py` and confirm failure because the named and canonical contracts do not exist.**
- [ ] **Step 3: Implement strict finite/range validation and one canonical skill-specific conversion with 0.25 m and ±π/3 bounds.**
- [ ] **Step 4: Re-run the focused tests and confirm PASS.**

### Task 2: Runtime mode and Safety gate configuration

**Files:**
- Create: `model/vlm_rl/safety/config.py`
- Create: `model/vlm_rl/tests/test_safety_config.py`
- Modify: `model/vlm_rl/inference/runtime.py`

**Interfaces:**
- Produces: `resolve_safety_gate(runtime_mode: str, cli_value: bool | None, env: Mapping[str, str]) -> bool`
- Consumes: CLI `--runtime-mode`, `--safety-gate-enabled`; env `VLM_RL_RUNTIME_MODE`, `VLM_RL_SAFETY_GATE_ENABLED`

- [ ] **Step 1: Write failing tests proving CLI overrides env, default is true, training can disable, and physical mode rejects false.**
- [ ] **Step 2: Run `pytest -q model/vlm_rl/tests/test_safety_config.py` and confirm the missing module failure.**
- [ ] **Step 3: Implement strict boolean parsing and `physical + false -> ValueError`; include gate state in runtime metadata.**
- [ ] **Step 4: Re-run the focused tests and confirm PASS.**

### Task 3: Recovery proposal, approval, and durable command persistence

**Files:**
- Create: `db/migrations/004_recovery_proposals_and_approvals.sql`
- Modify: `fms_gateway/app/recovery_models.py`
- Modify: `fms_gateway/app/recovery_repository.py`
- Modify: `fms_gateway/app/recovery_routes.py`
- Modify: `fms_gateway/app/main.py`
- Create: `fms_gateway/tests/unit/test_recovery_approval_api.py`
- Create: `fms_gateway/tests/integration/test_recovery_proposal_repository.py`

**Interfaces:**
- Produces: `POST /internal/v1/recovery/proposals`
- Produces: `POST /api/v1/recovery/proposals/{proposal_id}/decision`
- Produces: a transactional outbox command containing proposal hash, approval ID, `device_id`, skill, and canonical action

- [ ] **Step 1: Write failing API/repository tests for named-state input, `safety_manager` authorization, hash binding, expiry, rejection, approval idempotency, and `device_id` routing.**
- [ ] **Step 2: Run the focused unit tests and confirm 404/import failures for the new boundary.**
- [ ] **Step 3: Add append-only proposal/decision/outbox tables and implement atomic repository transitions; do not write example operational rows in the migration.**
- [ ] **Step 4: Implement strict Pydantic request/response models and routes, then run unit tests.**
- [ ] **Step 5: Run the MySQL integration test when `TRIHOUSE_TEST_MYSQL_DSN` is available; otherwise report it as environment-blocked, not passed.**

### Task 4: Device-link recovery downlink contract

**Files:**
- Modify: `fms_gateway/app/tcp_protocol.py`
- Modify: `fms_gateway/tests/unit/test_tcp_protocol.py`
- Create: `fms_gateway/app/recovery_dispatch.py`
- Create: `fms_gateway/tests/unit/test_recovery_dispatch.py`

**Interfaces:**
- Produces: server message `recovery_command` routed through `RobotLinkRegistry.push(device_id, payload)`
- Consumes: approved outbox rows and robot application ACK `recovery_command_ack`

- [ ] **Step 1: Write failing tests for exact payload validation, disconnected retry, matching ACK, duplicate ACK, and wrong-device rejection.**
- [ ] **Step 2: Run focused tests and confirm failure for unsupported recovery messages.**
- [ ] **Step 3: Add the recovery command/ACK schema and a retrying dispatcher that marks delivery only after application ACK.**
- [ ] **Step 4: Re-run focused tests and confirm PASS.**

### Task 5: Namespace-compatible Pinky ExecuteRecovery action

**Files:**
- Create: `trihouse_interfaces/action/ExecuteRecovery.action`
- Modify: `trihouse_interfaces/CMakeLists.txt`
- Create: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/recovery_execution.py`
- Modify: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py`
- Modify: `trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_pinky.launch.py`
- Create: `trihouse_pinky/test/test_recovery_execution.py`
- Create: `trihouse_interfaces/test/test_execute_recovery_contract.py`

**Interfaces:**
- Produces: relative action server `trihouse/recovery/execute`
- Consumes: canonical recovery action and returns observed pose/clearance/Safety result

- [ ] **Step 1: Write static and unit failing tests for the action fields, no absolute ROS names, empty namespace default, namespaced resolution, motion mutual exclusion, and stale/map/device rejection.**
- [ ] **Step 2: Run the focused tests and confirm missing action/executor failures.**
- [ ] **Step 3: Add the ROS action and a focused executor that maps wait, backup, detour, and rejoin to Nav2 behavior/action clients without publishing `cmd_vel`.**
- [ ] **Step 4: Integrate the executor into `FleetNode` with a shared motion lock and relative names, preserving concurrent narrow-zone edits.**
- [ ] **Step 5: Run Python/static tests locally; run `colcon build --packages-select trihouse_interfaces trihouse_pinky_fleet trihouse_pinky_bringup` in a ROS Jazzy environment.**

### Task 6: 5080 perception-to-VLM/RL proposal worker

**Files:**
- Create: `model/vlm_rl/inference/navigation_context.py`
- Create: `model/vlm_rl/inference/trigger.py`
- Create: `model/vlm_rl/inference/vlm_interpreter.py`
- Create: `model/vlm_rl/inference/proposal_client.py`
- Create: `model/vlm_rl/inference/worker.py`
- Modify: `model/vlm_rl/inference/runtime.py`
- Create: `model/vlm_rl/tests/test_realtime_worker.py`

**Interfaces:**
- Consumes: all structured segmentation detections and Gateway navigation context
- Produces: one named State V1 using the highest-risk object plus complete perception evidence
- Produces: a Gateway proposal only when an obstacle/person is present and Nav2 is failed or stuck

- [ ] **Step 1: Write failing tests using fake detector, context source, VLM, policy, and proposal client for no-trigger, person-trigger, obstacle-trigger, invalid VLM JSON, and full-evidence preservation.**
- [ ] **Step 2: Run focused tests and confirm missing worker component failures.**
- [ ] **Step 3: Implement dependency-injected components; preserve the existing Qwen prompt/JSON meaning and frozen checkpoint architecture.**
- [ ] **Step 4: Wire runtime startup and shutdown, then run model tests and prove inference code imports without training modules.**

### Task 7: 5080 image and TestClient dependency

**Files:**
- Modify: `docker/ai/Dockerfile.inference`
- Create: `docker/ai/requirements.inference.txt`
- Modify: `.dockerignore`
- Modify: `compose.ai_5080.yaml`
- Modify: `fms_gateway/requirements-dev.txt`
- Modify: `model/worker/tests/test_vision_compose_contract.py`
- Create: `tests/model/test_ai_5080_image_contract.py`

**Interfaces:**
- Produces: PyTorch 2.7.1/CUDA 12.8 inference image containing `model/worker`, `model/perception`, and `model/vlm_rl/inference`
- Produces: FastAPI TestClient backed by `httpx2==2.9.1`

- [ ] **Step 1: Write failing source-contract tests for the exact base tag, required build-context allowlist, inference-only entrypoint, safety env, and `httpx2==2.9.1`.**
- [ ] **Step 2: Run focused tests and confirm current base/dependency/allowlist failures.**
- [ ] **Step 3: Pin runtime dependencies, copy only inference packages, expose runtime/safety configuration, and preserve repository-root build context because COPY paths are repository-relative.**
- [ ] **Step 4: Run `docker compose -f compose.ai_5080.yaml config --quiet`.**
- [ ] **Step 5: Build on the 4060 and run CPU import/fake-pipeline smoke; classify real CUDA/model smoke as pending until run on 5080.**

### Task 8: End-to-end verification and operator runbook

**Files:**
- Create: `tests/e2e/test_recovery_approval_flow.py`
- Create: `tests/hardware/test_approved_recovery_wait.py`
- Create: `docs/runbooks/vlm-rl-approved-recovery.md`

**Interfaces:**
- Covers: fake RTSP/perception → trigger → proposal → approval → device link → fake ROS action → completion → one trainable JSONL row

- [ ] **Step 1: Write the failing fake end-to-end test and a hardware test that defaults to skip unless an explicit motion-safe flag is set.**
- [ ] **Step 2: Run the fake test and close only wiring gaps exposed by its failure.**
- [ ] **Step 3: Run focused suites, then the relevant repository suite; record exact passed/skipped/failed counts.**
- [ ] **Step 4: Document 4060/5080/Pinky commands, expected evidence, PASS/FAIL meanings, E-stop readiness, sole Safety publisher check, WAIT first, and bounded BACKUP second.**
- [ ] **Step 5: Inspect the final diff for unrelated changes and commit only files belonging to this implementation.**

## Self-Review Result

- Every design section maps to Tasks 1–8; physical motion remains an explicit hardware-only verification.
- The plan contains no placeholder implementation steps and keeps the frozen model math untouched.
- Contract names are consistent: `RecoveryStateV1`, `CanonicalRecoveryAction`, `SKILL_TO_ACTION_FAMILY`, `selected_skill_id`, and `selected_skill_name`.
