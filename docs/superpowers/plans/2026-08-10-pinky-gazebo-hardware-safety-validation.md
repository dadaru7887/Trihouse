# Pinky Gazebo·실기 안전 주행 검증 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 동일한 Pinky ROS 업무·안전 노드를 사용해 Gazebo와 실기에서 기본 경로 주행, 상태 회신, 비상 정지와 복귀를 검증하고, 마지막 선택 작업으로 ArUco marker 기반 협로 입구 진입을 검증한다.

**Architecture:** `control_tower → onboard gateway → ExecuteTransport → Nav2 → /cmd_vel_nav → Safety Supervisor → /cmd_vel`을 단일 수직 흐름으로 사용한다. Gazebo와 실기의 차이는 센서·odometry·motor adapter뿐이며, 상태와 명령 계약은 동일하게 유지한다. `control_system`은 기존 waypoint/lane·경로·상태 화면을 읽기 전용 기준으로 사용하고 원본 코드는 수정하지 않는다.

**Tech Stack:** ROS 2 Jazzy, Python 3.12, rclpy, Nav2, Gazebo, rosbag2, ROSIDL, unittest/pytest

## Global Constraints

- 내일 범위는 SR_03, SR_07·08·09·41, SR_23·24·25·27, SR_45·48·49, SR_54·55·56·57과 SR_20의 Pinky Safety 입력 연결로 제한한다.
- Vision 모델 정확도, SR_52, OMX/MoveIt 실물 동작과 물리 충전 접촉은 제외한다.
- `pinky_pro/**`와 `control_system/**`는 읽기·실행만 허용하며 수정하지 않는다.
- Control Tower가 업무·비상 결정의 단일 권한자이고 Safety Supervisor만 운영 `/cmd_vel`을 발행한다.
- 실기 검증은 저속 상한, 물리 비상 정지 담당자, 충분한 정지 공간을 확보한 뒤 시작한다.
- ArUco 협로 진입은 모든 필수 Task가 통과한 경우에만 수행하는 마지막 stretch task다.
- 사용자가 소유한 미추적 파일과 관련 없는 변경은 커밋하지 않는다.

---

### Task 1: RobotStatus ROS 타입 결함 수정

**Files:**
- Modify: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/status_node.py:40-45`
- Create: `trihouse_pinky/trihouse_pinky_fleet/test/test_status_node_ros.py`
- Modify: `trihouse_pinky/trihouse_pinky_fleet/setup.py`

**Interfaces:**
- Consumes: `BatteryPolicyState` from `/trihouse/battery/policy_state`
- Produces: valid `RobotStatus.battery_policy: trihouse_interfaces/msg/BatteryPolicyState`

- [ ] **Step 1: ROS 메시지 타입을 검증하는 실패 테스트 작성**

```python
def test_robot_status_uses_subscribed_battery_policy(status_node):
    policy = BatteryPolicyState()
    policy.state = BatteryPolicyState.STATE_RETURN_REQUIRED
    status_node.battery_policy = policy
    message = status_node._build_message()
    assert message.battery_policy.state == BatteryPolicyState.STATE_RETURN_REQUIRED
```

테스트를 위해 `_publish()`의 메시지 조립을 `_build_message() -> RobotStatus`로 분리하되 publish 동작은 유지한다.

- [ ] **Step 2: 테스트가 기존 float 대입 때문에 실패하는지 확인**

Run:

```bash
source /opt/ros/jazzy/setup.bash
pytest -q trihouse_pinky/trihouse_pinky_fleet/test/test_status_node_ros.py
```

Expected: `battery_policy`에 `float`을 대입할 수 없거나 예상 state가 일치하지 않아 FAIL.

- [ ] **Step 3: 최소 수정 구현**

```python
def _build_message(self) -> RobotStatus:
    # 기존 RobotStatus 필드를 그대로 조립한다.
    message.battery_percentage = self.battery
    message.battery_policy = self.battery_policy
    return message

def _publish(self) -> None:
    self.publisher.publish(self._build_message())
