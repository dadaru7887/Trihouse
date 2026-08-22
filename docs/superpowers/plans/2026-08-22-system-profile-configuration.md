# Trihouse System Profile Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 하나의 검증된 시스템 프로파일과 역할만 지정해 Trihouse의 Compose·ROS 2·JobRunner를 실행하고, 포장대별 작업자 배정과 관제 완료 팝업까지 같은 설정 정본으로 연결한다.

**Architecture:** 저장소 최상위의 `trihouse_config` 모듈이 YAML을 한 번의 규칙으로 읽고 역할별 설정을 만든다. `scripts/bringup`은 이 결과를 기존 Compose와 ROS launch에 전달하고, Gateway와 JobRunner는 같은 프로파일에서 포장 도크·작업자 및 Pinky·충전소 매핑을 읽는다. 관제 UI는 설정 파일을 직접 읽지 않고 Job assignment에 영속화된 `packing_worker_id`만 사용한다.

**Tech Stack:** Python 3.12, dataclasses, PyYAML, pytest, ROS 2 Jazzy launch/rclpy, Docker Compose, FastAPI, MySQL 8.4, Flutter/Dart.

**Spec:** `docs/superpowers/specs/2026-08-22-system-profile-configuration-design.md`

## Global Constraints

- 실물 ROS 2 통신은 `ROS_DOMAIN_ID=12`를 사용한다.
- 설정 필드와 논리 키는 소문자 `snake_case`를 사용한다.
- DB·명령 식별자인 `PK_01`, `PK_02`, `OMX_01`, `OMX_02`, `PACKING-01-DOCK-01`, `PACKING-01-DOCK-02`, `W-FIELD-01`, `W-FIELD-02`의 표기를 바꾸지 않는다.
- 프로파일에는 코드, DB seed, DHCP 예약, 실측 파일에서 확인된 실제 값만 기록한다. 확인할 수 없는 값은 빈 문자열로 두며 임의 기본값을 만들지 않는다.
- 선택한 역할의 필수값이 비어 있으면 doctor가 정확한 YAML 필드 경로를 출력하고 bringup은 시작하지 않는다.
- 암호와 토큰은 `.env`에만 두고 프로파일, 오류 출력, 로그에 넣지 않는다.
- 루트 `tests/`는 simulation 전용으로 유지한다. 실물 점검은 `scripts/hardware/`와 `docs/runbooks/`에 둔다.
- 기존 `pinky_pro` 미커밋 변경과 현재 worktree의 다른 변경은 수정하거나 커밋에 포함하지 않는다.
- 각 Task는 지정된 파일만 stage하고 별도 커밋한다.

---

### Task 1: 공용 시스템 프로파일 모델과 검증기

**Files:**
- Create: `trihouse_config/__init__.py`
- Create: `trihouse_config/profile.py`
- Create: `control_tower/tests/test_system_profile.py`

**Interfaces:**
- Produces: `load_system_profile(path: str | Path, *, repo_root: Path | None = None) -> SystemProfile`
- Produces: `validate_system_profile(profile: SystemProfile, *, role: str | None = None, environment: Mapping[str, str] | None = None, host_addresses: Collection[str] = ()) -> tuple[ProfileIssue, ...]`
- Produces: `resolve_role(profile: SystemProfile, role: str) -> ResolvedRole`
- Produces: `SystemProfile.packing_worker_by_dock: Mapping[str, str]`
- Produces: `SystemProfile.charger_by_mobile: Mapping[str, str]`
- Produces: `ResolvedRole.environment: Mapping[str, str]` and `ResolvedRole.command_kind: str`

- [ ] **Step 1: Write failing parser and immutable-mapping tests**

