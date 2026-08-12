# Gazebo·Open-RMF·MySQL Pinky 통합 시뮬레이션 설계

## 1. 목적

한 PC에서 Gazebo, Pinky ROS 2 노드, Open-RMF, Control Tower, FMS Gateway와
MySQL을 함께 실행해 다음 수직 흐름을 검증한다.

```text
Gazebo 센서·Nav2 상태
→ Pinky RobotStatus
→ 루프백 TCP 상태 보고
→ FMS Gateway 검증·MySQL 반영
→ Open-RMF 작업 제출·배정
→ Pinky 이동 수행
→ RMF·Pinky 실행 결과 반영
→ 업무 단계·실행 시도·운영 이벤트 확인
```

단순히 DB에 임의 행을 넣는 시험이 아니라 실제 배포에서 사용할 책임 경계와 통신
경로를 같은 PC의 루프백 통신으로 검증하는 것이 목표다.

## 2. 고정 결정

### 2.1 보호 대상

다음 경로는 읽기만 허용하며 코드와 설정을 변경하지 않는다.

- `/home/syw/Trihouse/control_system`
- `/home/syw/Trihouse/pinky_pro`

`control_system`은 실행 시 기본 입력 경로다. 통합 launch는 이 디렉터리의 파일을 직접
읽을 수 있지만 world 패치, nav graph 생성, 로그·PID·schedule 상태 기록을 포함한 어떤
쓰기 작업도 하지 않는다. 격리 시험이 필요할 때만 명시적인 복사 도구로
`/home/syw/Trihouse/control_system_test`에 새 복사본을 만들고 launch의 CLI 경로를 그쪽으로
바꾼다. 복사 도구는 `move`, 원본 삭제, 기존 대상 덮어쓰기를 허용하지 않는다.

새 구현은 `trihouse_interfaces`, `trihouse_pinky`, `trihouse_rmf_bridge`,
`trihouse_omx_adapter`, `control_tower`, `fms_gateway`, `db`, 루트 Compose와
`docs` 안에서만 수행한다.

### 2.2 장비 식별자

장비 식별자는 DB, ROS, RMF, TCP, UI read model과 측정 로그에서 동일한 값을 쓴다.

| 장비 | 통합 식별자 | 장비 유형 | fleet |
| --- | --- | --- | --- |
| Pinky 1 | `PK_01` | `mobile` | `project1_pinky` |
| Pinky 2 | `PK_02` | `mobile` | `project1_pinky` |
| OMX 1 | `OMX_01` | `arm` | `omx_fleet` |
| OMX 2 | `OMX_02` | `arm` | `omx_fleet` |

`devices.device_id`, ROS `robot_id`·`omx_id`, RMF robot name과 모든 장비 FK에
위 값을 사용한다. `PK-01`, `PINKY-01`, `OMX-01` 같은 기존 표기를 runtime에서
호환 변환하지 않는다. 마이그레이션과 seed에서 한 번 변환하고 이후에는 잘못된 ID를
거부한다.

`fleet_name`은 장비 ID가 아니다. `project1_pinky`는 `project1_pinky_config.yaml`에
선언된 실제 Open-RMF fleet이고,
`omx_fleet`은 OMX 장비를 묶는 FMS 논리 그룹이다.

### 2.3 control_system project1 입력 계약

기본 프로젝트는 `/home/syw/Trihouse/control_system/rmf_maps/project1`이다. 설정의 단일
원본을 한 파일로 잘못 합치지 않고 다음처럼 책임을 나눈다.

| 입력 | 원본으로 인정하는 필드 |
| --- | --- |
| `fleet.yaml` | robot ID, 표시 이름, kind, model, `gz_name`, zones, charger/station, spawn pose |
| `project1_pinky_config.yaml` | RMF fleet 이름, 이동 한계, footprint/vicinity, battery·mechanical 계수, charger 매핑 |
| `project1.building.yaml` | level, waypoint·lane·설비 위치의 편집 원본 |
| `nav_graphs/0.yaml` | RMF가 실제 실행할 waypoint·lane·charger graph |
| `nav2_map/project1.yaml` | Nav2 occupancy map과 원점·해상도 |
| `project1.world` | Gazebo world 입력 |
| `project1_gz_bridge.yaml` | Gazebo↔ROS topic 연결 |
| `robots/<ID>/*` | 개별 robot spawn, Nav2, URDF와 namespace 설정 |

같은 값이 둘 이상의 파일에 있을 때 무조건 한쪽을 덮어쓰지 않는다. preflight가 ID,
charger, namespace와 waypoint 존재 여부를 교차 검증하고 불일치하면 실행 전에 실패한다.
`fleet.yaml`에 RMF fleet 이름은 없으므로 이를 추측하지 않고
`project1_pinky_config.yaml`에서 읽는다.

현재 확인한 project1 장비 기준은 다음과 같다.

| device_id | kind | model | gz_name | home/station | zones |
| --- | --- | --- | --- | --- | --- |
| `PK_01` | `mobile` | `PINKY-GZ` | `pinky_01` | `충전1` | ambient, chilled, frozen |
| `PK_02` | `mobile` | `PINKY-GZ` | `pinky_02` | `충전2` | ambient, chilled, frozen |
| `OMX_01` | `workcell` | `open_manipulator_x` | `omx_01` | `설비1` | 없음 |
| `OMX_02` | `workcell` | `open_manipulator_x` | `omx_02` | `설비2` | 없음 |

DB의 `device_type`은 project1의 `kind=workcell`을 허용하지 않으므로 동기화 경계에서만
`workcell → arm`으로 명시 변환한다. ID, 이름, model, namespace는 변환하지 않는다.

### 2.4 지도 revision과 시간

