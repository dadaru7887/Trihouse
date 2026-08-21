# Role-Based Compose Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each Trihouse host start and diagnose its own simulation or hardware role with one `control_stack` command and a documented `.env`.

**Architecture:** A small deployment module owns role metadata, environment validation, canonical ID/namespace mappings, and Compose selection. Existing Compose services remain reusable; role overlays add ROS 2 host networking, hardware mounts, and per-host service sets. `up` mutates lifecycle state after fail-closed preflight, while `doctor` remains read-only and emits role-specific JSON evidence.

**Tech Stack:** Docker Engine, Compose V2, ROS 2 Jazzy, Python 3.12, Fast DDS, MediaMTX, pytest, YAML

**Spec:** `docs/superpowers/specs/2026-08-22-role-compose-hardware-deployment-design.md`

## Global Constraints

- Hardware `ROS_DOMAIN_ID` is exactly `12` on every host.
- Hardware roles are `control-4060`, `ai-5080`, `pinky-01`, `pinky-02`, `omx-01`, and `omx-02`; simulation uses role `simulation`.
- Reserved addresses are 5080 `.7`, 4060 `.9`, Pinky `.21/.22`, and OMX `.31/.32` on `192.168.0.0/24`.
- ROS 2 containers use host networking; remote hosts never share Docker bridge networks.
- Pinky map files are mounted read-only from `PINKY_MAP_DIR`; the container reads `/opt/trihouse/maps/new_map_2.yaml` and `.pgm`.
- `doctor` never starts containers, writes DB state, creates an order, resets a device, or sends a motion command.
- Hardware OMX motion remains blocked until a verified driver/action/ack plugin exists; Compose must not substitute the simulator.
- Existing user changes under `pinky_pro/**` are preserved.

---

### Task 1: Define the tracked `.env` contract and role parser

**Files:**
- Modify: `.env.example`
- Create: `control_tower/deployment/__init__.py`
- Create: `control_tower/deployment/role_stack.py`
- Create: `tests/test_role_environment_contract.py`
- Modify: `vision_system/tests/test_vision_compose_contract.py`

**Interfaces:**
- Produces: `RoleSpec`, `ROLE_SPECS`, `load_env(path)`, `validate_role_environment(mode, role, values)`.
- Consumes: plain `KEY=value` files with no shell execution.

- [ ] **Step 1: Write failing tests for exact role/IP/domain contracts**

```python
def test_hardware_role_uses_reserved_address_and_domain_12() -> None:
    values = valid_environment("pinky-01")
    report = validate_role_environment("hardware", "pinky-01", values)
    assert report.errors == ()
    assert values["ROBOT_LAN_IP"] == "192.168.0.21"
    assert values["ROS_DOMAIN_ID"] == "12"

@pytest.mark.parametrize("value", ["52", "0", ""])
def test_hardware_rejects_the_wrong_ros_domain(value: str) -> None:
    values = valid_environment("pinky-01") | {"ROS_DOMAIN_ID": value}
    assert "ROS_DOMAIN_ID must be 12" in validate_role_environment(
        "hardware", "pinky-01", values
    ).errors
```

Also test all six canonical role identity/namespace pairs, placeholder secret rejection, missing
map/device paths, and unknown roles.

- [ ] **Step 2: Run and verify RED**

Run: `pytest -q tests/test_role_environment_contract.py`

Expected: FAIL because the deployment module does not exist.

- [ ] **Step 3: Implement the minimal role model and validators**

```python
@dataclass(frozen=True)
class RoleSpec:
    name: str
    project_name: str
    compose_files: tuple[str, ...]
    services: tuple[str, ...]
    required_env: tuple[str, ...]
    expected_ip: str | None = None
    device_id: str | None = None
    ros_namespace: str | None = None
    requires_gpu: bool = False

@dataclass(frozen=True)
class ValidationReport:
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()
```

`load_env` parses only comments, blank lines, and literal `KEY=value`; it must not `source` the
file or execute substitutions. Validators compare `DEVICE_ID` and `ROS_NAMESPACE` against fixed
role metadata.

- [ ] **Step 4: Rewrite `.env.example` into named sections**

Include `[identity]`, `[ros2]`, `[lan]`, `[control-4060]`, `[ai-5080]`, `[pinky]`, `[omx]`, and
`[simulation]` comments, with `ROS_DOMAIN_ID=12`, actual reserved IPs, map mount variables,
stable `/dev/*/by-id` guidance, and placeholder secrets that hardware validation rejects.

- [ ] **Step 5: Run environment and vision contract tests**

Run:

