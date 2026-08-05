# Pinky-Pro 체크리스트 이전 안내

Pinky-Pro, DB, 관제시스템, 로봇팔과 SR·시나리오 추적을 합친 최신 체크리스트는 다음 문서로 통합했다.

- [Trihouse 시스템 요구사항 구현 체크리스트](./system-requirements-implementation-checklist.md)

아래 내용은 최초 Pinky-Pro 기본 코드 조사 기록으로 보존한다. 구현 진행 상태는 위 통합 문서에서만 갱신한다.

---

# Pinky-Pro 주행 로봇 기능 체크리스트 및 기본 코드 조사 (초기 기록)

작성일: 2026-08-05  
조사 대상: `docs/db_schema`, `docs/scenario`, `docs/setup`, `pinky_pro`

## 1. 범위와 판정 기준

이 문서는 입고·출고·비상상황 시나리오에서 **Pinky-Pro 주행 로봇이 직접 수행하거나 Pinky-Pro 쪽 연동 코드가 제공해야 하는 기능**을 정리하고, 현재 `pinky_pro` 기본 코드의 구현 여부를 파일 단위로 대조한다. 로봇팔의 파지·배치 정책과 중앙 관제의 주문·재고 처리 자체는 제외하되, Pinky-Pro가 주고받아야 하는 작업 명령·상태·인계 신호는 포함한다.

상태 표시는 다음과 같다.

- `[x] 구현`: 현재 저장소에 실행 코드 또는 실질적인 ROS 2 설정이 있다.
- `[ ] 부분 구현`: 기반 기능은 있으나 문서가 요구하는 종단 간 기능 또는 FMS 연동이 없다.
- `[ ] 미구현`: 현재 `pinky_pro`에서 관련 구현 파일을 찾지 못했다.

주의: `[x]`는 정적 코드 조사 결과다. 실제 Pinky-Pro 하드웨어에서의 빌드·실행·성능 검증 완료를 뜻하지 않는다.

## 2. 요구사항 출처

- `docs/scenario/입고_workflow.pdf`: 작업 할당, 경로 충돌 회피, 하차 위치 이동·대기, 준비/완료 신호, 통신 단절 복구, 대기 장소 복귀
- `docs/scenario/출고_workflow.pdf`: 목적지 명령, 위치 주기 보고, 도착 검증, 상시 카메라, 장애물·사람·위급상황 대응, 적재 무게 확인, 포장대 이동·작업자 확인·하차·복귀
- `docs/scenario/비상상황_workflow.pdf`: 감속·정지, 사람/장애물 구분, 자세·움직임 추적, 쓰러짐 의심 알림, 안전거리, 우회, 비상 LED·부저, 접근 금지, 관리자 해제 후 점검·복귀
- `docs/setup/system_environment/2026-08-05-vision-streaming-architecture-draft.md`: Pinky 내장 카메라 H.264 송신, MediaMTX RTSP/SRT 경로, 스트림 식별·상태·단절 복구, 로컬 영상 저장 금지
- `docs/db_schema/trihouse_fms_schema_v3_data_dictionary.xlsx`: `devices`, `device_states`, `jobs`, `job_steps`, `reservations`, `integration_messages`, `incidents`, `operation_events`에 대응하는 로봇 식별·상태·작업·점유·메시지·안전 이벤트 연동

## 3. 현재 기본 코드에 구현된 기능과 파일

