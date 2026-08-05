# Trihouse 시스템 요구사항 구현 체크리스트

작성일: 2026-08-05  
관제 코드 기준: `control_system` GitHub `main`, commit `684f1444eb67de46b088a89dcf98a9711d9ad685`  
대상: Pinky-Pro · DB · 관제시스템 · 로봇팔

### 조사 기준 자료

- `/home/newuser/Downloads/로보사피엔스_SR.pdf`: `SR_01`~`SR_51`(원문의 중복 번호 `SR_12(2)` 포함)
- `docs/scenario/입고_workflow.pdf`, `docs/scenario/출고_workflow.pdf`, `docs/scenario/비상상황_workflow.pdf`
- `docs/db_schema/trihouse_fms_schema_v3_data_dictionary.xlsx`, `docs/db_schema/trihouse_fms_schema_v3_er_diagram.drawio`
- `docs/setup/fms-gateway-setup.md`
- `docs/setup/system_environment/2026-08-05-vision-streaming-architecture-draft.md`
- `docs/setup/system_environment/2026-08-05-robot-arm-imitation-safe-operation-draft.md`
- 현재 브랜치의 `pinky_pro`, `vision_perception`, 그리고 위 commit으로 갱신한 `control_system`

## 1. 사용하는 방법

- `[x]`: 현재 코드와 연결 설정에서 구현 근거를 확인했다.
- `[ ] 부분 구현`: 기반 코드가 있지만 실제 장비 또는 종단 간 연동이 남아 있다.
- `[ ] 미구현`: 관련 실행 코드가 없다.
- `[ ] 설계만`: 설계 문서에는 있으나 실제 구현 코드는 없다.
- `[ ] 시뮬레이션만`: Gazebo/결정론적 시뮬레이터에만 있고 실물 코드에는 없다.

체크하지 않은 행이 실제 구현 작업 목록이다. 구현 후에는 반드시 `구현 근거`에 파일과 테스트를 추가한 다음 `[x]`로 바꾼다. 무게 관련 기능은 모두 `LOW/후순위`이며 초기 필수 시험에서 제외한다.

## 2. 지금 먼저 구현할 P0 작업 보드

아래 순서대로 진행하면 현재 분리된 Pinky, 관제, DB와 로봇팔 설계를 가장 짧게 연결할 수 있다.

### 2.1 Pinky-Pro P0

- [ ] `PINKY-P0-01` **실물 FMS agent 패키지 추가** — `control_system/robo_pinky/src/robo_pinky_agent/robo_pinky_agent/control_link.py`의 연결·backoff를 재사용하되 실제 `pinky_pro`의 Nav2, map pose, 배터리 토픽에 연결한다.  
  첫 대상: 새 `pinky_pro/pinky_fms_agent/`; 연동: `pinky_navigation`, `pinky_bringup`.
- [ ] `PINKY-P0-02` **FMS 이동 명령을 Nav2 action으로 변환** — 작업/목적지 명령을 `NavigateToPose`에 전달하고 accepted/running/succeeded/failed/arrival을 회신한다.  
  기반: `pinky_pro/pinky_navigation/scripts/nav2_web_server.py`; 시뮬레이션 참고: `control_system/robo_pinky/src/robo_pinky_agent/robo_pinky_agent/agent_node.py`.
- [ ] `PINKY-P0-03` **명령 ACK·멱등성·로컬 작업 복구** — `message_id`, `idempotency_key`, `job_id`, `job_step_id`, sequence, TTL을 저장하고 중복 명령을 재실행하지 않는다.
- [ ] `PINKY-P0-04` **명령·통신 watchdog** — 관제 단절 또는 명령 timeout 때 새 `cmd_vel`을 차단하고 0 속도·안전 상태를 유지한다. 재연결만으로 작업을 자동 재개하지 않는다.  
  시뮬레이션 참고: `control_system/robo_pinky/src/robo_pinky_agent/robo_pinky_agent/control_link.py:97`, `control_system/robo_pinky/src/robo_pinky_agent/robo_pinky_agent/agent_node.py:169`.
- [ ] `PINKY-P0-05` **실물 카메라 H.264 송신기** — `/dev/v4l/by-id/` 식별, 720p 10–15 fps, RTSP/TCP 우선, `pinky_1`/`pinky_2`, 로컬 파일 저장 금지.  
  첫 대상: 새 `pinky_pro/pinky_camera_streamer/`.
- [ ] `PINKY-P0-06` **통합 health reporter** — map pose, battery, Nav2 state, lidar, camera FPS/last frame, network, active job을 timestamp와 함께 보고한다.
- [ ] `PINKY-P0-07` **비상 명령과 로컬 정지 우선순위** — 라이다/근접 센서 정지 > 로컬 E-stop > 관제 hold > Nav2 goal 순으로 우선순위를 고정하고 빨간 LED·부저를 연결한다.

### 2.2 DB P0

