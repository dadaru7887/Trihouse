# Robot Registration and Directory Structure (로봇 등록과 디렉터리 구조)

## 1. 이 문서가 답하는 것

- 로봇 **등록**이 무엇이고 왜 스폰보다 먼저인가
- 등록 정보가 **어떤 파일로 흘러가는가**
- `robots/<로봇 ID>/` 디렉터리에 무엇이 들어 있고 각각 어디에 쓰이는가
- 로봇을 **추가·수정·삭제**할 때 실제로 무슨 일이 일어나는가

관련 문서: [Pinky 가상 로봇 · Fleet Adapter 연동](PINKY_FLEET_INTEGRATION.md) ·
[한 월드에 로봇 여러 대](MULTI_ROBOT_NAMESPACES.md) ·
[값이 오는 곳 셋](THREE_SOURCES.md) · [좌표계](COORDINATE_FRAMES.md) ·
[Nav2 길](NAV2_PATH.md)

## 2. 등록은 스폰보다 먼저다

**등록하지 않은 로봇은 스폰할 수 없습니다.**

```
로봇 등록  ─────▶  로봇 스폰
(무엇이 있는가)     (지도에 올린다)
```

| | 로봇 등록 | 로봇 스폰 |
|---|---|---|
| 하는 일 | 이 프로젝트에 어떤 로봇이 있는지 정함 | 등록된 로봇을 지도에 올림 |
| 결과가 가는 곳 | MySQL + 생성되는 설정 파일 | 화면 위 (앱 Mock 모드) |
| 화면에 보이나 | 안 보임 | 보임 |
| 어디서 | 로봇 메뉴 → `로봇 등록`<br>맵 관리 → `RMF 설정` → 로봇 탭 | 로봇 메뉴 → `로봇 Spawn` |

두 등록 화면은 **같은 목록**을 봅니다. 로봇을 다루러 온 사람이 먼저 찾는 곳이
로봇 메뉴라서 거기에도 두었습니다.

등록·수정·해제는 **누른 즉시** 열린 프로젝트에 저장됩니다. `프로젝트 저장`을
따로 눌러야만 남는다면 저장했는데 왜 되돌아왔느냐는 혼란이 반복됩니다.

## 3. 등록 정보

| 항목 | 뜻 | 어디에 쓰이나 |
|---|---|---|
| **로봇 ID** | 이 로봇의 이름 | fleet adapter 의 `robots` 항목 이름, 디렉터리 이름 |
| **표시 이름** | 사람이 읽는 이름 | 화면 표시 |
| **종류** | 이동 로봇 / 설치 로봇 | 아래 모든 것이 여기서 갈림 |
| **모델** | 어떤 로봇인가 | Gazebo 설명 파일 선택 |
| **Gazebo 이름** | `gz_name` | **토픽 네임스페이스** (`/pinky_01/odom`) |
| **값의 출처** | Mock / Gazebo / 실물 | 실행에 들어가는 자리가 갈림 |
| **자리 Waypoint** | 이 로봇이 서 있는 곳 | spawn 좌표, 충전소 |
| **구획 자격** | ambient / chilled / frozen | 관제 배차의 입찰 자격 (이동 로봇만) |

자리는 맵에 있는 Waypoint 중에서 **고릅니다.** 이름을 타자로 치지 않으므로
잘못 적을 일이 없고, 고르는 순간 spawn 좌표가 함께 채워집니다.

### 3.1 값의 출처

**로봇마다 다릅니다.** 실물 두 대를 돌리면서 한 대만 Gazebo로 시험하는 일이
흔합니다. 화면 전체에 하나로 두면 그런 구성을 담을 수 없습니다.

무엇을 고르느냐에 따라 **실행에 들어가는 자리가 갈립니다.**

| 출처 | fleet adapter | Gazebo bringup | 토픽 다리 | 뜻 |
|---|:---:|:---:|:---:|---|
| **앱 Mock** | ✗ | ✗ | ✗ | 앱이 제 안에서 굴린다. 실제로는 없다 |
| **Gazebo 시뮬레이션** | ✓ | ✓ | ✓ | Gazebo가 물리를 돌리고 토픽으로 주고받는다 |
| **실제 로봇** | ✓ | ✗ | ✗ | 실물이 이미 있다. 시뮬레이터에 또 띄우면 안 된다 |

**기본값은 앱 Mock 입니다.** 등록만 하고 아무것도 안 고른 로봇을 실행에 밀어
넣으면 안 됩니다.