| 현재 기능 | 구현 파일 | 확인한 코드/설정 |
|---|---|---|
| 차동 구동 명령 수신 및 모터 제어 | `pinky_pro/pinky_bringup/pinky_bringup/bringup.py` 17–18, 84–88, 104–125행; `pinky_pro/pinky_bringup/pinky_bringup/dynamixel_driver.py` 28–29, 45–69행 | `cmd_vel`을 좌·우 바퀴 RPM으로 변환, 최대 100 RPM 제한, Dynamixel 동기 명령 |
| 엔코더 기반 오도메트리·TF·휠 상태 | `pinky_pro/pinky_bringup/pinky_bringup/bringup.py` 127–195행 | 30 Hz 피드백, `odom`, `odom→base_footprint`, `joint_states` 발행 |
| 저수준 종료 시 모터 정지 | `pinky_pro/pinky_bringup/pinky_bringup/dynamixel_driver.py` 36–43행 | 종료 시 0 RPM, 토크 해제, 포트 종료 |
| RPLIDAR 기동 | `pinky_pro/pinky_bringup/launch/bringup_robot.launch.xml` 12–18행 | SLLIDAR C1, `/scan` 입력 기반 |
| SLAM 및 지도 저장 | `pinky_pro/pinky_navigation/launch/map_building.launch.xml` 4–8행; `pinky_pro/pinky_navigation/params/mapper_params.yaml`; `pinky_pro/pinky_navigation/scripts/nav2_web_server.py` 393–422행 | SLAM Toolbox 실행, 웹 API에서 reset/save 요청 |
| 지도 기반 위치 추정 | `pinky_pro/pinky_navigation/launch/localization_launch.xml` 7–68행; `pinky_pro/pinky_navigation/params/nav2_params.yaml` 1–42행 | Map Server와 AMCL, `map/odom/base_footprint` 좌표계 |
| 목표점 자율주행·도착 허용오차 | `pinky_pro/pinky_navigation/scripts/nav2_web_server.py` 140–164, 326–346행; `pinky_pro/pinky_navigation/params/nav2_params.yaml` 153–170행 | `NavigateToPose`, 위치 0.25 m·방향 0.25 rad 허용오차, 진행 정체 검사 |
| 라이다 장애물 반영 및 경로 계획 | `pinky_pro/pinky_navigation/params/nav2_params.yaml` 173–250, 268–275행 | 로컬/글로벌 costmap, obstacle/voxel/inflation layer, NavFn planner |
| 기본 복구 행동·웨이포인트 | `pinky_pro/pinky_navigation/params/nav2_params.yaml` 286–323행 | 회전, 후진, 직진, 대기, assisted teleop, waypoint follower |
| 주행 목표 취소 | `pinky_pro/pinky_navigation/scripts/nav2_web_server.py` 376–390, 487–496행 | 모든 활성 Nav2 goal 취소 API. 비상 자동 정지는 아님 |
| 웹 지도·현재 위치·경로·costmap 표시와 목표 지정 | `pinky_pro/pinky_navigation/scripts/nav2_web_server.py` 63–175, 218–346, 429–531행; `pinky_pro/pinky_navigation/scripts/index.html` | Flask API로 상태 조회, 목표/초기 위치 지정, 정지, SLAM 제어 |
| 배터리 퍼센트·전압 발행 | `pinky_pro/pinky_bringup/pinky_bringup/battery_publisher.py` 6–36행 | 5초마다 `battery/percent`, `battery/voltage` 발행 |
| 저전압 경고 로그 | `pinky_pro/pinky_bringup/pinky_bringup/bringup.py` 33–34, 90–95, 197–205행 | 6.8 V 이하 경고. 자동 복귀·충전은 없음 |
| 초음파·IR·ADC 배터리 센서 노드 | `pinky_pro/pinky_sensor_adc/src/main_node.cpp` 11–100행 | 초음파 거리, IR 3채널, `BatteryState` 발행 |
| IMU 센서 노드 | `pinky_pro/pinky_imu_bno055/src/main_node.cpp` 10–124행 | BNO055 자세·각속도·가속도 발행 |
| 상태 표시용 LED | `pinky_pro/pinky_led/pinky_led/led_server.py` 10–77행; `pinky_pro/pinky_lamp_control/src/main_node.cpp` 32–158행 | 색상/픽셀/밝기와 램프 효과 서비스. 비상 상태와 자동 연결되지 않음 |
| LCD 감정 표시 | `pinky_pro/pinky_emotion/pinky_emotion/emotion_server.py` 10–83행 | GIF 기반 감정 표시 서비스 |
| 시뮬레이션 센서·영상 브리지 | `pinky_pro/pinky_gz_sim/params/pinky_bridge.yaml`; `pinky_pro/pinky_gz_sim/launch/launch_sim.launch.xml` 33–35행; `pinky_pro/pinky_description/urdf/pinky_gz.urdf.xacro` | Gazebo의 scan/camera/cmd_vel/odom 브리지. 실물 H.264/RTSP 송신과는 다름 |
| 로봇 모델과 센서 프레임 | `pinky_pro/pinky_description/urdf/pinky.urdf.xacro` 145–234, 263–295행 | 램프, 라이다, 전면 카메라, 초음파, IR, IMU 링크 정의 |

