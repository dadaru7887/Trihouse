# P0 수동 테스트 절차 (2026-08-18)

## 무엇이 확인되고 무엇이 확인되지 않는가

이 문서는 두 층을 나눠 다룬다. 섞으면 어느 층의 문제인지 말할 수 없게 된다.

| 층 | 상태 | 이 문서에서 |
|---|---|---|
| Docker (UI, RMF dashboard, FMS Gateway, MySQL) | **안정적으로 재현된다** | 1~3절 |
| 호스트 ROS 2 (Gazebo, Nav2, Open-RMF, 온보드 노드) | **이 PC 의 용량을 넘는다.** 간헐 실패 | 4절 |

4절이 간헐적인 이유는 설정 결함이 아니라 부하다. 로봇 두 대의 Nav2 스택과 Gazebo
와 Open-RMF 와 로봇당 온보드 노드 6개가 12코어 개발 PC 하나에 올라간다. 실측으로
load average 가 60~90 이었고, 그 상태에서는 Nav2 의 lifecycle manager 가
`map_server/get_state` 를 기다리다 포기하며(`Failed to bring up all requested
nodes`), 새로 붙는 ROS CLI 노드도 토픽을 발견하지 못한다. 같은 명령이 어떤 때는
통하고 어떤 때는 통하지 않는다. 4060/5080 서버로 옮기면 사라질 종류의 문제다.

## 0. 전제

```bash
cd /home/syw/Trihouse
```

ROS 명령은 반드시 3단으로 source 한다. 하나라도 빠지면 메시지 타입이나 패키지를
찾지 못한다.

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
```

도메인은 **0** 이다. Docker 층이 `ROS_DOMAIN_ID=0` 으로 떠 있기 때문이다. 실기는
52 이며 절대 섞지 않는다. 도메인이 다르면 시뮬 `pinky_01` 과 실기 `pinky_01` 은
서로를 보지 못한다.

```bash
export ROS_DOMAIN_ID=0
```

## 1. Docker 층 확인

```bash
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'
```

여덟 개가 `Up` 이어야 한다. 없으면 먼저 띄운다.

```bash
scripts/control_stack up
```

각 경계를 직접 두드린다.

```bash
# 관제 UI
curl -s -o /dev/null -w 'control_ui %{http_code}\n' http://127.0.0.1:3100/

# Open-RMF dashboard
curl -s -o /dev/null -w 'rmf_dashboard %{http_code}\n' http://127.0.0.1:3000/

# FMS Gateway — DB 연결까지 확인한다
curl -s http://127.0.0.1:8080/ready
```

기대값은 `200`, `200`, `{"status":"ready","database":"ok"}` 다.

두 층을 한 번에 보려면 `doctor` 를 쓴다.

```bash
scripts/control_stack doctor --mode simulation
```

Docker 네 개(`mysql`, `fms_gateway`, `mediamtx`, `control_ui`)가 `healthy` 여야
한다. 호스트 ROS 항목은 4절을 하지 않았다면 `absent` 가 맞다.

> `doctor` 는 2026-08-18 까지 **여덟 개가 정상 실행 중인데도 전부 `absent`** 라고
> 보고했다. CLI 가 `.env.p0` 를 읽는데 MediaMTX 인가 변수 4개는 `.env` 에만
> 있어서 `docker compose` 가 설정 단계에서 실패했고, `doctor` 가 그 실패를
> "서비스 없음" 으로 바꿔 읽었기 때문이다. `up`·`status`·`logs`·`down` 도 함께 못
> 쓰는 상태였다. 지금은 `.env` 하나만 읽는다.

브라우저로는 **http://127.0.0.1:3100** (관제 UI) 과
**http://127.0.0.1:3000** (RMF dashboard) 을 연다.

## 2. DB 와 Job 상태 읽기

MySQL 이 세 개 있다. 헷갈리면 엉뚱한 DB 를 고치게 된다.

| 컨테이너 | 포트 | 용도 |
|---|---|---|
| `trihouse-mysql` | 3308 | **실기동/개발 DB** (`trihouse_fms`). Gateway 가 쓴다 |
| `trihouse_db-mysql-1` | 3306 | 보존되는 개발 DB |
| `trihouse_db_test-mysql_test-1` | 3307 | tmpfs 테스트 DB. 재시작하면 사라진다 |

API 로 읽는 것이 가장 안전하다. 쓰기 권한이 필요 없다.

```bash
curl -s http://127.0.0.1:8080/api/v1/jobs | python3 -m json.tool | head -40