```python
def test_loads_confirmed_physical_identity_without_normalizing_db_ids(tmp_path):
    profile_path = _write_profile(tmp_path, PHYSICAL_PROFILE)
    profile = load_system_profile(profile_path, repo_root=tmp_path)

    assert profile.ros_domain_id == 12
    assert profile.robots["pinky_01"].device_id == "PK_01"
    assert profile.packing_worker_by_dock == {
        "PACKING-01-DOCK-01": "W-FIELD-01",
        "PACKING-01-DOCK-02": "W-FIELD-02",
    }
    assert profile.charger_by_mobile == {
        "PK_01": "TRIHOUSE-TEST-01-CHG-01",
        "PK_02": "TRIHOUSE-TEST-01-CHG-02",
    }


def test_unknown_omx_hardware_values_stay_empty(tmp_path):
    profile_path = _write_profile(tmp_path, PHYSICAL_PROFILE)
    profile = load_system_profile(profile_path, repo_root=tmp_path)

    assert profile.omx_stations["omx_01"].serial_device == ""
    assert profile.omx_stations["omx_01"].front_camera == ""
```

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: `python -m pytest control_tower/tests/test_system_profile.py -q`

Expected: FAIL because `trihouse_config.profile` does not exist.

- [ ] **Step 3: Implement typed, immutable profile parsing**

```python
@dataclass(frozen=True)
class ProfileIssue:
    path: str
    code: str
    message: str


@dataclass(frozen=True)
class SystemProfile:
    source: Path
    repo_root: Path
    profile_name: str
    use_sim_time: bool
    ros_domain_id: int
    rmw_implementation: str
    discovery_range: str
    hosts: Mapping[str, HostConfig]
    control: ControlConfig
    map: MapConfig
    robots: Mapping[str, RobotConfig]
    omx_stations: Mapping[str, OmxConfig]
    packing_worker_by_dock: Mapping[str, str]

    @property
    def charger_by_mobile(self) -> Mapping[str, str]:
        return MappingProxyType({
            robot.device_id: robot.charger_code
            for robot in self.robots.values()
        })
```

Use `yaml.safe_load`, reject unknown top-level keys, copy all nested dictionaries into frozen dataclasses or `MappingProxyType`, and resolve relative file paths against `repo_root` without changing blank strings.

- [ ] **Step 4: Add failing structural validation tests**

```python
@pytest.mark.parametrize(
    ("mutate", "path", "code"),
    [
        (lambda value: value["ros"].update(domain_id=52), "ros.domain_id", "unexpected_value"),
        (lambda value: value["robots"]["pinky_02"].update(device_id="PK_01"), "robots.pinky_02.device_id", "duplicate"),
        (lambda value: value["robots"]["pinky_02"].update(namespace="pinky_01"), "robots.pinky_02.namespace", "duplicate"),
        (lambda value: value["packing_dock_assignments"].append(value["packing_dock_assignments"][0]), "packing_dock_assignments", "duplicate"),
    ],
)
def test_validation_reports_exact_field_path(tmp_path, mutate, path, code):
    raw = deepcopy(PHYSICAL_PROFILE)
    mutate(raw)
    profile = load_system_profile(_write_profile(tmp_path, raw), repo_root=tmp_path)
    issues = validate_system_profile(profile)
    assert any(issue.path == path and issue.code == code for issue in issues)
```

- [ ] **Step 5: Implement structural and role-specific validation**

Validation must cover schema version, lowercase snake-case logical names, duplicate DB IDs/namespaces/IPs, exact domain 12 for `physical_01`, file existence, physical `use_sim_time=false`, dock-worker uniqueness, and `.env` conflicts. Role-specific validation treats the six OMX hardware fields as required only for `omx_01` or `omx_02`; an empty value yields `ProfileIssue(path="omx_stations.omx_01.serial_device", code="required", ...)` rather than a guessed device path.

- [ ] **Step 6: Run profile tests and the existing config-adjacent suite**

Run: `python -m pytest control_tower/tests/test_system_profile.py control_tower/tests/test_job_runner_node.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the profile library**

```bash
git add trihouse_config/__init__.py trihouse_config/profile.py control_tower/tests/test_system_profile.py
git commit -m "feat(config): add validated system profiles"
```

### Task 2: 실제 값 기반 physical 및 simulation 프로파일

**Files:**
- Create: `config/profiles/physical_01.yaml`
- Create: `config/profiles/simulation.yaml`
- Modify: `.env.example`
- Test: `control_tower/tests/test_system_profile_files.py`

**Interfaces:**
- Consumes: `load_system_profile` and `validate_system_profile` from Task 1.
- Produces: repository-owned profile paths used by every later task.

- [ ] **Step 1: Write failing repository profile contract tests**

```python
def test_physical_profile_contains_only_confirmed_network_values(repo_root):
    profile = load_system_profile(
        repo_root / "config/profiles/physical_01.yaml", repo_root=repo_root
    )
    assert profile.hosts["control"].address == "192.168.0.9"
    assert profile.hosts["ai_5080"].address == "192.168.0.7"
    assert profile.robots["pinky_01"].host == "192.168.0.21"
    assert profile.robots["pinky_02"].host == "192.168.0.22"
    assert profile.omx_stations["omx_01"].host == "192.168.0.31"
    assert profile.omx_stations["omx_02"].host == "192.168.0.32"


