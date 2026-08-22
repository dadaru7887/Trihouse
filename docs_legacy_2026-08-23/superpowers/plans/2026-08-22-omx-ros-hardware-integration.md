# OMX ROS Hardware Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace fake OMX execution with two device-routed ROS Actions backed by the usang/omx LeRobot hardware runtime, while preparing OMX and navigating Pinky in parallel.

**Architecture:** AI-Server-4060 is the sole Gateway claimant and routes commands by canonical DB device ID. Each OMX PC runs a Python 3.12 ROS bridge and a Python 3.10 LeRobot worker connected by a local Unix socket; simulation exposes the identical Action contract from tests only.

**Tech Stack:** ROS 2 Jazzy, custom ROS Action, Python 3.12/3.10, LeRobot 0.4.4, PyTorch, Unix-domain NDJSON, MySQL 8, Docker Compose, pytest

**Spec:** `docs/superpowers/specs/2026-08-22-omx-ros-hardware-integration-design.md`

## Global Constraints

- `ROS_DOMAIN_ID=12` in simulation and hardware.
- DB/command IDs are exactly `OMX_01` and `OMX_02`; ROS namespaces are `/omx_01` and `/omx_02`.
- Only `device_id` selects the target robot.
- Hardware code contains no simulation or mock fallback.
- Unknown products, wrong device IDs, stale revisions, and incomplete results fail closed before motion or departure.
- Hardware images do not contain `tests/simulation`.
- Important system-boundary comments are bilingual English/Korean; self-evident comments are omitted.

---

### Task 1: Import and normalize the OMX hardware runtime

**Files:**
- Create: `trihouse_omx_hardware/` from `origin/usang/omx:trihouse_omx/`
- Create: `config/omx_product_policies.yaml`
- Create: `tests/omx/test_product_policy_catalog.py`
- Modify: imported policy/session/delivery files

**Interfaces:**
- Produces: `ProductPolicyCatalog.load(path)` and `lookup(product_code, temperature_zone)`
- Produces: hardware functions with explicit `device_id`, serial, camera, calibration, and model inputs

- [ ] **Step 1: Write failing mapping tests**

