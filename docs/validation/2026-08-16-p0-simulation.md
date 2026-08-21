# Trihouse P0 시뮬레이션 검증 기록

- **작성일:** 2026-08-16
- **계획:** `docs/superpowers/plans/2026-08-15-control-tower-integration.md`
- **설계:** `docs/superpowers/specs/2026-08-15-control-system-trihouse-integration-design.md` (commit `8b2466b6`)
- **검증 대상 commit:** Task 10 커밋 직전 `6241755b` + 본 문서 커밋

## 1. 무엇을 실행했고 무엇을 아직 실행하지 못했는가

이 문서는 **실제로 돌린 것만** 기록한다. 아래 2절은 이 저장소에서 통과를
확인한 자동 검증이고, 3절은 실행 조건이 갖춰지지 않아 **미실행**으로 남은
항목이다. 미실행 항목을 통과로 적지 않는다.

이 워크스테이션에서 확인한 조건:

- MySQL 8.4 테스트 인스턴스가 `127.0.0.1:3307`에서 동작한다.
- ROS 2 Jazzy가 `/opt/ros/jazzy`에 설치되어 있다.
- Flutter/Dart 툴체인이 설치되어 있다.
- **Docker 데몬에 접근 권한이 없다** (`permission denied ... /var/run/docker.sock`).
  따라서 `./scripts/control_stack up` 으로 스택 전체를 기동하는 절차와
  Gazebo/Nav2/RMF 실제 모션 관측은 실행하지 못했다.

## 2. 실행하고 통과한 검증

### 2.1 실행 환경

```bash
source /opt/ros/jazzy/setup.bash
export PYTHONPATH="/tmp/trihouse-task6-venv/lib/python3.12/site-packages:$PYTHONPATH"
export FMS_DB_HOST=127.0.0.1 FMS_DB_PORT=3307
export FMS_DB_USER=fms_gateway FMS_DB_PASSWORD=test_gateway_password
export FMS_DB_DATABASE=trihouse_fms
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
```

### 2.2 명령과 결과

| 명령 | 결과 |
|---|---|
| `pytest -q db/tests control_tower/tests trihouse_rmf_bridge/test trihouse_omx_adapter/tests trihouse_pinky/test vision_edge/tests media tests --ignore=trihouse_rmf_bridge/test/test_office_service.py` | **576 passed**, 8 subtests passed |
| `cd fms_gateway && pytest -q tests` (실제 MySQL) | **271 passed**, 1 skipped |
| `cd control_ui/rmf_control_ui && flutter test` | **211 passed** |
| `cd control_ui/rmf_control_ui && flutter analyze` | **No issues found** |
| `./scripts/control_stack doctor --mode simulation` | 실행됨, 종료 코드 1 (아래 3절 참고) |

첫 명령에는 `tests/e2e` 24건이 포함되어 있다. 위 두 pytest 명령은 같은 테스트
MySQL 인스턴스를 초기화하므로 **동시에 돌리면 안 된다**. 병렬로 실행하면 한쪽이
상대의 스키마를 지워 `Unknown database 'trihouse_fms'`로 깨진다. 순차로 돌린
결과가 위 표다.

`trihouse_rmf_bridge/test/test_office_service.py`는 빌드된 ROS 워크스페이스에
서비스가 떠 있어야 하는 launch 통합 시험이라 이 실행에서 제외했다. 이는
P0 이전부터 있던 조건이며 본 계획으로 바뀌지 않았다.

### 2.3 신선 seed 여섯 주문 (A–F)

`tests/e2e/test_trihouse_test_01_orders.py`가 A–F 각각에 대해
`db/migrations/001_physical_v1_baseline.sql` + `db/seeds/seed_dev.sql`을 다시 만들고, UI가 쓰는 것과 같은
공개 `POST /api/v1/orders`로 제출한 결과다.

| 예시 | 요청 | HTTP | 구역 순서 | 요청/가능/미충족 |
|---|---|---|---|---|
| A | 전 구역 | 201 | ambient → chilled → frozen | 3 / 3 / 0 |
| B | 냉장·냉동 (상온 없음) | 201 | chilled → frozen | 2 / 2 / 0 |
| C | 전량 출고 + 재고 부족 | 409 `INSUFFICIENT_STOCK` | — | Job·Step·예약 **0건 생성** |
| D | critical | 201 | ambient → frozen | 2 / 2 / 0 |
| E | 부분 출고 허용 | 201 | chilled → frozen | 4 / 3 / **1** |
| F | 상온 2품목·Dock 1회 | 201 | ambient | 2 / 2 / 0 |