Mock 로봇을 fleet adapter에 넣으면 **오지 않을 로봇의 상태를 계속 기다립니다.**
실물을 Gazebo bringup에 넣으면 **같은 이름이 두 번 뜹니다.** 그래서 생성되는
파일마다 해당하는 로봇만 들어갑니다.

들어가지 않는 로봇도 어떤 것이 있는지는 주석으로 남깁니다. 목록에서 통째로
빠지면 왜 없는지 알 수 없습니다.

```yaml
  robots:
    PK-01:
        charger: "충전1"
    RP-01:
        charger: "충전2"

# 앱 Mock 로봇은 플릿에 넣지 않는다. 실제로는 없는 로봇이다.
# 이 프로젝트의 Mock 로봇:
#   MK-01 · 연습용
```

로봇 디렉터리의 `spawn.launch.xml` 에도 왜 bringup이 부르지 않는지 적어 둡니다 —
파일만 보고 헤매지 않도록.

작업 상세의 출처 띠도 **그 로봇의 등록**을 그대로 씁니다.

### 3.2 이동 로봇과 설치 로봇

등록할 때 **종류를 먼저 정합니다.** 여기서 나머지가 전부 갈립니다.

| | 이동 로봇 | 설치 로봇 |
|---|---|---|
| 예 | Pinky | OpenMANIPULATOR |
| 자리 | **충전** Waypoint | **설비** Waypoint |
| 구획 자격 | ambient / chilled / frozen | 없음 (배차 대상이 아님) |
| fleet adapter | `robots` 에 들어감 | **안 들어감** |
| Gazebo 설명 | `pinky_description` | `open_manipulator_description` |
| 움직이는 방법 | diff drive · `cmd_vel` | ros2_control 컨트롤러 |
| 토픽 | odom · cmd_vel · scan · joint_states · camera_info | joint_states |

**설치 로봇을 플릿에 넣으면 안 됩니다.** fleet adapter 가 배차 대상으로 보고 갈
수 없는 곳으로 보내려 합니다. Open-RMF 에서 한자리에 붙은 것은 플릿이 아니라
**workcell** 입니다.

고를 수 있는 설치 로봇 모델은 xacro 가 실제로 펼쳐지고 Gazebo 용 컨트롤러 설정이
있는 것만 넣었습니다.

| 모델 | 컨트롤러 |
|---|---|
| `open_manipulator_x` | joint_state_broadcaster · arm · gripper |
| `omx_f` | joint_state_broadcaster · arm · gripper |
| `omy_3m` | joint_state_broadcaster · arm (**그리퍼 없음**) |

`omy_3m` 에 없는 `gripper_controller` 를 올리면 spawner 가 기다리다 실패하고
팔까지 안 움직이는 것처럼 보입니다. 그래서 모델마다 컨트롤러 목록이 따로입니다.

## 4. 디렉터리 구조

로봇 설정을 한 파일에 모아 두면 로봇이 늘수록 어느 줄이 누구 것인지 찾기
어렵습니다. **로봇 하나가 디렉터리 하나입니다.**

```
rmf_maps/gwanghee/
├── gwanghee.building.yaml          건물 맵
├── gwanghee.world                  Gazebo 월드
├── nav_graphs/0.yaml               주행 그래프
├── nav2_map/                       Nav2 점유격자 — 도면에서 만든다
│   ├── gwanghee.pgm
│   ├── gwanghee.yaml
│   └── README.md
│
├── gwanghee_pinky_config.yaml      fleet adapter (이동 로봇만)
├── fleet.yaml                      로봇 목록 요약
├── gwanghee_gz_bridge.yaml         ★ 실행에 쓰는 통합 토픽 다리
│
├── gwanghee.launch.xml             Open-RMF 실행
├── gwanghee_bringup.launch.xml     Gazebo 실행 — 아래 것들을 include
├── gwanghee_nav2.launch.xml        Nav2 실행 — 지도 하나 + 로봇마다 한 벌
├── gwanghee_nav2_adapter.py        RMF ↔ Nav2 를 잇는다
├── run_gwanghee.sh                 전체 실행
├── stop_gwanghee.sh                정리
│
└── robots/
    ├── PK-01/
    │   ├── robot.yaml              등록 정보
    │   ├── spawn.launch.xml        이 로봇만 올리는 launch
    │   ├── robot_description.sh    URDF 를 만든다 (벤더 xacro 를 손본다)
    │   ├── nav2.launch.xml         이 로봇의 Nav2
    │   ├── nav2_params.yaml        이 로봇 이름에 맞춘 Nav2 파라미터
    │   ├── bridge.yaml             이 로봇의 토픽 (보기용)
    │   └── README.md               설명
    └── OMX-01/
        ├── robot.yaml
        ├── spawn.launch.xml
        ├── robot_description.sh
        ├── bridge.yaml
        └── README.md
```