`bringup_robot.launch.xml`은 현재 로봇 모델, RPLIDAR, 구동 노드, 배터리 publisher만 시작한다. IMU, ADC 거리 센서, LED, 램프, LCD 노드는 코드가 있어도 기본 bringup에 포함되어 있지 않다.

## 4. Pinky-Pro 요구 기능 체크리스트와 구현 대조

### 4.1 기본 주행·지도·센서

- [x] 차동 구동 및 속도 명령 실행  
  구현: `pinky_pro/pinky_bringup/pinky_bringup/bringup.py`, `pinky_pro/pinky_bringup/pinky_bringup/dynamixel_driver.py`
- [x] 엔코더 기반 현재 위치 추정용 odometry·TF 발행  
  구현: `pinky_pro/pinky_bringup/pinky_bringup/bringup.py`
- [x] 2D LiDAR 스캔 입력  
  구현/기동: `pinky_pro/pinky_bringup/launch/bringup_robot.launch.xml`
- [x] SLAM 지도 작성·저장  
  구현/설정: `pinky_pro/pinky_navigation/launch/map_building.launch.xml`, `pinky_pro/pinky_navigation/params/mapper_params.yaml`, `pinky_pro/pinky_navigation/scripts/nav2_web_server.py`
- [x] 저장 지도 기반 AMCL 위치 추정  
  구현/설정: `pinky_pro/pinky_navigation/launch/localization_launch.xml`, `pinky_pro/pinky_navigation/params/nav2_params.yaml`
- [x] 목적 좌표로 Nav2 자율주행  
  구현/설정: `pinky_pro/pinky_navigation/launch/navigation_launch.xml`, `pinky_pro/pinky_navigation/scripts/nav2_web_server.py`, `pinky_pro/pinky_navigation/params/nav2_params.yaml`
- [x] 라이다 기반 정적 장애물 costmap 반영과 회피 경로 계획  
  구현/설정: `pinky_pro/pinky_navigation/params/nav2_params.yaml`
- [x] 정체 감지와 기본 복구 행동(회전·후진·대기 등)  
  구현/설정: `pinky_pro/pinky_navigation/params/nav2_params.yaml`
- [x] 주행 목표 취소를 통한 정지 요청  
  구현: `pinky_pro/pinky_navigation/scripts/nav2_web_server.py`
- [x] 배터리 퍼센트·전압 발행  
  구현: `pinky_pro/pinky_bringup/pinky_bringup/battery_publisher.py`
- [ ] **부분 구현** — IMU 측정은 구현됐으나 기본 bringup 및 Nav2 sensor fusion에 연결되지 않음  
  기반 코드: `pinky_pro/pinky_imu_bno055/src/main_node.cpp`; 누락 위치: `pinky_pro/pinky_bringup/launch/bringup_robot.launch.xml`, `pinky_pro/pinky_navigation/params/nav2_params.yaml`
- [ ] **부분 구현** — 초음파·IR 거리 측정은 구현됐으나 기본 bringup과 Nav2 costmap/안전 정지에 연결되지 않음  
  기반 코드: `pinky_pro/pinky_sensor_adc/src/main_node.cpp`; 누락 위치: `pinky_pro/pinky_bringup/launch/bringup_robot.launch.xml`, `pinky_pro/pinky_navigation/params/nav2_params.yaml`
- [ ] **부분 구현** — 저전압 로그는 있으나 배터리 임계치 기반 작업 거부·대기 존/충전소 복귀·FMS 상태 보고가 없음  
  기반 코드: `pinky_pro/pinky_bringup/pinky_bringup/bringup.py`, `pinky_pro/pinky_bringup/pinky_bringup/battery_publisher.py`

### 4.2 입고·출고 작업 수행과 FMS 연동

