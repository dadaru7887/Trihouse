# Trihouse 전체 시스템 Runbook 설계

## 1. 목적

`docs/guideline/run/`에 Trihouse 전체 시스템을 구성요소별·시나리오별로 실행하고
검증하는 운영 가이드를 만든다. 처음 보는 작업자도 여러 터미널을 순서대로 열어
Control System UI, FMS Gateway, MySQL, Open-RMF, Gazebo 또는 실물 Pinky, PC1·PC2
Vision을 같은 결과로 재현할 수 있어야 한다.

이 문서 집합은 다음 질문에 즉시 답해야 한다.

- 어느 호스트에서 어느 터미널을 열어야 하는가?
- 각 터미널에서 어떤 명령을 어떤 순서로 실행하는가?
- 명령이 참조하는 설정·launch·Compose·코드 파일은 무엇인가?
- 정상 상태를 ROS topic, API, DB, UI 중 어디에서 확인하는가?
- 어떤 결과가 성공이고, 어떤 상태에서 즉시 중단해야 하는가?
- 테스트 DB와 운영 DB가 섞이지 않았음을 어떻게 증명하는가?
- 전체 시스템을 어떤 역순으로 안전하게 종료하는가?

## 2. 고정 결정

### 2.1 Control System 기준 경로

시뮬레이션과 실물 모두 최종 승격 대상인 `control_system_root`를 사용한다.
`control_system_test`는 runbook의 실행 기준으로 사용하지 않는다. 승격 전에는
`control_system_root`가 준비되지 않았다는 이유를 명시하고 해당 Gate를 `blocked`로
기록한다. 다른 경로로 암묵적으로 대체하지 않는다.

### 2.2 DB 격리

시뮬레이션, 모듈 테스트, 통합 테스트 및 실물 리허설은
`compose.db_test.yaml`의 일회용 MySQL을 사용한다.

| 구분 | Compose | host:port | 저장 방식 | 용도 |
|---|---|---|---|---|
| 테스트 | `compose.db_test.yaml` | `127.0.0.1:3307` | tmpfs | 시뮬레이션·실물 리허설 |
| 운영 | `compose.db.yaml` 또는 PC1 운영 DB | 운영 설정의 `3306` | persistent volume | 승인된 운영 검증 |

두 환경 모두 데이터베이스 이름은 `trihouse_fms`이고 기준 스키마는
`db/schema_mysql.sql`이다. 이름을 같게 유지해 실제 스키마 정합성을 검증하되,
endpoint와 자격증명으로 환경을 분리한다.

시뮬레이션 runbook에는 `compose.db.yaml` 시작 명령을 넣지 않는다. 테스트 Gateway는
`FMS_DB_HOST=127.0.0.1`, `FMS_DB_PORT=3307`, `FMS_DB_USER=fms_gateway`,
`FMS_DB_PASSWORD=test_gateway_password`를 명시한다. 시작 전 실제 연결 endpoint를
출력하고, port가 `3306`이면 시험을 중단한다.

UI는 MySQL을 직접 실행하거나 접속하지 않는다. 맵·Waypoint·작업·이력은 해당 환경의
FMS Gateway API를 통해 읽고 쓴다.

### 2.3 Vision 및 제어 권한

PC1은 MediaMTX 영상 수신·중계·보존과 FMS Gateway/MySQL을 맡고, PC2는 YOLO·VLM
추론을 맡는다. PC2에 DB 자격증명을 배포하지 않는다. Vision 결과는 관측값으로만
Gateway/Control Tower에 전달하며 `/cmd_vel`을 직접 발행하지 않는다. Nav2가 주행을
계획하고 Pinky Safety Supervisor가 최종 속도와 정지를 제한한다.

## 3. 문서 구조

```text
docs/guideline/run/
├── README.md
├── common/
│   ├── 00_system_topology.md
│   ├── 01_terminal_layout.md
│   ├── 02_environment_profiles.md
│   ├── 03_database_isolation.md
│   ├── 04_network_and_ports.md
│   └── 05_build_and_install.md
├── component/
│   ├── 10_test_database.md
│   ├── 11_fms_gateway.md
│   ├── 12_control_system_ui.md
│   ├── 13_open_rmf.md
│   ├── 14_pinky_adapter.md
│   ├── 15_pinky_runtime.md
│   └── 16_vision_pc1_pc2.md
├── simulation/
│   ├── 20_simulation_preflight.md
│   ├── 21_rmf_gazebo_startup.md
│   ├── 22_ui_to_simulated_pinky.md
│   ├── 23_order_and_task_test.md
│   ├── 24_battery_and_db_test.md
│   └── 25_simulation_shutdown.md
├── physical/
│   ├── 30_physical_safety.md
│   ├── 31_p0_connection_test.md
│   ├── 32_p1_no_motion_test.md
│   ├── 33_p2_wheels_up_test.md
│   ├── 34_p3_low_speed_segment.md
│   ├── 35_p4_full_job_test.md
│   ├── 36_p5_vision_test.md
│   └── 37_physical_shutdown.md
├── integration/
│   ├── 40_full_simulation_run.md
│   ├── 41_full_physical_run.md
│   ├── 42_ui_order_to_robot_flow.md
│   └── 43_result_and_database_verification.md
└── reference/
    ├── terminal_commands.md
    ├── ros_interfaces.md
    ├── api_endpoints.md
    ├── database_queries.md
    ├── expected_state_values.md
    └── troubleshooting.md
```

