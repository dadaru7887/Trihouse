# 2026-08-10 Pinky 시연 준비 검증 기록

## 실행 정보

| 항목 | 값 |
| --- | --- |
| 결과 범주 | `static`, `simulation`, `blocked` |
| Git commit | `4adda333dddb` |
| 브랜치 | `feat/pinky-edge-agent` |
| 운영체제 | Ubuntu 24.04.4 LTS, amd64 |
| ROS | ROS 2 Jazzy |
| Gazebo | Gazebo Sim 8.11.0, Harmonic 계열 |
| ROS domain | 51 |
| GPU | `nvidia-smi` 없음, `/dev/dri` 없음 |
| simulation world | `pinky_factory.world` |
| RMF map | 사용하지 않음 |

이 기록은 Pinky 단독 headless simulation 결과다. `robosapiens.world`, Open-RMF,
Control System UI, Nav2 목표 완료와 OMX 인계는 이번 실행에 포함하지 않았다.

## 결과 요약

| 검증 | 결과 | 실제 관찰 |
| --- | --- | --- |
| Pinky SR pytest | PASS | 34개 수집, 34개 통과, 0.05초 |
| Python compileall | PASS | 종료 코드 0 |
| 전체 대상 colcon build | BLOCKED | OMX adapter가 catkin으로 분류되어 CMakeLists.txt 탐색 실패 |
| OMX 제외 colcon build | PASS | Gazebo, Nav2, interface, Pinky bringup/fleet/safety 빌드 |
| Gazebo GUI | BLOCKED | OpenGL/EGL context 실패 뒤 GUI와 server exit 139 |
| Gazebo headless server | PASS | physics와 OGRE2 sensor rendering thread 초기화 |
| Pinky entity 생성 | PASS | `Entity creation successful` |
| ROS bridge | PASS | `/scan`, `/odom`, `/cmd_vel`, `/clock`, TF 생성 |
| LiDAR | PASS | `rplidar_link`, 범위 0.05~12.0 m 메시지 수신 |
| odometry | PASS | `odom` → `base_footprint` 메시지 수신 |
| 벤더 구동계 | PASS | x≈0에서 x≈1.13 m로 위치 변화, 정지 뒤 선·각속도 0 |
| 관제 단절 안전 정지 | PASS | `control_link_lost`, 최종 `/cmd_vel` 0 |
| 정상 연결 감속 | PASS | `protective_zone`, 최종 선속도 0.01 m/s |
| 비상 latch | PASS | `emergency_latched`, `latched: true`, 최종 속도 0 |

headless simulation의 real-time factor가 1보다 커서 벽시계 2초와 simulation 이동 거리는
일치하지 않았다. 이동 검증은 실행 시간 추정이 아니라 odometry의 위치 변화와 정지 속도로
판정했다.

## 실행한 정적 명령

```bash
PYTHONPATH='trihouse_pinky/trihouse_pinky_fleet:trihouse_pinky/trihouse_pinky_safety:trihouse_pinky/trihouse_pinky_io:trihouse_pinky/trihouse_pinky_bringup' \
python3 -m pytest -v \
  trihouse_pinky/test/test_pinky_sr_policies.py \
  trihouse_pinky/test/test_eta_policy.py \
  trihouse_pinky/test/test_integrated_bringup_contract.py

python3 -m compileall -q trihouse_pinky
```

## 문제와 다음 조치

### DEMO-PINKY-001: OMX adapter build type 누락

- 증상: colcon이 `trihouse_omx_adapter`를 `(ros.catkin)`으로 표시하고 CMakeLists.txt를 찾는다.
- 직접 원인: `trihouse_omx_adapter/package.xml`에 `<export><build_type>ament_python</build_type></export>`가 없다.
- 영향: `trihouse_gazebo_demo.launch.py`가 OMX node를 요구하므로 전체 통합 build/launch가 차단된다.
- 내일 우회: OMX를 제외한 Pinky Gazebo·Safety 부분 검증만 표시한다.
- 후속 조치: package metadata 수정과 adapter 단독 colcon build test를 별도 변경으로 수행한다.

### DEMO-PINKY-002: GPU 없는 PC에서 Gazebo GUI 종료

- 증상: `QOpenGLContext`, EGL/GLX 초기화 실패 뒤 exit code 139가 발생한다.
- 직접 원인: 현재 PC에 NVIDIA GPU와 `/dev/dri` render device가 없다.
- 영향: 현재 PC에서 3D Gazebo 창을 시연할 수 없다.
- 우회 확인: `gz sim -s --headless-rendering`은 physics와 sensor rendering을 실행했다.
- 내일 조치: GPU 서버에서는 GUI launch를 재검증하고, 실패하면 headless 토픽 증거를 사용한다.

### DEMO-PINKY-003: rosdep의 ament_python 해석 실패

- 증상: `rosdep check`가 여러 Python package의 `ament_python` definition을 찾지 못해 종료 코드 2를 반환한다.
- 관찰: ROS 2 Python package의 실제 colcon build는 성공했다.
- 영향: rosdep 결과만으로 설치 실패라고 판정할 수 없다.
- 후속 조치: 서버의 rosdep source 갱신 상태를 확인하고 package metadata/rosdep key 정책을 정리한다.