- [ ] `DB-P0-01` **정식 스키마 하나로 확정** — 목표 `trihouse_fms` v3와 현재 `robosapiens` v2를 병행하지 말고 v3를 canonical schema로 정한다.
- [ ] `DB-P0-02` **v3 DDL을 실행 가능한 SQL migration으로 작성** — `locations`, `map_features`, `devices`, `inventory_lots`, `jobs`, `job_items`, `job_steps`, `reservations`, `inventory_moves`, `device_states`, `integration_messages`, `incidents`, `operation_events`, `artifacts`를 생성한다.
- [ ] `DB-P0-03` **MySQL repository/API 연결** — 현재 Flutter runtime은 SQLite만 사용하므로 v3 MySQL을 읽고 쓰는 Gateway repository를 구현한다. 로봇과 UI에는 DB write credential을 주지 않는다.
- [ ] `DB-P0-04` **명령 outbox와 멱등 처리** — `integration_messages`에서 원자적 enqueue, ACK, retry, timeout, dead-letter와 `(direction, channel, idempotency_key)` 중복 방지를 구현한다.
- [ ] `DB-P0-05` **장비 최신 상태·stale 판정 저장** — `device_states`에 pose, battery, health, current step, progress, heartbeat/details를 UPSERT한다.
- [ ] `DB-P0-06` **위치·통로·장비 reservation 트랜잭션** — FMS가 active lock을 원자적으로 획득·갱신·해제하고 만료 lock을 회수한다.
- [ ] `DB-P0-07` **작업·재고·이벤트 원자성** — job step 완료, inventory move, 현재 재고 변경과 operation event를 같은 트랜잭션으로 처리한다.

### 2.3 관제시스템 P0

- [ ] `FMS-P0-01` **관제 실행 경로 통합 결정** — 현재 독립적인 `robo_control`과 `openrmf_app` 중 하나를 상위 UI로 정하고, FMS 작업을 RMF task로 연결한다.
- [ ] `FMS-P0-02` **FMS Gateway 서비스 구현** — 문서에 명시된 FastAPI/MySQL API, Pinky·OMX adapter, 인증·권한·health endpoint를 만든다. 현재 main에는 Gateway 서버 코드가 없다.
- [ ] `FMS-P0-03` **Pinky 명령 프로토콜 v2** — TCP NDJSON의 `path/hold/speed/charge`에 job/step/message ID, ACK, TTL, 결과, heartbeat와 재전송 규칙을 추가한다.
- [ ] `FMS-P0-04` **입고·출고 workflow 상태 머신** — 시나리오의 준비 신호 barrier, 위치 점유 대기, 실패·보류, 통신 복구, 포장대 선택을 명시적인 상태로 구현한다.
- [ ] `FMS-P0-05` **Trihouse RMF 연동** — 현재 `control_system/openrmf/launch/office_web.launch.xml`은 stock office/tinyRobot 데모다. `control_system/rmf_maps/warehouse`와 실제 Pinky fleet adapter를 실행 경로에 연결한다.
- [ ] `FMS-P0-06` **MediaMTX 영상 허브** — 6개 H.264 stream 수신·중계·녹화, stream health, 최신 프레임 큐와 카메라별 retention을 구현한다.
- [ ] `FMS-P0-07` **QR·ArUco worker와 DB 검증** — 필요한 stream만 5–10 fps decode하고 observation을 생성해 작업 대상·위치와 대조한다.
- [ ] `FMS-P0-08` **비상상황 종단 간 workflow** — 감지 이벤트 → incident → 비상구역/no-go → 로봇 hold/우회 → 관리자 승인 해제 → health 점검 → 재할당을 구현한다.
- [ ] `FMS-P0-09` **실데이터 관제 UI 연결** — `robo_control`의 기능성 화면을 Gateway/MySQL/RMF/MediaMTX의 실데이터로 교체하고 시뮬레이션 데이터 생성을 운영 모드에서 끈다.

### 2.4 로봇팔 P0

- [ ] `ARM-P0-01` **실물 OMX-AI driver와 상태 reporter** — 관절·속도·그리퍼·fault·heartbeat를 일반 PC에서 수집하고 안전한 저수준 명령만 실행한다.
- [ ] `ARM-P0-02` **고정캠·손목캠 송신기** — 일반 PC마다 H.264 `fixed_n`, `wrist_n` stream을 MediaMTX에 게시한다.
- [ ] `ARM-P0-03` **카메라·hand-eye·ArUco 보정 파이프라인** — intrinsics, distortion, marker size, shelf→camera→arm transform을 버전 관리한다.
- [ ] `ARM-P0-04` **QR/DB/marker authorization gate** — 최신성, 반복 검출, ID 일치, lock, robot health를 통과한 1회용 authorization만 허용한다.
- [ ] `ARM-P0-05` **결정론적 safety supervisor** — workspace, joint, speed, collision, action TTL, heartbeat를 매 action마다 검사하고 네트워크 없이도 정지한다.
- [ ] `ARM-P0-06` **규칙 기반 이동과 ACT 경계 구현** — 관측·pre-grasp/pre-place는 규칙 기반, 미세 `pick/place_shelf/place_basket`만 ACT로 실행한다.
- [ ] `ARM-P0-07` **Pinky–로봇팔 인계 handshake** — 양쪽 ready, 로봇 도킹 pose, 적재 시작/완료/실패, timeout/abort를 job step과 연결한다.

## 3. Pinky-Pro 상세 체크리스트

