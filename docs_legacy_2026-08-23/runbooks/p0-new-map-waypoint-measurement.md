# 새 지도에서 waypoint 좌표 다시 재기 (`new_map_2`, 실기)

좌표는 **어느 지도 위에서 쟀는지**에 매여 있다. 지도를 새로 그리면 프레임이 바뀌어
같은 실측값이 다른 자리를 가리킨다.

**왜 다시 재야 하는가 — 2026-08-20 실측.**

```bash
python3 scripts/p0_show_map.py new_map_2
```

| 도크 | `trihouse_map_01` | `new_map_2` | 필요 |
|---|---|---|---|
| ambient | 0.30 m | 0.18 m | 0.14 m |
| chilled | 0.40 m | 0.36 m | 0.14 m |
| **frozen** | 0.20 m | **0.06 m** | 0.14 m → **통과 불가** |

지도 두 장은 같은 방을 두 번 SLAM 한 것인데 origin 이 **5.7 cm** 다르고
해상도가 0.05 → 0.03 이라 벽이 더 얇고 자세히 잡혔다.

같은 날 시뮬에서 `new_map_2` + 옛 좌표로 주문을 넣었더니 **로봇이 한 번도 움직이지
못했다** (`이동 0.0000 m`, `Controller patience exceeded` 반복). 좌표 재측정이
착수 게이트 G1 인 이유다.

재는 것은 **10 지점** — waypoint 8 + 병목 2.

| 표시 | 이름 | 지금 값 (옛 지도) |
|---|---|---|
| A | `ambient_storage_loading_dock_01` | (1.234, 0.743, 2.255) |
| B | `chilled_storage_loading_dock_01` | (1.260, 0.193, −2.258) |
| C | `frozen_storage_loading_dock_01` | (1.201, −0.799, −1.408) |
| D | `packing_station_loading_dock_01` | (0.351, −0.490, 0.231) |
| E | `packing_station_loading_dock_02` | (0.351, −1.017, 0.231) |
| F | `safety_zone_01` | (0.613, −1.249, 0.0) |
| G | `charging_station_01` | (0.065, 0.227, −0.005) |
| H | `charging_station_02` | (0.076, −0.013, 0.239) |
| J | `TRIHOUSE-TEST-01-BOTTLENECK-01` | (0.841, −0.111) |
| K | `TRIHOUSE-TEST-01-BOTTLENECK-02` | (0.367, −0.762) |

정본 파일은 하나다 —
`data/map_authoring/import/trihouse_test_01_physical_features.jsonl`.

협로 규칙 주행의 진입점·회전·후진 값은 **이 문서가 아니라**
[p0-narrow-zone-measurement.md](p0-narrow-zone-measurement.md) 에서 잰다.
**waypoint 좌표가 먼저다** — 그것이 틀리면 협로 값도 틀린 자리에서 잰 것이 된다.

---

## 터미널 배치

| | 어디서 | 무엇을 |
|---|---|---|
| **A** | 4060 관제 PC | 지도 발행 · 파생 params · 파일 배포 |
| **B** | **로봇 안 (ssh)** | 온보드 + Nav2 |
| **C** | 4060 관제 PC | 자세 읽기 (`pose`) |
| **D** | 4060 관제 PC | 수동 주행 (teleop) |

**`ROS_DOMAIN_ID` 는 실기 52 다.** 로봇과 관제 PC 의 값이 같아야 한다. 다르면
오류 없이 서로를 못 본다.

---

## 단계 1 — 지도를 발행한다 (터미널 A)

```bash
cd /home/newuser/Trihouse
```
```bash
docker compose -p trihouse_p0 -f compose.yaml -f compose.control.yaml -f compose.edge_4060.yaml up -d
```
```bash
until curl -fsS -m 2 http://127.0.0.1:8080/ready; do sleep 3; done; echo
```
```bash
python3 scripts/p0_publish_map.py pinky_pro_alpha/pinky_navigation/map/new_map_2.yaml | tail -1
```
```bash
export REV=$(docker exec trihouse-mysql mysql -uroot -p"$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)" -N -B -e "SELECT map_revision FROM trihouse_fms.map_revisions WHERE state='published' ORDER BY published_at DESC LIMIT 1;" 2>/dev/null) && echo "REV=$REV"
```

`REV=trihouse_test_01:...` 이 찍혀야 한다. **해시를 손으로 옮겨 적지 않는다.**

> `docker` 가 권한 거부를 내면 이 터미널에서 먼저 `newgrp docker`.

---