```

- [ ] **Step 4: 노드 테스트와 정책 회귀 테스트 실행**

```bash
source /opt/ros/jazzy/setup.bash
pytest -q trihouse_pinky/trihouse_pinky_fleet/test/test_status_node_ros.py
PYTHONPATH='trihouse_pinky/trihouse_pinky_fleet' python3 -m unittest -q trihouse_pinky.test.test_pinky_sr_policies
```

Expected: 모두 PASS.

- [ ] **Step 5: 커밋**

```bash
git add trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/status_node.py trihouse_pinky/trihouse_pinky_fleet/test/test_status_node_ros.py trihouse_pinky/trihouse_pinky_fleet/setup.py
git commit -m "fix: publish valid Pinky battery policy status"
```

### Task 2: 사람 감지를 최종 Safety gate에 연결

**Files:**
- Modify: `trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/safety_supervisor_node.py:79-83,109-120`
- Create: `trihouse_pinky/trihouse_pinky_safety/test/test_safety_supervisor_ros.py`

**Interfaces:**
- Consumes: `/trihouse/vision/person_detection/base` with confidence, pose and TTL
- Produces: `SafetyInputs.person_detected`, bounded `/cmd_vel`, non-canceled Nav2 goal

- [ ] **Step 1: TTL 내 사람 감지 wiring 실패 테스트 작성**

```python
def test_fresh_person_detection_reaches_safety_policy(supervisor, monkeypatch):
    detected = PersonDetection()
    detected.confidence = 0.9
    detected.pose.pose.position.x = 0.6
    detected.ttl_ms = 500
    supervisor._on_person(detected)
    decision = supervisor._evaluate(MotionCommand(0.2, 0.0))
    assert decision.reason == "protective_zone"
    assert decision.command.linear_x <= supervisor.config.slow_linear_speed_mps
```

- [ ] **Step 2: 기존 `person_detected=False` 때문에 실패하는지 확인**

```bash
source /opt/ros/jazzy/setup.bash
pytest -q trihouse_pinky/trihouse_pinky_safety/test/test_safety_supervisor_ros.py
```

Expected: `reason`이 `protective_zone`이 아니어서 FAIL.

- [ ] **Step 3: 평가 함수 분리와 wiring 수정**

```python
def _evaluate(self, desired: MotionCommand):
    person_detected = self.person_detected and monotonic() <= self.person_until
    inputs = SafetyInputs(
        sensor_fresh=scan_fresh and (range_fresh or not self.require_ultrasonic),
        front_distance_m=self._front_distance(),
        person_detected=person_detected,
        person_distance_m=self.person_distance if person_detected else None,
        keep_out=self._in_keep_out_zone(),
        emergency_latched=self.emergency_latched,
        control_link_fresh=self.control_link_online,
    )
    return apply_safety_gate(desired, inputs, self.config)
```

- [ ] **Step 4: TTL 만료·거리 센서 우선순위 회귀 테스트 추가**

```python
def test_expired_person_does_not_remain_latched(supervisor):
    supervisor.person_detected = True
    supervisor.person_until = 0.0
    decision = supervisor._evaluate(MotionCommand(0.2, 0.0))
    assert decision.reason != "protective_zone"

def test_front_stop_overrides_person_slow():
    decision = apply_safety_gate(
        MotionCommand(0.2, 0.0),
        SafetyInputs(front_distance_m=0.2, person_detected=True),
    )
    assert decision.reason == "front_stop"
    assert decision.command.linear_x == 0.0

def test_person_protection_keeps_nav_goal():
    decision = apply_safety_gate(
        MotionCommand(0.2, 0.0), SafetyInputs(person_detected=True)
    )
    assert decision.goal_may_continue is True
