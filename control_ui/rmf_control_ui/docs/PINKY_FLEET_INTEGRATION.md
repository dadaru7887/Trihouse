# Pinky Virtual Robot and Fleet Adapter Integration (Pinky 가상 로봇 · Fleet Adapter 연동)

## 1. 문서 목적

`rmf_control_ui`의 로봇을 앱 안에서 계산하는 **Mock 주행**에서, 실제 ROS 토픽을
주고받는 **Gazebo 가상 Pinky**로 옮기고 Open-RMF Fleet Adapter로 관제하는
과정을 기록합니다.

작업이 여러 날에 걸치고 PC를 옮겨 가며 이어지므로, 어디까지 됐고 무엇이
남았는지 이 문서만 보면 알 수 있어야 합니다.

## 2. 전체 그림

```text
Gazebo Pinky ──odom/scan──▶ [Nav2] ──▶ [RMF Fleet Adapter] ──▶ RMF core
   ▲                                          │              (schedule/traffic)
   └──────────cmd_vel─────────────────────────┘                     │
                                                            rmf-web ──▶ rmf_control_ui
```

## 3. 진행 상황

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | `pinky_pro` 빌드 · Gazebo 가상 Pinky 기동 · `/odom` `/cmd_vel` 확인 | **완료** |
| 2 | RMF core(schedule node, building map server)를 gwanghee 맵으로 기동 | 예정 |
| 3 | 프로젝트별 Fleet Adapter 설정 · 통합 launch 생성 | **완료** (실행 확인 남음) |
| 4 | 앱이 로봇 위치 토픽을 실제로 구독 | **완료** |
| 5 | rmf-web에 연결해 작업 상태까지 RMF에서 받아오기 | 예정 |

## 4. 사전 준비

### 4.1 저장소에 없는 것

다음 두 디렉터리는 **벤더 패키지라 이 저장소에 포함하지 않습니다.** 각 상위
저장소에서 받아 프로젝트 루트에 둡니다.

| 디렉터리 | 내용 |
|---|---|
| `pinky_pro/` | Pinky 로봇 ROS 2 패키지 (bringup, description, gz_sim, navigation, 센서·LED) |
| `open_manipulator/` | ROBOTIS OpenMANIPULATOR 패키지 (bringup, description, moveit_config, 컨트롤러) |

`rmf_maps/<맵이름>/` 아래의 배포 산출물(`building.yaml`, `nav_graphs/0.yaml`,
`*.world`, `generated_models/`)도 저장소에 넣지 않습니다. 앱의 `맵 관리`에서
`배포하기`를 눌러 다시 만듭니다. **`nav_graphs/0.yaml`은 Fleet Adapter에
반드시 필요하므로, 새 PC에서는 배포를 먼저 한 번 돌려야 합니다.**

### 4.2 환경

- Ubuntu 24.04 · ROS 2 Jazzy
- 빌드된 Open-RMF workspace: `$HOME/robosapiens/rmf_ws`

확인:

```bash
source /opt/ros/jazzy/setup.bash
source "$HOME/robosapiens/rmf_ws/install/setup.bash"
ros2 pkg prefix rmf_fleet_adapter
ros2 pkg prefix ros_gz_sim
```

### 4.3 추가로 설치해야 하는 패키지

`pinky_pro` 빌드와 Nav2 연동에 필요합니다. 기본 ROS 설치에는 없습니다.

```bash
sudo apt-get install -y \
  ros-jazzy-gz-ros2-control \
  ros-jazzy-joint-state-publisher \
  ros-jazzy-navigation2 \
  ros-jazzy-nav2-bringup
```

`gz_ros2_control`은 `pinky_gz_sim`의 **빌드 필수 의존**입니다. 없으면
`Could not find a package configuration file provided by "gz_ros2_control"`로
빌드가 멈춥니다.

확인된 버전(2026-08 기준):

```text
ros-jazzy-gz-ros2-control        1.2.19-1noble
ros-jazzy-joint-state-publisher  2.4.1-1noble
ros-jazzy-navigation2            1.3.12-1noble
ros-jazzy-nav2-bringup           1.3.12-1noble
```

## 5. 1단계 — 가상 Pinky 기동과 토픽 확인

### 5.1 빌드

```bash
cd ~/robosapiens/robot_model/pinky_pro
source /opt/ros/jazzy/setup.bash
colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release
```

10개 패키지가 모두 빌드되어야 합니다. `pinky_gz_sim`에서 `parameter_traits`
관련 경고가 나오지만 빌드는 성공합니다.

### 5.2 실행

화면으로 보려면 원래 launch를 씁니다.

```bash
cd ~/robosapiens/robot_model/pinky_pro
source /opt/ros/jazzy/setup.bash && source install/setup.bash
ros2 launch pinky_gz_sim launch_sim.launch.xml
```

화면이 없는 환경(SSH, 원격 세션)에서는 GUI를 뺀 launch를 씁니다. 토픽 확인에는
서버만으로 충분합니다.

```bash
ros2 launch pinky_gz_sim launch_sim_headless.launch.xml
```

`launch_sim_headless.launch.xml`은 원본에서 `gz_args='-g'`로 GUI를 띄우는
include와 카메라 image_bridge만 뺀 것입니다.

### 5.3 검증

토픽이 올라왔는지:

```bash
ros2 topic list
```

`/odom` `/scan` `/cmd_vel` `/joint_states` `/tf` `/clock` `/camera/*`가 보여야
합니다.

위치가 실제로 나오는지:

```bash
ros2 topic hz /odom          # 약 50Hz
ros2 topic echo /odom --once
```

명령으로 움직이는지:

```bash
ros2 topic echo /odom --once --field pose.pose.position.x
ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist \
  '{linear: {x: 0.25}, angular: {z: 0.0}}'   # 3초쯤 뒤 Ctrl-C
ros2 topic echo /odom --once --field pose.pose.position.x
```

### 5.4 확인된 결과

```text
빌드      10개 패키지 성공
/odom     50Hz 발행 (min 0.020s, max 0.026s)
/cmd_vel  전진 3초 → x: 0.000 → 1.287 m 이동
```