설치 로봇에는 `nav2.launch.xml` 과 `nav2_params.yaml` 이 없습니다. 한자리에 붙어
있어 길을 찾을 일이 없습니다.

**한 대를 빼거나 옮길 때 그 디렉터리만 보면 됩니다.**

### 4.1 `robot.yaml` — 등록 정보

이 로봇이 무엇인지 사람이 읽고 확인하는 파일입니다.

```yaml
# PK-01 · 핑키 1호
# rmf_control_ui 가 맵 프로젝트에서 생성했다. 손으로 고치면
# 다음 저장 때 덮어써진다. 고치려면 앱의 로봇 등록에서 고친다.
id: PK-01
name: 핑키 1호
kind: mobile # 이동 로봇
data_source: gazebo # Gazebo 시뮬레이션
model: PINKY-GZ
gz_name: pinky_01 # 토픽 네임스페이스
zones: [ambient, chilled, frozen]
charger_waypoint: 충전1 # 충전 자리
spawn_x: 1.482
spawn_y: 0.517
spawn_heading: 0.000
```

설치 로봇은 `charger_waypoint` 대신 `station_waypoint` 가 되고 `zones` 가
비어 있습니다.

```yaml
kind: workcell # 설치 로봇
model: open_manipulator_x
gz_name: omx_01 # 토픽 네임스페이스
zones: []
station_waypoint: OMX1 # 설비 자리
```

### 4.2 `spawn.launch.xml` — 이 로봇만 올리는 launch

프로젝트 bringup 이 이 파일을 `<include>` 합니다.

**이동 로봇** — `robot_description.sh` 가 URDF 를 만들고
`robot_state_publisher` 가 그것을 토픽에 올리면, `create` 가 그 토픽에서
스폰합니다.

```xml
<launch>
  <group>
    <push-ros-namespace namespace="pinky_01"/>
    <node pkg="robot_state_publisher" exec="robot_state_publisher"
          name="robot_state_publisher" output="screen">
      <param name="use_sim_time" value="True"/>
      <param name="frame_prefix" value="pinky_01/"/>
      <param name="robot_description"
             value="$(command '$(dirname)/robot_description.sh')"/>
    </node>
    <node pkg="joint_state_publisher" exec="joint_state_publisher"
          name="joint_state_publisher" output="screen">
      <param name="source_list" value="[joint_states]"/>
    </node>
    <node pkg="ros_gz_sim" exec="create" output="screen"
          args="-name pinky_01 -topic /pinky_01/robot_description
                -x 1.761 -y -0.638 -z 0.1 -Y 0.000">
      <param name="use_sim_time" value="True"/>
    </node>
  </group>
</launch>
```

> 벤더의 `upload_robot.launch.py` 를 쓰지 않습니다. 그 launch 가 펼치는 xacro 는
> **`<gazebo reference>` 에만 네임스페이스를 붙여서 라이다·카메라·IMU 가 통째로
> 버려집니다.** `robot_description.sh` 가 펼친 뒤 그것을 고칩니다. 벤더 launch 가
> 하던 일(`frame_prefix` · `joint_state_publisher`)은 그대로 맞춰 두었습니다.
> 자세한 것은 [한 월드에 로봇 여러 대](MULTI_ROBOT_NAMESPACES.md) 함정 6.

네임스페이스는 그룹에 **한 번만** 겁니다. 노드에 또 걸면 두 겹이 되어, `create`
가 오지 않을 `robot_description` 을 영영 기다립니다.

1. 노드 네임스페이스 — `/pinky_01/robot_state_publisher`
2. URDF 링크·프레임 접두사 — `pinky_01/base_link`
3. Gazebo 플러그인의 토픽 접두사 — `/pinky_01/odom`

`robot_description.sh` 가 xacro 에 `is_sim:=true` 를 넘깁니다. 이것이 빠지면
diff drive 도 LiDAR 도 없는 껍데기가 스폰됩니다. 보이기는 하는데 `cmd_vel` 을
줘도 꿈쩍하지 않습니다.