- 모든 Trihouse 시뮬레이션의 `map_revision`은 문자열 `"1"`이다.
- map 좌표를 보고하거나 이동 명령을 실행할 때 revision이 `"1"`이 아니면 거부한다.
- 운영 시각은 `Asia/Seoul`, UTC+9로 통일한다.
- 모든 컨테이너에 `TZ=Asia/Seoul`을 설정한다.
- Gateway는 MySQL connection을 얻을 때마다 `SET time_zone = '+09:00'`을 실행한다.
- API의 외부 시각은 `+09:00` 오프셋을 포함한다.

Gazebo의 ROS simulation clock은 운영 시각이 아니다. `device_states.observed_at`에는
FMS Gateway가 메시지를 받은 실제 KST 시각을 넣고 ROS simulation stamp는
`device_states.details.source_stamp`에 보존한다. 실행 시간 학습 지표는 simulation
duration 또는 monotonic duration을 `job_step_attempts.metrics.duration_s`에 기록한다.

## 3. 선택한 통합 방식

### 3.1 비교한 방식

| 방식 | 장점 | 문제 |
| --- | --- | --- |
| 루프백 TCP로 실제 경계 유지 | 실물 배포와 같은 프로토콜·재접속·중복 처리를 검증 | TCP 수신기 구현 필요 |
| ROS 노드가 MySQL에 직접 저장 | 구현이 빠름 | DB writer가 늘고 실제 배포 구조를 우회 |
| ROS 저장과 TCP 저장을 모두 제공 | 입력 경로 선택 가능 | 중복 구현과 상태 원본 충돌 |

루프백 TCP 방식을 선택한다. 같은 PC이므로 공유기나 외부 네트워크는 필요 없지만,
Pinky Gateway는 `127.0.0.1:8788`로 FMS Gateway에 연결한다. ROS 노드와 RMF worker는
MySQL에 직접 쓰지 않는다.

### 3.2 시스템 구조

```text
Gazebo
  │ /scan, /odom, /amcl_pose, /trihouse/battery
  ▼
Pinky StatusNode
  │ /trihouse/status
  ▼
Pinky GatewayNode
  │ NDJSON/TCP 127.0.0.1:8788
  ▼
FMS Gateway ───────────────────────────────┐
  │ 단일 MySQL writer                     │ 내부 HTTP API
  ▼                                       ▼
MySQL                              Control Tower RMF Worker
                                            │
                                            ▼
                                    Open-RMF task API
                                            │
                                            ▼
                                    Pinky Easy Fleet Adapter
                                            │ ExecuteTransport
                                            ▼
                                      Pinky FleetNode/Nav2
```

### 3.3 선택한 control_system 연결 방식

세 가지 방식을 비교한다.

| 방식 | 판단 |
| --- | --- |
| `control_system` project 경로 직접 참조 | 기본 방식. 최신 map export를 중복 없이 사용하고 보호 대상은 읽기만 한다. |
| `control_system_test` 복사본 참조 | 격리 재현이나 파생 파일 실험 때만 사용한다. 기존 대상을 덮어쓰지 않는 새 복사본이어야 한다. |
| control_system 생성 launch 직접 수정 | 사용하지 않는다. UI 재생성 시 덮어써지고 Trihouse 책임이 외부 프로젝트로 샌다. |

통합 launch 파일명은 프로젝트 이름을 포함하지 않는
`trihouse_rmf_bridge/launch/control_system_rmf.launch.py`로 고정한다. 동일 launch가
`project_name`과 경로 인자로 다른 control_system project에도 적용될 수 있어야 한다.

## 4. 책임 경계

### 4.1 Pinky

Pinky는 물리 관측과 즉시 안전의 원본이다.

- map pose, odometry twist, 센서 freshness
- BatteryState 원본과 BatteryPolicyState
- cargo, safety, navigation과 readiness
- Nav2 명령 수행·취소와 실제 도착·정지 확인
- Safety Supervisor의 최종 `/cmd_vel` 게이트

Safety stop은 FMS, MySQL 또는 RMF 응답을 기다리지 않는다.

### 4.2 Open-RMF와 Pinky Fleet Adapter

Open-RMF는 이동 작업과 traffic 조정의 원본이다.

- task booking, 배정 fleet·robot, task status
- navigation graph, itinerary와 traffic negotiation
- charger와 battery-aware planning
- 이동 callback, stop, cancel과 replan

RMF의 이동 완료는 해당 `navigate` 단계의 완료일 뿐 전체 물류 업무 완료가 아니다.

### 4.3 Control Tower

Control Tower는 업무 규칙과 단계 진행의 원본이다.

- 주문, 재고, 배차 제한과 업무 priority
- Pinky·OMX gate와 순서 있는 stage engine
- 배터리 LOCAL_ONLY·RETURN_REQUIRED 업무 규칙
- RMF 작업 제출 worker와 task summary observer
- 성공·실패 사실의 결정적 분류

Control Tower RMF worker는 DB 계정과 비밀번호를 가지지 않는다.

### 4.4 FMS Gateway

FMS Gateway는 MySQL의 유일한 writer다.

- HTTP read/write API
- TCP 8788 NDJSON 수신·검증
- 장비 상태 projection과 offline watchdog
- inbound/outbound 메시지 멱등 처리
- RMF worker용 내부 API
- 하나의 업무 변경에 필요한 transaction 소유

기존 `control_tower/database/repositories/rmf_task_repository.py`의 runtime 직접 MySQL
접근은 제거하고 FMS Gateway 내부 repository와 HTTP client로 역할을 나눈다.

## 5. 식별자 계약

### 5.1 공용 TaskContext

새 `trihouse_interfaces/msg/TaskContext.msg`를 정의한다.

```text
bool active
uint64 job_id
uint64 job_step_id
uint64 assignment_revision
string rmf_task_id
string command_id
string map_revision
```