def test_unknown_omx_device_paths_are_blank(repo_root):
    profile = load_system_profile(
        repo_root / "config/profiles/physical_01.yaml", repo_root=repo_root
    )
    assert profile.omx_stations["omx_01"].serial_device == ""
    assert profile.omx_stations["omx_02"].wrist_camera == ""
```

- [ ] **Step 2: Run tests and confirm missing-file failure**

Run: `python -m pytest control_tower/tests/test_system_profile_files.py -q`

Expected: FAIL because the two profile files do not exist.

- [ ] **Step 3: Create `physical_01.yaml` using only confirmed values**

Copy the approved schema from the spec. Use the DHCP reservations `192.168.0.7`, `.9`, `.21`, `.22`, `.31`, `.32`; canonical DB IDs; `ROS_DOMAIN_ID=12`; existing map and parameter paths; and existing gateway ports. Leave `serial_device`, `front_camera`, `wrist_camera`, `calibration_id`, `calibration_directory`, and `model_cache_directory` as `""` for both OMX stations because no measured values are available in the repository.

- [ ] **Step 4: Create `simulation.yaml` from executable simulation defaults**

Use `use_sim_time: true`, domain 12, the same DB IDs/namespaces/endpoints, and paths found in `control_tower/bringup/p0_simulation_bringup.sh`. Do not copy physical IPs into simulated processes that bind to loopback; use the existing `127.0.0.1` gateway values verified in that script.

- [ ] **Step 5: Mark profile-owned values in `.env.example`**

Keep credentials, bind addresses and host-local device overrides in `.env.example`. Keep `ROS_DOMAIN_ID=12` because Compose and directly launched ROS processes consume the environment, but document that `physical_01.yaml` is authoritative and doctor rejects any different value. Do not delete `.env.example`.

- [ ] **Step 6: Run repository profile tests**

Run: `python -m pytest control_tower/tests/test_system_profile.py control_tower/tests/test_system_profile_files.py -q`

Expected: PASS. The structural validator may report the known blank OMX hardware fields only when validating an OMX role, not when parsing `control`, Pinky, AI or simulation roles.

- [ ] **Step 7: Commit the real-value profiles**

```bash
git add config/profiles/physical_01.yaml config/profiles/simulation.yaml .env.example control_tower/tests/test_system_profile_files.py
git commit -m "feat(config): add physical and simulation profiles"
```

### Task 3: 단일 doctor 및 bringup 진입점

**Files:**
- Create: `scripts/bringup`
- Create: `control_tower/tests/test_system_bringup.py`
- Modify: `scripts/control_stack`
- Modify: `scripts/omx_stack`
- Modify: `control_tower/bringup/p0_simulation_bringup.sh`

**Interfaces:**
- Consumes: `resolve_role(profile, role) -> ResolvedRole` from Task 1.
- Produces CLI: `scripts/bringup --profile PATH --role ROLE {doctor,up,status,logs,down}`.
- Produces: `build_role_command(resolved: ResolvedRole, command: str) -> tuple[list[str], dict[str, str]]` for tests.
- Produces existing Pinky launch arguments from one resolved profile; individual launch files remain node-composition boundaries rather than additional profile parsers.

- [ ] **Step 1: Write failing CLI and command-construction tests**

```python
def test_pinky_role_builds_hardware_launch_with_confirmed_identity(profile):
    command, environment = build_role_command(resolve_role(profile, "pinky_01"), "up")
    assert command[:4] == [
        "ros2", "launch", "trihouse_pinky_bringup", "trihouse_pinky.launch.py"
    ]
    assert "robot_id:=PK_01" in command
    assert "namespace:=pinky_01" in command
    assert environment["ROS_DOMAIN_ID"] == "12"