```

정책 결정의 `goal_may_continue`는 사람/거리 보호 정지에서 `True`여야 한다.

- [ ] **Step 5: 관련 테스트 실행 및 커밋**

```bash
source /opt/ros/jazzy/setup.bash
pytest -q trihouse_pinky/trihouse_pinky_safety/test/test_safety_supervisor_ros.py
PYTHONPATH='trihouse_pinky/trihouse_pinky_safety' python3 -m unittest -q trihouse_pinky.test.test_pinky_sr_policies
git add trihouse_pinky/trihouse_pinky_safety
git commit -m "fix: connect person observations to Pinky safety gate"
```

### Task 3: 상태 Topic QoS 계약 적용

**Files:**
- Create: `trihouse_pinky/trihouse_pinky_bringup/trihouse_pinky_bringup/qos.py`
- Modify: `trihouse_pinky/trihouse_pinky_bringup/trihouse_pinky_bringup/readiness_node.py`
- Modify: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py`
- Modify: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/gateway_node.py`
- Modify: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/status_node.py`
- Modify: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/recovery_health_node.py`
- Modify: `trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/safety_supervisor_node.py`
- Create: `trihouse_pinky/test/test_state_qos_contract.py`

**Interfaces:**
- Produces: shared `state_qos()` returning RELIABLE + TRANSIENT_LOCAL + KEEP_LAST depth 1
- Consumes: the same profile at both publisher and subscriber ends of state Topics

- [ ] **Step 1: QoS profile 실패 테스트 작성**

```python
def test_state_qos_is_transient_reliable_depth_one():
    qos = state_qos()
    assert qos.reliability == ReliabilityPolicy.RELIABLE
    assert qos.durability == DurabilityPolicy.TRANSIENT_LOCAL
    assert qos.history == HistoryPolicy.KEEP_LAST
    assert qos.depth == 1
```

- [ ] **Step 2: helper가 없어 실패하는지 확인**

```bash
source /opt/ros/jazzy/setup.bash
pytest -q trihouse_pinky/test/test_state_qos_contract.py
```

Expected: import error로 FAIL.

- [ ] **Step 3: 공용 profile 구현**

```python
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

def state_qos() -> QoSProfile:
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=1,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )
```

- [ ] **Step 4: 카탈로그의 상태 Topic 양 끝에 profile 적용**

대상은 battery policy, FMS connection, indicator, readiness, health, safety, keep-out, cargo다.
`RobotStatus`, `NavigationState`, `TaskEvent`, detection stream은 문서의 기존 depth와 volatile 성격을 유지한다.

- [ ] **Step 5: 늦게 시작한 subscriber launch test 실행**

```bash
source /opt/ros/jazzy/setup.bash
colcon test --packages-select trihouse_pinky_bringup trihouse_pinky_fleet trihouse_pinky_safety --event-handlers console_direct+
colcon test-result --verbose
```

Expected: publisher가 먼저 한 번 발행된 뒤 시작한 subscriber가 마지막 상태를 2초 안에 수신.

- [ ] **Step 6: 커밋**

```bash
git add trihouse_pinky/trihouse_pinky_bringup trihouse_pinky/trihouse_pinky_fleet trihouse_pinky/trihouse_pinky_safety trihouse_pinky/test/test_state_qos_contract.py
git commit -m "fix: apply durable QoS to Pinky state topics"
```

### Task 4: ROS build와 정적 회귀 게이트 확정

**Files:**
- Modify: `docs/validation/pinky_sr_manual_validation.md`
- Create: `docs/validation/runs/2026-08-11-pinky-safety-validation.md`

**Interfaces:**
- Consumes: Tasks 1-3 changes
- Produces: reproducible build/test record with commit SHA and environment

- [ ] **Step 1: 보호 패키지를 제외하지 않고 선택 build 실행**

```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select trihouse_interfaces trihouse_pinky_io trihouse_pinky_safety trihouse_pinky_fleet trihouse_pinky_bringup trihouse_omx_adapter
source install/setup.bash
```

Expected: 선택 패키지 build 성공. 실패 시 최초 package와 stderr를 run 문서에 기록하고 다음 Task로 진행하지 않는다.

- [ ] **Step 2: 정적 정책과 ROS package test 실행**

```bash
PYTHONPATH='trihouse_pinky/trihouse_pinky_fleet:trihouse_pinky/trihouse_pinky_safety:trihouse_pinky/trihouse_pinky_io:trihouse_pinky/trihouse_pinky_bringup' python3 -m unittest -q trihouse_pinky.test.test_pinky_sr_policies trihouse_pinky.test.test_eta_policy trihouse_pinky.test.test_integrated_bringup_contract
colcon test --packages-select trihouse_interfaces trihouse_pinky_safety trihouse_pinky_fleet trihouse_pinky_bringup --event-handlers console_direct+
colcon test-result --verbose
```

- [ ] **Step 3: 결과 기록과 문서 명령 동기화**

run 문서에 OS, ROS distro, commit SHA, 통과 수, 실패/차단 이유를 적는다. 정적 성공을 Gazebo 또는 실기 성공으로 표기하지 않는다.

- [ ] **Step 4: 커밋**

```bash
git add docs/validation/pinky_sr_manual_validation.md docs/validation/runs/2026-08-11-pinky-safety-validation.md
git commit -m "docs: record Pinky ROS safety verification gate"
```

### Task 5: Gazebo 기본 경로 수직 흐름 검증

**Files:**
- Modify: `trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_gazebo_demo.launch.py`
- Create: `trihouse_pinky/trihouse_pinky_bringup/test/test_gazebo_vertical_slice.py`
- Modify: `docs/validation/runs/2026-08-11-pinky-safety-validation.md`

**Interfaces:**
- Consumes: one `ExecuteTransport.Goal` with `dropoff_pose.header.frame_id="map"`
- Produces: Nav2 result, `NavigationState`, `TaskEvent`, `RobotStatus`

- [ ] **Step 1: launch 인자와 topic contract test 작성**

테스트는 Gazebo launch가 `robot_id`, `map_revision`, `map`, `control_host`, `use_sim_time`을 하위 launch에 전달하고 Nav2 출력이 `/cmd_vel_nav`를 경유하는지 검증한다.

- [ ] **Step 2: headless Gazebo 실행**

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=51
ros2 launch trihouse_pinky_bringup trihouse_gazebo_demo.launch.py use_sim_time:=true map:=/home/syw/Trihouse/pinky_pro/pinky_navigation/map/my_map.yaml
```