## 4. 계층별 책임

### 4.1 `README.md`

사용자의 목적에서 첫 실행 문서로 연결한다.

- 구성요소 하나만 확인: `component/`
- UI에서 가상 Pinky 주문·주행 확인: `simulation/`
- 실물 Pinky 안전 검증: `physical/`
- 전체 시스템 실행: `integration/`
- 오류·상태값·조회 명령 확인: `reference/`

### 4.2 `common/`

모든 시나리오가 공유하는 기준만 둔다. 시스템 책임 계층, 호스트 배치, 터미널 번호,
환경 profile, DB 격리, IP·port, ROS workspace build/source를 설명한다. 실제 업무
시나리오 실행 명령은 넣지 않는다.

### 4.3 `component/`

각 구성요소를 독립적으로 시작하고 health를 증명한다. 다음 단계가 이 문서의 성공을
전제로 삼을 수 있도록 시작, 상태 확인, 종료까지 포함한다.

| 문서 | 주 참조 파일 |
|---|---|
| 테스트 DB | `compose.db_test.yaml`, `db/schema_mysql.sql`, `db/seed_dev.sql` |
| FMS Gateway | `fms_gateway/app/main.py`, `fms_gateway/app/config.py` |
| Control System UI | `control_system_root/rmf_control_ui` |
| Open-RMF | `control_system_root/rmf_maps`, `/home/syw/rmf_ws` |
| Pinky adapter | `trihouse_rmf_bridge/launch/control_system_rmf.launch.py` |
| Pinky runtime | `trihouse_pinky`, Nav2·Fleet·Safety launch |
| Vision | `compose.edge_4060.yaml`, `compose.ai_5080.yaml`, `vision_system` |

### 4.4 `simulation/`

`control_system_root + Open-RMF + Gazebo Pinky + test Gateway + test DB` 조합만 다룬다.
DB와 Gateway를 먼저 시작하고, RMF/Gazebo, adapter, UI 순서로 연결한다. UI 주문 한 건을
발행한 뒤 작업 배차, 배터리 상태, Waypoint segment, job/step/attempt/event DB 기록을
확인한다. 종료는 UI 입력 차단, worker/adapter, RMF/Gazebo, Gateway, test DB 역순이다.

### 4.5 `physical/`

실물 시험은 P0~P5 Gate를 독립 문서로 나눈다.

| Gate | 시험 | 진입 조건 | 핵심 성공 기준 |
|---|---|---|---|
| P0 | 연결 | 전원·네트워크·E-stop 확인 | UI, Gateway, RMF, Pinky heartbeat 정상 |
| P1 | 무구동 | P0 성공 | pose·battery·sensor 상태 정상, 모터 명령 없음 |
| P2 | 바퀴 부상 | P1 성공, 로봇 고정 | 방향·정지·단일 `/cmd_vel` 권한 정상 |
| P3 | 저속 segment | P2 성공, 안전구역 확보 | 인접 Waypoint 이동·정지·결과 기록 정상 |
| P4 | 전체 Job | P3 성공 | 모든 Step 및 DB event/attempt 일관성 정상 |
| P5 | Vision | P4 성공, PC1·PC2 준비 | H.264 수신·추론 관측·안전 gate 정상 |

각 Gate는 필요한 작업자, E-stop 담당자, 속도 상한, 즉시 중단 조건과 결과 기록을
명시한다. 실패한 Gate 다음 단계는 실행하지 않는다.

### 4.6 `integration/`

검증된 구성요소를 전체로 올리는 정확한 순서만 제공한다. 구성요소 설치 설명을 반복하지
않고 해당 component 문서의 완료 조건을 사전 조건으로 링크한다. 시뮬레이션과 실물을
분리하고, UI 주문부터 RMF task, Pinky 실행, Gateway event, DB projection까지의 추적
식별자를 한 표로 연결한다.

### 4.7 `reference/`

실행 중 빠르게 찾는 조회 명령과 정상값을 둔다. 동일 명령의 여러 변형을 만들지 않고
canonical command 하나와 환경별 치환값을 제공한다.

## 5. 터미널 배치

문서의 터미널 번호는 다음 의미로 고정한다.

| 터미널 | 기본 호스트 | 책임 |
|---:|---|---|
| 1 | Control/PC1 | test 또는 production MySQL |
| 2 | Control/PC1 | FMS Gateway |
| 3 | RMF host | Open-RMF·Gazebo |
| 4 | RMF host | RMF Gateway Worker·Pinky adapter |
| 5 | UI host | Control System UI |
| 6 | RMF/Pinky host | ROS topic·action·TF 관찰 |
| 7 | PC1 | MediaMTX·영상 ingress |
| 8 | PC2 | YOLO·VLM inference |
| 9 | Pinky | Nav2·Fleet·Safety runtime |