# 하나를 자세히
curl -s http://127.0.0.1:8080/api/v1/jobs/2 | python3 -m json.tool | head -40

# 그 Job 이 지나온 자리
curl -s http://127.0.0.1:8080/api/v1/jobs/2/timeline | python3 -m json.tool | head -30
```

DB 를 직접 볼 때는 읽기만 한다.

```bash
PW=$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)
docker exec trihouse-mysql mysql -uroot -p"$PW" -e "
  SELECT job_id, job_code, state, IFNULL(assigned_mobile_id,'-') AS robot
    FROM trihouse_fms.jobs ORDER BY job_id;
  SELECT job_id, COUNT(*) AS steps, GROUP_CONCAT(DISTINCT state) AS step_states
    FROM trihouse_fms.job_steps GROUP BY job_id ORDER BY job_id;
  SELECT job_id, COUNT(*) AS reservations
    FROM trihouse_fms.reservations GROUP BY job_id;
"
```

**2026-08-18 기준으로 job 2 와 3 이 `assigned` 상태로 PK_01·PK_02 를 붙잡고
있고 예약도 각각 3건 쥐고 있다.** 그래서 job 4·5 는 `no free robot` 으로 대기한다.
새 주문을 넣어도 그 뒤에 줄을 선다. 이 정리는 아직 하지 않았다 — 되돌릴 수 없는
운영 DB 쓰기이고 Gateway 에 취소 엔드포인트가 없다.

## 3. 주문 1건 넣기

주문은 상품과 수량만 준다. 경로·로봇·창고 위치를 주문자가 고르지 않는다.

주문 가능한 상품 코드를 먼저 확인한다.

```bash
docker exec trihouse-mysql mysql -uroot -p"$PW" -e "
  SELECT product_code, state, COUNT(*) AS lots
    FROM trihouse_fms.inventory_lots
   GROUP BY product_code, state ORDER BY product_code;
"
```

`state='stored'` 인 것만 주문할 수 있다. **재고는 유한하다** — 2026-08-18 기준
SKU 마다 stored lot 이 하나씩이고, 주문을 넣으면 실제로 소진된다.

```bash
curl -s -X POST http://127.0.0.1:8080/api/v1/orders \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: manual-test-$(date +%s)" \
  -d '{
        "requested_by": "manual-test",
        "priority": "normal",
        "items": [{"product_code": "SKU-COFFEE", "quantity": 1}]
      }' | python3 -m json.tool
```

`201` 과 함께 Job 하나와 7단계 계획이 생긴다. 재고가 모자라면 `409`
(`INSUFFICIENT_STOCK`), 없는 상품이면 `422` 다. `Idempotency-Key` 는 필수이며
같은 키로 다시 부르면 새 Job 이 아니라 원래 Job 이 돌아온다.

UI 에서도 같은 것을 확인한다 — http://127.0.0.1:3100 의 운영 화면에 새 Job 이
`queued` 로 보여야 한다.

여기까지가 **ROS 없이** 확인할 수 있는 범위다. Job 이 `queued` 로 생기고 계획이
만들어지는 것까지는 Docker 층만으로 재현된다. 로봇을 실제로 움직이는 것은 4절이다.

## 4. 호스트 ROS 2 층 (용량 제약)

### 4.1 기동

항상 깨끗한 상태에서 시작한다. 이전 세대가 남아 있으면 같은 토픽에 여러 세대가
발행해서 측정값이 오염된다.

```bash
scripts/sim_teardown.sh
```

`killed=<n> leftover=0`, `fastrtps_shm_left=0`, `docker_containers=8` 이어야 한다.
`leftover` 가 0 이 아니면 그 프로세스를 먼저 처리한다.

```bash
TRIHOUSE_MAP_REVISION="trihouse_test_01:730111d2e446f5141c5ef069e5f2c1c8c5383aea79bdeffd05d3d34f2094b7ff" \
ROS_DOMAIN_ID=0 \
control_tower/bringup/p0_simulation_bringup.sh 2>&1 | tee /tmp/sim.log
```

`ROS_DOMAIN_ID` 만 넘긴다. DDS transport 는 스크립트가 Docker 층과 같은 값으로
못박아 두었으므로 따로 줄 필요가 없다.

기동에 1~2분 걸린다. 파이프를 쓰면 종료코드가 가려지므로 상태는 아래 확인으로 본다.

### 4.2 위에서부터 확인

```bash
# ① localization lifecycle 이 활성까지 갔는가 (로봇 두 대이므로 2가 나와야 한다)
grep -c 'Managed nodes are active' /tmp/sim.log

