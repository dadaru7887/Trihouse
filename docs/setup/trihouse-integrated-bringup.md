# Trihouse Pinky·OMX 통합 bringup 및 검증 안내

이 문서는 `pinky_pro`와 `control_system/`을 수정하지 않는 overlay 실행 절차다. 첫 시작점은
`trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_gazebo_demo.launch.py`이며, 이 파일이
Pinky Gazebo/Navigation, mock sensor, Safety Supervisor, fleet gateway, Gazebo OMX adapter를
`trihouse_pinky_sim.launch.py`로 포함한다. 관제 화면은 별도 프로세스로
`control_tower/gateway/http_server.py`가 제공하는 Gateway read model만 읽는다.

## 1. 공통 작업 상태와 소유 경계

| 상태/사실 | 소유 코드 | 다음 단계 조건 |
| --- | --- | --- |
| `PENDING → RESERVED → PICKING` | `control_tower/task_manager/transport_job.py`, inventory/OMX workflow | 관제 예약과 OMX pick 결과 |
| `PINKY_TO_STATION → HANDOVER_READY` | Pinky fleet, `handover_gate.py` | Pinky 정차와 Pinky·OMX readiness 동시 확인 |
| `LOADING → LOADED` | OMX adapter + `transport_job.py` | OMX 성공만으로는 불가. gripper open, 안전 후퇴, cargo lock/load-cell 확인 필요 |
| `DELIVERING → UNLOADING → COMPLETED` | Pinky fleet + OMX adapter + inventory result | 목적지 정차 뒤 하차 물리 확인; 재고는 최종 완료 시 한 번만 변경 |
| `FAILED`, `HELD`, `EMERGENCY`, `RECOVERY`, `REASSIGNED` | Control Tower task manager | 운영자 결정/재배정만 허용; 비상 해제만으로 기존 작업 재개 금지 |

`ProtocolEnvelope`는 모든 관제 명령/결과에 `schema_version`, `message_id`, `type`,
`sent_at`, `robot_id`, `job_id`, `order_id`, `job_step_id`를 요구한다. `message_id`는 한 번만
처리하며, `LinkReconciler`는 단절 당시의 job/phase/checkpoint가 관제 값과 모두 같을 때만
재연결을 연다.

## 2. Gazebo 통합 시연

ROS 2 Jazzy와 vendor packages를 이미 build/source한 Ubuntu shell에서 실행한다. 현재 macOS
개발 환경에는 ROS/Gazebo가 없으므로 아래 명령은 여기서 실행하지 않았다.

```bash
cd /path/to/Trihouse
source /opt/ros/jazzy/setup.bash
colcon build --packages-select trihouse_interfaces trihouse_pinky_bringup trihouse_pinky_fleet trihouse_pinky_safety trihouse_pinky_io trihouse_omx_adapter
source install/setup.bash

# 터미널 1: Pinky, Nav2, mock ultrasonic/battery/cargo, Gazebo OMX
ros2 launch trihouse_pinky_bringup trihouse_gazebo_demo.launch.py \
  robot_id:=PK-01 map_revision:=demo-1 map:=/absolute/path/to/map.yaml \
  control_host:=127.0.0.1 control_port:=8788 omx_station_id:=OMX-01

# 터미널 2: 별도 Trihouse 관제 UI (RoboSapiens 원본은 시작하거나 수정하지 않음)
python3 -m http.server 8088 --directory control_tower/ui/operations
```

두 번째 명령은 정적 UI preview다. 실제 Gateway HTTP adapter는 `OperationsHttpServer`를
애플리케이션 process로 띄워야 하며, 운영 배포의 인증·지속 WebSocket fan-out은 아직 구현 전이다.
따라서 이 환경에서 UI↔실제 TCP 8788 job dispatch까지 성공했다고 주장하지 않는다.

관찰 기준:

```bash
ros2 topic echo /trihouse/readiness
ros2 topic echo /trihouse/safety/state
ros2 topic echo /trihouse/cargo/state
ros2 topic echo /trihouse/handover/state
ros2 topic echo /trihouse/status
ros2 topic info /cmd_vel -v
```

- 성공: readiness가 READY이고 `/cmd_vel` publisher가 Safety Supervisor 하나이며, mock cargo를
  확인한 경우에만 `CargoState.STATE_LOCKED`가 된다.
- handover 거절: OMX mock confirmation을 끈 상태에서 cargo lock 없는 출발이 거절된다.
- 비상: `/trihouse/safety/emergency_request` 또는 keep-out/근접 센서 입력 뒤 `/cmd_vel`이 0이며,
  OMX는 `HELD`/`EMERGENCY`로 남는다.
