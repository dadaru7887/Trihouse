# P0 실물 출고 실행 런북 (`new_map_2`)

주문 한 건이 아래 7 단계를 통과하는 것을 **한 사이클**로 본다. 시뮬과 같은 정의다.

```text
10 arm/pick          팔 단계 — 이번엔 물리 동작 없음. 사람이 물건을 올린다
20 mobile/navigate   로봇이 적재 지점으로 간다
30 fms/load          적재
40 mobile/navigate   로봇이 인계 지점으로 간다
50 fms/handover      인계
60 fms/wait          ← 사람이 확인해 줘야 넘어간다
70 mobile/return_home 로봇이 충전소로 돌아온다
```

**목표: 1부 — 로봇 1대로 완주 3회. 2부 — 로봇 2대 · 주문 2건 동시.**
UI 는 보지 않는다. 판정은 전부 DB 와 측정값으로 한다.

시뮬 절차는 [p0-simulation-quick-run.md](p0-simulation-quick-run.md) 다.
**두 문서를 섞어 쓰지 않는다** — 도메인(0 vs 52), 지도, 노드가 도는 자리가 전부 다르다.

메워야 하는 공백의 근거와 결정 기록은
[2026-08-20-hardware-readiness-gaps.md](../claude/2026-08-20-hardware-readiness-gaps.md) 다.

---

## 시뮬과 무엇이 다른가 — 먼저 읽는다

| | 시뮬 | 실기 |
|---|---|---|
| `ROS_DOMAIN_ID` | **0** | **52** |
| Nav2 | 관제 PC, `nav2_bringup` | **로봇**, 벤더 `pinky_navigation` |
| 온보드 노드 (safety·fleet·status·battery) | 관제 PC | **로봇** |
| 센서 | `sim_hardware` 가 만드는 가짜 값 | 실물 라이다·초음파·배터리 |
| `collision_monitor` (LiDAR 충돌 감시) | 있음 | **없음** — 벤더 lifecycle 목록에 없다 |
| 관제 PC 가 띄우는 것 | 전부 | RMF core · fleet adapter · 워커 3개뿐 |
| 지도 | `trihouse_map_01` | **`new_map_2`** |

**"로봇이 안 움직인다" 를 만났을 때 시뮬의 원인 표를 그대로 쓰면 안 된다.**

---

## 0부. 착수 게이트 — 하나라도 아니면 그 위에서 멈춘다

**이 절은 매 회차가 아니라 한 번만 한다.** 다만 **전부 통과하기 전에는 로봇을
자율 주행시키지 않는다.** 각 항목의 근거는 gaps 문서의 같은 번호에 있다.

| # | 확인할 것 | 통과 조건 | 아니면 |
|---|---|---|---|
| G1 | **좌표 정본이 `new_map_2` 위의 값인가** (H5) | `python3 scripts/p0_show_map.py new_map_2` 가 모든 도크를 **통과 가능**으로 낸다 | **2026-08-20 실측: 냉동 도크 통로가 0.06 m 로 나온다(필요 0.14 m). 재측정 없이는 냉동 출고가 불가능하다** |
| G2 | **`config/narrow_zones.new_map_2.yaml` 이 있는가** (H4·H5) | 파일이 있고 `map_name: new_map_2` | [p0-narrow-zone-measurement.md](p0-narrow-zone-measurement.md) · `notebooks/narrow_zone_measurement.ipynb` |
| G3 | **안전 gate 가 모터 토픽의 단독 발행자인가** (H3) | 로봇에서 `ros2 topic info <모터토픽>` 의 Publisher count 가 **1**, 그것이 `safety_supervisor` | **주행 금지.** gaps §1.4 의 배선을 먼저 한다 |
| G4 | **벤더 센서가 로봇 namespace 안에 있는가** (H1) | `ros2 topic list \| grep pinky_01/scan` 에 한 줄 | 분기 B(단일 로봇, namespace 없음)로만 진행 가능. 2부는 불가 |
| G5 | **관제 호스트 실기 bringup** (H2) | 아래 3부의 명령이 Gazebo·`sim_hardware` 없이 돈다 | `p0_simulation_bringup.sh` 를 실기에 쓰지 않는다 |
| G6 | **협로 파라미터가 실기 `fleet_node` 에 전달되는가** (H4) | 로봇 로그에 협로 비활성 경고가 없다 | 도크 앞에서 막힌다 |
| **G7** | **협로 규칙 주행이 RMF 작업을 취소시키지 않는가** (H0) | 시뮬에서 주문 1건이 step 20 을 넘어간다 | **2026-08-20 시뮬에서 2회 연속 여기서 죽었다.** 실기도 그대로 죽는다 |

### G3 · G4 를 로봇에서 확인하는 법

로봇에서 온보드 launch 를 띄운 뒤 **다른 셸**에서.

```bash
export ROS_DOMAIN_ID=52 && source /opt/ros/jazzy/setup.bash && source ~/trihouse_ws/install/setup.bash
```
```bash
ros2 topic list | grep -E '/(pinky_01/)?(scan|odom|cmd_vel|batt_state)$'
```

