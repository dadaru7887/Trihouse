# Pinky 오프라인 ROS/Gazebo SR 검증 가이드

## 1. 목적

이 문서는 실물 Pinky, 유선 공유기, Control Tower, FMS, MySQL, TCP 8788 없이
`trihouse_*` Pinky 코드를 이해하고 검증하는 절차를 정의한다. 검증 대상은 Pinky가 직접
담당하는 `SR_03, SR_23, SR_24, SR_25, SR_45, SR_48, SR_49, SR_54, SR_57`이다.

검증 결과는 다음 세 등급을 혼용하지 않는다.

| 등급 | 증명하는 것 | 증명하지 못하는 것 |
| --- | --- | --- |
| `static` | 정책 입력·상태 전이·launch 계약 | ROS graph, Gazebo 물리, 실물 센서 |
| `offline-simulation` | Gazebo 센서, Nav2, Safety, readiness/status의 ROS 연결 | TCP 8788, Control Tower/FMS, 실물 Pinky |
| `integration` | Control Tower/FMS 명령과 상태 보고 | 실물 센서 정확도와 정차 성능 |

`final_map_08.yaml`을 RViz와 Nav2에 표시하는 것과 같은 구조의 Gazebo world가 존재하는 것은
별개다. 현재 vendor simulation은 `pinky_factory.world`를 사용한다. 따라서 1단계는 ROS
인터페이스와 안전 경계를 검증하고, `final_map_08` 구조에서의 경로 성공은 동일한 Gazebo
world를 만드는 2단계 전까지 합격 근거로 사용하지 않는다.

## 2. 대상 구조와 offline 경계

```text
pinky_gz_sim
  └─ /scan, /odom, /tf, /clock
          ↓
pinky_navigation (Nav2)
  └─ /cmd_vel_nav
          ↓
trihouse_pinky_safety/safety_supervisor
  └─ /cmd_vel → Gazebo Pinky

trihouse_pinky_bringup
  ├─ sim_hardware → /trihouse/proximity/front, /trihouse/battery
  └─ readiness_checker → /trihouse/readiness

trihouse_pinky_fleet
  ├─ fleet_node → /trihouse/transport/execute, /trihouse/navigation/state
  ├─ status_node → /trihouse/status
  └─ recovery_health → /trihouse/health

offline에서 실행하지 않음
  ├─ fleet_gateway → TCP 8788
  └─ gazebo_omx_adapter
```

최종 `/cmd_vel` 발행자는 Safety Supervisor 하나여야 한다. Nav2가 `/cmd_vel`을 직접
발행하면 offline simulation의 핵심 안전 경계가 실패한 것이다.

## 3. 현재 코드에서 먼저 확인된 차단 사항

### 3.1 offline 선택 인자가 아직 없다

`trihouse_pinky_sim.launch.py`는 `fleet_gateway`와 `gazebo_omx_adapter`를 항상 실행한다.
따라서 목표 설계에는 다음 launch 인자가 필요하다.

```text
control_enabled:=false
omx_enabled:=false
```

두 인자가 구현되기 전에는 아래 통합 launch 명령을 완전한 offline 합격 명령으로 사용하지
않는다. TCP 연결 재시도나 OMX 시작 실패가 다른 노드 결과에 섞이기 때문이다.

### 3.2 `status_node` 메시지 타입 불일치

`RobotStatus.battery_policy` 타입은 `BatteryPolicyState`지만 현재 `status_node.py`는 float인
`self.battery`를 대입한다.

```python
message.battery_policy = self.battery
```

올바른 대입 대상은 node가 이미 보관하는 `self.battery_policy`다. 수정 전에는
`/trihouse/status` runtime 발행을 `BLOCKED`로 기록한다.

### 3.3 offline에서도 관제 연결 상태 입력이 필요하다