| 체크 | 우선순위 | ID | 기능 | 현재 상태와 구현 근거 |
|---|---|---|---|---|
| [x] | P0 | `PINKY-01` | `cmd_vel` 차동 구동과 RPM 제한 | `pinky_pro/pinky_bringup/pinky_bringup/bringup.py:104`, `pinky_pro/pinky_bringup/pinky_bringup/dynamixel_driver.py:59` |
| [x] | P0 | `PINKY-02` | encoder odometry, TF, joint state | `pinky_pro/pinky_bringup/pinky_bringup/bringup.py:127` |
| [x] | P0 | `PINKY-03` | RPLIDAR 기동과 `/scan` | `pinky_pro/pinky_bringup/launch/bringup_robot.launch.xml:12` |
| [x] | P0 | `PINKY-04` | SLAM, AMCL, Nav2 goal 주행·costmap 회피 | `pinky_pro/pinky_navigation/launch`, `pinky_pro/pinky_navigation/params/nav2_params.yaml` |
| [x] | P1 | `PINKY-05` | 웹에서 map/pose/path/costmap 확인과 goal 취소 | `pinky_pro/pinky_navigation/scripts/nav2_web_server.py` |
| [x] | P1 | `PINKY-06` | 배터리 퍼센트·전압 5초 발행 | `pinky_pro/pinky_bringup/pinky_bringup/battery_publisher.py` |
| [ ] 부분 구현 | P0 | `PINKY-07` | FMS TCP 연결·telemetry·경로·hold | Gazebo agent에만 있음: `control_system/robo_pinky/src/robo_pinky_agent/robo_pinky_agent/control_link.py`, `control_system/robo_pinky/src/robo_pinky_agent/robo_pinky_agent/agent_node.py`; 실물 `pinky_pro`에 없음 |
| [ ] 부분 구현 | P0 | `PINKY-08` | 관제 단절 즉시 정지와 backoff 재접속 | 시뮬레이션 구현: `control_system/robo_pinky/src/robo_pinky_agent/robo_pinky_agent/control_link.py:97`, `control_system/robo_pinky/src/robo_pinky_agent/robo_pinky_agent/agent_node.py:169`; 실물 bringup 미연결 |
| [ ] 부분 구현 | P0 | `PINKY-09` | 라이다 전방 장애물 최우선 정지 | Nav2 costmap은 구현. 별도 local gate는 Gazebo `control_system/robo_pinky/src/robo_pinky_agent/robo_pinky_agent/agent_node.py:157,209`에만 있음 |
| [ ] 미구현 | P0 | `PINKY-10` | job/step 명령 ACK·멱등성·TTL·결과 | 현재 TCP protocol은 ACK와 idempotency가 없음: `control_system/robo_control/lib/core/robot_link.dart` |
| [ ] 미구현 | P0 | `PINKY-11` | 통신 단절 시 작업 ID·마지막 안전 단계 로컬 저장 | 관련 구현 없음 |
| [ ] 미구현 | P0 | `PINKY-12` | 실물 H.264→MediaMTX 송신 | Gazebo ROS image bridge만 존재: `pinky_pro/pinky_gz_sim/launch/launch_sim.launch.xml` |
| [ ] 미구현 | P0 | `PINKY-13` | camera/FPS/frame/timestamp health와 freeze 감지 | 관련 구현 없음 |
| [ ] 부분 구현 | P1 | `PINKY-14` | IMU 기반 미끄럼·위치 보정 | IMU publisher만 존재: `pinky_pro/pinky_imu_bno055/src/main_node.cpp`; Nav2 fusion 없음 |
| [ ] 부분 구현 | P0 | `PINKY-15` | 초음파·IR 안전 센서 통합 | publisher만 존재하고 기본 launch/costmap 미연결: `pinky_pro/pinky_sensor_adc/src/main_node.cpp` |
| [ ] 미구현 | P0 | `PINKY-16` | 사람 검출 결과에 따른 감속·정지·안전거리 | 사람/비사람·pose·tracking runtime 없음 |
| [ ] 미구현 | P1 | `PINKY-17` | 정밀 도킹과 위치·자세 보정 | ArUco/dock controller 없음 |
| [ ] 부분 구현 | P0 | `PINKY-18` | 20% 절전·10% 안전 종료 후 충전 복귀 | `control_system/robo_control/lib/core/fleet_engine.dart:2285`와 Gazebo battery model에만 있음. 실물 Pinky에는 저전압 로그만 있음 |
| [ ] 부분 구현 | P1 | `PINKY-19` | 비상 LED/LCD 상태 표시 | generic service만 있음: `pinky_pro/pinky_led/pinky_led/led_server.py`, `pinky_pro/pinky_emotion/pinky_emotion/emotion_server.py`; 상태 머신 연결 없음 |
| [ ] 미구현 | P0 | `PINKY-20` | 비상 부저와 관리자 해제 전 latch | 부저 코드 없음 |
| [ ] 미구현 | P1 | `PINKY-21` | 포장대 작업자/점유 인식과 다른 포장대 선택 | 관련 perception·mission 코드 없음 |
| [ ] 미구현 | P1 | `PINKY-22` | 바구니 고정·물품 하차 actuator | 관련 하드웨어 제어 없음 |
| [ ] 미구현 | LOW | `PINKY-W01` | load cell, 최대 적재량, 무게 기반 완료 판정 | 후순위; 현재 ADC는 거리·배터리용 |