| 필드 | 단일 의미 |
| --- | --- |
| `job_id` | MySQL `jobs.job_id` |
| `job_step_id` | MySQL `job_steps.job_step_id` |
| `assignment_revision` | 늦은 이전 배정 결과를 거부하는 fencing 값 |
| `rmf_task_id` | Open-RMF booking ID |
| `command_id` | 개별 물리 실행 명령 UUID |
| `map_revision` | 이번 통합에서 항상 `"1"` |

활성 작업이 없으면 `active=false`, 숫자는 `0`, 문자열은 빈 값으로 둔다. 문자열에서
DB 숫자를 추측하거나 `rmf:`·`rmf-nav:` 접두사를 해석하지 않는다.

RMF EasyFullControl callback에서 DB ID를 직접 얻지 못한 경우 adapter는 `rmf_task_id`와
`command_id`를 보고한다. FMS Gateway는 unique인 `job_steps.rmf_task_id`로 정확히
단계를 조회한다. DB ID도 함께 전달되면 두 참조가 같은 단계인지 교차 검증한다.

`TaskContext`는 다음 계약에 포함한다.

- `ExecuteTransport.action` goal
- `NavigationState.msg`
- `TaskEvent.msg`
- `RobotStatus.msg`

기존 중복 문자열 `job_id`, `job_step_id`, `goal_id`는 새 계약으로 교체한다. 외부 wire
payload도 같은 의미를 사용한다.

### 5.2 메시지와 이벤트 ID

- `integration_messages.message_id`: 전송 한 건의 UUID
- `TaskEvent.event_id`: 장비가 생성한 결과 이벤트 UUID
- `job_step_attempts.attempt_uuid`: 실행 시도 UUID
- `TaskContext.command_id`: 실제 실행 명령 UUID

서로 다른 식별자를 같은 값으로 재사용하지 않는다. 다만 command와 terminal event의
관계는 `job_step_attempts.command_uuid`, `event_uuid`로 명시한다.

## 6. RobotStatus 계약

현재 `RobotStatus.msg`에는 `frame_id`, `pose`, `twist`, `navigation_state`가 이미 있다.
동일 의미 필드를 새로 추가하지 않고 기존 필드를 실제 TCP와 DB 경계까지 전달한다.
`map_revision`과 `TaskContext task_context`만 새로 추가한다.

```text
builtin_interfaces/Time stamp
string robot_id
string software_version
string frame_id
string map_revision
geometry_msgs/PoseWithCovariance pose
geometry_msgs/Twist twist
float32 battery_percentage
trihouse_interfaces/BatteryPolicyState battery_policy
trihouse_interfaces/CargoState cargo
trihouse_interfaces/SafetyState safety
trihouse_interfaces/TaskContext task_context
float32 task_progress
uint8 navigation_state
bool ready
string[] errors
```

`StatusNode`는 다음 규칙으로 필드를 채운다.

- 신선한 `/amcl_pose`가 있으면 `frame_id=map`과 map pose를 사용한다.
- AMCL이 없으면 odom pose와 실제 odom frame을 넣고 RMF adapter가 등록을 거부한다.
- `twist`는 최신 `/odom.twist.twist`를 사용한다.
- `map_revision`은 launch parameter `"1"`이다.
- navigation message가 제공한 공용 TaskContext를 그대로 보존한다.
- 센서 freshness와 battery policy를 `ready`와 `errors`에 반영한다.

### 6.1 TCP robot_status schema v2

```json
{
  "type": "robot_status",
  "schema_version": 2,
  "robot_id": "PK_01",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "sequence": 123,
  "sent_at_ns": 123456789,
  "map_revision": "1",
  "frame_id": "map",
  "pose": {"x": 1.2, "y": 3.4, "yaw": 0.5},
  "twist": {"linear_x_mps": 0.2, "angular_z_rps": 0.1},
  "navigation_state": 1,
  "task_progress": 0.4,
  "task_context": {
    "active": true,
    "job_id": 10,
    "job_step_id": 31,
    "assignment_revision": 2,
    "rmf_task_id": "rmf-task-10-31",
    "command_id": "1747bf84-6597-4b2f-9a71-bf65539b2836",
    "map_revision": "1"
  },
  "battery_percentage": 74.5,
  "battery_condition": {
    "percentage": 74.5,
    "present": true,
    "power_supply_status": 2,
    "measurement_valid": true,
    "has_valid_sample": true,
    "telemetry_fresh": true
  },
  "battery_policy": {
    "state": 1,
    "ready": true,
    "reason_code": "BATTERY_NORMAL",
    "detail": "battery permits normal work"
  },
  "safety_state": 0,
  "cargo_state": 1,
  "ready": true,
  "errors": []
}
```

`session_id`는 GatewayNode 기동마다 생성하는 UUID이고 `sequence`는 session 안에서 1씩
증가한다. FMS Gateway는 활성 connection의 session과 마지막 sequence보다 오래된 상태를
거부한다. 매초 상태 payload는 `integration_messages`에 넣지 않는다.

## 7. 장비 상태 projection

### 7.1 device_states

`device_states`는 장비당 최신 한 행만 보유한다.

| 입력 | 저장 대상 |
| --- | --- |
| 통합 `robot_id` | `device_id` |
| FMS 수신 KST 시각 | `observed_at` |
| 계산된 행동 상태 | `state` |
| 계산된 건강 상태 | `health` |
| 검증된 TaskContext | `current_job_step_id` |
| map pose | `pose_x`, `pose_y`, `pose_yaw` |
| 배터리 백분율 | `battery_pct` |
| 단계 진행률 | `progress` |
| frame, revision, twist, battery policy, cargo, safety, 원본 시각 | `details` |