토픽은 `pinky_gz_sim/params/pinky_bridge.yaml`이 Gazebo와 ROS 사이를 잇습니다.
로봇 URDF(`pinky_description/urdf/robot.urdf.xacro`)에 들어 있는
`gz-sim-diff-drive-system` 플러그인이 `cmd_vel`을 받아 `odom`을 냅니다.

### 5.5 남은 차이

- 기본 월드가 `pinky_factory.world`입니다. 최종적으로는 배포한
  `rmf_maps/<맵이름>/<맵이름>.world`를 써야 합니다.
- 로봇이 1대입니다. `robo_pinky/src/robo_pinky_sim/config/fleet.yaml`에 정의된
  PK-01, PK-02, PK-03을 각각 네임스페이스로 띄워야 합니다.

여러 대 띄우기는 6.3.2~6.3.4에서 해결하고 실제로 검증했습니다. 배포한
`*.world`를 쓰는 것은 생성된 bringup에 들어가 있으나 아직 돌려보지 않았습니다.

## 6. RMF 설정은 프로젝트마다 만들어진다

맵이 다르면 Waypoint 이름도 충전소 위치도 다릅니다. 전역 `fleet.yaml` 하나를
돌려 쓰면 프로젝트를 바꾸는 순간 spawn 좌표와 charger 이름이 어긋납니다.
그래서 플릿 설정과 생성된 설정 파일을 **맵 프로젝트에 묶어 MySQL에 보관**합니다.

### 6.1 저장 구조 (schema v10)

| 표 | 내용 |
|---|---|
| `map_project_fleets` | 프로젝트당 1행. 플릿 이름과 `rmf_fleet` 블록에 대응하는 설정(JSON) |
| `map_project_robots` | 프로젝트별 로봇. id, 표시 이름, 모델, **종류(이동/설치)**, **값의 출처(Mock/Gazebo/실물)**, `gz_name`, 구획, 자리 Waypoint, spawn 좌표 |
| `map_project_files` | 그 프로젝트에서 만들어진 설정 파일 전부 |
| `map_project_changes` | **언제 무엇을 바꿨는지.** 파일은 덮어쓰기라 지금 모습만 남는다 |

`map_project_files`가 핵심입니다. `building.yaml`, fleet adapter 설정, Gazebo
spawn 목록, launch를 한자리에 모아 두므로 **프로젝트 하나만 열면 배포와 실행에
필요한 것이 전부 보입니다.** 파일이 디스크 여기저기 흩어져 있으면 어느 것이 이
맵의 것인지 알 수 없습니다.

저장할 때마다 다시 만들어 넣으므로 맵과 어긋나지 않고, 지운 파일이 남아 도는
일도 없습니다. 프로젝트를 지우면 설정도 함께 사라집니다(외래 키 CASCADE).

### 6.2 프로필 반경은 로봇 안전 기준에서 가져온다

fleet adapter의 `profile.footprint`와 `vicinity`는 맵 관리에서 이미 입력한
로봇 안전 기준으로 계산합니다.

```text
footprint = 로봇 폭 / 2
vicinity  = 로봇 폭 / 2 + 위치 오차 여유
```

같은 값을 두 곳에 따로 적으면 어긋납니다. 폭 0.2m · 여유 0.05m인 작은 로봇이면
`footprint: 0.100`, `vicinity: 0.150`이 됩니다.

### 6.3 만들어지는 파일

| 파일 | kind | 용도 |
|---|---|---|
| `<맵이름>.building.yaml` | `building` | Open-RMF 건물 맵 |
| `<플릿이름>_config.yaml` | `fleet_adapter` | fleet adapter 설정. **이동 로봇만** 들어가고 `robots[].charger`에 충전 Waypoint 이름이 붙음 |
| `fleet.yaml` | `fleet_sim` | Gazebo에 띄울 로봇 목록. spawn 좌표는 맵 Waypoint에서 가져옴 |
| `<맵이름>.launch.xml` | `launch` | RMF core와 이 프로젝트의 fleet adapter를 함께 띄움 |
| `<맵이름>_bringup.launch.xml` | `bringup` | Gazebo에 이 맵의 월드와 **출처가 Gazebo인 로봇만** 올림. 로봇마다 네임스페이스를 나누고, 종류에 따라 pinky/open_manipulator 설명을 씀 |
| `<맵이름>_gz_bridge.yaml` | `bridge` | Gazebo↔ROS 토픽 다리. 로봇별 토픽을 절대 이름으로 나눔 |
| `robots/<로봇 ID>/…` | `robot` | 로봇 한 대의 등록 정보·spawn launch·토픽·설명 (6.3.5) |
| `run_<맵이름>.sh` | `script` | 전체 실행. Gazebo를 먼저 띄운 뒤 Open-RMF를 올림 |
| `stop_<맵이름>.sh` | `script` | 이 프로젝트로 띄운 프로세스만 정리 |

각 파일에는 **무엇이고 어디에 쓰이는지 설명이 함께 저장**됩니다. 이름만으로는
`building.yaml`과 `fleet.yaml`이 각각 무엇을 하는지 알 수 없기 때문입니다.
`.sh`는 실행 권한이 필요하다고 표시되어 내보낼 때 `chmod +x`됩니다.

`run_<맵이름>.sh`는 **Gazebo를 먼저 띄우고 12초 뒤 Open-RMF를 올립니다.** Gazebo가
먼저 떠야 `/clock`이 나오고, 그래야 `use_sim_time`을 쓰는 RMF 노드가 시간을
맞춥니다. 반대로 하면 RMF가 시간이 멈춘 줄 알고 멈춰 있습니다.

실행 전에 `building.yaml`과 `nav_graphs/0.yaml`이 있는지 먼저 확인하고, 없으면
무엇을 해야 하는지 알려주고 멈춥니다.

`nav_graphs/0.yaml`은 배포 스크립트가 `building.yaml`에서 만듭니다.

launch는 경로를 전부 이 프로젝트 것으로 박습니다. 하나라도 데모 것을 가리키면
지난번처럼 tinyRobot 설정으로 돌아갑니다.

```xml
<arg name="map_dir" default="…/rmf_maps/gwanghee"/>
<arg name="config_file" value="$(var map_dir)/gwanghee.building.yaml"/>
<arg name="config_file" value="$(var map_dir)/gwanghee_pinky_config.yaml"/>
<arg name="nav_graph_file" value="$(var map_dir)/nav_graphs/0.yaml"/>
```