Safety Supervisor는 `/trihouse/fms/state`가 `STATE_ONLINE`이 아니면 최종 속도를 0으로 만든다.
이는 올바른 fail-safe 정책이다. offline 시험에서는 FMS를 가장하지 않고, 시험자가 아래의
명시적인 mock 메시지를 발행했다는 사실을 결과에 기록한다.

## 4. 공통 준비와 정적 회귀 테스트

모든 터미널의 공통 시작 명령은 다음과 같다.

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
source /home/syw/Trihouse/install/setup.bash
export ROS_DOMAIN_ID=51
```

현재 코드 식별 정보를 먼저 기록한다.

```bash
git rev-parse --short=12 HEAD
git status --short --branch
```

Pinky 정적 정책 전체를 실행한다.

```bash
cd /home/syw/Trihouse
PYTHONPATH='trihouse_pinky/trihouse_pinky_fleet:trihouse_pinky/trihouse_pinky_safety:trihouse_pinky/trihouse_pinky_io:trihouse_pinky/trihouse_pinky_bringup' \
python3 -m pytest -v \
  trihouse_pinky/test/test_pinky_sr_policies.py \
  trihouse_pinky/test/test_eta_policy.py \
  trihouse_pinky/test/test_integrated_bringup_contract.py
```

합격 기준은 모든 수집 테스트 통과와 종료 코드 0이다. 기존 문서의 `34 passed`는 테스트가
추가·삭제되면 달라질 수 있으므로 현재 수집 개수도 함께 기록한다.

```bash
PYTHONPATH='trihouse_pinky/trihouse_pinky_fleet:trihouse_pinky/trihouse_pinky_safety:trihouse_pinky/trihouse_pinky_io:trihouse_pinky/trihouse_pinky_bringup' \
python3 -m pytest --collect-only -q \
  trihouse_pinky/test/test_pinky_sr_policies.py \
  trihouse_pinky/test/test_eta_policy.py \
  trihouse_pinky/test/test_integrated_bringup_contract.py
```

## 5. 목표 offline 통합 실행 터미널

아래 명령은 `control_enabled`와 `omx_enabled`가 구현된 뒤 사용할 목표 명령이다. 구현 전에는
두 인자가 `unused`로 거부되거나 gateway/OMX가 계속 실행되므로 합격 처리하지 않는다.

### 터미널 1 — Gazebo, Nav2, Trihouse offline graph

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=51

ros2 launch trihouse_pinky_bringup trihouse_gazebo_demo.launch.py \
  map:=/home/syw/Desktop/final_map_08.yaml \
  map_revision:=final-map-08 \
  control_enabled:=false \
  omx_enabled:=false
```

### 터미널 2 — RViz

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=51

ros2 launch pinky_navigation gz_nav2_view.launch.xml
```

### 터미널 3 — 핵심 graph 관찰

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=51

ros2 node list
ros2 topic list -t
ros2 action list -t
```

### 터미널 4 — offline 관제 연결 mock

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=51

ros2 topic pub --once /trihouse/fms/state \
  trihouse_interfaces/msg/ConnectionState \
  "{robot_id: 'PK-01', session_id: 'offline-test', state: 2, detail: 'explicit offline test input'}"