Test all 11 DB SKU codes, one-to-one policy keys, `SKU-ICECONE -> icecorn`, zone mismatch, duplicate policy key, and missing policy.

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/omx/test_product_policy_catalog.py`

Expected: FAIL because the config and loader do not exist.

- [ ] **Step 3: Import branch commits and implement mapping**

Cherry-pick `5b5d95f3`, `599caeef`, `2726b88f`, and `1c566de1`, retain commit provenance, then relocate the imported directory to `trihouse_omx_hardware`. Replace embedded policy keys and hardcoded IDs with the catalog and explicit constructor arguments. Do not enable its Gateway polling entrypoint.

- [ ] **Step 4: Verify GREEN**

Run: `pytest -q tests/omx/test_product_policy_catalog.py`

Expected: PASS.

- [ ] **Step 5: Commit normalization**

```bash
git add config/omx_product_policies.yaml trihouse_omx_hardware tests/omx
git commit -m "feat(omx): import hardware policy runtime"
```

### Task 2: Dispatch explicit dependencies in parallel

**Files:**
- Modify: `control_tower/task_manager/job_runner.py`
- Modify: `control_tower/task_manager/outbound_sequence.py`
- Modify: `control_tower/tests/test_job_runner.py`
- Modify: `control_tower/tests/test_outbound_sequence.py`
- Modify: `fms_gateway/app/repositories.py`
- Modify: `fms_gateway/tests/unit/test_job_runtime_api.py`

**Interfaces:**
- Produces: `ready_steps(steps) -> tuple[JobStepDetail, ...]`
- Consumes: `input.dependencies: list[int]`

- [ ] **Step 1: Write failing runner tests**

Assert two pending steps with empty dependencies dispatch in one cycle, the load gate waits for both, missing dependencies fail closed, and a failed dependency blocks descendants.

- [ ] **Step 2: Verify RED**

Run: `pytest -q control_tower/tests/test_job_runner.py control_tower/tests/test_outbound_sequence.py`

Expected: FAIL because only the earliest unfinished step dispatches.

- [ ] **Step 3: Implement ready-step selection and prepare semantics**

Generate `arm/prepare` and `mobile/navigate` with equal inherited dependencies, then dispatch every ready step using stable per-step idempotency keys.

- [ ] **Step 4: Write and verify failing Gateway tests**

Run: `pytest -q fms_gateway/tests/unit/test_job_runtime_api.py`

Expected: FAIL because Gateway still blocks every lower step number.

- [ ] **Step 5: Implement transactional dependency validation**

Validate listed step numbers under lock, reject missing/self/future dependencies, and remove the blanket lower-step query.

- [ ] **Step 6: Verify GREEN and commit**

Run: `pytest -q control_tower/tests/test_job_runner.py control_tower/tests/test_outbound_sequence.py fms_gateway/tests/unit/test_job_runtime_api.py`

```bash
git add control_tower/task_manager control_tower/tests fms_gateway/app/repositories.py fms_gateway/tests/unit/test_job_runtime_api.py
git commit -m "feat(tasks): dispatch ready workflow branches in parallel"
```

### Task 3: Define the production OMX command and Action contract

**Files:**
- Create: `trihouse_interfaces/action/ExecuteOmx.action`
- Modify: `trihouse_interfaces/CMakeLists.txt`
- Modify: `trihouse_interfaces/test/test_interface_contracts.py`
- Modify: `control_tower/gateway/omx_protocol.py`
- Modify: `control_tower/tests/test_omx_protocol.py`

**Interfaces:**
- Produces: `ExecuteOmx` goal/result/feedback interface
- Produces: versioned command JSON with structured `items`

- [ ] **Step 1: Write failing interface and protocol tests**

Assert the Action fields, structured items, canonical ID, supported kinds, positive revisions, and deterministic JSON round-trip.

- [ ] **Step 2: Verify RED**

Run: `pytest -q trihouse_interfaces/test/test_interface_contracts.py control_tower/tests/test_omx_protocol.py`

Expected: FAIL because `ExecuteOmx.action` and structured command parsing do not exist.

- [ ] **Step 3: Implement the interface and parser**

Add `command_json`, `success/code/result_json`, and `event_json`; extend the Python protocol with `prepare`, `load`, `hold`, and `reset` commands.

- [ ] **Step 4: Verify GREEN and commit**

Run: `pytest -q trihouse_interfaces/test/test_interface_contracts.py control_tower/tests/test_omx_protocol.py`

```bash
git add trihouse_interfaces control_tower/gateway/omx_protocol.py control_tower/tests/test_omx_protocol.py
git commit -m "feat(omx): define device-routed action contract"
```

### Task 4: Replace cargo sensing with OMX execution evidence

**Files:**
- Modify: `control_tower/task_manager/executor_worker.py`
- Modify: `control_tower/tests/test_executor_worker.py`
- Modify: `fms_gateway/app/models.py`
- Modify: `fms_gateway/app/repositories.py`
- Delete: `trihouse_interfaces/msg/CargoState.msg`
- Delete: `trihouse_interfaces/srv/SetCargoLock.srv`
- Modify: `trihouse_interfaces/msg/RobotStatus.msg`
- Modify: `trihouse_interfaces/CMakeLists.txt`
- Modify: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/status_node.py`
- Modify: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py`
- Modify: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/gateway_node.py`
- Modify: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/recovery_health_node.py`
- Modify: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/workflow.py`
- Delete: `trihouse_omx_adapter/trihouse_omx_adapter/gazebo_adapter_node.py`
- Modify: `trihouse_interfaces/test/test_interface_contracts.py`
- Modify: `trihouse_pinky/test/test_robot_status_battery_contract.py`
- Modify: `trihouse_pinky/test/test_pinky_sr_policies.py`
- Modify: `trihouse_interfaces/doc/interface-catalog.md`

**Interfaces:**
- Consumes: Action result `grasp_confirmed`, `release_confirmed`, `policy_completed`, per-item observations
- Produces: item-level `LOAD_CONFIRMED` attempts attributed to the OMX device

- [ ] **Step 1: Write failing evidence tests**

Assert a successful OMX result records all item attempts, partial/missing release evidence blocks departure, and no Pinky cargo state is queried.

- [ ] **Step 2: Verify RED**

Run: `pytest -q control_tower/tests/test_executor_worker.py`

Expected: FAIL because the executor requires cargo sensor fields.

- [ ] **Step 3: Implement OMX evidence and remove cargo runtime interfaces**

Remove CargoState/SetCargoLock subscriptions and fields, make Action results the load evidence, preserve the load ledger, and retain static `unit_weight_kg` inventory data.

- [ ] **Step 4: Verify GREEN and commit**

Run the affected control_tower, fms_gateway, trihouse_interfaces, and trihouse_pinky test suites.