```bash
pytest -q tests/test_role_environment_contract.py \
  vision_system/tests/test_vision_compose_contract.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add .env.example control_tower/deployment tests/test_role_environment_contract.py \
  vision_system/tests/test_vision_compose_contract.py
git commit -m "feat(deploy): define role environment contracts"
```

### Task 2: Add role Compose overlays

**Files:**
- Create: `compose.roles/control-4060.yaml`
- Create: `compose.roles/pinky.yaml`
- Create: `compose.roles/omx.yaml`
- Create: `compose.roles/simulation.yaml`
- Modify: `compose.ai_5080.yaml`
- Modify: `compose.edge_4060.yaml`
- Create: `tests/test_role_compose_contract.py`

**Interfaces:**
- Consumes: `RoleSpec.compose_files`, role `.env`, locally built/pulled image tags.
- Produces: Compose-valid service graphs for every role.

- [ ] **Step 1: Write failing role Compose tests**

Parse YAML and assert:

```python
def test_pinky_uses_host_ros_network_and_read_only_map_mount() -> None:
    service = compose("compose.roles/pinky.yaml")["services"]["pinky_runtime"]
    assert service["network_mode"] == "host"
    assert service["ipc"] == "host"
    assert "${PINKY_MAP_DIR}:/opt/trihouse/maps:ro" in service["volumes"]
    assert "${PINKY_SERIAL_DEVICE}:${PINKY_SERIAL_DEVICE}" in service["devices"]

def test_hardware_omx_never_uses_the_protocol_simulator() -> None:
    text = path("compose.roles/omx.yaml").read_text()
    assert "omx_protocol_simulator" not in text
    assert "hardware_omx_adapter" in text
```

Test `network_mode: host` for every ROS service, GPU reservation only on 5080, no MySQL
credentials on 5080, and no mock cargo confirmation in hardware overlays.

- [ ] **Step 2: Run and verify RED**

Run: `pytest -q tests/test_role_compose_contract.py`

Expected: FAIL because role overlays do not exist.

- [ ] **Step 3: Add minimal role overlays**

The Pinky command passes separate identity and namespace arguments:

```yaml
command:
  - ros2
  - launch
  - trihouse_pinky_bringup
  - trihouse_pinky.launch.py
  - robot_id:=${DEVICE_ID}
  - namespace:=${ROS_NAMESPACE}
  - map:=${NAV2_MAP_FILE}
  - map_revision:=${MAP_REVISION}
  - control_host:=${CONTROL_4060_IP}
```

The OMX command remaps both node namespace and canonical parameter, but starts only the safe
hardware skeleton until the verified plugin exists. The control overlay starts RMF core,
Gateway worker, and job runner but does not run the simulation-only OMX executor in hardware.

- [ ] **Step 4: Add 5080 camera registry and 4060 fixed-camera inputs**

Mount `config/cameras.yaml:ro` into 5080 and expose `VISION_RTSP_BASE_URL`. Add fixed camera
device variables to `.env.example`; keep the existing MediaMTX as the only publish target.

- [ ] **Step 5: Validate YAML and merged Compose models**

Run:

```bash
pytest -q tests/test_role_compose_contract.py
docker compose --env-file tests/fixtures/deployment/control-4060.env \
  -f compose.yaml -f compose.control.yaml -f compose.edge_4060.yaml \
  -f compose.roles/control-4060.yaml config --quiet
```

Repeat `config --quiet` with checked-in non-secret test fixtures for every role.

- [ ] **Step 6: Commit Task 2**

```bash
git add compose.roles compose.ai_5080.yaml compose.edge_4060.yaml \
  tests/test_role_compose_contract.py tests/fixtures/deployment
git commit -m "feat(deploy): add host role compose overlays"
```

### Task 3: Build role-specific ROS runtime images

**Files:**
- Create: `docker/ros/Dockerfile.control`
- Create: `docker/ros/Dockerfile.omx`
- Create: `docker/ros/Dockerfile.pinky`
- Create: `docker/ros/entrypoints/control.sh`
- Create: `docker/ros/entrypoints/omx.sh`
- Create: `docker/ros/entrypoints/pinky.sh`
- Create: `tests/test_role_dockerfile_contract.py`

**Interfaces:**
- Produces: `trihouse_control_ros:jazzy` (`linux/amd64`), `trihouse_omx_ros:jazzy`
  (`linux/amd64`), and `trihouse_pinky_ros:jazzy` (`linux/arm64`).
- Consumes: ROS 2 Jazzy base images and repository source; no runtime source mutation.

- [ ] **Step 1: Write failing Dockerfile contract tests**

Assert pinned ROS distribution, architecture intent, non-root runtime user, workspace build,
entrypoint, and absence of embedded secrets. For Pinky, assert the map is not copied into the
image because it is a host bind mount.