- [ ] **Step 3: graph와 단일 속도 소유권 확인**

```bash
ros2 node list
ros2 topic info /cmd_vel -v
ros2 topic info /cmd_vel_nav -v
ros2 action list -t
```

Expected: `/cmd_vel` publisher는 `safety_supervisor` 하나, `/navigate_to_pose`와 `/trihouse/transport/execute` action이 준비됨.

- [ ] **Step 4: 한 pose 목표 전송과 상태 관찰**

안전한 빈 공간의 실제 map 좌표를 선택해 `ExecuteTransport` goal의 `dropoff_pose` 한 점 `(x,y,yaw)`을 보낸다. 임의 좌표를 하드코딩하지 않고 RViz 또는 배포 map waypoint에서 선택한다.

```bash
ros2 topic hz /trihouse/status
ros2 topic echo /trihouse/navigation/state
ros2 topic echo /trihouse/task/events
```

Expected: ACCEPTED → NAVIGATING → ARRIVED/WAITING_HANDOVER, status 약 1 Hz.

- [ ] **Step 5: rosbag 기록**

```bash
ros2 bag record -o validation/runs/pinky_gazebo_nominal /scan /odom /cmd_vel_nav /cmd_vel /trihouse/readiness /trihouse/safety/state /trihouse/navigation/state /trihouse/status /trihouse/task/events
```

- [ ] **Step 6: 테스트·기록 커밋**

```bash
git add trihouse_pinky/trihouse_pinky_bringup docs/validation/runs/2026-08-11-pinky-safety-validation.md
git commit -m "test: verify Pinky Gazebo transport vertical slice"
```

### Task 6: Gazebo 오류·비상 시나리오 검증