```bash
git add control_tower fms_gateway trihouse_interfaces trihouse_pinky trihouse_omx_adapter tests
git commit -m "feat(load): use omx results as transfer evidence"
```

### Task 5: Implement identical simulation and hardware Action servers

**Files:**
- Create: `trihouse_omx_adapter/trihouse_omx_adapter/action_client.py`
- Create: `trihouse_omx_adapter/trihouse_omx_adapter/action_server.py`
- Create: `trihouse_omx_hardware/worker_server.py`
- Create: `trihouse_omx_hardware/ipc_protocol.py`
- Create: `tests/simulation/omx/action_server.py`
- Create: `tests/omx/test_ipc_protocol.py`
- Create: `tests/omx/test_action_routing.py`
- Modify: `control_tower/task_manager/executor_worker_node.py`

**Interfaces:**
- Produces: `/omx_01/execute` and `/omx_02/execute`
- Produces: `/run/trihouse-omx/worker.sock` NDJSON request/result stream

- [ ] **Step 1: Write failing IPC and routing tests**

Assert device mismatch rejection, command replay, feedback order, timeout, malformed JSON rejection, and `OMX_01 -> /omx_01/execute` derivation.

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/omx/test_ipc_protocol.py tests/omx/test_action_routing.py`

Expected: FAIL because the modules do not exist.

- [ ] **Step 3: Implement local worker protocol and Action adapters**

The ROS bridge validates and forwards JSON; the LeRobot worker owns hardware and caches results by command UUID. The simulation server emits the same event/result JSON without importing hardware packages.

- [ ] **Step 4: Verify GREEN and commit**

Run: `pytest -q tests/omx trihouse_omx_adapter/tests`

```bash
git add trihouse_omx_adapter trihouse_omx_hardware tests/omx tests/simulation control_tower/task_manager/executor_worker_node.py
git commit -m "feat(omx): bridge ros actions to lerobot worker"
```

### Task 6: Package each OMX role with Compose and doctor

**Files:**
- Create: `docker/ros/Dockerfile.omx_bridge`
- Create: `docker/omx/Dockerfile.lerobot`
- Create: `compose.roles/omx.yaml`
- Modify: `.env.example`
- Modify: deployment doctor scripts/tests
- Create: `tests/physical_readiness/test_07_omx_compose.py`

**Interfaces:**
- Consumes: `DEVICE_ID`, `ROS_NAMESPACE`, serial/camera/calibration/model variables
- Produces: two-container OMX role with shared Unix socket volume

- [ ] **Step 1: Write failing Compose contract tests**

Assert domain 12, host networking only for the bridge, explicit devices, read-only model cache, no privileged mode, healthchecks, and absence of simulation modules from hardware build contexts.

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/physical_readiness/test_07_omx_compose.py`

Expected: FAIL because role Compose and images do not exist.

- [ ] **Step 3: Implement images, Compose, environment example, and doctor checks**

Doctor validates udev links, v4l2loopback devices, calibration file, model cache, ROS domain, and Action visibility without moving the arm.

- [ ] **Step 4: Verify GREEN and commit**

Run: `pytest -q tests/physical_readiness/test_07_omx_compose.py tests/test_control_stack_cli.py`

```bash
git add docker compose.roles .env.example tests/physical_readiness tests/test_control_stack_cli.py
git commit -m "feat(deploy): add two-container omx hardware role"
```

### Task 7: Full verification

**Files:**
- Modify: operational documentation only if verification exposes incorrect commands

**Interfaces:**
- Consumes: every previous task
- Produces: evidence that static tests, ROS interface build, and Compose rendering agree

- [ ] **Step 1: Run focused tests**

```bash
pytest -q tests/omx tests/physical_readiness control_tower/tests trihouse_omx_adapter/tests trihouse_pinky/test fms_gateway/tests/unit
```

- [ ] **Step 2: Build ROS packages**

```bash
colcon build --packages-select trihouse_interfaces trihouse_omx_adapter
```

- [ ] **Step 3: Render Compose for both identities**

```bash
DEVICE_ID=OMX_01 ROS_NAMESPACE=omx_01 ROS_DOMAIN_ID=12 docker compose -f compose.roles/omx.yaml config
DEVICE_ID=OMX_02 ROS_NAMESPACE=omx_02 ROS_DOMAIN_ID=12 docker compose -f compose.roles/omx.yaml config
```

- [ ] **Step 4: Confirm worktree scope**

Run: `git status --short && git diff --check`

Expected: only planned files plus the pre-existing unstaged baseline comment edit.
