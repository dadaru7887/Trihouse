# 수동 시뮬레이션 절차 — D20 수정 검증

작성: 2026-08-19 04:45 · 브랜치 `feat/pinky-edge-agent` (미커밋)
테스트: `trihouse_pinky`+`control_tower`+`trihouse_rmf_bridge` **628 passed** /
`fms_gateway/tests/unit` **211 passed**

---

## 0. 지금 상태 — 출발선이 깨끗하다

| | 상태 |
|---|---|
| 시뮬 | **내려가 있음.** 고아 프로세스 0 (`sim_teardown` 이 2개 정리) |
| 부하 | load average **13.7** 로 하강 중 |
| Docker | P0 6개 + 테스트 MySQL(3307) 1개 |
| 살아 있는 job | **0** — 로봇 PK_01 자유 |
| Gateway | 04:31 재빌드본. `JOB_ALREADY_TERMINAL` 포함 (D16) |
| 재고 | SKU-ICEBAR 2, SKU-ICECONE 2, SKU-MANDARIN 2, 나머지 1 |

**주의:** `inventory_lots.reserved_qty` 에 **2** 가 갇혀 있다(D2 — 취소가 예약을
돌려주지 않는다). 아래 3-0 에서 직접 풀어야 한다.

---

## 1. 이번에 고친 것 — D20

### 무엇이 문제였나

낙찰 결과가 원장으로 돌아오는 경로가 **죽은 토픽**을 보고 있었다.

```
RosTaskSummaryObserver.attach(node, topic="task_summaries")   ← ros_task_client.py:116
```

실측(12초 구독):

```
task_summaries 수신 : 0
fleet_states  수신 : 97      robot=PK_01  task_id=''  mode=0
```

워커는 제출 직후 응답을 받는데 그때는 **입찰 전이라 `assignment` 가 없는 것이
정상**이고, 나중에 채워 줄 observer 가 아무것도 안 오는 토픽을 보고 있었다. 그래서
영원히 `RMF_ASSIGNMENT_PENDING` → 5회 소진 → `dead_letter` → step `failed`.

**RMF 와 로봇은 정상이었다.** 04:03 실행에서 실제로 이렇게 돌았다:

```
Bidding Result: task [compose.dispatch-d79d39763c] is awarded ... expected robot [PK_01]
[PK_01] RMF compose.dispatch-d79d39763c -> (0.841, -0.111, -1.089)
[PK_01] Pinky 도착·정지 확인 후 RMF 이동을 완료했습니다.
[PK_01] RMF compose.dispatch-d79d39763c -> (1.201, -0.799, -1.089)
```

**로봇은 두 구간을 주행했는데 원장만 실패로 적혔다.**

### 무엇을 고쳤나

| 파일 | 무엇 |
|---|---|
| `control_tower/rmf_adapter/task_api.py` | `normalize_fleet_state()` 추가 — `fleet_states` 의 `robots[].task_id` 에서 낙찰 사실만 뽑는다 |
| `control_tower/rmf_adapter/ros_task_client.py` | `RosFleetStateObserver` 추가 — 우리가 아는 작업만 원장에 반영 |
| `control_tower/rmf_adapter/rmf_gateway_worker_node.py` | 두 observer 를 함께 배선. `--fleet-state-topic` (기본 `fleet_states`) 추가 |
| `control_tower/tests/test_fleet_state_assignment_observer.py` | 신규, **8 테스트** |

**설계 판단 둘:**

1. **성패는 `fleet_states` 로 만들지 않는다.** `task_id` 가 빈 값으로 돌아가는 것은
   완료와 취소를 구분할 수 없다. 완료·실패는 로봇이 `task_event` 로 직접 보고한다.
   여기서 하는 일은 Gateway 가 outbox 를 닫도록 `robot_name` 을 돌려주는 것 하나다.
2. **`task_summaries` 구독을 지우지 않았다.** 다른 RMF 배포에서는 흐르므로 남겨 두고
   `fleet_states` 를 **더한다.** 비용이 없다.

### 왜 이것으로 끝까지 이어지는가

`fms_gateway/app/repositories.py` 의 `apply_rmf_task_update` 가 이렇게 되어 있다.

```python
if robot_name and row["message_id"] and row["message_state"] == "sent":
    ...  # outbox 를 acknowledged 로 닫는다
```

**`robot_name` 만 돌려주면 나머지는 이미 있다.** 그래서 토픽 하나가 경로 전체를
막고 있었다.