**Files:**
- Create: `trihouse_pinky/trihouse_pinky_bringup/trihouse_pinky_bringup/fault_injector_node.py`
- Modify: `trihouse_pinky/trihouse_pinky_bringup/setup.py`
- Create: `trihouse_pinky/trihouse_pinky_bringup/test/test_fault_injector.py`
- Modify: `docs/validation/runs/2026-08-11-pinky-safety-validation.md`

**Interfaces:**
- Produces: explicit test-only person, proximity, connection, emergency and keep-out inputs
- Consumes: SafetyState, `/cmd_vel`, RobotStatus and TaskEvent observations

- [ ] **Step 1: test-only fault injector 명령 검증 테스트 작성**

```python
def test_fault_injector_rejects_unknown_scenario():
    with pytest.raises(ValueError, match="unknown fault scenario"):
        build_fault("wheel_fire")

def test_person_scenario_has_finite_ttl_and_base_link_frame():
    message = build_fault("person")
    assert message.header.frame_id == "base_link"
    assert 0 < message.ttl_ms <= 1000

def test_keep_out_scenario_requires_three_or_more_points():
    with pytest.raises(ValueError, match="at least three points"):
        build_keep_out("zone-1", [(0.0, 0.0), (1.0, 0.0)])
```

- [ ] **Step 2: 최소 injector 구현**

노드는 `scenario` parameter가 `person`, `front_stop`, `connection_loss`, `emergency`, `keep_out` 중 하나일 때만 한정된 test input을 발행한다. 운영 launch에는 포함하지 않는다.

- [ ] **Step 3: 각 시나리오를 하나씩 실행**

각 시나리오마다 별도 rosbag을 사용하고 다음을 판정한다.

```text
person          → protective_zone, bounded/zero velocity, Nav2 goal 유지
front_stop      → front_stop, /cmd_vel=0
connection_loss → control_link_lost, /cmd_vel=0
emergency       → latched emergency, 승인 전 지속
keep_out        → polygon 내부 정지, 유효기간/clear 후 해제
```

- [ ] **Step 4: ClearEmergency 이후 자동 재개 방지 확인**

관리자 ID가 없는 요청은 거절하고, 승인된 clear 뒤에는 기존 목적지를 자동 재개하지 않고 return mode 명령을 기다리는지 확인한다.

- [ ] **Step 5: 커밋**

```bash
git add trihouse_pinky/trihouse_pinky_bringup docs/validation/runs/2026-08-11-pinky-safety-validation.md
git commit -m "test: add reproducible Pinky Gazebo fault scenarios"
```

### Task 7: Control Tower 상태·결정 폐루프 검증

**Files:**
- Create: `control_tower/tests/test_pinky_emergency_vertical_slice.py`
- Modify: `control_tower/task_manager/emergency_workflow.py`
- Modify: `control_tower/task_manager/lifecycle.py`
- Modify: `control_tower/fleet_manager/battery_policy.py`
- Modify: `docs/validation/runs/2026-08-11-pinky-safety-validation.md`

**Interfaces:**
- Consumes: RobotStatus/TaskEvent-equivalent Gateway payload with message ID
- Produces: hold, keep-out, clear-emergency and return-to-wait/charge decisions

- [ ] **Step 1: 폐루프 실패 테스트 작성**

테스트는 emergency 상태를 받은 뒤 새 작업 거부, 관리자 승인 전 clear 거부, 승인 뒤 return command 생성, health OK 전 재투입 거부를 한 흐름으로 고정한다.

- [ ] **Step 2: 테스트가 빠진 연결 지점에서 실패하는지 확인**

```bash
python3 -m unittest -v control_tower.tests.test_pinky_emergency_vertical_slice
```

- [ ] **Step 3: 필요한 최소 orchestration만 연결**

기존 `emergency_workflow`, `lifecycle`, `battery_policy` API를 재사용하고 별도 제2 상태 머신을 만들지 않는다. 같은 `message_id` 재수신은 상태를 두 번 진행시키지 않는다.

- [ ] **Step 4: Control Tower 관련 전체 회귀 테스트**