### DEMO-PINKY-004: Python ROS node Ctrl+C traceback

- 증상: `safety_supervisor`와 `sim_hardware` 종료 때 `rcl_shutdown already called`가 출력된다.
- 직접 원인 후보: SIGINT로 context가 이미 종료된 뒤 `finally`에서 `rclpy.shutdown()`을 다시 호출한다.
- 영향: 프로세스는 종료되지만 시연 터미널에 실패처럼 보이는 traceback이 남는다.
- 내일 우회: 실행 터미널과 발표 화면을 분리하고 종료는 시연 뒤 수행한다.
- 후속 조치: context 상태를 확인하는 공통 종료 helper와 노드 종료 test를 추가한다.

### DEMO-PINKY-005: bringup README 상태가 source와 다름

- 증상: bringup README는 “README만 존재”한다고 적지만 launch와 node source가 존재한다.
- 영향: 구현 완료 범위를 잘못 설명할 수 있다.
- 내일 우회: `pinky_sr_audit.md`와 이 실행 기록을 기준으로 설명한다.
- 후속 조치: build metadata 문제를 해결한 뒤 README의 상태와 완료 조건을 갱신한다.

### DEMO-PINKY-006: 수동 headless 실행의 Gazebo resource path

- 증상: resource path가 install root만 가리키면 Pinky mesh와 lamp system plugin을 찾지 못한다.
- 영향: 센서와 DiffDrive가 동작해도 visual/collision 자산 일부가 누락된 불완전 simulation이 된다.
- 해결 명령: `pinky_description/share`를 `GZ_SIM_RESOURCE_PATH`에, `pinky_gz_sim/lib`를
  `GZ_SIM_SYSTEM_PLUGIN_PATH`에 추가한다.
- 기준: 수동 절차 문서의 터미널 1 명령을 사용한다.

### DEMO-PINKY-007: 아직 실행하지 않은 통합 범위

- Nav2 `NavigateToPose` 목표 완료와 map localization
- `trihouse_omx_adapter` cargo lock/unlock 및 handover
- FMS Gateway TCP 8788 연결과 heartbeat
- Open-RMF `robosapiens.world` 및 Control System UI 연동
- 실물 Pinky LCD, LED, buzzer, 초음파 임계값과 정차 오차

위 항목은 이번 결과를 근거로 완료 표시하지 않는다.

### DEMO-PINKY-008: SR_03 RobotStatus 직렬화 타입 불일치

- 증상: `RobotStatus.battery_policy`에 숫자를 대입한 메시지를 직렬화하면 assertion과 함께
  프로세스가 종료 코드 134로 중단된다.
- 직접 원인: `status_node.py`에서 `BatteryPolicyState` 타입 필드에 배터리 percentage용
  `float`인 `self.battery`를 대입한다.
- 재현 경계: 단순 Python 대입은 허용되지만 `rclpy.serialization.serialize_message()`에서
  ROS 메시지 타입 검사가 실패한다.
- 영향: 순수 `StatusPolicyTest` 통과와 별개로 `/trihouse/status` heartbeat를 실제 발행할 수
  없으므로 SR_03을 완료로 판정할 수 없다.
- 후속 조치: 실패하는 node/message test를 먼저 추가한 뒤 올바른 `BatteryPolicyState` 객체를
  대입하고, 1초 주기·상태 변경 즉시 발행·TCP 전송을 순서대로 재검증한다.

### DEMO-PINKY-009: SR_03 FMS 상태 전송 경계 미완성

- ROS 내부 상태: `RobotStatus.msg`에는 pose, twist, navigation state, progress, battery,
  cargo, safety, job/step과 오류가 정의되어 있다.
- gateway 손실: `gateway_node.py::_status()`의 NDJSON에는 pose·방향, twist·navigation state,
  progress와 battery policy가 포함되지 않는다.
- Control Tower 수신 손실: TCP 8788에서 `robot_status`를 수신하고 `RobotSnapshot`과
  `RobotView`를 갱신하는 server/adapter가 현재 저장소에 없다.
- 배정 정책: `DispatchWorkflow.assign()`은 `ready=False` robot을 후보에서 제외하지만, 이
  정책에 실제 Pinky status를 공급하는 연결이 없어 end-to-end 증거는 아니다.
- 영향: SR_03의 ROS 메시지 계약과 배차 단위 정책은 부분 구현됐지만, FMS 및 관제 UI까지의
  상태 공유 기능은 완료되지 않았다.
- 후속 조치: 직렬화 결함 수정 후 status payload 계약 테스트, TCP 수신 adapter,
  `DispatchWorkflow`·`OperationsFeed` 반영 및 UI 표시 통합 테스트를 순서대로 추가한다.

## 내일 발표용 표현

```text
정적 정책: 34/34 PASS
Pinky Gazebo: headless 모델·LiDAR·odometry·구동 PASS
Safety: 관제 단절·보호구역·비상 latch PASS
통합 launch: OMX package metadata와 GPU GUI 문제로 부분 차단
Nav2·OMX·Open-RMF 통합: 아직 미검증
```
