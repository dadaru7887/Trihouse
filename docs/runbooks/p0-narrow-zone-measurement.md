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

### 어느 컴퓨터의 어느 터미널에서 명령을 실행하는가

실측에는 **컴퓨터 두 대**가 필요하다. 첫 번째는 관제 PC이고, 두 번째는 Pinky 안의
온보드 컴퓨터다. 터미널은 총 네 개를 연다. 여기서 “위치”는 로봇의 물리적 위치가
아니라, **명령을 입력하고 실행하는 셸이 어느 컴퓨터에서 실행 중인가**를 뜻한다.

- 터미널 A·C·D는 관제 PC에서 직접 연다.
- 터미널 B는 관제 PC에서 `ssh`로 Pinky에 접속한 뒤 표시되는 원격 셸이다. 화면은
  관제 PC에 보이지만 명령 자체는 Pinky의 온보드 컴퓨터에서 실행된다.
- 코드 경로, 설치된 ROS package, IP 주소가 두 컴퓨터에서 다르므로 명령을 다른
  터미널에서 실행하면 파일을 찾지 못하거나 다른 ROS graph를 볼 수 있다.
- 특히 관제 PC와 Pinky의 `ROS_DOMAIN_ID`가 다르면 명령이 오류 없이 끝나더라도 DDS가
  상대 노드나 토픽을 발견하지 못한다. 이름이 같은 `/pinky_01/...` 토픽도 서로 다른
  domain에서는 완전히 별개의 통신망이다.

| 터미널 | 명령이 실제로 실행되는 컴퓨터 | 역할 |
|---|---|---|
| **A** | 관제 PC | 시뮬 스택 또는 관제탑 |
| **B** | **Pinky 온보드 컴퓨터 (`ssh` 접속 후)** | 로봇 온보드 노드 + Nav2 |
| **C** | 관제 PC | 자세 읽기 (`pose`) |
| **D** | 관제 PC | 수동 주행 (teleop) |

**`ROS_DOMAIN_ID`는 시뮬레이션 `0`, 실기 `12`이며 절대 섞지 않는다.** 실기에서는
Pinky와 관제 PC의 모든 ROS 터미널이 `12`여야 한다. 시뮬레이션 터미널은 모두 `0`이어야
한다.

---

### 시뮬레이션으로 잴 때

> **먼저 확인할 것.** Gazebo 세계에 벽이 없으면 라이다가 아무것도 못 보고 AMCL이
> 위치를 보정하지 못한다. 그 상태에서 재는 값은 허공을 잰 것이다. 아래 0단계에서
> `new_map_2.yaml`로 충돌 벽을 생성하고 정합을 확인한다.

