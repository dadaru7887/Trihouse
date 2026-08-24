# Pinky 주문 실행 런북 (복사·붙여넣기용)

주문 → 주행 → 로봇팔까지 한 번에 돌리는 절차다. **위에서부터 순서대로 그대로
복사해 붙여넣으면 된다.**

매번 발목을 잡는 두 가지가 맨 앞에 있다.

1. **주소가 바뀐다** — 서버 PC 는 유선 `192.168.0.9` / 무선 `192.168.0.4` 를 오간다
2. **이전 프로세스가 남는다** — 같은 이름 노드가 겹치면 bond·TF 가 무너지고
   AMCL 이 죽는다. 증상은 "map_server IS DOWN", "Invalid frame ID pinky_01/odom",
   pose 가 `(0,0,0)` 으로 굳는 것이다.

그래서 **STEP 0 과 STEP 1 을 건너뛰지 않는다.**

---

## 고정 정보

| 항목 | 값 |
| --- | --- |
| 서버 PC | `cook2` — 유선 `eno1` **192.168.0.9** / 무선 `wlo1` **192.168.0.4** |
| 작업 경로 | `/home/newuser/Trihouse/.worktrees/physical-integration-v1` |
| Pinky PK_01 | `pinky@192.168.0.21` |
| Pinky PK_02 | `pinky@192.168.0.22` |
| OMX_01 PC | `192.168.0.31` |
| OMX_02 PC | `192.168.0.32` |
| ROS domain | `12` |
| Discovery Server | `<서버IP>:11811` |
| FMS API | `http://<서버IP>:8080` |
| FMS TCP (로봇) | `<서버IP>:8788` |
| map revision | `new_map_2:2419810c3f013a648f46da995aa33b6f8ba20154cf297c26932959a599898589` |

---

# STEP 0 — 주소 실측 (매번)

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1

# 로봇과 같은 192.168.0.x 대역 주소를 자동으로 고른다
export PC_IP="$(ip -4 -o addr show | awk '$4 ~ /^192\.168\.0\./ {split($4,a,"/"); print a[1]; exit}')"
echo "서버 IP = $PC_IP"

# 안 잡히면 직접 지정한다
# export PC_IP=192.168.0.9    # 유선
# export PC_IP=192.168.0.4    # 무선

export ROBOT_IP=192.168.0.21
export FMS_API="http://${PC_IP}:8080"

ping -c 2 -W 2 "$ROBOT_IP" | tail -2
```

`서버 IP =` 가 비어 있으면 랜선/Wi-Fi 를 확인하고 다시 실행한다.

---

# STEP 1 — 이전 프로세스 전멸 (매번)

## 1-1. 서버 PC

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1

kill -KILL $(pgrep -f 'rmf_core.launch|rmf_traffic_|rmf_task_dispatcher|door_supervisor|lift_supervisor|mutex_group_supervisor|pinky_easy_fleet_adapter|control_tower\.|tests.simulation.omx|ops_track_pinky|ops_battery_policy_override|fastdds discovery|fast-discovery' | tr '\n' ' ') 2>/dev/null

sleep 4
pgrep -af 'rmf_|control_tower\.|ops_track|ops_battery|omx.action_server|discovery' | grep -v 'bash -c' || echo "PASS: 서버 clean"
ss -lunp 2>/dev/null | grep 11811 || echo "PASS: 11811 해제됨"
```

> `fastdds discovery` 는 `sh` 래퍼와 실제 바이너리 두 프로세스다. 래퍼만 죽이면
> 바이너리가 11811 을 계속 물고 있어 **새 서버가 조용히 실패**한다. 위 명령은
> `fast-discovery` 도 함께 잡는다.

## 1-2. 로봇

```bash
ssh pinky@$ROBOT_IP 'bash -s' <<'REMOTE'
L=$(pgrep -f "trihouse_pinky_bringup trihouse_pinky.launch.py")
[ -n "$L" ] && kill -TERM $L
sleep 6
PIDS=$(ps -eo pid,cmd --no-headers \
  | grep -E "/opt/ros/jazzy/|trihouse_ws/install/|pinky_pro/install/|ros2 launch|ops_start_safety|watch_clearance|scan_probe" \
  | grep -v grep | awk '{print $1}' | tr '\n' ' ')
[ -n "$PIDS" ] && kill -KILL $PIDS 2>/dev/null
sleep 4
N=$(ps -eo pid,cmd --no-headers | grep -E "/opt/ros/jazzy/|trihouse_ws/install/|pinky_pro/install/" | grep -v grep | wc -l)
echo "잔존 ROS 프로세스 = $N   (0 이어야 한다)"
REMOTE
```

