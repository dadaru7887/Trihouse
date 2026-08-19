# P0 B절 완주 런북 — 주문 하나를 7단계 끝까지

주문 1건이 다음 7단계를 통과하는 것을 한 사이클로 본다.

```text
10 arm/pick        로봇팔이 물건을 집는다
20 mobile/navigate 로봇이 적재 지점으로 간다
30 fms/load        적재
40 mobile/navigate 로봇이 인계 지점으로 간다
50 fms/handover    인계
60 fms/wait        ← 사람이 확인해 줘야 넘어간다 (작업 9)
70 mobile/return_home 로봇이 돌아온다
```

## 이 문서를 읽는 사람이 먼저 알아야 할 것

**아직 한 번도 완주한 적이 없다.** 2026-08-19 기준 확인된 구간은 여기까지다.

| 구간 | 상태 |
|---|---|
| 주문 → job 계획 → RMF 낙찰 → 배정 반영 | 확인됨 |
| step 10 로봇팔 pick | 확인됨 (`succeeded`) |
| step 20 주행 | **로봇이 실제로 움직이는 것까지 확인됨.** 충전소 → `frozen_storage_loading_dock_01` |
| step 30 이후 | **미확인** |

step 20 까지 도달한 회차에서 원장이 그 주행을 `failed` 로 적는 결함이 있었고
(D11-b), 그것을 고친 뒤로는 아직 돌려 보지 않았다. **막히는 것이 정상이다.**
막히면 아래 "막혔을 때" 절을 따른다.

## 절대 규칙

- **시뮬을 만지는 창은 하나로 유지한다.** 다른 Claude 세션이나 다른 터미널에서
  `scripts/sim_teardown.sh` 를 돌리면 이 창의 bringup 이 함께 죽는다
  (`p0_simulation_bringup` 이 kill 패턴에 있다). 2026-08-19 에 이것으로 한
  회차를 잃었다.
- `pinky_pro/**` 와 `control_system/**` 는 **읽기·실행 전용**이다.
- 판정은 로그의 성공 문구가 아니라 **측정값**으로 한다. bringup 은 하위 launch 가
  죽어도 "올라왔습니다" 를 출력한다.

---

## 작업 0 → 터미널 1 (사전 조건)

서버 PC 에서 처음 시작한다면 컨테이너부터 띄운다. 이미 떠 있으면 건너뛴다.

```bash
cd /home/syw/Trihouse
docker ps --format '{{.Names}}' | sort
```

`trihouse-mysql`, `trihouse_p0-fms_gateway-1`, `trihouse_p0-rmf_api-1`,
`trihouse_p0-rmf_dashboard-1`, `trihouse_p0-mediamtx-1`,
`trihouse_p0-control_ui-1` 여섯이 보이면 된다. 없으면:

```bash
docker compose -p trihouse_p0 \
  -f compose.yaml -f compose.control.yaml \
  -f compose.edge_4060.yaml -f compose.simulation.yaml \
  up -d
```

Gateway 가 실제로 응답하는지 확인한다. bringup 이 이것을 요구한다.

```bash
curl -fsS http://127.0.0.1:8080/ready && echo " gateway ready"
```

지도 revision 이 발행돼 있는지 확인한다. 아래 값이 작업 2 에서 그대로 쓰인다.

```bash
docker exec trihouse-mysql mysql -uroot \
  -p"$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)" --table \
  -e "SELECT map_revision, state FROM trihouse_fms.map_revisions;" 2>/dev/null
```

`state` 가 `published` 여야 한다.

---

## 작업 1 → 터미널 1 (정리)

```bash
cd /home/syw/Trihouse
scripts/sim_teardown.sh
ps -eo pid,etimes,args | grep -E 'trihouse|gz sim' | grep -v grep
```

두 번째 명령이 **아무것도 출력하지 않아야** 다음으로 간다.

남는 것이 있으면 나이를 본다. `sim_teardown.sh` 는 **실행 파일이** `pytest` 나
`colcon` 인 프로세스를 일부러 살려 둔다 — 돌고 있는 테스트나 빌드를 중간에
죽이지 않기 위해서다. 판정은 `argv[0]` 기준이므로, 테스트가 **띄워 놓고 간**
launch(인자에 `/tmp/pytest-.../` 가 들어 있을 뿐인 것)는 이제 정리 대상이다.