## 4. DB 상세 체크리스트

### 4.1 현재 실제 구현

| 체크 | 우선순위 | ID | 기능 | 현재 상태와 구현 근거 |
|---|---|---|---|---|
| [x] | P1 | `DB-01` | SQLite migration, WAL, FK, transaction | `control_system/robo_core/lib/data/app_database.dart:20,52,59,77` |
| [x] | P0 | `DB-02` | robot master와 최신 telemetry | `control_system/robo_core/lib/data/app_database.dart:98,113`, `control_system/robo_core/lib/data/sqlite_repositories.dart` |
| [x] | P0 | `DB-03` | lot 재고, 예약 수량 제약, FEFO index | `control_system/robo_core/lib/data/app_database.dart:144`, `control_system/db/schema.sql:93` |
| [x] | P0 | `DB-04` | 주문·라인과 작업·작업 단계 저장 | `control_system/robo_core/lib/data/app_database.dart:182,199,230,291` |
| [x] | P0 | `DB-05` | append 성격의 stock move 원장 | `control_system/robo_core/lib/data/app_database.dart:162`, `control_system/robo_core/lib/data/sqlite_repositories.dart` |
| [x] | P1 | `DB-06` | event·incident·counter 영속화 | `control_system/robo_core/lib/data/app_database.dart:244,259,277` |
| [x] | P1 | `DB-07` | SQLite 재기동 복원과 재고 원자성 테스트 코드 | `control_system/robo_core/test/database_test.dart` |
| [ ] 부분 구현 | P0 | `DB-08` | MySQL DDL | `control_system/db/schema.sql`은 존재하지만 SQLite v2 복제이며 목표 v3와 다름 |
| [ ] 부분 구현 | P1 | `DB-09` | SQLite→MySQL migration | `control_system/db/migrate_sqlite_to_mysql.py`; 1회 전체 재적재 도구이며 runtime repository가 아님 |

### 4.2 v3 목표 대비 남은 기능

- [ ] `DB-10` `locations`와 parent hierarchy, pose, RMF waypoint, 온도 구역 상태.
- [ ] `DB-11` `map_features`의 fiducial, obstacle, bottleneck, door, no-go metadata.
- [ ] `DB-12` mobile/arm 공통 `devices`와 capability/control mode.
- [ ] `DB-13` `jobs`/`job_items`/`job_steps` v3 상태와 RMF task ID, policy name/version.
- [ ] `DB-14` `reservations`의 exclusive/bottleneck/time-slot lock과 expiry.
- [ ] `DB-15` `device_states`의 health, heartbeat, details JSON과 current job step.
- [ ] `DB-16` `integration_messages`의 inbound/outbound, channel, ACK, retry, dead-letter.
- [ ] `DB-17` `incidents`의 severity, 위치, raised/acknowledged/resolved 작업자와 승인 이력.
- [ ] `DB-18` append-only `operation_events`의 actor/device/job/step/incident, safety decision, confidence, payload.
- [ ] `DB-19` 영상·rosbag·episode·dataset·model `artifacts`와 SHA-256/URI metadata.
- [ ] `DB-20` API-only write boundary. 현재 consumer app과 관제는 같은 SQLite 파일을 직접 공유함: `control_system/README.md:54`.
- [ ] `DB-21` 시간 기준 확정. 데이터 사전의 UTC, setup의 MySQL `+09:00`, 현재 migration의 local DATETIME 정책이 충돌함.
- [ ] `DB-22` `trihouse_fms` DB명·v3 스키마로 통일. 현재 SQL은 `robosapiens` v2임.

## 5. 관제시스템 상세 체크리스트

### 5.1 현재 구현된 기능