위치와 속도를 매초 이력 행으로 만들지 않는다. 속도는 POC 동안
`details.motion.linear_x_mps`, `details.motion.angular_z_rps`에 둔다. 반복 조회·인덱스가
필요하다는 측정 근거가 생기기 전에는 전용 컬럼을 추가하지 않는다.

UPSERT는 incoming session·sequence가 현재 행보다 최신일 때만 적용한다. `REPLACE`는
사용하지 않는다.

### 7.2 state 우선순위

| 우선순위 | 조건 | `device_states.state` |
| --- | --- | --- |
| 1 | Safety emergency | `estop` |
| 2 | Safety stop | `blocked` |
| 3 | navigation failed 또는 치명적 error | `error` |
| 4 | battery policy CHARGING | `charging` |
| 5 | navigation active | `moving` |
| 6 | 활성 작업이 있으나 이동하지 않음 | `waiting` |
| 7 | 활성 작업 없이 정상 대기 | `idle` |

`docking`, `working`, `maintenance`는 해당 명시적 상태 입력이 들어오는 경우에만 사용한다.
관측되지 않은 행동을 추측하지 않는다.

### 7.3 health 우선순위

| 조건 | `device_states.health` |
| --- | --- |
| Safety stop 또는 emergency | `safety_hold` |
| navigation failure 또는 치명적 장비 오류 | `fault` |
| battery UNKNOWN·RETURN_REQUIRED 또는 telemetry stale | `warning` |
| 나머지 | `ok` |

`state`는 현재 행동이고 `health`는 작업 투입과 이상 여부다. 두 값을 하나의 열거값으로
합치지 않는다.

## 8. 작업 이벤트와 실행 이력

`TaskEvent`는 공용 TaskContext와 다음 안정 필드를 포함한다.

- `event_id`
- `robot_id`
- `event_type`: started, arrived, canceled, failed
- `reason_code`
- `method_code`
- `detail`

FMS Gateway는 event와 직전의 유효한 RobotStatus를 하나의 transaction에서 검증한다.
terminal 판정에 사용하는 status는 event와 같은 `robot_id`, `session_id`,
`TaskContext.command_id`, `assignment_revision`이어야 하며 FMS 수신 시각 기준 2초 이내여야
한다. 이 조건을 만족하는 status가 없으면 성공으로 추측하지 않고 불완전 결과로 분류한다.

| event | DB 처리 |
| --- | --- |
| started | matching attempt를 `running`, step을 `running`으로 전이 |
| arrived | 도착·정지·safety 기준을 분류한 뒤 attempt 종료 및 navigate step 성공 |
| canceled | attempt와 step을 `cancelled`로 종료 |
| failed | failure domain·reason을 분류하고 attempt와 step을 `failed`로 종료 |

`job_step_attempts`에는 한 번의 실행마다 다음을 채운다.

- 명령 생성 시: attempt UUID, command UUID, attempt number, actor, revision,
  method와 선택 이유
- 시작 시: `started_at`
- 종료 시: outcome, success, reason code, failure domain, detail, criteria,
  metrics와 `completed_at`
- 적용한 정책·모델이 있으면 이름과 버전을 쌍으로 기록
- 필요한 관측이 빠졌으면 성공으로 추측하지 않고 `data_quality_status=incomplete`,
  `outcome_reason_code=UNCLASSIFIED_RESULT`로 분류

POC navigation 성공 기준은 최소 다음 네 가지다.

| criterion | 성공 조건 |
| --- | --- |
| `NAV2_RESULT_SUCCEEDED` | 현재 command의 Nav2 결과가 성공 |
| `TARGET_POSE_WITHIN_TOLERANCE` | 최종 map pose가 목표 허용 오차 안 |
| `ROBOT_STOPPED` | 선속도·각속도가 정지 허용값 이하 |
| `SAFETY_CLEAR` | terminal 판정 시 safety가 CLEAR |

RMF `completed`는 위 Pinky terminal 결과를 대신하지 않는다. 두 결과가 불일치하면
`integration` failure event를 남기고 자동으로 전체 job을 완료하지 않는다.

## 9. TCP 8788 서버

FMS Gateway의 FastAPI lifespan에서 `asyncio.start_server()`로 NDJSON server를 함께
시작한다. HTTP는 8080, TCP는 8788을 사용한다.

### 9.1 처리 메시지

| 메시지 | 처리 |
| --- | --- |
| `hello` | 등록 장비, schema version, session ID 검증 |
| `heartbeat` | connection 생존 시각 갱신 |
| `robot_status` | session·sequence·revision 검증 후 최신 상태 UPSERT |
| `task_event` | event UUID 중복 확인 후 업무·단계·attempt·event transaction |
| `command_ack` | outbound Pinky message 전달 상태 반영 |

한 TCP connection은 hello에서 선언한 장비 하나만 대표한다. 이후 payload의 robot ID가
다르면 connection을 종료한다. 한 줄의 최대 크기를 설정해 무제한 메모리 사용을 막고,
잘못된 UTF-8·JSON·schema는 DB에 넣지 않는다.

### 9.2 ACK와 재전송

- 상태는 ACK를 기다리지 않는다. 다음 1초 상태가 최신 snapshot을 회복한다.
- task event는 FMS transaction commit 뒤에만 ACK한다.
- DB 연결·transaction timeout 같은 일시 오류에는 terminal ACK를 보내지 않는다.
- 복구 불가능한 schema·ID·revision 검증 실패에는 `event_rejected`와 안정적인
  `reason_code`를 반환한다. Pinky는 해당 event의 자동 재시도를 끝내고 dead-letter 로그에
  남긴다.
- Pinky Gateway는 미확인 event를 같은 `event_id`로 재전송한다.
- FMS는 `event_uuid` unique로 중복 효과를 막고 중복 event에도 같은 ACK를 반환한다.