```

이 입력은 Safety의 `control_link_fresh` gate만 연다. Control Tower/FMS 연동 성공을 의미하지
않는다.

## 6. 공통 runtime 사전 점검

필수 노드:

```bash
ros2 node list | sort
```

최소 기대 항목:

```text
/amcl
/bt_navigator
/controller_server
/fleet_node
/map_server
/planner_server
/readiness_checker
/recovery_health
/safety_supervisor
/sim_hardware
```

필수 토픽과 action:

```bash
ros2 topic list | rg '^/(clock|scan|odom|tf|tf_static|cmd_vel|cmd_vel_nav|trihouse/)'
ros2 action list -t
```

다음 action이 있어야 한다.

```text
/navigate_to_pose [nav2_msgs/action/NavigateToPose]
/trihouse/transport/execute [trihouse_interfaces/action/ExecuteTransport]
```

속도 발행자 경계를 확인한다.

```bash
ros2 topic info /cmd_vel -v
ros2 topic info /cmd_vel_nav -v
```

합격 기준:

- `/cmd_vel` publisher는 `safety_supervisor` 하나다.
- `/cmd_vel_nav` publisher는 Nav2 controller 계열이다.
- `fleet_gateway`와 `gazebo_omx_adapter` 노드는 offline graph에 없다.

## 7. SR별 테스트 파일, 명령과 검증 항목

### 7.1 SR_03 — 로봇 상태 공유

| 구분 | 파일 |
| --- | --- |
| 요구사항 | `docs/requirements/system_requirements.md` |
| 메시지 | `trihouse_interfaces/msg/RobotStatus.msg` |
| 정책 | `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/status.py` |
| ROS node | `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/status_node.py` |
| 정적 테스트 | `trihouse_pinky/test/test_pinky_sr_policies.py::StatusPolicyTest` |

정적 실행:

```bash
PYTHONPATH='trihouse_pinky/trihouse_pinky_fleet' \
python3 -m pytest -v \
  trihouse_pinky/test/test_pinky_sr_policies.py::StatusPolicyTest
```

runtime 관찰:

```bash
ros2 topic hz /trihouse/status
ros2 topic echo /trihouse/status --once
```

검증 항목:

- 정상 센서에서 약 1 Hz heartbeat가 발행된다.
- `robot_id=PK-01`, `frame_id`, pose, twist, battery, safety, ready가 채워진다.
- `/scan` 또는 `/odom`이 stale이면 `ready=false`와 오류가 나온다.
- 현재 타입 불일치를 수정하기 전 runtime 결과는 `BLOCKED`다.
- TCP/FMS 전송은 2차 integration 범위다.

### 7.2 SR_23 — 사람·전방 장애물 충돌 방지

| 구분 | 파일 |
| --- | --- |
| 정책 | `trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/policy.py` |
| ROS node | `trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/safety_supervisor_node.py` |
| 정적 테스트 | `SafetyPolicyTest`, `KeepOutGeometryTest` |

정적 실행:

```bash
PYTHONPATH='trihouse_pinky/trihouse_pinky_safety' \
python3 -m pytest -v \
  trihouse_pinky/test/test_pinky_sr_policies.py::SafetyPolicyTest \
  trihouse_pinky/test/test_pinky_sr_policies.py::KeepOutGeometryTest
```

runtime 정상 통과 시험은 터미널 두 개를 사용한다.

```bash
# 관찰 터미널
ros2 topic echo /cmd_vel
```

```bash
# 입력 터미널: offline FMS online mock 후 Nav2 속도 입력
ros2 topic pub --once /trihouse/fms/state trihouse_interfaces/msg/ConnectionState \
  "{robot_id: 'PK-01', session_id: 'offline-test', state: 2}"
ros2 topic pub --once /cmd_vel_nav geometry_msgs/msg/Twist \
  "{linear: {x: 0.10}, angular: {z: 0.0}}"
```

전방 정지 시험:

```bash
ros2 param set /sim_hardware front_distance_m 0.20
ros2 topic pub --once /cmd_vel_nav geometry_msgs/msg/Twist \
  "{linear: {x: 0.10}, angular: {z: 0.0}}"
ros2 topic echo /trihouse/safety/state --once
```

복구:

```bash
ros2 param set /sim_hardware front_distance_m 3.0
```

검증 항목:

- 3.0 m에서는 입력 속도가 최종 `/cmd_vel`로 통과한다.
- 0.20 m에서는 최종 linear/angular가 0이고 safety state가 STOP이다.
- 정지해도 Nav2 goal 자체는 취소되지 않는다.
- 사람 runtime 입력은 `PersonDetection.pose` 거리와 TTL을 사용하며, 실제 vision 정확도는 이
  단계에서 검증하지 않는다.

### 7.3 SR_24·SR_48 — 운반 요청과 Nav2 이동

| 구분 | 파일 |
| --- | --- |
| 상태 정책 | `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/workflow.py` |
| action adapter | `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py` |
| action 계약 | `trihouse_interfaces/action/ExecuteTransport.action` |
| 정적 테스트 | `TransportWorkflowTest` |

정적 실행:

```bash
PYTHONPATH='trihouse_pinky/trihouse_pinky_fleet' \
python3 -m pytest -v \
  trihouse_pinky/test/test_pinky_sr_policies.py::TransportWorkflowTest