def test_omx_doctor_reports_blank_real_world_value_without_starting(profile, capsys):
    result = doctor(profile, role="omx_01", environment={}, host_addresses={"192.168.0.31"})
    assert result == 1
    assert "omx_stations.omx_01.serial_device" in capsys.readouterr().out
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `python -m pytest control_tower/tests/test_system_bringup.py -q`

Expected: FAIL because `scripts/bringup` does not exist.

- [ ] **Step 3: Implement the non-mutating doctor path**

Doctor loads `.env` without printing values, collects local IPv4 addresses, validates the selected role, checks referenced files and executables, and emits stable JSON:

```json
{
  "profile": "physical_01",
  "role": "omx_01",
  "healthy": false,
  "issues": [
    {
      "path": "omx_stations.omx_01.serial_device",
      "code": "required",
      "message": "actual value is not configured"
    }
  ]
}
```

- [ ] **Step 4: Implement role command construction without shell strings**

Build subprocess argument lists, never `shell=True`. Map roles as follows: `control` to the merged control Compose project, `ai_5080` to `compose.ai_5080.yaml`, `omx_01` and `omx_02` to `compose.roles/omx.yaml`, Pinky roles to `trihouse_pinky.launch.py`, and `simulation` to the existing simulation bringup. Pass resolved environment through `subprocess.run(env=...)`.

- [ ] **Step 5: Make `up` run doctor first**

If doctor returns non-zero, print no start command and return the same non-zero status. `status`, `logs`, and `down` may run without a healthy device check so operators can diagnose and stop a partially configured role.

- [ ] **Step 6: Translate the resolved Pinky profile to existing launch arguments**

`scripts/bringup` selects the namespace entry once and maps it to the existing `robot_id`, `namespace`, map, Nav2, narrow-zone, marker-dock, vision, host and port launch arguments. Explicit command-line overrides remain allowed only for tests and diagnostics. Existing node-level ROS parameters remain in their parameter YAML files, and the launch file does not parse the system profile a second time.

- [ ] **Step 7: Route old role scripts through the shared loader**

Remove duplicated `ROS_DOMAIN_ID`, OMX identity pairs and packing defaults from production paths in `control_stack`, `omx_stack` and `p0_simulation_bringup.sh`. Retain compatibility flags but resolve their defaults from `simulation.yaml` or `physical_01.yaml`.

- [ ] **Step 8: Run CLI and launch tests**

Run: `python -m pytest control_tower/tests/test_system_bringup.py control_tower/tests/test_job_runner_node.py -q`

Expected: PASS and no subprocess starts a real robot because tests inspect command lists only.

- [ ] **Step 9: Commit the unified entrypoint**

```bash
git add scripts/bringup scripts/control_stack scripts/omx_stack control_tower/bringup/p0_simulation_bringup.sh control_tower/tests/test_system_bringup.py
git commit -m "feat(bringup): launch roles from system profiles"
```

### Task 4: JobRunner의 하드코딩된 도크와 충전소 제거

**Files:**
- Modify: `control_tower/task_manager/job_runner.py`
- Modify: `control_tower/task_manager/job_runner_node.py`
- Modify: `control_tower/tests/test_job_runner.py`
- Modify: `control_tower/tests/test_job_runner_node.py`
- Modify: `trihouse_rmf_bridge/launch/control_system_rmf.launch.py`
- Modify: `trihouse_rmf_bridge/launch/two_pinky_order_demo.launch.py`

**Interfaces:**
- Consumes: `SystemProfile.packing_worker_by_dock` and `SystemProfile.charger_by_mobile`.
- Changes: `JobRunner(..., packing_dock_codes: tuple[str, ...], charger_by_mobile: Mapping[str, str])`; both become required keyword arguments.
- Changes CLI: replace repeated production `--packing-dock` defaults with required `--profile`; retain `--packing-dock` only as an explicit diagnostic override.

- [ ] **Step 1: Write failing injection tests**