### 6.3.1 스폰되는 로봇의 정체

Pinky에는 **Gazebo용 SDF 모델이 없습니다.** `pinky_gz_sim/models/`에 있는 것은
선반과 매니퓰레이터 메시뿐입니다. 로봇 본체는 xacro로 URDF를 만들어
`robot_description` 토픽에 올린 뒤 그 토픽에서 스폰합니다.

```
robot.urdf.xacro          ← 진입점 (robot name="pinky")
 └ pinky.urdf.xacro       ← 링크·조인트·메시 (실물과 공용)
    └ pinky_gz.urdf.xacro ← is_sim:=True 일 때만 붙는 Gazebo 매크로
```

```
ros2 run ros_gz_sim create -name pinky_01 -topic /pinky_01/robot_description ...
```

메시에서 직접 잰 실체입니다.

| 항목 | 값 |
|---|---|
| 구동 | 2륜 차동구동 + 캐스터 1개 |
| 본체 크기 | 113 × 88 × 107 mm (base_link 충돌 메시) |
| 바퀴 간격 / 반경 | 96.1 mm / 28 mm |
| 총 질량 | 약 1.4 kg |
| 속도·가속 한계 | ±1.0 m/s, ±2.0 m/s² |
| LiDAR | RPLidar C1 — 640샘플, 360°, 0.05~12 m, 10 Hz |
| 카메라 | 전면 1280×720, 30 Hz |
| IMU | 100 Hz |
| 특수 | 램프 제어 플러그인 (`libgz-sim-lamp-control-system.so`) |

폭이 11 cm인 손바닥만 한 로봇입니다. 맵의 로봇 안전 기준을 0.2 m로 두면
`footprint 0.1`이 되어 실측보다 넉넉합니다.

**`is_sim:=True`가 빠지면 안 됩니다.** 그러면 `insert_gz_sim` 매크로가 통째로
빠져 diff drive도 LiDAR도 없는 껍데기가 스폰됩니다. 보이기는 하는데 `cmd_vel`을
줘도 꿈쩍하지 않습니다.

### 6.3.2 네임스페이스는 한 번만 건다

xacro 에 넘기는 `namespace` 인자 **하나**가 세 가지를 함께 정합니다.

1. 노드 네임스페이스 (`/pinky_01/robot_state_publisher`)
2. URDF 링크·프레임 접두사 (`pinky_01/base_link`)
3. Gazebo 플러그인의 토픽 접두사 (`/pinky_01/odom`)

네임스페이스를 두 번 걸면 **1번만 두 배**가 되어 셋이 어긋납니다.

> 지금은 벤더의 `upload_robot.launch.py` 를 쓰지 않고 `robot_description.sh` 로
> 직접 펼칩니다 — 그 launch 가 펼치는 xacro 에서 라이다·카메라·IMU 가 통째로
> 버려지기 때문입니다. 자세한 것은
> [한 월드에 로봇 여러 대](MULTI_ROBOT_NAMESPACES.md) 함정 6 과
> [Nav2 길](NAV2_PATH.md) §7.

```
/pinky_01/pinky_01/robot_state_publisher   ← 노드는 두 겹
/pinky_01/robot_description                ← create 가 기다리는 곳
```

`create`가 기다리는 `robot_description`이 영영 오지 않아 **로봇이 스폰되지 않고
멈춰 있습니다.** 그래서 bringup은 `push-ros-namespace`를 쓰지 않고 launch 인자로만
넘기며, `create`의 `-topic`도 절대 이름으로 적습니다.

### 6.3.3 토픽 다리는 프로젝트마다 새로 만든다

벤더의 `pinky_gz_sim/params/pinky_bridge.yaml`은 이름이 상대 경로(`odom`,
`cmd_vel`)라서 **로봇이 하나일 때만** 맞습니다. 여러 대를 띄우면 전부 같은
`/odom`으로 겹칩니다.

그래서 프로젝트마다 양쪽 다 절대 이름으로 새로 만듭니다. 네임스페이스 해석
규칙에 기대지 않으므로 어긋날 여지가 없습니다.

```yaml
- ros_topic_name: "/pinky_01/odom"
  gz_topic_name: "/pinky_01/odom"
  ros_type_name: "nav_msgs/msg/Odometry"
  gz_type_name: "gz.msgs.Odometry"
  direction: GZ_TO_ROS
```

`clock`과 `tf`는 월드에 하나뿐이라 로봇별로 나누지 않습니다. 프레임 이름은
`frame_prefix`로 이미 갈라져 있어 `/tf`를 함께 써도 섞이지 않습니다.

다리 노드도 **하나만** 띄웁니다. 로봇마다 띄우면 같은 토픽에 다리를 여러 번
놓게 됩니다.

### 6.3.4 검증 — 실제로 두 대를 띄워 확인

돌고 있는 `pinky_factory` 월드에 생성된 bringup으로 두 대를 붙였습니다.

```
=== ROS 노드 ===              ← 두 겹이 아니다
/pinky_01/robot_state_publisher
/pinky_02/robot_state_publisher
/gz_bridge                    ← 다리는 하나

=== gz 모델 ===
    - pinky_01
    - pinky_02

=== ROS 토픽 ===
/pinky_01/odom  /pinky_01/cmd_vel  /pinky_01/scan  …
/pinky_02/odom  /pinky_02/cmd_vel  /pinky_02/scan  …
```

`pinky_01`에만 `cmd_vel`을 주고 둘의 위치를 비교했습니다.

```
pinky_01  0.0284 -> 0.0545   이동 0.0261 m
pinky_02  -0.0000 -> -0.0000  이동 -0.0000 m
```

**한 대만 움직입니다.** 토픽이 겹치지 않는다는 뜻입니다.

이동 거리가 작은 것은 이 PC에서 로봇 3대 + GUI를 함께 돌려 real-time factor가
**0.006**까지 떨어졌기 때문입니다. 실제 운영에서는 `headless:=true`로 띄우십시오.

### 6.3.5 로봇 하나가 디렉터리 하나

로봇 설정을 한 파일에 모아 두면 로봇이 늘수록 어느 줄이 누구 것인지 찾기
어렵습니다. 그래서 **로봇마다 제 디렉터리**를 둡니다.