```

먼저 readiness와 cargo를 확인한다.

```bash
ros2 topic echo /trihouse/readiness --once
ros2 topic echo /trihouse/cargo/state --once
```

일반 운반은 cargo가 `LOCKED`이고 `sensor_confirmed=true`여야 수락된다. offline cargo mock:

```bash
ros2 topic pub --once /trihouse/cargo/state trihouse_interfaces/msg/CargoState \
  "{robot_id: 'PK-01', job_id: 'job-sim-1', request_id: 'cargo-sim-1', state: 2, sensor_confirmed: true, detail: 'offline locked cargo'}"
```

지도상 안전한 자유 공간 좌표로 action을 보낸다.

```bash
ros2 action send_goal /trihouse/transport/execute \
  trihouse_interfaces/action/ExecuteTransport \
  "{command_id: 'cmd-sim-1', job_id: 'job-sim-1', job_step_id: 'transport-1', map_revision: 'final-map-08', dropoff_location_id: 'TEST-01', destination_code: 'AMBIENT', dropoff_pose: {header: {frame_id: 'map'}, pose: {position: {x: 0.4, y: 0.3, z: 0.0}, orientation: {w: 1.0}}}, requires_precise_stop: false, mode: 0}" \
  --feedback
```

동시에 관찰한다.

```bash
ros2 topic echo /trihouse/navigation/state
ros2 topic echo /trihouse/task/events
ros2 topic echo /cmd_vel_nav
ros2 topic echo /cmd_vel
```

검증 항목:

- readiness/cargo 전에는 action이 `CODE_REJECTED`다.
- 준비 후 동일 command는 Nav2 goal 하나만 만든다.
- Nav2 성공과 정지 확인 뒤 `WAITING_HANDOVER`가 된다.
- 현재 Gazebo world와 `final_map_08` 불일치로 경로가 실패하면 interface 결과만 기록하고
  사용자 맵 주행 FAIL로 판정하지 않는다.

### 7.4 SR_25 — 대기·충전 위치 복귀

관련 파일과 테스트는 SR_24·48과 같으며
`TransportWorkflowTest::test_empty_return_to_charge_is_accepted_without_cargo`가 핵심이다.

```bash
PYTHONPATH='trihouse_pinky/trihouse_pinky_fleet' \
python3 -m pytest -v \
  trihouse_pinky/test/test_pinky_sr_policies.py::TransportWorkflowTest::test_empty_return_to_charge_is_accepted_without_cargo
```

runtime에서는 cargo 없이 `mode: 2`를 보낸다.

```bash
ros2 action send_goal /trihouse/transport/execute \
  trihouse_interfaces/action/ExecuteTransport \
  "{command_id: 'cmd-return-1', job_id: 'return-1', job_step_id: 'return-charge', map_revision: 'final-map-08', dropoff_location_id: 'CHARGE-01', destination_code: 'RETURN', dropoff_pose: {header: {frame_id: 'map'}, pose: {position: {x: 0.4, y: 0.3, z: 0.0}, orientation: {w: 1.0}}}, requires_precise_stop: false, mode: 2}" \
  --feedback
