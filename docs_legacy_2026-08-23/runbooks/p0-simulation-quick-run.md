# P0 시뮬레이션 실행 런북 (cook2)

## 현재 `new_map_2` 정본 (2026-08-22)

이 작업은 `/home/newuser/Trihouse/.worktrees/physical-integration-v1`에서 실행한다.
지도 feature 계약은 **waypoint 12 / bottleneck 2 / fiducial 0**이다. 기존 waypoint
10개에 아래 두 규칙 주행 인계점이 추가되어 있다.

| waypoint | x | y | yaw |
|---|---:|---:|---:|
| `ambient_storage_narrow_entry` | 1.010244055594586 | 0.9167344977253539 | -0.08675495954950327 |
| `chilled_storage_narrow_entry` | 1.1013315221281241 | -0.10045055614140724 | 3.1029342608092607 |

`p0_reset.sh`는 현재 소스로 Gateway 이미지를 다시 빌드하고 DB를 초기화한 뒤
`new_map_2`를 발행한다. 따라서 revision이나 임시 fiducial을 손으로 만들지 않는다.

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
P0_ROS_DOMAIN_ID=0 scripts/p0_reset.sh \
  "$PWD/pinky_pro_alpha/pinky_navigation/map/new_map_2.yaml"
P0_ROS_DOMAIN_ID=0 scripts/p0_up.sh
```

RViz와 TF relay를 띄운 뒤, 아직 최종 도크 pose가 실물 검증 전인 상온·냉장은
명시적인 calibration gate에서만 한 번씩 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=0
ros2 param set /pinky_01/trihouse_fleet allow_narrow_calibration true
```

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q \
  tests/simulation/test_narrow_zone_drive.py::test_drive_one_simulated_narrow_zone_roundtrip \
  --enable-sim-motion --sim-robot-namespace pinky_01 \
  --sim-destination ambient_storage_loading_dock_01 --sim-phase enter
```

상온 결과가 성공하고 궤적을 확인한 다음 목적지만 바꾸어 냉장을 실행한다.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q \
  tests/simulation/test_narrow_zone_drive.py::test_drive_one_simulated_narrow_zone_roundtrip \
  --enable-sim-motion --sim-robot-namespace pinky_01 \
  --sim-destination chilled_storage_loading_dock_01 --sim-phase enter
```

`--sim-phase roundtrip`은 탈출 후보까지 함께 움직이므로 각 `enter`를 먼저 확인하기
전에는 사용하지 않는다. 실행 흔적은 `/tmp/trihouse_narrow_*.json[l]`에 남는다.

주문 한 건이 아래 7 단계를 통과하는 것을 **한 사이클**로 본다.

```text
10 arm/pick          로봇팔이 물건을 집는다
20 mobile/navigate   로봇이 적재 지점으로 간다
30 fms/load          적재
40 mobile/navigate   로봇이 인계 지점으로 간다
50 fms/handover      인계
60 fms/wait          ← 사람이 확인해 줘야 넘어간다
70 mobile/return_home 로봇이 대기/충전소로 돌아온다
```

이 문서는 **이 PC(`cook2`, `/home/newuser/Trihouse`)에서 반복 실행**하는 현재 기준
절차다. 다른 호스트의 경로·계정·실행 스크립트와 섞어 쓰지 않는다.

---

## 매 회차 절차

### 터미널 1 — 초기화와 기동

```bash
cd /home/newuser/Trihouse
```
```bash
scripts/p0_reset.sh
```
```bash
scripts/p0_up.sh
```

**지도는 `p0_reset.sh` 의 인자로 고른다.** 이름도 되고 yaml 경로도 된다.

```bash
scripts/p0_reset.sh                                                              # 기본 trihouse_map_01
```
```bash
scripts/p0_reset.sh new_map_2                                                    # 이름으로
```
```bash
scripts/p0_reset.sh /home/newuser/Trihouse/pinky_pro_alpha/pinky_navigation/map/new_map_2.yaml   # 경로로
```