# ② 실패가 있으면 무엇이 실패했는가
grep -E 'Failed to bring up all requested|Failed to change state' /tmp/sim.log
```

①이 2 가 아니면 **부하 문제일 가능성이 높다.** `uptime` 으로 load average 를 보고,
60 을 넘으면 다른 작업을 멈춘 뒤 4.1 부터 다시 한다.

로봇 상태는 전용 스크립트로 읽는다. `ros2 topic echo` 는 쓰지 않는다 — 그 명령은
메시지 타입을 그래프에서 찾는데, 참가자가 많아지면 `ros2 topic list` 자체가 멈춘다.

```bash
python3 scripts/verify_robot_status.py pinky_01 20
python3 scripts/verify_robot_status.py pinky_02 20
```

읽는 곳은 세 줄이다.

- `publishers` — 모두 1 이어야 한다. 2 이상이면 이전 세대가 남아 있다는 뜻이고
  나머지 값은 믿을 수 없다. 4.1 로 돌아간다.
- `frame_id` — **`map` 이어야 한다.** `pinky_0N/odom` 이면 AMCL 이 위치추정을
  하지 못하고 있다는 뜻이고, RMF adapter 는 그 로봇을 거절한다.
- `dispatchable` — `true` 여야 RMF 가 그 로봇에 작업을 준다. `errors` 가 무엇이
  막고 있는지 알려 준다.

`errors` 를 읽는 법.

| 오류 | 뜻 | 볼 곳 |
|---|---|---|
| `map_pose_stale` | `map -> base` 변환이 없거나 낡음 = AMCL 미동작 | `grep 'pinky_0N.amcl' /tmp/sim.log` |
| `nav_unavailable` | `navigate_to_pose` 액션 서버가 없음 = navigation lifecycle 미활성 | ② 의 실패 줄 |
| `battery_stale` | `trihouse/battery` 가 안 옴 = `sim_hardware` 미동작 | 프로세스 존재 확인 |
| `control_link_offline` | Gateway TCP 8788 미연결 | `ss -tnp \| grep 8788` |
| `scan_stale` / `odom_stale` | Gazebo bridge 가 안 넘김 | `parameter_bridge` 프로세스 |

### 4.3 주문이 로봇까지 가는가

```bash
grep -E 'job runner cycle|job runner blocked' /tmp/sim.log | tail -5
grep -E 'RMF dispatch cycle' /tmp/sim.log | tail -3
```

`claimed=` 가 1 이상이면 dispatch 가 RMF 로 넘어간 것이다. `no free robot` 이
보이면 2절의 job 2·3 이 로봇을 붙잡고 있는 상태다.

## 5. 정리

```bash
scripts/sim_teardown.sh
```

Docker 층은 그대로 둔다. 이 스크립트는 컨테이너를 건드리지 않으며, 마지막 줄의
`docker_containers=8` 로 그것을 확인해 준다.

## 6. 테스트 스위트 돌리기

두 묶음으로 나눠 돌린다. e2e 는 **스키마를 초기화하므로 테스트 DB(3307)에서만**
돌아간다. 개발 DB 를 가리키면 fixture 가 거절한다 — 그 거절은 안전장치이며 실패가
아니다.

```bash
source /opt/ros/jazzy/setup.bash && source install/setup.bash