| 나오는 것 | 뜻 |
|---|---|
| `/pinky_01/scan`, `/pinky_01/odom`, … | **분기 A.** 로봇 2대까지 갈 수 있다 |
| `/scan`, `/odom`, … (접두사 없음) | **분기 B.** 벤더 bringup 이 namespace 를 안 문다. 1대만 |

```bash
ros2 topic info /pinky_01/cmd_vel      # 분기 B 면 /cmd_vel
```

**Publisher count 가 2 이상이면 안전 gate 가 뚫려 있다. 거기서 멈춘다.**

참고 — 같은 명령을 **시뮬**에서 돌린 2026-08-20 실측은 **3** 이었다
(`collision_monitor` · `docking_server` · `trihouse_safety_supervisor`).
**시뮬 값이 1 이 아니라고 해서 실기가 괜찮은 것이 아니다** — 둘 다 고쳐야 한다.

---

## 1부. 한 번만 하는 준비

### 1-1. 호스트 배치

| 호스트 | 무엇이 도는가 |
|---|---|
| **4060 서버** | MySQL · FMS Gateway · (MediaMTX) · RMF core · fleet adapter · job runner · executor worker · RMF dispatch worker |
| **로봇 PK_01 / PK_02** | 벤더 bringup(라이다·모터·배터리) · Nav2 · 온보드 노드 전부 |
| OMX PC | 이번 범위 밖 (팔 제외) |

**로봇과 4060 은 같은 서브넷의 ROS 전용 Ethernet 에 있어야 한다.** 서버는 인터페이스가
둘이므로 **Wi-Fi 쪽 주소를 쓰면 로봇이 붙지 못한다.**

### 1-2. 4060 — Docker 와 패키지

```bash
sudo apt install -y docker.io docker-compose-v2 && sudo systemctl enable --now docker && sudo usermod -aG docker "$USER"
```
로그아웃 후 다시 로그인한다.

```bash
sudo apt install -y \
  ros-jazzy-rmf-fleet-msgs ros-jazzy-rmf-fleet-adapter \
  ros-jazzy-rmf-task-ros2 ros-jazzy-rmf-traffic ros-jazzy-rmf-traffic-ros2 \
  ros-jazzy-rmf-battery ros-jazzy-tf-transformations
```

`nav2` 는 4060 에 필요 없다 — Nav2 는 로봇 위에서 돈다. 다만 이 저장소를 빌드하려면
`ros-jazzy-navigation2` 의 메시지 패키지가 필요하므로 이미 깔려 있으면 그대로 둔다.

### 1-3. 4060 — `.env`

`.env.example` 을 복사해 **실기 값**으로 채운다. 아래 다섯이 실기에서 달라지는 것이다.

```bash
ROS_DOMAIN_ID=52
FMS_TCP_BIND=<4060 Ethernet 주소>      # 127.0.0.1 이면 로봇이 8788 에 못 붙는다
FMS_API_HOST=<4060 Ethernet 주소>      # 로봇/타 PC 가 8080 을 쓸 때
PINKY_PK_01_IP=<PK_01 DHCP 예약 주소>
PINKY_PK_02_IP=<PK_02 DHCP 예약 주소>
```

`MYSQL_ROOT_PASSWORD` · `FMS_DB_PASSWORD` · `MTX_VIEWER_PASS` 도 자리표시자에서 바꾼다.

> **`FMS_TCP_BIND` 를 놓치면 증상이 이렇게 나온다** — 로봇은 멀쩡히 뜨고 Nav2 도
> 활성인데 `errors` 에 `control_link_offline` 이 남고 `dispatchable` 이 false 라
> RMF 가 그 로봇에 작업을 **하나도 주지 않는다.** 오류 메시지는 어디에도 안 나온다.

### 1-4. 4060 — 워크스페이스 빌드

**순서가 중요하다.** `pinky_pro` 를 먼저 빌드하고 source 한 뒤 루트를 빌드한다.

```bash
cd /home/newuser/Trihouse/pinky_pro && source /opt/ros/jazzy/setup.bash && colcon build --symlink-install
```
```bash
source /opt/ros/jazzy/setup.bash && source pinky_pro/install/setup.bash && colcon build --symlink-install --packages-select trihouse_interfaces trihouse_rmf_bridge trihouse_pinky_bringup trihouse_pinky_fleet trihouse_pinky_safety trihouse_omx_adapter
```

### 1-5. 로봇 — 빌드

로봇에서. `pinky_pro` 를 source 한 **뒤에** 빌드한다.

```bash
colcon build --symlink-install --packages-select \
  trihouse_interfaces trihouse_pinky_io trihouse_pinky_safety \
  trihouse_pinky_fleet trihouse_pinky_bringup trihouse_pinky_vision
```
```bash
for pkg in pinky_bringup pinky_navigation trihouse_pinky_bringup trihouse_pinky_fleet; do
  printf '%-26s %s\n' "$pkg" "$(ros2 pkg prefix $pkg 2>&1)"
done
```
넷 다 경로를 출력해야 한다.