**설치 로봇** — xacro 를 직접 펼쳐 올리고 ros2_control 컨트롤러를 붙입니다.

```xml
<launch>
  <group>
    <push-ros-namespace namespace="omx_01"/>
    <node pkg="robot_state_publisher" exec="robot_state_publisher" output="screen">
      <param name="use_sim_time" value="True"/>
      <param name="frame_prefix" value="omx_01/"/>
      <param name="robot_description"
             value="$(command '$(dirname)/robot_description.sh')"/>
    </node>
    <node pkg="ros_gz_sim" exec="create" output="screen"
          args="-name omx_01 -topic robot_description
                -x 4.203 -y 2.011 -z 0.0 -Y 0.000 -allow_renaming true">
      <param name="use_sim_time" value="True"/>
    </node>
    <!-- 팔은 ros2_control 컨트롤러가 움직인다. -->
    <node pkg="controller_manager" exec="spawner" args="joint_state_broadcaster" output="screen"/>
    <node pkg="controller_manager" exec="spawner" args="arm_controller" output="screen"/>
    <node pkg="controller_manager" exec="spawner" args="gripper_controller" output="screen"/>
  </group>
</launch>
```

여기서는 `push-ros-namespace` 를 씁니다. 아래 노드들에 네임스페이스를 따로 걸지
않으므로 두 겹이 되지 않습니다. 이동 로봇 쪽은 include 하는 launch 가 이미
`namespace` 인자를 받으므로 겹쳐 걸면 안 됩니다.

**이 파일 하나만 따로 돌릴 수 있습니다.** 로봇 하나가 안 뜰 때 전체를 띄우지
않고 그것만 볼 수 있습니다.

```bash
ros2 launch rmf_maps/gwanghee/robots/PK-01/spawn.launch.xml
```

### 4.3 `bridge.yaml` — 이 로봇의 토픽 (보기용)

이 로봇이 무엇을 주고받는지 한자리에서 보기 위한 파일입니다.

```yaml
# PK-01 한 대의 토픽 목록.
# 실행에는 프로젝트 전체를 묶은 <맵이름>_gz_bridge.yaml 을 쓴다.
# clock 과 tf 는 월드에 하나뿐이라 여기 넣지 않았다.

- ros_topic_name: "/pinky_01/odom"
  gz_topic_name: "/pinky_01/odom"
  ros_type_name: "nav_msgs/msg/Odometry"
  gz_type_name: "gz.msgs.Odometry"
  direction: GZ_TO_ROS
…
```

**실행에는 이 파일을 쓰지 않습니다.** `parameter_bridge` 는 설정 파일 하나만
받으므로 프로젝트 전체를 묶은 `<맵이름>_gz_bridge.yaml` 을 씁니다. 다리 노드도
하나만 띄웁니다 — 로봇마다 띄우면 같은 토픽에 다리를 여러 번 놓게 됩니다.

`clock` 과 `tf` 는 월드에 하나뿐이라 로봇별 파일에 넣지 않았습니다. 넣어 두면
이것만 보고 돌렸을 때 같은 토픽에 다리를 두 번 놓게 됩니다.

토픽 이름은 **양쪽 다 절대 경로**로 적습니다. 벤더의 `pinky_bridge.yaml` 은 이름이
상대 경로(`odom`, `cmd_vel`)라서 로봇이 하나일 때만 맞습니다. 여러 대를 띄우면
전부 같은 `/odom` 으로 겹칩니다.

| 종류 | 받기 | 보내기 |
|---|---|---|
| 이동 로봇 | `odom` `scan` `joint_states` `camera/camera_info` | `cmd_vel` |
| 설치 로봇 | `joint_states` | 없음 |

### 4.4 `README.md` — 설명

무엇이고 어디서 고치는지 적어 둡니다. 설치 로봇은 올리는 컨트롤러 목록도
함께 들어갑니다.

## 5. 등록 정보가 흘러가는 곳

```
                          ┌──────────────────────────┐
      로봇 등록  ────────▶ │  MySQL                    │
      (앱)                │  map_project_robots       │  ← 원장
                          └────────────┬─────────────┘
                                       │ 프로젝트 저장
                                       ▼
                          ┌──────────────────────────┐
                          │  map_project_files       │
                          └────────────┬─────────────┘
                                       │ 디스크로 내보내기
                                       ▼
       ┌───────────────────────────────┴────────────────────────────┐
       ▼                    ▼                    ▼                  ▼
 robots/<ID>/          <플릿>_config      <맵>_gz_bridge     <맵>_bringup
 robot.yaml            .yaml              .yaml              .launch.xml
 spawn.launch.xml      (이동 로봇만)       (전체 토픽)         (include 만)
 bridge.yaml
 README.md
```

