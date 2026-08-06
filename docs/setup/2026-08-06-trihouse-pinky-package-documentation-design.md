# Trihouse Pinky 패키지 문서 구조 설계

## 1. 목적

주행 로봇 기능을 기존 벤더 코드인 `pinky_pro`와 분리해 단계적으로 구현할 수 있도록, 저장소 루트에 Trihouse 전용 ROS 2 패키지 폴더 구조와 구현 안내 문서를 먼저 만든다.

이번 변경은 **폴더와 Markdown 문서만 생성**한다. `package.xml`, `CMakeLists.txt`, `setup.py`, ROS 인터페이스 정의 파일, 노드 코드, launch 및 파라미터 파일은 만들지 않는다. 이후 각 패키지를 우선순위대로 하나씩 구현한다.

## 2. 생성할 구조

```text
trihouse_interfaces/
├── README.md
└── doc/
    └── interface-catalog.md

trihouse_pinky/
├── README.md
├── doc/
│   ├── architecture.md
│   ├── control-ui-integration.md
│   ├── ros-interface-matrix.md
│   ├── pinky-pro-reference-map.md
│   └── implementation-order.md
├── trihouse_pinky_bringup/
│   └── README.md
├── trihouse_pinky_fleet/
│   └── README.md
├── trihouse_pinky_vision/
│   └── README.md
├── trihouse_pinky_safety/
│   └── README.md
└── trihouse_pinky_docking/
    └── README.md
```

모든 폴더에는 문서 파일이 있으므로 빈 디렉터리 문제 없이 Git에서 구조가 유지된다.

## 3. 문서별 책임

### 3.1 공용 인터페이스

`trihouse_interfaces/README.md`는 이 폴더가 실행 코드 없는 공용 ROS 2 인터페이스 패키지가 될 예정임을 설명한다. 주행 로봇, 로봇팔, 관제 사이의 계약이므로 특정 장치 패키지 아래에 두지 않는 이유와 호환성 규칙도 기록한다.

`trihouse_interfaces/doc/interface-catalog.md`는 체크리스트에 명시된 인터페이스 후보를 종류별로 정리한다.

- msg: `DeliveryOrder`, `RobotStatus`, `TaskEvent`, `TaskTrace`, `HandoverReady`, `HandoverGo`, `HandoverDone`, `PackingAssistanceRequest`, `PackingDirective`, `PackingStationStatus`, `PersonDetection`, `MarkerObservation`, `StreamHealth`, `KeepOutZone`, `EmergencyAlert`
- srv: `ClearEmergency`, `GetLocation`
- action: `ExecuteTransport`, `Dock`

각 항목에는 목적, 예상 필드, 주 발행자 또는 서버, 구독자 또는 클라이언트, 관련 SR, 확정 여부를 기록한다. 실제 `.msg`, `.srv`, `.action` 파일이 아직 없다는 점을 명시한다.

### 3.2 주행 로봇 전체 문서

`trihouse_pinky/README.md`는 전체 진입점이다. 다섯 패키지의 역할, 문서 링크, 벤더 코드 수정 금지 원칙, 구현 상태 표를 제공한다.

`trihouse_pinky/doc/architecture.md`는 다음 경계를 고정한다.

- `trihouse_pinky_bringup`: 실행 조합과 로봇별 배포 설정
- `trihouse_pinky_fleet`: 작업 상태 머신, 관제 연동, 텔레메트리, 체크포인트
- `trihouse_pinky_vision`: RTSP 영상 송신, 스트림 상태, 카메라 캘리브레이션과 좌표 변환
- `trihouse_pinky_safety`: 모든 속도 명령의 최종 게이트, 정지·비상·keep-out 처리
- `trihouse_pinky_docking`: ArUco 기반 마지막 정밀 정차

의존 방향은 `trihouse_interfaces`에서 각 기능 패키지로, 기능 패키지에서 `pinky_pro`로만 흐르게 한다. `trihouse_pinky_bringup`은 모든 실행 요소를 조합하지만 업무 로직을 소유하지 않는다.

`trihouse_pinky/doc/control-ui-integration.md`는 중앙 관제 UI/DB와 로봇의 기동 경계, TCP 8788 + NDJSON 전송 계약, 주문에서 구조화된 운반 작업으로 이어지는 흐름, readiness gate, 수락·진행·완료 회신을 설명한다. 기존 관제 링크에서 재사용할 부분과 기존 waypoint follower를 운영 경로에서 제외하는 이유도 기록한다.