### 1-6. 지도와 파생 params 를 로봇으로 배포

**관제가 발행한 지도와 로봇이 도는 지도는 반드시 같아야 한다.** 좌표는 지도마다 다른
프레임 위의 값이라, 갈라지면 도착 판정이 구조적으로 실패한다.

4060 에서:

```bash
cd /home/newuser/Trihouse
scp control_ui/rmf_control_ui/data/rmf_maps/new_map_2.{yaml,pgm} pinky@<PK_01 주소>:~/maps/
```

**분기 A 라면** 파생 nav2 params 도 함께 만든다 (벤더 launch 에는 `RewrittenYaml` 이
없어 감싸 주지 않으면 파라미터가 한 개도 적용되지 않는다).

```bash
scripts/derive_hardware_nav2_params.py \
  --source pinky_pro/pinky_navigation/params/nav2_params.yaml \
  --namespace pinky_01 \
  --output .trihouse/p0/nav2/hardware_pinky_01.yaml
```
```bash
head -1 .trihouse/p0/nav2/hardware_pinky_01.yaml     # 기대: pinky_01:
scp .trihouse/p0/nav2/hardware_pinky_01.yaml pinky@<PK_01 주소>:~/
```

**분기 B 면 이 단계를 건너뛴다.** nav2 노드가 루트에 있어 벤더 맨 키가 그대로 맞는다.

---

## 2부. 매 회차 — 4060 관제 층

### 터미널 1 — Docker 층과 지도 발행

```bash
cd /home/newuser/Trihouse
```
```bash
docker compose -p trihouse_p0 -f compose.yaml -f compose.control.yaml -f compose.edge_4060.yaml up -d
```
```bash
until curl -fsS -m 2 http://127.0.0.1:8080/ready; do sleep 3; done; echo
```
기대: `{"status":"ready","database":"ok"}`.

**첫 회차이거나 DB 를 되돌린 뒤에만** 지도를 발행한다.

```bash
python3 scripts/p0_publish_map.py control_ui/rmf_control_ui/data/rmf_maps/new_map_2.yaml | tail -1
```
```bash
export REV=$(docker exec trihouse-mysql mysql -uroot -p"$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)" -N -B -e "SELECT map_revision FROM trihouse_fms.map_revisions WHERE state='published' ORDER BY published_at DESC LIMIT 1;" 2>/dev/null) && echo "REV=$REV"
```

`REV=trihouse_test_01:...` 형태여야 한다. **해시를 손으로 옮겨 적지 않는다** —
원장이 정본이고, 두 번 데였다.

`new_map_2.pgm` 은 확장자만 `.pgm` 이고 내용은 PNG 다. `p0_publish_map.py` 가 magic
bytes 로 판별해 처리하므로 저장소 파일은 건드리지 않는다.

### 터미널 2 — nav_graph 와 파생 자산 생성

```bash
cd /home/newuser/Trihouse && source /opt/ros/jazzy/setup.bash && source install/setup.bash && source pinky_pro/install/setup.bash && export ROS_DOMAIN_ID=52
```
```bash
python3 control_tower/bringup/p0_runtime_assets.py \
  --fms-base-url http://127.0.0.1:8080 \
  --map-name trihouse_test_01 --map-revision "$REV" \
  --features control_ui/rmf_control_ui/data/import/trihouse_test_01_physical_features.jsonl \
  --nav2-source pinky_pro/pinky_navigation/params/nav2_params.yaml \
  --world-source control_tower/bringup/p0_world.sdf \
  --map-yaml control_ui/rmf_control_ui/data/rmf_maps/new_map_2.yaml \
  --output-dir .trihouse/p0 \
  --robot PK_01:pinky_01 --robot PK_02:pinky_02
```

`world.sdf` 도 함께 나오지만 실기에서는 쓰지 않는다(Gazebo 가 없다).

**병목 상호배제 확인** — 2부(2대)로 갈 때 이것이 곧 통로 안전장치다.

```bash
grep -A1 'BOTTLENECK' .trihouse/p0/nav_graph.yaml | grep -E 'mutex'
```

| 나오는 것 | 뜻 |
|---|---|
| `mutex: bottleneck_01` | **RMF 가 읽는다.** 상호배제 켜짐 |
| `mutex_group: bottleneck_01` | **RMF 가 조용히 버린다.** 상호배제 꺼짐 — gaps §2.2 |
| 아무것도 없음 | 병목이 JSONL 에 없다 |

### 터미널 3 — 관제 ROS 층 (**닫지 말 것**)

```bash
cd /home/newuser/Trihouse && source /opt/ros/jazzy/setup.bash && source install/setup.bash && source pinky_pro/install/setup.bash
```
```bash
export ROS_DOMAIN_ID=52 RMW_IMPLEMENTATION=rmw_fastrtps_cpp FASTDDS_BUILTIN_TRANSPORTS=UDPv4 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
```
```bash
export PYTHONPATH="/home/newuser/Trihouse:$PYTHONPATH"
```

**하위 셸 네 개를 순서대로 띄운다.** 각각을 `&` 로 배경에 두고 로그를 파일로 남긴다 —
실패 원인이 DB 에 안 남으므로(D22) 로그가 유일한 근거다.