**MySQL 이 원장입니다.** 모든 파일은 등록 정보에서 만들어지므로 서로 어긋나지
않습니다. 저장할 때마다 다시 만들어 넣으므로 지운 로봇의 파일이 남아 도는 일도
없습니다.

`ros2 launch` 는 파일만 읽으므로 실행 전에 `설정 파일` 메뉴에서
`디스크로 내보내기`를 한 번 눌러야 합니다.

### 5.1 bringup 은 적지 않고 불러온다

```xml
<!-- PK-01 · 핑키 1호 · 이동 로봇 @ 충전1 -->
<include file="$(var map_dir)/robots/PK-01/spawn.launch.xml"/>

<!-- OMX-01 · 매니퓰레이터 1호 · 설치 로봇 @ OMX1 -->
<include file="$(var map_dir)/robots/OMX-01/spawn.launch.xml"/>

<!-- 다리는 하나로 묶는다. -->
<node pkg="ros_gz_bridge" exec="parameter_bridge"
      name="gz_bridge" output="screen"
      args="--ros-args -p config_file:=$(var bridge_params)"/>
```

두 곳에 같은 것을 적으면 어긋납니다. 로봇의 spawn 설정은 그 디렉터리에만
있습니다.

### 5.2 fleet adapter 에는 이동 로봇만

```yaml
  robots:
    PK-01:
        charger: "충전1"

# 설치 로봇은 플릿에 넣지 않는다. 배차 대상이 아니다.
# 이 프로젝트의 설치 로봇:
#   OMX-01 · 매니퓰레이터 1호 (open_manipulator_x) @ OMX1
```

설치 로봇도 어떤 것이 있는지는 주석으로 남깁니다. 목록에서 통째로 빠지면 왜
없는지 알 수 없습니다.

## 6. MySQL 저장 구조 (schema v8)

| 표 | 내용 |
|---|---|
| `map_projects` | 맵 프로젝트 |
| `map_project_fleets` | 프로젝트당 1행. 플릿 이름과 `rmf_fleet` 설정 |
| `map_project_robots` | **등록된 로봇** |
| `map_project_files` | 생성된 설정 파일 전부 (로봇 디렉터리 포함) |

```sql
-- 이 프로젝트에 등록된 로봇
SELECT r.robot_id, r.display_name, r.kind, r.model, r.gz_name,
       r.charger_waypoint, r.spawn_x, r.spawn_y
FROM map_project_robots r
JOIN map_projects p ON p.id = r.project_id
WHERE p.map_name = 'gwanghee'
ORDER BY r.seq;

-- 로봇 디렉터리에 들어 있는 파일
SELECT file_name, kind, description
FROM map_project_files f
JOIN map_projects p ON p.id = f.project_id
WHERE p.map_name = 'gwanghee' AND f.file_name LIKE 'robots/%'
ORDER BY file_name;
```

프로젝트를 지우면 로봇과 설정 파일도 함께 사라집니다 (외래 키 CASCADE).

로봇 목록은 `seq` 로 되돌려 읽습니다. `JSON_ARRAYAGG` 는 순서를 보장하지 않아,
정렬하지 않으면 프로젝트를 다시 열 때마다 차례가 뒤바뀝니다.

## 6.1 설정을 바꾼 기록은 따로 남는다

`map_project_files` 는 저장할 때마다 덮어쓰므로 **지금 모습만** 있습니다. 언제
무엇을 바꿨는지는 `map_project_changes` 에 따로 쌓입니다.

```sql
SELECT c.at, c.category, c.action, c.target, c.summary
FROM map_project_changes c
JOIN map_projects p ON p.id = c.project_id
WHERE p.map_name = 'gwanghee'
ORDER BY c.at DESC;
```

| 갈래 | 남는 것 |
|---|---|
| `robot` | 로봇 추가·수정·해제. 무엇이 무엇으로 바뀌었는지까지 |
| `fleet` | 플릿 설정 변경. 값이 달라진 항목만 |
| `file` | 생성 파일이 새로 생기거나 내용이 달라지거나 없어진 것 |
| `project` | 프로젝트를 처음 저장한 것 |

