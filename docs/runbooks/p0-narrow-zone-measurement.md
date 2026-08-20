# 협로 진입 규칙 실측 런북

냉동·냉장·상온 도크 앞 좁은 통로를 **규칙 기반**으로 통과시키기 위해 재야 하는 값과
그 절차다. 실행 절차는 [p0-simulation-quick-run.md](p0-simulation-quick-run.md) 를 따르고,
이 문서는 그 위에서 한 번만 하는 측정을 다룬다.

## 왜 Nav2 로는 안 되는가

숫자가 답을 정한다.

| | 값 |
|---|---|
| 냉동 통로 폭 (`trihouse_map_01`, 최선 경로) | **0.20 m** |
| 로봇 필요 폭 (지역 costmap, `footprint_padding` 0.03 포함) | **0.14 m** |
| 남는 여유 | 편측 **0.03 m** |
| AMCL 위치추정 오차 (실측 stddev) | **0.08 ~ 0.11 m** |

**위치추정 오차가 통과 여유의 세 배다.** Nav2 는 절대 좌표로 계획하므로, 로봇이 자기
위치를 3 cm 정확도로 모르는 채 3 cm 틈을 지나야 한다. 좌표를 다시 재도 이 관계는
바뀌지 않는다. 2026-08-19 실측에서 이렇게 나타났다.

```
[planner_server]  [compute_path_to_pose] Aborting handle.
[behavior_server] Running spin  →  Initial checks failed for spin
[behavior_server] Initial checks failed for backup
```

경로 계획 실패 → 복구 동작(후진·회전) → 그것도 실패 → 재시도. 밖에서 보면 로봇이
"나왔다 들어갔다" 를 반복한다.

**규칙 기반은 절대 좌표가 아니라 진입점에서의 상대 이동으로 간다.** 회전 몇 rad,
후진 몇 m 는 오도메트리로 재므로 AMCL 오차가 누적되지 않는다.

## 재는 것

waypoint 좌표는 **다시 재지 않는다.** 지금 지도(`trihouse_map_01`)가 그 좌표를 잰
지도이고, 값도 유효하다. 새로 재는 것은 존마다 넷이다.

| # | 값 | 뜻 |
|---|---|---|
| 1 | **진입점** `cx, cy, yaw` | 통로 앞에서 규칙 주행을 시작하는 자리 |
| 2 | **존 크기** `length, width` | 그 자리를 인식할 직사각형. 통로 방향으로 정렬한다 |
| 3 | **회전 각도** | 바구니(뒤쪽 0.16 m)가 선반을 향하는 yaw |
| 4 | **후진 거리** | 도크까지 몇 m 후진하는가 |

`narrow3_rule_based_docking.py` 의 `ZONES` 와 같은 형식이다. 그 파일에 2026-08-15
실측값이 있으니 **먼저 읽고, 이번 지도에서 다시 확인하는 것**이 순서다.

## 준비

### 어느 터미널에서 무엇을 치는가

실측은 **기계 두 대, 터미널 네 개**로 나뉜다. 어디서 치는지를 틀리면 명령은
성공한 것처럼 보이는데 아무 일도 일어나지 않는다 — 도메인이 다르면 같은 이름의
`pinky_01` 이 서로를 못 본다.

| | 어디서 | 무엇을 |
|---|---|---|
| **A** | 관제 PC | 시뮬 스택 또는 관제탑 |
| **B** | **Pinky 안 (ssh)** | 로봇 온보드 노드 + Nav2 |
| **C** | 관제 PC | 자세 읽기 (`pose`) |
| **D** | 관제 PC | 수동 주행 (teleop) |

**`ROS_DOMAIN_ID` 는 시뮬 0, 실기 52 이며 절대 섞지 않는다.** 로봇과 측정 PC 의
값이 같아야 한다.

---

### 시뮬레이션으로 잴 때

> **먼저 확인할 것.** Gazebo 세계에 벽이 없으면 라이다가 아무것도 못 보고 AMCL 이
> 위치를 고치지 못한다. 그 상태에서 재는 값은 허공을 잰 것이다. 창고 모델을 먼저
> 정합시킨다 — [p0-glb-world-alignment.md](p0-glb-world-alignment.md)