이름을 주면 `pinky_pro_alpha/pinky_navigation/map/<이름>.yaml` 을 쓴다. 경로를 주면
그 파일을 쓰고, 이미지(`.pgm`/`.png`)는 ROS 지도 규약대로 **yaml 과 같은 디렉터리**에서
찾는다. 저장소 밖의 지도도 그대로 줄 수 있다.

**`p0_up.sh` 는 지도를 다시 묻지 않는다.** reset 이 `.trihouse/map_yaml` 에 적어 둔
경로를 그대로 Nav2 에 넘긴다. 없는 지도를 주면 reset 이 저장소의 목록을 보여 주고 멈춘다.

`p0_up.sh` 가 아래를 찍고 끝난다. **`판정 PASS` 가 아니면 더 내려가지 않는다.**

```text
Nav2 lifecycle 활성                2 (기대 2)
lifecycle 중단                     0 (기대 0)
FMS command claim 실패             0 (기대 0)
라이다 발행자                      있음 (기대 있음)

[up] 판정 PASS — 터미널 2(tf_relay), 3(rviz2) 로 넘어가세요.
```

이 창은 이제 닫아도 된다. bringup 은 `setsid` 로 떠 있다.
진행을 보려면 `tail -f /tmp/sim.log` (Ctrl+C 해도 시뮬은 산다).