```

합격 기준은 cargo가 없어도 readiness가 정상이면 명령이 수락되는 것이다. 실제 충전 GPIO와
충전 완료 판정은 hardware 범위다.

### 7.5 SR_45 — 포장대 재배정

| 구분 | 파일 |
| --- | --- |
| Pinky 상태 전이 | `workflow.py::reassign` |
| action 처리 | `fleet_node.py::_execute` |
| 정적 테스트 | `TransportWorkflowTest::test_waiting_handover_can_move_to_fms_reassigned_packing_station` |

```bash
PYTHONPATH='trihouse_pinky/trihouse_pinky_fleet' \
python3 -m pytest -v \
  trihouse_pinky/test/test_pinky_sr_policies.py::TransportWorkflowTest::test_waiting_handover_can_move_to_fms_reassigned_packing_station
```

runtime 검증은 첫 action이 `WAITING_HANDOVER`에 도달한 뒤 같은 `job_id`와 새 `command_id`, 새
dropoff pose를 보내 수행한다. 합격 기준은 job ID가 유지되고 navigation state가 다시 ACTIVE가
되며 Nav2 goal이 정확히 하나 추가되는 것이다. 어느 포장대를 고를지는 Control Tower의
`packing_station.py` 책임이므로 2차 integration에서 검증한다.

### 7.6 SR_49 — 목적지 표시와 안전 표시 우선순위

| 구분 | 파일 |
| --- | --- |
| 목적지 정책 | `trihouse_pinky/trihouse_pinky_io/trihouse_pinky_io/destination_display.py` |
| 표시 우선순위 | `trihouse_pinky/trihouse_pinky_io/trihouse_pinky_io/indicator.py` |
| 테스트 | `DestinationDisplayTest`, `IndicatorTest` |

```bash
PYTHONPATH='trihouse_pinky/trihouse_pinky_io' \
python3 -m pytest -v \
  trihouse_pinky/test/test_pinky_sr_policies.py::DestinationDisplayTest \
  trihouse_pinky/test/test_pinky_sr_policies.py::IndicatorTest
```

runtime 관찰:

```bash
ros2 topic echo /trihouse/display/destination_code
ros2 topic echo /trihouse/indicator/state
```

합격 기준:

- 운반 목표의 허용 destination code가 그대로 발행된다.
- 알 수 없는 code는 임의 한글 목적지로 변환되지 않는다.
- emergency 표시가 person/handover 표시보다 우선한다.
- 실제 LCD, LED, buzzer 출력은 hardware 검증 대상이다.

### 7.7 SR_54 — 비상 정지와 명시적 해제

| 구분 | 파일 |
| --- | --- |
| 속도 latch | `safety_supervisor_node.py` |
| 정책 | `policy.py`, `geometry.py` |
| service | `trihouse_interfaces/srv/ClearEmergency.srv` |
| 테스트 | `KeepOutGeometryTest`, `FleetProtocolTest`의 clear/zone 테스트 |

비상 요청:

```bash
ros2 topic pub --once /trihouse/safety/emergency_request std_msgs/msg/Bool "{data: true}"
ros2 topic echo /trihouse/safety/state --once
ros2 topic echo /cmd_vel --once
```

익명 해제 거부:

```bash
ros2 service call /trihouse/safety/clear_emergency \
  trihouse_interfaces/srv/ClearEmergency \
  "{robot_id: 'PK-01', operator_id: '', request_id: 'clear-denied-1', reason: 'offline negative test'}"
```

승인 주체를 포함한 해제:

```bash
ros2 service call /trihouse/safety/clear_emergency \
  trihouse_interfaces/srv/ClearEmergency \
  "{robot_id: 'PK-01', operator_id: 'offline-test-operator', request_id: 'clear-1', reason: 'offline reset'}"