# ① e2e 를 뺀 나머지 (약 10분)
PYTHONPATH="trihouse_pinky/trihouse_pinky_vision:$PYTHONPATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  db/tests control_tower/tests trihouse_rmf_bridge/test trihouse_omx_adapter/tests \
  trihouse_pinky/test vision_edge/tests media tests \
  --ignore=trihouse_rmf_bridge/test/test_office_service.py --ignore=tests/e2e

# ② e2e — 반드시 3307 테스트 DB 로
FMS_DB_HOST=127.0.0.1 FMS_DB_PORT=3307 \
MYSQL_ROOT_PASSWORD=test_root_password \
FMS_DB_DATABASE=trihouse_fms FMS_DB_USER=fms_gateway FMS_DB_PASSWORD=test_gateway_password \
PYTHONPATH="trihouse_pinky/trihouse_pinky_vision:$PYTHONPATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/e2e
```

2026-08-18 기준 ①은 **669 passed / 14 subtests**, ②는 **25 passed** 다.

## 7. 함정

- **`PYTHONPATH` 는 덮어쓰지 말고 더한다.** `PYTHONPATH=trihouse_pinky/trihouse_pinky_vision`
  라고 쓰면 ROS 경로가 사라져 `ModuleNotFoundError: rclpy` 가 난다. 반드시
  `PYTHONPATH="trihouse_pinky/trihouse_pinky_vision:$PYTHONPATH"` 로 쓴다.
- **`pytest` 는 플러그인 자동적재를 끈다.** ROS 를 source 한 셸에서 `.venv/bin/pytest`
  를 그냥 돌리면 `launch_testing` 플러그인이 venv 의 pytest 와 충돌해
  `PluginValidationError` 가 난다.
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest ...` 로 돌린다.
- **`status_node` 를 고치면 재빌드해야 한다.** install 이 복사본이다.
  `colcon build --packages-select trihouse_pinky_fleet --symlink-install` 를 돌린다.
  launch 파일은 symlink 이므로 재빌드가 필요 없다.
- **`pkill -f <패턴>` 을 직접 쓰지 않는다.** 명령줄에 패턴이 들어가서 자기 자신을
  죽인다. 그리고 Docker 컨테이너의 ROS 프로세스까지 죽일 수 있다.
  `scripts/sim_teardown.sh` 를 쓴다.
- **`ros2 topic list` / `node list` / `param get` 은 부하가 높으면 멈춘다.**
  이름을 지정한 pub/sub 은 그래도 동작한다. 그래서 확인은
  `scripts/verify_robot_status.py` 로 한다.
- **`colcon build` 는 `pinky_pro/install` 을 source 한 뒤에 한다.** 벤더 패키지에
  의존하는 것이 있다.

---

## 8. 2026-08-18 세션 기록 — 예약 회수와 그 뒤에 드러난 벽 넷

이 절은 실측 기록이다. 무엇이 확인됐고 무엇이 남았는지, 그리고 남은 것을 사람이
손으로 이어가는 방법을 적는다.

### 8.1 무엇이 끝났는가

설계 8절 1~4 와 계획 Task 4·5·6 이 코드로 끝났고 전부 테스트가 붙어 있다.

| 커밋 | 무엇 | 실측 검증 |
|---|---|---|
| `87d4fc91` | 취소 엔드포인트 `POST /internal/v1/jobs/{id}/cancel` | job 2·3 취소 → **예약 6건 회수** |
| `6c99d600` | 만료 회수 `POST /internal/v1/reservations/expire` + 이상 보고 | 실가동 호출 성공, 이상 0건 |
| `46316c7f` | 관제 화면 "예약 이상" 절과 확인 버튼 | 단위·통합 테스트 |
| `237ad0df` | `job_runner` 가 매 주기 회수를 먼저 호출 | 로그에 `expired=[]` 매 주기 |
| `3bd638ca` | 실기 nav2 params root key, TF namespace, 카메라 | launch 계약 테스트 |
| `73217c75` | `scripts/derive_hardware_nav2_params.py` | 실물 벤더 params 로 실행 확인 |
| `0f784d51` | costmap `odom` 프레임 namespace | **`Managed nodes are active` 1 → 2** |
| `4d1f3c4f` | 취소가 outbox 를 닫는다 + RMF worker 가 한 건에 죽지 않는다 | worker 94주기 무사고 |
| `0c2af19c` | 재취소가 남은 outbox 를 마저 닫는다 | 실가동 메시지 2건 정리 |
| `19f68e13` | fleet adapter 에 nav_graph 가 쓰는 충전기 이름 | **fleet 등록 성공** |

