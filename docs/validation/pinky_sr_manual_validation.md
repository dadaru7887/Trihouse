# Pinky SR 수동 정적 검증과 코드 분석

이 문서는 ROS 2와 Gazebo를 처음 다루는 사람도 Pinky SR 구현 근거를 직접 확인할 수
있도록 정적 테스트, 코드 읽기, 제한적인 Gazebo 검증을 순서대로 설명한다. 기준 저장소는
`/home/syw/Trihouse`이며 `pinky_pro/`와 `control_system/` 원본은 수정하지 않는다.

## 1. 무엇을 증명하는가

검증 결과를 다음 세 등급으로 구분한다.

| 등급 | 증명하는 내용 | 증명하지 못하는 내용 |
| --- | --- | --- |
| `static` | 입력 검증, 상태 전이, 안전 우선순위, launch source 계약 | ROS graph, Gazebo 물리, 실제 센서 |
| `simulation` | Gazebo 모델, ROS topic, 모의 센서와 Safety 연결 | 실물 Pinky, 실제 GPIO, 실제 네트워크 |
| `hardware` | 실물 센서, 모터, 정차 오차와 장치 부하 | 이 문서의 현재 실행 범위 밖 |

정적 테스트가 통과해도 “Pinky 주행 검증 완료”라고 표현하지 않는다. 발표에서는
`정적 정책 34개 통과`와 `headless Gazebo 부분 검증`을 서로 다른 증거로 표시한다.

## 2. 터미널과 저장소 상태 확인

모든 명령은 새 터미널에서 다음 경로로 이동한 뒤 실행한다.

```bash
cd /home/syw/Trihouse
pwd
git rev-parse --short=12 HEAD
git status --short --branch
python3 --version
```

- `cd`는 명령이 참조하는 상대 경로의 기준을 저장소 루트로 맞춘다.
- `pwd`가 `/home/syw/Trihouse`인지 확인한다.
- commit SHA는 어떤 코드에서 얻은 결과인지 식별하는 증거다.
- `git status`는 검증 전에 미커밋 변경이 있었는지 기록한다.
- 정적 정책 테스트는 시스템 Python 3으로 실행하며 ROS 설치가 없어도 된다.

## 3. 테스트를 실행하기 전에 목록만 확인하기

```bash
PYTHONPATH='trihouse_pinky/trihouse_pinky_fleet:trihouse_pinky/trihouse_pinky_safety:trihouse_pinky/trihouse_pinky_io:trihouse_pinky/trihouse_pinky_bringup' \
python3 -m pytest --collect-only -q \
  trihouse_pinky/test/test_pinky_sr_policies.py \
  trihouse_pinky/test/test_eta_policy.py \
  trihouse_pinky/test/test_integrated_bringup_contract.py
```

`PYTHONPATH`는 아직 wheel로 설치하지 않은 네 Python 패키지를 import 검색 경로에 추가한다.
`--collect-only`는 테스트를 실행하지 않고 발견된 이름만 보여준다. 현재 기준 기대값은
`34 tests collected`다.

## 4. Pinky SR 정적 테스트 실행

```bash
PYTHONPATH='trihouse_pinky/trihouse_pinky_fleet:trihouse_pinky/trihouse_pinky_safety:trihouse_pinky/trihouse_pinky_io:trihouse_pinky/trihouse_pinky_bringup' \
python3 -m pytest -v \
  trihouse_pinky/test/test_pinky_sr_policies.py \
  trihouse_pinky/test/test_eta_policy.py \
  trihouse_pinky/test/test_integrated_bringup_contract.py
```

- `python3 -m pytest`는 현재 Python과 같은 환경의 pytest를 사용한다.
- `-v`는 테스트 이름을 모두 출력하므로 SR 설명 자료로 사용할 수 있다.
- 세 파일을 명시해 다른 컴포넌트의 선택적 의존성 때문에 결과가 섞이지 않게 한다.
- 성공 판정은 마지막 줄의 `34 passed`와 프로세스 종료 코드 0이다.

Python 문법과 import 가능한 source 형태도 확인한다.

```bash
python3 -m compileall -q trihouse_pinky
echo $?
```

`compileall`은 Python source를 bytecode로 컴파일한다. `-q`라서 성공 시 출력이 없으며,
`echo $?`가 `0`이면 통과다. 이는 ROS package 의존성이나 노드 실행까지 검증하지 않는다.

## 5. SR을 하나씩 검증하는 방법

