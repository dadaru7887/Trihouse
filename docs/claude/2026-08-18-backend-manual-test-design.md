# 백엔드 다섯 층 수동 검증 — 설계 (2026-08-18)

## 0. 이 문서가 정하는 것

UI 를 판정 경로에서 빼고, **백엔드 다섯 층이 이어 붙었을 때 실제로 도는지**를
사람이 손으로 확인하는 절차의 설계다. 계획서(`2026-08-18-backend-manual-test-plan.md`)
는 이 설계를 Task 와 체크박스로 편 것이고, 실제로 나온 출력은
`docs/validation/2026-08-18-backend-manual-test-run.md` 에 적는다.

정하지 **않는** 것:

- 새 기능 구현. 이 문서는 이미 있는 것을 확인한다. 확인 과정에서 나온 결함은
  11절에 "관측한다"로 남기고 고치지 않는다.
- control_ui / rmf_dashboard 화면으로 하는 판정. 두 컨테이너는 떠 있어도 되지만
  **어떤 성공 기준도 화면을 근거로 삼지 않는다.**
- 실물 OMX 팔의 모션. 코드에 그 경로가 없다(4절).

### 0.1 용어 — 이 문서에서 "시뮬"이란

**Nav2 navigation 과 RViz 를 켜고 이 PC 안에서 도는 것**을 말한다. Gazebo 로 로봇을
띄우고 Nav2 가 실제로 경로를 만들며 RViz 로 그것을 눈으로 본다.

```bash
control_tower/bringup/p0_simulation_bringup.sh --rviz
```

`--gui`(Gazebo 창)는 선택이고 `--rviz` 는 **기본이다.** 앞선 문서들이 "처음 한 번은
붙이지 않는 편이 낫다"고 쓴 것을 여기서 뒤집는다 — 경로와 costmap 을 보지 못하면
Nav2 가 무엇을 하는지 판정할 수 없기 때문이다.

대신 부하 예산을 다시 잡는다. 단일 로봇 + Gazebo headless + RViz 를 기준으로
**load average 25 를 상한**으로 본다. 그 위에서 실패한 것은 부하이지 버그가 아니다.
`--gui` 까지 붙이면 상한을 40 으로 올려 읽는다.

### 0.2 로봇 이름 — 두 개의 이름공간

이 문서와 모든 명령줄은 **ROS namespace 이름(`pinky_01`, `pinky_02`)** 을 쓴다.
DB 의 `device_id` 는 FK 로 묶여 있어 그대로 둔다.

| 층 | 로봇 1 | 로봇 2 | 팔 1 | 팔 2 |
|---|---|---|---|---|
| ROS namespace / 노드 | `pinky_01` | `pinky_02` | `omx_01` | `omx_02` |
| DB `devices.device_id` | `PK_01` | `PK_02` | `OMX_01` | `OMX_02` |
| RMF robot name | `PK_01` | `PK_02` | — | — |

`devices.device_id` 는 `jobs.assigned_mobile_id`, `job_steps.assigned_device_id`,
`reservations.device_id` 세 곳에서 FK 대상이므로 바꾸면 seed 재작성과 기존 행
마이그레이션이 함께 따라온다. 이름 통일의 값이 그 비용을 넘지 않아 **DB 는 두지
않는다.**

대신 **`TRIHOUSE_ROBOTS` 가 namespace 이름을 받도록 한 줄 고친다.** 지금은
`TRIHOUSE_ROBOTS=PK_01` 만 받는다. 이것이 이 검증 문서가 요구하는 **유일한 코드
변경**이며, 계획서의 Task 0 에서 실패하는 테스트를 먼저 쓰고 고친다.

- Modify: `control_tower/bringup/p0_simulation_bringup.sh`, `two_pinky_order_demo.launch.py` 의 `robots` 인자 해석
- 계약: `pinky_01`/`PK_01` 둘 다 받아 내부적으로 `PK_01` 로 옮긴다. 기존 호출은 깨지지 않는다

## 1. 통과 기준