**`잔존 ROS 프로세스 = 0` 을 반드시 확인한다.** 0 이 아니면 한 번 더 실행한다.

---

# STEP 2 — Docker (운영 DB + Gateway)

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1

# 0.0.0.0 에 바인딩한다. 유선/무선 어느 쪽으로 바뀌어도 그대로 동작한다.
FMS_API_HOST='0.0.0.0' FMS_TCP_BIND='0.0.0.0' \
docker compose -p trihouse_p0 -f compose.yaml -f compose.control.yaml \
  up -d mysql fms_gateway

until curl -fsS -m 3 "$FMS_API/ready" >/dev/null 2>&1; do sleep 2; done
echo "PASS: Gateway ready"
docker ps --format 'table {{.Names}}\t{{.Status}}'
```

---

# STEP 3 — 서버 PC ROS 스택

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1

source /opt/ros/jazzy/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
export ROS_DISCOVERY_SERVER="${PC_IP}:11811"
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
unset ROS_STATIC_PEERS
unset FASTRTPS_DEFAULT_PROFILES_FILE
export PYTHONPATH="$PWD/trihouse_omx_adapter:$PWD${PYTHONPATH:+:$PYTHONPATH}"
export MAP_REVISION='new_map_2:2419810c3f013a648f46da995aa33b6f8ba20154cf297c26932959a599898589'

# 3-1. Discovery Server
setsid nohup fastdds discovery -i 0 -l "$PC_IP" -p 11811 \
  > /tmp/trihouse_discovery_server.log 2>&1 < /dev/null & disown
sleep 5
grep -a "Server Addresses" /tmp/trihouse_discovery_server.log
```

**`Server Addresses: UDPv4:[<PC_IP>]:11811` 줄이 나와야 한다.**
`Problem creating RTPSParticipant` 가 보이면 STEP 1-1 을 다시 한다.

```bash
# 3-2. RMF core  (dispatcher 가 없으면 주문이 영원히 RMF_ASSIGNMENT_PENDING)
setsid nohup ros2 launch trihouse_rmf_bridge rmf_core.launch.py \
  use_sim_time:=false start_visualization:=false \
  > /tmp/trihouse_rmf_core.log 2>&1 < /dev/null & disown
sleep 10
pgrep -f rmf_task_dispatcher >/dev/null && echo "PASS: dispatcher" || echo "FAIL: dispatcher 없음"

# 3-3. 관제 워커 3종  (없으면 outbox 가 dead_letter 가 된다)
setsid nohup python3 -m control_tower.task_manager.job_runner_node \
  --fms-base-url "$FMS_API" --poll-interval-s 1 \
  >> /tmp/trihouse_job_runner.log 2>&1 < /dev/null & disown

setsid nohup python3 -m control_tower.task_manager.executor_worker_node \
  --fms-base-url "$FMS_API" --environment hardware --poll-interval-s 1 \
  >> /tmp/trihouse_executor_worker.log 2>&1 < /dev/null & disown

setsid nohup python3 -m control_tower.rmf_adapter.rmf_gateway_worker_node \
  --fms-base-url "$FMS_API" --fleet-name project1_pinky \
  --worker-id trihouse-rmf-worker --poll-interval-s 1 \
  >> /tmp/trihouse_rmf_gateway_worker.log 2>&1 < /dev/null & disown

# 3-4. 배터리 게이트 우회 + 위치 추적기
setsid nohup python3 scripts/ops_battery_policy_override.py \
  --namespace pinky_01 --robot-id PK_01 \
  > /tmp/trihouse_battery_override.log 2>&1 < /dev/null & disown

setsid nohup python3 scripts/ops_track_pinky.py --namespace pinky_01 \
  --output "log/ops_test_$(date +%F)/pk01_track.csv" \
  > /tmp/trihouse_ops_track.log 2>&1 < /dev/null & disown

sleep 8
for p in rmf_task_dispatcher job_runner_node executor_worker_node \
         rmf_gateway_worker_node ops_battery_policy_override ops_track_pinky; do
  pgrep -f "$p" >/dev/null && printf "  OK   %s\n" "$p" || printf "  FAIL %s\n" "$p"
done
```

---

# STEP 4 — 로봇팔 (OMX)

## 4-A. 실장비를 쓸 때