**터미널 A — 관제 PC.** B 는 필요 없다(시뮬이 로봇 노드까지 띄운다).

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
# 실제 실행 명령은 아래 "0단계"의 격리 DB 절차를 사용한다.
```

---

### 실기 Pinky 로 잴 때

**터미널 B — Pinky 온보드 컴퓨터.** 관제 PC에서 아래 `ssh` 명령을 실행해 Pinky에
접속한다. 접속한 다음 셸 프롬프트에서 이어지는 명령을 실행한다.

```bash
ssh <pinky 계정>@<pinky 주소>
```

```bash
cd ~/Trihouse
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
```

`map_revision`은 임의로 작성하는 버전명이 아니다. 관제 PC에서 지도를 발행할 때
Gateway가 생성한 `<map project>:<hash>` 전체 문자열이다. 이 런북의 격리
`new_map_2` 절차에서는 `new_map_2:<hash>`다. `scripts/p0_reset.sh`를
사용했다면 관제 PC의 저장소에 자동으로 기록된다.

```bash
# 터미널 A — 관제 PC
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
cat .trihouse/map_revision
# 이 런북의 기대 형식: new_map_2:<긴 해시>
```

파일이 없다면 먼저 관제 PC에서 지도를 발행한다. 이 명령은 Gateway의 지도 draft와
published revision을 변경하므로 운영 중인 지도가 없는 준비 단계에서만 실행한다.

```bash
# 터미널 A — 관제 PC
FMS_MAP_PROJECT=new_map_2 \
FMS_PHYSICAL_FEATURES_FILE=control_ui/rmf_control_ui/data/import/trihouse_test_01_physical_features.new_map_2.jsonl \
python3 scripts/p0_publish_map.py new_map_2
# 마지막에 출력되는 TRIHOUSE_MAP_REVISION 값을 사용한다.
```

`hardware_pinky_01.yaml`도 저장소에 미리 들어 있는 파일이 아니다. 벤더 Nav2 설정을
`pinky_01` namespace 아래로 감싼 **생성 결과물**이다. 관제 PC에서 다음 명령으로 만든다.

```bash
# 터미널 A — 관제 PC
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
mkdir -p .trihouse/p0/nav2
scripts/derive_hardware_nav2_params.py \
  --source pinky_pro/pinky_navigation/params/nav2_params.yaml \
  --namespace pinky_01 \
  --initial-pose 0.0570244747,0.1949666005,0.1093261667 \
  --output .trihouse/p0/nav2/hardware_pinky_01.yaml
head -1 .trihouse/p0/nav2/hardware_pinky_01.yaml
# 기대: pinky_01:
```

그다음 생성 파일과 지도를 Pinky로 복사한다. 아래 `<...>` 값은 실제 계정과 주소로
바꾼다.

```bash
# 터미널 A — 관제 PC
ssh <pinky 계정>@<pinky 주소> 'mkdir -p $HOME/maps'
scp control_ui/rmf_control_ui/data/rmf_maps/new_map_2.yaml \
    control_ui/rmf_control_ui/data/rmf_maps/new_map_2.pgm \
    <pinky 계정>@<pinky 주소>:~/maps/
scp .trihouse/p0/nav2/hardware_pinky_01.yaml \
    config/narrow_zones.new_map_2.yaml \
    <pinky 계정>@<pinky 주소>:~/
```

터미널 B에서 실제 값을 변수로 지정한 뒤 launch한다.

```bash
REV='new_map_2:<관제 PC에서 확인한 해시>'
ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  robot_id:=PK_01 namespace:=pinky_01 \
  map:=$HOME/maps/new_map_2.yaml \
  map_revision:="$REV" \
  nav2_params_file:=$HOME/hardware_pinky_01.yaml \
  narrow_zones_file:=$HOME/narrow_zones.new_map_2.yaml \
  narrow_map_name:=new_map_2 \
  control_host:=<관제 PC 의 Ethernet IP> control_port:=8788 \
  2>&1 | tee /tmp/hw.log
```

이 하나가 벤더 bringup(모터·LiDAR·IMU), Nav2, `safety_supervisor`, `fleet_node`,
`status_node`, `fleet_gateway` 를 모두 띄운다. **로봇 위에서 도는 것은 이것뿐이다.**
아래 C·D 명령은 Pinky의 SSH 셸이 아니라 관제 PC에서 연 별도 터미널에서 실행한다.

---

### 측정용 터미널 (C, D — 관제 PC)

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
source /opt/ros/jazzy/setup.bash && source install/setup.bash && source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=12       # 실기 측정. 시뮬레이션 터미널에서는 0
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

`dev_driving` 원본 스크립트를 직접 실행하지 않는다. 가져온 규칙은
`trihouse_pinky_docking.narrow_zone` 한 곳에 정리했고, Fleet action과 safety
supervisor를 거친다. 0단계에서 시뮬레이션을 준비한 뒤 세 단계의 테스트로 검증한다.

### 0단계 — 격리 test DB로 `new_map_2` Gazebo 주행

별도의 `.glb`를 손으로 편집하지 않아도 된다. `p0_up.sh`가 Nav2와 같은
`new_map_2.yaml`의 점유 셀을 읽고, `p0_runtime_assets.py`의
`build_world_with_walls()`로 정적 box 벽을 `.trihouse/p0/world.sdf`에 생성한다. 따라서
지도, Nav2 static layer, Gazebo 충돌 벽이 같은 좌표를 사용한다.

`scripts/p0_reset.sh`는 `trihouse-mysql`의 `trihouse_fms`를 삭제 후 재생성하므로 이
검증에 사용하지 않는다. 아래 전용 Compose는 메모리 DB `mysql_test`, 테스트 Gateway
`18080`, 별도 map runtime volume만 사용한다. 운영·개발 Gateway `8080`과 DB `3306`은
접속하지 않는다.

```bash
# 시뮬레이션 터미널 S1 — 관제 PC: 격리 DB/Gateway와 Gazebo 기동
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
source /opt/ros/jazzy/setup.bash