추가로 확인한 것:

- 한 구역은 선반 수와 무관하게 Pinky Dock 방문이 **한 번**이다.
- F 주문 한 건을 배정 → 품목별 적재 시도 → 작업자 완료 → 포장 Dock 해제 →
  고정 충전기 복귀까지 끝냈다. 모든 적재 시도가 `LOAD_CONFIRMED`로 남았고,
  `return_home` 단계가 정확히 하나 생성되며 배정된 충전기를 가리킨다.
- 같은 `Idempotency-Key`로 작업자 완료를 다시 부르면 첫 응답을 그대로
  돌려주고 재고를 두 번 확정하지 않는다.

### 2.4 두 Pinky 동시 운용

`tests/e2e/test_two_pinky_traffic.py` 결과:

- 동시 주문 두 건이 서로 다른 Pinky·OMX·포장 Dock으로 배정된다.
- `PK_01 → TRIHOUSE-TEST-01-CHG-01`, `PK_02 → TRIHOUSE-TEST-01-CHG-02` 고정이
  실제 MySQL 트랜잭션에서 유지된다.
- 이미 예약된 로봇을 두 번째 Job이 가져가면 `ResourceUnavailable`로 막힌다.
- 경로가 등록되기 전에는 어떤 로봇도 이동 승인을 받지 못한다.
- 마주 오는 두 itinerary는 나중 등록분이 보류되고, 앞 로봇이 경로를 반납한
  뒤에 승인된다.
- dispatch payload가 fleet과 robot을 모두 고정한다. RMF는 다른 Pinky로
  대체 배정할 수 없다.
- bottleneck은 먼저 도착한 로봇이 이기고 `critical`이 순서를 바꾸지 못한다.
  15초를 넘겨야 우회를 계산하고, 유효한 우회가 없으면 계속 기다린다.
- 구역 안에서 비상 정지하면 lease가 유지된다.
- 두 로봇이 동시에 stubborn override handle을 쥐지 못한다.

### 2.5 OMX 계약 시뮬레이션

`trihouse_omx_adapter/tests` 결과:

- `OMX_01`, `OMX_02` 두 인스턴스가 각자의 `omx_id` 명령만 실행한다.
- prepare 명령이 `PREPARING → PICKING → OMX_READY`를 낸다.
- `command_uuid` 재전송은 첫 이벤트 열을 그대로 돌려준다.
- 오래된 `assignment_revision`은 `STALE_ASSIGNMENT`로 거절된다.
- 필수 필드가 하나라도 없으면 상태가 전혀 바뀌지 않는다.
- 물리 OMX ROS endpoint를 발행하지 않는다.

### 2.6 ACT와 카메라

- `config/act.simulation.yaml`의 repo/revision/profile은 모두 `UNCONFIGURED`,
  mode는 `deterministic_fake`다. 로더가 `real_motion_enabled = False`를 낸다.
- fake episode가 `OBSERVE → POLICY → GRASP → VERIFY → HANDOVER`를 내고
  lineage를 `fake-act/p0-v1`로 기록한다.
- hardware mode는 세 값이 모두 실제 값일 때만 열린다.
- 카메라 여섯 대를 등록만 하고 연결하지 않는다. `map_pose`는 전부 `null`이며
  P1 캘리브레이션 전까지 좌표를 만들지 않는다.
- Pinky 영상은 OMX 적재 증거로 선택되지도, 허용되지도 않는다.
- 적재 결과는 `LOAD_CONFIRMED` / `DROP_DETECTED` / `LOAD_UNCERTAIN` /
  `GRASP_RETAINED` 네 가지뿐이다.

### 2.7 비상 fixture 두 건

`tests/e2e/test_emergency_fixtures.py` 결과:

| fixture | 여는 카메라 | 즉시 보류 |
|---|---|---|
| 1. 이동 중 Pinky 전도 (`PK_01`) | `CAM-PK-01` | 예 |
| 2. 창고 내 전도 (`WH-FRZ-01`) | `CAM-FIXED-02` | 예 |