## 단계 2 — 지도 파일을 로봇으로 보낸다 (터미널 A)

```bash
scp pinky_pro_alpha/pinky_navigation/map/new_map_2.yaml pinky_pro_alpha/pinky_navigation/map/new_map_2.pgm <로봇계정>@<로봇주소>:~/maps/
```

**분기 A(namespace 사용)일 때만** 파생 params 도 만들어 보낸다. 벤더 Nav2 launch 에는
`RewrittenYaml` 이 없어 감싸 주지 않으면 파라미터가 **한 개도** 적용되지 않는다.

```bash
scripts/derive_hardware_nav2_params.py --source pinky_pro/pinky_navigation/params/nav2_params.yaml --namespace pinky_01 --output .trihouse/p0/nav2/hardware_pinky_01.yaml
```
```bash
head -1 .trihouse/p0/nav2/hardware_pinky_01.yaml
```
첫 줄이 `pinky_01:` 이어야 한다.
```bash
scp .trihouse/p0/nav2/hardware_pinky_01.yaml <로봇계정>@<로봇주소>:~/
```

---

## 단계 3 — 로봇을 띄운다 (터미널 B, 로봇 안)

```bash
ssh <로봇계정>@<로봇주소>
```
```bash
cd ~/Trihouse && source /opt/ros/jazzy/setup.bash && source install/setup.bash && source pinky_pro/install/setup.bash
```
```bash
export ROS_DOMAIN_ID=52 && export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
```
```bash
ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  robot_id:=PK_01 namespace:=pinky_01 \
  map:=$HOME/maps/new_map_2.yaml \
  map_revision:="<단계 1 의 REV>" \
  nav2_params_file:=$HOME/hardware_pinky_01.yaml \
  control_host:=<4060 Ethernet IP> control_port:=8788 \
  vision_enabled:=false 2>&1 | tee /tmp/hw.log
```

**분기 B 로 갈 때** — `namespace:=''` 로 주고 `nav2_params_file` 을 뺀다.

---

## 단계 4 — 분기를 확인한다 (터미널 C) · **이게 이후 전부를 정한다**

로봇이 뜬 뒤. 벤더 `bringup_robot.launch.xml` 에는 `push-ros-namespace` 가 없어
라이다·모터가 루트에 남을 수 있다. 그러면 Nav2 가 스캔을 못 받는다.

```bash
source /opt/ros/jazzy/setup.bash && source install/setup.bash && source pinky_pro/install/setup.bash && export ROS_DOMAIN_ID=52
```
```bash
ros2 topic list | grep -E '/(pinky_01/)?(scan|odom|cmd_vel|batt_state)$'
```

| 나오는 것 | 분기 | 아래에서 |
|---|---|---|
| `/pinky_01/scan` … | **A** | `NS=/pinky_01` |
| `/scan` … (접두사 없음) | **B** | `NS=` (빈 값) |

```bash
export NS=/pinky_01          # 분기 B 면  export NS=
```

**`ros2 node list` 로 판정하지 않는다.** 2026-08-20 실측에서 살아 있는 노드를 여럿
빠뜨렸다. `topic list` / `action list` 는 정확했다.

**안전 확인** — 발행자가 **1** 이어야 하고 그것이 `safety_supervisor` 다.

```bash
ros2 topic info $NS/cmd_vel --verbose | grep -E "Publisher count|Node name"
```

2 이상이면 안전 gate 가 뚫려 있다. **수동 주행을 시작하지 않는다.**

---

## 단계 5 — 자세 읽기 명령을 만든다 (터미널 C)

```bash
pose() { python3 -c "
import rclpy, math, time, os
from rclpy.node import Node
from geometry_msgs.msg import PoseWithCovarianceStamped
ns=os.environ.get('NS','')
rclpy.init(); n=Node('pose_probe'); got=[]
n.create_subscription(PoseWithCovarianceStamped, ns+'/amcl_pose', got.append, 10)
e=time.monotonic()+6
while rclpy.ok() and time.monotonic()<e: rclpy.spin_once(n, timeout_sec=0.2)
if got:
    m=got[-1]; p=m.pose.pose.position; o=m.pose.pose.orientation; c=m.pose.covariance
    yaw=math.atan2(2*(o.w*o.z+o.x*o.y), 1-2*(o.y*o.y+o.z*o.z))
    print('x=%.4f  y=%.4f  yaw=%.4f rad (%.1f deg)' % (p.x,p.y,yaw,math.degrees(yaw)))
    print('stddev  x=%.3f m  y=%.3f m  yaw=%.3f rad' % (c[0]**0.5, c[7]**0.5, c[35]**0.5))
else:
    print('amcl_pose 없음 — AMCL 이 수렴하지 않았다')
n.destroy_node(); rclpy.shutdown()"; }
```