- [ ] **미구현** — `job_id`/`job_step_id`, 목적지, 물품·바구니, 적재 중량, 우선순위를 포함한 FMS 작업 명령 수신
- [ ] **미구현** — 명령 수신 ACK, 중복 방지용 idempotency key, 재전송/실패/dead-letter 처리
- [ ] **부분 구현** — 목적 좌표 이동 API는 있으나 `DeliveryOrder` 또는 DB `job_steps.action_type=navigate`를 Nav2 goal로 변환하는 어댑터가 없음  
  기반 코드: `pinky_pro/pinky_navigation/scripts/nav2_web_server.py`
- [ ] **부분 구현** — 현재 좌표는 `odom` 30 Hz와 웹 상태 API로 제공되지만, 로봇 ID·작업 ID와 함께 FMS로 10초마다 보고하는 publisher/API가 없음  
  기반 코드: `pinky_pro/pinky_bringup/pinky_bringup/bringup.py`, `pinky_pro/pinky_navigation/scripts/nav2_web_server.py`
- [ ] **부분 구현** — Nav2 goal 상태와 도착 허용오차는 있으나 FMS용 도착/실패 결과 메시지와 목적지 ID 대조가 없음  
  기반 코드: `pinky_pro/pinky_navigation/scripts/nav2_web_server.py`, `pinky_pro/pinky_navigation/params/nav2_params.yaml`
- [ ] **미구현** — 하차·적재·포장 위치의 정밀 도킹 및 위치·자세 보정
- [ ] **미구현** — `READY_TO_UNLOAD`, `READY_TO_LOAD`, 하차 완료, 적재 완료, 포장대 도착/하차 완료 신호
- [ ] **미구현** — 바구니/적재물 무게 측정용 load cell과 적재 전후 중량 검증  
  참고: `pinky_pro/pinky_sensor_adc/src/main_node.cpp`의 ADC는 거리 센서와 배터리용이며 적재 중량을 계산하지 않는다.
- [ ] **미구현** — 로봇 최대 적재 가능 무게 확인 및 초과 작업 거부/분할 요청
- [ ] **미구현** — 바구니 고정, 물품 하차 등 Pinky 자체 적재/하차 액추에이터 제어
- [ ] **미구현** — 상온·냉장·냉동 저장 구역, 입고 하차 위치, 포장대, 대기 존, 충전소의 FMS location ID/좌표 매핑
- [ ] **미구현** — 하차 위치 점유 확인과 비어 있을 때까지 안전 대기
- [ ] **부분 구현** — Nav2 waypoint/대기 기능은 있으나 시나리오 상태 머신의 대기 장소·재확인 위치·충전소 복귀 명령과 연결되지 않음  
  기반 설정: `pinky_pro/pinky_navigation/params/nav2_params.yaml`
- [ ] **미구현** — 다른 로봇과 시간·공간 경로 충돌 검사 및 `reservations`/병목 lock 연동
- [ ] **미구현** — 포장대 작업자 존재 여부 탐지, 다른 포장대 선택, 작업자 배치 요청
- [ ] **미구현** — 입고/출고 단계별 로컬 작업 ID·마지막 안전 완료 상태 저장
- [ ] **미구현** — 통신 복구 후 FMS와 작업 상태 대조 및 마지막 확인 단계부터 멱등 재개
- [ ] **미구현** — 작업 종료 후 위치·이동 경로·작업시간·성공/실패를 FMS에 보고

### 4.3 장애물·사람·비상상황 대응

- [ ] **부분 구현** — LiDAR 장애물 회피는 있으나 “전방 대상 감지 → 감속 → 정지”를 명시적으로 관리하는 안전 상태 머신은 없음  
  기반 설정: `pinky_pro/pinky_navigation/params/nav2_params.yaml`
- [ ] **미구현** — 카메라 기반 사람/비사람 판별
- [ ] **미구현** — 사람과 대상의 위치·자세·움직임을 일정 프레임 추적
- [ ] **미구현** — 비정상 자세와 일정 시간 무동작을 결합한 작업자 쓰러짐 의심 판정
- [ ] **미구현** — 비사람 대상의 정적/동적 장애물 분류
- [ ] **미구현** — 사람/동적 장애물과의 안전거리 유지 및 경로가 비워질 때까지 재확인
- [ ] **부분 구현** — Nav2 재계획·복구 기반은 있으나 비상 판정 결과에 따른 우회/대기/재개 정책과 FMS 승인이 없음  
  기반 설정: `pinky_pro/pinky_navigation/params/nav2_params.yaml`