- `비상경보 발령`은 사건을 확정하고 보류를 유지한다.
- `작업 계속 진행`은 작업자와 사유를 남기고 보류를 풀며, **같은 Job**의
  Nav2 경로를 다시 계산하고 RMF 일정을 다시 등록한다.
- 대화상자를 닫으면 상태도 감사 기록도 바뀌지 않는다.
- 재개가 실제로 이전 경로 해시를 반납하고 새 해시를 등록하는 것까지 확인했다.

### 2.8 UI 경계

- `flutter analyze` 무경고.
- 운영 화면이 Nav2 전역/지역 경로와 실제 이동 궤적을 1차로 그리고,
  내부 bootstrap graph 위젯은 존재하지 않는다.
- RMF 예정 궤적은 `RMF 진단` 토글을 켰을 때만 나타난다.
- 카메라 여섯 장이 등록 카드로만 있고, 사건이 연 카메라만 디코딩한다.
- 적재 성공은 자동으로 닫히고 드랍은 열린 채로 남는다.

## 3. 실제 기동 실측 (2026-08-16, 추가 세션)

앞 절들은 자동 검증 기록이다. 이 절은 **스택을 실제로 띄워 본 결과**다.
Docker 데몬 접근은 `sg docker` 로 새 그룹 셸을 열어 해결했다(`syw` 는 이미
`/etc/group` 의 docker 그룹에 있었고 로그인 세션만 낡아 있었다).

> `sg` 는 setgid 라 `LD_LIBRARY_PATH` 를 지운다. 그 안에서 `ros2` 를 부르면
> `librcl_action.so` 를 못 찾는다. Docker 와 ROS 를 함께 쓰는 명령(`doctor`)은
> `sg docker -c "LD_LIBRARY_PATH='$LD_LIBRARY_PATH' ..."` 로 다시 넣어야 한다.
> 재로그인하면 `sg` 자체가 필요 없다.

### 3.1 통과한 것

| 항목 | 실측 |
|---|---|
| Docker 층 6개 서비스 기동 | mysql·fms_gateway·mediamtx·rmf_api·rmf_dashboard·control_ui **모두 healthy** |
| Gateway 준비 | `GET /ready` → `{"status":"ready","database":"ok"}` |
| 관제 UI 와 same-origin 프록시 | `:3100/` → 200, `:3100/ready` → 200 |
| 지도 발행 | `trihouse_test_01` staged → validated(`valid: true`) → published |
| 발행 revision | `trihouse_test_01:730111d2…4b7ff` (draft_revision 2) |
| 주문 → DB 실시간 반영 | 주문 1건에 jobs 1→2, job_items 1→3, job_steps 1→8, operation_events 0→1 |
| 운영 WebSocket | `/api/v1/operations/ws` 접속 후 주문 시 `order.created` 수신 |
| ROS 워크스페이스 빌드 | 6개 패키지 성공 (`build/` 청소 후) |
| 호스트 ROS 층 기동 | 프로세스 사망 0건 |
| Gazebo 모델 | `ground_plane`, `pinky_01`, `pinky_02` |
| 두 Pinky 실제 주행 | `cmd_vel` 지령으로 odom 이동 확인 — `pinky_01` 직진 +0.257 m, `pinky_02` 선회 (+0.329, +0.179) |
| namespace 격리 | `/pinky_0{1,2}/{scan,odom,cmd_vel,map}` 분리, 프레임도 `pinky_01/odom` 등으로 분리 |
| OMX 두 대 | ROS 노드 `/omx_01`, `/omx_02` |
| **`doctor` 11개 항목** | **전부 `healthy`, 종료 코드 0** |

`doctor` 실측 출력:

```json
{
  "checks": {
    "control_tower": "healthy", "control_ui": "healthy",
    "fms_gateway": "healthy", "gazebo": "healthy",
    "mediamtx": "healthy", "mysql": "healthy",
    "nav2:PK_01": "healthy", "nav2:PK_02": "healthy",
    "omx:OMX_01": "healthy", "omx:OMX_02": "healthy",
    "rmf_schedule": "healthy"
  },
  "healthy": true
}
```

### 3.2 이번에 고친 결함

기동을 가로막던 것들이다. 하나도 문서 오탈자가 아니었다.