---

## 단계 6 — AMCL 을 수렴시킨다 (터미널 C · D)

**초기 pose 를 준다.** 로봇이 실제로 서 있는 자리의 **대략값**이면 된다. 옛 좌표를
출발 추정으로 써도 origin 차이가 5.7 cm 라 AMCL 이 끌어당긴다.

```bash
ros2 topic pub --once $NS/initialpose geometry_msgs/msg/PoseWithCovarianceStamped '{header: {frame_id: "map"}, pose: {pose: {position: {x: 0.065, y: 0.227, z: 0.0}, orientation: {z: 0.0, w: 1.0}}}}'
```

**터미널 D — 수동 주행.** 넓은 곳에서 앞뒤·좌우로 조금 움직여 입자를 모은다.

```bash
cd /home/newuser/Trihouse && source /opt/ros/jazzy/setup.bash && source install/setup.bash && source pinky_pro/install/setup.bash && export ROS_DOMAIN_ID=52 && export NS=/pinky_01
```
```bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r /cmd_vel:=$NS/cmd_vel_nav
```

> **`cmd_vel` 이 아니라 `cmd_vel_nav` 다.** 모터용 `/cmd_vel` 의 발행자는
> `safety_supervisor` 하나여야 한다. 직접 쏘면 안전 gate 를 우회하는 경로가 생기고
> safety 의 정지 명령과 뒤섞여 로봇이 덜컥거린다. **실기에서는 이것이 사고다.**

> `x` 를 여러 번 눌러 선속도를 **0.06 m/s** 아래로 내린다.

수렴 확인 — 터미널 C 에서.

```bash
pose
```

`stddev` 가 **0.12 m 아래**로 내려올 때까지 반복한다. 그 위면 그 자리의 값은 못 쓴다.

---

## 단계 7 — 지점마다 재고 적는다 (터미널 D → C)

**10 지점을 하나씩.** 순서는 넓은 곳부터 — 충전소 → 병목 → 포장대 → 도크.
도크가 가장 어렵다.

각 지점에서:

1. 터미널 D 로 **로봇을 그 물리적 자리에 세운다.** 도크는 바구니(뒤쪽)가 선반을
   향하게 놓는다.
2. 터미널 C 에서

```bash
pose
```

3. `x`, `y`, `yaw`, `stddev` 네 값을 적는다.

> **도크에서 gate 가 막을 수 있다.** `safety_supervisor` 기본값이
> `stop_distance_m 0.30` 인데 도크는 그보다 가까이 들어가야 한다. 키를 눌러도
> 로봇이 안 움직이면 그것이다. **실기에서는 gate 를 낮추지 않는다** — 대신
> 로봇을 손으로 밀어 자리에 놓고 `pose` 만 읽는다. 바퀴가 굴러 오도메트리가
> 따라오므로 AMCL 은 계속 수렴해 있다.

기록 서식 — 그대로 옮겨 적으면 단계 8 이 쉬워진다.

```text
이름                                x        y        yaw       stddev_x  비고
charging_station_01                 0.0000   0.0000   0.0000    0.000
charging_station_02
TRIHOUSE-TEST-01-BOTTLENECK-01
TRIHOUSE-TEST-01-BOTTLENECK-02
packing_station_loading_dock_01
packing_station_loading_dock_02
safety_zone_01
ambient_storage_loading_dock_01
chilled_storage_loading_dock_01
frozen_storage_loading_dock_01
```

---

## 단계 8 — 지도 위에서 확인한다 (터미널 A)

JSONL 을 고치기 **전에** 새 값이 말이 되는지 본다.

```bash
python3 scripts/p0_show_map.py new_map_2
```

세 가지를 본다.

| 보는 것 | 통과 조건 |
|---|---|
| `모든 지점이 통행 가능한 격자 위에 있습니다` | 그대로 나와야 한다 |
| 도달 가능성 표 | **다섯 도크 전부 `통과 가능`** |
| 최선 통로 폭 | 전부 **0.14 m 이상** |

**냉동 도크가 `통과 불가` 로 남으면 좌표만으로는 못 푼다.** 그때는 선반을 물리적으로
옮기거나, 그 통로를 협로 규칙 주행으로 넘긴다
([p0-narrow-zone-measurement.md](p0-narrow-zone-measurement.md)).