```

검증 항목:

- emergency 이후 `/cmd_vel`은 0이다.
- 정상 센서 입력이 돌아와도 명시적 clear 전에는 latch가 유지된다.
- operator ID가 없는 해제는 거부된다.
- clear는 이전 작업 자동 재개가 아니라 복귀 점검 시작만 허용한다.
- 실제 관리자 인증은 Control Tower integration 범위다.

### 7.8 SR_57 — 복귀 후 재투입 health check

| 구분 | 파일 |
| --- | --- |
| 순수 정책 | `trihouse_pinky_fleet/recovery_health.py` |
| ROS node | `trihouse_pinky_fleet/recovery_health_node.py` |
| 테스트 | `RecoveryHealthTest`, recovery 관련 `TransportWorkflowTest` |

```bash
PYTHONPATH='trihouse_pinky/trihouse_pinky_fleet' \
python3 -m pytest -v \
  trihouse_pinky/test/test_pinky_sr_policies.py::RecoveryHealthTest \
  trihouse_pinky/test/test_pinky_sr_policies.py::TransportWorkflowTest::test_recovery_return_arrival_requires_health_check_before_idle
```

runtime 관찰:

```bash
ros2 topic echo /trihouse/health
```

고장 cargo mock:

```bash
ros2 topic pub --once /trihouse/cargo/state trihouse_interfaces/msg/CargoState \
  "{robot_id: 'PK-01', job_id: 'recovery-1', request_id: 'cargo-recovery-1', state: 2, sensor_confirmed: true, detail: 'cargo remains'}"
ros2 topic echo /trihouse/health --once
```

정상 cargo mock:

```bash
ros2 topic pub --once /trihouse/cargo/state trihouse_interfaces/msg/CargoState \
  "{robot_id: 'PK-01', job_id: 'recovery-1', request_id: 'cargo-recovery-2', state: 1, sensor_confirmed: true, detail: 'cargo removed'}"
ros2 topic echo /trihouse/health --once
```

합격 기준은 odom, scan, ultrasonic, battery가 fresh이고 cargo가 없을 때만 health가 OK가 되는
것이다. 센서 하나라도 stale이거나 cargo가 남아 있으면 재투입할 수 없다.

## 8. 테스트 결과 기록 형식

실행 결과는 다음 항목을 남긴다.

```text
date/time:
commit SHA:
map YAML 및 map revision:
ROS_DOMAIN_ID:
test level: static | offline-simulation | integration
SR:
command:
expected:
observed:
PASS | FAIL | BLOCKED:
blocking reason:
log/screenshot path:
```

판정 규칙:

- `PASS`: 해당 단계의 모든 검증 항목을 관측했다.
- `FAIL`: 필요한 인터페이스가 실행됐지만 관측값이 요구사항과 달랐다.
- `BLOCKED`: 선행 결함, 누락 package, world 불일치처럼 해당 기능을 실행할 수 없었다.
- `final_map_08`과 Gazebo world 불일치는 1단계 인터페이스 검증의 FAIL이 아니라 2단계 선행
  작업이다.

## 9. 1단계 완료 조건과 다음 단계

다음을 모두 만족하면 Control Tower/FMS 연결 단계로 넘어간다.

1. Pinky 정적 정책 테스트가 모두 통과한다.
2. offline launch에서 gateway와 OMX가 실행되지 않는다.
3. `/cmd_vel` 발행자는 Safety Supervisor 하나다.
4. 정상·전방 정지·비상 latch에서 `/cmd_vel_nav → /cmd_vel` 결과가 예상과 같다.
5. readiness와 recovery health가 센서 freshness에 따라 바뀐다.
6. `status_node` 타입 결함이 수정되고 `/trihouse/status`가 약 1 Hz로 발행된다.
7. `ExecuteTransport`가 준비 전 거절되고 준비 후 Nav2 goal 하나만 만든다.
8. 시뮬레이션 한계와 실제 Pinky 미검증 항목이 결과 기록에 명시된다.

그 다음 단계에서는 `control_enabled:=true`로 TCP 8788 연결을 활성화하고 Control Tower가
`ExecuteTransport`를 생성하며 `/trihouse/status`를 수신하는 흐름을 검증한다. 사용자 맵에서
실제 경로·충돌을 검증하려면 별도로 `final_map_08`과 같은 벽·선반 collision을 가진 Gazebo
world를 제작해야 한다.