시뮬 실측(단일 로봇, `robots:=PK_01`):

```
managed_active      = 2      (기대치. 고치기 전에는 1)
fleet_reject        = 0      (고치기 전에는 무한 재시도)
invalid_odom_frame  = 0      (고치기 전에는 계속 반복)
rmf_worker_crash    = 0      (고치기 전에는 기동 직후 사망)
rmf_cycles          = 94     (고치기 전에는 0)
robot status        : publishers=1, frame_id=map, dispatchable=true, errors=[]
```

### 8.2 순서가 중요했다 — 벽은 하나씩만 보인다

예약이 회수되기 전에는 job 이 배정조차 되지 않아 그 다음 벽이 보이지 않았다.
회수를 고치자 배정이 되고, 그러자 costmap 프레임이 보였다. 그것을 고치자 nav2 가
활성화되고, 그러자 RMF worker 의 죽음이 보였다. 그것을 고치자 worker 가 돌고,
그러자 fleet 등록 실패가 보였다. **네 개는 순차적으로만 관측된다.**

### 8.3 지금 막혀 있는 것

`job 4` 가 `PK_01` 을 쥔 채 되살아나지 못한다.

```bash
PW=$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)
docker exec trihouse-mysql mysql -uroot -p"$PW" --table -e "
  SELECT m.message_id, m.state, m.attempts, LEFT(IFNULL(m.last_error,'-'),40) AS err
    FROM trihouse_fms.integration_messages m WHERE m.job_step_id=17;"
```

`state=dead_letter`, `attempts=5`, `DISPATCH_ATTEMPTS_EXHAUSTED`. 그 5회는 **전부
충전기 이름이 갈라져 있던 때의 시도**다. `dead_letter` 는 재시도 대상이 아니므로
job 4 의 step 20 은 다시 dispatch 되지 않는다. job 1·5 도 2026-08-16 에 만들어진
이전 세션의 시험 잔여물이다.

### 8.4 사람이 이어서 하는 법

**주의: 아래 1번은 되돌릴 수 없는 운영 DB 쓰기다.**

```bash
cd /home/syw/Trihouse

# 0) 시뮬이 떠 있으면 내린다. 이 스크립트는 같은 셸의 pytest 도 죽이므로
#    테스트를 돌리는 중에는 실행하지 마라.
scripts/sim_teardown.sh
uptime            # load average 가 8 아래로 내려간 뒤에 다음으로 간다

# 1) 잔여 job 을 취소해 자원을 비운다. 취소 엔드포인트가 job·step·예약·outbox 를
#    한 트랜잭션에서 닫는다.
for JOB in 1 4 5; do
  curl -s -X POST "http://127.0.0.1:8080/internal/v1/jobs/$JOB/cancel" \
    -H 'Content-Type: application/json' \
    -H "Idempotency-Key: p0-clear-decks-job-$JOB" \
    -d '{"reason":"previous session leftover","requested_by":"W-OP-01"}' \
    | python3 -m json.tool
done

# 2) 자원이 실제로 비었는지 본다. active_resource_key 가 전부 NULL 이어야 한다.
docker exec trihouse-mysql mysql -uroot -p"$PW" --table -e "
  SELECT reservation_id, job_id, IFNULL(device_id, CONCAT('location:',location_id)) AS resource,
         state, IFNULL(active_resource_key,'(none)') AS active_key
    FROM trihouse_fms.reservations ORDER BY reservation_id;"

# 3) 단일 로봇으로 기동한다.
TRIHOUSE_MAP_REVISION="trihouse_test_01:730111d2e446f5141c5ef069e5f2c1c8c5383aea79bdeffd05d3d34f2094b7ff" \
TRIHOUSE_ROBOTS=PK_01 \
ROS_DOMAIN_ID=0 \
control_tower/bringup/p0_simulation_bringup.sh 2>&1 | tee /tmp/sim.log
```