**바뀐 것이 없으면 남기지 않습니다.** 저장을 누를 때마다 줄이 늘면 무엇이 실제로
달라졌는지 오히려 안 보입니다.

앱의 `운영 분석` 메뉴에서 이 기록을 작업·주문·사건과 **같은 시간축**에 놓고
봅니다. 어제까지 되던 것이 오늘 안 되면 그 사이에 무엇을 바꿨는지 함께 봐야
합니다.

## 7. 로봇을 다루는 법

### 7.1 한꺼번에 만들기

`충전 Waypoint에서 만들기` 를 누르면 맵의 자리 Waypoint 마다 로봇 한 대를
만듭니다.

| 맵의 Waypoint 카테고리 | 만들어지는 로봇 |
|---|---|
| 충전 | 이동 로봇 `PK-01`, `PK-02`, … |
| 설비 | 설치 로봇 `OMX-01`, `OMX-02`, … |

spawn 좌표와 자리가 한꺼번에 채워집니다. 필요 없는 것은 등록 해제하면 됩니다.

**로봇 대수는 맵의 자리 수로 정해집니다.** 로봇을 늘리려면 맵에 충전(또는 설비)
Waypoint 를 더 찍으면 됩니다.

### 7.2 하나씩 추가·수정

`로봇 등록` 에서 종류를 고르고 채웁니다. 종류를 바꾸면 자리를 고를 Waypoint
카테고리와 기본 모델이 함께 바뀝니다.

### 7.3 등록 해제

지우기 전에 무엇이 함께 사라지는지 알려 줍니다.

- Gazebo 에 올라오지 않습니다
- fleet adapter 에서도 빠집니다
- 지도에 배치되어 있으면 함께 내립니다

다음 저장 때 그 로봇의 디렉터리 파일도 `map_project_files` 에서 사라집니다.

### 7.4 손으로 고치지 마세요

`robots/` 아래 파일을 편집기로 고치면 **다음 저장 때 덮어써집니다.** 앱의
`로봇 등록` 에서 고칩니다. 각 파일 머리말에도 같은 말이 적혀 있습니다.

## 8. 안전장치

**로봇 ID 는 사람이 타자로 칩니다.** 그 값이 그대로 디렉터리 이름이 되므로
파일 이름으로 쓸 수 없는 글자를 걷어냅니다.

```
robotDirectoryName('PK-01')            → robots/PK-01
robotDirectoryName('../../etc/passwd') → robots/______etc_passwd
```

내보낼 때도 한 번 더 막습니다. 경로에 `..` 이 섞이면 배포 디렉터리 밖에 파일을
쓰게 되므로 그 파일은 건너뜁니다.

## 9. 문제가 생기면

| 증상 | 원인 | 할 일 |
|---|---|---|
| `로봇 Spawn` 이 눌리지 않음 | 등록된 로봇이 없음 | `로봇 등록` 에서 먼저 등록 |
| `충전 Waypoint에서 만들기` 가 아무것도 안 만듦 | 맵에 이름 있는 충전·설비 Waypoint 가 없음 | 맵 관리에서 Waypoint 를 찍고 카테고리와 이름을 넣음 |
| Gazebo 에 로봇이 안 뜨고 멈춰 있음 | `create` 가 기다리는 `robot_description` 이 안 옴 | 네임스페이스가 두 겹인지 확인 (`ros2 node list`) |
| 로봇이 보이는데 `cmd_vel` 을 줘도 안 움직임 | `is_sim:=True` 가 빠져 diff drive 플러그인이 없음 | `spawn.launch.xml` 확인 |
| 팔이 안 움직임 | 없는 컨트롤러를 올려 spawner 가 실패 | 모델의 컨트롤러 목록 확인 (`omy_3m` 은 그리퍼 없음) |
| 로봇 여러 대가 같이 움직임 | 토픽이 겹침 | `gz_name` 이 서로 다른지 확인 |
| `설정 파일` 에 로봇 디렉터리가 없음 | 등록 후 저장하지 않음 | `프로젝트 저장` → `디스크로 내보내기` |

확인용 명령:

```bash
# 네임스페이스가 두 겹인지
ros2 node list | grep pinky
#   /pinky_01/robot_state_publisher        ← 맞다
#   /pinky_01/pinky_01/robot_state_publisher  ← 두 겹

# 토픽이 갈렸는지
ros2 topic list | grep pinky_0

# 한 대만 따로 띄워 보기
ros2 launch rmf_maps/gwanghee/robots/PK-01/spawn.launch.xml
```