**터미널 A — 관제 PC.** B 는 필요 없다(시뮬이 로봇 노드까지 띄운다).

```bash
cd /home/newuser/Trihouse
scripts/p0_reset.sh new_map_2 && scripts/p0_up.sh
```

---

### 실기 Pinky 로 잴 때

**터미널 B — Pinky 안.** 여기서만 치는 명령이다. 로봇에 ssh 로 들어가서 친다.

```bash
ssh <pinky 계정>@<pinky 주소>
```

```bash
cd ~/Trihouse
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=52
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
```

```bash
ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  robot_id:=PK_01 namespace:=pinky_01 \
  map:=/절대/경로/new_map_2.yaml \
  map_revision:=<발행된 revision> \
  nav2_params_file:=/절대/경로/hardware_pinky_01.yaml \
  control_host:=<관제 PC 의 Ethernet IP> control_port:=8788 \
  2>&1 | tee /tmp/hw.log
```

이 하나가 벤더 bringup(모터·LiDAR·IMU), Nav2, `safety_supervisor`, `fleet_node`,
`status_node`, `fleet_gateway` 를 모두 띄운다. **로봇 위에서 도는 것은 이것뿐이다.**
아래 C·D 는 관제 PC 에서 친다.

---

### 측정용 터미널 (C, D — 관제 PC)

```bash
cd /home/newuser/Trihouse
source /opt/ros/jazzy/setup.bash && source install/setup.bash && source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=0        # 실기면 52
```

**터미널 C — 현재 자세를 찍는 명령.** 측정 내내 쓴다.

```bash
alias pose='python3 -c "
import rclpy, math, time
from rclpy.node import Node
from geometry_msgs.msg import PoseWithCovarianceStamped
rclpy.init(); n=Node(\"p\"); got=[]
n.create_subscription(PoseWithCovarianceStamped,\"/pinky_01/amcl_pose\",got.append,10)
e=time.monotonic()+5
while rclpy.ok() and time.monotonic()<e and not got: rclpy.spin_once(n,timeout_sec=0.2)
if got:
    m=got[-1]; p=m.pose.pose.position; o=m.pose.pose.orientation
    yaw=math.atan2(2*(o.w*o.z+o.x*o.y),1-2*(o.y*o.y+o.z*o.z))
    c=m.pose.covariance
    print(\"x=%.4f y=%.4f yaw=%.4f rad (%.1f deg)\" % (p.x,p.y,yaw,math.degrees(yaw)))
    print(\"stddev  x=%.3f m  y=%.3f m  yaw=%.3f rad\" % (c[0]**0.5, c[7]**0.5, c[35]**0.5))
else: print(\"amcl_pose 없음 — AMCL 이 수렴하지 않았다\")
n.destroy_node(); rclpy.shutdown()"'
```

**터미널 D — 수동 주행.** 띄워 두고 키로 움직인다.

```bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard \
  --ros-args -r /cmd_vel:=/pinky_01/cmd_vel_nav
```

> **`cmd_vel` 이 아니라 `cmd_vel_nav` 다.** 모터용 `/cmd_vel` 의 발행자는
> `safety_supervisor` **하나여야 한다** — 그것이 `cmd_vel_nav` 와 `cmd_vel_dock` 을
> 받아 LiDAR·근접센서·사람 검출을 걸어 모터로 내보낸다. `cmd_vel` 에 직접 쏘면
> 발행자가 둘이 되어 안전 gate 를 우회하는 경로가 생기고, safety 가 내보내는 정지
> 명령과 뒤섞여 로봇이 덜컥거린다. 실기에서는 이것이 사고다.