다른 셸에서 판정한다. **위에서부터, 하나씩.**

```bash
SIM=/tmp/sim.log
grep -c 'Managed nodes are active' $SIM        # 기대: 2
grep -c 'We will not add the robot' $SIM       # 기대: 0
grep -c 'Invalid frame ID "odom"' $SIM         # 기대: 0
grep -c 'RMF dispatch cycle failed' $SIM       # 기대: 0
grep -c 'RMF dispatch cycle:' $SIM             # 기대: 0 보다 큼
python3 scripts/verify_robot_status.py pinky_01 20
```

여기까지 통과하면 주문을 넣는다.

```bash
curl -s -X POST http://127.0.0.1:8080/api/v1/orders \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: sim-single-$(date +%s)" \
  -d '{"requested_by":"sim-single","priority":"normal",
       "items":[{"product_code":"SKU-COFFEE","quantity":1}]}' | python3 -m json.tool

grep -E 'job runner cycle|job runner blocked' $SIM | tail -5
grep -E 'RMF dispatch cycle:' $SIM | tail -3
curl -s http://127.0.0.1:8080/api/v1/jobs | python3 -m json.tool | head -40
```

기대: `claimed=` 1 이상, job 이 `queued` → `assigned` → `running`. **여기서부터는
아무도 아직 관측하지 못한 구간이다.** 막히면 그 지점의 로그를 그대로 기록한다.

### 8.5 이 절을 읽을 때 주의할 것

- **`scripts/sim_teardown.sh` 는 같은 셸에서 돌던 pytest 도 죽인다.** 이 세션에서
  실제로 그랬다. 테스트와 teardown 을 같은 시간에 돌리지 마라. handoff 7절이
  경고한 `pkill` 함정이 이 스크립트 안에도 있다.
- **`trihouse_pinky_bringup` 의 install 은 복사본이었다.** handoff 7절의 "launch
  파일은 symlink 라 재빌드가 필요 없다" 는 이 패키지에 맞지 않았다.
  `colcon build --packages-select trihouse_pinky_bringup --symlink-install` 로 한 번
  다시 빌드해 두었고, 이제 install → build → source 가 live symlink 로 이어진다.
- **Gateway 컨테이너는 소스 마운트가 아니라 빌드 이미지다.** `fms_gateway` 를
  고치면 반드시 다시 빌드해야 새 엔드포인트가 뜬다.

  ```bash
  docker compose --project-name trihouse_p0 --env-file .env \
    -f compose.yaml -f compose.control.yaml -f compose.edge_4060.yaml \
    -f compose.simulation.yaml up -d --build fms_gateway
  curl -s http://127.0.0.1:8080/openapi.json | python3 -c "
  import json,sys; p=json.load(sys.stdin)['paths']
  print('/internal/v1/jobs/{job_id}/cancel' in p)"
  ```
- **Gateway 통합 테스트에는 자격증명이 필요하다.** 6절의 ② 만으로는 부족하다.

  ```bash
  FMS_DB_HOST=127.0.0.1 FMS_DB_PORT=3307 \
  FMS_DB_USER=fms_gateway FMS_DB_PASSWORD=test_gateway_password \
  FMS_DB_ADMIN_USER=root FMS_DB_ADMIN_PASSWORD=test_root_password \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q fms_gateway/tests
  ```

### 8.6 실기로 넘어갈 때

계획 Task 3(분기점)은 실물 로봇에서 `grep` 하나로 30초면 끝난다. 그 결과가 A 면
파생 params 를 만들어 넘긴다 — 이제 도구가 있다.

```bash
scripts/derive_hardware_nav2_params.py \
  --source pinky_pro/pinky_navigation/params/nav2_params.yaml \
  --namespace pinky_01 \
  --output .trihouse/p0/nav2/hardware_pinky_01.yaml
```

첫 줄이 `pinky_01:` 이면 성공이다. 분기 B(`namespace:=''`)면 이 도구를 쓰지 않고
벤더 기본 params 를 그대로 쓴다.