`trihouse_pinky/doc/ros-interface-matrix.md`는 패키지별로 발행·구독 토픽, 제공·호출 서비스, 제공·호출 액션을 표로 정리한다. 아직 이름이 확정되지 않은 관제 연동 인터페이스는 가칭임을 표시하고, ROS 2 표준 인터페이스와 Trihouse 사용자 정의 인터페이스를 구분한다.

`trihouse_pinky/doc/pinky-pro-reference-map.md`는 재사용 지점을 파일 경로와 함께 정리한다.

- 베이스 구동과 odometry: `pinky_bringup/pinky_bringup/bringup.py`
- 하드웨어 launch와 LiDAR: `pinky_bringup/launch/bringup_robot.launch.xml`
- 배터리: `pinky_bringup/pinky_bringup/battery_publisher.py`
- IMU: `pinky_imu_bno055/src/main_node.cpp`
- 초음파·IR·배터리 센서: `pinky_sensor_adc/src/main_node.cpp`
- LED, 램프, LCD: `pinky_led`, `pinky_lamp_control`, `pinky_emotion`
- URDF 확장: `pinky_description`
- Nav2, AMCL, SLAM, map: `pinky_navigation`
- 목표 전송, 취소, pose와 상태 판정 참고: `pinky_navigation/scripts/nav2_web_server.py`
- 카메라 시뮬레이션: `pinky_gz_sim`

각 참조는 “그대로 호출”, “launch include”, “토픽 구독”, “서비스 호출”, “알고리즘 참고” 중 어느 방식인지 구분한다. `pinky_pro` 내부 파일을 직접 수정하지 않는다.

`trihouse_pinky/doc/implementation-order.md`는 이번 주 구현 순서를 선행 의존성과 Sprint2 중요도에 따라 기록한다.

## 4. 패키지별 README 내용

각 패키지 README는 동일한 틀을 사용한다.

1. 목적과 소유 책임
2. 이번 패키지에 넣지 않을 기능
3. 구현할 노드와 작업 목록
4. 발행·구독 토픽
5. 제공·호출 서비스
6. 제공·호출 액션
7. 사용하는 `trihouse_interfaces`
8. 참조하는 `pinky_pro` 자산과 참조 방법
9. 설정 파일 후보
10. 단계별 구현 순서와 완료 조건

### 4.1 `trihouse_pinky_bringup`

벤더 bringup/Nav2 launch와 Trihouse 노드를 조합하고 `robot_id`, 카메라 장치 경로, RTSP URL, 맵 revision, 관제 주소, 안전·도킹 임계값을 주입한다. 로직 노드는 구현하지 않는다.

최종 운영 목표는 `trihouse_pinky_bringup`의 최상위 launch 하나로 로봇 온보드 프로세스를 기동하는 것이다. 현재 `pinky_pro/pinky_bringup/launch/bringup_robot.launch.xml`은 URDF, LiDAR, 모터/odometry, 배터리만 실행하므로 이것만 include해서는 전체 로봇 기능이 올라오지 않는다. 최상위 launch는 다음 요소를 명시적으로 조합해야 한다.

1. `pinky_bringup/bringup_robot.launch.xml` — URDF, LiDAR, 모터, odometry, 배터리
2. `pinky_navigation/bringup_launch.xml` — map server, AMCL, Nav2
3. `pinky_imu_bno055` — IMU
4. `pinky_sensor_adc` — 초음파, IR, 보조 배터리 센서
5. `pinky_led`, `pinky_lamp_control`, `pinky_emotion` — 상태 표시 장치
6. `trihouse_pinky_safety` — 최종 속도 게이트
7. `trihouse_pinky_vision` — 영상 송신과 카메라 좌표계
8. `trihouse_pinky_docking` — 정밀 정차
9. `trihouse_pinky_fleet` — 관제 연동과 작업 수행

관제 UI와 DB는 중앙 PC에서 별도로 실행한다. 로봇 launch가 관제 UI 프로세스까지 직접 관리하지는 않는다. 대신 `trihouse_pinky_fleet`가 설정된 관제 주소에 접속하며, 필요한 노드가 실행됐다는 사실만으로 작업 준비 완료로 보지 않는다. 다음 조건을 확인하는 readiness gate를 통과한 뒤에만 새 작업을 수락한다.