시뮬레이션 POC의 미확인 event queue는 Pinky Gateway process 메모리에 유지한다. process
재시작을 넘는 로컬 durable outbox는 실물 운영 전 별도 인수 조건이며, JSONL 측정 로그를
재전송 큐로 오해하지 않는다.

### 9.3 offline watchdog

마지막 유효 `robot_status` 이후 5초가 지나면 다음을 한 번 수행한다.

- `device_states.state=offline`
- `device_states.health=warning`
- 신규 작업 배정 차단
- `robot.offline` operation event 추가

다음 유효 상태가 오면 `robot.online` event를 한 번 기록하고 최신 projection으로 복귀한다.

## 10. RMF worker와 내부 API

RMF worker는 ROS 환경 때문에 호스트에서 실행하고 DB 작업은 FMS Gateway 내부 API에
요청한다.

```text
POST /internal/rmf/messages/claim
→ FMS Gateway가 FOR UPDATE SKIP LOCKED로 outbound 행 선점

RMF worker
→ task_api_requests에 공식 dispatch_task_request 발행

POST /internal/rmf/messages/{message_id}/acceptance
→ 수락·거절과 rmf_task_id 반영

task_summaries 구독
→ POST /internal/rmf/tasks/{rmf_task_id}/status
→ job_steps RMF projection 반영
```

POC internal API는 `127.0.0.1`로만 노출한다. 운영 배포의 service 인증은 별도 배포
보안 작업으로 남기되 외부 UI API와 경로를 분리한다.

### 10.1 RMF 상태 매핑

| RMF 상태 | `job_steps.rmf_status` | `job_steps.state` |
| --- | --- | --- |
| queued 또는 pending | 원본 안정 문자열 | `pending` |
| active | `active` | `running` |
| completed | `completed` | Pinky 결과까지 일치할 때 `succeeded` |
| failed | `failed` | `failed` |
| canceled | `canceled` | `cancelled` |

알 수 없는 task, 지원하지 않는 상태 또는 더 오래된 관측 시각은 현재 업무를 변경하지
않고 operation event에 기록한다. RMF 완료만으로 `jobs.state=completed`를 만들지 않는다.

## 11. MySQL 저장 책임

| 테이블 | 데이터 출처 | 저장 규칙 |
| --- | --- | --- |
| `locations` | RMF 지도·운영 설정 | waypoint, 슬롯, 충전기, 포장대의 논리 위치 |
| `map_features` | 지도·안전 설정 | revision `"1"`의 병목·금지구역·marker |
| `workers` | 계정 관리 | 운영자와 승인 권한 마스터 |
| `devices` | 장비 등록 | 네 개 통합 장비 ID의 불변 마스터 |
| `device_states` | RobotStatus·OMX status | 장비당 최신 한 행 UPSERT |
| `inventory_lots` | 재고 workflow | 현재 lot 수량·위치 |
| `inventory_moves` | 재고 확정 | 수량 변화 append-only 원장 |
| `jobs` | 주문·복구 workflow | 업무 전체의 현재 상태 |
| `job_items` | 주문·QR·lot 배정 | 업무 대상과 처리 수량 |
| `job_steps` | stage engine·RMF·OMX | 단계 현재 상태와 최종 요약 |
| `job_step_attempts` | Pinky·OMX·FMS 실행 | 재시도 한 번당 한 행 |
| `reservations` | 배차·자원 정책 | 도크·포장대·OMX·병목의 점유 |
| `integration_messages` | RMF·Pinky·OMX 연동 | 명령·결과의 멱등·재전송 상태 |
| `incidents` | Safety·Vision·운영자 | 진행 중 안전 사건 |
| `operation_events` | 상태 변화·정책·결과 | append-only 감사·학습 label |
| `artifacts` | rosbag·영상·JSONL | 파일 URI, SHA-256과 label 연결 |
| `location_recovery_profiles` | 검증된 safe node | 복구 후보 위치와 신뢰도 |
| `recovery_episodes` | 복구 workflow | 복구 사건과 정책·모델 계보 |
| `recovery_steps` | 실제 복구 행동 | 행동·전후 관측·보상·결과 |

### 11.1 project1 fleet와 DB 장비 마스터 동기화

launch는 DB를 수정하지 않는다. 별도 registry 동기화 단계가 project1 입력을 읽어 정규화된
장비 manifest를 만들고 FMS Gateway 내부 API를 통해 검증·반영한다. Control Tower나 ROS
노드가 MySQL에 직접 연결하지 않는다는 4.4의 원칙을 유지한다.

동기화 입력과 DB 매핑은 다음과 같다.

| project1 입력 | DB 대상 |
| --- | --- |
| `fleet.yaml.robots[].id` | `devices.device_id` |
| `kind=mobile/workcell` | `devices.device_type=mobile/arm` |
| `name` | `devices.name` |
| `model` | `devices.model` |
| mobile + RMF config fleet name | `devices.fleet_name=project1_pinky` |
| workcell | `devices.fleet_name=omx_fleet` |
| charger/station waypoint | `devices.home_location_id`과 `locations.rmf_waypoint_name` |
| `gz_name`, zones, data source, RMF robot name | `devices.capabilities` JSON |
| spawn pose | 초기 시험용 `device_states`가 아니라 capabilities의 simulation metadata |

`capabilities`의 최소 형식은 다음과 같다.

```json
{
  "data_source": "gazebo",
  "gz_name": "pinky_01",
  "rmf_robot_name": "PK_01",
  "zones": ["ambient", "chilled", "frozen"],
  "navigation": true,
  "rmf": true
}
```