각 팔 PC 에서 실행한다. OMX_01 은 `192.168.0.31`, OMX_02 는 `192.168.0.32`.

```bash
# [OMX PC] 서버 PC 주소와 domain 을 맞춘다
ssh <omx-user>@192.168.0.31

cd ~/trihouse_ws     # 팔 PC 의 workspace 경로
source /opt/ros/jazzy/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
export ROS_DISCOVERY_SERVER='192.168.0.9:11811'     # STEP 0 의 PC_IP
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
unset ROS_STATIC_PEERS
unset FASTRTPS_DEFAULT_PROFILES_FILE

# 팔 제어 노드 (device_id 를 반드시 맞춘다)
setsid nohup ros2 run trihouse_omx_adapter action_server \
  --ros-args -r __node:=omx_01 -p device_id:=OMX_01 \
  > /tmp/omx_01.log 2>&1 < /dev/null & disown
```

서버 PC 에서 확인한다.

```bash
ping -c 2 -W 2 192.168.0.31
ros2 action list | grep omx        # /omx_01/execute 가 보여야 한다
```

**손목 카메라를 쓸 때**는 팔 PC 가 MediaMTX 로 RTSP 를 발행하므로,
`.env` 의 `OMX_PC_01_IP` / `OMX_PC_02_IP` 가 그 PC 주소와 같아야 한다.
다르면 MediaMTX 가 조용히 거절한다.

## 4-B. 팔 PC 가 없을 때 (무동작 시뮬레이터)

주행만 시험할 때 쓴다. **팔 동작은 모의이고 주행·도킹·포장대·복귀는 실물이다.**

```bash
# [서버 PC] STEP 3 의 환경이 잡힌 터미널에서
for omx in OMX_01 OMX_02; do
  node="$(echo "$omx" | tr '[:upper:]' '[:lower:]')"
  setsid nohup python3 -m tests.simulation.omx.action_server \
    --ros-args -r __node:="$node" -p device_id:="$omx" \
    > "/tmp/trihouse_omx_sim_${node}.log" 2>&1 < /dev/null & disown
done
sleep 4
pgrep -af 'tests.simulation.omx.action_server' | grep -v 'bash -c'
```

**같은 노드 이름이 두 벌 뜨면 안 된다.** 위 목록이 정확히 2줄이어야 한다.

> 팔이 없으면 `step 30`(적재)이 열리지 않아 로봇이 창고 도크에서 멈춘다.
> `step 30` 은 `step 10`(팔) 과 `step 20`(주행) 이 **둘 다** 성공해야 열린다.

---

# STEP 5 — 로봇 기동

**로봇을 충전소에 놓고, 충전 케이블을 뽑는다.**
케이블이 붙어 있으면 라이다가 8~9 cm 앞의 케이블을 보고 회전을 막는다
(2026-08-24 실측 `scan_nearby=0.088`).

**USB 장치가 붙어 있는지 먼저 본다.** 라이다와 모터 컨트롤러가 없으면 bringup 은
떠도 로봇은 아무것도 못 한다 (2026-08-24 20:12 에 실제로 겪었다).

```bash
ssh pinky@$ROBOT_IP 'lsusb | grep -v "root hub" || echo "USB 장치 없음 - 케이블 확인"'
ssh pinky@$ROBOT_IP 'ls /dev/ttyUSB* 2>/dev/null || echo "/dev/ttyUSB0 없음 - 라이다 미연결"'
```

```bash
ssh pinky@$ROBOT_IP 'sed -n "41,47p" /home/pinky/hardware_pinky_01.yaml'
# initial_pose 가 x 0.0570244747 / y 0.1949666005 / yaw 0.1093261667 이어야 한다
```

```bash
ssh pinky@$ROBOT_IP "PC_IP=$PC_IP bash -s" <<'REMOTE'
LOG=/home/pinky/ops_bringup_$(date +%Y%m%d_%H%M%S).log
echo "$LOG" > /home/pinky/.ops_last_bringup_log
: > "$LOG"
cd /home/pinky/trihouse_ws
source /opt/ros/jazzy/setup.bash
source /home/pinky/pinky_pro/install/setup.bash
source /home/pinky/trihouse_ws/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
export ROS_DISCOVERY_SERVER="${PC_IP}:11811"
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
  control_host:="$PC_IP" control_port:=8788 \
  vision_enabled:=false docking_enabled:=false \
  >> "$LOG" 2>&1 < /dev/null &
disown
sleep 12
echo "launch PID = $(pgrep -f 'trihouse_pinky.launch.py' | head -1)"
grep -a "협로 profile" "$LOG" | tail -1
REMOTE
```