# linked worktree에는 vendor build 결과가 없을 수 있다. 소스는 submodule로 받고,
# 이미 빌드된 vendor install만 기본 checkout에서 읽는다.
git submodule update --init --recursive pinky_pro
test -e pinky_pro/install || \
  ln -s /home/newuser/Trihouse/pinky_pro/install pinky_pro/install

source pinky_pro/install/setup.bash
export PINKY_NAV2_PARAMS="$PWD/pinky_pro/pinky_navigation/params/nav2_params.yaml"

colcon build --symlink-install --packages-up-to \
  trihouse_pinky_fleet trihouse_pinky_bringup trihouse_rmf_bridge \
  trihouse_omx_adapter
source install/setup.bash

docker compose -f compose.narrow_sim_test.yaml up -d --build
until curl -fsS http://127.0.0.1:18080/ready >/dev/null; do sleep 2; done

FMS_GATEWAY_BASE_URL=http://127.0.0.1:18080 \
FMS_MAP_PROJECT=new_map_2 \
FMS_PHYSICAL_FEATURES_FILE="$PWD/control_ui/rmf_control_ui/data/import/trihouse_test_01_physical_features.new_map_2.jsonl" \
  /usr/bin/python3 scripts/p0_publish_map.py new_map_2 \
  2>&1 | tee /tmp/narrow-map-publish.log
REVISION="$(tail -n 1 /tmp/narrow-map-publish.log)"
test "${REVISION#new_map_2:}" != "$REVISION" || {
  echo "FAIL: 지도 revision 발행 실패"; exit 1;
}
printf '%s\n' "$REVISION"

setsid nohup env \
  ROS_DOMAIN_ID=0 \
  ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET \
  FMS_BASE_URL=http://127.0.0.1:18080 \
  TRIHOUSE_PROJECT=new_map_2 \
  TRIHOUSE_MAP_REVISION="$REVISION" \
  TRIHOUSE_ROBOTS=PK_01 \
  TRIHOUSE_NAV2_MAP="$PWD/control_ui/rmf_control_ui/data/rmf_maps/new_map_2.yaml" \
  PHYSICAL_FEATURES_FILE="$PWD/control_ui/rmf_control_ui/data/import/trihouse_test_01_physical_features.new_map_2.jsonl" \
  control_tower/bringup/p0_simulation_bringup.sh \
  > /tmp/sim.log 2>&1 &
echo "Gazebo/RMF PID=$!; 로그=/tmp/sim.log"
```

PK_01 한 대를 headless로 실행하고 `/tmp/sim.log`에 남긴다. Nav2 두 lifecycle group이
활성화되고 생성된 충돌 벽이 있어야 다음 단계로 간다. `rg`는 사용하지 않는다.

```bash
for unused in $(seq 1 90); do
  test "$(grep -ac 'Managed nodes are active' /tmp/sim.log || true)" -ge 2 && break
  sleep 2
