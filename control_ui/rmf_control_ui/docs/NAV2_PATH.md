# From Gazebo to a Physical Pinky — The Nav2 Path (Gazebo에서 실물 핑키까지 — Nav2 길)

관련 문서: [값이 오는 곳 셋](THREE_SOURCES.md) · [좌표계](COORDINATE_FRAMES.md) ·
[한 월드에 로봇 여러 대](MULTI_ROBOT_NAMESPACES.md) ·
[관제 노드별 하는 일](RMF_NODES.md)

---

## 1. 왜 이 길인가

최종이 실물 핑키라면 **slotcar를 쓰면 안 됩니다.** RMF 표준 시뮬레이션 로봇인
slotcar는 `robot_path_requests`를 받아 모델을 nav graph 위로 그냥 끌고 갑니다.
라이다도 지도도 안 씁니다. 지금 당장은 제일 빠르지만 실물로 갈 때 통째로
버립니다.

Nav2 길로 가면 Gazebo에서 만든 것이 실물에 **그대로** 갑니다. 바뀌는 것은 맨
아래 한 겹뿐입니다.

```
   RMF 관제 · 배차 · 교통정리          ← 그대로
   EasyFullControl 어댑터              ← 그대로
   Nav2 · AMCL · costmap               ← 그대로
   점유격자 지도                        ← 그대로 (원점만 맞으면)
 ─────────────────────────────────
   /cmd_vel  /odom  /scan
   Gazebo diff_drive    →    진짜 핑키 모터·라이다     ← 여기만 바뀜
```

---

## 2. 지금 어디까지 왔나

| 단계 | 상태 |
|------|------|
| ① 점유격자 지도 | **끝** — 앱이 도면에서 만듭니다 |
| ② Nav2 네임스페이스 정리 | **끝** — 핑키 두 대로 확인했습니다 |
| ③ EasyFullControl 어댑터 | **거의** — 충전 Waypoint 하나가 막고 있습니다 |
| ④ 실물 핑키 | 아직 |

### 실제로 확인한 것

```
/pinky_01/scan        9.91Hz          /pinky_02/scan   9.96Hz
URDF                  pinky_01/…                       pinky_02/…
map → odom            [1.761, −0.638]                  [0.312, −0.299]
노드                   17개                              17개
```

pinky_01에만 `cmd_vel`을 주면 **1.761 → 2.112(0.351m)** 움직이고 pinky_02는
**그대로**입니다. 서로 간섭하지 않습니다.

AMCL이 도면에서 만든 지도(`154 × 172 @ 0.021 m/pix`)로 홈1에서 정확히 자리를
잡습니다. **맞추는 작업은 한 번도 없었습니다.**

### 아직 막혀 있는 곳

어댑터가 뜨고 로봇을 등록하다 죽습니다.

```
[FleetUpdateHandle::add_robot] Unable to find nearest charging waypoint.
```

`building.yaml`에는 **충전1**이 있는데 **Lane이 하나도 안 붙어 있어** nav
graph로 넘어가지 못했습니다. nav graph의 waypoint 8개 중 충전 waypoint가
**0개**입니다.

> **할 일** — 맵 관리에서 **충전1에 Lane을 연결**하고 배포하면 nav graph에
> 들어갑니다. RMF는 로봇을 플릿에 넣을 때 충전 Waypoint를 최소 하나 요구합니다.

---

## 3. ① 점유격자 지도 — 끝

앱이 프로젝트를 내보낼 때마다 **도면에서** 만듭니다.

```
rmf_maps/<맵>/nav2_map/
  <맵>.pgm       그림
  <맵>.yaml      map_server 가 읽는 설명
  README.md      이게 뭐고 SLAM 과 어떻게 비교하는지
```

### 왜 시뮬레이터에서 SLAM을 안 도나

**정확한 도면이 이미 있고, 그 도면이 Gazebo 월드를 만든 바로 그 원본이기
때문입니다.** 도면에서 바로 만들면