- [ ] **부분 구현** — LED/램프 제어 서비스는 있으나 비상 시 빨간 LED 자동 점등이 연결되지 않음  
  기반 코드: `pinky_pro/pinky_led/pinky_led/led_server.py`, `pinky_pro/pinky_lamp_control/src/main_node.cpp`
- [ ] **미구현** — 부저 제어
- [ ] **미구현** — 작업자 쓰러짐 의심 알림(로봇 ID, 구역, 감지 위치·시각, 증거/신뢰도) 전송
- [ ] **미구현** — FMS 비상 대응 구역/no-go zone 수신, 진입 차단, 안전 정지 상태 유지
- [ ] **미구현** — 관리자 해제 승인 전 재시작 금지와 해제 후 위치·적재·통신·센서 self-check
- [ ] **미구현** — 비상 영향 작업의 보류·재할당·대기 존/충전소 복귀 결과 보고

### 4.4 Pinky 내장 카메라와 영상 스트리밍

- [ ] **부분 구현** — 로봇 모델에는 전면 카메라 프레임이 있고 Gazebo 영상 브리지는 있으나, 실물 Pinky 내장 카메라 캡처 노드가 없음  
  기반 모델/시뮬레이션: `pinky_pro/pinky_description/urdf/pinky.urdf.xacro`, `pinky_pro/pinky_description/urdf/pinky_gz.urdf.xacro`, `pinky_pro/pinky_gz_sim/launch/launch_sim.launch.xml`
- [ ] **미구현** — 실물 카메라의 안정적인 `/dev/v4l/by-id/` 식별과 부팅 시 자동 시작
- [ ] **미구현** — H.264 1280×720, 10–15 fps, 1.5–3 Mbps, 1초 keyframe 인코딩/패스스루
- [ ] **미구현** — RTX 4060 MediaMTX의 `pinky_1`/`pinky_2` RTSP(TCP) 또는 SRT 경로 게시
- [ ] **미구현** — 오래된 프레임 폐기와 제한된 최신 RAM 버퍼
- [ ] **미구현** — 카메라 연결, FPS, 비트레이트, 마지막 frame ID·capture timestamp 상태 보고
- [ ] **미구현** — 1초 `DEGRADED`, 3초 `DISCONNECTED`, 재연결 중 `RECOVERING`, 5초 안정 후 `HEALTHY` 판정
- [ ] **미구현** — Wi-Fi/카메라/송신 프로세스 단절 감지, 제한 backoff 재접속, freeze 감지
- [ ] **미구현** — 스트림 단절 시 의존 동작 정지와 재연결 후 새 검증 전 재개 금지
- [ ] **미구현** — Pinky 로컬 영상/이미지 파일 생성 금지를 보장하는 서비스 설정과 검증
- [ ] **미구현** — 영상은 RTSP/SRT, 상태·이벤트는 ROS 2/API로 분리하는 실물 운용 구성  
  참고: Gazebo는 `ros_gz_image`로 ROS 2 이미지 토픽을 사용하므로 실물 목표 아키텍처의 구현 근거가 아니다.

### 4.5 DB 스키마에 맞춘 로봇 상태·감사 연동

- [ ] **미구현** — `devices`의 `device_id`, `device_type=mobile`, home/current location, control mode, capabilities와 Pinky 설정 연결
- [ ] **부분 구현** — 위치·배터리 원천 토픽은 있으나 `device_states`의 state, health, battery_pct, pose, current step, heartbeat/details 형태로 집계·전송하지 않음  
  기반 코드: `pinky_pro/pinky_bringup/pinky_bringup/bringup.py`, `pinky_pro/pinky_bringup/pinky_bringup/battery_publisher.py`