그래도 남는 것이 있으면 오래된 것만 골라 정리한다 — 일괄로 죽이지 않는다.

```bash
ps -eo pid,etimes,args | grep -E 'trihouse|gz sim' | grep -v grep \
  | awk '$2 > 300 {print $1}' | xargs -r kill
```

큐를 비운다. 런타임 상태이지 저장소 자산이 아니다.

```bash
rm -f .trihouse/p0/pinky_0*_task_events.sqlite3
```

---

## 작업 2 → 터미널 1 (bringup)

```bash
cd /home/syw/Trihouse
setsid nohup env \
  TRIHOUSE_MAP_REVISION="trihouse_test_01:730111d2e446f5141c5ef069e5f2c1c8c5383aea79bdeffd05d3d34f2094b7ff" \
  TRIHOUSE_ROBOTS=PK_01 \
  TRIHOUSE_NAV2_MAP="$PWD/control_ui/rmf_control_ui/data/rmf_maps/new_map_2.yaml" \
  ROS_DOMAIN_ID=0 \
  control_tower/bringup/p0_simulation_bringup.sh > /tmp/sim.log 2>&1 &
disown
```

`setsid` 로 새 세션에 띄우므로 **이 창을 닫아도 죽지 않는다.** 포그라운드로
묶으면 창을 닫는 순간 프로세스 그룹이 통째로 죽는다.

`TRIHOUSE_ROBOTS` 는 **robot_id** 를 받는다 — `PK_01` 이지 `pinky_01` 이 아니다.
`pinky_01` 은 DDS namespace 다.

진행은 `tail -f /tmp/sim.log` 로 본다(Ctrl+C 해도 시뮬은 산다).

**2분 뒤 판정:**

```bash
grep -c 'Managed nodes are active' /tmp/sim.log
grep -c 'p0_world.sdf' /tmp/sim.log
```

| 명령 | 기대값 | 뜻 |
|---|---|---|
| 첫 번째 | **2** | Nav2 lifecycle 이 활성 |
| 두 번째 | **1 이상** | 물리 설정(RTF 0.71)이 실제로 적용됨 |

---

## 작업 3 → 터미널 2 (TF relay — **창을 닫지 말 것**)

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash && source install/setup.bash && source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=0
python3 scripts/tf_relay.py pinky_01
```

포그라운드로 계속 떠 있는다. nav2 는 `-r /tf:=tf` 로 뜨므로 TF 가
`/pinky_01/tf` 에 있고 전역 `/tf` 에는 `map -> odom` 이 없다. RViz 는 tf2
규약대로 절대 이름을 보므로, 이것이 없으면 `Frame [map] does not exist` 가 된다.

로봇을 두 대 띄운 상태에서 relay 를 둘 돌리면 전역 `/tf` 에 같은 프레임 이름이
두 번 들어간다. **관측할 때만, 한 대에만 쓴다.**

---

## 작업 4 → 터미널 3 (RViz — **창을 닫지 말 것**)

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash && source install/setup.bash && source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=0
rviz2 -d control_tower/bringup/p0_sim.rviz
```

`pinky_pro/install/setup.bash` 를 빼면 로봇 메시를 못 찾아 RobotModel 이
빨간 Error 가 된다.

보여야 하는 것:

| 항목 | 값 |
|---|---|
| Fixed Frame | `map` |
| Map 토픽 | `/pinky_01/map` (Durability: **Transient Local**) |
| RobotModel | TF Prefix `pinky_01` |

`pinky_01/caster_rotate_link`, `pinky_01/caster_wheel` 에 Status Error 가 뜨는
것은 URDF 에 해당 메시가 없어서이고 주행과 무관하다.

---

