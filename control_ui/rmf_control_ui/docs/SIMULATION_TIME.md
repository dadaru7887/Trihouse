# Simulation Time and Real-Time Factor (시뮬레이션 시간 및 실시간 계수, RTF)

Gazebo 안의 시계는 벽시계와 다르게 흐릅니다. 그 비율을 **RTF**(Real-Time
Factor)라고 합니다. RTF 1.0 이면 같은 속도, 0.1 이면 시뮬레이션 1초가 벽시계
10초입니다.

이 문서는 그 값이 **어디서 정해지고**, 왜 이것을 먼저 봐야 하는지를 적습니다.

---

## 1. 왜 중요한가

느려 보이는 것이 불편한 정도가 아닙니다. **RTF 가 낮으면 멀쩡한 설정이 고장난
것처럼 보입니다.** 실제로 겪은 것들입니다.

### 1.1 로봇이 RMF 에 안 붙습니다

RTF 0.097 일 때 이렇게 됐습니다.

```
[map_io]: Read map .../project1_slam.pgm: 43 X 53 map @ 0.05 m/cell
[map_server.rclcpp]: failed to send response to /map_server/change_state
                     (timeout): client will not receive response
```

`map_server` 는 지도를 **제대로 읽었는데** lifecycle 응답이 시간 초과됐습니다.
`lifecycle_manager` 는 성공을 못 받아 activate 로 넘어가지 않았고, `map_server`
는 `inactive` 로 멈췄습니다. 그러면 이렇게 줄줄이 끊깁니다.

```
map_server inactive
  → AMCL 이 지도를 못 받음
  → map→odom TF 가 안 나옴
  → 어댑터가 로봇 자리를 못 읽음 (read_state 가 None)
  → add_robot 을 아예 안 부름
  → /fleet_states 에 robots: []
  → RViz 에 로봇이 안 보임
```

**오류는 저 한 줄뿐입니다.** Gazebo·Nav2·RMF core 는 멀쩡히 살아 있어 겉으로는
정상으로 보입니다.

### 1.2 어댑터가 죽습니다

Nav2 20여 개 노드와 같이 뜨는 중에 `project1_nav2_adapter.py` 가
`add_easy_fleet` 안에서 SIGSEGV(-11) 로 죽은 적이 있습니다.

```
[ERROR] [python3-21]: process has died [pid 229066, exit code -11]
```

한가할 때 같은 명령을 손으로 돌리면 멀쩡히 뜹니다. 부하가 걸린 순간에만 나는
rmf_adapter 쪽 경합이라 우리가 고칠 수 없어서, launch 에 `respawn` 을
걸어 두었습니다. 근본 원인은 부하, 곧 RTF 입니다.

### 1.3 속도를 잘못 진단하게 만듭니다 — 가장 비쌌던 것

RTF 0.082 에서 로봇이 12초 동안 손가락 두 마디만큼 움직였습니다. 시뮬레이션
시간으로는 명령한 0.2 m/s 그대로였는데, 벽시계로 보면 12배 느립니다.

이것을 **로봇이 느린 것**으로 읽고 속도 설정을 건드리면 이렇게 굴러갑니다.

```
직진 속도를 0.02 m/s 로 낮춤
  → Nav2 progress checker (10초에 0.5m) 를 정상 주행이 통과 못 함
  → "Failed to make progress" → 복구 동작 (제자리 회전·후진)
  → 바퀴만 돌고 몸은 안 움직임 → odom 에 헛회전이 쌓임
  → AMCL 이 되돌리느라 map→odom 이 46도 틀어짐
  → 앱 화면(odom 기반)과 RViz(map 기반) 의 로봇 위치가 1m 넘게 어긋남
  → 로봇이 픽업 지점에 영영 못 감
```

**시작은 RTF 하나였습니다.** 화면에 보이는 증상은 전혀 다른 세 가지였고요.

> 느려 보인다고 로봇 속도를 낮추지 마세요. 먼저 RTF 를 재세요.

### 1.4 시간에 기대는 판정이 다 흔들립니다

Nav2 와 RMF 는 **시뮬레이션 시간**으로 판단합니다(`use_sim_time: true`).
그래서 RTF 가 낮아도 판정 자체는 맞습니다. 흔들리는 것은 **시뮬레이션 시간을
안 쓰는 것들**입니다.

- lifecycle 서비스 응답 타임아웃 (§1.1)
- 배포 스크립트의 준비 대기 (`MAP_READY_WAIT`, 기본 25초 — 벽시계)
- 실행 스크립트의 Gazebo·어댑터 대기 (`GAZEBO_WAIT`, `ADAPTER_WAIT`)
- 사람의 인내심

RTF 0.1 이면 이 벽시계 기준들을 10배로 잡아야 맞습니다.

---

## 2. 재는 법

`/clock` 이 얼마나 흘렀는지를 벽시계와 견줍니다.

```bash
export ROS_DOMAIN_ID=22        # 맵의 도메인
source /opt/ros/jazzy/setup.bash

ros2 topic echo /clock --once  # sec 를 적어 두고
sleep 10
ros2 topic echo /clock --once  # 다시 적어서 차이를 10 으로 나눕니다
```

실측한 값입니다.

```
sim 1.45초 / wall 14.98초  →  RTF 0.097
```

곁들여 보면 좋은 것 — 라이다가 설정대로 나오는지입니다. 이것이 곧 RTF 입니다.