- [ ] **Step 2: Run and verify RED**

Run: `pytest -q tests/test_role_dockerfile_contract.py`

Expected: FAIL because the files do not exist.

- [ ] **Step 3: Add minimal Dockerfiles and entrypoints**

Each entrypoint sources ROS and the colcon overlay without sourcing `.env`:

```bash
#!/usr/bin/env bash
set -euo pipefail
source /opt/ros/jazzy/setup.bash
source /opt/trihouse/install/setup.bash
exec "$@"
```

The Pinky image includes the protected vendor packages as read-only build input but does not
modify them. Use a BuildKit platform declaration so the image cannot silently build for amd64.

- [ ] **Step 4: Perform static builds without pulling on test-only hosts**

Run:

```bash
pytest -q tests/test_role_dockerfile_contract.py
docker buildx build --check -f docker/ros/Dockerfile.control .
docker buildx build --check -f docker/ros/Dockerfile.omx .
docker buildx build --check -f docker/ros/Dockerfile.pinky .
```

Expected: static checks PASS. Actual image build/pull is a later host validation and must not be
reported as complete from static checks.

- [ ] **Step 5: Commit Task 3**

```bash
git add docker/ros tests/test_role_dockerfile_contract.py
git commit -m "build: add ROS role runtime images"
```

### Task 4: Refactor `control_stack` into role-aware lifecycle commands

**Files:**
- Modify: `scripts/control_stack`
- Modify: `tests/test_control_stack_cli.py`

**Interfaces:**
- Consumes: `ROLE_SPECS`, `.env`, `--mode`, `--role`.
- Produces: `bootstrap`, `up`, `status`, `logs`, `doctor`, `down`; removes the separate host-only
  `ros` requirement after Compose owns the ROS services.

- [ ] **Step 1: Rewrite tests for the desired CLI**

Add parameterized tests for all roles:

```python
@pytest.mark.parametrize("role", ROLE_NAMES)
def test_role_selects_one_compose_project(role: str) -> None:
    command = module.compose_command("ps", mode="hardware", role=role, values=valid_env(role))
    assert command[:4] == ["docker", "compose", "--project-name", f"trihouse_{role.replace('-', '_')}"]

def test_doctor_does_not_call_up(monkeypatch) -> None:
    calls = capture_subprocess(monkeypatch)
    module.main(["doctor", "--mode", "hardware", "--role", "pinky-01"])
    assert not any("up" in call for call in calls)
```

Test fallback to `TRIHOUSE_ROLE`, unknown-role rejection, bootstrap copy behavior, opposite-mode
local project detection, and preflight before any `up` subprocess.

- [ ] **Step 2: Run and verify RED**

Run: `pytest -q tests/test_control_stack_cli.py`

Expected: FAIL because only simulation mode and one global project are supported.

- [ ] **Step 3: Implement role-aware parser and Compose selection**

Public parser contract:

```text
control_stack bootstrap --mode {simulation,hardware} --role ROLE
control_stack up        --mode {simulation,hardware} --role ROLE [--build]
control_stack status    --mode {simulation,hardware} --role ROLE
control_stack logs      --mode {simulation,hardware} --role ROLE
control_stack doctor    --mode {simulation,hardware} --role ROLE
control_stack down      --mode {simulation,hardware} --role ROLE
```

`up` runs environment validation and `docker compose config --quiet` before the first lifecycle
mutation, then one `up -d --wait` for the role service graph rather than one call per service.

- [ ] **Step 4: Implement safe bootstrap**

If `.env` does not exist, copy `.env.example` with mode `0600`; create only role runtime
directories. If it exists, do not overwrite it. Print device discovery commands when a required
device path is absent. Do not install packages, change groups/firewall, or invent secrets.

- [ ] **Step 5: Run CLI tests**

Run: `pytest -q tests/test_control_stack_cli.py tests/test_role_environment_contract.py`

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add scripts/control_stack tests/test_control_stack_cli.py
git commit -m "feat(deploy): make lifecycle CLI role aware"
```

### Task 5: Add role-specific read-only doctor probes

**Files:**
- Create: `control_tower/deployment/doctor.py`
- Create: `tests/test_role_doctor.py`
- Modify: `scripts/control_stack`

**Interfaces:**
- Produces: `DoctorReport(mode, role, ros_domain_id, checks, healthy)` JSON.
- Consumes: bounded subprocess/HTTP/RTSP probes injected for unit tests.

- [ ] **Step 1: Write failing doctor behavior tests**

```python
def test_pinky_doctor_requires_canonical_status_and_transport_action(fake_probe) -> None:
    report = doctor("hardware", "pinky-01", valid_env("pinky-01"), fake_probe)
    assert set(report.checks) >= {
        "compose", "lan_ip", "ros_domain", "serial", "camera", "robot_status",
        "transport_action", "motor_safety_owner",
    }

