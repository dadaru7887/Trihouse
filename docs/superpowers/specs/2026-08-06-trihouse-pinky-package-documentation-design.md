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

### 4.2 `trihouse_pinky_fleet`

`ExecuteTransport` 액션 서버, Nav2와 `Dock` 액션 클라이언트, 작업 상태 머신, 중복 작업 방지, 관제 heartbeat, 체크포인트, `RobotStatus`·`TaskEvent`·`TaskTrace`, 인수인계와 포장대 흐름, 표시 장치 상태 매핑을 담당한다. `/cmd_vel`을 직접 발행하지 않는다.

### 4.3 `trihouse_pinky_vision`

GStreamer 기반 H.264/RTSP 송신, `StreamHealth`, 카메라 intrinsic/extrinsic 관리, `camera_optical_frame` TF, 관제에서 받은 `MarkerObservation`·`PersonDetection`의 `base_link` 변환을 담당한다. 영상 본체를 ROS 2 토픽으로 배포하지 않는다.

### 4.4 `trihouse_pinky_safety`

`/cmd_vel_nav`와 `/cmd_vel_dock`을 입력으로 받아 `/cmd_vel`을 출력하는 최종 속도 게이트를 담당한다. LiDAR·근접센서·사람 검출로 `CLEAR/SLOW/STOP`을 판정하고, 비상 상태 래치, 명시적 해제, keep-out zone, speed limit, 비상 표시 keep-alive를 처리한다.

### 4.5 `trihouse_pinky_docking`

`Dock` 액션 서버와 마커 기반 정밀 정차를 담당한다. Nav2 목표가 종료된 이후에만 동작하며 `/cmd_vel_dock`을 통해 안전 게이트로 명령한다. 마커 소실 시 정지하고 제한된 횟수만 재시도한다.

## 5. 이번 주 권장 구현 우선순위

문서에는 아래 순서를 권장안으로 기록한다. 사용자와 함께 각 단계를 하나씩 구현하며, 한 단계의 인터페이스와 검증이 끝난 뒤 다음 단계로 넘어간다.

1. **`trihouse_interfaces` 계약 확정 및 패키지화**: 이후 모든 패키지의 빌드 기반이다.
2. **`trihouse_pinky_safety` 최소 속도 게이트**: Nav2와 도킹의 모든 움직임이 통과할 안전 경로를 먼저 확보한다.
3. **`trihouse_pinky_bringup` 최소 통합 launch**: `pinky_pro`와 safety를 실제 로봇 또는 시뮬레이션에서 함께 띄운다.
4. **`trihouse_pinky_vision` 스트림과 상태 감시**: RTSP 송신과 `StreamHealth`를 먼저 만들고 캘리브레이션을 고정한다.
5. **`trihouse_pinky_docking` 정밀 정차**: 변환된 마커 pose와 safety 경로를 전제로 구현한다.
6. **`trihouse_pinky_fleet` 핵심 운반 상태 머신**: Nav2와 docking을 연결해 최소 운반 시나리오를 완성한다.
7. **fleet 운영 기능 확장**: 관제 heartbeat, 체크포인트, 텔레메트리, 인수인계, 포장대 예외, 표시 매핑 순으로 추가한다.
8. **bringup 운영 프로파일 완성**: 1호기·2호기·시뮬레이션별 설정과 systemd 등 배포 구성을 마무리한다.

이번 주의 최소 목표는 1~3단계를 완료하고, 하드웨어 여건이 허용되면 4단계의 RTSP 송신과 상태 감시까지 검증하는 것이다. 도킹과 전체 fleet 상태 머신은 카메라 캘리브레이션 및 관제 인터페이스 확정에 영향을 받으므로 후속 단계로 둔다.

## 6. 정확성 기준

- 기준 문서는 `docs/scenario/2026-08-05-mobile-robot-sr-checklist.md`이다.
- 문서의 인터페이스 이름과 역할은 체크리스트와 일치해야 한다.
- 기존 `pinky_pro` 파일은 변경하지 않는다.
- 문서가 구현 완료를 암시하지 않도록 모든 미구현 요소를 `계획` 또는 `초안`으로 표시한다.
- README만 읽어도 패키지의 책임, 입출력, 의존성, 첫 구현 작업을 알 수 있어야 한다.
- 중앙 인터페이스 표와 패키지 README 사이의 발행자·구독자 관계가 서로 모순되지 않아야 한다.

## 7. 이번 변경에서 제외할 사항

- ROS 2 패키지 생성과 빌드
- `.msg`, `.srv`, `.action` 파일 작성
- 노드, launch, YAML, URDF 작성
- `pinky_pro` 수정
- 관제·DB·로봇팔 코드 수정
- 하드웨어 및 시뮬레이션 실행 검증