한 번에 34개 테스트를 실행한 결과는 전체 회귀 확인에는 유용하지만, 개별 SR을 이해했다는
증거로는 부족하다. 실제 학습·검증은 `요구사항 원문 → 메시지 계약 → 순수 정책 → ROS node
→ 외부 시스템 경계` 순서로 SR 한 개씩 진행한다. 현재 첫 대상은 SR_03이다.

### 5.1 SR_03 로봇 상태 공유

#### 구현 흐름

```text
/scan, /odom, /trihouse/battery
/trihouse/safety/state, /trihouse/cargo/state, /trihouse/navigation/state
                         ↓
                    status_node
                         ↓
                 /trihouse/status
                         ↓
                    fleet_gateway
                         ↓
                  FMS NDJSON/TCP
```

다음 순서로 원문과 코드를 읽는다.

```bash
cd /home/syw/Trihouse

# SR_03 원문을 확인한다.
rg -n -C 2 'SR_03' docs/requirements/system_requirements.md

# FMS로 전달할 ROS 메시지의 필드와 타입을 확인한다.
nl -ba trihouse_interfaces/msg/RobotStatus.msg
nl -ba trihouse_interfaces/msg/BatteryPolicyState.msg

# 센서 freshness를 작업 가능 여부로 바꾸는 순수 정책을 확인한다.
nl -ba trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/status.py

# ROS 입력을 RobotStatus로 조합하는 node를 확인한다.
nl -ba trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/status_node.py

# RobotStatus를 FMS용 NDJSON payload로 바꾸는 경계를 확인한다.
nl -ba trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/gateway_node.py | sed -n '21,50p'
```

SR_03의 순수 정책 테스트 하나만 실행한다.

```bash
cd /home/syw/Trihouse

PYTHONPATH='trihouse_pinky/trihouse_pinky_fleet' \
python3 -m pytest \
  trihouse_pinky/test/test_pinky_sr_policies.py::StatusPolicyTest \
  -v
```

기대 결과는 `1 passed`다. 이 테스트는 `/scan`이 stale이면 `ready=False`와
`scan_stale` 오류가 생성되는 것만 증명한다. 1초 발행, 변경 즉시 발행, pose 전송, TCP 전송,
FMS의 배정 차단은 아직 증명하지 않는다.

현재 source에는 `RobotStatus.battery_policy`에 `BatteryPolicyState`가 아니라 `float`를 넣는
결함이 있다. 다음 명령은 source를 수정하지 않고 ROS 직렬화 경계에서 문제를 재현한다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/syw/Trihouse/install/setup.bash