## 작업 5 → 터미널 4 (판정 — 여기서 걸러야 뒤가 믿을 만하다)

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash && source install/setup.bash && source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=0
python3 scripts/verify_robot_status.py pinky_01 20
grep -c 'FMS command claim 실패' /tmp/sim.log
```

**셋이 모두 맞아야 아래로 간다.**

| 항목 | 기대값 | 아니면 |
|---|---|---|
| `publishers` | 전부 **1** | 이전 세대가 남았다 — 작업 1 로 돌아간다. **이 값이 2 이상이면 그 아래 숫자는 전부 못 믿는다** |
| 판정 | **`RESULT: PASS`** | `errors` 를 읽는다 |
| claim 실패 | **0** | 원장에 없는 task 를 어댑터가 claim 하고 있다 |

`amcl_pose: (없음)` 은 정지 상태에서 정상이다. `frame_id: map` 이면 AMCL 이
수렴한 것이다.

---

## 작업 6 → 터미널 4 (주문)

```bash
curl -s -X POST http://127.0.0.1:8080/api/v1/orders \
  -H 'Content-Type: application/json' -H "Idempotency-Key: b-run-$(date +%s)" \
  -d '{"requested_by":"W-OP-01","priority":"normal","items":[{"product_code":"SKU-PORKBELLY","quantity":1}]}' \
  | python3 -m json.tool
```

응답의 **`job_id` 를 적어 둔다.** 아래에서 `<JOB>` 자리에 넣는다.

같은 `Idempotency-Key` 로 다시 부르면 같은 job 이 돌아온다. 아직 `queued` 인
job 이 있으면 새 주문을 넣어도 그것이 반환될 수 있다.

---

## 작업 7 → 터미널 5 (진행 관측)

```bash
cd /home/syw/Trihouse
watch -n2 'docker exec trihouse-mysql mysql -uroot -p"$(grep -E "^MYSQL_ROOT_PASSWORD=" /home/syw/Trihouse/.env | cut -d= -f2-)" --table -e "SELECT s.step_no,s.executor_type,s.action_type,s.state,IFNULL(m.channel,\"-\") ch,IFNULL(m.state,\"-\") outbox FROM trihouse_fms.job_steps s LEFT JOIN trihouse_fms.integration_messages m ON m.job_step_id=s.job_step_id WHERE s.job_id=<JOB> ORDER BY s.step_no;" 2>/dev/null'
```

`outbox` 가 `dead_letter` 가 되면 그 step 은 회복되지 않는다. 재투입 API 는
없다 — job 을 닫고 새로 시작한다(아래 "막혔을 때").

---

## 작업 8 → 터미널 4 (주행 측정 — step 20 이 `running` 이 된 뒤)

```bash
timeout 25 python3 -c "
import time, rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
rclpy.init(); n=Node('p'); c=[]; o=[]
n.create_subscription(Twist,'/pinky_01/cmd_vel',c.append,10)
n.create_subscription(Odometry,'/pinky_01/odom',o.append,10)
e=time.monotonic()+15
while rclpy.ok() and time.monotonic()<e: rclpy.spin_once(n,timeout_sec=0.2)
mv=[x for x in c if abs(x.linear.x)>1e-4 or abs(x.angular.z)>1e-4]
print('cmd_vel %d / 움직임 %d' % (len(c), len(mv)))
if o:
    a,b=o[0].pose.pose.position,o[-1].pose.pose.position
    print('이동 %.4f m' % (((b.x-a.x)**2+(b.y-a.y)**2)**0.5))
n.destroy_node(); rclpy.shutdown()"
```

**주행 확인은 로그가 아니라 이 값으로 한다.** step 이 `running` 이고 RViz 에
초록 경로가 그려져도 로봇이 안 움직일 수 있다.

| 결과 | 뜻 |
|---|---|
| `cmd_vel 0` | **발행자가 없다.** 0 값이 오는 것과 다르다. `safety_supervisor` 가 떴는지 본다 |
| `cmd_vel N / 움직임 0` | 발행자는 있는데 값이 0 — 목표가 없거나 안전 gate 가 막고 있다 |
| `움직임 > 0`, `이동 > 0` | 실제로 주행 중 |

---

## 작업 9 → 터미널 4 (사람 확인 — step 60 에서 멈췄을 때)

step 60 은 `fms/wait` 이고 **사람이 확인해 줘야 넘어간다.** 이것이 없으면
영원히 기다린다.

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/jobs/<JOB>/worker-completion \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: worker-completion-<JOB>" \
  -d '{"worker_id":"W-OP-01","completion_note":"manual B-run"}' \
  | python3 -m json.tool
```