navigation 은 60 초 뒤에 올라온다. **`active=2` 가 될 때까지 기다린다.**

```bash
ssh pinky@$ROBOT_IP 'L=$(cat /home/pinky/.ops_last_bringup_log)
for i in $(seq 1 40); do
  n=$(grep -ac "Managed nodes are active" "$L")
  [ "$n" -ge 2 ] && { echo "PASS: lifecycle active=$n"; exit 0; }
  sleep 3
done
echo "FAIL: active=$(grep -ac "Managed nodes are active" "$L")"
grep -aE "Failed to bring up|Failed to change state|Invalid frame ID" "$L" | tail -3'
```

`FAIL` 이면 좀비가 남은 것이다. **STEP 1-2 로 돌아간다.**

---

# STEP 6 — safety supervisor 교체 (도킹 가능 임계값)

launch 가 만든 기본값(`stop_distance_m=0.30`)으로는 **도킹을 못 한다.**
창고 도크가 진입부에서 정확히 0.30 m 라 출발하자마자 걸린다.

```bash
# 스크립트를 로봇에 배포 (한 번만)
cat > /tmp/ops_start_safety.sh <<'EOF'
#!/bin/bash
source /opt/ros/jazzy/setup.bash
source /home/pinky/pinky_pro/install/setup.bash
source /home/pinky/trihouse_ws/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
export ROS_DISCOVERY_SERVER="${DS_IP:-192.168.0.9}:11811"
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
unset ROS_STATIC_PEERS
unset FASTRTPS_DEFAULT_PROFILES_FILE
exec ros2 run trihouse_pinky_safety safety_supervisor --ros-args \
  -r __ns:=/pinky_01 -p robot_id:=PK_01 \
  -p stop_distance_m:="${STOP_D:-0.05}" \
  -p slow_distance_m:="${SLOW_D:-0.25}" \
  -p swept_clearance_m:="${SWEPT_C:-0.12}" \
  -r cmd_vel_nav:=cmd_vel -r cmd_vel:=cmd_vel_safe
EOF
scp -q /tmp/ops_start_safety.sh pinky@$ROBOT_IP:/home/pinky/ops_start_safety.sh
ssh pinky@$ROBOT_IP 'chmod +x /home/pinky/ops_start_safety.sh'
```

```bash
# 기본값 supervisor 와 로봇쪽 battery_policy 를 내리고 교체본을 띄운다
ssh pinky@$ROBOT_IP "DS_IP=$PC_IP bash -s" <<'REMOTE'
S=$(ps -eo pid,cmd --no-headers | grep "trihouse_pinky_safety/lib" | grep -v grep | awk '{print $1}')
B=$(ps -eo pid,cmd --no-headers | grep "trihouse_pinky_fleet/battery_policy" | grep -v grep | awk '{print $1}')
echo "내릴 safety=$S  battery_policy=$B"
[ -n "$S" ] && kill -KILL $S 2>/dev/null
[ -n "$B" ] && kill -KILL $B 2>/dev/null
sleep 3
setsid nohup env DS_IP="$DS_IP" /home/pinky/ops_start_safety.sh \
  > /home/pinky/ops_safety.log 2>&1 < /dev/null & disown
sleep 7
echo "--- safety 인스턴스 (1 이어야 한다) ---"
ps -eo pid,cmd --no-headers | grep "trihouse_pinky_safety/lib" | grep -v grep | wc -l
echo "--- battery_policy (0 이어야 한다) ---"
ps -eo pid,cmd --no-headers | grep "trihouse_pinky_fleet/battery_policy" | grep -v grep | wc -l
REMOTE
```

**safety 가 2 이면 기본값 인스턴스가 남은 것이다.** 둘이 같은
`/pinky_01/cmd_vel_safe` 에 발행해 판정이 번갈아 뒤집힌다. 다시 실행한다.

### 파라미터 뜻

| 파라미터 | 기본값 | 권장 | 뜻 |
| --- | --- | --- | --- |
| `stop_distance_m` | 0.30 | **0.05** | 진행 방향 장애물이 이 안이면 STOP. **범퍼/바구니 끝 기준** |
| `slow_distance_m` | 0.70 | **0.25** | 이 안이면 감속 |
| `swept_clearance_m` | 0.179 | **0.12** | 제자리 회전 시 360° 최근접이 이 안이면 STOP |

