# Pinky Gazebo·실기 안전 주행 검증 설계

## 목적

오늘부터 내일 오전까지 Gazebo에서 Pinky의 기본 경로 주행과 안전·오류 흐름을 검증하고,
내일 오후에는 같은 ROS 계약과 업무 노드를 실제 Pinky에서 저속으로 검증한다. Gazebo와 실기의
차이는 센서·odometry·모터 입력 계층으로 제한하며, Fleet, Gateway, Safety, Status 노드는 동일하게
사용한다.

이번 범위에는 이미 발견된 `RobotStatus` 타입 오류, 사람 감지 Safety 연결 오류, 상태 Topic QoS
불일치의 수정과 회귀 테스트 계획이 포함된다. Vision 모델 정확도와 SR_52 쓰러짐 감지는 포함하지
않는다.

## 권한과 통합 경계

```text
control_system
  ├─ 지도 waypoint/lane 및 기본 경로 입력
  └─ 기존 관제 화면과 자체 robot_link 상태 표시

control_tower
  ├─ 작업 배정, 배터리 정책, 공간 예약
  ├─ 비상 구역, 작업 보류, 복귀 결정
  └─ Pinky용 execute_transport/keep-out/emergency 명령 생성

Pinky onboard
  ├─ gateway: 외부 NDJSON ↔ ROS 변환
  ├─ fleet: ExecuteTransport ↔ Nav2
  ├─ safety: 최종 /cmd_vel 단일 소유
  └─ status: RobotStatus/TaskEvent/RobotHealth 회신
```

`control_system/robo_control`의 TCP 8788은 `hello`, `telemetry`, `path`, `hold`, `speed` 형식을
사용하고, Trihouse Pinky Gateway는 `execute_transport`, `robot_status`, `task_event` 형식을
사용한다. 따라서 기존 코드가 있다고 해서 두 시스템의 통합이 끝난 것으로 판정하지 않는다.
내일은 `control_system`을 변경하지 않고, 이미 구현된 지도·경로·화면 기능을 기준 또는 시연 화면으로
사용한다. Control Tower가 업무·안전 결정의 단일 권한자이며, Safety Supervisor가 실제 모터 속도의
최종 권한자다.

## 내일 검증할 SR 범위

표의 `control_system 자체 구현 완료`는 기존 RoboSapiens 내부 모델과 자체 TCP 프로토콜에서 기능이
존재한다는 뜻이다. Trihouse Pinky/Control Tower 계약과 실제 연결까지 완료됐다는 뜻은 아니다.

| SR | 내일 확인할 기능 | control_system 현재 상태 | Trihouse/Pinky 현재 판정과 내일 목표 |
| --- | --- | --- | --- |
| SR_03 | 1초 RobotStatus heartbeat와 상태 변경 즉시 보고 | telemetry·battery·속도·작업 표시 자체 구현 완료 | `status_node → gateway_node` 실제 직렬화와 TCP 전달 검증 |
| SR_07·08·09 | 작업 배정, 경로·공간 예약, 재배정 | waypoint/lane 지도, 경로 계산·전송, hold 자체 구현 완료 | Control Tower 정책은 정적 구현; Pinky action/새 목표 연결 검증 |
| SR_41 | 긴급 작업 우선순위 | task 화면과 자체 FleetEngine 작업 관리 구현 완료 | Control Tower 우선순위 정책 테스트만 확인; 실기 강제 선점 제외 |
| SR_23 | 거리·사람·timeout 기반 최종 감속·정지 | speed/hold 명령과 incident 화면 자체 구현 완료 | Safety 입력 wiring 수정 후 `/cmd_vel` 단일 발행과 정지 검증 |
| SR_24 | 운반 수락, Nav2 이동, 정차·도착 보고 | 경로 전송·로봇 이동 표시 자체 구현 완료 | ExecuteTransport → Nav2 → WAITING_HANDOVER 검증 |
| SR_25 | 대기·충전 위치 복귀 | charger/holding station과 charge 명령 자체 구현 완료 | 지정 waypoint 복귀까지만 검증; 물리 충전 접촉 제외 |
| SR_27 | 배터리 기반 새 작업 제한·복귀 | battery 표시와 charging 상태 자체 구현 완료 | Control Tower 배터리 정책 → Pinky return mode 연결 검증 |
| SR_45 | 포장대 부재 시 대기·재배정 | workstation 및 작업 경로 모델 자체 구현 완료 | 같은 job/cargo를 유지한 새 목적지 action 검증 |
| SR_48 | 포장대·작업자 위치까지 운반 | workstation 목적지와 경로 표시 자체 구현 완료 | 적재 확인 후 출발, 지정 방향 정차 검증 |
| SR_49 | 도착 후 인계 대기 표시 | 작업·로봇 상태 화면 자체 구현 완료 | Pinky LCD/LED 상태와 비상 우선순위 검증 |
| SR_54 | 비상 구역, 접근 제한, 로봇 정지 | incident 표시와 hold/speed 명령 자체 구현 완료 | keep-out polygon, emergency latch, Safety 정지 검증 |
| SR_55 | 영향 작업 보류·재할당 | 자체 task/incident lifecycle 일부 구현 | Control Tower checkpoint 기반 보류 판정까지만 검증 |
| SR_56 | 관리자 비상 해제 승인 | incident 해제 UI 자체 구현 완료 | Trihouse 관리자 권한·감사·ClearEmergency 연결 검증 |
| SR_57 | 해제 후 복귀·상태 점검·재투입 | returning/charging 상태 표시 자체 구현 완료 | 복귀 후 센서·통신·battery·cargo health gate 검증 |
| SR_19·20·44 | 사람 관측을 Pinky Safety 입력으로 연결 | 기존 UI 표시가 있어도 Trihouse YOLO 계약 완료로 보지 않음 | SR_20의 Pinky Safety wiring만 검증; 모델 정확도·OMX·포장 ROI 제외 |