409 `MANUAL_ACKNOWLEDGEMENT_REQUIRED` 가 오면 응답의 `item_ids` 를 그대로 넣어
다시 부른다.

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/jobs/<JOB>/worker-completion \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: worker-completion-<JOB>-ack" \
  -d '{"worker_id":"W-OP-01","acknowledged_manual_item_ids":[<ID>]}' \
  | python3 -m json.tool
```

이 호출은 **실물 재고를 확정한다.** 되돌릴 수 없다.

---

## 작업 10 → 터미널 4 (완주 판정)

```bash
docker exec trihouse-mysql mysql -uroot \
  -p"$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)" --table -e "
SELECT job_id, state FROM trihouse_fms.jobs WHERE job_id=<JOB>;
SELECT step_no, state FROM trihouse_fms.job_steps WHERE job_id=<JOB> ORDER BY step_no;
" 2>/dev/null
```

**7 단계가 모두 `succeeded` 이고 job 이 `completed` 이면 한 사이클 완주다.**

---

## 막혔을 때

### 먼저 볼 것

```bash
grep -aE '\[(ERROR|WARN)\]' /tmp/sim.log | tail -30 | cut -c1-200
```

### 증상별

| 증상 | 원인 · 조치 |
|---|---|
| step 이 `pending` 인데 `outbox` 가 `dead_letter` | 재투입 API 가 없다. job 을 닫고 새 주문 |
| `job runner blocked: no free robot` | 앞선 job 이 로봇을 쥐고 있다. 그 job 을 닫는다 |
| `robot is not idle` 반복 | 정차 대기(D13) 문제. `arrival_stop_timeout_s` 확인 |
| `Unable to replan assignments` | 순간 안전정지가 로봇을 fleet 에서 빼냈다(**D15, 미수정**). RTF 가 낮으면 잦아진다 — 작업 2 의 `p0_world.sdf` 확인이 통과했는지 본다 |
| `FMS command claim 실패: 404` 반복 | 원장에 없는 task 를 claim 하고 있다. `pinky_fleet.yaml` 의 `finishing_request` 가 `"nothing"`, `responsive_wait` 가 `false` 인지 확인 |
| 시뮬이 이유 없이 죽음 | **다른 창이 teardown 을 돌렸다.** `ps -eo args \| grep claude` |
| 저장소 동작이 테스트와 다름 | InMemory 와 MySQL 두 구현이 어긋났을 수 있다. **운영은 MySQL 로 돈다** |

### job 을 닫고 다시 시작

```bash
curl -sS -X POST http://127.0.0.1:8080/internal/v1/jobs/<JOB>/cancel \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: manual-cancel-<JOB>' \
  -d '{"reason":"<사유>","requested_by":"W-OP-01"}' | python3 -m json.tool
```

`reason` 과 `requested_by` **둘 다 필수**다. 30초 뒤 job 이 `cancelled` 로
남아 있는지 확인한다 — `assigned` 로 돌아가면 취소한 job 을 러너가 되살린
것이다(D16, 고침).

취소는 **재고 예약을 돌려주지 않는다**(D2, 미수정). 재고를 봐야 한다면 취소보다
먼저 읽는다.

---

## 한 번에 붙여 넣는 요약

```text
터미널 1   작업 0 사전 조건 → 작업 1 정리 → 작업 2 bringup      (창 닫아도 됨)
터미널 2   작업 3 tf_relay                                      ← 닫지 말 것
터미널 3   작업 4 rviz2                                          ← 닫지 말 것
터미널 4   작업 5 판정 → 6 주문 → 8 주행 측정 → 9 사람 확인 → 10 완주 판정
터미널 5   작업 7 진행 관측 (watch)
```

관련 문서: [p0-stack-reference.md](p0-stack-reference.md) — 결함 D1~D20 의 증상·근거·수정 내역