```bash
ros2 topic hz /pinky_01/scan   # 설정 10 Hz 인데 1.08 Hz 로 나왔습니다
```

---

## 3. 어디서 정해지나

### 3.1 물리 설정 — `<맵>.world`

```xml
<physics name="10ms" type="ode">
  <max_step_size>0.01</max_step_size>
  <real_time_factor>1.0</real_time_factor>
  <dart>
    <collision_detector>bullet</collision_detector>
  </dart>
</physics>
```

**이 파일은 손으로 고쳐도 다음 배포에 덮어써집니다.** 나오는 곳이 우리 코드가
아닙니다.

| 부분 | 만드는 곳 |
|---|---|
| `<physics>` 블록 전체 | `rmf_building_map_tools` 의 `templates/gz_world.sdf` |
| `<collision_detector>bullet</collision_detector>` | 우리 [deploy_map.sh](../../openrmf/scripts/deploy_map.sh) 가 덧붙임 |

앱에는 이 값을 고치는 화면이 **없습니다.** 일부러 안 두었습니다 — 아래를 보면
여기를 고쳐서 얻을 것이 거의 없기 때문입니다.

### 3.2 `real_time_factor` 는 목표가 아니라 상한입니다

가장 흔한 오해입니다. `1.0` 은 **"1배보다 빨리 가지 마라"** 는 뜻이지 "1배로
가라" 가 아닙니다. 기계가 못 따라가면 그냥 느려집니다. 그러니 **이 값을 올려도
빨라지지 않습니다.**

`max_step_size` 를 0.01 → 0.02 로 키우면 스텝 수가 절반이라 두 배쯤 빨라질 수
있습니다. 대신 물리 정확도가 떨어져 로봇이 벽을 뚫거나 튑니다. 마지막에 손댈
곳이지 처음에 손댈 곳이 아닙니다.

### 3.3 진짜 비용은 센서입니다 — `pinky_gz.urdf.xacro`

```
~/robosapiens/robot_model/pinky_pro/pinky_description/urdf/pinky_gz.urdf.xacro
```

| 센서 | 줄 | 지금 값 | 무게 |
|---|---|---|---|
| `camera` | 104~ | **1280×720**, `always_on: 1` | 매우 큼 |
| `gpu_lidar` | 69~ | `samples: 180`, 10 Hz | 중간 |
| `imu` | 125~ | 100 Hz | 작음 (렌더링 없음) |

로봇 2대면 이것이 두 벌입니다.

- **해상도가 프레임보다 셉니다.** 30Hz → 5Hz 로 낮춰도 한 장의 비용은 그대로라
  RTF 가 0.097 → 0.082 로 오히려 나빠 보였습니다(측정 오차 범위). 320×240 으로
  줄이면 픽셀이 **24분의 1** 입니다.
- `always_on: 1` 은 **아무도 안 볼 때도 계속 그린다**는 뜻입니다. 관제를 RViz 로
  본다면 카메라 그림을 쓰는 곳이 없습니다.

이 workspace 는 `colcon build` 로 지어 둡니다. 설치 트리가 소스 디렉터리의
심볼릭 링크에 의존하지 않으므로 xacro 를 고친 뒤에는 **다시 빌드해야** 합니다.
빌드가 끝나면 로봇을 다시 스폰해 변경을 반영합니다.

### 3.4 Gazebo GUI

```
gz sim -s (서버)  111% CPU
gz sim -g (GUI)    81% CPU
```

GUI 도 같은 내장 GPU 를 두고 서버와 다툽니다. 관제를 RViz 로 본다면 창이
필요 없습니다. 앱의 실행 창에서 `Gazebo 창` 을 끄면 됩니다.

---

## 4. 손보는 순서

싼 것부터, 그리고 **한 번에 하나씩** 바꾸고 다시 재세요. 두 개를 같이 바꾸면
어느 것이 들었는지 모릅니다.

1. **Gazebo GUI 끄기** — 설정 변경 없음. 앱의 실행 창에서 고릅니다
2. **카메라 해상도 320×240, `always_on: 0`** — 가장 클 것으로 봅니다
3. **로봇 수 줄여 재기** — 대수에 비례하는지 확인용입니다
4. **라이다 `samples` 180 → 90**
5. **`max_step_size` 0.01 → 0.02** — 마지막 수단. 물리가 거칠어집니다

---

## 5. 하지 말아야 할 것

- **로봇 속도를 낮추지 마세요.** §1.3 이 그래서 벌어졌습니다. RTF 는 그대로인데
  로봇만 진짜로 느려지고, Nav2 가 정상 주행을 "끼었다" 로 판정합니다
- **`real_time_factor` 를 올리지 마세요.** 상한이라 효과가 없습니다 (§3.2)
- **`<맵>.world` 를 손으로 고치지 마세요.** 다음 배포에 덮어써집니다 (§3.1)

---

## 6. 관련 문서

- [RMF_NODES.md](RMF_NODES.md) — 시각화 노드가 무엇을 먹고 그리는지. RViz 가 비는
  이유를 여기서 갈라 봅니다
- [MAP_AUTHORING_AND_DEPLOYMENT.md](MAP_AUTHORING_AND_DEPLOYMENT.md) — 배포의
  벽시계 대기값(`MAP_READY_WAIT` 등)
- [COORDINATE_FRAMES.md](COORDINATE_FRAMES.md) — `map` 과 `odom` 이 어떻게 다른지.
  §1.3 의 46도가 무슨 뜻인지 여기 있습니다