```python
def test_assignment_uses_injected_docks_and_chargers(gateway):
    runner = JobRunner(
        gateway,
        packing_dock_codes=("PACKING-01-DOCK-02",),
        charger_by_mobile={"PK_01": "TRIHOUSE-TEST-01-CHG-01"},
    )
    runner.run_once()
    _, request = gateway.assignments[0]
    assert request.packing_dock_code == "PACKING-01-DOCK-02"
    assert request.charger_code == "TRIHOUSE-TEST-01-CHG-01"


def test_unknown_mobile_has_no_guessed_charger(gateway):
    runner = JobRunner(
        gateway,
        packing_dock_codes=("PACKING-01-DOCK-01",),
        charger_by_mobile={},
    )
    report = runner.run_once()
    assert report.assigned == ()
```

- [ ] **Step 2: Run tests and confirm the old constants cause failure**

Run: `python -m pytest control_tower/tests/test_job_runner.py control_tower/tests/test_job_runner_node.py -q`

Expected: FAIL because `JobRunner` does not accept `charger_by_mobile` and still uses `CHARGER_BY_MOBILE`.

- [ ] **Step 3: Inject all static assignment policy**

Delete production use of `DEFAULT_PACKING_DOCK_CODES` and `CHARGER_BY_MOBILE`. Store immutable copies of the injected mappings in `JobRunner`; `_select_assignment` returns no assignment if the selected mobile has no configured charger.

- [ ] **Step 4: Load JobRunner policy from the selected profile**

`job_runner_node.main` loads `--profile`, validates the `control` or `simulation` role, passes `tuple(profile.packing_worker_by_dock)` as dock codes and `profile.charger_by_mobile` to `JobRunner`. Launch files pass the same profile path instead of repeating dock arguments.

- [ ] **Step 5: Run JobRunner and launch contract tests**

Run: `python -m pytest control_tower/tests/test_job_runner.py control_tower/tests/test_job_runner_node.py trihouse_rmf_bridge/test -q`

Expected: PASS.

- [ ] **Step 6: Commit policy injection**

```bash
git add control_tower/task_manager/job_runner.py control_tower/task_manager/job_runner_node.py control_tower/tests/test_job_runner.py control_tower/tests/test_job_runner_node.py trihouse_rmf_bridge/launch/control_system_rmf.launch.py trihouse_rmf_bridge/launch/two_pinky_order_demo.launch.py
git commit -m "refactor(tasks): load assignment policy from profile"
```

### Task 5: Gateway의 포장 작업자 영속화와 검증

**Files:**
- Modify: `fms_gateway/app/config.py`
- Modify: `fms_gateway/app/main.py`
- Modify: `fms_gateway/app/models.py`
- Modify: `fms_gateway/app/repositories.py`
- Modify: `fms_gateway/Dockerfile`
- Modify: `compose.control.yaml`
- Modify: `fms_gateway/tests/unit/test_assignment_repository_parity.py`
- Modify: `fms_gateway/tests/unit/test_worker_completion_api.py`
- Modify: `fms_gateway/tests/integration/test_worker_completion_repository.py`

**Interfaces:**
- Produces setting: `FMS_SYSTEM_PROFILE=/app/config/profiles/physical_01.yaml`.
- Changes repository construction: `MySqlFmsRepository(database, *, packing_worker_by_dock: Mapping[str, str])` and `InMemoryFmsRepository(..., packing_worker_by_dock: Mapping[str, str])`.
- Changes Job assignment response/context: adds required `packing_worker_id: str` derived by Gateway, not accepted from the client request.
- Adds completion conflict code: `PACKING_WORKER_MISMATCH`.

- [ ] **Step 1: Write failing assignment derivation parity tests**

```python
@pytest.mark.parametrize("repository_factory", REPOSITORY_FACTORIES)
def test_assignment_derives_worker_from_packing_dock(repository_factory):
    repository = repository_factory(
        packing_worker_by_dock={"PACKING-01-DOCK-01": "W-FIELD-01"}
    )
    assigned = repository.assign_job_resources(job_id, ASSIGNMENT)
    assert assigned["packing_worker_id"] == "W-FIELD-01"
    assert repository.get_job(job_id)["context"]["assignment"]["packing_worker_id"] == "W-FIELD-01"
```

- [ ] **Step 2: Write failing completion authorization tests**