> **안전 gate 가 측정 동작을 그대로 막는다.** `cmd_vel_nav` 는 `safety_supervisor`
> 를 지나는데, 기본값이 `stop_distance_m 0.30` / `swept_clearance_m 0.191` 이다.
> 재야 하는 동작이 바로 그것들이다 — 도크까지 기어들어가기(전방 0.30 m 안), 통로
> 안에서 제자리 회전(옆벽 0.10 m), 후진(gate 가 **전방** 거리로 판정하므로 앞이
> 막히면 뒤로도 못 간다). 그대로 teleop 을 켜면 키를 눌러도 로봇이 안 움직인다.
>
> **`ros2 param set` 으로는 안 바뀐다.** 노드가 `__init__` 에서 한 번 읽어
> `self.config` 에 담고 파라미터 콜백이 없다. 값만 바뀌고 동작은 그대로다.
>
> 측정 회차에는 gate 를 **낮춘 값으로 다시 띄운다.** 발행자가 하나로 유지되므로
> `cmd_vel` 에 직접 쏘는 것과 다르다. **시뮬 측정 전용이고, 실기에서는 하지 않는다.**
>
> ```bash
> pkill -f safety_supervisor
> ```
> ```bash
> ros2 run trihouse_pinky_safety safety_supervisor --ros-args \
>   -r __ns:=/pinky_01 -r __node:=trihouse_safety_supervisor \
>   -p robot_id:=PK_01 -p use_sim_time:=true \
>   -p require_ultrasonic:=false -p sensor_timeout_s:=2.0 \
>   -p stop_distance_m:=0.03 -p slow_distance_m:=0.05 -p swept_clearance_m:=0.03
> ```
>
> launch 는 `on_exit` 도 `respawn` 도 걸지 않아 이 노드만 죽고 나머지는 산다.
> 측정이 끝나면 `scripts/p0_reset.sh` 부터 다시 해서 원래 임계로 돌린다.

> 협로 안에서는 속도를 최저로 낮춘다. `teleop` 화면에서 `x` 를 여러 번 눌러 선속도를
> **0.06 m/s** 아래로 내린다. `narrow3` 이 쓰는 값이다.

## 절차 — 존 하나마다

냉동(`narrow_3`)을 예로 든다. 냉장·상온도 같다.

### 1. 통로 앞까지 자동 주행

규칙 주행이 시작될 자리까지는 Nav2 가 데려갈 수 있어야 한다. 병목 01 근처까지
자동으로 보내고, 거기서부터 수동으로 바꾼다.

### 2. 진입점을 정하고 기록한다

통로 입구 **바로 앞**, 로봇이 회전할 수 있는 넓이가 남는 마지막 지점이다.

```bash
pose
```

세 값을 적는다 — `cx`, `cy`, `yaw`. **`stddev` 도 함께 적는다.** 0.12 m 를 넘으면
그 자리에서 앞뒤로 조금 움직여 AMCL 을 다시 수렴시킨 뒤 다시 잰다.

> 회전 여유 확인: 로봇이 제자리에서 돌면 지름 **0.40 m** 의 원을 쓸고 지나간다
> (`footprint` 외접반경 0.171 m + padding 0.03). 진입점은 그만한 여유가 있는
> 자리여야 한다. 통로 안에서는 못 돈다.

### 3. 바구니가 선반을 향하도록 회전한다

수동으로 제자리 회전만 시킨다. 바구니(뒤쪽 긴 부분)가 **선반 쪽**을 향하면 멈춘다.

```bash
pose
```

`yaw` 를 적는다. 이것이 시퀀스의 `("rotate", …)` 값이다.

### 4. 후진해 들어간다

로봇팔이 물건을 넣을 수 있는 자리까지 **후진만** 한다. 도중에 방향을 바꾸지 않는다.

```bash
pose
```

진입점과의 거리를 계산한다.

```bash
python3 -c "
import math
cx, cy = 0.000, 0.000      # 2번에서 적은 진입점
x,  y  = 0.000, 0.000      # 방금 적은 도착 지점
print('후진 거리 %.3f m' % math.hypot(x-cx, y-cy))"
```

이것이 `("straight", -거리)` 값이다.

### 5. 존 직사각형을 정한다

`in_oriented_zone()` 이 "지금 이 존 안이다" 를 판정하는 범위다. 통로 방향으로 정렬한
직사각형이고, 원이 아니다 — 좁고 긴 통로에는 원이 맞지 않는다.