python3 -c "from trihouse_interfaces.msg import RobotStatus; from rclpy.serialization import serialize_message; m=RobotStatus(); print('expected=', type(m.battery_policy).__name__); m.battery_policy=42.0; print('assigned=', type(m.battery_policy).__name__); serialize_message(m)"
```

현재 기대 결과는 `expected= BatteryPolicyState`, `assigned= float` 출력 뒤 assertion과 종료
코드 134다. 이는 테스트 환경 문제가 아니라
`status_node.py`의 `message.battery_policy = self.battery` 대입과 메시지 계약의 불일치다.
수정 전에는 `status_node`의 1초 heartbeat 실행 검증으로 넘어가지 않는다.

#### SR_03 현재 판정

| 요구사항 | 현재 증거 | 판정 |
| --- | --- | --- |
| stale 센서를 작업 불가로 보고 | `StatusPolicyTest` | 정적 PASS |
| 로봇 ID·작업 ID·단계 보유 | `RobotStatus.msg`, `status_node.py` | source 확인 |
| 위치·방향·배터리·주행·적재·안전·오류 보유 | `RobotStatus.msg` | 메시지 계약 확인 |
| 1초 주기 발행 | 1초 timer source | 실행 미검증 |
| 작업 단계·안전 상태 변경 즉시 발행 | navigation/safety callback source | 실행 미검증 |
| ROS 메시지 실제 발행 | battery policy 타입 불일치 | BLOCKED |
| FMS로 위치·방향·주행 상태 전송 | gateway payload에 해당 필드 없음 | 미구현 |
| FMS TCP 수신 | Control Tower에 TCP 8788 수신 server 없음 | 미구현 |
| FMS가 작업 불가 Pinky의 신규 배정 차단 | 배차 정책은 존재하지만 status 수신과 연결되지 않음 | 부분 구현 |

`RobotStatus.msg`와 `gateway_node.py::_status()`를 대조하면 다음과 같다.

| RobotStatus 필드 | FMS NDJSON 포함 | SR_03 관점 |
| --- | --- | --- |
| `robot_id` | 예 | 충족 후보 |
| `stamp` | 원본 대신 gateway 현재 시각 `sent_at_ns` 사용 | 충족 후보 |
| `current_job_id`, `current_job_step_id` | 예 | 충족 후보 |
| `pose`, `frame_id` | 아니요 | 위치·방향 누락 |
| `twist`, `navigation_state`, `task_progress` | 아니요 | 주행 상태 누락 |
| `battery_percentage` | 예 | 충족 후보 |
| `battery_policy` | 아니요 | 정책 상태 누락 |
| `cargo.state`, `safety.state` | enum 값만 포함 | 상세정보 필요 여부 확인 |
| `ready`, `errors` | 예 | 작업 불가 보고 후보 |

Control Tower의 `DispatchWorkflow.assign()`은 `robot.ready`가 참인 robot만 후보로 고르므로
작업 불가 배정 차단 **정책 자체**는 존재한다. 그러나 현재 저장소에는 Pinky TCP
`robot_status`를 수신해 `RobotSnapshot`으로 만들고 `upsert_robot()`을 호출하는 연결 코드가
없다. 따라서 단위 정책을 실제 end-to-end 동작으로 확대해 설명하면 안 된다.

gateway가 실제 만드는 payload는 TCP server 없이 다음 명령으로 관찰할 수 있다. ROS overlay의
생성 메시지 경로를 보존해야 하므로 이 명령에서는 `PYTHONPATH`를 새 값으로 덮어쓰지 않는다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/syw/Trihouse/install/setup.bash

python3 - <<'PY'
from types import SimpleNamespace
from trihouse_interfaces.msg import RobotStatus
from trihouse_pinky_fleet.gateway_node import GatewayNode

class LinkRecorder:
    def send(self, payload):
        print(payload)

message = RobotStatus()
message.robot_id = 'PK-01'
message.frame_id = 'map'
message.pose.pose.position.x = 1.25
message.pose.pose.position.y = -0.50
message.battery_percentage = 80.0
message.current_job_id = 'job-1'
message.current_job_step_id = 'transport'
message.navigation_state = 1
message.task_progress = 0.5
message.ready = True

fake_node = SimpleNamespace(
    link=LinkRecorder(),
    get_clock=lambda: SimpleNamespace(
        now=lambda: SimpleNamespace(nanoseconds=123456789)
    ),
)
GatewayNode._status(fake_node, message)
PY
```

출력에는 `robot_id`, job/step, ready, battery, safety, cargo, errors는 있지만 입력한
`frame_id`, x=1.25, y=-0.50, `navigation_state`, `task_progress`가 없다. 이것이 위치·방향·주행
상태가 FMS 경계에서 누락된 직접 증거다.

FMS 배차 정책만 별도로 눈으로 확인하려면 다음을 실행한다.

```bash
cd /home/syw/Trihouse

python3 - <<'PY'
from control_tower.fleet_manager.dispatch_workflow import (
    DispatchWorkflow,
    RobotSnapshot,
    TaskRequest,
)

fms = DispatchWorkflow()
fms.upsert_robot(RobotSnapshot(
    robot_id='PK-01',
    ready=False,
    battery=80,
    available_at_s=0,
    cargo_present=False,
))

try:
    fms.assign(TaskRequest(
        job_id='job-1',
        priority=1,
        requested_at_s=0,
        workspace_id='PACK-1',
    ))
except ValueError as error:
    print(type(error).__name__, str(error))
PY
```

기대 출력은 `ValueError no assignable robot`이다. 이 결과는 `ready=False` 배정 제외 정책만
검증하며 Pinky status가 Control Tower에 도달한다는 의미는 아니다.

### 5.2 테스트 파일부터 읽는 이유

구현 파일을 처음부터 전부 읽기보다 테스트의 입력과 기대값을 먼저 보면 정책 경계를 빠르게
이해할 수 있다.

```bash
sed -n '1,340p' trihouse_pinky/test/test_pinky_sr_policies.py
sed -n '1,120p' trihouse_pinky/test/test_eta_policy.py
sed -n '1,120p' trihouse_pinky/test/test_integrated_bringup_contract.py
```