## 수정 대상 결함

### RobotStatus 타입

`status_node.py`는 `RobotStatus.battery_policy`에 `float` 배터리 값을 대입하지 않고 구독한
`BatteryPolicyState` 메시지를 대입해야 한다. 실제 생성된 ROS 메시지로 publish가 성공하고 Gateway가
NDJSON으로 변환하는 테스트가 필요하다.

### 사람 감지 Safety 연결

`safety_supervisor_node.py`가 계산한 TTL 내 `person_detected` 값을 `SafetyInputs`에 그대로 전달해야
한다. 보호 거리 안의 사람은 목표를 취소하지 않고 최종 `/cmd_vel`을 0으로 제한하며, TTL 만료와 거리
센서 안전 조건 충족 뒤 다시 Nav2 명령을 통과시켜야 한다.

### 상태 Topic QoS

`ConnectionState`, `IndicatorState`, `Readiness`, `RobotHealth`, `SafetyState`, `KeepOutZone`,
`CargoState`와 배터리 정책 상태는 카탈로그대로 RELIABLE + TRANSIENT_LOCAL, depth 1을 사용한다.
늦게 시작한 subscriber가 마지막 상태를 즉시 받는 launch test를 둔다.

## 동일한 Gazebo·실기 데이터 흐름

```text
Control Tower 결정
  → TCP NDJSON
  → gateway_node
  → ExecuteTransport / emergency / keep-out / clear-emergency
  → fleet_node 또는 safety_supervisor_node
  → NavigateToPose
  → /cmd_vel_nav
  → Safety Supervisor
  → /cmd_vel
  → Gazebo DiffDrive 또는 Pinky 실제 motor driver

센서·주행·오류 상태
  → SafetyState / NavigationState / RobotHealth / TaskEvent / RobotStatus
  → gateway_node
  → Control Tower
  → 보류·새 목적지·복귀 결정
```

Gazebo에서는 `/scan`, `/odom`, battery, proximity, cargo, person detection을 시뮬레이션하거나 오류
주입한다. 실기에서는 같은 Topic 이름과 타입을 실제 `pinky_pro` adapter가 발행한다. 두 환경 모두
Nav2의 출력은 `/cmd_vel_nav`로 remap하고, 실제 `/cmd_vel` 발행자는 Safety Supervisor 하나만 둔다.

## 포장대·적재 위치 좌표 규칙

### 기본 이동 목표는 4점이 아니라 한 개의 pose다

Pinky가 포장대나 적재 위치로 이동할 때 Nav2에 주는 목표는 지도 `map` frame의 한 개 pose다.

```text
(x, y, yaw)
```

- `x`, `y`: 정차했을 때 로봇의 `base_link` 원점이 위치할 지도 좌표
- `yaw`: 포장대·선반을 바라보는 최종 방향
- ROS 표현: `geometry_msgs/PoseStamped`; yaw는 quaternion으로 변환
- `frame_id`: `map`

`base_link`는 보통 로봇 회전 중심 또는 구동축 중심에 정의된다. 따라서 지도에 찍는 한 점은 로봇
외곽의 앞 모서리가 아니라 `base_link`가 도착할 점이다. 로봇 앞면과 포장대 사이의 실제 거리는
로봇 footprint와 필요한 작업 간격을 이용해 뒤로 offset한 좌표로 정한다.

### 두 단계 도킹

포장대나 선반에서 정밀 정차가 필요하면 좌표를 다음처럼 나눈다.