def test_doctor_is_bounded_and_read_only(fake_probe) -> None:
    doctor("hardware", "ai-5080", valid_env("ai-5080"), fake_probe)
    assert fake_probe.mutations == []
    assert all(call.timeout_s <= 10 for call in fake_probe.calls)
```

Test that OMX reports `motion_plugin=blocked` and unhealthy while only the skeleton is present.

- [ ] **Step 2: Run and verify RED**

Run: `pytest -q tests/test_role_doctor.py`

Expected: FAIL because doctor probes do not exist.

- [ ] **Step 3: Implement injected bounded probes**

Use typed probe methods for Compose ps, local IP, file/device existence, ROS node/topic/action,
HTTP GET, `ffprobe`, and NVIDIA. Do not use a generic shell string. Redact credentials from all
returned commands and errors.

- [ ] **Step 4: Wire role check sets and JSON output**

Hardware OMX remains explicitly blocked until the adapter reports an approved motion plugin.
Simulation doctor reports `act_contract=deterministic_fake`; hardware never reports simulated
success.

- [ ] **Step 5: Run doctor and lifecycle tests**

Run:

```bash
pytest -q tests/test_role_doctor.py tests/test_control_stack_cli.py
./scripts/control_stack doctor --mode simulation --role simulation
```

Expected: tests PASS; local doctor may return exit 1 with explicit absent checks when the stack
is not running, which is correct.

- [ ] **Step 6: Commit Task 5**

```bash
git add control_tower/deployment/doctor.py tests/test_role_doctor.py \
  scripts/control_stack
git commit -m "feat(deploy): add read-only role doctor"
```

### Task 6: Update deployment runbooks and execute static verification

**Files:**
- Modify: `docs/deployment/environment_overview.md`
- Modify: `docs/deployment/server_4060_deployment.md`
- Modify: `docs/deployment/server_5080_deployment.md`
- Create: `docs/deployment/pinky_pi_deployment.md`
- Create: `docs/deployment/omx_pc_deployment.md`
- Modify: `docs/deployment/local_simulation_demo.md`

**Interfaces:**
- Consumes: final CLI and `.env.example` contracts.
- Produces: one-command role runbooks with PASS/FAIL interpretation and no embedded secrets.

- [ ] **Step 1: Add documentation contract tests**

Extend existing deployment tests or add `tests/test_role_deployment_docs.py` to assert all roles,
`ROS_DOMAIN_ID=12`, actual reserved IPs, map discovery commands, `.env.example` retention, and
the hardware OMX blocked warning are documented.

- [ ] **Step 2: Run and verify RED**

Run: `pytest -q tests/test_role_deployment_docs.py`

Expected: FAIL until runbooks are updated.

- [ ] **Step 3: Write role runbooks**

Every role includes:

```bash
cp .env.example .env          # first install only; never commit .env
./scripts/control_stack bootstrap --mode hardware --role pinky-01
./scripts/control_stack up --mode hardware --role pinky-01 --build
./scripts/control_stack doctor --mode hardware --role pinky-01
```

Explain that Compose is executed on the Pinky's internal Pi, not remotely on the 4060.

- [ ] **Step 4: Run the full static suite**

Run:

```bash
pytest -q db/tests tests/test_device_command_identity_contract.py \
  tests/test_role_environment_contract.py tests/test_role_compose_contract.py \
  tests/test_role_dockerfile_contract.py tests/test_control_stack_cli.py \
  tests/test_role_doctor.py tests/test_role_deployment_docs.py \
  vision_system/tests/test_vision_compose_contract.py
git diff --check
```

Expected: PASS with no warnings attributable to changed code.

- [ ] **Step 5: Validate Compose rendering for every role**

Run a checked-in test-env loop that invokes `docker compose ... config --quiet` for
`control-4060`, `ai-5080`, both Pinkies, both OMX PCs, and simulation. This renders
configuration only and starts no containers.

- [ ] **Step 6: Record hardware validation as pending, not passed**

In the handoff, list per-host commands that still require execution on the actual 4060, 5080,
Pi, and OMX PCs. Do not claim camera decode, DDS discovery, GPU inference, or physical motion
from local static tests.

- [ ] **Step 7: Commit Task 6**

```bash
git add docs/deployment tests/test_role_deployment_docs.py
git commit -m "docs: add role deployment runbooks"
```