```bash
ros2 launch trihouse_rmf_bridge rmf_core.launch.py use_sim_time:=false start_visualization:=false > /tmp/hw_rmf_core.log 2>&1 &
```
```bash
sleep 5
```
```bash
ros2 launch trihouse_rmf_bridge pinky_easy_fleet_adapter.launch.py \
  nav_graph:=/home/newuser/Trihouse/.trihouse/p0/nav_graph.yaml \
  robot_name:=PK_01 rmf_map_name:=L1 charger_waypoint:=charging_station_01 \
  map_revision:="$REV" fms_base_url:=http://127.0.0.1:8080 \
  robot_status_topic:=/pinky_01/trihouse/status \
  transport_action:=/pinky_01/trihouse/transport/execute \
  use_sim_time:=false > /tmp/hw_adapter_pk01.log 2>&1 &
```

**분기 B(namespace 없음)라면** 두 토픽 인자를 `/trihouse/status`,
`/trihouse/transport/execute` 로 준다.

```bash
python3 -m control_tower.task_manager.job_runner_node --fms-base-url http://127.0.0.1:8080 > /tmp/hw_job_runner.log 2>&1 &
```
```bash
python3 -m control_tower.task_manager.executor_worker_node --fms-base-url http://127.0.0.1:8080 --environment hardware --act-config /home/newuser/Trihouse/config/act.simulation.yaml > /tmp/hw_executor.log 2>&1 &
```
```bash
python3 -m control_tower.rmf_adapter.rmf_gateway_worker_node --fms-base-url http://127.0.0.1:8080 --fleet-name project1_pinky --worker-id trihouse-rmf-worker > /tmp/hw_rmf_worker.log 2>&1 &
```

**`--use-sim-time` 을 주지 않는다.** 실기에는 `/clock` 발행자가 없어 시계가 0 에 멈춘다.

**`--environment hardware`** 는 소요시간 표본을 실기로 태그하는 것이다. `act-config` 는
`deterministic_fake` 그대로다 — 팔은 이번에 물리 동작을 하지 않는다(gaps H6).

**Gazebo·`sim_hardware`·`ros_gz_bridge` 는 하나도 뜨지 않는 것이 정상이다.**
`ps -eo args | grep -c 'gz sim'` 가 0 이어야 한다.

---

## 3부. 매 회차 — 로봇

### 로봇 터미널 (**닫지 말 것**)

```bash
export ROS_DOMAIN_ID=52 && export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
```
```bash
source /opt/ros/jazzy/setup.bash && source ~/trihouse_ws/install/setup.bash
```

**주행 전에 안전 확인.** 전방 2 m 를 비우거나 바퀴를 띄운다. 물리 비상정지를 손 닿는
곳에 둔다. **G3 이 통과하지 않았으면 여기서 멈춘다** — 소프트 정지가 로봇을 못 세운다.

**분기 A:**

```bash
ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  robot_id:=PK_01 namespace:=pinky_01 \
  map:=$HOME/maps/new_map_2.yaml map_revision:="<REV>" \
  nav2_params_file:=$HOME/hardware_pinky_01.yaml \
  control_host:=<4060 Ethernet 주소> control_port:=8788 \
  vision_enabled:=false 2>&1 | tee /tmp/hw.log
```

**분기 B:** `namespace:=''` 로 주고 `nav2_params_file` 을 뺀다.

`vision_enabled:=false` — 카메라는 출고 완주 경로에 없다. 켜려면 MediaMTX 의 IP
허용목록(`PINKY_PK_01_IP`)을 먼저 채운다.

### 로봇 판정 — 위에서부터, 실패하면 그 자리에서 멈춘다

다른 셸에서. 층을 건너뛰면 어느 층의 문제인지 말할 수 없게 된다.

```bash
grep -c 'Managed nodes are active' /tmp/hw.log        # 기대 2 (localization 1 + navigation 1)
grep -E 'Failed to bring up all requested|Failed to change state' /tmp/hw.log   # 기대 빈 출력
```

실기에는 Gazebo 도 두 번째 로봇도 없다. 시뮬에서 이 단계를 무너뜨리던 부하 문제가
여기엔 없으므로 **여기서 실패하면 부하가 아니라 실제 결함이다.**

```bash
NS=/pinky_01     # 분기 B 면 NS= (빈 값)
ros2 topic echo --once $NS/scan sensor_msgs/msg/LaserScan | head -3
ros2 topic echo --once $NS/odom nav_msgs/msg/Odometry | head -3
ros2 topic echo --once $NS/trihouse/battery sensor_msgs/msg/BatteryState | head -3
ros2 topic echo --once $NS/trihouse/readiness trihouse_interfaces/msg/Readiness
```

`Readiness.missing_interfaces` 가 **비어 있어야 한다.** 비어 있지 않으면 무엇이 아직
안 왔는지 이름으로 알려 주므로 거기로 돌아간다.