한 호스트가 여러 역할을 맡아도 터미널 번호의 논리적 책임은 바꾸지 않는다.

## 6. 모든 runbook의 공통 형식

각 실행 문서는 다음 12개 절을 같은 순서로 사용한다.

1. 목적
2. 실행 환경과 호스트
3. 금지 사항
4. 참조 파일
5. 사전 점검
6. 터미널별 실행 명령
7. 예상 출력
8. ROS/API/UI/DB 상태 확인
9. 성공 기준
10. 실패 및 즉시 중단 기준
11. 안전 종료 명령
12. 결과 기록

명령은 복사 가능한 Bash block으로 작성하고, block 위에 `Terminal N — 역할`을 붙인다.
각 시작 명령 바로 다음에 상태 확인 명령을 둔다. 단순히 “정상인지 확인”이라고 쓰지 않고
명령, 정상 출력의 핵심 필드와 실패 시 이동할 troubleshooting 항목을 명시한다.

## 7. 환경 profile

runbook은 다음 네 profile 이름을 사용한다.

| profile | Robot | DB | 목적 |
|---|---|---|---|
| `module_test` | 없음 또는 fake | test:3307 | 구성요소 단독 검사 |
| `simulation` | Gazebo Pinky | test:3307 | UI·RMF·DB 통합 검사 |
| `physical_rehearsal` | 실물 Pinky | test:3307 | P0~P5 안전 리허설 |
| `physical_operation` | 실물 Pinky | production:3306 | 승인된 이력 보존 시험 |

문서에는 비밀번호 실제값을 저장하지 않는다. 테스트 DB의 저장소 고정 자격증명만
`compose.db_test.yaml` 계약으로 표시하고 운영 비밀값은 로컬 `.env` 또는 서버 secret에서
읽는다.

## 8. 상태 및 결과 검증

각 시나리오는 최소 다음 네 계층을 교차 확인한다.

1. UI: 주문·robot·task 표시
2. ROS/RMF: fleet state, task dispatch, Nav2 action, battery state
3. Gateway API: readiness, job hierarchy, step/event timeline
4. MySQL: `jobs`, `job_steps`, `job_step_attempts`, `operation_events`, device state projection

성공은 UI의 완료 표시 하나만으로 판정하지 않는다. 같은 job/step/attempt 식별자가 API와
DB에 일치하고, terminal 상태가 재기록 또는 역전되지 않아야 한다.

## 9. 오류 처리와 중단 원칙

- 테스트 runbook에서 DB port 3306이 감지되면 즉시 중단한다.
- 필수 ROS topic/action이 없으면 이동 명령을 보내지 않는다.
- `/cmd_vel` 권한이 둘 이상이면 P2 이상을 진행하지 않는다.
- map revision, robot identity 또는 RMF assignment가 일치하지 않으면 task를 claim하지 않는다.
- Vision stream 단절을 “검출 객체 없음”으로 처리하지 않는다.
- 실물 P2~P5에서는 E-stop 담당자가 자리를 비우면 시험을 중단한다.
- 실패 후 재시도 전에 기존 task, adapter, robot motion, DB attempt 상태를 확인한다.

## 10. 문서 검증 방법

작성된 runbook은 다음 기준으로 검토한다.

- 모든 상대 링크 대상이 존재한다.
- 모든 절대 경로는 CLI argument로 대체할 수 있거나 기준 경로임을 명시한다.
- simulation 문서에 `compose.db.yaml`, port 3306, 운영 DB 비밀번호가 없다.
- physical operation 이외 문서가 persistent DB를 시작하지 않는다.
- `control_system_test`를 실행 기준으로 참조하지 않는다.
- `control_system_root`와 map, fleet, nav graph 경로가 launch CLI 계약과 일치한다.
- 각 시작 명령에 대응하는 health 확인과 종료 명령이 있다.
- ROS topic, API endpoint와 DB table 이름이 현재 코드와 일치한다.
- 보호 경로인 `control_system/**`, `pinky_pro/**`의 수정 명령이 없다.

정적 검토 후 사용자가 터미널별로 실행하며 실제 출력과 차이를 기록한다. 실제 장비나 서버가
없어 실행하지 못한 명령은 성공으로 표현하지 않고 `not_run` 또는 `blocked`로 표시한다.

## 11. 범위 제외

첫 문서화 단계에서는 다음을 만들지 않는다.

- 전체 시스템을 무조건 한 번에 시작하는 새로운 shell script
- 운영 DB 자격증명 또는 실제 서버 secret
- 실물 속도·제동거리의 미측정 최종값
- Vision 모델 정확도 또는 SR52 완료 주장
- `control_system`과 `pinky_pro`의 코드 변경

반복 실행으로 검증된 명령만 이후 별도 자동화 계획에서 script 또는 launch로 승격한다.