- **원점이 RMF 월드에 계산으로 정확히 맞습니다.** 맞추는 작업 자체가 없습니다
- 표류가 없습니다
- 맵을 고치면 다시 만들어집니다

SLAM은 나중에 **진짜 건물**에서 뜹니다. 그때는 원점을 손으로 맞춰야 합니다(§6).

### 시뮬레이터와 같은 것을 그린다

격자가 Gazebo와 다르면 AMCL이 라이다와 지도를 못 맞춥니다. 그래서
`building.yaml`에 나가는 것과 **같은 원본**을 씁니다.

| 격자 | 원본 | Gazebo |
|------|------|--------|
| 다닐 수 있음 | 바닥 다각형 | `floor_1.obj` |
| 벽 | 벽 선분 + 두께 **0.1 m** | `wall_1.obj` |
| 모름 | 바닥 바깥 | — |

벽 두께 0.1 m는 RMF가 정한 값입니다 —
`rmf_building_map_tools/building_map/wall.py`의 `wall_thickness = 0.1`. 생성된
`wall_1.obj`를 재 봐도 정확히 0.1 m입니다.

### 한 칸을 몇 미터로

두 가지를 함께 봅니다.

- **로봇 몸이 여섯 칸은** 되게 — 한 칸이 로봇만 하면 좁은 통로가 통째로 막힌
  것으로 보입니다
- **바닥 짧은 쪽이 120칸은** 되게 — 작은 아레나에서 0.05 m를 쓰면 방 전체가
  쉰 칸밖에 안 되어 AMCL이 맞출 무늬가 없습니다

0.05 m(ROS 관례, `pinky_navigation`의 기존 지도와 같은 값)와 0.01 m 사이로
묶습니다. gwanghee는 짧은 쪽이 2.557 m라 **0.0213 m**가 나옵니다.

### 맞는지 확인한 방법

`map_server`로 띄워서 RMF 좌표 그대로 찍어 봤습니다.

| 지점 | RMF 좌표 | 격자 |
|------|----------|------|
| 홈1 | (1.7607, −0.6376) | 다닐 수 있음 |
| 픽업1 | (0.3176, −0.9018) | 다닐 수 있음 |
| 드랍오프1 | (1.9607, −0.3027) | 다닐 수 있음 |
| 예전 잘못된 자리 | (1.642, **+**1.595) | 격자 밖 |
| 건물 밖 | (−0.40, −1.5) | 모름 |

**맞추는 작업 없이 계산만으로** 전부 제자리에 떨어집니다.

```bash
cd rmf_maps/<맵>/nav2_map
ros2 run nav2_map_server map_server --ros-args -p yaml_filename:=$PWD/<맵>.yaml
ros2 lifecycle set /map_server configure
ros2 lifecycle set /map_server activate
```

---

## 4. ② Nav2 네임스페이스 — 끝

`pinky_navigation/params/nav2_params.yaml`은 로봇 한 대를 전제로 쓰였습니다. 두
대를 올리면 **서로의 라이다를 보고** TF가 충돌합니다.

**벤더 파일은 고치지 않습니다.** 읽어서 로봇마다 다시 씁니다. 벤더가 맞춰 둔
속도·컨트롤러 설정과 주석을 그대로 살리면서 이름만 가릅니다. 실제 파일(337줄)에
돌려 **31개를 바꾸고 경고 0개**입니다.

| | |
|---|---|
| **가름** | `base_frame_id`·`odom_frame_id`·`robot_base_frame`·`local_frame`, local costmap의 `global_frame`, 라이다·오도메트리 토픽 |
| **함께 씀** | `map` 프레임 — 같은 건물이니까요 |

### 맨 위 칸의 노드 이름도 갈라야 합니다

```yaml
amcl:            →   /pinky_01/amcl:
local_costmap:   →   /pinky_01/local_costmap:
```