| 체크 | 우선순위 | ID | 기능 | 현재 상태와 구현 근거 |
|---|---|---|---|---|
| [x] | P0 | `FMS-01` | 주문 접수와 출고 task 전개 | `control_system/robo_control/lib/core/fleet_engine.dart:1521,2779` |
| [x] | P0 | `FMS-02` | FEFO lot 선택과 긴급도·납기·거리 scheduling | `control_system/robo_control/lib/core/scheduler.dart:72,178`, `control_system/robo_control/lib/core/fleet_engine.dart:1147,1598` |
| [x] | P0 | `FMS-03` | task lease 단일 소유권과 TTL | `control_system/robo_control/lib/core/coordination.dart:8`, `control_system/robo_control/lib/core/fleet_engine.dart:119,1638` |
| [x] | P1 | `FMS-04` | 메모리 resource 단일 점유 | `control_system/robo_control/lib/core/coordination.dart:54`, `control_system/robo_control/lib/core/fleet_engine.dart:1853` |
| [x] | P0 | `FMS-05` | 입고 완료 재고 반영과 출고 차감 | `control_system/robo_control/lib/core/fleet_engine.dart:2033,2067`; `control_system/robo_control/test/operations_test.dart` |
| [x] | P0 | `FMS-06` | TCP 8788 robot/arm 연결, telemetry, path/hold/speed/charge/load | `control_system/robo_control/lib/core/robot_link.dart:24,161,283,308,318,338` |
| [x] | P0 | `FMS-07` | 링크 단절 시 task 회수·배차 제외 | `control_system/robo_control/lib/core/fleet_engine.dart:900` 부근; `control_system/robo_control/test/robot_link_test.dart:201` |
| [x] | P1 | `FMS-08` | 정체 감지 후 중앙 경로 재계산·재queue | `control_system/robo_control/lib/core/fleet_engine.dart:769` |
| [x] | P0 | `FMS-09` | 20% 절전·10% 충전 복귀·재할당 정책 | `control_system/robo_control/lib/core/fleet_engine.dart:2285`; 현재 실물 연동은 부분적 |
| [x] | P0 | `FMS-10` | incident, global E-stop, 해제, hold 하달 | `control_system/robo_control/lib/core/fleet_engine.dart:2470,2550,2576`; `control_system/robo_control/test/robot_link_test.dart:177` |
| [x] | P1 | `FMS-11` | 작업자 거리 기반 보호/경고 field 시뮬레이션 | `control_system/robo_control/lib/core/fleet_engine.dart:1016,2252`; 실제 vision 입력은 없음 |
| [x] | P1 | `FMS-12` | 수동 robot 회수·재개, task 취소·재할당 | `control_system/robo_control/lib/core/fleet_engine.dart:2923,2937,2945,2956` |
| [x] | P1 | `FMS-13` | dashboard/map/robot/task/inventory/safety/event UI | `control_system/robo_control/lib/ui/pages` |
| [x] | P1 | `FMS-14` | 처리량·성공률·FEFO·배터리·재할당 지표 | `control_system/robo_control/lib/core/fleet_engine.dart:2963`, `control_system/robo_control/lib/ui/pages/dashboard_page.dart` |
| [x] | P1 | `FMS-15` | RMF API map/robot/task/door/lift/alert UI client | `control_system/openrmf_app/lib/src/rmf_api.dart`, `control_system/openrmf_app/lib/src/controller.dart` |
| [x] | P2 | `FMS-16` | RMF warehouse map/nav graph 파일 | `control_system/rmf_maps/warehouse` |

### 5.2 실제 Trihouse 운영에 남은 기능

- [ ] 부분 구현 `FMS-17` **두 관제 앱 통합** — `robo_control`의 물류 정책과 `openrmf_app`의 RMF 조작이 서로 연결되지 않는다.
- [ ] 부분 구현 `FMS-18` **warehouse RMF 실행 구성** — 현재 launch는 office/tinyRobot demo: `control_system/openrmf/launch/office_web.launch.xml`.
- [ ] 미구현 `FMS-19` **FastAPI/MySQL Gateway** — setup 문서의 requirements와 실행 절차는 있으나 최신 main에 서버 소스가 없다.
- [ ] 미구현 `FMS-20` **명령 ACK·멱등·내구성 queue** — TCP sequence는 path에만 있고 수신 ACK, 재전송, persistent outbox가 없다.
- [ ] 부분 구현 `FMS-21` **입고 상세 workflow** — simulation task는 있지만 바코드 재스캔, 바구니 검수, 양 로봇 완료 barrier, 통신 복구 상태 대조가 없다.
- [ ] 부분 구현 `FMS-22` **출고 상세 workflow** — FEFO/긴급/부분 성공은 있으나 60초 사용자 선택, staging 확정, 포장대 작업자·하차 확인이 없다.
- [ ] 부분 구현 `FMS-23` **로봇팔 handshake** — `load/loaded/loadFailed/abort`는 있으나 QR·marker authorization, 양쪽 ready, 실제 파지·배치 검증이 없다.
- [ ] 부분 구현 `FMS-24` **비상 workflow** — manual/simulated incident는 있으나 카메라 감지, 증거 payload, 마지막 안전 단계 기록, 관리자 권한 승인, 복구 health check가 없다.
- [ ] 미구현 `FMS-25` **MediaMTX·RTSP/SRT·원격 녹화** — 저장소에서 관련 구성 없음.
- [ ] 미구현 `FMS-26` **QR·ArUco runtime worker** — 저장소에서 decoder·PnP·observation API 없음.
- [ ] 미구현 `FMS-27` **YOLO runtime service** — `vision_perception/data_collection/Camera_check_&_Slicing_.ipynb`, `vision_perception/augmentation/generate_augmentation_candidates.py`, `vision_perception/augmentation/warehouse_augmentation_preview.ipynb`는 카메라 확인·데이터 절단·증강 준비 코드다. YOLO train/inference server는 없다.
- [ ] 부분 구현 `FMS-28` **실영상 관제** — `control_system/roboapp/lib/ui/live_view.dart`는 local `getUserMedia`이며 robot stream/signaling이 없다.
- [ ] 부분 구현 `FMS-29` **경로·작업 이력** — task 시간/event/현재 telemetry는 저장하지만 robot trace 전체와 job step event를 v3 audit 구조로 저장하지 않는다.
- [ ] 미구현 `FMS-30` **stream/device/worker emergency 통합 health와 alerting**.
- [ ] 미구현 `FMS-31` **역할 기반 관리자 승인·감사** — worker 모델은 있으나 인증·권한·승인 서명이 없다.

## 6. 로봇팔 상세 체크리스트

현재 실제 로봇팔 코드는 없다. `control_system/robo_pinky/src/robo_pinky_agent/robo_pinky_agent/arm_node.py`는 Gazebo 궤적·IK 시뮬레이터이며, 스스로 “물리적 파지를 모사하지 않는다”고 명시한다.