초기 spawn pose를 최신 관측값처럼 `device_states`에 seed하지 않는다. Gazebo의 실제
RobotStatus가 들어오기 전에는 상태를 `offline` 또는 미관측으로 유지한다. 위치 seed는
`locations`의 charger/station 기준정보에만 사용한다.

동기화 명령은 기본적으로 diff만 출력한다. 명시적 `--apply`에서만 다음을 수행한다.

1. `충전1`, `충전2`, `설비1`, `설비2`가 building/nav graph에 존재하는지 확인한다.
2. 기존 `PINKY-01`, `PINKY-02`, `OMX-01`, `OMX-02`, `PK-01`, `PK-02` 참조를 보고한다.
3. FK와 논리 참조 migration이 준비되지 않았으면 적용을 거부한다.
4. FMS Gateway transaction으로 locations와 devices를 upsert한다.
5. 재조회해 네 장비의 ID, fleet, home location, capabilities가 manifest와 같은지 확인한다.

현재 `db/seed_dev.sql`의 `PINKY-01`, `PINKY-02`, `OMX-01`, `OMX-02`와 `pinky_fleet`은
project1 계약과 불일치한다. 구현 단계에서 12.3의 ID migration과 새 개발 seed를 함께
수정해야 하며 문자열 치환만으로 기존 FK를 깨뜨리면 안 된다.

### 11.2 원시 관측과 DB label 분리

다음 고빈도 원시 데이터는 MySQL에 매 sample INSERT하지 않는다.

- `/scan`, 원시 `/odom`, 전체 TF
- 카메라 frame과 point cloud
- 동일 상태의 1초 heartbeat

이 데이터는 rosbag·영상·JSONL 파일에 저장하고 `artifacts`가 URI와 해시를 가리킨다.
MySQL에는 최신 snapshot, 상태 변화, 작업 결과와 학습 label만 저장한다.

## 12. 스키마와 문서 정합성

### 12.1 확인된 문제

- `db/schema_mysql.sql`: 19개 테이블과 298개 컬럼의 현재 물리 기준
- `docs/database/data_dictionary.xlsx`: 18개 테이블과 253개 컬럼만 포함
- XLSX에는 `job_step_attempts` 전체와 최신 jobs·job_steps·operation_events 컬럼이 누락
- `004_add_korean_comments.sql`은 현재 `jobs.state DEFAULT 'queued'`와 달리 과거
  `DEFAULT 'pending'`을 포함
- 기존 metadata check는 XLSX에 존재하는 253행의 설명만 확인하고 누락 구조를 실패로
  판정하지 않음

### 12.2 단일 원본과 변경 방식

`db/schema_mysql.sql`을 유일한 물리 스키마 원본으로 삼는다.

1. 새 DB는 항상 이 파일로 생성한다.
2. 이미 존재하는 DB는 새 `005_align_runtime_schema_and_device_ids.sql`로 변경한다.
3. 이미 적용됐을 수 있는 `004`는 수정하지 않고 역사적 migration으로 유지한다.
4. XLSX를 현재 19개 테이블·298개 컬럼 전체로 재생성한다.
5. sync check가 SQL과 XLSX의 테이블·컬럼 집합 차이도 실패로 판정하게 한다.
6. `database_guide.md`의 과거 상태값·migration 예시를 현재 계약에 맞춘다.

### 12.3 장비 ID migration

FK 검사 비활성화로 문제를 숨기지 않고 다음 순서를 하나의 migration transaction으로
수행한다.

1. 기존 device 마스터를 새 ID로 복제한다.
2. `device_states`, jobs, job_steps, attempts, reservations, integration messages,
   operation events, artifacts의 FK를 새 ID로 갱신한다.
3. `trihouse_recovery.recovery_episodes.device_id` 논리 참조도 갱신한다.
4. RMF robot name과 capabilities를 새 ID로 정렬한다.
5. 참조가 남지 않았음을 검증한 뒤 옛 device 행을 제거한다.

일회용 `compose.db_test.yaml`은 갱신된 seed로 바로 새 ID를 만든다.

## 13. 오류 처리

| 상황 | 처리 |
| --- | --- |
| 잘못된 장비 ID | connection 또는 message 거부, DB 변경 없음 |
| map revision이 `"1"`이 아님 | 명령·상태 작업 연결 거부, `MAP_REVISION_MISMATCH` 기록 |
| 오래된 session·sequence | 최신 상태 덮어쓰기 금지 |
| status 유실 | 다음 status로 snapshot 회복 |
| 5초 status timeout | offline 전이와 신규 배차 차단 |
| DB 일시 장애 | safety 운행은 계속, status는 다음 sample로 회복 |
| task event DB 실패 | ACK 보류, 같은 event ID 재전송 |
| task event 영구 검증 실패 | `event_rejected` 반환, 자동 재시도 중단과 dead-letter 기록 |
| 중복 task event | DB 효과 한 번, ACK는 재전송 |
| RMF 응답 timeout | 같은 request ID로 재시도 |
| 늦은 이전 배정 결과 | assignment revision 불일치로 거부 |
| 알 수 없는 RMF task | 업무 변경 없이 경고 event |
| RMF와 Pinky terminal 결과 불일치 | integration failure, 자동 job 완료 금지 |

## 14. 통합 실행 구성

새 `compose.integration_test.yaml`은 다음 두 service만 시작한다.

```text
trihouse_integration_test
├─ mysql_test: MySQL 8.4, tmpfs, host 3307
└─ fms_gateway: HTTP 8080, TCP 8788
```

Gazebo, ROS 2, RMF schedule·dispatcher와 RMF worker는 호스트에서 실행한다. MySQL
tmpfs는 시험 종료 후 사라지므로 장기 실험 데이터는 영구 `compose.db.yaml`에서 별도로
수행한다.

### 14.1 `control_system_rmf.launch.py` 경계