```bash
python3 -m unittest -q control_tower.tests.test_pinky_emergency_vertical_slice control_tower.tests.test_emergency_workflow control_tower.tests.test_task_lifecycle control_tower.tests.test_authorization control_tower.tests.test_battery_policy control_tower.tests.test_dispatch_workflow
```

- [ ] **Step 5: 실제 Gateway log와 message ID 대조 및 커밋**

```bash
git add control_tower docs/validation/runs/2026-08-11-pinky-safety-validation.md
git commit -m "test: close Pinky emergency decision loop"
```

### Task 8: 실기 전 안전 점검과 저속 기본 주행

**Files:**
- Create: `docs/validation/pinky_hardware_preflight.md`
- Modify: `docs/validation/runs/2026-08-11-pinky-safety-validation.md`

**Interfaces:**
- Consumes: real Pinky `/scan`, `/odom`, proximity, battery and motor driver
- Produces: same ROS graph and status contracts proven in Gazebo

- [ ] **Step 1: 물리 안전 preflight 작성·수행**

체크 항목은 바퀴를 띄운 첫 시험, 물리 E-stop 담당자, 0.05 m/s 이하 첫 속도 상한, 최소 2 m 정지 공간, 배터리, 네트워크, ROS_DOMAIN_ID=51, map/TF 일치다.

- [ ] **Step 2: 센서와 TF를 모터 출력 없이 확인**

```bash
ros2 topic hz /scan /odom /trihouse/proximity/front /trihouse/battery
ros2 run tf2_ros tf2_echo map base_link
ros2 topic echo /trihouse/readiness --once
```

Expected: 필수 sensor가 timeout 이내, `map → base_link` TF가 연속적, readiness가 READY. 아니면 주행 금지.

- [ ] **Step 3: 실제 launch 후 단일 `/cmd_vel` publisher 확인**

```bash
export TRIHOUSE_MAP_REVISION='demo-map-v1'
export TRIHOUSE_MAP_PATH='/home/syw/Trihouse/pinky_pro/pinky_navigation/map/my_map.yaml'
export TRIHOUSE_CONTROL_HOST='192.168.0.10'
test -f "$TRIHOUSE_MAP_PATH"
ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py robot_id:=PK-01 map_revision:="$TRIHOUSE_MAP_REVISION" map:="$TRIHOUSE_MAP_PATH" control_host:="$TRIHOUSE_CONTROL_HOST"
ros2 topic info /cmd_vel -v
```

`TRIHOUSE_MAP_REVISION`과 `TRIHOUSE_CONTROL_HOST`는 실행 직전에 실제 배포 값으로 바꾸고 run 문서에 기록한다.

- [ ] **Step 4: 0.5 m 이하 직선 또는 가까운 waypoint로 저속 주행**

첫 goal은 장애물이 없는 영역에서 선택한다. 목표 pose는 `base_link` 중심의 `(x,y,yaw)` 한 점이며 로봇 앞 모서리 좌표를 사용하지 않는다.

- [ ] **Step 5: 실기 rosbag과 정차 오차 기록**

Gazebo와 동일 Topic을 기록하고 목표/최종 `base_link` pose의 xy·yaw 오차, 최대 속도, heartbeat 간격을 run 문서에 적는다.

- [ ] **Step 6: 문서 커밋**

```bash
git add docs/validation/pinky_hardware_preflight.md docs/validation/runs/2026-08-11-pinky-safety-validation.md
git commit -m "docs: record Pinky hardware preflight and low-speed run"
```

### Task 9: 실기 오류·비상·복귀 반복 검증

**Files:**
- Modify: `docs/validation/runs/2026-08-11-pinky-safety-validation.md`

**Interfaces:**
- Consumes: the same scenarios and expected state transitions as Task 6
- Produces: hardware evidence for SR_03, 23-25, 27, 54-57

- [ ] **Step 1: 비접촉 안전 입력부터 순차 검증**

관제 단절 → 사람 detection test message → keep-out 순서로 수행한다. 실제 사람을 로봇 진행 방향에 세워 최초 시험하지 않는다.

- [ ] **Step 2: 물리 장애물 접근 검증**