읽을 때 각 테스트에서 다음 네 항목을 메모한다.

1. 입력 상태: 센서, 관제 연결, cargo, map revision
2. 실행 함수: `apply_safety_gate`, `TransportWorkflow.accept` 등
3. 기대 상태: `STOP`, `NAVIGATING`, `WAITING_HANDOVER`, `IDLE`
4. 금지 조건: 익명 비상 해제, cargo 없는 출발, stale 센서 주행 등

## 6. SR별 코드 읽기 순서

### 6.1 SR_23 사람 충돌 방지와 안전 정지

```bash
sed -n '1,220p' trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/policy.py
sed -n '1,260p' trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/safety_supervisor_node.py
rg -n 'SafetyPolicyTest|KeepOutGeometryTest' trihouse_pinky/test/test_pinky_sr_policies.py
```

`policy.py`의 판정 순서는 비상 latch → 관제 단절 → 센서 timeout → 장애물/keep-out 정지 →
보호 구역 감속 → 정상 통과다. `safety_supervisor_node.py`는 `/cmd_vel_nav`와 센서를 받아
최종 `/cmd_vel`을 발행한다. 따라서 테스트에서는 속도 값뿐 아니라 더 높은 우선순위가 낮은
우선순위를 덮는지도 확인한다.

### 6.2 SR_24·45·48·57 운반과 복구 상태 전이

```bash
sed -n '1,320p' trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/workflow.py
sed -n '1,300p' trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py
sed -n '1,180p' trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/recovery_health.py
rg -n 'TransportWorkflowTest|RecoveryHealthTest|ArrivalToleranceTest' \
  trihouse_pinky/test/test_pinky_sr_policies.py
```

확인할 핵심은 다음과 같다.

- readiness와 cargo 확인 전에는 운반을 시작하지 않는다.
- Nav2 성공만으로 도착을 확정하지 않고 정지 상태도 확인한다.
- 도착 뒤 cargo 인계 전에는 `WAITING_HANDOVER`를 유지한다.
- 비상 해제 뒤 이전 작업을 자동 재개하지 않고 복귀와 health check를 거친다.
- OMX 정밀 인계는 일반 Nav2 허용 오차보다 작은 별도 허용 오차를 사용한다.

### 6.3 SR_03 상태 공유와 통신 입력 검증

```bash
sed -n '1,240p' trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/status.py
sed -n '1,260p' trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/protocol.py
sed -n '1,260p' trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/gateway_node.py
rg -n 'StatusPolicyTest|FleetProtocolTest' trihouse_pinky/test/test_pinky_sr_policies.py
```

네트워크 메시지에 `message_id`, job/step ID, pose, map revision과 승인 주체가 있는지 확인한다.
패킷 파싱 성공과 실제 TCP 연결 성공은 다른 증거다. 현재 정적 테스트는 잘못된 패킷이 Nav2
명령이나 비상 해제로 변환되지 않는 계약을 증명한다.

### 6.4 SR_25 ETA와 복귀 판단

```bash
sed -n '1,240p' trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/eta.py
sed -n '1,160p' trihouse_pinky/test/test_eta_policy.py
```

graph ETA는 Nav2 경로가 생기기 전의 추정치다. Nav2 경로가 생기면 두 값을 더하지 않고
실제 path 기반 값으로 교체한다. 작은 ETA 변화로 OMX 준비 시각을 계속 재예약하지 않는지도
테스트한다.

### 6.5 SR_49 표시 우선순위

```bash
sed -n '1,180p' trihouse_pinky/trihouse_pinky_io/trihouse_pinky_io/indicator.py
sed -n '1,180p' trihouse_pinky/trihouse_pinky_io/trihouse_pinky_io/destination_display.py
rg -n 'IndicatorTest|DestinationDisplayTest' trihouse_pinky/test/test_pinky_sr_policies.py
```

알 수 없는 목적지 코드는 임의 문구로 표시하지 않고 화면을 비운다. 비상 표시는 사람 감지나
일반 인계 표시보다 우선한다. 실제 LCD font, LED와 buzzer는 실물 검증 항목이다.

### 6.6 launch 안전 경계

```bash
sed -n '1,220p' trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_pinky.launch.py
sed -n '1,220p' trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_pinky_sim.launch.py
sed -n '1,160p' trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_gazebo_demo.launch.py
```