```
rmf_maps/gwanghee/
├── gwanghee.building.yaml
├── gwanghee_bringup.launch.xml       ← 아래 spawn.launch.xml 들을 include
├── gwanghee_gz_bridge.yaml           ← 실행에 쓰는 통합 다리 설정
├── gwanghee_pinky_config.yaml
├── run_gwanghee.sh / stop_gwanghee.sh
└── robots/
    ├── PK-01/
    │   ├── robot.yaml            이 로봇의 등록 정보
    │   ├── spawn.launch.xml      이 로봇만 Gazebo에 올리는 launch
    │   ├── bridge.yaml           이 로봇이 주고받는 토픽
    │   └── README.md             무엇이고 어디서 고치는지
    └── OMX-01/
        └── …
```

**한 대를 빼거나 옮길 때 그 디렉터리만 보면 됩니다.**

bringup은 이제 로봇 설정을 직접 적지 않고 불러오기만 합니다.

```xml
<!-- PK-01 · 핑키 1호 · 이동 로봇 @ 충전1 -->
<include file="$(var map_dir)/robots/PK-01/spawn.launch.xml"/>
```

두 곳에 같은 것을 적으면 어긋납니다. 로봇의 spawn 설정은 그 디렉터리에만
있습니다. **이 로봇만 따로 시험하려면 그 파일 하나만 돌리면 됩니다.**

```bash
ros2 launch rmf_maps/gwanghee/robots/PK-01/spawn.launch.xml
```

로봇별 `bridge.yaml`에는 `clock`과 `tf`를 넣지 않았습니다. 월드에 하나뿐이라
로봇별 파일에 넣어 두면 이것만 보고 돌렸을 때 같은 토픽에 다리를 두 번 놓게
됩니다. **실행에는 통합 `<맵이름>_gz_bridge.yaml`을 씁니다.**

모든 파일은 같은 등록 정보에서 만들어지므로 서로 어긋나지 않습니다. 손으로
고치면 다음 저장 때 덮어써집니다 — 앱의 `로봇 등록`에서 고칩니다.

각 파일의 내용과 등록 정보가 흘러가는 경로는
[로봇 등록과 디렉터리 구조](ROBOT_REGISTRATION.md)에 따로 정리했습니다.

### 6.4 디스크로 내보내기

로봇 디렉터리도 함께 만들어집니다. 파일 이름에 `..`이 섞이면 배포 디렉터리
밖에 파일을 쓰게 되므로 막습니다 — 로봇 ID는 사람이 타자로 칩니다.

설정의 원장은 MySQL이지만 **`ros2 launch`는 파일만 읽습니다.** 실행하기 전에
`RMF 설정` → `설정 파일` 탭 → `디스크로 내보내기`를 한 번 누르세요.

`rmf_maps/<맵이름>/`에 풀립니다. 배포 산출물(`nav_graphs/0.yaml`, `*.world`)이
이미 그 디렉터리에 있으므로 launch가 한 경로만 가리키면 됩니다. 맵마다 디렉터리가
따로이므로 프로젝트를 바꿔도 서로 덮어쓰지 않습니다.

내보낸 뒤 실행:

```bash
source /opt/ros/jazzy/setup.bash
source $HOME/robosapiens/rmf_ws/install/setup.bash
ros2 launch ~/robosapiens/rmf_maps/<맵이름>/<맵이름>.launch.xml
```

### 6.5 설정 파일 메뉴

왼쪽 메뉴 **`설정 파일`**에서 이 프로젝트의 파일을 설명과 함께 봅니다.

- 파일마다 종류(건물 맵 / Fleet Adapter / 시뮬레이션 로봇 / 실행 / 셸 스크립트)를
  색으로 구분하고, 무엇에 쓰이는지 한 줄 설명이 붙습니다
- 펼치면 내용을 그대로 보고 복사할 수 있습니다
- `디스크로 내보내기`가 `rmf_maps/<맵이름>/`에 전부 풀어 놓습니다

열린 프로젝트가 없으면 그 사실과 함께 `맵 관리로` 가는 길을 알려 줍니다.

### 6.6 앱에서 실행하고 자동으로 정리하기

`설정 파일` 메뉴의 `프로젝트 실행`이 `run_<맵이름>.sh`를 띄웁니다. 띄워 둔 동안은
버튼이 `<맵이름> 중지`로 바뀝니다.

**앱 창을 닫으면 자동으로 정리됩니다.** Flutter의 종료 요청을 가로채
`stop_<맵이름>.sh`를 먼저 돌립니다.

정리되는 범위는 이렇습니다.

| 종료 방식 | 자동 정리 |
|---|---|
| 창 닫기 · 정상 종료 | **된다** |
| 앱이 죽음 · `kill -9` · 전원 차단 | **안 된다** |

강제 종료는 앱 안에서 아무것도 실행되지 않으므로 막을 수 없습니다. 대신 **다음에
앱을 켤 때 알아챕니다.**

실행 스크립트가 남긴 `.<맵이름>.pgid` 를 훑어 그 프로세스 그룹이 아직 살아 있으면
시작하면서 알려 주고, 정리할지 묻습니다.

```
정리되지 않은 프로젝트가 있습니다
· gwanghee (프로세스 그룹 394845)

그대로 두고 새로 띄우면 schedule node 가 부딪혀 엉뚱한 오류로 나타납니다.
                                        [그대로 두기]  [정리]
```

프로세스가 이미 없는 흔적 파일은 조용히 지웁니다. 남지도 않은 것을 두고 알릴
일은 아닙니다.

`로봇 운영` 화면의 백엔드 현황에서 확인하거나 `stop_<맵이름>.sh`를 직접 돌려도
됩니다.

**앱이 띄운 것만 앱이 내립니다.** 터미널에서 직접 띄운 것은 앱을 닫아도
그대로 둡니다 — 남의 프로세스를 말없이 죽이면 곤란합니다.

정리는 두 겹입니다. 먼저 이 프로젝트의 launch 경로로 시작한 프로세스를 이름으로
찾아 내리고, 그다음 실행 스크립트가 남긴 프로세스 그룹을 통째로 끊습니다.
이름으로 못 찾은 자식이 있어도 그룹에서 정리됩니다.