done
grep -a 'Managed nodes are active' /tmp/sim.log | tail -n 2
grep -n '<model name="walls">' .trihouse/p0/world.sdf
# PASS: 한 줄 이상 출력. FAIL: 출력이 없으면 world에 지도 벽이 생성되지 않았다.
```

다른 관제 PC 터미널에서 ROS graph와 보정 gate를 준비한다.

```bash
# 시뮬레이션 터미널 S2 — 관제 PC
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

ros2 action list | grep '/pinky_01/trihouse/transport/execute'
ros2 param set /pinky_01/trihouse_fleet allow_narrow_calibration true
ros2 param get /pinky_01/trihouse_fleet allow_narrow_calibration
# 기대: Boolean value is: True
```

이제 실물과 같은 `ExecuteTransport` action으로 냉동 진입→탈출을 한 번 실행한다.

```bash
set -o pipefail
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q -s \
  tests/simulation/test_narrow_zone_drive.py \
  --enable-sim-motion \
  --sim-robot-namespace pinky_01 \
  --sim-destination frozen_storage_loading_dock_01 \
  --sim-phase roundtrip \
  2>&1 | tee "/tmp/narrow_sim_attempt_$(date +%Y%m%d_%H%M%S).log"
```

테스트가 끝나거나 중단되면 후보값 실행 gate를 다시 닫는다.

```bash
ros2 param set /pinky_01/trihouse_fleet allow_narrow_calibration false
scripts/sim_teardown.sh
docker compose -f compose.narrow_sim_test.yaml down -v
```

마지막 명령은 `trihouse_narrow_sim_test`의 임시 컨테이너와 test 전용 map runtime
volume만 삭제한다. `trihouse-mysql`과 `trihouse_mysql_data`는 삭제하지 않는다.

실행 중 상태는 시뮬레이션 터미널 S3(관제 PC)에서 확인한다. JSONL은 최종 결과 전에도
매 pose와 gate/goal 전환을 즉시 기록하므로 오류나 강제 종료 뒤에도 남는다.

```bash
# 시뮬레이션 터미널 S3 — 관제 PC: 전체 stack 로그
tail -f /tmp/sim.log

# 다른 창에서 협로 test client와 실제 이동 좌표를 확인
LATEST="$(ls -1t /tmp/trihouse_narrow_pinky_01_*_roundtrip_*.jsonl 2>/dev/null | head -n 1)"
test -n "$LATEST" && tail -f "$LATEST"
```

테스트는 domain이 `0`이 아니거나, `--enable-sim-motion`이 없거나, profile 후보 구조가
불완전하면 실제 goal을 보내지 않는다. 결과 trace는
`/tmp/trihouse_narrow_pinky_01_frozen_storage_loading_dock_01_roundtrip_*.jsonl`에
단계별 이벤트가, 같은 이름의 `.json`에 최종 요약이 남는다.

### 1단계 — 순수 모듈·Fleet 분기

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  trihouse_pinky/test/test_narrow_zone_module.py \
  trihouse_pinky/test/test_narrow_zone_profiles.py \
  trihouse_pinky/test/test_narrow_zone_fleet_orchestration.py
```

여기서는 최단 각도 회전, 실제 이동거리, 감속, timeout/cancel 정지, 창고 진입점 강제,
미실측 profile의 Nav2 fallback 금지, 충전소의 탈출 전용 분기를 검사한다.

### 2단계 — Pinky 한 대 실물 모듈 주행(컴퓨터 두 대, 터미널 네 개)

Pinky launch에 보정 모드를 명시적으로 켠다. 기본값은 `false`다. 아래 A·C·D는
관제 PC의 로컬 셸이고 B만 Pinky에 SSH 접속한 원격 셸이다. 네 터미널 모두 실기
`ROS_DOMAIN_ID=12`여야 한다.

```bash
# 터미널 A — 관제 PC: revision과 전송 파일 준비
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
REV="$(cat .trihouse/map_revision)"
printf '%s\n' "$REV"
# 기대: new_map_2:<hash>. 다르면 실물 launch를 시작하지 않는다.
```