`0.179` 는 `hypot(FOOTPRINT_REAR_M 0.16, PROTECTIVE_HALF_WIDTH_M 0.08)` — 회전
외접반경이다. **그 아래로 내리면 가드가 접촉을 막지 못한다. E-stop 담당자가
실질적 보호 장치다.**

---

# STEP 7 — fleet adapter (반드시 rmf_core 다음에)

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1

setsid nohup ros2 launch trihouse_rmf_bridge pinky_easy_fleet_adapter.launch.py \
  nav_graph:="$PWD/.trihouse/p0/nav_graph.yaml" \
  robot_name:=PK_01 \
  rmf_map_name:=L1 \
  charger_waypoint:=charging_station_01 \
  map_revision:="$MAP_REVISION" \
  robot_status_topic:=/pinky_01/trihouse/status \
  transport_action:=/pinky_01/trihouse/transport/execute \
  fms_base_url:="$FMS_API" \
  use_sim_time:=false \
  > /tmp/trihouse_pinky_fleet_adapter.log 2>&1 < /dev/null & disown

sleep 22
grep -aE "adapter 시작|등록했습니다|RuntimeError|does not have any robots" \
  /tmp/trihouse_pinky_fleet_adapter.log | tail -3
```

**두 줄이 나와야 한다.**

```
PK_01 EasyFullControl adapter 시작: status=/pinky_01/trihouse/status, action=/pinky_01/trihouse/transport/execute
[PK_01] 유효한 pose/SOC로 RMF에 등록했습니다.
```

| 나온 것 | 뜻 | 조치 |
| --- | --- | --- |
| `RuntimeError: RMF adapter를 만들지 못했습니다` | rmf_core 보다 먼저 떴다 | STEP 3-2 확인 후 이 STEP 재실행 |
| `does not have any robots` | status 토픽 namespace 가 틀렸다 | `robot_status_topic` 이 `/pinky_01/...` 인지 확인 |
| 등록 줄이 없음 | 로봇 `ready=0` | STEP 8 의 출발 조건 확인 |

---

# STEP 8 — 출발 조건 확인

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
TRACK="log/ops_test_$(date +%F)/pk01_track.csv"

tail -3 "$TRACK" | awk -F, '{printf "(%s, %s) yaw=%s  %s %sm  nav=%s  safety=%s/%s  ready=%s disp=%s  err=%s\n", $3,$4,$5,$6,$7,$8,$9,$10,$12,$13,$18}'
```

**전부 만족해야 출발한다.**

| 항목 | 값 |
| --- | --- |
| 최근접 waypoint | `charging_station_01`, 거리 `0.000` |
| safety | `clear/clear` |
| ready / dispatchable | `1 / 1` |
| errors | 비어 있음 |

**라이다가 실제로 발행하는지 확인한다.** 프로세스가 살아 있어도 데이터가 안 나올
수 있다.

```bash
ssh pinky@$ROBOT_IP "source /opt/ros/jazzy/setup.bash; \
  export ROS_DOMAIN_ID=12 ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT \
    ROS_DISCOVERY_SERVER=${PC_IP}:11811 RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
    FASTDDS_BUILTIN_TRANSPORTS=UDPv4; \
  timeout 10 ros2 topic hz /pinky_01/scan 2>&1 | head -3"
# average rate 가 나와야 한다.
# "does not appear to be published" 면 USB 를 확인한다.
```

**장애물이 있으면 어느 방향인지 각도로 특정한다.** `scan_nearby` 는 360° 최솟값이라
방향을 알려 주지 않는다.

```bash
# 서버 PC 에서 실행한다 (STEP 3 환경이 잡힌 터미널)
python3 scripts/ops_scan_sectors.py --namespace pinky_01
```

**읽는 법** — 좁은 각도 구간에 여러 빔이 **같은 거리**로 걸리고 **좌우가 크게
비대칭**이면 벽이 아니라 로봇에 붙었거나 옆에 놓인 물체다.

| 구간 최근접 | 뜻 |
| --- | --- |
| 0.20 m 이상 | 출발 가능 |
| 0.10 ~ 0.15 m | 로봇 몸통 안쪽 — **충전 케이블·물건** |
| 0.05 m 이하 | 접촉 직전 |

2026-08-24 20:10 실측 예 — 왼쪽 39.8 cm 대 오른쪽 13.3 cm 로 비대칭이었고,
-45°~-49° 구간이 전부 13.3 cm 였다. 환경이 아니라 물체였다.