```python
def test_worker_completion_rejects_worker_from_other_dock(seeded_schema):
    job_id = _packing_ready_job(worker_id="W-FIELD-01")
    with pytest.raises(WorkerCompletionConflict) as caught:
        _repository().complete_worker_packing(
            job_id,
            {"worker_id": "W-FIELD-02", "acknowledged_manual_item_ids": []},
            "wrong-dock-worker",
        )
    assert caught.value.code == "PACKING_WORKER_MISMATCH"
```

- [ ] **Step 3: Run focused Gateway tests and confirm failure**

Run: `python -m pytest fms_gateway/tests/unit/test_assignment_repository_parity.py fms_gateway/tests/unit/test_worker_completion_api.py fms_gateway/tests/integration/test_worker_completion_repository.py -q`

Expected: FAIL because assignment does not contain `packing_worker_id` and completion accepts any active worker.

- [ ] **Step 4: Load the profile once at Gateway startup**

Add a settings field for the profile path. `_default_repository` loads and validates it, then injects an immutable dock-worker mapping. `create_app(repository=...)` tests continue to inject their repository and do not read host files.

- [ ] **Step 5: Derive and persist `packing_worker_id` atomically**

Before MySQL or InMemory assignment is persisted, look up `assignment["packing_dock_code"]`. Raise `ResourceAssignmentConflict("PACKING_WORKER_MAPPING_REQUIRED")` if absent. Add the derived field to the context, response and `job.assignment.persisted` event payload in the same transaction.

- [ ] **Step 6: Enforce the worker-dock invariant at completion**

Before inventory mutation, require `canonical_request["worker_id"] == assignment["packing_worker_id"]`. Preserve the existing active-worker, packing-readiness, manual acknowledgement and idempotency checks.

- [ ] **Step 7: Mount the profile read-only in the Gateway container**

Copy `trihouse_config` into the image, mount `./config/profiles:/app/config/profiles:ro`, and set `FMS_SYSTEM_PROFILE=/app/config/profiles/physical_01.yaml` through resolved Compose environment. Do not copy `.env` into the image.

- [ ] **Step 8: Run Gateway suites**

Run: `python -m pytest fms_gateway/tests/unit -q`

Run: `python -m pytest fms_gateway/tests/integration/test_worker_completion_repository.py fms_gateway/tests/integration/test_job_cancellation_repository.py -q`

Expected: PASS.

- [ ] **Step 9: Validate Compose without starting containers**

Run: `docker compose --env-file .env.example -f compose.yaml -f compose.control.yaml config --quiet`

Expected: exit code 0. If placeholder secrets are rejected by Compose substitution, use a temporary environment only for parsing and do not write credentials to the repository.

- [ ] **Step 10: Commit Gateway policy enforcement**

```bash
git add fms_gateway/app/config.py fms_gateway/app/main.py fms_gateway/app/models.py fms_gateway/app/repositories.py fms_gateway/Dockerfile compose.control.yaml fms_gateway/tests/unit/test_assignment_repository_parity.py fms_gateway/tests/unit/test_worker_completion_api.py fms_gateway/tests/integration/test_worker_completion_repository.py
git commit -m "feat(packing): bind workers to assigned docks"
```

### Task 6: 관제 UI의 준비 기반 완료 팝업

**Files:**
- Modify: `control_ui/rmf_control_ui/lib/trihouse/presentation/task_management_page.dart`
- Modify: `control_ui/rmf_control_ui/lib/trihouse/features/orders/job_detail_page.dart`
- Modify: `control_ui/rmf_control_ui/test/worker_completion_test.dart`
- Modify: `control_ui/rmf_control_ui/test/job_step_timeline_test.dart`

**Interfaces:**
- Removes: `JobDetailPage.workerId` constructor input.
- Consumes: `job.context.assignment.packing_worker_id` and `revision`.
- Produces pure predicate: `bool isWorkerCompletionReady(JobDetailDto job)`.
- Produces idempotency key: `control-ui-worker-completion-{jobId}-revision-{revision}`.

- [ ] **Step 1: Write failing readiness predicate tests**

```dart
test('completion is ready only after packing handover succeeds', () {
  expect(isWorkerCompletionReady(jobWith(
    handoverState: 'succeeded',
    waitState: 'running',
    packingWorkerId: 'W-FIELD-01',
  )), isTrue);
  expect(isWorkerCompletionReady(jobWith(
    handoverState: 'running',
    waitState: 'pending',
    packingWorkerId: 'W-FIELD-01',
  )), isFalse);
});
```