- 통신 단절: `/trihouse/fms/state`가 OFFLINE이면 Safety Supervisor가 `control_link_lost` STOP을
  발행한다. link가 ONLINE이 되어도 작업 state/checkpoint reconciliation 전에는 재개하지 않는다.

Gazebo 로그는 ROS launch stdout와 `~/.ros/log/`에 남는다. STOP이 아닌 속도가 나오거나
`/cmd_vel` publisher가 둘 이상이면 즉시 launch를 종료하고 모터/시뮬레이터를 정지한다.

## 3. 실제 Pinky Pro + OMX bringup

```bash
cd /path/to/Trihouse
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  robot_id:=PK-01 map_revision:=warehouse-2026-08 map:=/absolute/path/to/map.yaml \
  control_host:=CONTROL_TOWER_HOST control_port:=8788 omx_station_id:=OMX-01 \
  vision_enabled:=false docking_enabled:=false
```

실기 launch는 vendor `pinky_bringup/bringup_robot.launch.xml`, IMU/ultrasonic node, Nav2,
Safety Supervisor, readiness, fleet/gateway를 조합한다. OMX는 endpoint가 저장소에서 확인되지
않았으므로 `hardware_omx_adapter`가 **motion을 보내지 않는 진단 skeleton**으로만 시작한다.
실제 MoveIt/gripper endpoint, TF frame, joint state, gripper/stop acknowledgement, payload 및
workspace limit이 승인되기 전에는 hardware plugin을 추가하거나 motion을 켜지 않는다.

## 4. 실기 연결 전 필수 점검·중단·rollback

```bash
ros2 node list
ros2 topic hz /scan
ros2 topic hz /odom
ros2 topic echo /tf --once
ros2 topic echo /imu_raw --once
ros2 topic echo /trihouse/battery --once
ros2 topic echo /trihouse/proximity/front --once
ros2 topic echo /trihouse/cargo/state --once
ros2 action list | rg navigate_to_pose
ros2 lifecycle nodes
ros2 topic info /cmd_vel -v
```

시작 전에는 map revision/AMCL pose, Nav2 lifecycle, E-stop acknowledgement, OMX stop acknowledgement,
payload/workspace limit, cargo sensor를 각각 확인한다. 센서 stale, 두 개 이상의 `/cmd_vel`
publisher, E-stop/OMX stop acknowledgement 실패, 사람 진입, 예상 밖 motion이 하나라도 있으면
즉시 Nav2 goal을 취소하고 인증된 E-stop을 사용한다. 소프트웨어 safety는 전기 안전 시스템을
대체하지 않는다. rollback은 Trihouse launch를 종료하고 vendor 기본 bringup만으로 센서/모터를
재검증한 뒤 overlay parameters와 hardware endpoint 계약을 되돌려 검토하는 방식이다.

## 5. 자동 테스트와 실행 경계

```bash
cd /path/to/Trihouse
PYTHONPATH='trihouse_pinky/trihouse_pinky_fleet:trihouse_pinky/trihouse_pinky_safety:trihouse_pinky/trihouse_pinky_io:trihouse_pinky/trihouse_pinky_bringup' \
python3 -m unittest -v \
  control_tower.tests.test_transport_job_contract \
  trihouse_omx_adapter.tests.test_omx_adapter_policy \
  trihouse_pinky.test.test_integrated_bringup_contract \
  trihouse_pinky.test.test_pinky_sr_policies
python3 -m compileall -q control_tower trihouse_pinky trihouse_omx_adapter vision_system
git diff --check
```

이 테스트는 상태 순서, 중복 message, physical cargo gate, OMX timeout/비상 hold, link loss STOP,
launch 공통 parameter를 검증한다. ROS graph, Gazebo world, real OMX motion, UI TCP dispatch는
이 macOS 환경에서 실행하지 않았으며 위 Ubuntu 절차로 별도 검증해야 한다.

## 6. 자동화하지 않은 안전 결정

- 사람 쓰러짐 감지는 `docs/scenario/sr52-fall-detection-research-plan.md`의 조사 단계다. 감지
  모델/테스트를 추가하지 않았으며, 승인된 Control Tower emergency 요청만 Pinky latch로 연결한다.
- emergency clear는 작업 자동 재개가 아니다. recovery health/cargo 상태에 따라 `RECOVERY`,
  `HELD`, 재배정 또는 수동 인계로 가야 한다.
- OMX 실기 motion, gripper/stop topic과 hardware E-stop은 endpoint 계약과 안전 책임자 승인 전
  추측·자동화하지 않는다.