> **단, 이미 `dead_letter` 인 메시지는 되살아나지 않는다.** 위 조건이
> `message_state == "sent"` 이기 때문이다. 그래서 **새 주문으로만 검증된다.**

---

## 2. 아직 안 고친 것 — 정직하게

| 후보 | 무엇 | 왜 안 고쳤나 |
|---|---|---|
| **D19** | Gateway 가 로봇 메시지를 `MESSAGE_TYPE_UNSUPPORTED` 로 거절 (이전 세대 로그에 42건) | **근본 원인을 확정하지 못했다.** 로봇이 `command_ack`·`command_rejected` 를 보내는데 `tcp_protocol.py:66-73` 이 그 타입을 모른다. 그런데 그 두 메시지에는 `session_id` 가 없어 순서상 `SESSION_ID_MISMATCH` 가 먼저 나야 한다(`:64`). 로그는 그렇게 말하지 않는다 — **모순이 남아 있다.** 추측으로 고치면 안 된다 |
| **D21** | `execution_command` 가 `HTTP 409 Conflict` 로 5회 실패 | 409 가 **결함인지 정상 동작인지** 모른다. D11-a 가 멱등키를 `rmf:{task}:robot:{robot}:rev:{revision}` 로 바꿨으므로, 같은 revision 에서 두 번 쓰면 409 가 **맞는 동작**일 수 있다. 그렇다면 고칠 곳은 409 가 아니라 그것을 재시도로 처리하는 쪽이다 |

**둘 다 이번 실행에서 다시 나오는지 봐야 한다.** 두 증거 모두 이전 세대 로그에
있었고 그 로그는 재기동으로 지워졌다. **이번 실행이 곧 재현 시험이다.**

그리고 **로봇은 이 둘이 있는 상태에서도 주행했다.** 완주를 직접 막는 것이 아닐
가능성이 있다.

---

## 3. 수동 실행 절차

### 3-0. 재고 예약 해제 → 터미널 1 (**직접 실행하셔야 합니다**)

자동 모드가 운영 원장 직접 `UPDATE` 를 차단한다.

```bash
cd /home/syw/Trihouse
PW=$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)
docker exec trihouse-mysql mysql -uroot -p"$PW" --table -e "
UPDATE trihouse_fms.inventory_lots SET reserved_qty = 0 WHERE reserved_qty > 0;
SELECT SUM(available_qty) AS avail, SUM(reserved_qty) AS reserved FROM trihouse_fms.inventory_lots;
" 2>&1 | grep -v 'password on the command line'
```

기대: `reserved 0`.

### 3-1. 출발선 확인 → 터미널 1

```bash
cd /home/syw/Trihouse
export ROS_DOMAIN_ID=0

uptime                                        # load 10 아래에서 시작하는 것이 좋다
ps -eo pid,etime,args | grep -E "two_pinky_order_demo|gz sim|lifecycle_manager" | grep -v grep
curl -s http://127.0.0.1:8080/ready; echo
docker inspect trihouse_p0-rmf_api-1 \
  --format '{{range .Config.Env}}{{println .}}{{end}}' | grep ROS_DOMAIN_ID
```

기대: 프로세스 목록 **비어 있음**, `{"status":"ready","database":"ok"}`,
`ROS_DOMAIN_ID=0`.

프로세스가 남아 있으면 `scripts/sim_teardown.sh` 를 먼저 돌린다.
**`pkill -f` 는 쓰지 않는다** — 자기 명령줄에 걸려 자멸하고 Docker 안까지 죽인다.

### 3-2. 시뮬 기동 → 터미널 2 (**이 창은 절대 닫지 마십시오**)

닫으면 SIGHUP 으로 시뮬 전체가 죽는다(D18). Ctrl+C 가 정상 종료다.

```bash
cd /home/syw/Trihouse
TRIHOUSE_ROBOTS=PK_01 \
TRIHOUSE_MAP_REVISION="trihouse_test_01:730111d2e446f5141c5ef069e5f2c1c8c5383aea79bdeffd05d3d34f2094b7ff" \
ROS_DOMAIN_ID=0 \
control_tower/bringup/p0_simulation_bringup.sh 2>&1 | tee /tmp/sim.log
```

지도를 `new_map_2` 로 쓰려면 한 줄을 더한다(기본은 `trihouse_map_01`).
두 지도 모두 nav graph 정점 10개를 포함하는 것을 확인했다.

```bash
TRIHOUSE_NAV2_MAP=/home/syw/Trihouse/control_ui/rmf_control_ui/data/rmf_maps/new_map_2.yaml \
```