그룹 번호는 실행 스크립트가 `.<맵이름>.pgid`에 직접 적습니다. 앱이 받은 PID는
그룹 리더가 아니어서(실측: pid 391104, pgid 391103) 그 번호로 그룹을 끊으면
엉뚱한 곳을 건드립니다.

### 6.7 로봇 등록 — 스폰보다 먼저

**등록하지 않은 로봇은 스폰할 수 없습니다.** 등록이 이 프로젝트에 어떤 로봇이
있는지 정하는 곳이고, 스폰은 그중 하나를 지도에 올리는 일입니다.

한 번 등록하면 세 곳이 같은 로봇을 봅니다.

| 곳 | 등록에서 가져가는 것 |
|---|---|
| `<플릿이름>_config.yaml` | 로봇 ID, 충전 Waypoint 이름 |
| `<맵이름>_bringup.launch.xml` | gz 이름, spawn 좌표·방향 |
| `<맵이름>_gz_bridge.yaml` | gz 이름 (토픽 네임스페이스) |

등록은 **로봇 메뉴 위쪽 `로봇 등록`** 과 **맵 관리의 `RMF 설정` → 로봇 탭**
두 곳에 있고 같은 목록을 봅니다. 로봇을 다루러 온 사람이 먼저 찾는 곳은 로봇
메뉴라서 거기에도 두었습니다.

`충전 Waypoint에서 만들기`를 누르면 맵의 자리 Waypoint마다 로봇 한 대를 만들고
spawn 좌표와 자리를 한꺼번에 채웁니다. 로봇을 손으로 하나씩 넣는 대신 맵에서
끌어옵니다. 개별 추가·수정도 됩니다. 자리는 맵에 있는 것 중에서 고르므로 이름을
잘못 적을 일이 없습니다.

#### 이동 로봇과 설치 로봇

등록할 때 **종류를 먼저 정합니다.** 여기서 나머지가 다 갈립니다.

| | 이동 로봇 | 설치 로봇 |
|---|---|---|
| 예 | Pinky | OpenMANIPULATOR |
| 자리 | **충전** Waypoint | **설비** Waypoint |
| 구획 자격 | ambient/chilled/frozen | 없음 (배차 대상이 아님) |
| fleet adapter | `robots` 에 들어감 | **안 들어감** |
| Gazebo 설명 | `pinky_description` | `open_manipulator_description` |
| 움직이는 방법 | diff drive · `cmd_vel` | ros2_control 컨트롤러 |
| 다리 놓는 토픽 | odom · cmd_vel · scan · joint_states | joint_states 만 |

**설치 로봇을 플릿에 넣으면 안 됩니다.** fleet adapter가 배차 대상으로 보고 갈
수 없는 곳으로 보내려 합니다. Open-RMF에서 한자리에 붙은 것은 플릿이 아니라
workcell입니다. 그래서 `<플릿이름>_config.yaml`의 `robots`에는 이동 로봇만
들어가고, 설치 로봇은 어떤 것이 있는지만 주석으로 남습니다.

고를 수 있는 설치 로봇 모델은 **xacro가 실제로 펼쳐지고 Gazebo용 컨트롤러
설정이 있는 것만** 넣었습니다. 고를 수 있는데 띄우면 죽는 항목은 없느니만
못합니다.

| 모델 | 컨트롤러 |
|---|---|
| `open_manipulator_x` | joint_state_broadcaster · arm · gripper |
| `omx_f` | joint_state_broadcaster · arm · gripper |
| `omy_3m` | joint_state_broadcaster · arm (**그리퍼 없음**) |

뺀 것: `omy_f3m`은 `realsense2_description`이 있어야 펼쳐지고, `omx_l`·
`omy_l100`은 원격 조종의 leader 쪽이라 설비로 세울 것이 아닙니다.

`omy_3m`에 없는 `gripper_controller`를 올리면 spawner가 기다리다 실패하고 팔까지
안 움직이는 것처럼 보입니다. 그래서 모델마다 컨트롤러 목록을 따로 둡니다.

구획(ambient/chilled/frozen)은 이동 로봇의 관제 배차 입찰 자격입니다.

등록·수정·해제는 **누른 즉시 열린 프로젝트에 저장**됩니다. `프로젝트 저장`을
따로 눌러야만 남는다면 저장했는데 왜 되돌아왔느냐는 혼란이 반복됩니다.

**등록을 해제하면** 그 로봇은 Gazebo에 올라오지 않고 fleet adapter에서도
빠집니다. 지도에 배치되어 있으면 함께 내립니다. 지우기 전에 그 사실을 먼저
알립니다.

스폰 창은 이름을 타자로 치는 칸 대신 **등록된 로봇을 고르는 칸**을 보여 줍니다.
지도에 그릴 종류는 등록한 종류를 그대로 씁니다 — 설치 로봇은 매니퓰레이터로
그립니다. 출발 자리는 등록된 자리 Waypoint로 맞춰 둡니다.

관제 대상이 아닌 **사람·휴머노이드**만 `등록 없이 배치`로 올립니다. 이들은 RMF
설정에 들어가지 않습니다.

### 6.7.15 앱이 실제로 토픽을 받아온다

출처를 Gazebo로 골라도 **화면 숫자는 앱이 계산한 것**이었습니다. 작업 상세의
띠가 그 사실을 경고로 알렸지만, 경고를 없애려면 실제로 받아와야 합니다.

앱에 rclpy·rclcpp 바인딩이 없으므로 `ros2 topic echo`를 자식 프로세스로 띄워
읽습니다. MySQL도 `mysql` 클라이언트를 부르고 노드 확인도 `ros2 node list`를
부르는 것과 같은 방식입니다.

```bash
ros2 topic echo /pinky_01/odom --field pose.pose --csv
# 3.25,1.75,0.0,0.0,0.0,0.3826834,0.9238795
#  x    y   z   qx  qy  qz         qw
```

일곱 개 숫자만 한 줄로 옵니다. 전체 Odometry를 YAML로 받아 파싱하는 것보다
훨씬 쌉니다. 평면을 도는 로봇이라 사원수에서 yaw 하나만 풉니다.