| 곳 | 결함 |
|---|---|
| `.env` / `compose.db.yaml` | P0 가 쓰려는 `FMS_DB_PORT` 를 개발용 MySQL 도 본다. 런북대로 `.env` 를 3308 로 고치면 개발 DB 가 다음 기동에서 충돌한다 → P0 전용 `.env.p0` + `--env-file` |
| `control_ui/.../Dockerfile` | `ghcr.io/cirruslabs/flutter:3.44.9` 는 존재하지 않는다(그 미러는 3.44.0 까지, 그 Dart 는 3.12.0 이라 `sdk: ^3.12.2` 불만족) → Google 아카이브에서 체크섬 고정 설치 |
| `.dockerignore` | `control_ui/` 전체가 빌드 문맥에서 빠져 있었다 |
| `fms_gateway/Dockerfile` | 런타임 프로파일이 해시하는 `pinky_pro` YAML 2개가 이미지에 없어 `/runtime-profiles/...` 가 500 → **지도 발행 전체가 막힘** |
| `compose.control.yaml` | Gateway 가 `read_only` 인데 지도 staging 이 `/app/runtime` 에 쓴다 → named volume |
| `scripts/control_stack` | `up` 이 `--build` 를 안 넘겨 소스 수정이 컨테이너에 반영되지 않는다 |
| `build/` (colcon) | 삭제된 launch 파일을 가리키는 symlink 가 남아 `trihouse_pinky_bringup` 빌드 실패 |
| `p0_simulation_bringup.sh` | `set -u` 상태로 ROS setup 을 source 해 `AMENT_TRACE_SETUP_FILES` 에서 즉사 |
| `p0_simulation_bringup.sh` | 좌표 원본 기본값이 gitignore 대상 경로였다 → git 에 있는 `control_ui/` 정본으로 |
| `p0_simulation_bringup.sh` | `two_pinky_order_demo.launch.py` 의 필수 인자 4개(`nav_graph`·`world`·`nav2_params_file`·`fleet_config`)를 안 넘겨 **Gazebo 층 전체가 안 뜸** |
| `p0_simulation_bringup.sh` | fleet 이름이 `trihouse_pinky` 인데 fleet config 는 `project1_pinky` — dispatch 가 어떤 adapter 에도 닿지 않는다 |
| `two_pinky_order_demo.launch.py` | `robot_description` 을 아무도 발행하지 않아 spawn 불가 (robot_state_publisher 없음) |
| `two_pinky_order_demo.launch.py` | `ros_gz_bridge` 가 없어 `cmd_vel`/`scan`/`odom`/`clock` 이 ROS 로 오지 않음 |
| `two_pinky_order_demo.launch.py` | `GZ_SIM_RESOURCE_PATH`/`GZ_SIM_SYSTEM_PLUGIN_PATH` 미설정 |
| `two_pinky_order_demo.launch.py` | Nav2 를 `Node(executable="bringup_launch.py")` 로 띄우려 함 — launch 파일은 실행 파일이 아니다 |
| `two_pinky_order_demo.launch.py` | nav2 의 `slam` 인자는 `PythonExpression` 에 들어가므로 `true` 가 아니라 `True` 여야 한다 (아니면 launch 전체가 `NameError`) |
| `two_pinky_order_demo.launch.py` | spawn 지연 5초는 Gazebo 로딩보다 짧아 `create` 가 timeout |
| `p0_simulation_bringup.sh` | OMX 를 `simulator_node` 로 띄웠다. 그건 ROS 노드가 아니라 stdin/stdout NDJSON 필터라서 배경 실행 시 EOF 로 즉시 종료된다 → rclpy 노드인 `gazebo_omx_adapter` 를 이름 갈라서 2개 |
| `scripts/control_stack` | `doctor` 의 `gazebo` 점검이 존재하지 않는 `ros_gz` 노드를 찾고 있었다 |

### 3.3 새로 만든 것

- `control_tower/bringup/p0_runtime_assets.py` — 발행된 지도 revision 을
  launch 가 받을 수 있는 파일로 펼친다. Gateway 는 지도를 **내용**으로만 주고
  launch 는 **경로**를 받으므로 그 사이가 비어 있었다. 아티팩트 sha256 을
  검증하고 발행본을 그대로 보존한다.