`amcl:`은 `/amcl`을 뜻합니다. 그대로 두면 `/pinky_01/amcl`에는 **파라미터가
하나도 안 붙고 조용히 기본값으로 돕니다.** 오류도 안 납니다.

### 벤더 파일의 버그 하나

```yaml
initial_pose: [0, 0, 0]      # AMCL이 못 읽습니다
```

AMCL은 `initial_pose.x/.y/.z/.yaw`로 선언합니다. 리스트는 맞는 이름이 없어
**조용히 버려집니다.** 다시 쓸 때 제대로 된 모양으로 고치면서 **로봇을 올린
자리**를 넣습니다. 자리 맞추기에서 고친 spawn 좌표가 그대로 AMCL 초기 위치가
됩니다.

### 지도는 `/map`을 쓸 수 없습니다

RMF의 `building_map_server`가 이미 그 이름으로 `BuildingMap`을 냅니다. 같이
쓰면 한 토픽에 형식이 둘 올라갑니다.

```
/map   Type: ['nav_msgs/msg/OccupancyGrid', 'rmf_building_map_msgs/msg/BuildingMap']
```

`/nav2_map`으로 옮겼습니다. costmap의 `static_layer`도 지도를 따로 구독하는데
벤더 파일에 그 토픽이 안 적혀 있어 기본값 `map`, 즉 `/pinky_01/map`을 보고
있었습니다. 다시 쓸 때 넣어 줍니다.

### `lifecycle_manager`만은 벽시계로 잽니다

전이 응답을 기다리는 시간 제한이 sim 시계에 걸리면 **`Configuring`에서 영영
멈춥니다.** 실제로 `map_server`가 거기서 멈춰 있었습니다. 관리자가 하는 일은
순서대로 켜고 끄는 것뿐이라 벽시계가 맞습니다.

---

## 5. ③ EasyFullControl 어댑터 — 거의

`rmf_demos_fleet_adapter`(slotcar 전용) 대신 `<맵>_nav2_adapter.py`를 앱이
만듭니다. `rmf_adapter.EasyFullControl`이 Python으로 열려 있습니다.

| 방향 | RMF | 로봇 |
|------|-----|------|
| 명령 | `Destination` (nav graph waypoint) | Nav2 `NavigateToPose` |
| 보고 | `RobotState` (위치·배터리) | TF `map → <로봇>/base_footprint` |

**RMF가 아는 이름과 ROS 네임스페이스가 다릅니다** — RMF는 `PK-01`을, ROS는
`pinky_01`을 압니다. 그 짝도 어댑터가 짓습니다.

### 설정은 이미 맞습니다

우리가 만들던 fleet adapter 설정이 `FleetConfiguration.from_config_files`에
**스키마 그대로** 읽힙니다. 플릿 이름·로봇 목록·nav graph를 다 가져옵니다.

### 확인한 것과 막힌 것

어댑터가 떠서 로봇을 RMF에 등록하는 데까지 갑니다. 그다음 §2의 충전 Waypoint
문제로 멈춥니다.

**이 노드가 실물에서도 그대로 돕니다.** Nav2가 아래에서 Gazebo를 몰든 진짜
모터를 몰든 위쪽은 같기 때문입니다.

---

## 6. ④ 실물 핑키 — 마지막

실물 하드웨어를 처음 켜는 날에는 Nav2보다 먼저
[실제 Pinky 최초 기동과 수동 주행 절차](PHYSICAL_PINKY_FIRST_RUN.md)에 따라
모터, `/odom`, `/scan`, TF와 정지를 검증합니다.

바뀌는 것은 맨 아래 한 겹입니다.

1. Gazebo 대신 `pinky_bringup`으로 진짜 모터·라이다를 띄웁니다
2. **진짜 건물을 SLAM으로 뜹니다**