**출처가 Gazebo인 로봇만 구독합니다.** Mock은 앱 안에만 있고, 실물은 아직
Gazebo 토픽을 내지 않습니다.

#### 값이 들어오면 앱은 계산을 멈춘다

```
토픽이 들어오는 동안   위치 = /pinky_01/odom 을 픽셀로 옮긴 값
토픽이 없을 때         위치 = 앱이 100ms마다 계산한 값 (예전 그대로)
```

계산한 값으로 덮어써 버리면 실제로 어디 있는지 알 수 없게 됩니다. 도착 판정도
실제 좌표로 하되, 좌표를 Waypoint로 끌어당기지 않습니다 — 그러면 토픽 값을
덮어쓰게 됩니다.

미터를 픽셀로 옮기는 계산은 등록할 때 spawn 좌표를 만든 것의 역입니다.

```
pixel.x = x_m / metersPerPixel + bounds.left
pixel.y = bounds.bottom - y_m / metersPerPixel
```

#### 3초 넘게 안 오면 끊긴 것으로 본다

구독을 걸어 두기만 하고 값이 안 오는 것과 실제로 오는 것은 다릅니다. 값이 멈춘
것을 실시간으로 착각하면 **로봇이 서 있는 건지 통신이 끊긴 건지 구별할 수
없습니다.** 끊기면 앱 계산으로 되돌아가고 띠도 다시 빨갛게 됩니다.

로봇 등록 카드가 상태를 배지로 보여 줍니다.

| 배지 | 뜻 |
|---|---|
| **토픽 수신** (주황) | 지금 값이 들어오고 있음 |
| **토픽 없음** (빨강) | Gazebo로 골랐는데 값이 안 옴 |
| 배치됨 / 대기 | Gazebo가 아닌 로봇 |

### 6.7.2 작업 상세는 값의 출처를 크게 밝힌다

앱이 계산한 값과 실물에서 온 값은 **같은 자리에 같은 모양으로** 보입니다. 어느
쪽인지 모르고 보면 Mock 주행을 실제 로봇 상태로 착각합니다. 그래서 작업 상세
맨 위에 출처를 크게 세웁니다.

| 출처 | 색 | 뜻 |
|---|---|---|
| 앱 Mock 데이터 | **빨강** | 앱이 100ms마다 계산한 값. ROS가 아예 관여하지 않음 |
| Gazebo 시뮬레이션 | 주황 | Gazebo가 물리를 돌리고 그 결과를 ROS 토픽으로 주고받음 |
| 실제 로봇 | 초록 | 실물 로봇이 보내는 ROS 토픽 |

Mock을 실물로 착각하는 것이 가장 위험해서 빨강으로 세웁니다.

**토픽을 쓰는 경우에는 어떤 토픽인지도 보여 줍니다.** 등록한 gz 이름이
네임스페이스가 되고, `<맵이름>_gz_bridge.yaml`이 다리를 놓는 이름과 같습니다.

```
받기    /pinky_01/odom  ·  /pinky_01/scan  ·  /pinky_01/joint_states
보내기  /pinky_01/cmd_vel
```

설치 로봇은 바퀴도 LiDAR도 없어 `/omx_01/joint_states`만 옵니다.

#### 고른 방식과 실제 출처는 다를 수 있다

**실행 방식을 고르는 것과 값이 실제로 들어오는 것은 다릅니다.** 4단계(rmf-web
연결)가 아직이라 지금은 어떤 방식을 골라도 앱이 토픽을 구독하지 않습니다.

그래서 띠는 **고른 방식이 아니라 실제로 값을 만들어 낸 곳**을 표시하고, 둘이
어긋나면 그 사실을 함께 밝힙니다.

```
🔴 앱 Mock 데이터
   앱이 계산한 값입니다. 실제 로봇도 Gazebo도 아닙니다.
   ┌────────────────────────────────────────────────┐
   │ 실행 방식은 `Gazebo 시뮬레이션`으로 골라 두었지만 │
   │ 앱이 아직 그 토픽을 구독하지 않습니다.            │
   │ 지금 보이는 값은 앱이 계산한 것입니다.            │
   └────────────────────────────────────────────────┘
```

이것을 감추면 이 띠 자체가 거짓말이 됩니다. 4단계가 붙으면
`topicsConnected` 하나만 바꾸면 띠가 따라옵니다.

`복사`를 누르면 출처와 토픽 이름도 함께 복사됩니다.

### 6.7.1 설정 파일 탭

만들어진 파일을 펼쳐 내용을 보고 복사합니다. `프로젝트 저장`을 누르면 이 로봇
목록으로 설정 파일이 다시 만들어집니다.

### 6.8 SQL로 직접 보기

```sql
-- 프로젝트의 설정 파일 목록
SELECT f.file_name, f.kind, LENGTH(f.content) AS 크기, f.generated_at
FROM map_project_files f
JOIN map_projects p ON p.id = f.project_id
WHERE p.map_name = 'gwanghee';

-- fleet adapter 설정 내용
SELECT f.content FROM map_project_files f
JOIN map_projects p ON p.id = f.project_id
WHERE p.map_name = 'gwanghee' AND f.kind = 'fleet_adapter';

-- 프로젝트의 로봇
SELECT r.robot_id, r.gz_name, r.zones, r.charger_waypoint, r.spawn_x, r.spawn_y
FROM map_project_robots r
JOIN map_projects p ON p.id = r.project_id
WHERE p.map_name = 'gwanghee' ORDER BY r.seq;
```

v5 데이터베이스는 `db/migrate_v5_to_v6.sql`을 적용합니다. 기존에 보관하던
`building.yaml`은 설정 파일 목록으로 함께 옮겨집니다.

## 7. Open-RMF 백엔드 — 무엇이고 어떻게 띄우나

### 7.1 백엔드란

로봇 화면의 `Open-RMF 백엔드` 카드는 `ros2 node list` 를 읽어 **관제를 맡는 ROS
노드가 떠 있는지** 봅니다.

| 노드 | 하는 일 |
|---|---|
| `rmf_traffic_schedule_primary` | 모든 로봇의 경로를 한자리에서 잡아 충돌을 막음 |
| `building_map_server` | `building.yaml` 을 읽어 맵을 뿌림 |
| `rmf_dispatcher_node` | 작업을 어느 로봇에 줄지 입찰로 정함 |
| `rmf_traffic_blockade_node` | 좁은 길에서 서로 막히는 것을 푼다 |
| `*_fleet_adapter` | 이 프로젝트의 로봇을 RMF 에 이어 줌 |