지도 범위를 벗어나면 AMCL 이 발산한 것이다. **그 상태로 주문을 넣으면 로봇이
벽을 향해 "정상 주행" 한다.**

```
x  -0.22 ~ 1.97      y  -1.473 ~ 1.197
```

대기 중인 job 과 RMF task 도 비어 있어야 한다.

```bash
source .env
docker exec trihouse-mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -t -e \
  "SELECT job_id, state FROM jobs WHERE state NOT IN ('cancelled','completed','failed');
   SELECT job_id, rmf_task_id FROM job_steps WHERE rmf_task_id IS NOT NULL AND state='cancelled';" \
  trihouse_fms
```

취소된 job 의 `rmf_task_id` 가 남아 있으면 **반드시 지운다.** RMF 가 그 task 를
계속 재배정해 새 주문이 영원히 `20=pending` 에 머문다.

> **STEP 1 부터 순서대로 했다면 대개 지울 것이 없다.** `rmf_task_dispatcher` 는
> task 목록을 메모리에만 들고 있어서, STEP 1-1 에서 죽이고 STEP 3-2 에서 새로
> 띄우면 RMF 쪽 기억이 통째로 사라진다. 아래 정리는 **스택을 재기동하지 않고
> 이어서 주문할 때** 필요하다. 판별 기준은 `rmf_task_dispatcher` 의 기동 시각이다.
>
> ```bash
> ps -o lstart= -p "$(pgrep -f rmf_task_dispatcher | head -1)"   # dispatcher 기동 시각
> source .env
> docker exec trihouse-mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -t -e \
>   "SELECT job_id, created_at, state FROM jobs ORDER BY job_id DESC LIMIT 5;" trihouse_fms
> ```
>
> dispatcher 기동 **이후**에 만들어진 job 의 task 만 RMF 에 남아 있다.

```bash
# 위 SELECT 로 나온 것을 한 번에 넘긴다
source .env
STALE="$(docker exec trihouse-mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e \
  "SELECT rmf_task_id FROM job_steps WHERE rmf_task_id IS NOT NULL AND state='cancelled';" trihouse_fms)"
echo "남은 task: $STALE"
[ -n "$STALE" ] && python3 scripts/ops_rmf_cancel_task.py $STALE
# 응답 ...: {"success":true}
```

---

# STEP 9 — 주문 (복사해서 바로 쓴다)

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
export FMS_API="http://${PC_IP}:8080"

submit_order() {
  local zone="$1" sku="$2" run_id resp
  run_id="$(date +%Y%m%d%H%M%S)"
  resp="$(curl -fsS -X POST "$FMS_API/api/v1/orders" \
    -H 'Content-Type: application/json' \
    -H "Idempotency-Key: ${zone}-live-${run_id}" \
    -d "{\"external_reference\":\"${zone}-LIVE-${run_id}\",\"priority\":\"normal\",\"allow_partial_fulfillment\":false,\"items\":[{\"product_code\":\"${sku}\",\"quantity\":1}]}")" || {
      echo "주문 실패: $zone $sku"; return 1; }
  echo "$resp" | python3 -c "import json,sys;d=json.load(sys.stdin);print(f\"  {d['job_id']}  {d['job_code']}  {d['state']}\")"
  echo "$resp" | python3 -c "import json,sys;print(json.load(sys.stdin)['job_id'])"
}