- 같은 스크립트가 **RMF nav graph 를 생성한다.** 발행본은
  `lanes: []` 라 RMF 가 경로를 못 만든다. 승인된 JSONL 의 병목 2곳을 정점으로
  넣고 실측 배치가 말하는 통로대로 lane 을 잇는다 (정점 10, lane 18).
- 같은 스크립트가 **로봇별 Nav2 파라미터를 파생한다.** `pinky_pro` 원본은
  프레임이 `base_footprint`/`odom` 이고 costmap 이 `/scan` 을 절대 경로로 봐서
  두 대를 한 Gazebo 에 띄우면 서로를 덮어쓴다. `pinky_pro` 아래 파일은 읽기만
  한다.

### 3.4 주문이 로봇을 움직이지 못한다 (2026-08-17 일부 해소)

**두 Pinky 는 Gazebo 에서 실제로 달리지만, 그것은 `cmd_vel` 을 직접 준
결과다.** 주문을 넣어도 로봇은 움직이지 않았다. 확인한 사슬은 이렇다.

1. `POST /api/v1/orders` → Job 이 `queued` 로 생기고 7단계 계획이 만들어진다. **동작**
2. 누군가 Job 에 자원을 배정하고 (`POST /internal/v1/jobs/{id}/assignment`)
   현재 Step 을 내보내야 한다 (`POST /internal/v1/job-steps/{id}/dispatch`).
   → **2026-08-17 해소.** 3.4.1 참고.
3. `rmf_gateway_worker_node` 가 그 행을 claim 해 RMF 로 넘긴다. **동작하지만
   `channel='rmf'` 행만 claim 한다.** → 3.4.2 참고.

2번을 할 것으로 기대했던 `control_tower/task_manager/sequence_orchestrator.py`
의 `SequenceOrchestrator` 는 **자기 모듈과 테스트 밖에서 한 번도 생성되지
않았다.** 게다가 이 클래스는 `create_outbound` 로 **자기 Job 을 새로 만드는**
경로여서, 주문이 이미 만들어 놓은 Job 을 전진시키는 데는 쓸 수 없다.

실측(2026-08-16): 주문 4건을 넣은 뒤 `integration_messages` 는 0행, 모든
`job_steps` 는 `pending`, `jobs.assigned_mobile_id` 는 전부 `NULL` 이었다.

#### 3.4.1 Job 러너 — 2026-08-17 추가, 실기동 확인

`control_tower/task_manager/job_runner.py` (순수 로직) 와
`job_runner_node.py` (실행 프로세스) 를 만들었다. 한 주기에 이것을 한다.

1. `GET /api/v1/jobs` 로 아직 살아 있는 Job 을 읽는다.
2. `source == public_product_order` 인데 배정이 없으면 로봇·OMX·포장 Dock·
   충전기를 골라 `POST /internal/v1/jobs/{id}/assignment` 로 넘긴다.
3. 아직 성공하지 않은 첫 Step 이 `pending` 이면 dispatch 한다.

설계에서 의도한 세 가지:

- **주기 간 무상태.** 어떤 로봇·OMX·Dock 이 쓰이고 있는지를 프로세스 기억이
  아니라 Gateway 가 보여 주는 활성 Job 에서 매 주기 다시 계산한다. 따라서
  재시작해도 이어지고, DB 와 예약이 어긋날 수 없다. 최종 판정은 Gateway 가
  행 잠금 아래에서 한다.
- **고정 멱등 키.** dispatch 된 Step 은 실행자가 잡을 때까지 `pending` 이라
  다음 주기에 반드시 다시 보인다. 키를 Step 신원에서만 만들어, 재조회가
  409 나 중복 outbox 행이 아니라 원래 행을 그대로 돌려받게 했다.
- **자동 재시도 없음.** `failed`/`cancelled` Step 은 보고만 하고 두었다.
  창고 한복판의 실물 로봇에게 무엇을 되풀이해도 안전한지는 별도 정책이며,
  여기서 지어내면 P0 기동 중 결함을 덮는다.

**실기동 확인 (2026-08-17, 어제 띄운 Docker 층이 그대로 살아 있는 상태).**
어제 남아 있던 `queued` 주문 4건에 대해 `--once` 로 한 주기를 돌렸다.