```bash
ros2 launch pinky_navigation map_building.launch.xml
ros2 run nav2_map_server map_saver_cli -f rmf_maps/<맵>/nav2_map/<맵>_slam
```

3. **원점을 맞춥니다.** 여기가 유일하게 손이 가는 곳입니다

SLAM 지도의 원점은 **로봇이 SLAM을 시작한 자리**이고, RMF의 원점은 **도면 그림의
왼쪽 위**입니다. `<맵>_slam.yaml`의 `origin:` 세 숫자를 고쳐서 도면에서 만든
`<맵>.yaml`과 같은 자리를 가리키게 합니다.

맞았는지는 **두 그림을 겹쳐 보면** 압니다. 벽이 어긋나면 아직 안 맞은
것입니다. 도면에서 만든 지도가 그대로 기준자 노릇을 합니다 — 이것이 둘 다
만들어 두는 이유입니다.

> 도면이 실제 건물과 충분히 같다면 SLAM 지도 없이 도면 지도를 그대로 써도
> 됩니다. 많은 현장이 그렇게 합니다. 겹쳐 보고 정하면 됩니다.

---

## 7. 라이다가 아예 안 돌던 세 겹

Nav2를 붙이려다 발견했습니다. **AMCL은 라이다가 없으면 아무것도 못 합니다.**
세 가지가 겹쳐 있었고, 하나만 고쳐서는 안 됐습니다.

**셋 다 오류를 내지 않습니다.** 토픽 이름은 다리(bridge)가 만들어서 보이는데
데이터만 영영 안 옵니다.

### 겹 ① 월드에 센서 시스템이 없다

월드는 `rmf_building_map_tools`가 제 템플릿(`gz_world.sdf`)에서 만드는데,
거기에는 시스템 플러그인이 **셋뿐**입니다 — Physics · UserCommands ·
SceneBroadcaster. RMF의 시범 로봇(slotcar)은 라이다를 안 쓰니 필요가
없었습니다.

실행 스크립트가 **매번 채웁니다**(`ensure_world_sensors`). 배포할 때마다 월드가
다시 만들어지므로 한 번 넣고 마는 것으로는 안 됩니다.

```xml
<plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
  <render_engine>ogre2</render_engine>
</plugin>
<plugin filename="gz-sim-imu-system" name="gz::sim::systems::Imu"/>
```

### 겹 ② 헤드리스에 렌더링이 없다

`gz sim -s`는 그릴 자리가 없습니다. **gpu_lidar는 GPU로 거리를 잽니다.** 그릴
자리가 없으면 아무것도 발행하지 않습니다. bringup에 헤드리스 렌더링 옵션을
넣었습니다.

> XML 주석 안에는 붙임표 두 개를 쓸 수 없습니다. 옵션 이름을 주석에 그대로
> 적었다가 파일이 깨져 bringup이 통째로 안 떴습니다.

### 겹 ③ 벤더 xacro의 `<gazebo reference>` 접두사

```xml
<link name="rplidar_link"/>                   ← 접두사 없음
<gazebo reference="pinky_01/rplidar_link">    ← 접두사 있음  ✗
  <sensor name="pinky_01/gpu_lidar" type="gpu_lidar">
```

맞는 링크가 없으니 그 `<gazebo>` 블록이 **통째로 버려집니다.** 라이다·카메라·
IMU가 하나도 안 올라가고, 바퀴 마찰(`mu1`·`mu2`·`kp`)도 같이 사라집니다.

링크에 접두사를 안 붙이는 것은 **일부러**입니다 — TF는
`robot_state_publisher`의 `frame_prefix`가 붙입니다. 그러니 `reference` 쪽을
떼는 것이 맞습니다.

**무조건 떼면 안 됩니다.** 조인트 이름에는 접두사가 붙어 있습니다.

```
reference="rplidar_link"                          ← 링크: 뗐음
reference="pinky_01/robot_lamp_mount_fixed_joint" ← 조인트: 그대로
```