| 체크 | 우선순위 | ID | 기능 | 현재 상태와 구현 근거 |
|---|---|---|---|---|
| [ ] 시뮬레이션만 | P1 | `ARM-01` | 관제 `load/abort` 수신과 `loaded/loadFailed/status` 회신 | `control_system/robo_pinky/src/robo_pinky_agent/robo_pinky_agent/arm_node.py`, `control_system/robo_control/lib/core/robot_link.dart:338` |
| [ ] 시뮬레이션만 | P2 | `ARM-02` | IK 기반 joint/gripper 궤적 | `control_system/robo_pinky/src/robo_pinky_agent/robo_pinky_agent/arm_kinematics.py`, `control_system/robo_pinky/src/robo_pinky_agent/robo_pinky_agent/arm_node.py`; 물품 파지는 모사하지 않음 |
| [ ] 설계만 | P0 | `ARM-03` | 고정캠·손목캠 H.264 stream | vision streaming 설계 문서 |
| [ ] 설계만 | P0 | `ARM-04` | QR observation과 DB target double-check | robot-arm 설계 §3 |
| [ ] 설계만 | P0 | `ARM-05` | ArUco pose, camera/hand-eye calibration, marker-to-slot transform | robot-arm 설계 §4 |
| [ ] 설계만 | P0 | `ARM-06` | 규칙 기반 관측·pre-grasp/pre-place 이동 | robot-arm 설계 §5.1 |
| [ ] 설계만 | P0 | `ARM-07` | ACT `pick`, `place_shelf`, `place_basket` | robot-arm 설계 §5.2 |
| [ ] 설계만 | P0 | `ARM-08` | short Action Proposal, authorization, timestamp/TTL | robot-arm 설계 §5.3·5.6 |
| [ ] 설계만 | P0 | `ARM-09` | workspace/joint/speed/collision safety supervisor | robot-arm 설계 §8 |
| [ ] 설계만 | P0 | `ARM-10` | local heartbeat/watchdog와 네트워크 독립 정지 | robot-arm 설계 §2·8 |
| [ ] 미구현 | P0 | `ARM-11` | 실제 OMX-AI USB driver와 joint/gripper feedback | 관련 실물 코드 없음 |
| [ ] 미구현 | P0 | `ARM-12` | 파지 성공 검증, 3회 재시도, 좌표 callback, 최종 실패 보고 | 관련 실물 코드 없음 |
| [ ] 미구현 | P0 | `ARM-13` | Pinky docking/ready 확인 후 안전 적재 | simulation load 신호만 존재 |
| [ ] 미구현 | P1 | `ARM-14` | 사람 작업공간 침입 감지와 이탈 후 승인 재개 | 관련 runtime 없음 |
| [ ] 미구현 | P1 | `ARM-15` | LeRobot v3 episode builder와 영상·RobotState 동기화 | 관련 runtime 없음 |
| [ ] 미구현 | LOW | `ARM-W01` | 무게 기반 파지·적재 교차 검증 | 후순위 |

## 7. SR 01~51 추적표

`SR_12(2)`는 원문 번호를 유지한다. 상태는 위 상세 항목의 현재 판정을 요약한다.

