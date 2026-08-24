# 4060 서버 PC 운영 테스트 실전 가이드 (PK_01)

2026-08-24 실기 시험에서 실제로 친 명령과, 막혔던 지점 19개를 그대로 담았다.
**우리 장비의 IP 와 경로를 그대로 적는다.** 다른 현장에 그대로 쓰라고 만든
문서가 아니다.

---

## 1. 장비·주소·경로 정본

| 항목 | 값 |
| --- | --- |
| 4060 서버 PC hostname | `cook2` |
| 4060 LAN IP | **`192.168.0.4`** (인터페이스 `wlo1`, Wi-Fi) |
| 4060 OS / 커널 | Ubuntu 24.04.4 LTS / 7.0.0-30-generic |
| 4060 GPU | NVIDIA GeForce RTX 4060 Laptop, driver 580.173.02, 8188 MiB |
| 작업 경로 | **`/home/newuser/Trihouse/.worktrees/physical-integration-v1`** |
| Pinky PK_01 | **`192.168.0.21`** (계정 `pinky`, hostname `raspi`) |
| Pinky PK_02 | `192.168.0.22` |
| OMX_01 팔 PC | `192.168.0.31` — **2026-08-24 시험 당시 응답 없음** |
| OMX_02 팔 PC | `192.168.0.32` |
| ROS domain | `12` |
| Fast DDS Discovery Server | **`192.168.0.4:11811`** |
| FMS API | **`http://192.168.0.4:8080`** |
| FMS TCP (로봇 gateway) | **`192.168.0.4:8788`** |
| MySQL (운영 DB) | `127.0.0.1:3308` → 컨테이너 `trihouse-mysql` |
| RMF dashboard | `http://127.0.0.1:3000` |
| RMF API (인증 필요) | `http://127.0.0.1:8000` |
| MediaMTX RTSP | `127.0.0.1:8554` |
| 지도 | `new_map_2` |
| **published map revision** | `new_map_2:2419810c3f013a648f46da995aa33b6f8ba20154cf297c26932959a599898589` |

### 로봇 쪽 경로

| 항목 | 경로 |
| --- | --- |
| workspace | `/home/pinky/trihouse_ws` |
| 벤더 스택 | `/home/pinky/pinky_pro/install` |
| 지도 | `/home/pinky/map/new_map_2.yaml` (+ `.pgm`) |
| Nav2 파라미터 | `/home/pinky/hardware_pinky_01.yaml` |
| 협로 설정 | `/home/pinky/narrow_zones.new_map_2.yaml` |
| bringup 로그(이번 시험) | `/home/pinky/ops_test_20260824_bringup4.log` |

### 4060 쪽 로그 경로

| 대상 | 경로 |
| --- | --- |
| 시험 기록 | `log/ops_test_2026-08-24/session.md` |
| 위치 추적 CSV | `log/ops_test_2026-08-24/pk01_track.csv` |
| job runner | `/tmp/trihouse_job_runner.log` |
| executor worker | `/tmp/trihouse_executor_worker.log` |
| rmf gateway worker | `/tmp/trihouse_rmf_gateway_worker.log` |
| fleet adapter | `/tmp/trihouse_pinky_fleet_adapter.log` |
| 배터리 게이트 우회 | `/tmp/trihouse_battery_override.log` |
| Discovery Server | `/tmp/trihouse_discovery_server.log` |

### 지도 좌표 정본 (DB `locations`, map `new_map_2`)

| location_code | rmf_waypoint_name | x | y | yaw |
| --- | --- | --- | --- | --- |
| WH-AMB-01-DOCK-01 | `ambient_storage_loading_dock_01` | 1.234 | 0.743 | 2.255 |
| WH-CHL-01-DOCK-01 | `chilled_storage_loading_dock_01` | 1.260 | 0.193 | −2.258 |
| WH-FRZ-01-DOCK-01 | `frozen_storage_loading_dock_01` | 1.3315 | −0.8149 | −1.57214 |
| PACKING-01-DOCK-01 | `packing_station_loading_dock_01` | 0.351 | −0.490 | 0.231 |
| PACKING-01-DOCK-02 | `packing_station_loading_dock_02` | 0.351 | −1.017 | 0.231 |
| TRIHOUSE-TEST-01-CHG-01 | `charging_station_01` | 0.0570 | 0.1950 | 0.1093 |
| TRIHOUSE-TEST-01-CHG-02 | `charging_station_02` | 0.1337 | −0.0066 | 0.1570 |
| TRIHOUSE-TEST-01-CHG-EXIT | `charging_station_narrow_exit` | 0.7993 | 0.0854 | 0.0924 |
| WH-AMB-01-NARROW-ENTRY | `ambient_storage_narrow_entry` | 1.0102 | 0.9167 | −0.0868 |
| WH-CHL-01-NARROW-ENTRY | `chilled_storage_narrow_entry` | 1.1013 | −0.1005 | 3.1029 |
| WH-FRZ-01-NARROW-ENTRY | `frozen_storage_narrow_entry` | 1.1793 | −1.1897 | 0.0109 |

`devices.home_location_id`: PK_01 → 19 (`charging_station_01`), PK_02 → 20.

**지도 범위** — `new_map_2.pgm` 은 73 × 89 셀, 해상도 0.03 m, origin `(-0.22, -1.473)`.
따라서 x `−0.22 ~ 1.97`, y `−1.473 ~ 1.197`.
**추적 CSV 의 pose 가 이 범위를 벗어나면 AMCL 이 발산한 것이다. 즉시 정지시킨다.**

### 시험 재고 SKU