- [ ] **Step 2: Write failing popup and worker-identity widget tests**

```dart
testWidgets('packing-ready transition opens one completion dialog', (tester) async {
  final api = CompletionApi.sequence([notReadyJob(), readyJob()]);
  await tester.pumpWidget(MaterialApp(home: JobDetailPage(api: api, jobId: 42)));
  await tester.pumpAndSettle();
  api.emitPackingReady();
  await tester.pumpAndSettle();
  expect(find.byKey(const Key('worker-completion-dialog')), findsOneWidget);
  expect(find.text('W-FIELD-01'), findsOneWidget);
});


testWidgets('completion request uses assigned packing worker', (tester) async {
  // Acknowledge the manual item and confirm the dialog.
  expect(api.calls.single.request.workerId, 'W-FIELD-01');
  expect(api.calls.single.key, 'control-ui-worker-completion-42-revision-1');
});
```

- [ ] **Step 3: Run focused Flutter tests and confirm failure**

Run: `cd control_ui/rmf_control_ui && flutter test test/worker_completion_test.dart test/job_step_timeline_test.dart`

Expected: FAIL because `JobDetailPage` still requires `workerId` and has no readiness popup.

- [ ] **Step 4: Derive worker identity only from Job assignment**

Remove `_job!.requestedBy ?? 'W-OP-01'` from `TaskManagementPage`. Remove `workerId` from `JobDetailPage`; read and type-check `packing_worker_id`. If it is missing, disable completion and show `포장대 작업자 미설정` rather than substituting another worker.

- [ ] **Step 5: Implement one-popup-per-readiness-transition behavior**

After `_load` updates the Job, schedule the dialog with `WidgetsBinding.instance.addPostFrameCallback` only when the predicate changes from false to true and the dialog was not shown for the current `(job_id, assignment_revision)`. Closing the dialog leaves a visible `승인 대기` button in the detail page; it does not call the API.

- [ ] **Step 6: Move existing acknowledgement controls into reusable dialog content**

The popup shows Job code, dock code, Pinky ID, read-only worker ID, item list, manual acknowledgement controls, optional note and `포장 완료 승인`. The existing page button reopens the same dialog after dismissal.

- [ ] **Step 7: Make idempotency stable across retries**

Build the key from Job ID and assignment revision, cache it for that pair, and reuse it when an HTTP retry occurs. On success, mark completed and close the dialog. On conflict, leave the dialog open and show the Gateway error.

- [ ] **Step 8: Run the full control UI test suite**

Run: `cd control_ui/rmf_control_ui && flutter test`

Expected: PASS and no test fixture contains `W-OP-01` for worker completion.

- [ ] **Step 9: Commit the popup flow**

```bash
git add control_ui/rmf_control_ui/lib/trihouse/presentation/task_management_page.dart control_ui/rmf_control_ui/lib/trihouse/features/orders/job_detail_page.dart control_ui/rmf_control_ui/test/worker_completion_test.dart control_ui/rmf_control_ui/test/job_step_timeline_test.dart
git commit -m "feat(ui): prompt assigned packing worker"
```

### Task 7: 운영 문서와 전체 정적 검증

**Files:**
- Modify: `docs/deployment/environment_overview.md`
- Modify: `docs/runbooks/p0-hardware-quick-run.md`
- Modify: `docs/runbooks/p0-simulation-quick-run.md`
- Modify: `docs/README.md`
- Create: `scripts/hardware/inspect_omx_devices.sh`

**Interfaces:**
- Consumes: final `scripts/bringup` CLI and profile field names.
- Produces: read-only hardware discovery commands that fill currently blank OMX fields.

- [ ] **Step 1: Add a shell syntax test target before writing the hardware helper**

Document and use this exact check:

```bash
bash -n scripts/hardware/inspect_omx_devices.sh
```

Expected before creation: FAIL because the file is missing.

- [ ] **Step 2: Implement read-only OMX discovery**

The script prints `ls -l /dev/serial/by-id`, `v4l2-ctl --list-devices`, existing calibration directories and model cache directories. It must not create symlinks, download models, change permissions or write profile values automatically.