- 필수 센서 토픽이 제한 시간 안에 갱신됨
- Nav2 lifecycle 노드가 active이고 `navigate_to_pose` 액션 서버가 사용 가능함
- AMCL pose가 존재하고 공분산이 허용 범위 이내임
- 로봇의 `map_revision`과 관제 작업의 `map_revision`이 일치함
- safety 상태가 비상 정지 상태가 아님
- 관제 heartbeat가 정상임
- 해당 작업이 vision 또는 docking을 요구하면 그 노드도 healthy임

실제 로봇용 최상위 launch와 시뮬레이션용 launch는 분리하되, Trihouse 기능 노드와 인터페이스는 동일하게 유지한다.

### 4.2 `trihouse_pinky_fleet`

`ExecuteTransport` 액션 서버, Nav2와 `Dock` 액션 클라이언트, 작업 상태 머신, 중복 작업 방지, 관제 heartbeat, 체크포인트, `RobotStatus`·`TaskEvent`·`TaskTrace`, 인수인계와 포장대 흐름, 표시 장치 상태 매핑을 담당한다. `/cmd_vel`을 직접 발행하지 않는다.

초기 관제 연동은 기존 `control_system/robo_control/lib/core/robot_link.dart`와 `control_system/robo_pinky/src/robo_pinky_agent/robo_pinky_agent/control_link.py`가 사용하는 TCP 8788 + NDJSON 링크를 확장해 재사용한다. 관제와 로봇 사이의 네트워크 payload는 `trihouse_interfaces`의 의미와 필드에 대응되도록 버전을 명시한다. ROS 2 사용자 정의 인터페이스는 로봇 내부 패키지 계약이고, TCP/NDJSON은 중앙 PC와 로봇 사이의 전송 계약이다.

기존 `robo_pinky_agent/agent_node.py`는 관제가 준 waypoint를 자체 follower로 추종하고 `cmd_vel`을 직접 발행하므로 실장 운영 경로로 그대로 사용하지 않는다. 재사용 범위는 TCP 재접속, hello/telemetry framing, 관제 서버 연결 방식이다. 실제 이동은 `trihouse_pinky_fleet`가 Nav2 `navigate_to_pose` 액션을 호출하고, 모든 속도 출력은 safety를 거쳐야 한다.

관제 명령은 단순 waypoint 대신 최소한 `task_id`, 작업 종류, `map_revision`, pickup/dropoff/packing location id와 pose, 우선순위 또는 기한을 가진 구조화된 운반 작업이어야 한다. 로봇은 수락·거절, 현재 단계, pose, 배터리, 안전 상태, 성공·실패 결과를 관제에 회신한다.

### 4.3 `trihouse_pinky_vision`

GStreamer 기반 H.264/RTSP 송신, `StreamHealth`, 카메라 intrinsic/extrinsic 관리, `camera_optical_frame` TF, 관제에서 받은 `MarkerObservation`·`PersonDetection`의 `base_link` 변환을 담당한다. 영상 본체를 ROS 2 토픽으로 배포하지 않는다.

### 4.4 `trihouse_pinky_safety`

`/cmd_vel_nav`와 `/cmd_vel_dock`을 입력으로 받아 `/cmd_vel`을 출력하는 최종 속도 게이트를 담당한다. LiDAR·근접센서·사람 검출로 `CLEAR/SLOW/STOP`을 판정하고, 비상 상태 래치, 명시적 해제, keep-out zone, speed limit, 비상 표시 keep-alive를 처리한다.

### 4.5 `trihouse_pinky_docking`

`Dock` 액션 서버와 마커 기반 정밀 정차를 담당한다. Nav2 목표가 종료된 이후에만 동작하며 `/cmd_vel_dock`을 통해 안전 게이트로 명령한다. 마커 소실 시 정지하고 제한된 횟수만 재시도한다.

## 5. 이번 주 권장 구현 우선순위

문서에는 아래 순서를 권장안으로 기록한다. 사용자와 함께 각 단계를 하나씩 구현하며, 한 단계의 인터페이스와 검증이 끝난 뒤 다음 단계로 넘어간다. 최종 기능을 패키지별로 전부 완성한 뒤 통합하는 방식 대신, 관제 UI 주문이 실제 Nav2 주행과 결과 보고까지 연결되는 최소 수직 흐름을 먼저 만든다.