저속에서 큰 평면 장애물을 사용하고 stop distance 밖에서 시작한다. `/scan`, proximity, `/cmd_vel_nav`, `/cmd_vel`과 SafetyState를 동시에 기록한다.

- [ ] **Step 3: emergency latch와 관리자 해제 검증**

비상 입력 뒤 통신 재연결·노드 상태 변화만으로 해제되지 않는지 확인한다. 승인된 ClearEmergency 후에도 기존 작업이 자동 재개되지 않아야 한다.

- [ ] **Step 4: 대기/충전 waypoint 복귀와 health gate 검증**

Control Tower가 지정한 return pose로 이동한 후 scan, odom, proximity, battery, cargo, connection이 정상일 때만 IDLE이 되는지 확인한다.

- [ ] **Step 5: 결과 판정**

각 SR을 `passed`, `failed`, `blocked` 중 하나로 기록한다. UI에 표시된 것만으로 Pinky/Control Tower 통합을 passed 처리하지 않는다.

- [ ] **Step 6: 기록 커밋**

```bash
git add docs/validation/runs/2026-08-11-pinky-safety-validation.md
git commit -m "docs: record Pinky hardware emergency and recovery validation"
```

### Task 10: ArUco marker 기반 협로 입구 진입 — 마지막 Stretch

**Prerequisite:** Tasks 1-9가 모두 통과하고 실기 기본 주행과 정지가 안정적이어야 한다. 하나라도 failed면 이 Task를 시작하지 않고 `blocked_by_required_validation`으로 기록한다.

**Files:**
- Create: `trihouse_pinky/trihouse_pinky_docking/package.xml`
- Create: `trihouse_pinky/trihouse_pinky_docking/setup.py`
- Create: `trihouse_pinky/trihouse_pinky_docking/setup.cfg`
- Create: `trihouse_pinky/trihouse_pinky_docking/resource/trihouse_pinky_docking`
- Create: `trihouse_pinky/trihouse_pinky_docking/trihouse_pinky_docking/__init__.py`
- Create: `trihouse_pinky/trihouse_pinky_docking/trihouse_pinky_docking/controller.py`
- Create: `trihouse_pinky/trihouse_pinky_docking/trihouse_pinky_docking/dock_action_server.py`
- Create: `trihouse_pinky/trihouse_pinky_docking/test/test_controller.py`
- Create: `trihouse_pinky/trihouse_pinky_docking/test/test_dock_action_server.py`
- Modify: `trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_pinky_sim.launch.py`
- Modify: `trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_pinky.launch.py`
- Modify: `docs/validation/runs/2026-08-11-pinky-safety-validation.md`

**Interfaces:**
- Consumes: `/trihouse/vision/marker_observation/base: MarkerObservation`, `/trihouse/vision/readiness: Readiness`, `Dock.Goal.target_offset`
- Produces: `/cmd_vel_dock: Twist` only; never publishes `/cmd_vel` directly
- Produces: `/trihouse/dock: Dock` action result with marker lost/timeout/tolerance codes

- [ ] **Step 1: 순수 controller 실패 테스트 작성**

```python
def test_alignment_turns_before_forward_motion():
    decision = compute_dock_command(
        RelativePose(x=0.8, y=0.0, yaw=0.3),
        RelativePose(x=0.55, y=0.0, yaw=0.0),
        DockConfig(),
    )
    assert decision.command.linear_x == 0.0
    assert decision.command.angular_z != 0.0

def test_forward_speed_is_bounded_to_005_mps():
    decision = compute_dock_command(
        RelativePose(x=1.0, y=0.0, yaw=0.0),
        RelativePose(x=0.55, y=0.0, yaw=0.0),
        DockConfig(max_linear_mps=0.05),
    )
    assert 0.0 < decision.command.linear_x <= 0.05

def test_within_xy_and_yaw_tolerance_returns_zero_and_complete():
    target = RelativePose(x=0.55, y=0.0, yaw=0.0)
    decision = compute_dock_command(target, target, DockConfig())
    assert decision.complete is True
    assert decision.command == MotionCommand(0.0, 0.0)

def test_stale_or_wrong_marker_returns_zero_command():
    decision = reject_observation(reason="marker_stale")
    assert decision.complete is False
    assert decision.command == MotionCommand(0.0, 0.0)
```