| 값 | 기준 |
|---|---|
| `length` | 진행축 방향 길이. 진입점 앞뒤로 판정할 폭. `narrow3` 은 0.05~0.10 m |
| `width` | 통로 폭. **실측한 통로 폭을 그대로** 쓴다 |

통로 폭은 지도에서 확인할 수 있다.

```bash
scripts/p0_show_map.py
```

출력 끝의 도달 가능성 표에 존별 최선 통로 폭이 나온다.

### 6. 나오는 시퀀스도 잰다

입고의 역순이지만 각도는 다르다. 후진했던 만큼 전진 → 회전 → 존을 벗어날 때까지 전진.
`narrow3` 의 `sequence_exit` 형식이다.

## 기록 형식

`narrow3_rule_based_docking.py` 의 `ZONES` 와 같게 적는다.

```python
"narrow_3": {  # 냉동
    "geometry": {
        # 2026-08-__ 실측 (stddev x=__cm/y=__cm/yaw=__deg)
        "cx": 0.000, "cy": 0.000, "yaw": 0.000,
        "length": 0.10, "width": 0.20,
    },
    "sequence": [                    # 입고
        ("straight",  0.00),         # 필요하면 진입점에서 직진
        ("rotate",    0.000),        # 바구니가 선반을 향하는 각도
        ("straight", -0.000),        # 후진 거리
    ],
    "sequence_exit": [               # 출고 — 입고의 역순
        ("straight",  0.000),
        ("rotate",    0.000),
        ("exit_zone", None),
    ],
}
```

**측정 이력을 함께 남긴다.** 날짜, 로봇, stddev, 무엇을 보고 그 값으로 정했는지.
승인된 JSONL 의 `source_measurements` 가 같은 형식이고, 나중에 값이 의심스러울 때
되돌아갈 근거가 된다.

## 검증

세 존을 다 재면 하나씩 돌려 본다. **터미널 D(관제 PC)** 에서 친다 — 로봇 안이 아니다.

```bash
python3 narrow3_rule_based_docking.py narrow_3
```

> **이 스크립트는 `dev_driving` 브랜치의 원본이고 LiDAR 충돌 감지가 없다.** 모터용
> `cmd_vel` 을 직접 발행하므로 `safety_supervisor` 를 통째로 건너뛴다. **실기에서는
> 쓰지 않는다.** 반드시 사람이 로봇 옆에서 지켜보다가 이상하면 Ctrl+C 를 누른다.
>
> 저장소에 들어온 `narrow_zone_pilot` 은 이 전제를 없앤 것이다 — `cmd_vel_nav` 로
> 넣어 velocity_smoother 와 collision_monitor, 그리고 safety 를 그대로 통과한다.
> 실기 검증은 그쪽으로 한다: 존 표를 `config/narrow_zones.<지도>.yaml` 에 넣고
> `scripts/p0_up.sh` 로 올린 뒤 실제 작업을 태운다.

확인할 것:

| | 기대 |
|---|---|
| 존 인식 | 진입점에 서면 스크립트가 "존 안" 으로 판정 |
| 회전 | 바구니가 선반 쪽을 향함 |
| 후진 | 벽에 닿지 않고 도크까지 |
| 나오기 | 왔던 길로 되돌아 나옴 |

## 이것이 임시라는 것

규칙 기반은 **좌표가 지도에 묶여 있다.** 지도를 다시 그리면 진입점과 각도를 전부 다시
재야 한다. 통로 폭이나 선반 위치가 바뀌어도 마찬가지다.

최종형은 [marker-docking-design.md](../architecture/marker-docking-design.md) 의
마커 기반 도킹이다. 마커 상대 좌표로 정렬하므로 지도가 바뀌어도 마지막 구간은 그대로
동작한다. 이 측정값은 그때까지의 다리이고, 도킹이 붙으면 **걷어내는 것이 맞다.**

관련: [p0-simulation-quick-run.md](p0-simulation-quick-run.md) ·
`~/vlm_rl_backup/Trihouse_segmentation/Trihouse/driving_fms/narrow3_rule_based_docking.py`