| 구역 | SKU |
| --- | --- |
| 상온 | `SKU-MANDARIN`, `SKU-ORANGE`, `SKU-STRAWBERRY` |
| 냉장 | `SKU-SANDWICH`, `SKU-MILK`, `SKU-YOGURT`, `SKU-COFFEE` |
| 냉동 | `SKU-PORKBELLY`, `SKU-ICEBAR`, `SKU-ICECONE`, `SKU-DUMPLING` |

---

## 2. 명령이 흐르는 경로

주문 하나가 로봇 바퀴까지 가는 길을 알아야 어디서 막혔는지 읽을 수 있다.

```
POST /api/v1/orders            (4060 Docker: fms_gateway)
  └─ job_runner_node           (4060 호스트) job 을 7 step 으로 쪼갠다
       ├─ step 10 arm    OMX_01  prepare       → omx 채널 outbox
       └─ step 20 mobile PK_01   navigate      → rmf 채널 outbox
            └─ rmf_gateway_worker_node (4060 호스트)
                 └─ rmf_task_dispatcher (4060 호스트)  입찰
                      └─ pinky_easy_fleet_adapter (4060 호스트)
                           └─ /pinky_01/trihouse/transport/execute  (Action)
                                └─ fleet_node (로봇)
                                     ├─ 일반 구간: NavigateToPose → Nav2 → /pinky_01/cmd_vel
                                     └─ 협로 구간: 규칙 제어 → /pinky_01/cmd_vel_dock
                                          └─ safety_supervisor → /pinky_01/cmd_vel_safe → 모터
```

step 30(적재)은 **step 10 과 20 이 둘 다 성공해야** 열린다. 그다음 40(포장대) →
50(인계) → 60(대기) → 70(충전소 복귀) 가 직렬로 이어진다.

```sql
SELECT step_no, JSON_EXTRACT(input,'$.dependencies') FROM job_steps WHERE job_id=<ID>;
-- 10 []        omx_prepare
-- 20 []        pinky_navigate
-- 30 [10, 20]  readiness_load_gate
-- 40 [30]      packing_navigate
-- 50 [40]  60 [50]  70 [60]
```

**따라서 OMX 가 없으면 로봇은 창고 도크에서 멈추고 포장대·충전소로 가지 않는다.**

---

## 3. 기동 절차

### 3-1. Docker (운영 DB + Gateway)

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1

# .env 의 과거 IP 가 남아 있으면 존재하지 않는 주소에 bind 하려다 실패한다.
# 현재 호스트 IP 를 명시한다.
export FMS_API_HOST='192.168.0.4'
export FMS_TCP_BIND='192.168.0.4'

FMS_API_HOST="$FMS_API_HOST" FMS_TCP_BIND="$FMS_TCP_BIND" \
docker compose -p trihouse_p0 \
  -f compose.yaml -f compose.control.yaml \
  up -d mysql fms_gateway

until curl -fsS http://192.168.0.4:8080/ready > /dev/null; do sleep 2; done
echo 'PASS: FMS Gateway ready'

docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

운영 DB 는 `compose.yaml` 의 `trihouse-mysql` 이다. 시드가
`db/seeds/seed_hardware.sql`(실장비 시드)이며, `compose.db.yaml`(개발용,
`seed_dev.sql`)과 **다른 스택**이다. 혼동하지 않는다.

DB 직접 조회:

```bash
source .env
docker exec trihouse-mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -t \
  -e "SELECT job_id, job_code, state, assigned_mobile_id FROM jobs ORDER BY job_id DESC LIMIT 5;" \
  trihouse_fms
```

### 3-2. 4060 호스트 — 공통 환경

**모든 4060 터미널에서 매번 실행한다.**

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1

source /opt/ros/jazzy/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
unset ROS_STATIC_PEERS
unset FASTRTPS_DEFAULT_PROFILES_FILE
export FMS_API='http://192.168.0.4:8080'
```

> **Discovery Server 방식과 SUBNET 방식을 섞지 않는다.** 두 방식은 서로를
> 발견하지 못한다. 관제 워커가 Discovery Server 를 쓰므로 로봇도 반드시
> Discovery Server 로 띄운다.

### 3-3. Discovery Server

```bash
pgrep -af '[f]astdds discovery' || {
  setsid nohup fastdds discovery -i 0 -l 192.168.0.4 -p 11811 \
    > /tmp/trihouse_discovery_server.log 2>&1 < /dev/null &
}
sleep 3
pgrep -af '[f]astdds discovery'
ss -lunp | grep ':11811'
```

### 3-4. RMF core

```bash
setsid nohup ros2 launch trihouse_rmf_bridge rmf_core.launch.py \
  use_sim_time:=false start_visualization:=false \
  > /tmp/trihouse_rmf_core.log 2>&1 < /dev/null &
sleep 8
pgrep -af 'rmf_task_dispatcher|rmf_traffic_schedule|mutex_group_supervisor'
```

`rmf_task_dispatcher` 가 없으면 주문은 영원히 `RMF_ASSIGNMENT_PENDING` 이다.

### 3-5. fleet adapter — **namespace 를 반드시 붙인다**

```bash
MAP_REVISION='new_map_2:2419810c3f013a648f46da995aa33b6f8ba20154cf297c26932959a599898589'

setsid nohup ros2 launch trihouse_rmf_bridge pinky_easy_fleet_adapter.launch.py \
  nav_graph:="$PWD/.trihouse/p0/nav_graph.yaml" \
  robot_name:=PK_01 \
  rmf_map_name:=L1 \
  charger_waypoint:=charging_station_01 \
  map_revision:="$MAP_REVISION" \
  robot_status_topic:=/pinky_01/trihouse/status \
  transport_action:=/pinky_01/trihouse/transport/execute \
  fms_base_url:=http://192.168.0.4:8080 \
  use_sim_time:=false \
  > /tmp/trihouse_pinky_fleet_adapter.log 2>&1 < /dev/null &