> **`ros2 topic echo` 에 타입을 항상 같이 준다.** 타입 없이 부르면 그래프에서 타입을
> 찾는데, 참가자가 많거나 부하가 높으면 그 열거가 멈춘다.
>
> **`ros2 node list` 를 판정에 쓰지 않는다.** 2026-08-20 시뮬 실측에서 `node list` 는
> 10 개만 돌려주며 `amcl`·`bt_navigator`·fleet adapter·`safety_supervisor` 를 빠뜨렸다
> — 전부 살아 있는데도 그랬다. **같은 순간 `ros2 topic list` 는 160 개를, `ros2 action
> list` 는 18 개를 정확히 냈다.** 존재 확인은 topic/action list 로 한다.

**초기 pose 를 준다.** 이것을 건너뛰면 AMCL 이 지도 전체에 입자를 흩뿌린 채 시작하고,
그 실패는 로봇이 움직이기 시작한 뒤에야 보인다.

```bash
ros2 topic pub --once $NS/initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
  '{header: {frame_id: "map"}, pose: {pose: {position: {x: <실측x>, y: <실측y>, z: 0.0}, orientation: {z: 0.0, w: 1.0}}}}'
```

좌표는 **로봇이 실제로 서 있는 자리**다. 충전소에서 시작한다면 `new_map_2` 에서 다시
잰 `charging_station_01` 값을 쓴다 (G1).

---

## 4부. 매 회차 — 판정 → 주문 → 완주

### 4060 터미널 4

```bash
cd /home/newuser/Trihouse && source /opt/ros/jazzy/setup.bash && source install/setup.bash && source pinky_pro/install/setup.bash && export ROS_DOMAIN_ID=52
```
```bash
python3 scripts/verify_robot_status.py pinky_01 20
```

| 항목 | 기대값 | 아니면 |
|---|---|---|
| `publishers` | 전부 **1** | **2 이상이면 그 아래 숫자는 전부 못 믿는다.** 이전 세대가 남았거나 관제 PC 가 온보드 노드를 함께 띄웠다(gaps H2) |
| `frame_id` | **`map`** | `pinky_01/odom` 이면 AMCL 미수렴 — 초기 pose 를 다시 준다 |
| `dispatchable` | **true** | 아래 표 |
| `errors` | **`[]`** | 아래 표 |

| 오류 | 뜻 | 볼 곳 |
|---|---|---|
| `control_link_offline` | 8788 미연결 | 로봇에서 `nc -z <4060 IP> 8788`. `.env` 의 `FMS_TCP_BIND` |
| `map_pose_stale` | `map -> base` 변환 없음 = AMCL 미동작 | 초기 pose, 벤더가 namespace 를 물었는지(G4) |
| `scan_stale` / `odom_stale` | 센서가 namespace 밖에 있다 | **G4** |
| `nav_unavailable` | `navigate_to_pose` 서버 없음 | 로봇 로그의 lifecycle 실패 줄 |
| `battery_stale` | `trihouse/battery` 미도달 | 로봇의 `battery_adapter` |

**`RESULT: PASS` 가 아니면 주문을 넣지 않는다.**

### 주문을 넣는다

**이번 회차의 SKU 를 5부의 표에서 고른다.**

```bash
ORDER=$(curl -s -X POST http://127.0.0.1:8080/api/v1/orders -H 'Content-Type: application/json' -H "Idempotency-Key: hw-$(date +%s)" -d '{"requested_by":"W-OP-01","priority":"normal","items":[{"product_code":"SKU-DUMPLING","quantity":1}]}')
```
```bash
echo "$ORDER" | python3 -m json.tool && export JOB=$(echo "$ORDER" | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])') && echo "JOB=$JOB"
```

여러 품목을 한 주문에 넣으면 **같은 로봇이** 온도 구역별로 나뉜 묶음을 차례로 처리한다.
**로봇 두 대를 동시에 돌리려면 주문을 두 건 넣어야 한다** — 6부.

### 주행 측정 — step 20 이 `running` 이 된 뒤

로그의 성공 문구가 아니라 이 값으로 판단한다.

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
| `cmd_vel 0` | **발행자가 없다.** 0 값이 오는 것과 다르다 |
| `cmd_vel N / 움직임 0` | 발행자는 있는데 값이 0 — 목표가 없거나 안전 gate 가 막고 있다 |
| `움직임 > 0`, `이동 > 0` | 실제로 주행 중 |

### 사람이 해야 하는 두 가지

**(1) step 10 뒤 — 물건을 로봇에 올린다.** 팔이 이번엔 물리 동작을 하지 않는다.
원장에는 `succeeded` 로 적히고 로봇은 출발하므로, **step 20 이 시작되기 전에 올린다.**