controller signature를 다음으로 고정한다.

```python
def compute_dock_command(
    observed: RelativePose,
    target: RelativePose,
    config: DockConfig,
) -> DockDecision:
    """Return a bounded docking command in the base_link frame."""
```

- [ ] **Step 2: 최소 P controller 구현**

각속도 오차가 `angular_tolerance_rad`보다 크면 선속도는 0이다. 정렬 후에만 최대 0.05 m/s로 전진하며, 출력은 `DockDecision(command, complete, reason)`으로 반환한다.

- [ ] **Step 3: action lifecycle 실패 테스트 작성**

다음을 검증한다.

```text
vision readiness != READY → goal reject
marker ID mismatch/stale TTL → /cmd_vel_dock zero
marker loss → 즉시 zero, 최대 3회 제한 재탐색
timeout → CODE_TIMEOUT
허용 오차 도달 → CODE_OK
cancel → zero 후 CODE_CANCELED
```

- [ ] **Step 4: Dock action server 구현**

MarkerObservation의 `header.frame_id`는 `base_link`여야 한다. action server는 `/cmd_vel_dock`만 발행하고 Safety Supervisor가 `/cmd_vel`로 전달한다. open-loop 전진은 이번 협로 입구 검증에서 사용하지 않는다.

- [ ] **Step 5: launch를 `docking_enabled` 조건으로 연결**

기본값 `false`를 유지한다. Gazebo/실기 모두 명시적으로 `docking_enabled:=true`를 준 경우에만 action server를 시작한다.

- [ ] **Step 6: Gazebo 또는 기록된 marker pose replay 검증**

pre-dock pose까지 Nav2로 이동한 뒤 marker observation을 replay한다. `/cmd_vel_dock → Safety → /cmd_vel` 경로와 marker 소실 즉시 정지를 확인한다.

- [ ] **Step 7: 실기 marker frame과 목표 offset 측정**

```bash
ros2 run tf2_ros tf2_echo base_link camera_optical_frame
ros2 topic echo /trihouse/vision/marker_observation/base
```

marker 축의 방향을 확인한 뒤 `target_offset` 부호를 정한다. 로봇 중심 `base_link`가 협로 입구 중앙에 오도록 offset을 측정하며 추측값을 사용하지 않는다.

- [ ] **Step 8: 실기 저속 협로 입구 진입**

pre-dock pose → marker 정렬 → 지정 offset 정지까지만 수행한다. 협로 내부 장거리 주행이나 반대편 이탈은 수행하지 않는다. marker를 가리면 즉시 0이 되는지 별도 run으로 확인한다.

- [ ] **Step 9: docking 회귀 테스트와 전체 안전 테스트 실행**

```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select trihouse_pinky_docking trihouse_pinky_bringup trihouse_pinky_safety
colcon test --packages-select trihouse_pinky_docking trihouse_pinky_bringup trihouse_pinky_safety --event-handlers console_direct+
colcon test-result --verbose
```

- [ ] **Step 10: 코드와 결과 커밋**

```bash
git add trihouse_pinky/trihouse_pinky_docking trihouse_pinky/trihouse_pinky_bringup/launch docs/validation/runs/2026-08-11-pinky-safety-validation.md
git commit -m "feat: add guarded ArUco corridor entry docking"
```

## 최종 게이트

- [ ] Tasks 1-9의 모든 필수 테스트와 run 판정을 확인한다.
- [ ] `git diff --check`를 실행한다.
- [ ] 관련 없는 사용자 파일이 staging에 없는지 `git status --short`로 확인한다.
- [ ] ArUco Task가 차단됐더라도 필수 Gazebo·실기 결과를 별도로 완료 판정한다.
- [ ] `control_system 자체 구현 완료`와 `Trihouse 통합 완료`를 발표 자료에서 혼용하지 않는다.