```

**성공 로그 두 줄을 반드시 확인한다.**

```bash
grep -aE "adapter 시작|등록했습니다" /tmp/trihouse_pinky_fleet_adapter.log
# [PK_01] EasyFullControl adapter 시작: status=/pinky_01/trihouse/status, action=/pinky_01/trihouse/transport/execute
# [PK_01] 유효한 pose/SOC로 RMF에 등록했습니다.
```

두 번째 줄이 없으면 RMF fleet 에 로봇이 없는 것이고, 주문은 반드시 실패한다.

### 3-6. 관제 워커 3종

```bash
setsid nohup python3 -m control_tower.task_manager.job_runner_node \
  --fms-base-url "$FMS_API" --poll-interval-s 1 \
  >> /tmp/trihouse_job_runner.log 2>&1 < /dev/null &

setsid nohup python3 -m control_tower.task_manager.executor_worker_node \
  --fms-base-url "$FMS_API" --environment hardware --poll-interval-s 1 \
  >> /tmp/trihouse_executor_worker.log 2>&1 < /dev/null &

setsid nohup python3 -m control_tower.rmf_adapter.rmf_gateway_worker_node \
  --fms-base-url "$FMS_API" --fleet-name project1_pinky \
  --worker-id trihouse-rmf-worker --poll-interval-s 1 \
  >> /tmp/trihouse_rmf_gateway_worker.log 2>&1 < /dev/null &

sleep 3
pgrep -af 'control_tower\.'
```

**새 주문 전에 이 셋이 먼저 떠 있어야 한다.** 없으면 outbox 가 재시도 5회를
소진해 `dead_letter` 가 되고 주문은 자동으로 재개되지 않는다.

### 3-7. OMX (팔이 없을 때)

OMX PC 가 꺼져 있으면 `executor error: step NN: /omx_01/execute unavailable` 이
나고 step 30 이 열리지 않는다. 주행만 시험하려면 무동작 시뮬레이터로 대체한다.

```bash
export PYTHONPATH="$PWD/trihouse_omx_adapter:$PWD${PYTHONPATH:+:$PYTHONPATH}"

for omx in OMX_01 OMX_02; do
  node="$(echo "$omx" | tr '[:upper:]' '[:lower:]')"
  setsid nohup python3 -m tests.simulation.omx.action_server \
    --ros-args -r __node:="$node" -p device_id:="$omx" \
    > "/tmp/trihouse_omx_sim_${node}.log" 2>&1 < /dev/null &
done

# 중복 확인 — 같은 노드 이름이 두 벌 뜨면 안 된다
pgrep -af 'tests.simulation.omx.action_server'
```

> 이때 팔 동작은 **모의**다. 주행·협로·도킹·포장대·충전소 복귀는 실물이다.
> 결과를 적을 때 반드시 구분해 적는다.

### 3-8. 위치 추적기 (켜 두면 사후 분석이 가능해진다)

```bash
setsid nohup python3 scripts/ops_track_pinky.py \
  --namespace pinky_01 \
  --output log/ops_test_2026-08-24/pk01_track.csv \
  > /tmp/trihouse_ops_track.log 2>&1 < /dev/null &
```

실시간으로 보기:

```bash
tail -f log/ops_test_2026-08-24/pk01_track.csv | \
  awk -F, '{printf "%s  (%s, %s) yaw=%s°  %s %sm  %s  %s/%s\n", $1,$3,$4,$5,$6,$7,$8,$9,$10}'
```

### 3-9. 로봇 bringup

**로봇을 물리적으로 충전소에 놓는다.** `hardware_pinky_01.yaml` 의
`initial_pose` 가 `charging_station_01` 로 고정돼 있어, 다른 자리에서 띄우면
AMCL 이 처음부터 틀어진다.

```bash
ssh pinky@192.168.0.21 'sed -n "41,47p" /home/pinky/hardware_pinky_01.yaml'
#       set_initial_pose: true
#       initial_pose:
#         x: 0.0570244747
#         y: 0.1949666005
#         z: 0.0
#         yaw: 0.1093261667
```

기존 프로세스를 **완전히** 정리한다(정리 패턴은 6-15 참고).

```bash
ssh pinky@192.168.0.21 'bash -s' <<'REMOTE'
LOG=/home/pinky/ops_test_20260824_bringup4.log
: > "$LOG"
cd /home/pinky/trihouse_ws
source /opt/ros/jazzy/setup.bash
source /home/pinky/pinky_pro/install/setup.bash
source /home/pinky/trihouse_ws/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
unset ROS_STATIC_PEERS
unset FASTRTPS_DEFAULT_PROFILES_FILE
MAP_REVISION='new_map_2:2419810c3f013a648f46da995aa33b6f8ba20154cf297c26932959a599898589'
setsid nohup ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  namespace:=pinky_01 robot_id:=PK_01 \
  map:=/home/pinky/map/new_map_2.yaml \
  map_revision:="$MAP_REVISION" \
  nav2_params_file:=/home/pinky/hardware_pinky_01.yaml \
  lifecycle_bond_timeout_s:=60.0 navigation_start_delay_s:=60.0 \
  narrow_zones_file:=/home/pinky/narrow_zones.new_map_2.yaml \
  narrow_map_name:=new_map_2 allow_narrow_calibration:=true \
  control_host:=192.168.0.4 control_port:=8788 \
  vision_enabled:=false docking_enabled:=false \
  >> "$LOG" 2>&1 < /dev/null &