노드 하나하나가 무엇을 맡고 무엇이 없으면 무엇이 안 되는지는
[관제 노드별 하는 일](RMF_NODES.md)에 따로 정리했습니다.

**떠 있는 백엔드가 없습니다** 는 이것들이 하나도 없다는 뜻입니다. 앱 Mock 로봇만
쓸 때는 정상입니다 — Mock 은 앱이 제 안에서 굴리므로 RMF 가 필요 없습니다.

Gazebo나 실제 로봇을 쓰려면 백엔드가 있어야 합니다.

### 7.2 앱에서 띄우기

카드의 **`백엔드 띄우기`** 를 누릅니다. 열린 프로젝트의 설정을 디스크로 풀어
놓고 `run_<맵이름>.sh` 를 돌립니다.

```
설정을 디스크로 내보내기  →  Gazebo bringup  →  (12초)  →  Open-RMF
```

Gazebo가 먼저 떠야 `/clock` 이 나오고, 그래야 `use_sim_time` 을 쓰는 RMF 노드가
시간을 맞춥니다. 반대로 하면 RMF 가 시간이 멈춘 줄 알고 멈춰 있습니다.

띄운 뒤 16초쯤 지나 카드가 스스로 다시 확인합니다.

**프로젝트가 없으면 버튼이 잠깁니다.** 어떤 맵으로 띄울지 정해지지 않았기
때문입니다. 맵 관리에서 `프로젝트 열기` 또는 `프로젝트 저장` 을 먼저 하세요.

설정 파일 메뉴의 `프로젝트 실행` 과 같은 일을 합니다. 백엔드가 없다는 것을 알게
된 자리에서 바로 띄울 수 있어야지, 다른 메뉴로 찾아가라고 하면 무엇을 눌러야
하는지 또 헤맵니다.

### 7.2.1 로봇이 안 뜨면

**launch 예외는 bringup 전체를 중단시킵니다.** 패키지 하나를 못 찾으면 그것과
상관없는 로봇까지 안 뜹니다. Pinky 와 OMX 를 함께 등록해 두고
`open_manipulator_description` 이 없으면 **Pinky 도 안 뜹니다.**

실행 스크립트가 띄우기 전에 필요한 패키지를 먼저 확인합니다.

```
없는 ROS 패키지: open_manipulator_description

이 프로젝트의 로봇을 띄우려면 아래를 빌드하고 다시 실행하세요.
  open_manipulator_description  ->  cd $OMX_WS && colcon build
```

예전에는 찾아본 경로 수십 개가 한 줄로 쏟아져 원인을 알기 어려웠습니다.

필요한 패키지는 **등록에서 뽑습니다.**

| 등록에 있는 것 | 요구하는 패키지 |
|---|---|
| Gazebo 이동 로봇 | `pinky_description` |
| Gazebo 설치 로봇 | `open_manipulator_description` |
| Mock·실물만 | (로봇 패키지 없음) |

`GZ_SIM_RESOURCE_PATH` 도 같은 규칙을 따릅니다. 설치 로봇이 없는 프로젝트가
`open_manipulator_description` 을 가리키면, 그것을 쓰지 않는 사람도 bringup 이
통째로 멈춥니다.

빌드해야 하는 것:

```bash
cd ~/robosapiens/open_manipulator
colcon build --packages-select open_manipulator_description open_manipulator_bringup
```

### 7.3 터미널에서 띄우기

```bash
rmf_maps/gwanghee/run_gwanghee.sh
```

화면 없이 돌리려면 `HEADLESS=true` 를 앞에 붙입니다.

office 데모를 띄우려면 `openrmf/scripts/start_backend.sh` 를 씁니다. 이쪽은
rmf-web api-server 를 Docker 로 함께 올리며, **이 프로젝트의 맵이 아니라 office
데모 맵**을 씁니다.

### 7.4 남아 있는 백엔드 정리

떠 있는 것을 모르고 새로 띄우면 schedule node 와 fleet adapter 가 서로 부딪혀
엉뚱한 오류로 나타납니다. 카드에 노드 목록이 보이면 `백엔드 중지` 로 내립니다.

**`백엔드 중지` 는 프로젝트별로만 다룹니다.** 열린 프로젝트와, 프로세스가 돌고
있는 다른 프로젝트를 함께 찾아 각각의 `stop_<맵이름>.sh` 를 돌립니다. 어떤
프로젝트를 내릴지 확인 창에 이름이 나옵니다.

office 데모 스크립트는 **부르지 않습니다.** 두 가지 이유가 있습니다.

- 그 스크립트는 대상을 office 경로(`tinyRobot_config.yaml`)로만 고르므로 맵
  프로젝트로 띄운 백엔드는 애초에 대상이 아닙니다.
- 그 스크립트는 rmf-web API 컨테이너(`docker stop`)까지 내립니다. 그런데
  프로젝트 launch 는 `server_uri:=ws://127.0.0.1:8000/_internal` 로 그 API 를
  씁니다. **프로젝트를 내리면서 프로젝트가 기대는 것을 함께 끊게 됩니다.**

office 데모를 내리려면 터미널에서 `./openrmf/scripts/stop_office.sh` 를 직접
돌립니다.

프로젝트 루트도 `rmf_maps` 가 있는 곳으로 찾습니다. 예전에는
`openrmf/scripts/stop_office.sh` 를 기준으로 찾아서, office 데모를 받지 않은
곳에서는 루트를 아예 못 찾아 중지가 통째로 실패했습니다.

#### 재부모화된 노드

`ros2 launch` 가 죽으면 자식이 init 으로 재부모화됩니다. 프로세스 그룹도 잃고
`ros2 launch <경로>` 라는 이름도 잃어서, **PGID 로도 이름으로도 잡히지
않습니다.** `fleet_manager` 가 그렇게 혼자 남는 일이 있었습니다.

그래서 중지 스크립트가 마지막에 **이 맵 디렉터리를 인자로 물고 있는 프로세스**를
쓸어냅니다. 그 경로를 들고 있으면 이 프로젝트가 띄운 것입니다. 다른 맵이나
관계없는 RMF 는 건드리지 않습니다.