---

## 단계 9 — 정본을 고치고 다시 발행한다 (터미널 A)

**JSONL 이 좌표 정본이다.** 코드 상수보다 먼저다.

고칠 것 — 지점마다 세 자리.

| 자리 | 무엇 |
|---|---|
| `map_pose.x` / `.y` / `.yaw` | 새 실측값 |
| `source_map_name` | `new_map_2.yaml` 의 경로로 |
| `source_measurements[]` | 항목을 **추가**한다(덮지 않는다) — `timestamp`, `note`, `map_x/y/yaw`, `amcl_xy_stddev_m` |

병목(`record_type: bottleneck`)은 `map_pose` 에 `yaw` 가 없다. x·y 만 고친다.

고친 뒤 다시 발행하고 새 revision 을 받는다.

```bash
python3 scripts/p0_publish_map.py pinky_pro_alpha/pinky_navigation/map/new_map_2.yaml | tail -1
```
```bash
export REV=$(docker exec trihouse-mysql mysql -uroot -p"$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)" -N -B -e "SELECT map_revision FROM trihouse_fms.map_revisions WHERE state='published' ORDER BY published_at DESC LIMIT 1;" 2>/dev/null) && echo "REV=$REV"
```

**JSONL 내용이 sha256 에 들어가므로 revision 이 반드시 바뀐다.** 로봇을 새 `REV` 로
재기동해야 한다 — 안 그러면 bringup 이 `발행된 지도 revision 이 요청과 다릅니다` 로 죽는다.

nav_graph 도 다시 만든다.

```bash
python3 control_tower/bringup/p0_runtime_assets.py \
  --fms-base-url http://127.0.0.1:8080 \
  --map-name trihouse_test_01 --map-revision "$REV" \
  --features data/map_authoring/import/trihouse_test_01_physical_features.jsonl \
  --nav2-source pinky_pro/pinky_navigation/params/nav2_params.yaml \
  --world-source control_tower/bringup/p0_world.sdf \
  --map-yaml pinky_pro_alpha/pinky_navigation/map/new_map_2.yaml \
  --output-dir .trihouse/p0 \
  --robot PK_01:pinky_01 --robot PK_02:pinky_02
```
```bash
grep -A2 BOTTLENECK .trihouse/p0/nav_graph.yaml | grep -E 'mutex|name'
```

---

## 단계 10 — 코드 상수를 함께 맞춘다

이름을 바꾸지 않고 좌표만 고쳤다면 건드릴 것이 없다. **이름을 바꿨다면** 아래가
같은 커밋에서 함께 바뀌어야 한다 — 어긋나면 `p0_runtime_assets.py` 가 `SystemExit`
로 즉시 죽는다.

| 파일 | 무엇 |
|---|---|
| `control_tower/bringup/p0_runtime_assets.py` | `LANE_TOPOLOGY` (9 쌍) · `CHARGER_BY_ROBOT` |
| `control_tower/task_manager/assignment.py` | `CHARGER_BY_MOBILE` |
| `trihouse_rmf_bridge/config/pinky_fleet.yaml` | `robots.PK_0N.charger` |
| `config/narrow_zones.new_map_2.yaml` | 협로 존 표 (이 지도용으로 새로 만든다) |

---

## 함정

- **`ROS_DOMAIN_ID` 를 export 하지 않은 셸에서 `pose` 를 치지 않는다.** 오류 없이
  `amcl_pose 없음` 만 나온다 — AMCL 이 죽은 것과 구분되지 않는다.
- **`stddev` 를 안 적으면 나중에 그 값을 믿을 근거가 없다.** 0.12 m 를 넘으면 다시 잰다.
- **`ros2 topic echo` 에 타입을 항상 같이 준다.** 타입 없이 부르면 그래프 열거에
  의존해 부하가 높을 때 멈춘다.
- **`cmd_vel` 에 직접 teleop 하지 않는다.** `cmd_vel_nav` 다.
- **협로 값을 이 문서에서 재지 않는다.** waypoint 가 확정된 뒤
  [p0-narrow-zone-measurement.md](p0-narrow-zone-measurement.md) 로 간다.

---

관련 문서
- 실행 절차: [p0-hardware-quick-run.md](p0-hardware-quick-run.md)
- 설계 결정: [new-map-2 waypoint refresh design](../superpowers/specs/2026-08-22-new-map-2-waypoint-refresh-design.md)
- 협로 실측: [p0-narrow-zone-measurement.md](p0-narrow-zone-measurement.md)