watch_job() {
  local id="$1" limit="${2:-120}" i
  for i in $(seq 1 "$limit"); do
    printf "t+%04ds  " $((i*10))
    curl -fsS "$FMS_API/api/v1/jobs/$id" | python3 -c "
import json,sys; d=json.load(sys.stdin)
print(d['state'][:9].ljust(9), ' '.join(f\"{s['step_no']}={s['state'][:4]}\" for s in d['steps']), end='  ')"
    tail -1 "log/ops_test_$(date +%F)/pk01_track.csv" | cut -d, -f3,4,5,6,7,8,9,10
    st="$(curl -fsS "$FMS_API/api/v1/jobs/$id" | python3 -c "import json,sys;print(json.load(sys.stdin)['state'])")"
    case "$st" in completed|failed|cancelled) echo "=> $st"; return 0;; esac
    sleep 10
  done
}
```

## 한 건씩

```bash
JOB=$(submit_order ambient SKU-MANDARIN | tail -1);  echo "JOB=$JOB"; watch_job "$JOB"
JOB=$(submit_order chilled SKU-SANDWICH | tail -1);  echo "JOB=$JOB"; watch_job "$JOB"
JOB=$(submit_order frozen  SKU-PORKBELLY | tail -1); echo "JOB=$JOB"; watch_job "$JOB"
```

## 3건 연속 (상온 → 냉장 → 냉동)

앞 주문이 끝나야 다음이 나간다. 로봇이 한 대뿐이라 동시에 넣으면 뒤엣것이
`no free robot` 으로 대기만 한다.

```bash
run_three() {
  local zones=(ambient chilled frozen)
  local skus=(SKU-MANDARIN SKU-SANDWICH SKU-PORKBELLY)
  local i job st
  for i in 0 1 2; do
    echo "════════ $((i+1))/3  ${zones[$i]}  ${skus[$i]} ════════"
    job="$(submit_order "${zones[$i]}" "${skus[$i]}" | tail -1)" || return 1
    echo "JOB=$job"
    watch_job "$job"
    st="$(curl -fsS "$FMS_API/api/v1/jobs/$job" | python3 -c "import json,sys;print(json.load(sys.stdin)['state'])")"
    if [ "$st" != "completed" ]; then
      echo "!! ${zones[$i]} 주문이 $st 로 끝났습니다. 중단합니다."
      curl -fsS "$FMS_API/api/v1/jobs/$job" | python3 -c "
import json,sys; d=json.load(sys.stdin)
for s in d['steps']:
    if s.get('failure_reason'): print('  실패:', s['step_no'], s['action_type'], s['failure_reason'])"
      return 1
    fi
    echo "충전소 복귀 안정화 대기 20초"
    sleep 20
  done
  echo "════════ 3건 모두 완료 ════════"
}

run_three
```

## 시험 재고 SKU

| 구역 | 쓸 수 있는 SKU |
| --- | --- |
| 상온 | `SKU-MANDARIN` `SKU-ORANGE` `SKU-STRAWBERRY` |
| 냉장 | `SKU-SANDWICH` `SKU-MILK` `SKU-YOGURT` `SKU-COFFEE` |
| 냉동 | `SKU-PORKBELLY` `SKU-ICEBAR` `SKU-ICECONE` `SKU-DUMPLING` |

좌표는 주지 않는다. FMS 가 SKU 의 `temperature_zone` 으로 창고 도크와 포장대를
스스로 정한다.

## 주문 한 건이 만드는 7 단계

| step | 작업 | 담당 |
| --- | --- | --- |
| 10 | 팔이 상품을 도크로 준비 | OMX |
| 20 | 창고 도크로 주행 | PK_01 |
| 30 | 적재 게이트 (**10 과 20 이 둘 다 성공해야 열림**) | FMS |
| 40 | 포장대로 주행 | PK_01 |
| 50 | 포장대 인계 | FMS |
| 60 | 포장 대기 | FMS |
| 70 | 대기/충전소 복귀 | PK_01 |

---

# STEP 10 — 즉시 정지

**FMS job 을 취소해도 로봇은 멈추지 않는다.** RMF task 가 살아 있으면 어댑터가
계속 명령을 보낸다. **순서를 지킨다.**

```bash
# 1) 로봇에 가는 명령을 먼저 끊는다
kill -KILL $(pgrep -f 'pinky_easy_fleet_adapter' | tr '\n' ' ') 2>/dev/null

# 2) job 취소
curl -sS -X POST "$FMS_API/internal/v1/jobs/$JOB/cancel" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: cancel-job-$JOB-$(date +%Y%m%d%H%M%S)" \
  -d '{"reason":"emergency_stop","requested_by":"newuser"}'

# 3) RMF task 취소 (안 하면 다음 주문이 굶는다)
source .env
TASKS="$(docker exec trihouse-mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e \
  "SELECT rmf_task_id FROM job_steps WHERE job_id=$JOB AND rmf_task_id IS NOT NULL;" trihouse_fms)"
echo "취소할 task: $TASKS"
[ -n "$TASKS" ] && python3 scripts/ops_rmf_cancel_task.py $TASKS
```

---

# 증상별 조치표

| 증상 | 원인 | 조치 |
| --- | --- | --- |
| `Couldn't connect to server` | 서버 IP 가 바뀌었다 | STEP 0 부터 다시 |
| `Problem creating RTPSParticipant` / `tool not found` | 옛 discovery server 가 11811 점유 | STEP 1-1 (`fast-discovery` 포함해서 kill) |
| `Waiting for service map_server/get_state...` 무한 | discovery server 가 죽은 주소를 광고 | STEP 1 → 3-1 → 5 순서로 전부 재기동 |
| `Invalid frame ID "pinky_01/odom"` / `Failed to bring up` | nav2 가 두 벌 | STEP 1-2 (전멸 후 재기동) |
| `map_server IS DOWN` 이 22초마다 반복 | `joint_state_publisher` 등 좀비 | STEP 1-2 |
| pose 가 `(0,0,0)` 에 `sensor_timeout` | 로봇 스택이 죽었거나 좀비 충돌 | STEP 1-2 → STEP 5 |
| pose 가 지도 범위 밖 | AMCL 발산 | 즉시 정지, 충전소에 놓고 STEP 5 재기동 |
| `20=pending` 인데 안 움직임 | ① 어댑터 미등록 ② 취소된 RMF task 가 굶김 ③ 배터리 게이트 | STEP 7 로그 / STEP 8 task 정리 / 배터리 우회 확인 |
| `does not have any robots` | 어댑터가 namespace 없는 토픽 구독 | STEP 7 인자 확인 |
| `DISPATCH_ATTEMPTS_EXHAUSTED` | 워커 없이 주문을 넣었다 | job 취소 → STEP 3-3 → 새 주문 |
| `/omx_01/execute unavailable` | 팔이 없다 | STEP 4-A 또는 4-B |
| `front_stop` 에서 안 움직임 | `stop_distance_m` 이 도크 거리보다 크다 | STEP 6 (0.05) |
| `swept_stop` 반복 | 회전 반경 안에 물체 | **충전 케이블 확인**, `scan_nearby` 값 확인 |
| `PINKY_NOT_READY` 반복 | 배터리 SOC 판독 잡음 | STEP 3-4 배터리 우회 확인 |
| `SCHEMA_INVALID type=robot_status` | 유휴 상태의 정상 메시지 | 무시 |
| `/pinky_01/scan does not appear to be published` | 라이다 USB 가 빠졌다 (프로세스는 살아 있다) | `lsusb`, `ls /dev/ttyUSB*` 확인 후 케이블 재연결 |
| `lsusb` 에 root hub 만 보임 | USB 장치 전부 미연결 (라이다·모터) | 케이블·허브 전원 물리 확인. 소프트웨어로 복구 불가 |
| 어댑터가 떠 있는데 등록 로그가 없음 | `pgrep` 이 자기 셸을 잡은 오판 | 로그 **갱신 시각**으로 판별하고 `nohup ... &` 로 재기동 |
| 로봇 pose 가 `(0,0,0)` 인데 노드는 살아 있음 | 진단 스크립트가 스캔을 붙들고 있다 | `watch_clearance` / `scan_probe` 회수 |

`scan_nearby` 읽는 법:

```bash
ssh pinky@$ROBOT_IP 'grep -aE "swept_stop|front_stop" /home/pinky/ops_safety.log | tail -5'
```

| `scan_nearby` | 뜻 |
| --- | --- |
| 0.15 이상 | 정상 (벽·선반) |
| 0.09 ~ 0.12 | 로봇 몸통(뒤 0.16 m) 안쪽 — **케이블·물건이 붙어 있다** |
| 0.05 이하 | 접촉 직전 |

---

# 도구

| 스크립트 | 용도 |
| --- | --- |
| `scripts/ops_track_pinky.py` | 위치·상태를 CSV 로 기록 (최근접 waypoint 와 거리 포함) |
| `scripts/ops_read_pose.py` | 현재 pose 를 협로 설정에 붙여넣을 형태로 출력 |
| `scripts/ops_battery_policy_override.py` | 배터리 게이트를 `ready=True` 로 고정 (시험용) |
| `scripts/ops_rmf_cancel_task.py` | RMF 에 남은 task 를 취소 |
| `scripts/ops_seed_amcl.py` | AMCL 씨앗 (측정 도구가 아니다) |

> `ops_read_pose.py` 는 **로봇이 스스로 주행해 도달한 자리**에서만 실측이다.
> 손으로 옮긴 직후에는 옮기기 전 좌표가 나온다. `x 산포 0.0000 m` 이면 믿지 않는다.

---

# 함께 볼 문서

- `docs/guides/pinky-ops-test-4060.md` — 장비 주소·경로 정본, 막혔던 지점 24개
- `log/ops_test_2026-08-24/session.md` — 2026-08-24 시간순 실행 기록