스크립트 자신과 그것을 부른 셸은 거릅니다 — 스크립트 경로에도 맵 디렉터리가
들어 있기 때문입니다.

#### INT → TERM → KILL

rclpy 노드는 TERM 을 받고도 **종료 중에 스레드가 서로를 기다리며 굳는** 일이
있습니다. 거기서 멈추면 노드가 살아남아 다음 실행에서 이름이 겹칩니다.

단계마다 3초 기다렸다가 다음 신호로 올라가고, 마지막에 강제 종료합니다. 좀비는
이미 끝난 것이라 기다리지 않습니다.

#### 유령 노드

강제 종료된 노드는 DDS 에 떠난다고 알리지 못해 `ros2 node list` 에 그대로
남습니다. **실측 약 16초** 걸립니다.

그래서 정리 여부의 판정은 **프로세스 목록으로** 합니다. 노드 목록은 뒤에서
조용히 다시 읽어 화면이 스스로 맞춰지게 둡니다.

프로세스가 없는데 노드만 남아 있으면 카드가 그렇게 말합니다.

```
✓ Open-RMF 백엔드 · 정리했습니다.
  프로세스는 모두 내려갔습니다. 목록에 남은 것은 DDS 가 아직
  떠난 것을 알아채지 못한 흔적이며 곧 사라집니다.
```

예전에는 중지 직후 노드 목록을 한 번만 읽어, 방금 내린 것이 그대로 보였습니다.
**정리가 안 된 것처럼 보이지만 실제로는 끝난 상태**였습니다.

터미널에서는:

```bash
./openrmf/scripts/stop_office.sh     # office 데모
rmf_maps/gwanghee/stop_gwanghee.sh   # 이 프로젝트로 띄운 것
```

앱이 띄운 것은 **창을 닫을 때 자동으로 정리**됩니다. 강제 종료로 남은 것은 다음
실행에서 알아채고 물어봅니다(6.6).

## 8. 다음 단계에서 만들어야 하는 것

### 8.1 Pinky용 Fleet Adapter 설정 — 완료

지난 시도는 office 데모의 `tinyRobot_config.yaml`에 gwanghee nav graph를 물려
실행했습니다. 로봇 이름·속도·회전 반경·배터리 파라미터가 모두 tinyRobot 값이라
그대로는 맞지 않았습니다.

이제 **맵 프로젝트마다** 설정을 만들어 MySQL에 보관합니다. 6절을 참고하세요.
남은 것은 이 설정을 물려 실제로 fleet adapter를 띄우는 launch입니다.

### 8.2 통합 launch — 생성 완료, 실행 확인 남음

프로젝트마다 `<맵이름>.launch.xml`이 만들어집니다. RMF core(schedule·blockade·
building map server·supervisor·dispatcher)와 이 프로젝트의 fleet adapter를 함께
띄웁니다. ROS가 파싱하는 것까지 확인했습니다(`ros2 launch --print-description`).

아직 실제로 띄워 확인하지 않았습니다. 확인 전에 필요한 것:

- 맵에 **충전 카테고리 Waypoint**가 있어야 로봇이 만들어집니다
- `디스크로 내보내기`를 한 번 눌러야 파일이 생깁니다
- 이전 세션의 RMF 노드가 남아 있으면 먼저 정리해야 합니다(7절)

Gazebo는 `<맵이름>_bringup.launch.xml`이 맡고 `run_<맵이름>.sh`가 둘을 순서대로
띄웁니다. 로봇을 네임스페이스로 나눠 여러 대 올리는 것은 실제로 검증했습니다
(6.3.4). 배포한 `*.world`를 쓰는 것은 아직 돌려보지 않았습니다.

### 8.3 앱과 rmf-web 연결 (없음)

`rmf_control_ui`에는 ROS·rmf-web 연결이 없습니다. 로봇은 앱 안에서 계산하는
Mock입니다(`docs/APP_MOCK_ROBOTS.md`).

`openrmf_app/lib/src/rmf_api.dart`(REST)와 `trajectory_client.dart`(WebSocket)에
이미 rmf-web 클라이언트가 있으므로 가져다 쓸 수 있습니다. 연결 대상은
`OPENRMF_APP_RUN_GUIDE.md`에 적힌 것과 같습니다.

```text
rmf-web REST      http://127.0.0.1:8000
rmf-web WebSocket ws://127.0.0.1:8000/_internal
```

이 작업은 1~3단계와 독립적입니다. office 데모만으로도 검증할 수 있어 ROS 쪽
진행과 무관하게 먼저 해도 됩니다.

## 9. 관련 문서

- [로봇 등록과 디렉터리 구조](ROBOT_REGISTRATION.md) — 등록 정보가 어떤 파일로
  흘러가는지, `robots/<로봇 ID>/` 에 무엇이 들어 있는지
- [관제 노드별 하는 일](RMF_NODES.md) — 백엔드를 띄우면 어떤 노드가 올라오고
  무엇이 없으면 무엇이 안 되는지
- [좌표계](COORDINATE_FRAMES.md) — 로봇이 홈1이 아니라 0,0 에 있을 때
- [Gazebo에서 실물 핑키까지 — Nav2 길](NAV2_PATH.md) — 점유격자·Nav2·
  EasyFullControl 어댑터
- [한 월드에 로봇 여러 대](MULTI_ROBOT_NAMESPACES.md) — 네임스페이스가 닿아야
  하는 네 곳과 이번에 밟은 함정 넷
- [맵 작성 및 배포 가이드](MAP_AUTHORING_AND_DEPLOYMENT.md) — 맵을 만들고
  `nav_graphs/0.yaml`을 얻는 과정
- [앱 전용 Mock 로봇 가이드](APP_MOCK_ROBOTS.md) — 지금의 Mock 주행 범위
- [ROS 관제 시스템 Waypoint 아키텍처 매핑](ROS_CONTROL_WAYPOINT_ARCHITECTURE.md)
- [openrmf_app 실행 가이드](../../openrmf/docs/OPENRMF_APP_RUN_GUIDE.md) —
  rmf-web을 거쳐 관제 화면에 붙이는 기존 경로