```
[INFO] job runner cycle: assigned=[2, 3] dispatched=[2, 3]
[WARN] job runner blocked: job 4: no free robot, arm, or dock
[WARN] job runner blocked: job 5: no free robot, arm, or dock
[WARN] job runner blocked: job 1: no assignment and not an order
```

DB 실측 결과:

| 항목 | 이전 | 이후 |
|---|---|---|
| `integration_messages` | **0행** | **2행** (`outbound`/`omx`/`pending`) |
| Job 2 state | `queued` | `assigned` |
| Job 2 배정 | 없음 | `PK_01` / `OMX_01` / `PACKING-01-DOCK-01` / `CHG-01` |
| Job 3 배정 | 없음 | `PK_02` / `OMX_02` / `PACKING-01-DOCK-02` / `CHG-02` |
| Step 10·20 `assigned_device_id` | `NULL` | `OMX_01` / `PK_01` |

두 Pinky 분리, OMX 분리, Dock 분리, 로봇별 고정 충전기가 **실제 MySQL 에서**
지켜졌다. 로봇이 2대뿐이므로 Job 4·5 는 기다리고, `dev_seed` Job 1 은 주문이
아니므로 건드리지 않는다 — 둘 다 의도한 동작이다.

자동 검증은 `control_tower/tests/test_job_runner.py` 19건,
`test_job_runner_node.py` 4건이다. `doctor` 에 `job_runner` 점검이 추가되어
필수 항목은 11개에서 **12개**가 되었다.

#### 3.4.2 남은 결함 — `omx`/`pinky` 채널에 소비자가 없다

러너가 outbox 를 채우게 되었지만 **주문은 여전히 로봇을 움직이지 못한다.**
막히는 곳이 바뀌었다.

`dispatch_step` 은 Step 의 `executor_type` 으로 채널을 정한다
(`repositories.py` 의 `_dispatch_kind`).

| `executor_type` | 채널 | 소비자 |
|---|---|---|
| `mobile` | `rmf` | `rmf_gateway_worker_node` **있음** |
| `arm` | `omx` | **없음** |
| `fms` | `pinky` | **없음** |

`integration_messages` 를 읽는 모든 경로가 `channel = 'rmf'` 로 걸러진다
(`repositories.py:4677`, `:4732`). 즉 `omx`·`pinky` 행을 claim 할 수 있는
HTTP 경로 자체가 존재하지 않는다.

공개 주문의 7단계는 `pick(arm) → navigate(mobile) → load(fms) →
navigate(mobile) → handover(fms) → wait(fms) → return_home(mobile)` 이고,
Step 은 순서대로만 열린다. **첫 단계가 `arm` 이라 여기서 멈춘다.** 그래서
`navigate` 가 RMF 로 나가지 못하고 로봇은 출발하지 않는다.

OMX 시뮬레이터(`simulator_node.py`)는 Gateway 명령을 **stdin NDJSON** 으로
읽게 되어 있는데, Gateway 의 `omx` outbox 를 그 stdin 으로 넣어 주는 전송이
없다. `gazebo_adapter_node.py` 도 Gateway 에 접속하지 않는다.

Step 을 `succeeded` 로 만드는 경로는 TCP 수집 서버(`:8788`)의 `task_event`
이며(`ingest_task_event`), 이것도 위 소비자들이 있어야 흐른다.

따라서 아래는 **여전히 미실행**이다.

- 런북 8.1 (동시 주문 두 건이 서로 다른 로봇·OMX·Dock 으로 배정)
- 런북 8.2 (Nav2 경로와 실제 이동 궤적이 관제 UI 에 그려짐)
- 런북 8.3 (병목 통과 순서)
- 런북 8.4 (OMX 적재와 작업자 완료의 실기동 확인)
- 런북 8.5 (비상 fixture 실화면)

이 항목들의 **로직**은 2.4·2.5·2.7 절대로 자동 테스트에서 결정적으로
검증되어 있다. 빠진 것은 그 로직을 실행하는 프로세스였고, 그중 배정과
dispatch 는 3.4.1 로 채워졌다. 남은 것은 3.4.2 의 채널 소비자다.

### 3.5 그 밖에 남은 것