실기와 simulation launch가 같은 핵심 인자를 노출하는지, Nav2 `/cmd_vel`이
`/cmd_vel_nav`로 remap되는지, Safety만 최종 `/cmd_vel`을 발행하도록 구성했는지 확인한다.
source 문자열 검사는 launch 실행 성공을 대체하지 않는다.

## 7. ROS 2·Gazebo 사전 점검

```bash
source /opt/ros/jazzy/setup.bash
echo "$ROS_DISTRO"
command -v ros2
command -v colcon
command -v gz
test -e /dev/dri && ls -l /dev/dri || echo 'GPU render device 없음'
```

현재 PC는 ROS 2 Jazzy와 Gazebo Harmonic을 사용한다. `/dev/dri`가 없으면 GUI보다 headless
서버 검증을 우선한다. ROS 환경을 source하지 않은 터미널에서는 설치되어 있어도 `ros2`를
찾지 못한다.

## 8. 현재 가능한 패키지만 빌드하기

현재 `trihouse_omx_adapter`의 package metadata 문제로 전체 통합 빌드는 차단된다. 문제를
숨기지 않기 위해 먼저 전체 명령의 실패를 확인하고 실행 기록에 남길 수 있다.

```bash
source /opt/ros/jazzy/setup.bash
cd /home/syw/Trihouse

colcon build --symlink-install \
  --packages-up-to \
    pinky_gz_sim pinky_navigation trihouse_interfaces \
    trihouse_pinky_bringup trihouse_pinky_safety \
    trihouse_pinky_fleet trihouse_omx_adapter
```

내일 시연용 부분 검증은 OMX를 제외하고 다음처럼 빌드한다.

```bash
source /opt/ros/jazzy/setup.bash
cd /home/syw/Trihouse

colcon build --symlink-install --packages-select \
  pinky_description pinky_gz_sim pinky_navigation trihouse_interfaces \
  trihouse_pinky_bringup trihouse_pinky_fleet trihouse_pinky_safety

source /home/syw/Trihouse/install/setup.bash
ros2 pkg prefix pinky_gz_sim
ros2 pkg prefix trihouse_pinky_safety
```

`--symlink-install`은 Python source와 launch 수정이 install 공간에 symlink로 반영되게 한다.
마지막 두 명령이 저장소의 `install/` 경로를 출력하면 overlay 조회가 된 것이다.

## 9. GPU 없는 PC의 headless Pinky Gazebo

다섯 터미널을 사용한다. 모든 터미널에서 먼저 ROS 환경과 domain을 동일하게 설정한다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/syw/Trihouse/install/setup.bash
export ROS_DOMAIN_ID=52
```

### 터미널 1: Gazebo physics·sensor 서버

```bash
export GZ_SIM_RESOURCE_PATH="$(ros2 pkg prefix pinky_description)/share:$(ros2 pkg prefix pinky_gz_sim)/share/pinky_gz_sim/models:$HOME/.gazebo/models"
export GZ_SIM_SYSTEM_PLUGIN_PATH="$(ros2 pkg prefix pinky_gz_sim)/lib"
unset DISPLAY

gz sim -r -s -v4 --headless-rendering \
  "$(ros2 pkg prefix pinky_gz_sim)/share/pinky_gz_sim/worlds/pinky_factory.world"
```

- `-r`: world를 일시정지하지 않고 실행한다.
- `-s`: GUI 없이 server만 실행한다.
- `--headless-rendering`: camera와 GPU LiDAR용 EGL rendering을 사용한다.
- resource path가 틀리면 `model://pinky_description/...` mesh를 찾지 못한다.

### 터미널 2: Pinky robot description

```bash
ros2 launch pinky_description upload_robot.launch.py \
  use_sim_time:=True is_sim:=True
```

이 터미널은 `robot_description`, TF와 joint 상태의 기준 모델을 유지하므로 종료하지 않는다.

### 터미널 3: 모델 생성과 ROS bridge

```bash
ros2 run ros_gz_sim create \
  -name pinky -topic /robot_description \
  -x 0.0 -y 0.0 -z 0.1

ros2 run ros_gz_bridge parameter_bridge --ros-args \
  -p config_file:="$(ros2 pkg prefix pinky_gz_sim)/share/pinky_gz_sim/params/pinky_bridge.yaml"
```

첫 명령이 `Entity creation successful`로 끝난 뒤 두 번째 명령을 실행한다. bridge는
`/scan`, `/odom`, `/cmd_vel`, `/clock`, TF를 Gazebo와 ROS 사이에 연결한다.