**`ROS_DOMAIN_ID=0` 을 빼면** 스크립트 기본값 52로 떠서 Docker 층(0)과 갈라지고
RMF 대시보드가 빈다. **`TRIHOUSE_ROBOTS=PK_01` 을 빼면** 2대가 떠서 load 가
60~130 까지 간다.

### 3-3. 기동 판정 → 터미널 3 (기동 2분 뒤)

**bringup 의 `"올라왔습니다"` 를 믿지 않는다.** 로봇 launch 가 죽어도 그 줄이
나온다(D1).

```bash
cd /home/syw/Trihouse
set +u; source /opt/ros/jazzy/setup.bash; source install/setup.bash; source pinky_pro/install/setup.bash; set -u
export ROS_DOMAIN_ID=0

grep -c 'Managed nodes are active' /tmp/sim.log      # 2
grep -c 'waiting for its battery' /tmp/sim.log       # 0   ← D7
pgrep -af 'lib/trihouse_pinky_fleet/fleet_node' >/dev/null && echo fleet_node_OK   # D10
python3 scripts/verify_robot_status.py pinky_01 20
```

기대: **`RESULT: PASS`**, `frame_id=map`, `dispatchable=true`, `errors=[]`,
`publishers` 가 전부 **1** (2 이면 이전 세대가 남은 것이니 값을 믿지 말고 정리부터).

기동 직후 1~2분은 AMCL 수렴 전이라 `frame_id=pinky_01/odom` 이 정상이다.
`ros2 topic list`/`node list`/`param get` 은 부하에서 40초 멈추므로 쓰지 않는다.

### 3-4. 주문 → 터미널 3

**재고가 SKU 당 유한하므로 매번 다른 SKU 를 쓴다.** 지금 2개 남은 것부터.

```bash
curl -s -X POST http://127.0.0.1:8080/api/v1/orders \
  -H 'Content-Type: application/json' -H "Idempotency-Key: run-$(date +%s)" \
  -d '{"requested_by":"W-OP-01","priority":"normal","items":[{"product_code":"SKU-ICEBAR","quantity":1}]}' \
  | python3 -m json.tool
```

기대: `201` + job 1건 + **7단계**. 다음 회차는 `SKU-ICECONE` → `SKU-MANDARIN`.

### 3-5. **D20 검증** — 이번 실행의 핵심 → 터미널 3

주문 40초 뒤. **`outbox` 열이 판정 기준이다.**

```bash
cd /home/syw/Trihouse
PW=$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)
docker exec trihouse-mysql mysql -uroot -p"$PW" --table -e "
SELECT s.step_no, s.state, IFNULL(s.rmf_task_id,'-') rmf_task,
       IFNULL(m.state,'-') outbox, IFNULL(m.attempts,0) att
  FROM trihouse_fms.job_steps s
  LEFT JOIN trihouse_fms.integration_messages m ON m.job_step_id=s.job_step_id
 WHERE s.job_id=(SELECT MAX(job_id) FROM trihouse_fms.jobs) ORDER BY s.step_no;
" 2>&1 | grep -v 'password on the command line'
```

| step 20 의 `outbox` | 뜻 |
|---|---|
| **`acknowledged`** | **D20 수정 성공.** 낙찰이 원장으로 돌아왔다 |
| `sent` (att 1~4) | 아직 입찰 중. 30초 더 기다린다 |
| `dead_letter` (att 5) | **D20 수정 실패.** 아래 3-7 로 원인을 가른다 |

워커 쪽에서도 같은 것을 본다.

```bash
grep -oE "RMF dispatch cycle:.*" /tmp/sim.log | tail -3
```

| 보이는 것 | 뜻 |
|---|---|
| `claimed=1 accepted=1` | **성공** |
| `claimed=1 indeterminate=1` 반복 | observer 가 여전히 배정을 못 받는다 |

### 3-6. 주행 관찰 → 터미널 3

```bash
grep -oE "\[PK_01\].*" /tmp/sim.log | tail -8
```

보고 싶은 것:

```
[PK_01] RMF compose.dispatch-... -> (0.841, -0.111, ...)     ← BOTTLENECK-01
[PK_01] Pinky 도착·정지 확인 후 RMF 이동을 완료했습니다.        ← D13 수정 작동
[PK_01] RMF compose.dispatch-... -> (1.201, -0.799, ...)     ← 창고 dock
```