**주문 1건 완주.** 주문 → 7단계 전부 종료 → 예약 `released` → job 이 종료 상태
(`completed`/`failed`/`cancelled` 중 `completed`)까지 한 번 간다. `wait` 단계는
사람이 `POST /api/v1/jobs/{id}/worker-completion` 을 불러 넘긴다 — 배경 프로세스가
그 단계를 절대 닫지 않도록 되어 있기 때문이다([executor_worker.py:41-44](../../control_tower/task_manager/executor_worker.py#L41-L44)).

시뮬(도메인 0)에서 먼저 통과하고, **통과한 뒤에만** 실기(도메인 52)로 같은 완주를
한 번 더 한다. 시뮬이 통과하지 못하면 실기로 넘어가지 않는다.

## 2. 판정 구조 — A절과 B절

층을 위에서부터 한 층씩 판정하되, 재고는 완주에만 쓴다. 그래서 두 부분으로 나눈다.

```text
A절  주문 없이 판정되는 것          재고 0 소진
     L1 DB   → L2 Gateway → L3 관제 → L4 로봇 → L5 OMX
     각 층이 자기 신호를 내는가. 실패하면 그 자리에서 멈춘다.
                    │
                    ▼  A절 전부 통과했을 때만
B절  완주 한 줄기                    재고 1 lot 소진
     주문 → L2 쓰기 → L3 dispatch → L4 주행 → L5 arm step
          → wait → worker-completion → 종료·예약 released
```

**왜 이렇게 나누는가.** 완주는 층을 가로지르므로 완주만으로 판정하면 중간에서
막혔을 때 어느 층의 결함인지 말할 수 없다. 이 저장소에서 벽 네 개가 **순차적으로만**
관측된 기록이 그 증거다(예약 회수 → costmap 프레임 → RMF worker 사망 → fleet 등록
실패). 반대로 층마다 주문을 하나씩 쓰면 재고 상한 4건을 A절에서 다 써 버린다.

A절이 전부 통과한 상태에서 B절이 막히면, **그 지점이 곧 결함 위치다.** 그것이 이
구조가 사는 이유다.

## 3. 층의 실제 경계 — 코드에서 확인한 것

네가 준 다섯 층 표와 코드가 어긋나는 자리가 있다. 판정 대상은 **런타임에 도는
것**이지 모듈이 존재하는 것이 아니다.

| 층 | 런타임에 실제로 도는 것 | 런타임에 없는 것 |
|---|---|---|
| L1 DB | MySQL 3308 (`trihouse_p0_trihouse_mysql_data` 볼륨). 3307 은 e2e 전용, 3306 은 별개 | — |
| L2 Gateway | FastAPI 단일 앱 [main.py](../../fms_gateway/app/main.py), 라우트 44개 | — |
| L3 관제 | `job_runner_node`, `executor_worker_node`, `rmf_gateway_worker_node` 세 프로세스. 전부 HTTP 로만 Gateway 와 말한다 | `rmf_adapter/bottleneck.py`, `rmf_adapter/traffic_reservation.py` — **import 하는 곳이 테스트뿐**이다 |
| L4 로봇 | 시뮬: Nav2 + `status_node` + `sim_hardware` + `battery_condition` + `battery_policy` + `readiness_checker` + `fleet_gateway`. 실기: 여기에 `safety_supervisor`·LED·부저·초음파·OLED·`camera_streamer` 가 더해진다 | 시뮬에는 `safety_supervisor`·`recovery_health`·`fleet_node`·표시장치가 **없다**([two_pinky_order_demo.launch.py:336-343](../../trihouse_rmf_bridge/launch/two_pinky_order_demo.launch.py#L336-L343)) |
| L5 OMX | `executor_worker` → `OmxProtocolSimulator` (HTTP 경로). ROS 쪽은 `gazebo_omx_adapter` 가 `HandoverState`/`CargoState` 를 2 Hz 로 발행 | `task_manager/omx_workflow.py` 의 `OmxWorkflow`·`PickRecovery` — **import 하는 곳이 테스트뿐**이다. `handover_gate`·`zone_handover`·`stage_engine`·`task_orchestrator`·`pick_failure_report`·`emergency_workflow` 도 같다 |

### 3.1 실기에서도 로봇팔은 움직이지 않는다

`executor_worker_node --environment hardware` 는 duration 표본에 태그만 다르게
붙인다([executor_worker_node.py:99-104](../../control_tower/task_manager/executor_worker_node.py#L99-L104)).
팔은 어느 환경에서든 `OmxProtocolSimulator`
다([executor_worker_node.py:66-77](../../control_tower/task_manager/executor_worker_node.py#L66-L77)).
`hardware_adapter_node` 는 "motion remains disabled until hardware plugin is
approved" 인 진단 전용 skeleton 이다. **실기 완주에서도 팔은 정지해 있다.**

### 3.2 그래서 L5 를 무엇으로 판정하는가

두 가지를 본다. 실물 OMX 는 확장안(11.7)으로 미룬다.

1. **ROS 왕복 — 시뮬에서만 본다.** `gazebo_omx_adapter` 의 `mock_load_confirmed`
   파라미터를 바꾸고 두 토픽의 값이 따라 바뀌는 것을 본다. "적재 준비 → 적재 완료"
   의 왕복이다. 이 노드는 Gazebo 데모용이라 실기 기동에는 없다.
2. **완주 중 arm step** — B절에서 `pick` step 이 실제로 닫히는 것. 시뮬과 실기 공통이며
   **실기 L5 판정은 이것뿐이다.**

### 3.3 스키마 대조 — `db/migrations/001_physical_v1_baseline.sql` 을 정본으로 확인한 것

성공 기준에 쓰는 상태 문자열은 전부 스키마의 `CHECK` 제약에서 가져왔다. 코드가
아니라 스키마가 정본이다.

| 테이블 | 이 문서가 쓰는 값 | 근거 |
|---|---|---|
| `jobs.state` | 비종료 `queued`/`assigned`/`running`/`held`, 완주 성공은 `completed` | `chk_jobs_state` (7개) |
| `job_steps.state` | 성공은 `succeeded` | `chk_job_steps_state` = `pending`/`running`/`succeeded`/`failed`/`cancelled` |
| `job_steps.executor_type` | `mobile`/`arm`/`fms` | `chk_job_steps_executor` |
| `job_steps.action_type` | `pick`/`navigate`/`load`/`handover`/`wait`/`return_home` | `chk_job_steps_action` (13개 중) |
| `integration_messages.channel` | `rmf`/`omx`/`pinky` | `chk_messages_channel`. `_dispatch_kind` 와 정확히 일치한다 |
| `integration_messages.state` | 성공은 `acknowledged`, 되살아나지 않는 것은 `dead_letter` | `chk_messages_state` = `pending`/`sent`/`acknowledged`/`completed`/`failed`/`dead_letter` |
| `reservations.state` | 완주 뒤 `released` | `chk_reservations_state` = `reserved`/`in_use`/`released`/`expired`/`cancelled` |
| `inventory_lots.state` | `stored` 인 것만 주문 가능, 소진되면 `depleted` | `chk_lots_state` (6개) |
| `map_revisions.state` | `published` | `chk_map_revisions_state` = `published`/`retired` |

대조에서 설계를 고친 곳이 넷이다.

1. **`integration_messages` 에 `processed` 상태는 없다.** 성공한 outbound 메시지는
   `acknowledged` 가 된다([repositories.py:5578-5584](../../fms_gateway/app/repositories.py#L5578-L5584)).
2. **revision 은 `map_projects` 가 아니라 `map_revisions` 에 있다.**
3. **`job_steps` 의 성공은 `succeeded` 한 값뿐이다.** "종료" 로 뭉뚱그리면 `failed`
   와 `cancelled` 를 통과로 읽게 된다.
4. **재고 제약이 11.1 을 더 무겁게 만든다.** `reserved_qty <= available_qty` 이므로
   취소로 남은 예약은 같은 양의 재고를 영구히 잠근다.

또 하나: `job_steps.final_method_code` 가 L5 판정에 쓸 열이다. 시도별 값은
`job_step_attempts.method_code` 에 남는다.

## 4. 7단계 계획의 실제 모양

단일 SKU · 수량 1 · 단일 온도존 주문이 만드는 step 은 정확히 7개다
([outbound_sequence.py:75-193](../../control_tower/task_manager/outbound_sequence.py#L75-L193)).
품목이 두 온도존에 걸치면 bundle 이 늘어 step 이 7개를 넘는다. **그래서 주문은
반드시 단일 SKU · 수량 1 로 넣는다.**

| step_no | executor_type | action | 채널 | 누가 닫는가 |
|---|---|---|---|---|
| 10 | `arm` | `pick` | `omx` | `executor_worker` + `OmxProtocolSimulator` |
| 20 | `mobile` | `navigate` | `rmf` | `rmf_gateway_worker` → RMF → 로봇 task_event |
| 30 | `fms` | `load` (게이트) | `pinky` | `executor_worker` |
| 40 | `mobile` | `navigate` (포장 Dock) | `rmf` | `rmf_gateway_worker` |
| 50 | `fms` | `handover` | `pinky` | `executor_worker` |
| 60 | `fms` | `wait` | — | **사람.** `worker-completion` |
| 70 | `mobile` | `return_home` | `rmf` | `rmf_gateway_worker` |

채널 대응의 정본은 `_dispatch_kind`
([repositories.py:5177-5183](../../fms_gateway/app/repositories.py#L5177-L5183))다:
`mobile → ("rmf", "dispatch_task_request")`, `arm → ("omx", "execute_action")`,
`fms → ("pinky", "execute_fms_action")`. `rmf` 채널은 `rmf_gateway_worker` 가 집고
나머지 둘은 `executor_worker` 가 집는다(`EXECUTOR_CHANNELS = ("omx", "pinky")`).

step 60 도 `fms` 이므로 `pinky` 채널로 나가지만, `executor_worker` 는 그것을 실행하지
않고 **deferred 로 되돌린다**([executor_worker.py:128-133](../../control_tower/task_manager/executor_worker.py#L128-L133)).

## 5. A절 성공 기준 — 시뮬 (도메인 0)

"정상 동작" 같은 말은 쓰지 않는다. 아래는 전부 숫자거나 문자열이다.

### L1 — DB

| 확인 | 통과 기준 |
|---|---|
| 컨테이너 | `docker ps` 에 8개가 `Up`: `mysql`, `fms_gateway`, `control_ui`, `mediamtx`, `qr_worker`, `recording_catalog`, `rmf_api`, `rmf_dashboard` |
| 테이블 6개 | `jobs`, `job_steps`, `reservations`, `integration_messages`, `map_projects`, `inventory_lots` 에 대한 `SELECT` 가 오류 없이 반환 |
| 현재 점유 | `jobs` 중 `state IN ('queued','assigned','running','held')` 인 행과 그 `context.assignment.mobile_id` 를 표로 얻는다. 이 네 값이 `chk_jobs_state` 가 허용하는 7개 중 비종료 상태 전부다 |
| 재고 | `inventory_lots` 의 `product_code, available_qty, reserved_qty, state` 를 표로 얻는다. **이 값이 10절 주문 SKU 선택의 근거다** |

**맵 revision 은 판정 기준으로 쓰지 않는다.** 이전 UI 로 만든 지도를 지웠기 때문에
`map_revisions` 의 어떤 행도 통과/실패의 근거가 되지 못한다. 기동에 넘기는
`TRIHOUSE_MAP_REVISION` 값은 그대로 쓰되, 그 값이 DB 에 있는지를 성공 기준에
넣지 않는다. 기동이 실패하면 그때 원인으로 확인한다.

**MySQL 3308 에는 데이터베이스가 두 개다.** `schema_mysql.sql` 은 중간에
`USE \`trihouse_recovery\`` 로 대상을 바꾸고 거기에 테이블 두 개를 만든다
([schema_mysql.sql:979-1076](../../db/migrations/001_physical_v1_baseline.sql#L979-L1076)). VLM+RL 회복
데이터셋의 그릇이다. 이 문서는 **그릇이 제대로 있는지만** 판정한다 — 왜 그것뿐인지는
11.8 에 적었다.

| 확인 | 통과 기준 |
|---|---|
| DB 두 개 | `SHOW DATABASES` 에 `trihouse_fms` 와 `trihouse_recovery` 가 둘 다 |
| 회복 테이블 | `trihouse_recovery` 에 `recovery_episodes`, `recovery_steps` **2개** |
| 교차 DB FK | `trihouse_recovery` → `trihouse_fms` 참조가 **0개**. 설계상 금지다 |
| 행 수 | 두 테이블 모두 **0행**. B절 완주 뒤에 다시 세어 **여전히 0행**임을 확인한다 |
| Gateway 권한 | `SHOW GRANTS FOR 'fms_gateway'@'%'` 에 `trihouse_recovery` 가 나오는지 **확인만 하고 기록한다**(11.8) |

숫자를 미리 못박지 않는 유일한 항목이 "현재 점유"와 "재고"다. 스택이 지금 내려가
있어 값을 읽을 수 없으므로, **읽은 값 자체가 산출물**이고 그것으로 8절 승인 게이트의
대상이 정해진다.

### L2 — Gateway

| 확인 | 통과 기준 |
|---|---|
| `GET /ready` | `{"status":"ready","database":"ok"}` |
| `GET /openapi.json` | `paths` 에 다섯 개가 **전부** 있다: `/api/v1/orders`, `/api/v1/jobs/{job_id}/worker-completion`, `/internal/v1/jobs/{job_id}/cancel`, `/internal/v1/reservations/expire`, `/api/v1/operations/anomalies` |
| `GET /api/v1/jobs` | `200`, JSON 배열 |
| `GET /api/v1/inventory/lots` | `200`, L1 의 재고 표와 같은 lot 수 |
| `GET /api/v1/operations/anomalies?state=open` | `200`. 열린 이상이 있으면 **개수와 내용을 기록한다** — 통과를 막지는 않는다 |

`openapi.json` 을 보는 이유: `fms_gateway` 컨테이너는 소스 마운트가 아니라 빌드
이미지다. 코드에 엔드포인트가 있어도 이미지가 낡았으면 뜨지 않는다.

### L3 — 관제 (호스트 ROS, 단일 로봇 `TRIHOUSE_ROBOTS=pinky_01`)

`/tmp/sim.log` 를 근거로 한다. **주문이 없는 상태에서** 판정한다.

| grep | 통과 기준 | 뜻 |
|---|---|---|
| `Managed nodes are active` | `2` | localization 1 + navigation 1 |
| `Failed to bring up all requested\|Failed to change state` | 빈 출력 | lifecycle 포기 |
| `We will not add the robot` | `0` | fleet 등록 실패 |
| `Invalid frame ID "odom"` | `0` | costmap 프레임 |
| `RMF dispatch cycle failed` | `0` | worker 사망 |
| `RMF dispatch cycle:` | `0` 보다 큼 | worker 가 주기를 돈다. 이 로그는 **주기마다 무조건** 나온다 |

세 워커 프로세스의 생존은 로그로 판정할 수 없다. `job runner cycle:` 은
`assigned`/`dispatched`/`expired` 중 하나라도 있을 때만 나오고
([job_runner.py:80-82](../../control_tower/task_manager/job_runner.py#L80-L82)),
`executor cycle:` 은 `succeeded`/`failed` 가 있을 때만 나온다
([executor_worker.py:66-68](../../control_tower/task_manager/executor_worker.py#L66-L68)).
**주문이 없으면 둘 다 조용한 것이 정상이다.** 그래서 생존은 프로세스로 본다 —
`ros2 node list` 는 부하에 멈추므로 쓰지 않는다.

| 확인 | 통과 기준 |
|---|---|
| `pgrep -af 'task_manager\.job_runner_node'` | **1줄** |
| `pgrep -af 'task_manager\.executor_worker_node'` | **1줄** |
| `pgrep -af 'rmf_adapter\.rmf_gateway_worker_node'` | **1줄** |

2줄 이상이면 이전 세대가 남은 것이고, 두 러너가 같은 job 을 두고 경쟁하므로 그
상태의 측정값은 믿을 수 없다. `scripts/sim_teardown.sh` 로 내리고 다시 시작한다.

`job runner blocked: ...` 는 **잔여 job 이 자원을 쥐고 있을 때만** 나온다. G1 전에는
나오는 것이 정상이고, G1 뒤에는 사라져야 한다. 그 사라짐 자체가 G1 이 들은 증거다.

`uptime` 을 함께 적는다. load average 가 60 을 넘으면 위 실패는 부하이지 버그가
아니다. **단, 단일 로봇으로 띄웠는데도 실패하면 그것은 남은 버그다.**

> **`scripts/control_stack doctor` 를 판정에 쓰지 않는다.** `REQUIRED_CHECKS` 에
> `nav2:PK_02`·`omx:OMX_02` 가 박혀 있어 단일 로봇에서는 통과할 수 없고
> ([scripts/control_stack:83-99](../../scripts/control_stack#L83-L99)),
> 호스트 ROS 판정을 `ros2 node list` 로 한다
> ([scripts/control_stack:259-267](../../scripts/control_stack#L259-L267)) — 부하가
> 높으면 멈춘다고 문서가 경고하는 바로 그 명령이다. 참고로만 돌리고 결과를 기록한다.

### L4 — 로봇 (시뮬)

```bash
python3 scripts/verify_robot_status.py pinky_01 20
```

| 줄 | 통과 기준 |
|---|---|
| `publishers` | `{'status': 1, 'scan': 1, 'amcl_pose': 1}` — **하나라도 2 이상이면 이전 세대가 남은 것이고 나머지 값은 못 믿는다** |
| `frame_id` | `map` |
| `dispatchable` | `true` |
| `errors` | `[]` |
| 마지막 줄 | `RESULT: PASS` (종료코드 0) |

`ros2 topic echo` · `topic list` · `param get` 은 쓰지 않는다.

**시뮬에서 판정하지 않는 것**: LED·부저·초음파·OLED·`safety_supervisor`. 시뮬
launch 가 그 노드들을 띄우지 않는다. 이 다섯은 **실기 A절에서만** 판정된다(7절).

### L5 — OMX (ROS 왕복)

`gazebo_omx_adapter` 두 개가 `p0_simulation_bringup.sh` 3단계에서 노드 이름
`omx_01`·`omx_02` 로 뜬다. 둘 다 **같은 절대 토픽**에 발행하므로 `robot_id` 로
갈라 읽는다(`OMX_01` → `PK_01`).

| 조작 | `/trihouse/handover/state` | `/trihouse/cargo/state` |
|---|---|---|
| `mock_load_confirmed:=false` (적재 준비) | `state: 2` (REQUESTED), `detail` 에 `awaiting cargo confirmation` | `state: 1` (UNLOCKED), `sensor_confirmed: false` |
| `mock_load_confirmed:=true` (적재 완료) | `state: 1` (READY), `detail` 에 `cargo confirmed` | `state: 2` (LOCKED), `sensor_confirmed: true` |

값은 [HandoverState.msg](../../trihouse_interfaces/msg/HandoverState.msg) 와
[CargoState.msg](../../trihouse_interfaces/msg/CargoState.msg) 의 상수다.

파라미터를 바꾸는 방법은 `ros2 param set /omx_01 mock_load_confirmed true` 다.
**이 명령은 노드 이름으로 서비스를 찾으므로 부하가 높으면 멈춘다.** 멈추면 대체
경로가 있다: `p0_simulation_bringup.sh` 를 내리고 `ros2 run trihouse_omx_adapter
gazebo_omx_adapter --ros-args -r __node:=omx_01 -p omx_id:=OMX_01 -p
robot_id:=PK_01 -p mock_load_confirmed:=true` 로 한 개만 직접 띄워 같은 두 토픽을
읽는다. 어느 경로를 썼는지 기록에 적는다.

## 6. B절 성공 기준 — 완주 한 줄기 (시뮬)

A절 다섯 층이 전부 통과한 뒤에만 시작한다.

| # | 조작 / 확인 | 통과 기준 |
|---|---|---|
| B1 | `POST /api/v1/orders` (단일 SKU, 수량 1, `Idempotency-Key` 필수) | `201`. 응답에 job 하나 |
| B2 | `job_steps` 조회 | 그 job 의 step 이 **7행**. `executor_type` 이 4절 표와 일치 |
| B3 | `job runner cycle:` 로그 | `assigned=[<새 job_id>]` 가 나온다 |
| B4 | `RMF dispatch cycle:` 로그 | `claimed=` 가 1 이상 |
| B5 | step 10 (`arm`/`pick`) | `job_steps.state='succeeded'`, `job_steps.final_method_code='OMX_SIMULATED_CONTRACT'`. 그 step 의 `integration_messages` (`channel='omx'`) 행이 `state='acknowledged'` |
| B6 | step 20 (`mobile`/`navigate`) | RMF 가 낙찰(`Assigning task` 또는 bid 로그). `--gui` 로 띄웠으면 Pinky 가 움직인다 |
| B7 | step 30·40·50 | 순서대로 종료. `job.state` 가 `running` |
| B8 | step 60 (`wait`) | **여기서 선다. 이것이 정상이다.** 로그에 `executor deferred: step <N>: wait awaits the worker` 가 매 주기 나온다 |
| B9 | `POST /api/v1/jobs/{id}/worker-completion` (`{"worker_id":"W-OP-01"}`) | `200`. step 60 종료 |
| B10 | step 70 (`return_home`) | 종료 |
| B11 | `jobs` 조회 | 그 job 이 `completed` |
| B12 | `reservations` 조회 | 그 job 의 예약이 전부 `released` |
| B13 | `inventory_lots` 조회 | 주문한 lot 의 `available_qty` 와 `reserved_qty` 가 **각각 1** 줄었다. `available_qty` 가 0 이 되면 `state` 가 `depleted` 로 갔는지 함께 적는다 |
| B14 | `job_step_attempts` 조회 | 그 job 의 시도 행이 **1개 이상**이고 `metrics` JSON 에 `duration.total_ms` 와 `duration.environment` 가 있다. **이것이 '이벤트마다 데이터가 쌓인다'를 관측하는 자리다**(11.9) |
| B15 | `trihouse_recovery` 조회 | `recovery_episodes`·`recovery_steps` 가 **여전히 0행**. 쌓이지 않는 것이 현재의 사실이다(11.8) |

B12 가 `reserved`/`in_use` 로 남으면 RMF task update 가 도착하지 않은 것이다.
그때는 `POST /internal/v1/reservations/expire` 를 부르고 열린 이상을 기록한다 —
**그 이상은 사람이 확인하기 전까지 닫히지 않는다.**

막혔을 때 원인을 가르는 표는 계획서 각 Task 안에 둔다. `docs/validation/2026-08-18-p0-manual-test.md`
9.4 의 표를 재발명하지 않고 그대로 참조한다.

## 7. 실기 트랙 (도메인 52)

시뮬 완주가 통과한 뒤에만 시작한다. **같은 항목이라도 전제와 기대값이 다르다.**

### 7.1 시뮬과 실기의 차이

| 층 | 시뮬 | 실기 |
|---|---|---|
| 도메인 | `ROS_DOMAIN_ID=0` | `ROS_DOMAIN_ID=52` |
| L1 DB | 같다. **하나뿐이다** | 같다 |
| L2 Gateway | 같다 | 같다. 단 컨테이너를 도메인 52 로 다시 올려야 한다(7.2) |
| L3 관제 | `p0_simulation_bringup.sh` | **스크립트가 없다**(7.3) |
| L4 로봇 | Gazebo 로봇. LED·부저·초음파·OLED·safety 없음 | 실물 Pinky. 그 다섯이 여기서 처음 판정된다 |
| L5 OMX | `gazebo_omx_adapter` ROS 왕복(5절) + 완주 중 arm step | **ROS 왕복은 시뮬 전용이다.** 실기에는 `gazebo_omx_adapter` 가 없다. 실기 L5 는 완주 중 arm step 하나로만 판정한다 |

L1 과 L2 는 도메인과 무관하므로 실기 A절에서 다시 판정하지 않는다. **실기 A절은
L3·L4·L5 만 본다.**

### 7.2 Docker 층 도메인 전환

`compose.simulation.yaml` 의 `rmf_api` 는 `${ROS_DOMAIN_ID:-52}` 를 읽는다. 시뮬을
0 으로 돌렸으므로 컨테이너가 0 으로 떠 있고, **실기는 그 상태에서 RMF 대시보드도
fleet 도 보지 못한다.** 그래서 트랙 전환에 재기동이 들어간다.

```text
시뮬 완주 통과
  → scripts/sim_teardown.sh          (호스트 ROS 층만 내린다)
  → 승인 게이트                       (8절)
  → ROS_DOMAIN_ID=52 scripts/control_stack up   (Docker 층 재기동)
  → docker inspect ... | grep ROS_DOMAIN_ID     (52 인지 확인)
```

MySQL 데이터는 `trihouse_p0_trihouse_mysql_data` 볼륨에 있어 재기동으로 사라지지
않는다. **그래도 재기동은 되돌릴 수 없는 조작으로 다룬다** — 8개 컨테이너가 내려갔다
올라오고, 그 사이 UI 와 Gateway 가 끊긴다.

### 7.3 실기 관제 ROS 조합은 새로 조립해야 한다

`p0_simulation_bringup.sh` 는 Gazebo 를 띄우는 유일한 스크립트다. 실기는 Gazebo 도
시뮬 Nav2 도 필요 없고, 로봇이 자기 Nav2 를 자기 위에서 돌린다. 필요한 것은 RMF
core + fleet adapter + 세 워커다.

`two_pinky_order_demo.launch.py` 에 `start_gazebo`·`start_nav2` 인자가 이미 있으므로
조합은 가능하다. **다만 아무도 그 조합을 돌린 적이 없다.** 계획서는 이 조합을
절차로 적되, 이것이 **미검증 조합**임을 명시하고 실패하면 그것을 결함이 아니라
관측으로 기록한다.

실기 `fleet_gateway` 의 `control_host` 는 `127.0.0.1` 이 아니라 관제 PC 의 LAN IP
여야 한다. 기본값 그대로면 `control_link_offline` 이 남는다.

### 7.4 실기 A절 — L4 에서 처음 판정되는 다섯

시뮬에 없던 것들이다. 절차는 `docs/validation/2026-08-18-pinky-hardware-nav2-smoke.md`
6.2~6.7 이 이미 갖고 있으므로 **재발명하지 않고 참조한다.** 요약하면:

| 대상 | 통과 기준 | 주의 |
|---|---|---|
| 벤더 센서 | `scan`/`odom`/`batt_state`/`us_sensor/range` 넷 다 값이 나온다 | 여기가 비면 아래가 반드시 빈다 |
| `_io` 어댑터 | `trihouse/battery`, `trihouse/proximity/front` 에 값 | 어댑터가 namespace 밖일 수 있다 |
| LED·부저 | `emergency_request` 래치 → `IndicatorState.state: 2`, `SafetyState.state: 3`, `latched: true` | **`trihouse/indicator/state` 에 직접 publish 하지 않는다.** `safety_supervisor` 가 20 Hz 로 덮어쓴다 |
| 해제 | `clear_emergency` 서비스 → `accepted=true`, `latched: false` | `emergency_request: false` 로는 풀리지 않는다. **주행 전에 반드시 푼다** |
| 카메라 | `stream_health` `state: 1`(HEALTHY), fps ≈ 15. RTSP 프레임 `shape: (720, 1280, 3)` | **영상은 ROS 토픽으로 나가지 않는다.** MediaMTX 인가는 발행자 IP 로 제한된다 |

실기 L4 종합은 `ROS_DOMAIN_ID=52 python3 scripts/verify_robot_status.py pinky_01 20`
이고, 관제를 켠 뒤이므로 **`errors` 는 `[]` 여야 한다** — 관제 없이 도는 smoke
문서와 달리 `control_link_offline` 이 남으면 실패다.

### 7.5 실기 B절

시뮬 B절과 같은 13개 항목을 같은 순서로 본다. 다른 것은 B6 에서 **실물 로봇이
실제로 움직인다**는 것뿐이다. 안전 조건은 smoke 문서 1절을 따른다: 전방을 비우고
물리 비상정지를 손 닿는 곳에 둔다. `/cmd_vel` 발행자가 `safety_supervisor` **하나**
인지 먼저 확인한다.

## 8. 승인 게이트 — 되돌릴 수 없는 조작

아래 조작은 **사람이 명시적으로 승인하기 전에는 하지 않는다.** 계획서에서 각각
독립 체크박스이며, 승인 없이 다음 Task 로 넘어가지 않는다.

| # | 조작 | 왜 되돌릴 수 없는가 | 승인 시점 |
|---|---|---|---|
| G1 | `POST /internal/v1/jobs/{id}/cancel` (잔여 job) | job·step·예약·outbox 를 한 트랜잭션에서 닫는다. **그리고 재고 예약은 돌려주지 않는다**(11.1) | L1 에서 현재 점유를 읽은 뒤, 대상 job_id 를 사람이 지목 |
| G2 | `POST /api/v1/orders` | 재고 lot 을 실제로 예약하고, 완주하면 소진한다. 취소해도 돌아오지 않는다 | B절 시작 직전. 건수는 10절 상한 안에서 |
| G3 | `POST /api/v1/jobs/{id}/worker-completion` | 물리 재고 확정을 승인하는 호출이다. 사람 확인이 그 자리의 목적이다 | B9 |
| G4 | `scripts/control_stack up` / `down` (도메인 전환) | 8개 컨테이너가 내려갔다 올라온다. UI·Gateway 가 그 사이 끊긴다 | 7.2 트랙 전환 |
| G5 | 실기 로봇 주행 | 물리적으로 움직인다 | 실기 B6 직전 |
| G6 | `POST /internal/v1/reservations/expire` | 예약을 만료로 밀고 이상을 연다 | B12 가 실패했을 때만 |
| G7 | `UPDATE inventory_lots SET reserved_qty = …` | **원장 직접 수정이다.** 취소된 job 이 잠가 둔 재고를 되찾는 유일한 경로이고, API 가 없다(11.1) | L1 에서 잠긴 lot 을 확인하고 10절 예산이 모자랄 때만 |

### G7 을 쓰는 법

취소된 job 이 잠근 재고는 API 로 풀리지 않는다. 되찾으려면 원장을 직접 고치는
수밖에 없고, 그래서 **가장 위험한 게이트**다. 대상을 먼저 눈으로 확인한다.

```sql
-- 잠긴 것: 종료된 job 만 참조하는데 reserved_qty 가 남은 lot
SELECT lot_id, product_code, available_qty, reserved_qty, state
  FROM trihouse_fms.inventory_lots
 WHERE reserved_qty > 0 ORDER BY lot_id;
```

이 목록을 살아 있는 job(`state IN ('queued','assigned','running','held')`)의 예약
품목과 대조해 **어느 job 도 참조하지 않는 것만** 푼다. 살아 있는 job 의 예약을
풀면 그 job 이 없는 재고를 집으러 간다.

근본 수정(`cancel_job` 이 재고까지 닫게 하는 것)은 구현이므로 이 문서 밖이다.

**계획을 세우는 동안에는 어떤 조작도 하지 않는다.** 읽기 전용 조회(`curl` GET,
`SELECT`, 파일 읽기)만 한다.

## 9. 단일 로봇 기본 / 2대 필요 항목

**기본은 `TRIHOUSE_ROBOTS=pinky_01` 단일 로봇이다.** 12코어 개발 PC 에서 로봇 2대 +
Gazebo + Open-RMF 는 load average 60~90 까지 가고, 그 상태에서 Nav2 lifecycle 이
포기하며 ROS CLI 도 멈춘다. 설정 결함이 아니라 용량이다.

2대가 있어야 하는 항목은 아래뿐이고, **전부 4060/5080 이관 후로 미룬다.**

| 항목 | 왜 2대가 필요한가 | 지금 미루는 이유 |
|---|---|---|
| Open-RMF 교통 협상 | 두 로봇이 같은 lane 을 놓고 협상하는 것을 보려면 둘이 있어야 한다 | 부하 |
| `control_stack doctor` 전체 통과 | `REQUIRED_CHECKS` 가 `PK_02`·`OMX_02` 를 요구한다 | 부하 |
| 병목 상호배제 | — | **2대를 띄워도 관측되지 않는다.** 아래를 보라 |

병목 항목은 미루는 것이 아니라 **이 문서의 판정 대상이 아니다.** 스키마 대조로
그것을 확인했다.

`reservations` 는 병목 배타성을 제대로 갖추고 있다. `reservation_mode='bottleneck_lock'`
이고 `state IN ('reserved','in_use')` 이면 생성 열 `active_resource_key` 가
`feature:<map_feature_id>` 가 되고, 그 열에 `UNIQUE KEY uq_reservations_active_resource`
가 걸려 있다([schema_mysql.sql:606-625](../../db/migrations/001_physical_v1_baseline.sql#L606-L625)). 즉 같은
병목을 두 job 이 동시에 쥐는 것은 **DB 가 막는다.**

문제는 그 행을 만드는 코드가 없다는 것이다. `fms_gateway/` 와 `control_tower/`
전체에서 `bottleneck_lock` 도 `map_feature_id` 도 한 번도 나오지 않는다. 파이썬
`BottleneckLease`([rmf_adapter/bottleneck.py](../../control_tower/rmf_adapter/bottleneck.py))
는 테스트만 import 한다. **메커니즘은 있고 기록자가 없다.** 그래서 로봇을 몇 대
띄우든 이 경로는 돌지 않는다. 실제 상호배제는 Open-RMF 자체 교통 협상이 한다.

## 10. 재고 예산

**주문 상한 4건.** 취소해도 재고가 돌아오지 않으므로(11.1) 실패한 주문도 개수에
들어간다.

| 몫 | 건수 |
|---|---|
| 시뮬 완주 | 1 |
| 시뮬 재시도 여유 | 1 |
| 실기 완주 | 1 |
| 실기 재시도 여유 | 1 |

규칙:

- **단일 SKU · 수량 1** 로만 넣는다(4절). 여러 온도존이면 step 이 7개를 넘는다.
- 4건은 **서로 다른 SKU** 를 쓴다. 같은 SKU 를 반복하면 `reservable_qty` 가 먼저
  바닥나 `409 INSUFFICIENT_STOCK` 이 난다.
- SKU 는 L1 에서 읽은 `available_qty - reserved_qty > 0` 인 것 중에서 고른다.
  seed 기준 11 lot / 17 단위이지만 **이전 세션의 job 이 이미 일부를 잠가 놓았다.**
- 4건을 다 쓰면 **멈추고 보고한다.** 재적재는 이 문서의 범위 밖이다.

## 11. 관측만 하고 고치지 않는 것

설계 단계에서 코드를 읽다 나온 결함이다. **고치지 않는다.** 계획서에서는 "관측한다"
항목으로만 들어가고, 실제로 관측되면 `docs/validation/` 기록에 남긴다.

### 11.1 취소가 재고 예약을 돌려주지 않는다

[`cancel_job`](../../fms_gateway/app/repositories.py#L3631-L3846) 전체(3631–3846행)에
`inventory_lots` 도 `reserved_qty` 도 한 번도 나오지 않는다. 닫는 것은 job·job_steps·
reservations(로봇/팔/Dock)뿐이다. 주문 수락은 `available_qty - reserved_qty > 0` 으로
판정하므로([repositories.py:3022](../../fms_gateway/app/repositories.py#L3022)),
**취소한 주문의 재고는 영원히 잠긴 채 남는다.** 지금 막혀 있는 job 도 이미 그렇게
잠가 놓고 있다.

스키마가 `chk_lots_qty CHECK (available_qty >= 0 AND reserved_qty >= 0 AND
reserved_qty <= available_qty)` 로 두 값을 묶어 두었으므로
([schema_mysql.sql:349-351](../../db/migrations/001_physical_v1_baseline.sql#L349-L351)), 취소로 남은
`reserved_qty` 는 그만큼의 `available_qty` 를 **영구히 주문 불가로 만든다.**
`available_qty = reserved_qty` 가 된 lot 은 재고가 있는데도 주문할 수 없다.

관측 방법: G1 전후로 `inventory_lots` 의 `available_qty, reserved_qty` 를 찍어
비교한다. `reserved_qty` 가 바뀌지 않으면 관측된 것이다.

### 11.2 러너의 점유 계산이 원장과 갈라진다

예약이 `expired` 로 회수되어도 그 job 이 `queued`/`assigned`/`running`/`held` 인 한
`job_runner` 는 그 자원을 점유로 센다([job_runner.py:319](../../control_tower/task_manager/job_runner.py#L319)).
배타성의 정본은 `reservations.active_resource_key` 인데 러너가 매 주기 따로 계산한다.
2026-08-18 에 이미 실측된 갈라짐이고
(`docs/validation/2026-08-18-p0-manual-test.md` 9.4), 이번에도 나오면 그대로 적는다.

### 11.3 `dead_letter` 는 되살아나지 않는다

`integration_messages.state='dead_letter'` 인 메시지는 재시도 대상이 아니다. 그
step 은 다시 dispatch 되지 않으므로 그 job 은 취소하고 새 주문으로 다시 시작하는
것이 유일한 경로다.

### 11.4 `doctor` 가 단일 로봇에서 통과할 수 없다

5절 L3 의 각주와 같다. 판정에 쓰지 않되 출력은 기록한다.

### 11.5 두 OMX 어댑터가 같은 절대 토픽에 발행한다

`gazebo_omx_adapter` 는 `/trihouse/handover/state` 를 절대 이름으로 발행한다
([gazebo_adapter_node.py:41](../../trihouse_omx_adapter/trihouse_omx_adapter/gazebo_adapter_node.py#L41)).
단일 로봇으로 띄워도 bringup 은 OMX 두 개를 다 띄우므로 발행자가 2다. `robot_id`
로 갈라 읽어야 하고, 이것을 결함으로 볼지는 관측 뒤에 정한다.

### 11.6 실기 관제 ROS 조합이 미검증이다

7.3 과 같다. 조합 자체를 처음 돌리는 것이므로 실패를 기대값에 넣어 둔다.

### 11.7 실물 OMX 연결 — 별도 설계로 나갔다

`hardware_adapter_node` 에 검증된 endpoint 를 연결해 실기 팔이 움직이게 하는 것은
**확인이 아니라 구현이다.** [2026-08-18-omx-arm-hardware-design.md](2026-08-18-omx-arm-hardware-design.md)
가 그것을 다룬다.

이 검증 문서는 그쪽에 **입력을 준다**: 5절 L5 의 ROS 왕복이 통과하면 명령 계약면이
확인된 것이고, B절의 arm step 이 닫히면 Gateway ↔ 실행기 경로가 확인된 것이다.
로봇팔 설계는 그 두 지점 사이에 실물 모션을 끼워 넣는 일이다.

### 11.8 `trihouse_recovery` 에는 기록자가 없다

그릇은 있는데 붓는 코드가 없다. 세 겹으로 확인했다.

1. **런타임 기록자 0.** `recovery_episodes`·`recovery_steps` 에 `INSERT` 하는 코드는
   `fms_gateway/tests/integration/test_schema.py` 뿐이다. `fms_gateway/app/` 에도
   `control_tower/` 에도 없다.
2. **Gateway 는 DB 를 하나만 안다.** `config.py:23` 이 `database: str = "trihouse_fms"`
   이고 두 번째 연결이 없다.
3. **P0 스택에는 권한 스크립트가 붙지 않는다.** `db/init/003_grant_gateway_recovery.sh`
   는 `compose.db.yaml`(3306)과 `compose.db_test.yaml`(3307)에만 마운트되어 있고
   **`compose.yaml`(3308 운영)에는 없다.** 3308 에서는 DB 가 생겨도 `fms_gateway`
   사용자에게 권한이 없다.

그리고 `chk_recovery_episodes_trigger` 가 허용하는 trigger 는
`blocked`/`person`/`low_visibility`/`localization` 넷인데, 이것을 만들 VLM/RL 스택은
5080 에 있고 P0 는 그것을 **명시적으로 금지한다**
(`FORBIDDEN_IN_SIMULATION = ("compose.ai_5080.yaml",)`).

**그래서 이번 테스트로 "이벤트가 일어나면 데이터셋이 쌓인다"를 확인할 수 없다.**
쌓일 경로 자체가 없기 때문이다. 확인할 수 있는 것은 L1 에 적은 네 가지 — DB·테이블
존재, 교차 FK 없음, 행 수 0, 권한 상태 — 뿐이고, 그 **0행이 곧 관측 결과**다.
확인 대신 추측하지 않기 위해 굳이 세어 기록한다.

권한 누락을 결함으로 볼지는 판단을 미룬다. 기록자가 없는 동안에는 P0 에 권한이
없어도 아무것도 깨지지 않는다. 다만 나중에 기록자를 붙이면 3308 에서만 조용히
실패한다 — 그것을 [2026-08-18-recovery-ingestion-design.md](2026-08-18-recovery-ingestion-design.md)
가 다룬다. **이 검증에서 세는 0행이 그 설계의 출발선이다.**

### 11.9 P0 에서 실제로 쌓이는 데이터셋은 duration 표본이다

회복 데이터셋과 달리 이쪽은 **런타임에 실제로 쌓인다.** `executor_worker` 가 각
step 의 실측 소요를 `{"duration": {"total_ms", "segments", "environment",
"attribution": "measured"}}` 로 만들고
([executor_worker.py:191-205](../../control_tower/task_manager/executor_worker.py#L191-L205)),
Gateway 가 그것을 `job_step_attempts.metrics` (JSON) 에 넣는다
([repositories.py:4206-4236](../../fms_gateway/app/repositories.py#L4206-L4236)).
`--environment` 인자가 여기에 태그로 들어가므로 시뮬 표본이 실기 보정을 오염시키지
않는다.

**다만 집계 테이블에는 기록자가 없다.** `duration_baselines` 에 `INSERT` 하는 코드도
테스트뿐이다. 원표본은 쌓이고 baseline 은 비어 있는 상태다.

B절에서 확인할 수 있다: 완주 뒤 그 job 의 `job_step_attempts` 를 세고
`metrics` 에 `duration.total_ms` 가 들어 있는지 본다. **이것이 이번 테스트에서
"이벤트마다 데이터가 쌓인다"를 실제로 관측할 수 있는 유일한 자리다.**

## 12. 함정 — 계획서 전체에 적용된다

정본은 `docs/validation/2026-08-18-p0-manual-test.md` 7절과
`2026-08-18-pinky-hardware-nav2-smoke.md` 9절이다. 여기서는 **이 검증에서 반드시
지켜야 하는 것만** 다시 적는다.

- **도메인을 섞지 않는다.** 시뮬 0, 실기 52. 모든 터미널에서 같은 값을 export 한다.
- **source 3단**: `/opt/ros/jazzy/setup.bash` → `install/setup.bash` →
  `pinky_pro/install/setup.bash`.
- **`pkill -f` 를 직접 쓰지 않는다.** `scripts/sim_teardown.sh` 를 쓴다. 단 이
  스크립트는 같은 셸의 pytest 도 죽이므로 테스트와 동시에 돌리지 않는다.
- **`ros2 topic list` / `node list` / `param get` 은 부하가 높으면 멈춘다.** 이름과
  타입을 함께 준 pub/sub 은 동작한다. 상태 판정은 `verify_robot_status.py` 로 한다.
- **`trihouse/indicator/state` 에 직접 publish 하지 않는다.**
- **`compose.control.yaml` 단독으로는 기동되지 않는다.** 네 파일을 `-f` 로 묶고
  `--project-name trihouse_p0 --env-file .env` 를 준다. `scripts/control_stack` 이
  이미 그렇게 한다.
- **MySQL 3308 만 본다.** 3307 에는 `trihouse_fms` 데이터베이스 자체가 없다.
- **수동 검증은 worktree 에서 돌리지 않는다.** 스택이 `/home/syw/Trihouse` 기준으로
  뜨고 `.trihouse/p0/` 와 Docker bind mount 가 그 경로에 묶여 있다.

## 13. 산출물

이 검증의 산출물:

| 파일 | 무엇 |
|---|---|
| `docs/claude/2026-08-18-backend-manual-test-design.md` | 이 문서 |
| `docs/claude/2026-08-18-backend-manual-test-plan.md` | Task 와 체크박스. **실측값을 적지 않는다** |
| `docs/validation/2026-08-18-backend-manual-test-run.md` | 빈 기록표. 사람이 실제 출력을 붙인다. **실패한 것을 성공한 것과 함께 그대로 적는다** |

이 문서에서 갈라져 나간 두 구현 설계:

| 파일 | 무엇 | 이 문서와의 관계 |
|---|---|---|
| `docs/claude/2026-08-18-recovery-ingestion-design.md` | `trihouse_recovery` 에 주행 중 데이터가 쌓이게 한다 | 11.8 의 0행이 출발선 |
| `docs/claude/2026-08-18-omx-arm-hardware-design.md` | 로봇팔 통신 패키지 + ACT 정책 + 실제 파지 | 11.7. 실기 완주 전에 끝나야 한다 |

**순서는 검증이 먼저다.** 층이 도는 것을 확인하지 않은 채 구현을 얹으면 새 결함과
기존 결함을 가를 수 없다.

계획서는 실행하면서 체크박스를 **그 자리에서** 갱신한다. 다 끝난 뒤 한꺼번에
칠하지 않는다.

---

## 14. 부록 — 판정하기 전에 알아야 할 개념

성공 기준을 읽으려면 아래 여섯 가지를 먼저 알아야 한다. 전부 코드와 스키마에서
확인한 것이고, 확인되지 않은 것은 "없다"고 적었다.

### 14.1 MySQL 이 세 개인 이유와, 두 개로 줄이는 방법

세 개가 우연히 쌓인 것이 아니다. 각각 다른 일을 한다.

| 포트 | Compose | 무엇 | 이 검증에서 |
|---|---|---|---|
| **3308** | `compose.yaml` | **Gateway 가 실제로 쓰는 DB.** L1 판정 대상 | **여기만 본다** |
| 3306 | `compose.db.yaml` | 보존되는 개발 DB | 건드리지 않는다 |
| 3307 | `compose.db_test.yaml` | tmpfs 테스트 DB. 재시작하면 사라진다 | e2e 전용 |

**3308 이 생긴 이유**는 네트워크다. `compose.control.yaml` 이 `db_internal` 격리
네트워크를 만들고 거기에 Gateway 와 MySQL 만 붙인다. 그 구조를 한 Compose project
안에서 완성하려고 `compose.yaml` 에 MySQL 을 넣었고, 그 결과 **Gateway 는 3306 DB 에
네트워크 수준에서 도달할 수 없다**(커밋 `fe9a9c18` 의 실측). 포트 번호가 늘어난 것이
아니라 **격리 경계가 늘어난 것**이다.

**혼란의 진짜 원인은 3306 과 3308 이 같은 스키마의 개발 데이터를 따로 들고 갈라졌다는
것**이다. `trihouse_test_01` 의 draft revision 이 3306 은 27, 3308 은 2 이고,
`trihouse_test`·`project1` 은 3308 에 아예 없다. UI 는 Gateway 를 거치므로 지금 UI 로
저장한 것은 3306 에서 보이지 않는다.

**권고 — 운영 1 + 테스트 1, 두 개로 줄인다.**

1. 3306 에만 있는 지도 작업물의 **가치를 먼저 판정한다.** 이전 UI 산출물을 이미
   지우기로 했으므로(맵 revision 을 판정에서 뺀 이유가 그것이다) 대부분 버릴 수 있다.
   남길 것이 있으면 UI 로 3308 에 다시 만든다 — 그것이 정상 경로다.
2. 판정이 끝나면 `compose.db.yaml` 을 지운다. 이미 네 번째 정의(`compose.test.yaml`)를
   같은 이유로 지운 전례가 있다.
3. **포트 번호는 3308 을 유지한다.** 3306 으로 되돌리려는 유혹이 있지만,
   `db_internal` 격리 구조가 `compose.yaml` + `compose.control.yaml` 쌍에 묶여 있어
   번호만 바꾸면 얻는 것 없이 검증된 구성을 흔든다. **이름을 "운영 3308 / 테스트 3307"
   로 문서에서 고정하는 것으로 충분하다.**

이 정리 자체는 이 검증의 범위 밖이다. 검증은 3308 만 본다.

### 14.2 `jobs.state = held` 는 무엇인가

**비상 hold 다.** 두 성질이 코드에 못박혀 있다([job_runner.py:50-57](../../control_tower/task_manager/job_runner.py#L50-L57)).

- **배경 프로세스가 절대 풀 수 없다.** `ACTIVE_JOB_STATES` 에서 의도적으로 빠져 있고
  주석이 이유를 적는다 — "an emergency hold must not be lifted by a background poll,
  only by the operator review path".
- **그런데도 자원을 계속 쥔다.** `OCCUPYING_JOB_STATES` 에는 들어간다. held job 은
  로봇과 dock 을 놓지 않는다.

전환 근거는 [sr07-08-41 설계:229](../../docs/superpowers/specs/2026-08-12-sr07-08-41-rmf-order-reservation-design.md#L229)
의 `ADMIN_INTERVENTION_REQUIRED` 다.

**다만 `held` 로 바꾸는 코드가 지금 없다.** 저장소 전체에서 `'held'` 는 읽히기만
하고 쓰이지 않는다. 그래서 이 검증에서 `held` job 을 볼 일은 없고, L1 의 점유 조회에
포함시키는 것은 **혹시 있으면 놓치지 않기 위해서**다.

### 14.3 `job_steps.state` 와 `integration_messages.state` 의 차이

**층이 다르다. 하나는 업무 원장이고 하나는 배달 원장이다.**

| | `job_steps.state` | `integration_messages.state` |
|---|---|---|
| 답하는 질문 | **일이 어디까지 됐는가** | **명령이 전달됐는가** |
| 값 | `pending` → `running` → `succeeded`/`failed`/`cancelled` | `pending` → `sent` → `acknowledged`/`failed`/`dead_letter` |
| 개수 | step 하나에 1행 | step 하나에 **여러 행** (재시도마다) |
| 누가 바꾸는가 | Gateway 가 outcome 을 받아서 | Gateway 가 claim·ack·재시도마다 |

**둘이 어긋나는 것이 정상적인 상태가 있다.** 지금 막혀 있는 job 이 그 예다 —
메시지는 `dead_letter`(배달 포기)인데 step 은 `pending`(일은 안 됨) 이다. 메시지가
죽었다고 step 이 실패로 닫히지 않는다. 그래서 그 job 은 영영 전진하지 않으면서도
"실패"로 보이지 않는다.

판정할 때 **둘을 같이 읽어야 하는 이유**가 이것이다. step 만 보면 "왜 안 가지?" 로
끝나고, 메시지만 보면 "죽었네" 로 끝난다.

### 14.4 `reservations.state` 가 다섯 개인 이유

먼저 **둘로 갈린다.** 생성 열 `active_resource_key` 는 `reserved` 와 `in_use` 에서만
값을 갖고, 그 열에 UNIQUE 가 걸려 있다. **앞의 둘이 점유이고 뒤의 셋은 비점유다.**

| 값 | 점유? | 뜻 |
|---|---|---|
| `reserved` | O | 잡아 두었다. 아직 쓰지 않았다 |
| `in_use` | O | 실제로 쓰는 중이다. **로봇이 거기 있다** |
| `released` | X | 정상적으로 다 쓰고 놓았다 |
| `expired` | X | **시간이 지나 시스템이 걷어 갔다** |
| `cancelled` | X | 사람이 취소해서 놓았다 |

**앞의 둘을 합칠 수 없는 이유**: `in_use` 는 로봇이 물리적으로 그 자리에 있다는 뜻이고
`reserved` 는 아니다. 정리 판단이 갈린다 — `in_use` 인 예약은 함부로 건드리면 움직이는
로봇의 자원을 뺏는 것이 된다.

**뒤의 셋을 합칠 수 없는 이유**: **왜 놓았는가가 다르고, 그 차이가 동작을 바꾼다.**
`expired` 만 이상(anomaly)을 연다. 시간이 지나 시스템이 걷어 갔다는 것은 **자원은
풀렸는데 로봇이 아직 거기 있을 수 있다**는 뜻이기 때문이다. 그 이상은 사람이 눈으로
확인하기 전까지 닫히지 않는다. `released` 와 `cancelled` 는 그럴 이유가 없다.

즉 다섯 개는 "점유/비점유"라는 **한 축**과 "왜"라는 **또 한 축**의 곱이고, 두 축이
각각 다른 코드 경로를 만든다.

### 14.5 `control_stack doctor` 가 무엇인가

**Docker 층과 호스트 ROS 층을 한 명령으로 점검해 14개 항목을 `healthy`/`absent` 로
보고하는 진단 명령**이다. 판정 근거는 두 갈래다.

```text
doctor
├─ Docker 4개  ─ docker compose ps 의 Health/State 를 읽는다
│                mysql, fms_gateway, mediamtx, control_ui
└─ 호스트 ROS 10개 ─ ros2 node list 에서 이름 조각을 찾는다
                  rmf_schedule, gazebo, nav2:PK_01, nav2:PK_02,
                  omx:OMX_01, omx:OMX_02, control_tower, job_runner, executor
```

전부 `healthy` 일 때만 종료코드가 0 이다.

**이 검증에서 판정 근거로 쓰지 않는 이유가 둘이다.**

1. `REQUIRED_CHECKS` 에 `nav2:PK_02`·`omx:OMX_02` 가 하드코딩돼 **단일 로봇에서는
   구조적으로 통과할 수 없다.**
2. 호스트 ROS 판정을 `ros2 node list` 로 한다. 이 문서가 "부하에 멈추므로 쓰지 마라"고
   경고하는 바로 그 명령이다. 멈추면 doctor 는 빈 목록을 받고 **전부 `absent` 로
   보고한다** — 실제로는 다 떠 있는데도.

**그래서 참고로만 돌리고 출력을 기록한다.** 통과/실패는 5절의 개별 기준으로 정한다.

### 14.6 재고 부등호 `> 0` 은 맞다

`available_qty - reserved_qty > 0` 을 `>= 0` 으로 바꾸면 안 된다. 열의 뜻을 보면
분명하다.

| 열 | 스키마 주석 | 뜻 |
|---|---|---|
| `available_qty` | "Total physical quantity currently held" | **지금 물리적으로 갖고 있는 총량** |
| `reserved_qty` | "Quantity for reserved" | 그중 **이미 다른 job 에 약속된 양** |

가용 = 보유 − 약속. 이 값이 0 이면 **물건은 있지만 전부 다른 주문에 팔린 것**이다.
거기서 새 주문을 받으면 같은 물건을 두 번 파는 것이 된다. `> 0` 이 맞다.

수명주기는 이렇다.

```text
주문 수락   reserved_qty  +1          (available_qty 는 그대로)
적재 확인   available_qty -1, reserved_qty -1
취소        아무것도 안 한다          ← 여기가 결함이다 (11.1)
```

**부등호는 정상이고 결함은 취소 쪽에 있다.** 취소가 `reserved_qty` 를 안 줄이므로
그 lot 은 `available_qty = reserved_qty` 가 되어 재고가 있는데도 영영 주문 불가가
된다. 되찾는 유일한 경로가 G7 이다.

### 14.7 예약 할당은 있고 시간 스케줄링은 없다

**"작업이 예약 할당되는 것"까지는 돈다.**

```text
job_runner (매 주기)
  → assignment.py 가 로봇·팔·포장 Dock 을 고른다
  → reservations 에 exclusive_lock 으로 쓴다
  → active_resource_key UNIQUE 가 중복 점유를 막는다
```

**그러나 시간축이 통째로 비어 있다.** 스키마와 모듈은 있고 기록자가 없다.

| 있어야 할 것 | 스키마/모듈 | 기록자 |
|---|---|---|
| step 소요 예측 | `job_steps.predicted_duration_ms`, `prediction_source` | **없다** |
| 소요 baseline | `trihouse_fms.duration_baselines` | **없다** (테스트만) |
| 로봇 ETA | `trihouse_pinky_fleet/eta.py` 의 `EtaEstimator` | **없다** (테스트만) |
| Open-RMF 추정 | `rmf_adapter/energy_estimator.py` + `ros_energy_client.py` | **손으로 부르는 CLI 뿐** — `estimate_energy_cli.py`. dispatcher 가 부르지 않는다 |
| 시간대 예약 | `reservations.reservation_mode='time_slot'` | **있다.** [rmf_task_repository.py:302](../../control_tower/database/repositories/rmf_task_repository.py#L302) 가 **RMF 낙찰 뒤** 만든다 |

마지막 줄이 중요하다. `time_slot` 예약은 **사후 기록**이다 — RMF 가 이미 로봇을
정하고 나서 그 결과를 원장에 남긴다. 낙찰 전에 ETA 로 순서를 정하거나 대기 시간을
예측하는 경로는 **없다.**

**그래서 이 검증은 "예약 할당" 까지만 판정한다.** Open-RMF ETA 를 스케줄링에 쓰는
것은 새 기능이고, 붙일 자리(`RosEstimateService`)와 저장할 자리
(`predicted_duration_ms`)가 이미 있다는 것까지가 여기서 말할 수 있는 전부다.

### 14.8 Gateway 라우트 44개 중 이 검증이 쓰는 것

5절의 다섯 개는 **존재 확인용**이지 전부가 아니다. 실제로 쓰는 것과 없는 것을 갈라
둔다.

**쓴다 (12개)**

| 절 | 라우트 |
|---|---|
| L2 | `GET /ready`, `GET /openapi.json`, `GET /api/v1/jobs`, `GET /api/v1/inventory/lots`, `GET /api/v1/devices`, `GET /api/v1/operations/anomalies` |
| B절 | `POST /api/v1/orders`, `GET /api/v1/jobs/{id}`, `GET /api/v1/jobs/{id}/timeline`, `POST /api/v1/jobs/{id}/worker-completion` |
| 게이트 | `POST /internal/v1/jobs/{id}/cancel`, `POST /internal/v1/reservations/expire` |

**없어서 MySQL 로 직접 읽는 것 (3개)**

| 읽어야 하는 것 | 왜 API 가 없어도 되는가 |
|---|---|
| `reservations` 현재 상태 | 운영 UI 가 아직 안 쓴다. 수동 테스트는 `docker exec mysql` 로 충분하다 |
| `job_step_attempts.metrics` (duration 표본) | 같다. B14 판정은 SQL 로 한다 |
| `integration_messages` 상태·attempts | 같다. 14.3 의 두 원장 대조는 SQL 이 더 낫다 |

**정말 없는 것 — recovery 계열 전부.** episode 시작·step 추가·episode 종료 세 개가
있어야 `trihouse_recovery` 에 데이터가 쌓인다. 지금은 하나도 없다. 이것이
[recovery 적재 설계](2026-08-18-recovery-ingestion-design.md)가 만들 것이고, 이
검증에서는 **없다는 사실만 확인한다**(11.8).