- [ ] **미구현** — `job_steps`의 `navigate`, `dock`, `load`, `unload`, `wait`, `return_home`, `safety_stop` 실행 상태 매핑
- [ ] **미구현** — `integration_messages(channel=pinky)` 명령·응답, ACK와 멱등 키 연동
- [ ] **미구현** — `reservations`의 위치·장비·병목 점유 획득/갱신/해제
- [ ] **미구현** — `incidents`의 blocked path, worker emergency, estop, device fault 생성/갱신용 이벤트 전송
- [ ] **미구현** — `operation_events`의 operation/vision/safety/system 이벤트, severity, safety decision, payload 기록 요청

### 4.6 운용 완성도

- [ ] **부분 구현** — Gazebo는 namespace 인자를 사용하지만 실물 두 대의 토픽·TF·노드 namespace와 `device_id` 분리 구성이 없음  
  기반 코드: `pinky_pro/pinky_description/urdf/robot.urdf.xacro`, `pinky_pro/pinky_gz_sim/launch/launch_sim.launch.xml`
- [ ] **미구현** — 모터 명령 timeout/watchdog와 노드·센서·네트워크 heartbeat를 종합한 fail-safe 정지
- [ ] **미구현** — FMS 연결 실패, 센서 고장, 카메라 단절, 저전압을 통합한 diagnostics/health reporter
- [ ] **부분 구현** — 개별 센서·표시 노드는 있으나 기본 `bringup_robot.launch.xml`에 IMU, ADC, LED/램프, LCD가 통합되지 않음
- [ ] **미구현** — 시나리오 상태 머신, FMS 프로토콜, 비상 대응, 영상 스트림에 대한 단위·통합·하드웨어 시험  
  현재 테스트 파일: `pinky_pro/pinky_bringup/test/*`, `pinky_pro/pinky_led/test/*`, `pinky_pro/pinky_emotion/test/*`는 저작권/flake8/pep257 검사 중심이다.

## 5. 현재 상태 요약과 구현 우선순위

현재 기본 코드는 **수동 또는 웹 목표점 기반의 단일 로봇 Nav2 주행 기반**은 갖추고 있다. 반면 문서의 Trihouse 시나리오를 완성하는 데 필요한 **FMS 작업 어댑터, 작업 상태 머신, 실물 영상 송신, 사람·비상 인지, 적재 중량/도킹, 장애 복구 프로토콜**은 별도 개발이 필요하다.

권장 구현 순서는 다음과 같다.

1. `pinky_fms_bridge`: 장비 ID, 작업 명령/ACK, 상태·위치·배터리 보고, Nav2 결과, 멱등 재개
2. `pinky_mission_manager`: 입고/출고/대기/복귀/비상 상태 머신과 안전 정지 우선권
3. `pinky_camera_streamer`: 실물 카메라 식별, H.264 RTSP/SRT 송신, stream health·재접속, 로컬 저장 금지
4. `pinky_safety`: 센서·Nav2·카메라 인지 결과 통합, watchdog, 감속/정지, 비상 LED·부저, 관리자 해제 gate
5. 적재 하드웨어 계층: load cell, 바구니 고정/하차 장치, 정밀 도킹 센서와 제어
6. 다중 로봇 연동: location/feature reservation, 병목 lock, no-go zone, 경로 충돌 조정
7. 시나리오 기반 통합 시험: 정상 입고·출고, 장애물/사람, 통신·카메라 단절, 저전압, 재시작·중복 명령

## 6. 판정 시 주의할 점

- Nav2 장애물 회피는 사람 판별, 쓰러짐 감지, 동적/정적 의미 분류를 대신하지 않는다.
- `/api/nav/stop`은 수동 goal 취소 기능이며, 안전 센서나 비상상황에 의해 자동 실행되는 E-stop 계층은 아니다.
- `odom`이 존재해도 FMS의 `device_states`가 자동 갱신되는 것은 아니다. 로봇 ID·작업 ID·map pose·timestamp·health를 묶는 어댑터가 필요하다.
- 현재 ADC 센서 노드는 적재 중량 센서가 아니다.
- Gazebo 카메라의 ROS 2 image bridge는 실물 카메라 H.264→MediaMTX 스트리밍 구현으로 체크하지 않았다.
- Generic LED/LCD 서비스가 있어도 비상/작업 상태 머신과 연결되기 전에는 시나리오의 경광·알림 기능이 완료된 것이 아니다.