launch는 control_system이 생성한 `project1.launch.xml`,
`project1_bringup.launch.xml`, `project1_nav2.launch.xml` 전체를 그대로 include하지 않는다.
이 파일들은 과거 절대경로, OMX 필수 의존성과 기존 `project1_nav2_adapter.py` 실행을
포함하고, 함께 제공되는 `run_project1.sh`는 source world 패치와 nav graph 생성을 수행하기
때문이다. 대신 보호된 project artifact 중 필요한 world, building, bridge, robot spawn,
robot Nav2 파일을 선택적으로 include하고 Trihouse가 소유한 Pinky stack과
EasyFullControl adapter를 조합한다.

명령 소유권은 하나로 고정한다.

```text
Open-RMF
→ Trihouse EasyFullControl adapter
→ ExecuteTransport
→ Pinky FleetNode
→ namespaced Nav2 NavigateToPose
→ Safety Supervisor
→ namespaced final cmd_vel
→ ros_gz_bridge
→ Gazebo
```

`project1_nav2_adapter.py`와 Trihouse EasyFullControl adapter를 동시에 실행하지 않는다.
Nav2 controller의 원래 `/<namespace>/cmd_vel`은 `/<namespace>/cmd_vel_nav`으로 remap하고,
Safety Supervisor만 최종 `/<namespace>/cmd_vel`을 발행한다.

### 14.2 CLI argument 계약

필수·경로 인자는 ML/DL 실행 CLI처럼 launch invocation에서 명시적으로 덮어쓸 수 있어야
한다. 기본값은 현재 workspace에 맞추되 코드 로직에서 `/home/gyi`를 사용하지 않는다.

| argument | 기본값 또는 의미 |
| --- | --- |
| `control_system_root` | `/home/syw/Trihouse/control_system` |
| `project_name` | `project1` |
| `map_dir` | `<control_system_root>/rmf_maps/<project_name>` |
| `fleet_file` | `<map_dir>/fleet.yaml` |
| `rmf_fleet_config` | `<map_dir>/<project_name>_pinky_config.yaml` |
| `building_yaml` | `<map_dir>/<project_name>.building.yaml` |
| `world` | `<map_dir>/<project_name>.world` |
| `nav_graph` | `<map_dir>/nav_graphs/0.yaml` |
| `nav2_map` | `<map_dir>/nav2_map/<project_name>.yaml` |
| `gz_bridge_config` | `<map_dir>/<project_name>_gz_bridge.yaml` |
| `robot_ids` | 첫 시험 `PK_01`; 쉼표로 `PK_01,PK_02` 선택 가능 |
| `start_omx` | 기본 `false`; OMX 패키지가 설치된 뒤에만 `true` |
| `start_gazebo`, `start_rmf_core`, `start_nav2` | 각 계층 독립 모듈 시험 스위치 |
| `start_pinky_stack`, `start_rmf_adapter` | Pinky 제어와 RMF adapter 독립 스위치 |
| `start_control_gateway` | 실제 TCP 8788 경계 실행 여부 |
| `headless`, `use_sim_time` | 기본 `true` |
| `map_revision` | 기본 `1` |
| `control_host`, `control_port` | 기본 `127.0.0.1`, `8788` |
| battery scenario 인자 | 초기 SOC, charging, 충·방전 가속률 |

개별 artifact 경로를 넘기면 `map_dir` 파생값보다 우선한다. 존재하지 않는 경로, project
이름과 맞지 않는 파일, fleet에 없는 robot ID는 launch 시작 전 preflight 실패로 처리한다.

### 14.3 읽기 전용 artifact와 파생 산출물

direct 모드에서도 control_system 원본을 수정하지 않는다. world 센서 plugin 추가,
collision detector 변경 또는 nav graph 생성이 필요하면 아래 둘 중 하나만 허용한다.

1. 최신 control_system export에 완성된 artifact가 있으면 그대로 읽는다.
2. 없으면 명시적인 준비 명령으로 새 `control_system_test` 복사본을 만든 뒤 그 복사본에서
   파생 artifact를 생성하고 launch의 `control_system_root` 또는 `map_dir`을 변경한다.

현재 project1에는 `generated_models/project1_L1`과 `nav_graphs/0.yaml`이 없고 world는
`model://project1_L1`을 참조한다. 따라서 이 두 artifact가 준비되기 전에는 preflight가
실패해야 한다. `.log`, `.err.log`, `.pgid`, `.rmf_schedule_node.yaml`, `__pycache__`는
복사 대상이 아니다.

복사 도구는 source root, destination root, project name을 CLI 인자로 받고 다음을 지킨다.

- `copy`만 사용하고 `move`를 사용하지 않는다.
- source가 control_system project인지 검증한다.
- destination project가 이미 있으면 덮어쓰거나 삭제하지 않고 실패한다.
- 필요한 project 파일과 하위 `robots`, `nav2_map`, `generated_models`, `nav_graphs`만 복사한다.
- 복사 완료 후 source와 destination의 필수 파일 SHA-256을 비교한다.

### 14.4 시작 순서

하나의 launch 안에서도 다음 event 순서를 보장한다.

1. preflight가 파일·fleet·namespace·charger·패키지를 검증한다.
2. Gazebo server와 clock bridge를 시작한다.
3. `/clock`과 world가 준비된 뒤 선택한 robot을 spawn한다.
4. RMF core와 building map server를 시작한다.
5. Nav2 map server, 선택한 robot의 AMCL·Nav2를 시작한다.
6. Pinky sensor/status/safety/fleet/gateway stack을 namespaced remap으로 시작한다.
7. 신선한 map pose와 RobotStatus를 확인할 수 있는 상태에서 RMF adapter를 시작한다.