- OMX NDJSON 프로토콜 시뮬레이터(`simulator_node`)는 Gateway 와 아직
  연결되지 않는다. 이제 `integration_messages` 에 `omx` 행이 쌓이지만 그것을
  시뮬레이터 stdin 으로 옮기는 전송이 없다 (3.4.2). ROS 층에는
  `gazebo_omx_adapter` 만 떠 있다.
- Nav2 는 `slam_toolbox` 로 돈다. 승인된 SLAM 지도(`control_system_test/`,
  gitignore 대상)를 쓰려면 `TRIHOUSE_NAV2_SLAM=false` 와 `nav2_map:=` 이
  필요하고, 두 로봇의 초기 pose 정합이 별도로 필요하다.
- Gazebo world 는 `pinky_gz_sim` 의 `empty.world`(바닥면만)를 쓴다. 발행된
  world 아티팩트는 `<world name="..."/>` 뿐이라 쓸 수 없다
  (`fms_gateway/app/map_deployment.py` 의 `_runtime_artifacts` 가 그렇게
  생성한다). SLAM 지도에서 실제 벽을 만드는 것은 미구현이다.
- 이 호스트의 real-time factor 는 0.17 이었다 (SLAM 2개 + Nav2 2개 동시).

## 3.6 미실행으로 남은 항목 (기존 기록)

아래는 **통과하지 않았다**. 조건이 갖춰지면 그때 실행하고 이 문서를 갱신해야
한다.

0. **스택이 두 층으로 나뉜다.** `up` 은 Docker 층(MySQL, Gateway, MediaMTX,
   RMF API/Dashboard, control_ui)만 올린다. RMF core, Gazebo, Nav2, fleet
   adapter, OMX 시뮬레이터, RMF dispatch worker 는 rclpy 와 DDS 가 필요해
   호스트에서 돈다. `control_stack ros` 또는
   `control_tower/bringup/p0_simulation_bringup.sh` 가 그 층을 한 번에 띄운다.
   수동 절차는 `docs/runbooks/2026-08-16-p0-manual-test.md` 에 있다.
1. **`./scripts/control_stack up --mode simulation --project trihouse_test_01`
   전체 기동과 `doctor` 실측.** 이 호스트에 Docker 데몬 접근 권한이 없다.
   `doctor`를 실행한 실제 출력은 다음과 같다. 열한 개 필수 항목을 모두
   보고하지만 스택이 떠 있지 않으므로 전부 `absent`이고 종료 코드는 1이다.

   ```json
   {
     "act_contract": "deterministic_fake",
     "ai_5080_started": false,
     "checks": {
       "control_tower": "absent", "control_ui": "absent",
       "fms_gateway": "absent", "gazebo": "absent",
       "mediamtx": "absent", "mysql": "absent",
       "nav2:PK_01": "absent", "nav2:PK_02": "absent",
       "omx:OMX_01": "absent", "omx:OMX_02": "absent",
       "rmf_schedule": "absent"
     },
     "healthy": false,
     "mode": "simulation",
     "project": "trihouse_p0"
   }
   ```

   CLI
   계약(서브커맨드, 단일 Compose project, 기동 순서, 필수 점검 항목,
   `compose.ai_5080.yaml` 제외, headless 기본값, `STARTUP_ORDER`의 모든
   서비스가 compose에 정의되어 있음)은 `tests/test_control_stack_cli.py`
   13개로 검증했지만, 실제 컨테이너 기동은 미실행이다.
2. **Gazebo/Nav2/Open-RMF 실제 모션 관측.** 두 Pinky가 실제로 경로를 따라
   움직이는 장면, 실제 costmap, 실제 RMF 충돌 해소는 스택 기동이 필요하다.
   Task 7이 만든 계약(경로 계산 후 등록, 승인 전 무이동, 재계획 시 보류와
   override 반납)은 단위 수준에서 결정적으로 검증했다.
3. **비상 화면 스크린샷.** UI 위젯 동작은 `flutter test`로 검증했으나 실제
   브라우저 화면 캡처는 스택 기동이 필요하다.
4. **artifact/log URI.** P0는 fixture 이벤트 클립만 등록하며, 실제 클립이
   생성되려면 MediaMTX가 떠 있어야 한다. 카탈로그 로직
   (`media/event_catalog/catalog.py`)은 9개 테스트로 검증했다.

## 4. 계측 상태: `UNMEASURED`