### 터미널 4: 모의 하드웨어

```bash
ros2 run trihouse_pinky_bringup sim_hardware --ros-args \
  -p use_sim_time:=true
```

Gazebo에 없는 Pinky 초음파와 배터리 입력을 명시적인 simulation 값으로 발행한다.

### 터미널 5: Safety Supervisor

```bash
ros2 run trihouse_pinky_safety safety_supervisor --ros-args \
  -p robot_id:=PK-01 -p use_sim_time:=true
```

## 10. Gazebo 관찰과 Safety 시나리오

새 여섯 번째 터미널에서 공통 ROS 환경을 source한 뒤 실행한다.

```bash
ros2 topic list -t
ros2 topic echo /scan --once
ros2 topic echo /odom --once
ros2 node info /safety_supervisor
```

관제 연결 전에는 `/cmd_vel_nav`을 보내도 최종 속도가 0이어야 한다.

```bash
ros2 topic pub -1 /cmd_vel_nav geometry_msgs/msg/Twist \
  '{linear: {x: 0.01}, angular: {z: 0.0}}'

ros2 topic echo /cmd_vel --once
ros2 topic echo /trihouse/safety/state --once
```

기대값은 `/cmd_vel.linear.x: 0.0`, `detail: control_link_lost`다. 다음으로 테스트용
관제 ONLINE 상태를 보내고 작은 속도를 다시 입력한다.

```bash
ros2 topic pub -1 /trihouse/fms/state \
  trihouse_interfaces/msg/ConnectionState \
  '{robot_id: PK-01, session_id: demo, state: 2, detail: online}'

ros2 topic pub -1 /cmd_vel_nav geometry_msgs/msg/Twist \
  '{linear: {x: 0.01}, angular: {z: 0.0}}'

ros2 topic echo /cmd_vel --once
ros2 topic echo /trihouse/safety/state --once
```

장애물이 감속 거리 안에 있으면 `protective_zone`과 0.01 m/s가 보인다. 정지 거리 안이면
정상적으로 `front_stop`과 0이 나온다. 마지막으로 비상 latch를 확인한다.

```bash
ros2 topic pub -1 /trihouse/safety/emergency_request \
  std_msgs/msg/Bool '{data: true}'

ros2 topic echo /cmd_vel --once
ros2 topic echo /trihouse/safety/state --once
```

기대값은 속도 0, `state: 3`, `latched: true`, `detail: emergency_latched`다.

## 11. 종료 순서

비상 상태에서 속도가 0인 것을 확인한 뒤 다음 순서로 각 실행 터미널에서 Ctrl+C를 누른다.

1. Safety Supervisor
2. sim hardware
3. ROS bridge
4. robot description
5. Gazebo server

현재 Python ROS 노드는 Ctrl+C 때 `rcl_shutdown already called` traceback을 남길 수 있다.
프로세스는 종료되지만 시연 화면에는 보이지 않도록 종료 터미널을 분리한다. 잔류 여부는 다음으로
확인한다.

```bash
ps -eo pid,args | rg 'gz sim|ros_gz_bridge|safety_supervisor|sim_hardware' \
  | rg -v 'rg '
```

출력이 없으면 종료된 것이다.

## 12. 결과를 읽는 기준

| 항목 | PASS 기준 | 현재 증거 등급 |
| --- | --- | --- |
| 정적 정책 | 34 tests passed | `static` |
| Python source | compileall 종료 코드 0 | `static` |
| Gazebo model | entity creation successful | `simulation` |
| 센서 | `/scan`, `/odom` 1개 이상 수신 | `simulation` |
| 구동 | odometry 위치 변화와 정지 속도 0 | `simulation` |
| 관제 단절 | `control_link_lost`, 최종 속도 0 | `simulation` |
| 정상 감속 | `protective_zone`, 제한된 양의 속도 | `simulation` |
| 비상 latch | `emergency_latched`, 최종 속도 0 | `simulation` |
| Nav2 목표 | `navigate_to_pose` goal 완료 | 아직 미검증 |
| OMX 인계 | cargo lock/unlock과 handover 상태 | 아직 미검증 |
| GUI | Gazebo 3D 창 또는 서버 PC 화면 | 현재 PC 차단 |

오늘 실제 실행 결과와 차단점은
[`runs/2026_08_10_pinky_demo_validation.md`](runs/2026_08_10_pinky_demo_validation.md)에 기록한다.