**(2) step 60 `fms/wait` 에서 — 완료 보고.** 이것이 없으면 영원히 기다리고
step 70(충전소 복귀)이 시작되지 않는다. **이 호출은 실물 재고를 확정하며 되돌릴 수 없다.**

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/jobs/$JOB/worker-completion -H 'Content-Type: application/json' -H "Idempotency-Key: worker-completion-$JOB" -d '{"worker_id":"W-OP-01","completion_note":"hardware run"}' | python3 -m json.tool
```

409 `MANUAL_ACKNOWLEDGEMENT_REQUIRED` 가 오면 응답의 `item_ids` 를 그대로 넣어 다시 부른다.

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/jobs/$JOB/worker-completion -H 'Content-Type: application/json' -H "Idempotency-Key: worker-completion-$JOB-ack" -d '{"worker_id":"W-OP-01","acknowledged_manual_item_ids":[<응답의_ID>]}' | python3 -m json.tool
```

### 완주 판정

```bash
docker exec trihouse-mysql mysql -uroot -p"$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)" --table -e "SELECT job_id,state,IFNULL(assigned_mobile_id,'-') robot FROM trihouse_fms.jobs WHERE job_id=$JOB; SELECT step_no,executor_type,action_type,state,final_outcome_reason_code FROM trihouse_fms.job_steps WHERE job_id=$JOB ORDER BY step_no;"
```

**7 단계가 모두 `succeeded` 이고 job 이 `completed` 이면 한 사이클 완주다.**

### 터미널 5 — 진행 관측

```bash
watch -n2 'docker exec trihouse-mysql mysql -uroot -p"$(grep -E "^MYSQL_ROOT_PASSWORD=" /home/newuser/Trihouse/.env | cut -d= -f2-)" --table -e "SELECT s.step_no,s.executor_type,s.action_type,s.state,IFNULL(m.channel,\"-\") ch,IFNULL(m.state,\"-\") outbox FROM trihouse_fms.job_steps s LEFT JOIN trihouse_fms.integration_messages m ON m.job_step_id=s.job_step_id WHERE s.job_id='"$JOB"' ORDER BY s.step_no;" 2>/dev/null'
```

`outbox` 가 `dead_letter` 가 되면 그 step 은 회복되지 않는다. **재투입 API 는 없다.**

---

## 5부. 3회 반복 — 회차마다 SKU 를 바꾼다

**초기화하지 않는다.** `p0_reset.sh` 는 DB 를 되돌리며 **지도도 다시 발행**하는데,
그러면 로봇이 든 `map_revision` 이 낡아 거절되어 **로봇까지 재기동**해야 한다.
그리고 취소해도 재고 예약이 돌아오지 않는다(D2). 그래서 **재고를 그냥 소진한다.**

| 회차 | SKU | 온도 구역 | 도크 |
|---|---|---|---|
| 1 | `SKU-DUMPLING` | frozen | `frozen_storage_loading_dock_01` |
| 2 | `SKU-YOGURT` | chilled | `chilled_storage_loading_dock_01` |
| 3 | `SKU-ORANGE` | ambient | `ambient_storage_loading_dock_01` |

**세 구역을 하나씩 고른 것은 의도다.** 도크마다 진입 통로가 다르므로 한 SKU 로 세 번
도는 것보다 커버리지가 넓다.

예비 (실패해서 다시 돌려야 할 때): `SKU-ICEBAR` · `SKU-MILK` · `SKU-MANDARIN` ·
`SKU-PORKBELLY` · `SKU-ICECONE` · `SKU-COFFEE` · `SKU-SANDWICH` · `SKU-STRAWBERRY`.
**SKU 당 1 lot 이므로 한 번 쓰면 끝이다.**

재고를 먼저 본다.

```bash
docker exec trihouse-mysql mysql -uroot -p"$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)" --table -e "SELECT product_code,temperature_zone,available_qty,reserved_qty,state FROM trihouse_fms.inventory_lots ORDER BY temperature_zone,product_code;"
```

**1회 성공은 우연과 구분되지 않는다.** 3회 연속이어야 완주 기준선이다.

**한 job 이 끝나기 전에 새 주문을 넣지 않는다** (1부에서는 로봇이 한 대다). 두 job 이
한 로봇을 두고 경합하면 fleet adapter 가 `FMS command claim 실패: 409` 를 초당 수백 번
반복한다.

### 완전 초기화가 필요해졌을 때

재고가 다 잠기거나 job 이 로봇을 쥔 채 굳었을 때만.

```bash
scripts/p0_reset.sh /home/newuser/Trihouse/control_ui/rmf_control_ui/data/rmf_maps/new_map_2.yaml
```

**그 뒤 반드시:** 새 `REV` 를 다시 읽고(2부 터미널 1), nav_graph 를 다시 만들고
(터미널 2), **로봇의 launch 를 새 `map_revision` 으로 재기동한다.**
`p0_reset.sh` 는 `sim_teardown.sh` 를 부르므로 **4060 의 관제 ROS 층도 함께 죽는다** —
터미널 3 을 다시 띄운다.

---

## 6부. 로봇 2대 · 주문 2건

**1부의 완주 3회가 끝난 뒤에만 시작한다.**

### 6-1. 먼저 확인할 것 두 가지

| # | 무엇 | 통과 조건 |
|---|---|---|
| T1 | 벤더 namespace (G4) | 두 로봇 모두 `/pinky_0N/scan` 이 보인다. **분기 B 면 2대는 불가** |
| T2 | 병목 상호배제 | `nav_graph.yaml` 에 **`mutex:`** 로 적혀 있다 (2부 터미널 2). `mutex_group:` 이면 RMF 가 조용히 버린다 |