| SR | 주 책임/연결 항목 | 현재 상태 |
|---|---|---|
| SR_01 바코드·QR | `ARM-04`, `FMS-26` | 설계만/미구현 |
| SR_02 물품 DB 자동 저장 | `DB-13`, `FMS-19` | 부분 구현 |
| SR_03 입고 검수 | `FMS-21` | 미구현 |
| SR_04 온도 구역 자동 배정 | `FMS-05`, `DB-10` | simulation 구현, v3 연동 필요 |
| SR_05 유통기한 순서 적재 | `FMS-02` | 출고 FEFO 구현, 입고 적재 순서 미완성 |
| SR_06 빈 선반 앞 번호 배정 | `FMS-21`, `DB-10` | 미구현 |
| SR_07 재고 반영 | `FMS-05`, `DB-03~05` | 구현 |
| SR_08 주문 접수 | `FMS-01` | 구현; 운영 API 미구현 |
| SR_09 작업 할당 | `FMS-02~04` | simulation/TCP 구현, RMF 통합 필요 |
| SR_10 물건 인식 | `ARM-04~05` | 설계만 |
| SR_11 물건 파지 | `ARM-07,11~12` | 설계만/미구현 |
| SR_12 주행로봇 상차 | `ARM-13`, `FMS-23` | simulation만 |
| SR_12(2) 선반 적재 | `ARM-07` | 설계만 |
| SR_13 출고 double-check | `ARM-04` | 설계만 |
| SR_14 marker 인식 | `ARM-05`, `FMS-26` | 설계만/미구현 |
| SR_15 목적지 운반 | `PINKY-04`, `PINKY-07` | Nav2 구현, FMS 종단 연동 필요 |
| SR_16 FEFO 선정 | `FMS-02` | 구현 |
| SR_17 긴급 주문 우선 | `FMS-02` | 구현 |
| SR_18 작업자 요청 우선 | `FMS-02` | simulation 생성만; 실제 요청 API 필요 |
| SR_19 작업 중복 방지 | `FMS-03~04`, `DB-P0-06` | 메모리 구현, DB lock 필요 |
| SR_20 로봇 상태 공유 | `PINKY-07`, `FMS-06`, `DB-P0-05` | simulation/TCP 구현, 실물·v3 필요 |
| SR_21 통합 관제 화면 | `FMS-13~15` | 구현; 실데이터 통합 필요 |
| SR_22 관리자 정지·재배정 | `FMS-10,12` | 구현; 인증·승인 필요 |
| SR_23 저조도 적응 인식 | `FMS-27`, `ARM-03` | dataset/runtime 미구현 |
| SR_24 미끄럼 보정 | `PINKY-14` | 부분 구현 |
| SR_25 Pinky 사람 감지 | `PINKY-16`, `FMS-27` | 미구현 |
| SR_26 Pinky 사람 충돌 방지 | `PINKY-09,16` | 일반 장애물 정지만 부분 구현 |
| SR_27 로봇팔 사람 감지 | `ARM-14` | 미구현 |
| SR_28 로봇팔 충돌 방지 | `ARM-09,14` | 설계만 |
| SR_29 특수상황 안전 주행 | `PINKY-09,17` | 부분 구현 |
| SR_30 위급상황 영상 감지 | `FMS-27` | 미구현 |
| SR_31 비상 알림 | `FMS-24,30` | manual incident만 부분 구현 |
| SR_32 LED·부저 대응 | `PINKY-19~20` | generic LED만 부분 구현 |
| SR_33 관리자 비상 종료 | `FMS-10,31` | 해제 UI 구현, 권한 승인 미구현 |
| SR_34 20% 절전 | `PINKY-18`, `FMS-09` | 관제 simulation 구현, 실물 미완성 |
| SR_35 10% 충전 복귀 | `PINKY-18`, `FMS-09` | 관제 simulation 구현, 실물 미완성 |
| SR_36 배터리 작업 재할당 | `FMS-09` | 구현; v3 job 연동 필요 |
| SR_37 파지 재시도 | `ARM-12` | 미구현 |
| SR_38 좌표 callback | `ARM-12` | 미구현 |
| SR_39 파지 실패 알림 | `ARM-12`, `FMS-23` | simulation protocol만 부분 구현 |
| SR_40 인수인계 준비 확인 | `ARM-13`, `FMS-P0-04` | 미구현 |
| SR_41 인수인계 후 확인 | `ARM-13` | 미구현 |
| SR_42 로봇 간 충돌 방지 | `FMS-04,18`, `DB-P0-06` | simulation 메모리 구현, RMF/DB 통합 필요 |
| SR_43 포장공간 이송 | `PINKY-04`, `FMS-22` | 일반 목적지 이동만 구현 |
| SR_44 포장 준비 완료 알림 | `PINKY-10`, `FMS-22` | 미구현 |
| SR_45 LCD/LED 준비 표시 | `PINKY-19` | generic 표시만 부분 구현 |
| SR_46 작업자 전달 결과 기록 | `FMS-21~22`, `DB-18` | 미구현 |
| SR_47 포장대 사용 중 인식 | `PINKY-21`, `DB-P0-06` | 미구현 |
| SR_48 포장대 작업자 부재 인식 | `PINKY-21`, `FMS-27` | 미구현 |
| SR_49 포장대 대기·재배정 | `FMS-22` | 미구현 |
| SR_50 이동 경로·작업 이력 | `FMS-29`, `DB-18` | 부분 구현 |
| SR_51 작업 상황 송출 | `FMS-13,25,28` | 상태 UI 구현, robot 영상 미구현 |

## 8. SR에 없지만 시나리오·아키텍처에 필요한 체크리스트

### 8.1 입고

- [ ] `INB-01` 바코드 재스캔 실패 시 입고 보류 구역·관리자 확인 요청.
- [ ] `INB-02` 바구니 ID·물품 목록·수량과 입고 DB 교차 검증.
- [ ] `INB-03` 선반 위치 예약과 대체 선반·입고 대기 queue.
- [ ] `INB-04` Pinky와 로봇팔 예상 완료 시간을 반영한 동시 할당.
- [ ] `INB-05` 동일 시간·공간 경로 충돌 검사와 시간/경로 재계획.
- [ ] `INB-06` 하차 위치 점유 확인과 안전 대기.
- [ ] `INB-07` Pinky 하차 준비와 로봇팔 가능 상태 barrier.
- [ ] `INB-08` 센서·인식 불일치 때 관리자 승인까지 두 로봇 안전 대기.
- [ ] `INB-09` 두 로봇의 하차 완료 신호 barrier.
- [ ] `INB-10` 통신 장애 시 로컬 job/마지막 완료 단계 저장과 복구 후 상호 대조.
- [ ] `INB-11` 마지막 확인 단계부터 멱등 재개.
- [ ] `INB-12` DB update 재시도와 반복 실패 시 완료 보류 기록.
- [ ] `INB-W01` 바구니 무게 0 및 영상 결과 교차 확인 — `LOW/후순위`.

### 8.2 출고