`scripts/p0_reset.sh` 는 **`trihouse_fms` 데이터베이스를 지우고 seed 로 다시 만든다.**
회차마다 이렇게 되돌리는 이유는 [아래](#왜-매번-초기화하는가)에 적었다.

### 터미널 2 — TF relay (**닫지 말 것**)

```bash
cd /home/newuser/Trihouse && source /opt/ros/jazzy/setup.bash && source install/setup.bash && source pinky_pro/install/setup.bash && export ROS_DOMAIN_ID=0
```
```bash
python3 scripts/tf_relay.py pinky_01
```

nav2 는 `-r /tf:=tf` 로 뜨므로 TF 가 `/pinky_01/tf` 에만 있다. 전역 `/tf` 에
`map -> odom` 이 없으면 RViz 가 `Frame [map] does not exist` 를 낸다.
**로봇 두 대에 relay 두 개를 돌리면 전역 `/tf` 에 같은 프레임이 두 번 들어간다.
관측할 때만, 한 대에만 쓴다.**

### 터미널 3 — RViz (**닫지 말 것**)

```bash
cd /home/newuser/Trihouse && source /opt/ros/jazzy/setup.bash && source install/setup.bash && source pinky_pro/install/setup.bash && export ROS_DOMAIN_ID=0
```
```bash
rviz2 -d control_tower/bringup/p0_sim.rviz
```

| 항목 | 값 |
|---|---|
| Fixed Frame | `map` |
| Map 토픽 | `/pinky_01/map` (Durability: **Transient Local**) |
| RobotModel | TF Prefix `pinky_01` |
| Map 크기 | 고른 지도와 맞아야 한다 — `trihouse_map_01` 이면 **44 × 54 / 0.05**, `new_map_2` 면 **73 × 89 / 0.03**. 다르면 발행한 지도와 도는 지도가 갈라진 것이니 멈춘다 |

`pinky_01/caster_rotate_link`, `pinky_01/caster_wheel` 의 Status Error 는 URDF 에
해당 메시가 없어서이고 주행과 무관하다. **Gazebo 창은 뜨지 않는 것이 정상이다** —
bringup 이 `gz sim -s --headless-rendering` 으로 서버만 띄운다. 굳이 보려면 새 창에서
`source /opt/ros/jazzy/setup.bash && gz sim -g` (렌더링 부하로 RTF 가 떨어진다).

### 터미널 4 — 판정 → 주문 → 완주

```bash
cd /home/newuser/Trihouse && source /opt/ros/jazzy/setup.bash && source install/setup.bash && source pinky_pro/install/setup.bash && export ROS_DOMAIN_ID=0
```
```bash
python3 scripts/verify_robot_status.py pinky_01 20
```

| 항목 | 기대값 | 아니면 |
|---|---|---|
| `publishers` | 전부 **1** | 이전 세대가 남았다. **2 이상이면 그 아래 숫자는 전부 못 믿는다** — 터미널 1 부터 다시 |
| 판정 | **`RESULT: PASS`** | `errors` 를 읽는다 |

`amcl_pose: (없음)` 은 정지 상태에서 정상이다. `frame_id: map` 이면 AMCL 이 수렴한 것이다.

주문을 넣고 `job_id` 를 변수에 담는다. 두 줄을 차례로 실행한다.

```bash
ORDER=$(curl -s -X POST http://127.0.0.1:8080/api/v1/orders -H 'Content-Type: application/json' -H "Idempotency-Key: b-run-$(date +%s)" -d '{"requested_by":"W-OP-01","priority":"normal","items":[{"product_code":"SKU-PORKBELLY","quantity":1}]}')
```
```bash
echo "$ORDER" | python3 -m json.tool && export JOB=$(echo "$ORDER" | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])') && echo "JOB=$JOB"
```

`JOB=2` 처럼 숫자가 찍혀야 한다. 초기화 직후라면 seed 의 job 1 다음인 2 다.

**주행 측정** — step 20 이 `running` 이 된 뒤. 로그의 성공 문구가 아니라 이 값으로 판단한다.

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

| 결과 | 뜻 |
|---|---|
| `cmd_vel 0` | **발행자가 없다.** 0 값이 오는 것과 다르다. `safety_supervisor` 를 확인한다 |
| `cmd_vel N / 움직임 0` | 발행자는 있는데 값이 0 — 목표가 없거나 안전 gate 가 막고 있다 |
| `움직임 > 0`, `이동 > 0` | 실제로 주행 중 |

**사람 확인** — step 60 (`fms/wait`) 에서 멈췄을 때. 이것이 없으면 영원히 기다린다.
**이 호출은 실물 재고를 확정하며 되돌릴 수 없다.**

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/jobs/$JOB/worker-completion -H 'Content-Type: application/json' -H "Idempotency-Key: worker-completion-$JOB" -d '{"worker_id":"W-OP-01","completion_note":"manual B-run"}' | python3 -m json.tool
```

409 `MANUAL_ACKNOWLEDGEMENT_REQUIRED` 가 오면 응답의 `item_ids` 를 그대로 넣어 다시 부른다.

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/jobs/$JOB/worker-completion -H 'Content-Type: application/json' -H "Idempotency-Key: worker-completion-$JOB-ack" -d '{"worker_id":"W-OP-01","acknowledged_manual_item_ids":[<응답의_ID>]}' | python3 -m json.tool
```

**완주 판정**

```bash
docker exec trihouse-mysql mysql -uroot -p"$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)" --table -e "SELECT job_id,state FROM trihouse_fms.jobs WHERE job_id=$JOB; SELECT step_no,action_type,state,final_outcome_reason_code FROM trihouse_fms.job_steps WHERE job_id=$JOB ORDER BY step_no;"
```

**7 단계가 모두 `succeeded` 이고 job 이 `completed` 이면 한 사이클 완주다.**

### 터미널 5 — 진행 관측

```bash
cd /home/newuser/Trihouse && export JOB=$(docker exec trihouse-mysql mysql -uroot -p"$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)" -N -B -e "SELECT job_id FROM trihouse_fms.jobs ORDER BY job_id DESC LIMIT 1;") && echo "JOB=$JOB"
```
```bash
watch -n2 'docker exec trihouse-mysql mysql -uroot -p"$(grep -E "^MYSQL_ROOT_PASSWORD=" /home/newuser/Trihouse/.env | cut -d= -f2-)" --table -e "SELECT s.step_no,s.executor_type,s.action_type,s.state,IFNULL(m.channel,\"-\") ch,IFNULL(m.state,\"-\") outbox FROM trihouse_fms.job_steps s LEFT JOIN trihouse_fms.integration_messages m ON m.job_step_id=s.job_step_id WHERE s.job_id='"$JOB"' ORDER BY s.step_no;" 2>/dev/null'
```

`outbox` 가 `dead_letter` 가 되면 그 step 은 회복되지 않는다. 재투입 API 는 없다.

---

## 지도 선택

| 지도 | 크기 · 해상도 | 상태 |
|---|---|---|
| **`trihouse_map_01`** (기본) | 44 × 54 px @ 0.05 → 2.20 × 2.70 m | waypoint 실측 기록의 `source_map_name` 이 이것이다. bringup 의 기본값이기도 하다 |
| `new_map_2` | 73 × 89 px @ 0.03 → 2.19 × 2.67 m | 같은 방을 다시 SLAM 한 것. 좌표를 이 지도 위에서 다시 재지 않았다 |

**발행한 지도와 Nav2 가 도는 지도는 반드시 같아야 한다.** 좌표는 지도마다 다른 프레임
위의 값이라, 갈라지면 로봇이 "도착했다"고 말하는 자리와 원장이 아는 자리가 어긋나
도착 판정이 구조적으로 실패한다. 그래서 두 스크립트가 한 곳(`.trihouse/map_yaml`)을
공유한다.

```text
scripts/p0_reset.sh [지도이름 | yaml경로]
   ├─ 그 yaml + 이미지 + 실측 JSONL 을 FMS 에 발행
   └─ yaml 의 절대 경로를 .trihouse/map_yaml 에 기록
scripts/p0_up.sh
   └─ .trihouse/map_yaml 을 읽어 그대로 TRIHOUSE_NAV2_MAP 으로 넘김
```

두 스크립트 모두 시작할 때 어떤 지도를 쓰는지 이름과 전체 경로를 함께 출력한다.
`p0_up.sh` 를 먼저 돌리면 `.trihouse/map_yaml` 이 없어 멈춘다.

`new_map_2.pgm` 은 **확장자만 `.pgm` 이고 내용은 PNG** 다. 배포 검증기가 확장자로
파서를 고르므로 그대로 올리면 `SLAM_IMAGE_INVALID` 가 난다. `p0_publish_map.py` 가
파일의 magic bytes 로 형식을 판별해 올릴 이름과 yaml 의 `image` 필드를 맞춰 주므로
저장소 파일은 건드리지 않는다.

---

## 절대 규칙

- **job 하나가 끝나기 전에 새 주문을 넣지 않는다.** 로봇이 `PK_01` 한 대뿐이라 두 job 이
  동시에 배정되면 fleet adapter 가 `FMS command claim 실패: 409` 를 초당 수백 번
  반복한다. 2026-08-19 에 이것으로 `/tmp/sim.log` 가 17 만 줄을 넘었다.
- **막히면 손으로 풀지 말고 `scripts/p0_reset.sh` 부터 다시 한다.** job 취소로는
  재고 예약도 RMF task 도 회수되지 않는다.
- **다른 창에서 `scripts/sim_teardown.sh` 를 돌리지 않는다.** 터미널 1 의 bringup 이
  함께 죽는다(`p0_simulation_bringup` 이 kill 패턴에 있다).
- **판정은 로그의 성공 문구가 아니라 측정값으로 한다.** bringup 은 하위 launch 가
  죽어도 "올라왔습니다" 를 출력한다.

---

## 왜 매번 초기화하는가

회차를 거듭하면 상태가 쌓여 다음 회차가 앞 회차와 달라진다.

| 남는 것 | 결과 |
|---|---|
| **재고 예약** — job 을 취소해도 돌아오지 않는다 (D2, 미수정) | 두 번 취소하면 `SKU-PORKBELLY` 2 개가 모두 잠겨 새 주문이 배정되지 않는다. 주문을 넣어도 **아무 일도 일어나지 않는다** |
| 실패한 step 을 가진 job 이 `assigned` 로 남음 | 로봇을 쥔 채라 다음 job 이 `no free robot` 으로 막힌다 |
| RMF dispatcher 에 살아 있는 task | FMS job 을 취소해도 남아 `claim 409` 무한 루프를 만든다 |

`scripts/p0_reset.sh` 가 DB 를 `db/migrations/001_physical_v1_baseline.sql` + `db/seeds/seed_dev.sql` 로 되돌리고
지도를 다시 발행해 이 셋을 한 번에 없앤다.

지도 revision 은 **`scripts/p0_up.sh` 가 원장(`map_revisions` 테이블)에서 직접
읽는다.** 해시를 손으로 옮겨 적지 않는다. 두 번 데였다 — 자리표시자
`<발행된_해시>` 를 그대로 export 해 bringup 이 첫 줄에서 죽었고, 파일에 적어 둔 값이
재발행 뒤 한 세대 뒤처져 `발행된 지도 revision 이 요청과 다릅니다` 로 죽었다.

---

## 막혔을 때

### 먼저 볼 것 — 세 줄

**① 10~70 중 어디서 멈췄나.** 원장을 HTTP 로 읽으므로 docker 권한이 없어도 된다.

```bash
export JOB=$(curl -s http://127.0.0.1:8080/api/v1/jobs | python3 -c 'import sys,json;print(max(j["job_id"] for j in json.load(sys.stdin)))') && echo "JOB=$JOB"
```
```bash
curl -s http://127.0.0.1:8080/api/v1/jobs/$JOB | python3 -c '
import sys, json
j = json.load(sys.stdin)
print("job %s  state=%s" % (j["job_id"], j["state"]))
for s in j["steps"]:
    r = s.get("result") or {}
    print("  %-4s %-7s %-13s %-11s %-22s %s" % (
        s["step_no"], s["executor_type"], s["action_type"], s["state"],
        r.get("reason_code") or "", s.get("rmf_task_id") or ""))'
```

```text
job 2  state=assigned
  10   arm     pick          succeeded   PICK_CONFIRMED
  20   mobile  navigate      cancelled                          compose.dispatch-84cfafbbf5
  30   fms     load          pending
```

끝난 step 은 `result.reason_code` 가, `mobile` step 은 마지막 칸에 RMF task id 가
찍힌다. **실패한 step 의 `result` 는 대개 `null` 이다** — 이유는 원장이 아니라 로그에
있다. 그래서 ②③ 이 필요하다.

**`pending` 이 아닌 마지막 줄이 실패 지점이다.** 그 아래가 전부 `pending` 인데 job 이
`assigned` 로 남아 있으면 러너가 그 자리에서 영원히 막혀 있는 것이다.

**② 에러를 종류별로 접는다.** 그냥 `tail` 하면 초당 수백 줄인 `claim 실패` 가 화면을
다 먹어 진짜 원인이 위로 밀려난다. 개수까지 함께 보인다.

```bash
grep -aE '\[(ERROR|WARN)\]' /tmp/sim.log | sed -E 's/\[[0-9]{9,}\.[0-9]+\]//' | sort | uniq -c | sort -rn | head -25 | cut -c1-190
```

**③ 되풀이되는 두 줄을 빼고 시간순으로 읽는다. 인과는 여기 다 보인다.** 로그 시각은
epoch 이라 `awk` 로 시:분:초로 바꾼다.

```bash
grep -aE '\[(ERROR|WARN)\]' /tmp/sim.log | grep -av 'claim 실패\|job runner blocked' | awk '{ if (match($0, /[0-9]{10}\.[0-9]+/)) { sub(/[0-9]{10}\.[0-9]+/, strftime("%H:%M:%S", substr($0, RSTART, 10))) } print }' | tail -40 | cut -c1-200
```

```text
12:10:43 [controller_server]  RegulatedPurePursuitController detected collision ahead!
12:11:08 [controller_server]  Failed to make progress
12:11:08 [pinky_easy_fleet_adapter] Requesting replan ... command handle seems to be unresponsive
12:11:08 [pinky_easy_fleet_adapter] [PK_01] navigation canceled     ← step 20 이 여기서 죽었다
```

**④ 로그에 없는 것 — 안전 gate.** `safety_supervisor` 는 `cmd_vel_nav` 를 받아
`cmd_vel` 로 내보내는 **마지막 관문**인데 아무것도 로그에 찍지 않는다. STOP 이 걸려도
Nav2 의 목표를 취소하지 않으므로([policy.py](../../trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/policy.py))
`Passing new path to controller` 만 1 초마다 반복되고 로봇은 가만히 있는다.
**로봇이 안 움직이는데 로그가 조용하면 여기부터 본다.**

```bash
timeout 12 ros2 topic echo --once /pinky_01/trihouse/safety/state
```

| `state` | `detail` | 뜻 |
|---|---|---|
| 0 | `clear` | 통과 |
| 1 | `person_slow` 등 | 감속 |
| **2** | **`front_stop`** | 전방 통로에 0.30 m(`stop_distance_m`) 안쪽으로 무언가 있다. **속도가 0 으로 눌린다** |
| 3 | — | 비상 latch. `ClearEmergency` 없이는 안 풀린다 |

`front_stop` 이면 실제로 얼마나 남았는지 잰다. 2.20 × 2.70 m 방이라 벽을 마주 보면
0.30 m 는 쉽게 깨진다.

```bash
timeout 20 python3 -c "
import rclpy, time
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from trihouse_pinky_safety.geometry import (
    forward_path_distance, nearest_range,
    SCAN_FORWARD_OFFSET_RAD, SCAN_ORIGIN_OFFSET_X_M, PROTECTIVE_HALF_WIDTH_M)
rclpy.init(); n=Node('probe'); d={}
n.create_subscription(LaserScan,'/pinky_01/scan',lambda m: d.__setitem__('s',m),10)
e=time.monotonic()+10
while rclpy.ok() and time.monotonic()<e and 's' not in d: rclpy.spin_once(n,timeout_sec=0.2)
m=d['s']
sh=dict(angle_min=m.angle_min, angle_increment=m.angle_increment,
        range_min=m.range_min, range_max=m.range_max,
        forward_offset_rad=SCAN_FORWARD_OFFSET_RAD, origin_offset_x_m=SCAN_ORIGIN_OFFSET_X_M)
print('전방 통로 %.3f m (stop_distance_m 0.30)' % forward_path_distance(m.ranges, half_width_m=PROTECTIVE_HALF_WIDTH_M, **sh))
print('최근접   %.3f m' % nearest_range(m.ranges, **sh))
n.destroy_node(); rclpy.shutdown()"
```

### 더 파고들 때

```bash
grep -an '<문구>' /tmp/sim.log | head -3 | cut -c1-200
```
그 종류가 **처음** 난 줄번호. 반복하는 에러는 마지막이 아니라 첫 줄이 원인 근처다.

```bash
sed -n '640,680p' /tmp/sim.log | cut -c1-200
```
그 줄번호 앞뒤를 `INFO` 까지 포함해 읽는다. 무엇이 죽기 직전에 무엇을 했는지가 여기 있다.

```bash
tail -f /tmp/sim.log | grep -a --line-buffered -E '\[(ERROR|WARN)\]' | grep -av --line-buffered 'claim 실패\|job runner blocked'
```
실시간으로 같은 필터를 건다. Ctrl+C 해도 시뮬은 산다.

```bash
grep -ac 'FMS command claim 실패' /tmp/sim.log; ls -la /tmp/sim.log
```
`claim 실패` 가 만 단위이거나 로그가 수십 MB 면 이미 [409 루프](#절대-규칙)에 빠진 것이다.

**로그의 `step 3` 은 `step_no` 가 아니라 `job_step_id` 다**
([job_runner.py:242](../../control_tower/task_manager/job_runner.py#L242)).
10/20/…70 과 다른 번호이니 ① 의 표와 대조해서 읽는다.

### 증상별

| 증상 | 원인 · 조치 |
|---|---|
| `[up] 발행된 지도 revision 이 없습니다` | 원장에 `published` 인 지도가 없다. `scripts/p0_reset.sh` 부터 |
| `[up] .trihouse/map_yaml 이 없습니다` | 지도를 발행한 적이 없다. `scripts/p0_reset.sh [지도이름\|경로]` 부터 |
| `발행된 지도 revision 이 요청과 다릅니다` | bringup 을 `p0_up.sh` 없이 손으로 띄웠고 넘긴 해시가 옛것이다. `p0_up.sh` 를 쓴다 |
| `pinky_pro 워크스페이스가 빌드되어 있지 않습니다` | [전제 조건](#전제-조건-한-번만) 의 colcon 빌드를 안 했다 |
| `Managed nodes are active` 가 **1** | Nav2 navigation lifecycle 이 중단됐다. 대개 라이다가 없어 AMCL 이 `map -> odom` 을 못 낸 것이다. `gz topic -i -t /pinky_01/scan` 에 Publishers 가 있는지 본다 |
| 주문을 넣어도 job 이 안 생김 | 재고 예약이 잠겼다(D2). `scripts/p0_reset.sh` |
| `job runner blocked: job 1: no assignment and not an order` | seed 의 job 1 이다. 로봇을 쥐지 않으므로 **무시해도 된다** |
| `job runner blocked: no free robot` | 앞선 job 이 로봇을 쥐고 있다. `scripts/p0_reset.sh` |
| `FMS command claim 실패: 409` 반복 | 두 job 이 한 로봇을 두고 경합한다. `scripts/p0_reset.sh` |
| `FMS command claim 실패: 404` 반복 | 원장에 없는 task 를 claim 하고 있다. `pinky_fleet.yaml` 의 `finishing_request` 가 `"nothing"`, `responsive_wait` 가 `false` 인지 확인 |
| `Passing new path to controller` 만 1 초마다 반복되고 로봇이 안 움직인다 | 안전 gate 가 `front_stop` 으로 속도를 0 으로 누르고 있다. STOP 은 Nav2 목표를 취소하지 않아 겉으로는 주행 중처럼 보인다. **④** 로 확인한다. 10 초 뒤 Nav2 의 `SimpleProgressChecker`(0.5 m / 10 s)가 `Failed to make progress` 로 끝낸다 |
| step 20 이 `cancelled`, `job runner blocked: job N: step M is cancelled` 반복 | Nav2 가 주행을 포기했다. ③ 으로 거슬러 오르면 `collision ahead` → `Controller patience exceeded` → `Failed to make progress` → `navigation canceled` 가 차례로 보인다. 좁은 통로에 걸렸거나 RTF 가 낮은 것이다. **취소된 step 을 되살리는 경로는 없다** — `scripts/p0_reset.sh` |
| `GOAL_TOLERANCE_NOT_MET` | 로봇의 실제 정지 좌표와 목표 좌표를 함께 뽑아 오차의 방향·크기를 본다. 허용오차는 `fleet_node.py` 의 `PRECISE_STOP_XY_TOLERANCE_M` |
| `Unable to replan assignments` | 순간 안전정지가 로봇을 fleet 에서 빼냈다(D15, 미수정). RTF 가 낮으면 잦다 |
| 시뮬이 이유 없이 죽음 | **다른 창이 teardown 을 돌렸다.** `ps -eo args \| grep claude` |

### job 을 닫고 다시 시작 (초기화 없이)

`reason` 과 `requested_by` **둘 다 필수**다. **취소는 재고 예약을 돌려주지 않으므로**
같은 SKU 로 다시 주문할 생각이면 초기화가 낫다.

```bash
curl -sS -X POST http://127.0.0.1:8080/internal/v1/jobs/$JOB/cancel -H 'Content-Type: application/json' -H "Idempotency-Key: manual-cancel-$JOB" -d '{"reason":"<사유>","requested_by":"W-OP-01"}' | python3 -m json.tool
```

30 초 뒤 `cancelled` 로 남아 있는지 확인한다. `assigned` 로 돌아가면 러너가 되살린 것이다.

---

## 전제 조건 (한 번만)

새로 설치한 PC 에서만 한다. 이미 되어 있으면 건너뛴다.

```bash
sudo apt install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"      # 로그아웃 후 다시 로그인
```

```bash
sudo apt install -y \
  ros-jazzy-rmf-fleet-msgs ros-jazzy-rmf-fleet-adapter \
  ros-jazzy-rmf-task-ros2 ros-jazzy-rmf-traffic ros-jazzy-rmf-traffic-ros2 \
  ros-jazzy-rmf-battery \
  ros-jazzy-navigation2 ros-jazzy-nav2-bringup ros-jazzy-tf-transformations
```

`.env` 를 만든다. `.env.example` 을 복사해 두 DB 비밀번호와 `MTX_VIEWER_PASS` 를 바꾼다.
시뮬 전용 호스트라면 `PC1_LAN_IP=127.0.0.1` 로 둔다.

**워크스페이스 두 개를 빌드한다. 순서가 중요하다** — `pinky_pro` 를 먼저 빌드하고
source 한 뒤 루트를 빌드한다.

```bash
cd /home/newuser/Trihouse/pinky_pro && source /opt/ros/jazzy/setup.bash && colcon build --symlink-install
```
```bash
cd /home/newuser/Trihouse && source /opt/ros/jazzy/setup.bash && source pinky_pro/install/setup.bash && colcon build --symlink-install --packages-select trihouse_interfaces trihouse_rmf_bridge trihouse_pinky_bringup trihouse_pinky_fleet trihouse_pinky_safety trihouse_omx_adapter
```

---

## 이 PC 에서 고친 것

원본 런북이 쓰인 서버 PC 와 다른 점, 그리고 여기서 막혀 고친 것들의 기록이다.

| 항목 | 내용 |
|---|---|
| 경로 | `/home/syw/Trihouse` → `/home/newuser/Trihouse` |
| Gazebo 센서가 생기지 않음 | `pinky.urdf.xacro` 는 **joint 에만** namespace 를 붙이는데 `pinky_gz.urdf.xacro` 는 링크를 `${namespace}rplidar_link` 로 참조한다. 가리키는 링크가 없어 sdformat 이 `<gazebo>` 블록을 **조용히 버려** 라이다·IMU·카메라가 생성되지 않았다. `pinky_pro` 는 고정된 서브모듈이라, `two_pinky_order_demo.launch.py` 의 `_robot_description()` 이 xacro 를 펼친 뒤 **링크를 가리키는 참조만** 접두사를 벗긴다 |
| `GOAL_TOLERANCE_NOT_MET` | 정밀 정차 허용오차가 Nav2 의 goal tolerance 와 **같아서**(둘 다 0.10 m) 경계선 동전 던지기가 됐다. Nav2 는 허용오차 안에 들어오는 순간 멈추므로 로봇은 늘 경계에 선다. `0.15 m / 0.35 rad` 로 넓혔다 |
| 지도 | 원본 B절 런북은 `TRIHOUSE_NAV2_MAP` 으로 `new_map_2` 를 덮어쓰지만 **발행하는 지도는 바꾸지 않아** 둘이 갈라진다. 여기서는 `p0_reset.sh` 의 인자 하나로 양쪽을 함께 정한다. 기본은 `trihouse_map_01` — [지도 선택](#지도-선택) |

현재 구성과 컴포넌트 경계는 [시스템 구성](../architecture/system_overview.md)과
[환경 개요](../deployment/environment_overview.md)를 따른다.