disown
REMOTE
```

navigation 은 60 초 지연 후 시작한다. 활성화 확인:

```bash
ssh pinky@192.168.0.21 'L=/home/pinky/ops_test_20260824_bringup4.log
until [ "$(grep -c "Managed nodes are active" "$L")" -ge 2 ]; do sleep 3; done
echo "lifecycle active = $(grep -c "Managed nodes are active" "$L")"'
```

협로 설정이 실제로 적재됐는지도 본다.

```bash
ssh pinky@192.168.0.21 'grep -a "협로 profile" /home/pinky/ops_test_20260824_bringup4.log'
# 협로 profile 4개 적재 (운영 가능 3개): ambient..., charging_narrow_departure, chilled..., frozen...
```

### 3-10. 주문 전 최종 확인

```bash
tail -1 log/ops_test_2026-08-24/pk01_track.csv | cut -d, -f3,4,5,6,7,8,9,10,12,13,18
# 0.0571,0.1950,6.1,charging_station_01,0.000,idle,clear,clear,1,1,
#  x      y      yaw  최근접               거리   nav   safety  detail  ready dispatchable errors
```

**출발 조건**: 충전소 거리 `0.000`, safety `clear/clear`, `ready=1`,
`dispatchable=1`, `errors` 비어 있음.

---

## 4. 주문 넣고 감시하기

```bash
submit_order() {
  local zone="$1" sku="$2" run_id order_file
  run_id="$(date +%Y%m%d%H%M%S)"
  order_file="/tmp/trihouse-${zone}-order-${run_id}.json"
  curl -fsS -X POST "$FMS_API/api/v1/orders" \
    -H 'Content-Type: application/json' \
    -H "Idempotency-Key: ${zone}-live-${run_id}" \
    -d "{\"external_reference\":\"${zone^^}-LIVE-${run_id}\",\"priority\":\"normal\",\"allow_partial_fulfillment\":false,\"items\":[{\"product_code\":\"${sku}\",\"quantity\":1}]}" \
    | tee "$order_file" | python3 -m json.tool
  echo "ORDER_FILE=$order_file"
}

submit_order ambient SKU-MANDARIN     # 상온
submit_order chilled SKU-SANDWICH     # 냉장
submit_order frozen  SKU-PORKBELLY    # 냉동
```

**한 번에 한 주문만 넣는다.** 좌표를 직접 주지 않는다 — FMS 가 SKU 의
`temperature_zone` 으로 창고 도크와 포장대를 스스로 정한다.

감시:

```bash
JOB_ID=<위에서 나온 job_id>

watch -n 2 "curl -fsS '$FMS_API/api/v1/jobs/$JOB_ID' | python3 -c \"
import json,sys
d=json.load(sys.stdin)
print('job', d['state'])
for s in d['steps']:
    print(' ', s['step_no'], s['action_type'], s.get('assigned_device_id'), '->', s['state'], s.get('failure_reason') or '')
\""
```

한 줄 요약 + 위치를 같이 보려면:

```bash
for i in $(seq 1 30); do
  printf "t+%03ds  " $((i*10))
  curl -fsS "$FMS_API/api/v1/jobs/$JOB_ID" | python3 -c "