- [ ] `OUT-01` 재고 부족 시 부분출고/전체취소 60초 사용자 선택.
- [ ] `OUT-02` 확정 전 staging과 긴급→유통기한 순 정렬.
- [ ] `OUT-03` Pinky·로봇팔 병렬 시작과 양쪽 ready barrier.
- [ ] `OUT-04` 목적지 도착 후 위치·자세 검증과 재도킹.
- [ ] `OUT-05` 로봇팔 30초 무응답 시 실패 반영과 Pinky 대기소 복귀.
- [ ] `OUT-06` 포장대 작업자 확인, 다른 포장대 선택, 모두 부재 시 작업자 배치 요청.
- [ ] `OUT-07` 포장 불가 알림 300초와 추가 대기 120초 timeout.
- [ ] `OUT-08` 작업자 포장 완료/전달 성공 입력과 주문 결과 확정.
- [ ] `OUT-09` 성공·부분출고·피킹 실패·적재 실패별 재고·이력 반영.
- [ ] `OUT-W01` 최대 적재량 초과 작업 분할 — `LOW/후순위`.

### 8.3 비상상황

- [ ] `EMG-01` Pinky camera 대상 위치·자세·움직임 일정 frame 추적.
- [ ] `EMG-02` 사람/비사람, 정상/비정상 자세, 무동작 판정.
- [ ] `EMG-03` 정적/동적 장애물 구분과 안전거리 재확인.
- [ ] `EMG-04` 위급 의심 알림에 zone, camera/robot ID, 위치, 시각, confidence, evidence 포함.
- [ ] `EMG-05` 비상구역과 no-go zone 생성, 진입 로봇 정지, 주변 로봇 우회.
- [ ] `EMG-06` 영향 작업의 마지막 안전 단계와 물품·적재 상태 기록.
- [ ] `EMG-07` 인계 가능한 작업 재할당, 현장 확인 필요 작업 보류.
- [ ] `EMG-08` 관리자 승인 전 비상 latch와 진입 차단 유지.
- [ ] `EMG-09` 해제 후 위치·적재·통신·센서 self-check 및 정비 상태 결정.
- [ ] `EMG-10` 발생 시간, 대응 결과, 작업 인계 결과 감사 기록.

### 8.4 영상·통신

- [ ] `VIS-01` 원격 6개 H.264 stream을 720p 10–15 fps로 10분 유지.
- [ ] `VIS-02` 영상은 RTSP/SRT, 상태·결과는 ROS 2/API로 분리.
- [ ] `VIS-03` Pinky·일반 PC 영상 파일 생성 0건, 제한된 RAM 최신 frame buffer만 사용.
- [ ] `VIS-04` RTX 4060 원본 stream 녹화·중계와 QR/ArUco 저주기 decode.
- [ ] `VIS-05` 영상·RobotState·action timestamp 목표 ±50 ms 동기화.
- [ ] `VIS-06` 1초 DEGRADED, 3초 DISCONNECTED, RECOVERING, 5초 안정 HEALTHY 판정.
- [ ] `VIS-07` freeze, USB 제거, publisher 종료, Wi-Fi 단절과 policy heartbeat timeout 감지.
- [ ] `VIS-08` 단절 시 action queue/authorization 폐기와 last frame 재사용 금지.
- [ ] `VIS-09` 재접속 후 새 QR·ArUco·DB 검증과 authorization 전 재개 금지.

## 9. 문서·코드 간 충돌과 결정 필요 사항

- [ ] `DEC-01` **DB 표준** — 데이터 사전은 `trihouse_fms` v3 15개 table, 최신 관제 main은 `robosapiens` v2 12개 table이다.
- [ ] `DEC-02` **시간대** — v3 사전은 UTC DATETIME, setup은 MySQL session `+09:00`, 현재 migration은 local datetime을 보존한다.
- [ ] `DEC-03` **관제 UI** — 물류 정책 UI `robo_control`과 RMF UI `openrmf_app`이 별개다.
- [ ] `DEC-04` **RMF 대상** — repository에 warehouse map은 있지만 실행 launch는 office/tinyRobot demo다.
- [ ] `DEC-05` **Pinky 경로 실행** — 기본 Pinky는 Nav2, `robo_pinky` agent는 독자 waypoint follower다. 실물은 Nav2 action adapter를 권장한다.
- [ ] `DEC-06` **사람 인식 위치** — SR은 Pinky/로봇팔 감지를 요구하고 영상 설계는 중앙 GPU 처리를 제안한다. 근접 정지는 로컬 센서, 의미 인식은 중앙 worker로 분리한다.
- [ ] `DEC-07` **로봇팔 범위** — Gazebo OMX agent는 실제 물리 파지 구현이 아니므로 실제 로봇팔 완료 근거로 사용하지 않는다.
- [ ] `DEC-08` **DB 접근 경계** — 현재 app은 SQLite 파일을 공유하지만 v3는 FMS API만 DB에 쓰도록 요구한다.

## 10. 검증 상태

- 정적 파일·코드 조사는 완료했다.
- 현재 환경에는 `flutter` 명령이 없어 `flutter test`와 `flutter analyze`를 재실행하지 못했다. 저장소에는 `robo_core`, `robo_control`, `openrmf_app` 테스트 코드와 이전 build artifact가 있지만 이번 판정은 테스트 통과를 가정하지 않는다.
- 실물 Pinky, 카메라, OMX-AI, MediaMTX, MySQL, Open-RMF runtime의 하드웨어·통합 시험은 수행하지 않았다.