1. **`trihouse_interfaces` 계약 확정 및 패키지화**: 이후 모든 패키지의 빌드 기반이다.
2. **`trihouse_pinky_safety` 최소 속도 게이트**: Nav2와 도킹의 모든 움직임이 통과할 안전 경로를 먼저 확보한다.
3. **`trihouse_pinky_bringup` 최소 통합 launch**: `pinky_pro`와 safety를 실제 로봇 또는 시뮬레이션에서 함께 띄운다.
4. **`trihouse_pinky_fleet` 최소 수직 기능**: 기존 TCP 링크를 통해 구조화된 작업 한 건을 받고, Nav2 목표 한 곳으로 이동한 뒤 결과와 telemetry를 관제에 회신한다.
5. **관제 UI 작업 전송 연결**: 출고 주문 또는 입고 예정이 작업으로 전개되면 robot link가 해당 로봇에 구조화된 운반 작업을 보내고 수락·진행·완료 상태를 UI에 반영한다.
6. **`trihouse_pinky_vision` 스트림과 상태 감시**: RTSP 송신과 `StreamHealth`를 만들고 캘리브레이션을 고정한다.
7. **`trihouse_pinky_docking` 정밀 정차**: 변환된 마커 pose와 safety 경로를 전제로 구현한다.
8. **입고·출고 전체 상태 머신**: pickup, docking, handover, packing, dropoff, return 단계를 연결한다.
9. **fleet 운영 기능 확장**: 관제 heartbeat 강화, 체크포인트, 중복 제거, 인수인계, 포장대 예외, 표시 매핑 순으로 추가한다.
10. **bringup 운영 프로파일 완성**: 1호기·2호기·시뮬레이션별 설정과 systemd 등 배포 구성을 마무리한다.

이번 주의 최소 목표는 1~3단계를 완료하는 것이다. 가능하면 4~5단계까지 진행해 아래 수직 흐름을 검증한다.

```text
관제 UI 출고 주문 또는 입고 예정
→ 관제 작업 생성·로봇 배정
→ Pinky 작업 수락
→ Nav2 목표 이동
→ safety 게이트를 거쳐 모터 구동
→ 도착 또는 실패 결과와 현재 상태를 관제 UI에 표시
```

vision, docking, 전체 fleet 상태 머신은 이 기본 흐름이 검증된 뒤 확장한다. 이렇게 해야 관제 계약이나 기동 구조가 잘못된 상태에서 카메라·도킹 기능을 먼저 만드는 재작업을 줄일 수 있다.

## 6. 속도 명령 경로의 필수 제약

운영 시 모든 이동 명령은 아래 경로만 사용한다.

```text
Nav2 controller/velocity smoother → /cmd_vel_nav ┐
                                                  ├→ trihouse_pinky_safety → /cmd_vel → pinky_bringup
trihouse_pinky_docking            → /cmd_vel_dock┘
```

현재 `pinky_navigation/launch/navigation_launch.xml`에는 controller 입력과 velocity smoother 출력의 remap이 함께 들어 있어, 구성에 따라 velocity smoother가 `/cmd_vel`로 직접 출력할 수 있다. 통합 bringup 구현 시 실제 토픽 그래프를 검사해 safety 우회 경로가 없도록 remap을 덮어쓰거나 Trihouse용 Nav2 launch overlay를 제공한다. `robo_pinky_agent/agent_node.py`의 직접 `cmd_vel` 발행 경로도 운영 launch에 포함하지 않는다.

## 7. 정확성 기준

- 기준 문서는 `docs/scenario/2026-08-05-mobile-robot-sr-checklist.md`이다.
- 문서의 인터페이스 이름과 역할은 체크리스트와 일치해야 한다.
- 기존 `pinky_pro` 파일은 변경하지 않는다.
- 문서가 구현 완료를 암시하지 않도록 모든 미구현 요소를 `계획` 또는 `초안`으로 표시한다.
- README만 읽어도 패키지의 책임, 입출력, 의존성, 첫 구현 작업을 알 수 있어야 한다.
- 중앙 인터페이스 표와 패키지 README 사이의 발행자·구독자 관계가 서로 모순되지 않아야 한다.
- 최상위 bringup 한 번으로 로봇 온보드 필수 프로세스가 실행되되, readiness gate 전에는 작업을 수락하지 않아야 한다.
- 관제 UI가 로봇 launch에 종속되지 않고 별도 중앙 프로세스로 유지되어야 한다.
- Nav2, docking 또는 기존 에이전트가 safety를 우회해 모터용 `/cmd_vel`을 발행해서는 안 된다.

## 8. 이번 변경에서 제외할 사항

- ROS 2 패키지 생성과 빌드
- `.msg`, `.srv`, `.action` 파일 작성
- 노드, launch, YAML, URDF 작성
- `pinky_pro` 수정
- 관제·DB·로봇팔 코드 수정
- 하드웨어 및 시뮬레이션 실행 검증