가리키는 것이 링크일 때만 뗍니다. 뗀 뒤에도 붙을 곳이 없으면 경고합니다 —
벤더가 파일을 바꾸면 여기 걸립니다. 벤더 파일은 건드리지 않고 펼친 뒤에
고칩니다(`robots/<ID>/robot_description.sh`). OMX에 쓰던 방식과 같습니다.

---

## 8. 로봇 두 대를 올릴 때 — arg 이름이 겹칩니다

pinky_02가 **pinky_01의 URDF로** 올라갔습니다. 라이다도 odom도 안 나왔습니다.

로봇마다 만드는 `spawn.launch.xml`이 저마다 이렇게 선언했습니다.

```xml
<arg name="robot_dir" default="$(dirname)"/>
```

**같은 이름의 `<arg>`를 여러 include가 선언하면 launch 안에서 범위가 겹쳐 먼저
읽은 값이 나머지에 쓰입니다.** PK-02가 PK-01 디렉터리의 스크립트를 돌렸습니다.

arg를 없애고 `$(dirname)`을 쓰는 자리에 직접 적습니다. 파일마다 제 자리를
가리키고 이름이 겹칠 일도 없습니다.

> [한 월드에 로봇 여러 대](MULTI_ROBOT_NAMESPACES.md)의 함정들과 같은 부류입니다
> — 겉으로는 조용하고, 증상은 엉뚱한 데서 나타납니다.

---

## 9. 확인할 때 걸리는 것

### `tf2_echo`는 sim 시간을 켜야 합니다

안 켜면 **프레임이 없다고 나옵니다.** AMCL이 안 도는 것처럼 보여서 한참
헤맸습니다.

```bash
# 이렇게 하면 "Invalid frame ID map ... does not exist"
ros2 run tf2_ros tf2_echo map pinky_01/base_footprint

# 이렇게 해야 보입니다
ros2 run tf2_ros tf2_echo map pinky_01/base_footprint \
  --ros-args -p use_sim_time:=true
```

### 라이다가 도는지 보는 법

토픽 이름이 보이는 것은 아무 뜻이 없습니다 — 다리가 만든 것입니다. **Gazebo
쪽에 발행자가 있는지**를 봐야 합니다.

```bash
gz topic -i -t /pinky_01/scan     # "No publishers" 면 센서가 안 도는 것
ros2 topic hz /pinky_01/scan      # 10Hz 정도 나와야 정상
```

### 머신 용량

Gazebo(라이다 2개) + Nav2 2벌 + RMF + 앱을 한 머신에서 돌리면 **부하 26 / 코어
12**가 나옵니다. 스캔이 시계보다 2~3초 뒤처지고 AMCL이 흔들립니다.

설계 문제가 아니라 용량 문제입니다. **실제 운용에서는 로봇의 Nav2가 로봇 위에서
도므로** 이 부하는 생기지 않습니다. 시뮬레이터에서 여러 대를 함께 시험할 때만
겪습니다.

---

## 10. 점검표

이 순서대로 확인하면 어디서 끊겼는지 알 수 있습니다.

| # | 확인 | 정상 |
|---|------|------|
| 1 | `gz topic -i -t /<로봇>/scan` | 발행자 1 |
| 2 | `ros2 topic hz /<로봇>/scan` | 10Hz 안팎 |
| 3 | `ros2 topic info /nav2_map` | `OccupancyGrid`, 발행자 1 |
| 4 | `ros2 lifecycle get /map_server` | `active` |
| 5 | `ros2 lifecycle get /<로봇>/amcl` | `active` |
| 6 | `tf2_echo map <로봇>/base_footprint` (**sim 시간 켜고**) | 자리가 나옴 |
| 7 | nav graph에 `is_charger` | 최소 1개 |
| 8 | 어댑터 로그 | `RMF 에 붙었습니다` |