1. `pre-dock pose`: Nav2가 이동할 안전한 한 개 `(x, y, yaw)` waypoint
2. `dock target_offset`: 마커 기준으로 최종 `base_link`가 있어야 할 상대 pose

예를 들어 선반 전면 ArUco marker를 기준으로 로봇 중심이 0.55 m 앞에 있고 정면을 바라봐야 한다면,
카메라·마커 frame 정의를 확인한 뒤 `Dock.action.target_offset`에 그 상대 거리와 방향을 설정한다.
정확한 부호는 TF tree의 marker 축 방향을 보고 결정해야 하며 고정 숫자를 추측하지 않는다.

현재 `trihouse_pinky_docking`은 README와 `Dock.action` 계약만 있고 action server는 구현되지 않았다.
따라서 내일 필수 완료 조건은 Nav2의 한 개 pose에 저속으로 정차하는 것이다. 이 필수 검증이 모두
통과하고 시간이 남으면 마지막 stretch task로 ArUco marker를 보고 정렬한 뒤 협로 입구의 지정
offset까지 저속 진입한다. 마커 freshness·ID·신뢰도가 유효하지 않거나 관측이 소실되면 즉시
`/cmd_vel_dock`을 0으로 만들고 제한된 재탐색 후 실패해야 한다.

협로 진입 stretch task의 성공 기준은 marker 기준 목표 pose 허용 오차에 정지하는 것까지다. 협로
내부의 장거리 자율주행, 반대편 이탈, OMX 정밀 인계와 자동 충전 접촉은 포함하지 않는다.

### 4점을 사용하는 경우

4개 이상의 점은 목표 pose가 아니라 다음 영역 표현에 사용한다.

- 로봇이 들어가면 안 되는 keep-out polygon
- 포장대·선반의 물리 점유 영역
- 작업자/OMX 안전 ROI
- 정차 허용 구역을 면적으로 검사할 때의 polygon

경로 계획에는 로봇 footprint polygon도 필요하지만, 이는 Nav2 costmap 설정이며 매 목표마다 4점을
보내는 값이 아니다.

## 디버깅과 관측

ML/DL 코드에서 입력 tensor, 중간 activation, output, metric을 보는 것처럼 ROS에서는 다음 계층을
관찰한다.

| ML/DL 관점 | Pinky 관점 |
| --- | --- |
| 입력 batch | `/scan`, proximity, person detection, odometry, FMS connection |
| 중간 activation | `Readiness`, `SafetyState`, `NavigationState`, workflow phase |
| output | `/cmd_vel`, `RobotStatus`, `TaskEvent` |
| metric | 정지 지연, 최소 거리, pose 오차, heartbeat 간격, action 결과 |
| 재현 dataset | rosbag2와 Control Tower NDJSON log |

Gazebo와 실기에서 같은 rosbag Topic 집합을 기록한다. 실기는 첫 실행부터 저속 상한, 물리 비상 정지
담당자, 충분한 정지 공간을 전제로 한다. 센서 timeout, 관제 단절, 사람 보호 거리, keep-out,
emergency latch를 한 번에 섞지 않고 한 시나리오씩 주입해 최초로 기대와 달라지는 경계를 찾는다.

## 성공 기준

- 생성된 ROS 메시지로 `RobotStatus` publish와 Gateway 직렬화가 예외 없이 동작한다.
- 사람 보호 거리와 stale sensor에서 Nav2 목표는 유지되고 `/cmd_vel`만 0이 된다.
- 늦게 시작한 상태 subscriber가 TRANSIENT_LOCAL의 마지막 값을 받는다.
- Gazebo와 실기 모두 `/cmd_vel` publisher가 Safety Supervisor 하나다.
- 정상 경로 한 건이 ExecuteTransport 수락부터 도착·정차·상태 회신까지 이어진다.
- emergency/keep-out에서 정지하고 승인 전 자동 재개하지 않는다.
- 해제 후 기존 작업을 자동 재개하지 않고 지정 대기·충전 pose로 복귀해 health check를 수행한다.
- 실기 검증은 저속으로 수행하고 rosbag, node log, Control Tower message ID를 같은 run 기록에 남긴다.
- 필수 항목 통과 후에만 ArUco marker 정렬·협로 입구 진입을 수행하며, marker 소실 시 즉시 정지한다.

## 제외 범위

- `control_system` 원본 Dart/Flutter 코드 수정
- 두 TCP 8788 프로토콜의 운영 adapter 구현
- Vision 모델 학습·정확도 평가와 SR_52
- OMX/MoveIt 실물 동작
- 물리 충전 단자 정렬과 충전 시작
- 협로 내부 장거리 주행, 반대편 이탈과 OMX/충전 접촉까지 포함한 완전 자동 도킹