- [ ] **Step 3: Replace manual long commands in runbooks**

Use:

```bash
./scripts/bringup --profile config/profiles/physical_01.yaml --role control doctor
./scripts/bringup --profile config/profiles/physical_01.yaml --role control up
```

Add corresponding commands for both Pinky roles, both OMX roles, `ai_5080`, and simulation. Explain that blank OMX fields are intentionally awaiting measured values.

- [ ] **Step 4: Remove obsolete worker completion examples**

Replace any `W-OP-01` completion curl example with the normal UI popup flow. Keep a diagnostic curl only if it uses `packing_worker_id` read from the Job response instead of a hardcoded worker.

- [ ] **Step 5: Run static checks and focused suites**

Run: `bash -n scripts/hardware/inspect_omx_devices.sh control_tower/bringup/p0_simulation_bringup.sh`

Run: `python -m pytest control_tower/tests/test_system_profile.py control_tower/tests/test_system_profile_files.py control_tower/tests/test_system_bringup.py control_tower/tests/test_job_runner.py control_tower/tests/test_job_runner_node.py -q`

Run: `python -m pytest fms_gateway/tests/unit -q`

Run: `cd control_ui/rmf_control_ui && flutter test`

Expected: all PASS.

- [ ] **Step 6: Validate both Compose profiles without starting them**

Run: `docker compose --env-file .env.example -f compose.yaml -f compose.control.yaml config --quiet`

Run: `docker compose --env-file .env.example -f compose.ai_5080.yaml config --quiet`

Run: `docker compose --env-file .env.example -f compose.roles/omx.yaml config --quiet`

Expected: all exit code 0. These checks parse configuration only and do not start containers.

- [ ] **Step 7: Run the no-fabricated-values audit**

Run:

```bash
grep -RInE '192\.0\.2\.|W-OP-01|W-1|station-1|change_me' \
  config/profiles scripts/bringup control_tower/task_manager/job_runner.py \
  control_ui/rmf_control_ui/lib/trihouse
```

Expected: no output. Empty unknown hardware fields remain visible in `physical_01.yaml` and doctor reports them only for the applicable OMX role.

- [ ] **Step 8: Commit operational documentation and helper**

```bash
git add docs/deployment/environment_overview.md docs/runbooks/p0-hardware-quick-run.md docs/runbooks/p0-simulation-quick-run.md docs/README.md scripts/hardware/inspect_omx_devices.sh
git commit -m "docs: run Trihouse from system profiles"
```

### Task 8: Final repository verification

**Files:**
- Modify only files that fail the checks above and are already in this plan.

**Interfaces:**
- Consumes all previous task outputs.
- Produces evidence for software readiness; it does not claim physical motion readiness.

- [ ] **Step 1: Confirm no unrelated changes are staged**

Run: `git status --short`

Expected: pre-existing user changes may remain unstaged; the index is empty after each task commit.

- [ ] **Step 2: Run all non-hardware Python tests affected by shared imports**

Run: `python -m pytest control_tower/tests fms_gateway/tests/unit -q`

Expected: PASS.

- [ ] **Step 3: Run outbound integration tests**

Run: `python -m pytest fms_gateway/tests/integration/test_worker_completion_repository.py fms_gateway/tests/integration/test_job_cancellation_repository.py fms_gateway/tests/integration/test_load_attempt_repository.py -q`

Expected: PASS when the test database fixture is available; otherwise record the exact environment skip separately and do not call it a pass.

- [ ] **Step 4: Run all Flutter tests**

Run: `cd control_ui/rmf_control_ui && flutter test`

Expected: PASS.

- [ ] **Step 5: Run profile doctors without starting services**

Run: `./scripts/bringup --profile config/profiles/simulation.yaml --role simulation doctor`

Expected: exit code 0.

Run: `./scripts/bringup --profile config/profiles/physical_01.yaml --role omx_01 doctor`

Expected until the user fills measured OMX values: non-zero with explicit empty field paths. This is a correct blocked result, not a test failure.

- [ ] **Step 6: Record the final commit list**

Run: `git log --oneline 257e5f41..HEAD`

Expected: only the planned profile, bringup, assignment, UI and documentation commits plus any pre-existing concurrent commits. Do not stage or rewrite unrelated worktree changes.