**T2 가 왜 중요한가.** 창고 → 포장 경로가 병목 두 곳을 지난다. RMF 의
`request_mutex_groups` 는 필요한 그룹을 **집합으로 한 번에** 얻은 뒤에야 진입하므로
"A 가 1 을 쥐고 2 를 기다리고 B 가 그 반대" 라는 교착이 생기지 않는다. **키 이름이
맞아야 그 보호가 켜진다.** 근거는 gaps §2.

### 6-2. 관제 층에 두 번째 adapter 를 더한다

터미널 3 에서 PK_01 adapter 다음에.

```bash
ros2 launch trihouse_rmf_bridge pinky_easy_fleet_adapter.launch.py \
  nav_graph:=/home/newuser/Trihouse/.trihouse/p0/nav_graph.yaml \
  robot_name:=PK_02 rmf_map_name:=L1 charger_waypoint:=charging_station_02 \
  map_revision:="$REV" fms_base_url:=http://127.0.0.1:8080 \
  robot_status_topic:=/pinky_02/trihouse/status \
  transport_action:=/pinky_02/trihouse/transport/execute \
  use_sim_time:=false > /tmp/hw_adapter_pk02.log 2>&1 &
```

### 6-3. PK_02 를 띄운다

3부와 같되 `robot_id:=PK_02`, `namespace:=pinky_02`,
`nav2_params_file:=$HOME/hardware_pinky_02.yaml`. 초기 pose 는 `charging_station_02`.

두 로봇 모두 판정을 통과해야 한다.

```bash
python3 scripts/verify_robot_status.py pinky_01 20
```
```bash
python3 scripts/verify_robot_status.py pinky_02 20
```

### 6-4. 주문 두 건을 넣는다

**서로 다른 온도 구역**을 고른다. 같은 구역이면 두 로봇이 같은 도크를 두고 경합해
병목 상호배제만 시험하게 된다.

```bash
for sku in SKU-ICEBAR SKU-MILK; do
  curl -s -X POST http://127.0.0.1:8080/api/v1/orders -H 'Content-Type: application/json' \
    -H "Idempotency-Key: hw2-$sku-$(date +%s)" \
    -d "{\"requested_by\":\"W-OP-01\",\"priority\":\"normal\",\"items\":[{\"product_code\":\"$sku\",\"quantity\":1}]}" \
    | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["job_id"], d["state"])'
done
```

### 6-5. 2대 판정

```bash
docker exec trihouse-mysql mysql -uroot -p"$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)" --table -e "SELECT job_id,state,IFNULL(assigned_mobile_id,'-') robot FROM trihouse_fms.jobs WHERE state NOT IN ('completed','cancelled') ORDER BY job_id;"
```

| 기대 | 아니면 |
|---|---|
| 두 job 이 **서로 다른 robot** 을 받는다 | 한 로봇만 나오면 다른 로봇이 `dispatchable=false` 다. `verify_robot_status.py` 로 확인 |
| 둘 다 `running` 으로 전진 | `no free robot` 이면 앞선 job 이 로봇을 쥐고 있다 |

**병목 통과 관측** — 두 로봇이 동시에 병목으로 향할 때.

```bash
ros2 topic echo /mutex_group_states rmf_fleet_msgs/msg/MutexGroupStates
```

한 로봇이 그룹을 쥐고 다른 로봇이 대기하는 것이 보이면 상호배제가 켜진 것이다.
**아무것도 안 나오면 T2 가 안 됐다.**

---

## 7부. 막혔을 때

### 먼저 볼 것

```bash
for f in /tmp/hw_rmf_core.log /tmp/hw_adapter_pk01.log /tmp/hw_job_runner.log /tmp/hw_executor.log /tmp/hw_rmf_worker.log; do echo "== $f"; grep -aE '\[(ERROR|WARN)\]|Traceback' $f | tail -8 | cut -c1-180; done
```

로봇에서:

```bash
grep -aE '\[(ERROR|WARN)\]' /tmp/hw.log | tail -30 | cut -c1-200
```

### 증상별