import json,sys; d=json.load(sys.stdin)
print(' '.join(f\"{s['step_no']}={s['state'][:4]}\" for s in d['steps']), end='  ')"
  tail -1 log/ops_test_2026-08-24/pk01_track.csv | cut -d, -f3,4,5,6,7,8,9,10
  sleep 10
done
```

### 정상 진행의 모습

```
t+010s  10=succ 20=pend ...   (0.0570, 0.1950)  charging_station_01   idle
t+024s  10=succ 20=runn ...   (0.7749, 0.1469)  charging_station_narrow_exit  navigating
t+036s  10=succ 20=runn ...   (0.8718, 0.7372)  ambient_storage_narrow_entry  navigating
```

어댑터 로그에 RMF 경유점이 하나씩 찍힌다.

```
[PK_01] RMF compose.dispatch-XXXX -> (0.799, 0.085, -1.146)
[PK_01] Pinky 도착·정지 확인 후 RMF 이동을 완료했습니다.
[PK_01] RMF compose.dispatch-XXXX -> (0.895, -0.126, 1.199)
```

---

## 5. 협로 좌표 실측과 검증

### 5-1. 좌표 찍기

```bash
python3 scripts/ops_read_pose.py --namespace pinky_01 --samples 20 --label entry
```

출력이 설정에 그대로 붙여넣을 형태로 나온다.

> **손으로 들어 옮긴 직후 값은 실측이 아니다.** 로봇을 들면 odometry 가 끊기는데
> AMCL 은 그것을 모르고 옮기기 전 좌표를 계속 보고한다. `initialpose` 로 씨앗을
> 뿌려도 AMCL 은 **스캔으로 찾지 않고 씨앗을 그대로 받아들인다** — 결과는
> 측정이 아니라 추측이다. 2026-08-24 에 이것으로 한 번 속았다.
>
> 산포로 구분한다. `x 산포 0.0000 m` 이면 AMCL 이 갱신되지 않은 것이니 믿지 않는다.
> `0.001 ~ 0.01 m` 이면 정상 수렴이다.
>
> **신뢰할 수 있는 경우는 로봇이 스스로 주행해 그 자리에 도달했을 때뿐이다.**

### 5-2. 배포

```bash
cp -a config/narrow_zones.new_map_2.yaml \
      config/narrow_zones.new_map_2.yaml.backup-$(date +%Y%m%d-%H%M%S)
# 편집 후
python3 -c "import yaml; yaml.safe_load(open('config/narrow_zones.new_map_2.yaml'))"
scp config/narrow_zones.new_map_2.yaml \
    pinky@192.168.0.21:/home/pinky/narrow_zones.new_map_2.yaml
sha256sum config/narrow_zones.new_map_2.yaml
ssh pinky@192.168.0.21 'sha256sum /home/pinky/narrow_zones.new_map_2.yaml'
```

**`fleet_node` 는 launch 때 이 파일을 읽는다. 배포 후 bringup 재기동이 필수다.**

### 5-3. 자기일관성 검증 — 넣기 전에 반드시 돌린다

```bash
python3 - <<'PY'
import math, yaml
d = yaml.safe_load(open('config/narrow_zones.new_map_2.yaml'))
for name, z in d['zones'].items():
    e, t, seq = z.get('entry'), z.get('dock_target'), z.get('enter')
    if not (e and t and seq): continue
    x, y, h = e['x'], e['y'], e['yaw']
    for op, v in seq:
        if op == 'rotate': h = v
        elif op == 'straight': x += v*math.cos(h); y += v*math.sin(h)
    enter_err = math.hypot(x - t['x'], y - t['y'])
    strat = 'warehouse_entry(전진)' if z.get('entry_passage') else 'legacy(회전→후진)'
    print(f"{name:<38} enter오차={enter_err:.10f} m  {strat}")
PY
```

`enter` 시퀀스를 적분한 값이 `dock_target` 과 맞아야 한다. **오차가 0 이 아니면
좌표나 시퀀스 중 하나가 틀린 것이다.** 2026-08-24 에 냉장이 1.025 m 어긋나
있었고 그것이 도킹 실패의 원인이었다.

### 5-4. 2026-08-24 기준 확정 좌표

```
ambient_storage_loading_dock_01
   entry       (1.010244055594586, 0.9167344977253539, -0.08675495954950327)   # -4.971 deg
   dock_target (1.293481094178777, 1.0156120986977553, -2.805721254488808)     # -160.756 deg
   enter  [rotate -2.805721254488808] [straight -0.30]
   exit   [straight 0.30] [rotate -3.130293455959265] [exit_zone]

chilled_storage_loading_dock_01
   entry       (1.101331522128124, -0.10045055614140724, 3.1029342608092607)   # 177.785 deg
   dock_target (1.3263418779273253, -0.2988701614809928, 2.4189105956431427)   # 138.593 deg
   enter  [rotate 2.4189105956431427] [straight -0.30]

frozen_storage_loading_dock_01
   entry       (0.9198039894575488, -1.1892528962848725, -0.03242978898931081) # -1.858 deg
   dock_target (1.036067117750, -0.933812857015, -0.9057963267948966)          # -51.898 deg
   enter  [straight 0.325] [rotate -0.9057963267948966] [straight -0.338]
```

세 구역 모두 `entry_passage` 없이 **회전 → 후진** 방식으로 통일했다.

---

## 6. 실제로 막혔던 지점 19개

### 6-1. `.env` 의 호스트 IP 가 실제와 다르다

`.env` 는 `PC1_LAN_IP=192.168.0.9` 인데 이 호스트의 실제 주소는 `192.168.0.4`
하나뿐이다. 재기동하면 존재하지 않는 주소에 bind 하려다 실패한다.

```bash
grep -n "PC1_LAN_IP\|FMS_API_HOST\|EDGE_BIND\|FMS_TCP_BIND" .env
docker inspect trihouse_p0-fms_gateway-1 --format '{{json .HostConfig.PortBindings}}'
```

→ 기동할 때 `FMS_API_HOST` / `FMS_TCP_BIND` 를 셸에서 명시한다(3-1 참고).
Compose 는 셸 환경 > `.env` 우선순위다.

### 6-2. MediaMTX 가 loopback 에만 bind

`127.0.0.1:8554` 로 떠 있으면 로봇(192.168.0.21)이 카메라를 발행하지 못한다.
`EDGE_BIND_ADDRESS` 를 LAN 주소로 준다. (`vision_enabled:=false` 로 시험하면 무관)

### 6-3. DDS discovery 방식이 갈린다

`SUBNET`(Discovery Server 없음)과 `SYSTEM_DEFAULT + ROS_DISCOVERY_SERVER` 는
**서로를 발견하지 못한다.** 로봇과 관제가 같은 방식이어야 한다. 실행 중인
프로세스의 실제 환경은 이렇게 확인한다.

```bash
tr '\0' '\n' < /proc/<PID>/environ | grep -i 'ROS_\|RMW\|FASTDDS'
```

### 6-4. `devices.fleet_name` 과 워커 `--fleet-name` 이 다르다

DB 는 `new_map_2_pinky`, 워커 기본값은 `project1_pinky`, 설정 파일
`trihouse_rmf_bridge/config/pinky_fleet.yaml` 도 `project1_pinky`.
**dispatch 는 payload 의 fleet_name 또는 워커 기본값을 쓰므로 실제 동작에는
영향이 없었다.** 혼란만 준다.

### 6-5. 가이드 문서의 map revision 이 폐기본

`docs/guides/pinky-ad-guideline.md` 는 `new_map_2:df9a7f70...` 를 적어 두었으나
그것은 `retired` 다. published 는 `new_map_2:2419810c...`.

```bash
curl -s http://192.168.0.4:8080/internal/v1/maps/new_map_2/published \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['map_revision'])"
```

### 6-6. 로봇 AMCL 초기 pose 가 충전소가 아니었다

`hardware_pinky_01.yaml` 의 `initial_pose` 가 직전 상온 calibration 잔재인
`(0.9117, 0.7759, yaw 0.8752)` 였다. 충전소 출발 시나리오에서는 1 m 가까이
틀어진 채 시작한다.

### 6-7. 협로 `measured` 플래그는 실측이 아니라 수동 개방이었다

정식 주문 경로를 열기 위해 손으로 `true` 로 바꾼 값이다. `git diff` 로 확인한다.

```bash
git diff config/narrow_zones.new_map_2.yaml
```

### 6-8. **fleet adapter 가 namespace 없는 토픽을 보고 있었다 (근본 원인)**

`--status-topic /trihouse/status` 로 떠 있어서 로봇 상태를 한 건도 못 받았고,
어댑터는 상태를 받아야 `add_robot` 을 하므로 fleet 에 로봇이 없었다.

```
[Bidder] Received Bidding notice for task_id [compose.dispatch-XXXX]
Fleet [project1_pinky] does not have any robots to accept task [...].
```

FMS 쪽에서는 `RMF_ASSIGNMENT_PENDING` → 5회 소진 → `DISPATCH_ATTEMPTS_EXHAUSTED`
→ `dead_letter` 로 보인다. **원인에서 세 단계 떨어진 증상이다.**
게다가 어댑터가 **두 벌** 떠 있었다. → 3-5 의 명령으로 하나만 띄운다.

### 6-9. OMX 없이는 포장대·충전소 복귀까지 못 간다

step 30 이 step 10 과 20 의 성공을 모두 요구한다. → 3-7.

### 6-10. **FMS job 취소가 RMF task 를 취소하지 않는다**

취소된 job 의 task 가 RMF 에 남아 계속 재배정되고, 어댑터는 `cancelled` 인
job_step 을 claim 하려다 409 를 받는다.

```
[PK_01] FMS command claim 실패: HTTP Error 409: Conflict
Replanning requested for [project1_pinky/PK_01]     ← 초당 수백 회
```

409 조건은 `fms_gateway/app/repositories.py:6407`:

```python
if step["state"] not in {"pending", "running"}:
    raise CommandClaimConflict
```

이 굶주림 고리 때문에 **새 주문이 영원히 `20=pending` 에 머문다.**

**새 주문 전에 반드시 정리한다.**

```bash
source .env
docker exec trihouse-mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e \
  "SELECT rmf_task_id FROM job_steps WHERE rmf_task_id IS NOT NULL AND state='cancelled';" \
  trihouse_fms

python3 scripts/ops_rmf_cancel_task.py <task_id> [<task_id> ...]
# 응답 ...: {"success":true}
```

RMF API(`127.0.0.1:8000`)는 인증이 걸려 있어 HTTP 로는 못 지운다. ROS
`/task_api_requests` 로 보낸다.

### 6-11. safety 임계값이 도크 거리와 같아 구조적으로 진입 불가

`stop_distance_m` 은 **범퍼 기준** 정지 거리다(`FOOTPRINT_FRONT_M=0.04` 차감 후).
기본값 `0.30` 인데 상온 `entry → dock_target` 거리가 정확히 `0.300 m` 였다.

```
front_stop: path_clearance=0.2973716054436855 scan_nearby=0.2142366662946382
```

**3 mm 차이로 영구 차단.** 회전도 `swept threshold=0.179` vs 실측 `0.1755` 로 같은 상황.

launch 는 safety 파라미터를 인자로 받지 않으므로 **프로세스 교체가 유일한 방법**이다.

```bash
ssh pinky@192.168.0.21 'pgrep -f "trihouse_pinky_safety/lib/trihouse_pinky_safety/safety_supervisor"'
ssh pinky@192.168.0.21 'kill -KILL <PID>'

ssh pinky@192.168.0.21 'bash -s' <<'REMOTE'
source /opt/ros/jazzy/setup.bash
source /home/pinky/pinky_pro/install/setup.bash
source /home/pinky/trihouse_ws/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
setsid nohup ros2 run trihouse_pinky_safety safety_supervisor --ros-args \
  -r __ns:=/pinky_01 -p robot_id:=PK_01 \
  -p stop_distance_m:=0.15 -p slow_distance_m:=0.40 \
  -r cmd_vel_nav:=cmd_vel -r cmd_vel:=cmd_vel_safe \
  > /home/pinky/ops_test_20260824_safety4.log 2>&1 < /dev/null &
disown
REMOTE
```

> `swept_clearance_m` 은 기본값(기하학적 외접반경 `hypot(0.16, 0.08) = 0.179 m`)을
> 쓴다. 그 아래로 내리면 가드가 더 이상 접촉을 막지 못한다.

### 6-12. `front_stop` 에는 recovery 가 없다

`trihouse_pinky/trihouse_pinky_docking/trihouse_pinky_docking/narrow_zone.py:434`

```python
if safety.detail == "swept_stop" and self.phase == self.ENTRY_ALIGNMENT:
    ...  # 회전 공간 확보 recovery
return self._fail(f"safety_stop:{safety.detail or 'unknown'}")
```

recovery 는 `swept_stop` × `ENTRY_ALIGNMENT` **한 조합에만** 있다.
`ENTER_STRAIGHT` 중 `front_stop` 은 곧바로 `failed` 가 되고
`recovery_max_attempts: 2` 는 한 번도 쓰이지 않는다.

```
rule_transition ... phase=enter_straight safety='front_stop' recovery_attempt=0
rule_transition ... from=enter_straight to=failed failure='safety_stop:front_stop'
```

이 전이가 초당 수십 회 반복된다. **미해결 — 코드 수정 필요.**

### 6-13. 협로 `entry` 좌표가 자기 `dock_target` 과 어긋나 있었다

2026-08-23 편집이 상온·냉장의 `entry` 를 덮어썼다. 세 방향에서 교차 확인했다.

- 상온: 되돌린 entry 로 계산한 `doorway.yaw = 0.3358713991009853` 이 파일에 남아
  있던 원본 `0.33587139910098424` 와 일치
- 냉장: `dock_target` 을 고정하고 역산하니 DB waypoint `chilled_storage_narrow_entry`
  가 **오차 0.0000000000 m** 로 정확히 나옴
- 냉동: 결함 아님. `enter` 가 `straight` 로 시작해 방위 비교가 성립하지 않는다

증상은 "Nav2 가 도달 불가능한 yaw 를 맞추려 제자리 회전만 반복" 이다.

### 6-14. **배터리 게이트가 배차를 막는다**

`trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/battery_policy.py`

```python
if percentage <= 10.0:
    return BatteryProjection("RETURN_REQUIRED", False, "BATTERY_AT_OR_BELOW_RETURN_THRESHOLD")
```

문턱이 하드코딩이라 파라미터로 못 낮춘다. 이 로봇의 SOC 판독은 한 주행 안에서
`0.0 ~ 100.0` 을 오간다. 그 잡음이 `dispatchable` 을 5 초마다 껐다 켜고, 어댑터는
그때마다 로봇을 RMF 에서 뺐다 넣는다.

```
[PK_01] RMF 상태 갱신 중단: PINKY_NOT_READY
[PK_01] 상태 복구 확인 후 RMF에 recommission했습니다.
```

**주문이 `20=pending` 에 머무는 또 하나의 정체다.**

```bash
tail -30 log/ops_test_2026-08-24/pk01_track.csv | awk -F, '{print $13}' | sort | uniq -c
#   20 0
#   10 1
```

**조치** — 로봇 정책 노드를 내리고 4060 에서 `ready=True` 를 고정 발행한다.
두 발행자가 같은 토픽에 쓰면 판정이 번갈아 뒤집히므로 **로봇 쪽을 먼저 내린다.**

```bash
ssh pinky@192.168.0.21 'pgrep -f "trihouse_pinky_fleet/battery_policy"'
ssh pinky@192.168.0.21 'kill -KILL <PID>'

setsid nohup python3 scripts/ops_battery_policy_override.py \
  --namespace pinky_01 --robot-id PK_01 \
  > /tmp/trihouse_battery_override.log 2>&1 < /dev/null &
```

> 시험용 우회다. SOC 판독을 고치면 되돌린다.
> `ros2 run trihouse_pinky_fleet battery_policy --ros-args -r __ns:=/pinky_01`

### 6-15. **bringup 재시작 시 좀비 노드가 남아 AMCL 이 무너진다**

증상: pose 가 `(0, 0, 0)`, `sensor_timeout`, 그리고 22 초마다 반복되는

```
CRITICAL FAILURE: SERVER map_server IS DOWN after not receiving a heartbeat
for 60000 ms. Shutting down related nodes.
```

원인은 map_server 가 아니라 **이전 bringup 의 노드가 살아남은 것**이다.

```bash
ssh pinky@192.168.0.21 'ps -eo pcpu,pmem,pid,comm --sort=-pcpu | head -10'
#  9.1 0.9  7840 joint_state_pub   <- 2회차 잔존
#  8.3 0.9  5520 joint_state_pub   <- 1회차 잔존
#  7.5 0.9  9754 joint_state_pub   <- 현재
```

같은 이름의 노드가 여럿이면 `/pinky_01/joint_states` 와 TF 를 두고 다투고,
bond heartbeat 가 끊겨 lifecycle_manager 가 AMCL 을 내린다.
`battery_publisher` 도 함께 중복되어 **SOC 가 튀는 원인의 일부**였다.

시작 시각으로 세대를 구분한다.

```bash
ssh pinky@192.168.0.21 'ps -eo pid,lstart,cmd --no-headers \
  | grep -E "ros2 launch|/opt/ros/jazzy/lib/|trihouse_ws/install/|pinky_pro/install/" \
  | grep -v grep | sort -k4'
```

**정리 패턴 — 이 목록이어야 한다.**

```bash
ssh pinky@192.168.0.21 '
LAUNCH=$(pgrep -f "trihouse_pinky_bringup trihouse_pinky.launch.py")
[ -n "$LAUNCH" ] && kill -TERM $LAUNCH
sleep 10
for p in $(pgrep -f "trihouse_pinky|nav2_|sllidar_node|pinky_imu|pinky_sensor|bringup_namespaced|lifecycle_manager|robot_state_publisher|joint_state_publisher|safety_supervisor|fleet_gateway|status_node|fleet_node|battery_publisher"); do
  kill -KILL $p 2>/dev/null
done
sleep 4
pgrep -af "trihouse|nav2_|sllidar|joint_state|robot_state|pinky_" | grep -v "bash -c" || echo "PASS: clean"
'
```

> **bringup 을 두 번 이상 재시작한 뒤 이상 징후가 보이면 로봇을 재부팅한다.**
> 좀비를 하나씩 찾는 것보다 빠르고 확실하다.

### 6-16. `entry_passage` 는 이 도크들에 맞지 않는 동작이다

전략 선택은
`trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/narrow_zone_routing.py:26`.

```python
def entry_motion_strategy(profile: NarrowZoneProfile) -> str:
    return "warehouse_entry" if profile.entry_passage is not None else "legacy_narrow_zone"
```

`warehouse_entry` 는 출입구를 **앞으로 통과**한다. 그러나 이 도크들의 실측 절차는
**회전 뒤 후진**이다. 앞으로 밀고 들어가면 완화된 임계에서도 이렇게 된다.

```
front_stop: path_clearance=0.04606385131705024
front_stop: path_clearance=-0.006074218545109034     ← 이미 발자국 안에 장애물
```

임계값 문제가 아니라 **동작이 틀린 것**이다. 냉동에는 이 블록이 처음부터 없다.
→ 상온·냉장에서도 제거해 세 구역을 `legacy_narrow_zone` 으로 통일했다.

### 6-17. AMCL 이 발산하면 로봇은 벽을 향해 "정상 주행" 한다

```
2026-08-24T12:57:54  (0.6886, 2.7387, -178.3deg)     ← y 가 지도 범위 밖
```

무너지는 경로:

```
enter_straight 실패(front_stop) → 규칙 failed → fleet_node 재시도
  → Nav2 재목표 → controller "Failed to make progress" → recovery 회전/후진
  → 좁은 공간에서 바퀴 미끄러짐 → odometry 오차 누적 → 파티클 필터 발산
```

**추적 CSV 의 pose 가 지도 범위(x −0.22~1.97, y −1.473~1.197)를 벗어나면 즉시
정지시킨다.** 그 상태에서는 어떤 주문도 의미가 없다.

### 6-18. FMS job 을 취소해도 로봇이 멈추지 않는다

RMF task 가 살아 있으면 어댑터가 계속 명령을 보낸다.
**즉시 정지는 어댑터를 내리는 것이다.**

```bash
kill -KILL $(pgrep -f 'pinky_easy_fleet_adapter')
```

그 뒤에 RMF task 를 취소한다. 순서를 바꾸면 취소하는 동안에도 로봇이 움직인다.

### 6-19. 손으로 놓은 위치는 AMCL 로 잴 수 없다

→ 5-1 참고.

---

## 7. 정지·정리

### 즉시 정지 (긴급)

```bash
# 1) 로봇에 가는 명령을 끊는다
kill -KILL $(pgrep -f 'pinky_easy_fleet_adapter')

# 2) job 취소
curl -sS -X POST "$FMS_API/internal/v1/jobs/<ID>/cancel" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: cancel-job-<ID>-$(date +%Y%m%d%H%M%S)" \
  -d '{"reason":"emergency_stop","requested_by":"newuser"}'

# 3) RMF task 취소
python3 scripts/ops_rmf_cancel_task.py <task_id>
```

### 정상 종료

```bash
# 로봇
ssh pinky@192.168.0.21 'kill -TERM $(pgrep -f "trihouse_pinky.launch.py")'

# 4060 호스트
kill -TERM $(pgrep -f 'pinky_easy_fleet_adapter|rmf_core.launch|control_tower\.|tests.simulation.omx|ops_track_pinky|ops_battery_policy_override')

# Docker 는 남겨 둔다 (운영 DB 보존)
docker ps
```

---

## 8. 부록 — 이번 시험에서 만든 도구

| 파일 | 용도 |
| --- | --- |
| `scripts/ops_track_pinky.py` | 위치·상태를 CSV 로 계속 기록. 최근접 waypoint 와 거리까지 적는다 |
| `scripts/ops_read_pose.py` | 현재 map pose 를 협로 설정에 붙여넣을 형태로 출력 |
| `scripts/ops_seed_amcl.py` | AMCL 에 대략 위치를 뿌린다 (**측정 도구가 아니다** — 5-1 경고 참고) |
| `scripts/ops_battery_policy_override.py` | 배터리 게이트를 `ready=True` 로 고정 (시험용 우회) |
| `scripts/ops_rmf_cancel_task.py` | RMF 에 남은 task 를 ROS api request 로 취소 |

---

## 9. 2026-08-24 시험 결과 요약

| job | 구역 | 결과 |
| --- | --- | --- |
| 6, 7 | 상온 | fleet adapter 미등록 → `DISPATCH_ATTEMPTS_EXHAUSTED` |
| 8 | 상온 | 기본 safety(`0.30`)로 협로 진입 3 mm 차 차단 |
| 9 | 상온 | safety 완화 후 상온 도크 앞 도달, `entry.yaw` 30.3° 불일치로 제자리 회전 |
| 10 | 상온 | 배터리 게이트로 배차 자체가 안 됨 |
| 11 | 상온 | 좌표 수정 후 `entry_alignment` **최초 통과**, `enter_straight` 에서 벽 접촉 → AMCL 발산 |

**확인된 것**

- 운영 DB → 주문 → job 7 단계 자동 생성 → RMF 배차 → Nav2 주행까지 전 경로 관통
- 로봇이 충전소에서 출발해 `charging_station_narrow_exit` → `bottleneck_01` →
  상온 도크 앞까지 실제 주행
- 좌표 수정 후 협로 `entry_alignment` 통과

**미완**

- 상온·냉장·냉동 3 회 완전 사이클(창고 → 포장대 → 충전소 복귀)
- 실제 도킹 완료 (`enter` 회전→후진 시퀀스 검증)

**남은 코드 결함**

- `front_stop` 에 recovery 없음 (6-12)
- FMS job 취소가 RMF task 를 취소하지 않음 (6-10)
- 배터리 SOC 판독 잡음 (6-14)
- `battery_policy` 문턱 하드코딩 — 파라미터화 필요 (6-14)