```bash
# 터미널 B — Pinky 온보드 컴퓨터(SSH 접속 후): 로봇 stack 기동
cd ~/Trihouse
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
REV='new_map_2:<관제 PC에서 확인한 해시>'
set -o pipefail
ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  robot_id:=PK_01 namespace:=pinky_01 \
  map:=$HOME/maps/new_map_2.yaml map_revision:="$REV" \
  nav2_params_file:=$HOME/hardware_pinky_01.yaml \
  narrow_zones_file:=$HOME/narrow_zones.new_map_2.yaml \
  narrow_map_name:=new_map_2 \
  allow_narrow_calibration:=true \
  2>&1 | tee "/tmp/narrow_hw_bringup_$(date +%Y%m%d_%H%M%S).log"
```

터미널 C에서는 실제 motor 입력의 발행자가 safety 하나인지와 readiness를 관찰한다.
E-stop 담당자가 로봇 옆에 있고 협로가 비어 있을 때만 D로 넘어간다.

```bash
# 터미널 C — 관제 PC: 안전 gate와 상태 관찰
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
ros2 topic info /pinky_01/cmd_vel -v | tee /tmp/narrow_hw_safety_publishers.log
# PASS: Publisher count 1이고 node name에 safety가 포함된다.
ros2 topic echo /pinky_01/trihouse/status --once
```

관제 PC 터미널 D에서 한 번만 실행한다. `--enable-motion`이 없으면 실제 goal은 항상
skip된다. 출력과 별개로 pose 경로는 JSONL에 즉시 보존된다.

```bash
# 터미널 D — 관제 PC: 1회 roundtrip test
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
set -o pipefail
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q -s \
  tests/hardware/test_narrow_zone_drive.py \
  --enable-motion --robot-namespace pinky_01 \
  --destination frozen_storage_loading_dock_01 --phase roundtrip \
  2>&1 | tee "/tmp/narrow_hw_attempt_$(date +%Y%m%d_%H%M%S).log"

LATEST="$(ls -1t /tmp/trihouse_narrow_pinky_01_*_roundtrip_*.jsonl | head -n 1)"
echo "좌표 로그: $LATEST"
tail -n 20 "$LATEST"
```

테스트는 `/cmd_vel`을 직접 발행하지 않는다. `ExecuteTransport`만 호출하며,
readiness·safety·map revision·action server·`/cmd_vel` 단일 safety 발행자를 모두 확인한
뒤 1회만 시도한다. 실패하면 자동 재시도하지 않고 action을 취소하며 trace를 `/tmp`에
남긴다. 실제 탈출과 `exit_target` 복귀를 확인한 뒤에만 설정의 `measured.exit`을
`true`로 승인한다.

### 3단계 — 공개 주문 전체 통합

2단계 승인 뒤 관제·DB·Gateway·RMF·OMX·Pinky 전체를 띄운 상태에서 실행한다.

```bash
pytest -q tests/hardware/test_narrow_zone_full_stack.py \
  --enable-motion --enable-full-stack \
  --fms-url http://127.0.0.1:8080 --full-stack-timeout 300
```

테스트는 공개 주문 API로 냉동 SKU 주문 하나를 만들고, 냉동 진입 단계와 그 다음 mobile
이동(즉, 협로 탈출 후 이동)이 성공하는지 기다린다. 종료 시 테스트 주문을 취소해 예약과
장치 점유를 반환한다. 냉동 profile이 운영 준비 상태가 아니면 주문 자체를 만들기 전에
중단한다.

`dev_driving`의 `narrow3_rule_based_docking.py`는 `/cmd_vel`을 직접 발행하므로 실기에서
실행하지 않는다. V2의 VLM/RL TODO 경로도 검증된 구현이 아니어서 가져오지 않았다.