`scripts/measurement_gate.py`의 판정은 현재 `UNMEASURED`다. 4060/5080 동시성,
저장 모드, 보존 기간은 아래가 **모두** 실제 호스트에서 나오기 전까지 바뀌지
않는다.

| 필요한 산출물 | 생성 방법 | 현재 |
|---|---|---|
| `nvidia_smi.txt` | `scripts/measure_control_hosts.sh <dir>` | 없음 |
| `free.txt` | 같음 | 없음 |
| `lsblk.txt` | 같음 | 없음 |
| `df.txt` | 같음 | 없음 |
| `camera_soak.json` | `scripts/camera_soak_test.py`, 6스트림 ≥1800초 | 없음 |

게이트는 다음도 함께 요구한다. 짧은 fixture 실행이 상태를 바꾸지 못하도록
한 장치다.

- soak 길이 1800초 이상, 스트림 정확히 6개.
- 스트림마다 코덱·해상도·소스 FPS·디코딩 FPS·비트레이트·드롭·QR/ArUco
  지연·CPU·GPU·RAM·기록 바이트가 모두 기록되어야 한다.
- 산출물이 실제 호스트 이름을 담아야 한다 (`fixture` 라벨은 거절).

`scripts/camera_soak_test.py`는 실제 계측기가 주입되지 않으면
`RuntimeError`를 내고 숫자를 만들어 내지 않는다.

### 4.1 계획과 달라진 파일 위치

계획은 게이트를 `tools/measurement_gate.py`에 두라고 했지만, 이 저장소의
`.gitignore`는 `tools/` 전체를 무시한다(예외는 `db/tools/`). 그 경로에 두면
파일이 버전 관리되지 않으므로 `scripts/measurement_gate.py`로 옮겼다.
`tests/test_measurement_gate.py`가 그 경로에서 `evaluate_measurements`를
불러온다.

## 5. 승인된 좌표 출처에 대한 기록

P0의 유일한 pose 출처는
`control_system_test/rmf_control_ui/data/import/trihouse_test_01_physical_features.jsonl`
(13줄: waypoint 8, bottleneck 2, fiducial 3) 이다.

이번 작업에서 이 파일의 **병목 기록 2건(9·10번 줄)의 출처 표기**를 계획
Task 3 Step 4대로 수정했다. `source_radius_m: 0.2` → `source_diameter_m: 0.2`,
측정 주석의 "반경 20cm" → "지름 20cm, 반지름 10cm". 실행 반경
`radius_m: 0.1`과 모든 좌표는 손대지 않았다.

**정정 (2026-08-16 실기동 세션):** 위 경로만 있다고 적었던 것은 사실과 다르다.
같은 파일의 **git 에 들어 있는 정본**이

```
control_ui/rmf_control_ui/data/import/trihouse_test_01_physical_features.jsonl
```

에 있다. 자동 테스트(`fms_gateway/tests/unit/test_map_project_api.py`)와 이번
지도 발행이 모두 이 파일을 썼고, 두 사본은 좌표가 완전히 같다(주석 문구 한 곳만
다르다). 두 파일 모두 이미 `source_diameter_m` 표기를 갖고 있어 런북의 보정
스크립트는 실행할 필요가 없었다.

따라서 기동 스크립트의 기본 경로도 `control_ui/` 쪽으로 바꿨다.
`control_system_test/` 사본은 없을 수 있으므로 되돌아갈 자리로만 남긴다.

한편 **SLAM 지도(`*_slam.yaml` / `*_slam.pgm`)는 아직 git 에 없다.**
`control_system_test/rmf_maps/trihouse_test_01/nav2_map/` 아래에만 있어서, 새
클론에서는 지도 발행의 `slam_yaml`/`slam_image` 소스를 채울 수 없다. 발행은
이 두 소스가 없으면 `SOURCE_SLAM_IMAGE_MISSING` / `SOURCE_SLAM_YAML_MISSING`
으로 거절된다.

## 6. P1 진입 게이트 재확인

계획 마지막 절의 여섯 입력 중 이 저장소에서 준비된 것은 6번(P0 회귀 증거,
이 문서)뿐이다. 1~5번은 실제 장비에서만 얻을 수 있으며, 그때까지 물리
프로파일은 막혀 있고 처리량·보존 기간은 `UNMEASURED`로 남는다.