**포장대에서 멈추면 정상이다.** step 60 `wait` 가 사람의 완료 보고를 기다린다.
이것을 넣어야 step 70 `return_home` 이 시작되고 충전소로 돌아간다.

```bash
curl -s -X POST http://127.0.0.1:8080/api/v1/jobs/<JOB_ID>/worker-completion \
  -H 'Content-Type: application/json' -d '{}' | python3 -m json.tool
```

기대: `state_reason_code=RETURNING_TO_FIXED_CHARGER` +
`charging_station_01` 로 가는 `rmf` outbox 1건.

### 3-7. 막히면 — 원인 분기

```bash
cd /home/syw/Trihouse
for k in "Unable to replan" "sensor_timeout" "robot is not idle" \
         "no running event loop" "waiting for stop" "MESSAGE_TYPE_UNSUPPORTED" \
         "HTTP Error 409" "ASSIGNMENT_MISMATCH" "did not received any bids"; do
  printf "  %-26s : %s\n" "$k" "$(grep -c "$k" /tmp/sim.log)"
done
```

| 보이는 것 | 뜻 | 어디를 본다 |
|---|---|---|
| `Unable to replan` / `sensor_timeout` | **D15** — 순간 안전정지가 로봇을 fleet 에서 빼낸다 | 레퍼런스 10절 D15 |
| `robot is not idle` | **D13 재발** | `arrival_stop_timeout_s` 를 2.0 → 4.0 으로 올려 본다 |
| `no running event loop` | 정차 대기가 rclpy 에서 죽었다 | 이번 세션에 고쳤다. 나오면 재빌드 누락 |
| `waiting for stop` 만 있고 `robot is not idle` 0 | **정상.** 레이스가 났고 대기가 막아 냈다 — 가장 강한 증거 | — |
| `MESSAGE_TYPE_UNSUPPORTED` | **D19 재현** | 2절. 나오면 그때 원인을 확정한다 |
| `HTTP Error 409` | **D21 재현** | 2절 |
| `did not received any bids` | 로봇이 fleet 에 없다 | `We will not add the robot` 을 grep |

**RTF 도 함께 본다.** 낮으면 타임아웃 계열이 전부 흔들린다.

```bash
source /opt/ros/jazzy/setup.bash && source pinky_pro/install/setup.bash
gz topic -e -t /world/default/stats -n 2 | grep real_time_factor
```

직전 실측은 **0.09~0.22** 였다(벤더 물리 `step_size 0.001`). 0.2 아래가 계속되면
`p0_simulation_bringup.sh:187` 을 `control_tower/bringup/p0_world.sdf` 로 바꿔
250Hz/0.004/iters 50 로 낮춘다 — **다만 재기동이 필요하다.**

### 3-8. 정리 → 터미널 2

```bash
# 터미널 2 에서 Ctrl+C  (정상 종료)
# 그다음 터미널 1 에서
scripts/sim_teardown.sh
ps -eo pid,etime,args | grep -E "two_pinky_order_demo|gz sim|lifecycle_manager" | grep -v grep
```

두 번째 줄이 비어야 한다. **세대가 겹치면 다음 측정이 전부 오염된다** — 실제로
그렇게 잃은 구간이 있었다(D17).

---

## 4. 관측용 (선택) → 터미널 4·5

```bash
# 터미널 4 — 닫으면 RViz 에서 지도가 사라진다
python3 scripts/tf_relay.py pinky_01

# 터미널 5
rviz2 -d control_tower/bringup/p0_sim.rviz --ros-args -p use_sim_time:=true
```

로봇 형체를 보려면 터미널 5 도 `pinky_pro/install` 까지 3단 source 해야 한다.

---

## 5. 이번 실행으로 답이 나오는 질문

| 질문 | 답이 되는 지표 |
|---|---|
| D20 수정이 맞았나 | step 20 `outbox = acknowledged` |
| D13 수정이 실전에서 버티나 | `robot is not idle` 0 + `도착·정지 확인` 로그 |
| D19 가 완주를 막나 | `MESSAGE_TYPE_UNSUPPORTED` 가 나오는데도 완주하면 안 막는다 |
| D21 이 완주를 막나 | `HTTP Error 409` 가 나오는데도 완주하면 안 막는다 |
| RTF 를 고쳐야 하나 | `Unable to replan`/`sensor_timeout` 이 나오면 고친다 |

**완주(step 70 `succeeded`)까지 가면 P0 기준선이 처음으로 생긴다.**
그때 실측을 `docs/validation/` 에 적고, 3회 연속을 확인한다.