| 증상 | 원인 · 조치 |
|---|---|
| `errors: ['control_link_offline']` 만 남음 | 관제 8788 에 못 붙었다. `.env` 의 `FMS_TCP_BIND` 가 `127.0.0.1` 이 아닌지, 로봇에서 `nc -z <4060 IP> 8788` |
| `verify_robot_status` 의 `publishers` 가 2 | **관제 PC 가 온보드 노드를 함께 띄웠다.** `p0_simulation_bringup.sh` 를 쓰지 않았는지 확인 (gaps H2) |
| `frame_id: pinky_01/odom` 이 계속 | AMCL 미수렴. 초기 pose 를 실제 자리로 다시 준다. 라이다가 `$NS` 아래 있는지 (G4) |
| 로봇이 도크 앞에서 나왔다 들어갔다 반복 | **협로 규칙 주행이 꺼져 있다.** `config/narrow_zones.new_map_2.yaml` 과 실기 launch 의 파라미터 전달 (gaps H4) |
| `GOAL_TOLERANCE_NOT_MET` | 실제 정지 좌표와 목표 좌표를 함께 뽑아 오차의 방향·크기를 본다. **`new_map_2` 좌표 재측정이 안 됐을 때 가장 먼저 나오는 증상이다** (G1) |
| **`command handle seems to be unresponsive` → `navigation canceled` → step 20 `RMF_TASK_CANCELLED`** | **협로 규칙 주행 중 RMF 가 로봇을 응답 없음으로 보고 작업을 취소했다 (H0).** 그 뒤 러너가 `job runner blocked: step N is cancelled` 를 무한 반복하고 adapter 가 409 를 쏟는다. **회복 경로가 없다 — job 을 취소하고 다음 SKU 로 간다** |
| `Unable to replan assignments` | 순간 안전정지가 로봇을 fleet 에서 빼냈다(D15, 미수정). 실기에서는 사람·장애물 때문에 자주 난다 |
| `FMS command claim 실패: 409` 반복 | 두 job 이 한 로봇을 두고 경합한다. 1부에서는 주문을 하나씩만 |
| `FMS command claim 실패: 404` 반복 | 원장에 없는 task 를 claim 하고 있다. `pinky_fleet.yaml` 의 `finishing_request` 가 `"nothing"`, `responsive_wait` 가 `false` 인지 |
| `발행된 지도 revision 이 요청과 다릅니다` | 로봇의 `map_revision` 이 낡았다. 새 `REV` 로 로봇을 재기동 |
| outbox 가 `dead_letter` | 그 step 은 회복되지 않는다. job 을 취소하고 다음 SKU 로 |

### job 을 닫고 다음으로

`reason` 과 `requested_by` **둘 다 필수**다. **취소는 재고 예약을 돌려주지 않으므로**
같은 SKU 로 다시 주문할 생각이면 5부의 예비 SKU 를 쓴다.

```bash
curl -sS -X POST http://127.0.0.1:8080/internal/v1/jobs/$JOB/cancel -H 'Content-Type: application/json' -H "Idempotency-Key: manual-cancel-$JOB" -d '{"reason":"<사유>","requested_by":"W-OP-01"}' | python3 -m json.tool
```

30 초 뒤 `cancelled` 로 남아 있는지 확인한다. `assigned` 로 돌아가면 러너가 되살린 것이다.

### 정리

로봇에서 launch 를 `Ctrl-C`. 4060 터미널 3 의 배경 프로세스를 내린다.

```bash
kill %1 %2 %3 %4 %5 2>/dev/null; sleep 10; ps -eo args | grep -E 'rmf_core|easy_fleet_adapter|job_runner_node|executor_worker_node|rmf_gateway_worker' | grep -v grep
```

한 줄도 안 나와야 한다. **`scripts/sim_teardown.sh` 를 쓰지 않는다** — 시뮬용이다.
Docker 층은 그대로 두어도 된다.

---

## 절대 규칙

- **`p0_simulation_bringup.sh` 를 실기에 쓰지 않는다.** Gazebo·가짜 센서·온보드 노드
  한 벌을 관제 PC 에 더 띄워 모든 측정을 무효로 만든다.
- **도메인 0 과 52 를 섞지 않는다.** 시뮬이 떠 있는 PC 에서 실기를 보려면 그 셸의
  `ROS_DOMAIN_ID` 가 52 인지 **매번** 확인한다.
- **`ROS_DOMAIN_ID` 를 export 하지 않은 셸에서 판정 명령을 돌리지 않는다.** 오류 없이
  아무것도 못 보고, 그것이 "발행자 0" 으로 보인다.
- **판정은 로그의 성공 문구가 아니라 측정값으로 한다.**
- **G3(안전 gate 단독 발행자)이 통과하지 않으면 자율 주행을 시작하지 않는다.**
- **물리 비상정지가 항상 우선이다.** 소프트 정지는 보조 수단이지 대체 수단이 아니다.

---

## 결과 기록

**실패한 것을 성공한 것과 함께 그대로 적는다.**

| 회차 | SKU | 분기(A/B) | lifecycle | `verify` 판정 | 이동(m) | 7 step | 소요 | 비고 |
|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | |
| 2 | | | | | | | | |
| 3 | | | | | | | | |
| 2대 | | | | | | | | |

---

관련 문서
- 공백·결정 기록: [2026-08-20-hardware-readiness-gaps.md](../claude/2026-08-20-hardware-readiness-gaps.md)
- 로봇 단독 점검(관제 없이): [2026-08-18-pinky-hardware-nav2-smoke.md](../validation/2026-08-18-pinky-hardware-nav2-smoke.md)
- 협로 실측: [p0-narrow-zone-measurement.md](p0-narrow-zone-measurement.md)
- 시뮬 절차: [p0-simulation-quick-run.md](p0-simulation-quick-run.md)
- 결함 정본 D1~D22: [p0-stack-reference.md](../claude/p0-stack-reference.md)