### Python 파일을 ML/DL 실험처럼 디버깅할 수 있는가

가능하다. 순수 controller와 test client는 일반 Python이므로 `pytest --pdb`, IDE
breakpoint, `breakpoint()`를 사용할 수 있다.

```bash
# 실패 지점에서 Python debugger 진입
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -s --pdb \
  tests/simulation/test_narrow_zone_drive.py \
  --enable-sim-motion --sim-robot-namespace pinky_01 \
  --sim-destination frozen_storage_loading_dock_01 --sim-phase roundtrip
```

다만 test process와 `fleet_node`는 서로 다른 process다. 위 debugger로는
`tests/hardware/narrow_zone_client.py`의 goal 생성·대기·결과 처리는 단계 실행할 수 있지만,
이미 시뮬 스택에서 실행 중인 `fleet_node.py` 내부로 자동 진입하지는 않는다. Fleet 쪽은
`/tmp/sim.log`와 JSON trace를 먼저 사용하고, 필요할 때 Fleet process를 IDE/debugger로
별도 실행한다.

**실물 로봇이 움직이는 동안 Fleet의 속도 제어 loop에 breakpoint를 걸지 않는다.** process가
정지하면 마지막 속도 명령 이후의 동작을 debugger가 보장하지 못한다. 실물에서는 goal을
보내기 전 validation 구간에만 breakpoint를 쓰고, 움직이는 구간은 로그·trace·영상으로
관측한다. E-stop 담당자는 로봇 옆에 있어야 한다.

## 냉동 탈출이 현재 일반 주문에서 차단되는 이유

탈출 코드가 없어서가 아니다. `config/narrow_zones.new_map_2.yaml`에는 다음 후보가 이미
있다.

```text
도크에서 0.372569 m 전진
→ 입구 yaw 0.0109381190 rad로 회전
→ 0.20 m 후진
→ exit_target (1.1792881155, -1.1896842748, 0.0109381190)
```

이 값은 입고 궤적을 수학적으로 뒤집은 **후보값**이다. 실제 바닥의 바퀴 미끄러짐,
회전 중심 오차, safety 감속·정지, AMCL 오차, 선반과의 실제 여유를 통과했다는 물리 증거가
아직 없다. 그래서 `measured.exit: false`이고, 일반 주문은 냉동에 들어간 뒤 나오지 못하는
상태를 만들지 않도록 진입 자체를 `NARROW_PROFILE_UNMEASURED`로 거절한다.

탈출을 운영 승인하려면 다음 순서로 진행한다.

1. 위 Gazebo `roundtrip` 테스트에서 충돌 없이 `exit_target`으로 돌아오는지 확인한다.
2. Pinky launch에 `allow_narrow_calibration:=true`를 명시하고 실기 domain `12`를 사용한다.
3. E-stop 담당자, 비어 있는 통로, 단일 safety `/cmd_vel` 발행자를 확인한다.
4. 실물에서 `tests/hardware/test_narrow_zone_drive.py --phase roundtrip`을 **자동 재시도 없이
   한 번씩** 실행한다.
5. 매 회차 JSON trace와 최종 AMCL pose를 기록한다. 최소 세 번의 독립 회차에서 벽 접촉이
   없고 최종 pose가 `exit_target` 허용오차 안에 들어오는지 확인한다.
6. 오차가 반복되면 `exit` 거리·각도와 `exit_target`을 실측값으로 조정하고 4단계부터 다시
   실행한다.
7. 물리 검증이 끝난 뒤에만 `measured.exit: true`로 변경한다. 그때부터 냉동 profile 전체가
   `READY`가 되어 일반 창고 주문을 받을 수 있다.

시뮬레이션 성공만으로 `measured.exit`을 `true`로 바꾸지 않는다. 시뮬레이션은 논리,
좌표계, 충돌 형상, action 연결을 검증하지만 실제 마찰과 센서 오차의 측정 증거는 아니다.

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