고정 `sleep`만으로 준비를 추정하지 않는다. 프로세스 종료, `/clock`, action server, map pose,
TCP connection readiness를 각각 관측하고 다음 계층을 시작하거나 명확한 timeout으로 실패한다.

## 15. 테스트 전략

### 15.1 정적·단위 테스트

- 네 개 통합 ID 외 값 거부
- TaskContext의 active·ID·revision 불변식
- quaternion에서 yaw 변환과 twist 직렬화
- state·health 우선순위
- KST API 직렬화와 ROS simulation stamp 분리
- session·sequence 순서 판정
- RMF 상태 매핑과 알 수 없는 상태 거부
- DB schema와 XLSX 구조 집합 일치
- CLI 경로 파생과 개별 artifact override 우선순위
- fleet.yaml과 RMF config의 robot·charger·fleet 교차 검증
- project1 `workcell → arm` 외 암묵적 ID 변환 거부
- 기존 control_system 원본을 변경하지 않는 copy·preflight 계약
- 기존 destination 복사 거부와 runtime 파일 제외
- 선택하지 않은 OMX 패키지를 요구하지 않는 조건부 의존성
- robot namespace별 odom, scan, AMCL, Nav2 action, cmd_vel remap

### 15.2 MySQL 통합 테스트

- RobotStatus UPSERT가 장비당 한 행만 유지
- 오래된 sequence가 최신 pose·battery를 덮어쓰지 않음
- 상태 변화만 operation event에 추가
- 동일 TaskEvent 재전송의 DB 효과가 한 번
- started·arrived·failed·canceled의 step/attempt transaction
- assignment revision이 다른 결과 거부
- RMF task acceptance와 task summary 반영
- RMF 완료만으로 전체 job이 완료되지 않음
- 장비 ID migration 후 모든 FK와 logical reference 정합성
- project1 manifest dry-run이 기존 DB ID·fleet 불일치를 정확히 보고
- 명시적 apply 뒤 `PK_01`, `PK_02`, `OMX_01`, `OMX_02`와 home location 정합성
- 두 Pinky의 `capabilities.rmf_robot_name`과 `devices.fleet_name=project1_pinky` 정합성
- 같은 manifest 재적용의 멱등성과 fleet 파일 변경 시 차이 보고

### 15.3 Gazebo·RMF E2E

1. 통합 Compose를 시작한다.
2. `PK_01`, map revision `"1"`로 Gazebo를 시작한다.
3. `/trihouse/status`의 map pose, twist, navigation, battery를 확인한다.
4. MySQL `device_states`가 1초 내 갱신되는지 확인한다.
5. RMF schedule, dispatcher, worker와 Pinky Fleet Adapter를 시작한다.
6. seed 업무의 navigate step을 RMF에 제출한다.
7. RMF가 `PK_01`을 배정하고 Gazebo Pinky가 이동하는지 확인한다.
8. 도착 후 RMF status, Pinky terminal result, step과 attempt를 확인한다.
9. cancel, navigation failure, stale telemetry, battery 제한과 safety stop을 각각 시험한다.
10. `device_states`, `job_steps`, `job_step_attempts`, `operation_events`를 실시간 조회한다.

통합 시험 전에 아래 모듈 시험을 순서대로 통과해야 한다.

1. artifact preflight와 fleet manifest parsing
2. Gazebo world·clock·PK_01 spawn
3. PK_01 odom·scan·AMCL·Nav2 action
4. Nav2 `cmd_vel_nav` → Safety Supervisor → 최종 `cmd_vel`
5. 배터리 scenario → RobotStatus → RMF SOC
6. RMF core·task API·단일 Pinky adapter 등록
7. FMS Gateway TCP 8788 → MySQL latest state projection
8. RMF 단일 waypoint task → Pinky terminal result → DB step/attempt
9. `PK_02`를 추가한 traffic·namespace·개별 SOC 검증
10. OpenManipulator 의존성이 준비된 뒤 OMX를 추가한 전체 stage 검증

### 15.4 성공 기준

- `PK_01` 상태가 다른 ID 변환 없이 ROS·RMF·DB에 동일하게 나타난다.
- `RobotStatus`의 map pose, twist, navigation, battery와 readiness가 DB 최신 상태에
  반영된다.
- 상태 메시지 중복·역전에도 최신 snapshot과 event 이력이 오염되지 않는다.
- 하나의 RMF 이동이 하나의 DB job step과 하나 이상의 명시적 attempt로 연결된다.
- 성공·실패·취소가 reason, method, criteria, metrics와 함께 저장된다.
- 안전 정지는 DB·RMF 장애 중에도 Pinky 로컬에서 작동한다.
- RMF 이동 완료가 OMX·검수·인계 전 전체 job을 완료하지 않는다.
- 모든 DB 시각과 API 시각은 KST 의미를 유지하고 ROS simulation time과 섞이지 않는다.

## 16. 구현 순서

1. project1 fleet/config/nav graph parser와 읽기 전용 preflight
2. 장비 ID·fleet 이름과 DB 문서·migration·seed 정합성
3. TaskContext와 ROS 인터페이스 계약
4. StatusNode와 TCP robot_status schema v2
5. FMS Gateway TCP server와 device state projection
6. TaskEvent ACK·재전송과 실행 이력 transaction
7. RMF worker 내부 HTTP API 전환과 task observer runtime
8. 안전한 `control_system_test` 복사 도구
9. `control_system_rmf.launch.py`와 namespace·Safety remap
10. launch 모듈 시험과 MySQL 통합 시험
11. PK_01 Gazebo·RMF·MySQL E2E와 수동 검증 명령
12. PK_02 다중 운행, 이후 OMX 통합과 run record

각 단계는 앞 단계의 계약 테스트를 통과한 뒤 진행한다. 보호 대상 경로는 어떤 단계에서도
수정하지 않는다.
