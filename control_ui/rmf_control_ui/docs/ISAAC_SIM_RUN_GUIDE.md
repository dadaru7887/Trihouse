# Isaac Sim Virtual Environment Run Guide (Isaac Sim 가상환경 실행 가이드)

이 문서는 RoboSapiens 프로젝트를 Gazebo 대신 NVIDIA Isaac Sim에서 실행하는
절차를 설명합니다. 여기서 **가상환경**은 Python `venv`만을 뜻하지 않고, Isaac
Sim 안에 창고·로봇·센서·물리를 올린 디지털 트윈 실행 환경 전체를 뜻합니다.

관련 문서: [값의 출처](THREE_SOURCES.md) · [좌표계](COORDINATE_FRAMES.md) ·
[Nav2 경로](NAV2_PATH.md) · [로봇 등록](ROBOT_REGISTRATION.md)

NVIDIA 공식 참고 문서:

- [ROS 2 Installation (ROS 2 설치)](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_ros.html)
- [ROS 2 Bridge (ROS 2 연결 다리)](https://docs.isaacsim.omniverse.nvidia.com/latest/py/source/extensions/isaacsim.ros2.bridge/docs/index.html)
- [URDF Importer (URDF 가져오기 도구)](https://docs.isaacsim.omniverse.nvidia.com/latest/importer_exporter/ext_isaacsim_asset_importer_urdf.html)
- [ROS 2 Clock (ROS 2 시뮬레이션 시계)](https://docs.isaacsim.omniverse.nvidia.com/latest/ros2_tutorials/tutorial_ros2_clock.html)
- [ROS 2 Putting It All Together (ROS 2·Nav2 통합 예제)](https://docs.isaacsim.omniverse.nvidia.com/latest/ros2_tutorials/tutorial_ros2_putting_it_all_together.html)

---

## 1. 전체 구조

Isaac Sim을 선택해도 관제·배차·주행 계층은 바뀌지 않습니다. 물리와 센서의
출처만 Gazebo에서 Isaac Sim으로 바뀝니다.

```text
Flutter 관제
    ↓
Open-RMF → Fleet Adapter → Nav2
                            ↓  cmd_vel
                      Isaac Sim ROS 2 Bridge
                            ↓
                    USD 로봇·물리·센서
                            ↓
                   odom · scan · TF · clock
```

RViz는 물리 시뮬레이터가 아닙니다. Gazebo 또는 Isaac Sim과 함께 켤 수도 있고,
`시뮬레이터 없음 + RViz`로 RMF 지도와 경로만 볼 수도 있습니다.

---

## 2. 현재 컴퓨터의 설치 상태

2026-08-15에 확인한 로컬 설치는 다음과 같습니다.

| 항목 | 현재 값 |
|---|---|
| Isaac Sim 소스 | `/home/gyi/isaac/isaacsim` |
| 버전 | `6.0.1-rc.7` |
| release 실행기 | `/home/gyi/isaac/isaacsim/_build/linux-x86_64/release/isaac-sim.sh` |
| standalone Python | `/home/gyi/isaac/isaacsim/_build/linux-x86_64/release/python.sh` |
| Isaac Lab 환경 | `/home/gyi/isaac/env_isaaclab` |
| 프로젝트 ROS | ROS 2 Jazzy |

이 설치는 일반 패키지 설치가 아니라 **소스 빌드**입니다. 따라서 앱 실행기가
기본으로 찾는 `$HOME/isaacsim/python.sh`가 없고, 아래의
`ISAAC_SIM_PYTHON`을 반드시 지정해야 합니다.

현재 세션의 `nvidia-smi`는 NVIDIA 드라이버와 통신하지 못했습니다. 이 상태에서는
Isaac Sim을 실행하기 전에 드라이버·GPU 접근 문제를 먼저 해결해야 합니다.

```bash
nvidia-smi
```

정상이라면 GPU 이름, VRAM, 드라이버 버전이 표로 나옵니다. 오류가 나오면 다음을
확인합니다.

- NVIDIA 커널 모듈이 로드됐는가
- 재부팅 후에도 `nvidia-smi`가 되는가
- 컨테이너라면 GPU가 전달됐는가
- 원격 세션이 GPU 장치를 볼 수 있는가

---

## 3. Python Environments (Python 환경 구분)

Isaac Sim standalone 스크립트를 일반 `python`, 시스템 Python 또는 임의의
`venv`로 실행하면 안 됩니다. `isaacsim`, `omni`, Kit 확장 모듈이 그 Python에
없기 때문입니다.

| 목적 | 실행 방법 |
|---|---|
| Isaac Sim 앱/standalone 스크립트 | Isaac Sim의 `python.sh` |
| Isaac Lab 학습 | `/home/gyi/isaac/IsaacLab/isaaclab.sh` 또는 전용 환경 |
| 외부 RMF/Nav2 ROS 노드 | `/opt/ros/jazzy`와 프로젝트 workspace |
| Flutter 관제 앱 | Flutter 실행 환경 |

이 프로젝트가 자동 생성하는 `isaac/start_<프로젝트>.py`도 반드시 Isaac Sim의
`python.sh`로 실행됩니다.

---

## 4. 터미널 환경 준비

Isaac Sim과 외부 ROS 터미널은 같은 ROS 배포판, RMW 구현, ROS domain을 사용해야
합니다. 하나라도 다르면 오류 없이 서로를 발견하지 못할 수 있습니다.

새 터미널에서 다음을 실행합니다.

```bash
source /opt/ros/jazzy/setup.bash

export ROBOSAPIENS_ROOT=/home/gyi/robosapiens
export ISAAC_SIM_ROOT=/home/gyi/isaac/isaacsim/_build/linux-x86_64/release
export ISAAC_SIM_PYTHON="$ISAAC_SIM_ROOT/python.sh"
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
```

ROS domain은 앱의 프로젝트 설정값과 같아야 합니다. 예를 들어 프로젝트가 22라면:

```bash
export ROS_DOMAIN_ID=22
```

확인:

```bash
test -x "$ISAAC_SIM_PYTHON" && echo "Isaac Python 준비됨"
echo "$ROS_DOMAIN_ID"
echo "$RMW_IMPLEMENTATION"
```

Flutter 앱도 이 환경을 물려받아야 하므로 같은 터미널에서 실행하는 것이 가장
확실합니다.

```bash
cd /home/gyi/robosapiens/rmf_control_ui
flutter run -d linux
```

> `RMW_IMPLEMENTATION`을 Cyclone DDS로 바꾸려면 Isaac Sim과 모든 외부 ROS
> 터미널을 함께 `rmw_cyclonedds_cpp`로 바꿉니다. 한쪽만 바꾸지 마세요.

---

## 5. 프로젝트 산출물 만들기

관제 앱에서 맵 프로젝트를 저장하고 `설정 파일 → 디스크로 내보내기`를 실행합니다.
그러면 다음 파일이 생성됩니다.

```text
rmf_maps/<프로젝트>/
├── run_<프로젝트>.sh
├── stop_<프로젝트>.sh
├── <프로젝트>.launch.xml
├── <프로젝트>_nav2.launch.xml
├── isaac/
│   └── start_<프로젝트>.py
└── robots/
    └── <robot_id>/
```

`start_<프로젝트>.py`는 다음을 담당합니다.

1. Isaac `SimulationApp` 시작
2. ROS 2 Bridge 확장 활성화
3. 지정한 USD stage 열기
4. timeline Play
5. 앱이 끝날 때까지 simulation update

USD 자체는 자동 생성하지 않습니다. 다음 파일은 별도로 준비해야 합니다.

```text
rmf_maps/<프로젝트>/isaac/<프로젝트>.usd
```

USD가 없으면 백엔드 실행기는 RMF/Nav2를 먼저 띄우지 않고 필요한 경로를 출력한
뒤 중단합니다.

---

## 6. Import Pinky URDF to USD (Pinky URDF를 USD로 가져오기)

### 6.1 Generate URDF (URDF 생성)

프로젝트 내보내기가 만든 로봇 설명 스크립트를 사용합니다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/gyi/robosapiens/robot_model/pinky_pro/install/setup.bash

/home/gyi/robosapiens/rmf_maps/project1/robots/pinky_01/robot_description.sh \
  > /tmp/pinky_01.urdf
```

설치 workspace가 다르면 실제 `pinky_description`을 빌드한 workspace의
`install/setup.bash`를 source합니다.

### 6.2 Open Isaac Sim GUI (Isaac Sim GUI 열기)

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=22
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

/home/gyi/isaac/isaacsim/_build/linux-x86_64/release/isaac-sim.sh
```

GUI에서 다음 순서로 진행합니다.

1. `File → Import`에서 `/tmp/pinky_01.urdf` 선택
2. articulation root와 movable base 설정 확인
3. wheel joint 축과 회전 방향 확인
4. collision, mass, inertia 확인
5. stage에 창고 바닥과 벽 배치
6. `/World/Robots/pinky_01`처럼 로봇별 prim path 지정
7. 프로젝트 경로에 USD 저장

예:

```text
/home/gyi/robosapiens/rmf_maps/project1/isaac/project1.usd
```

여러 대라면 prim과 ROS namespace를 분리합니다.

```text
/World/Robots/pinky_01  → /pinky_01/*
/World/Robots/pinky_02  → /pinky_02/*
```

---

## 7. ROS 2 Action Graphs for USD (USD에 필요한 ROS 2 동작 그래프)

ROS 2 Bridge는 확장만 켠다고 토픽을 자동 생성하지 않습니다. USD stage에
OmniGraph/Action Graph를 구성해야 합니다. 또한 publisher와 subscriber는
simulation timeline이 Play 중일 때만 동작합니다.

### 7.1 장면 공통 그래프

| 입력/출력 | 노드 역할 | ROS 이름 |
|---|---|---|
| 출력 | simulation clock | `/clock` |
| 출력 | 공통/로봇 transform | `/tf`, `/tf_static` |

Clock 그래프의 기본 연결은 다음과 같습니다.

```text
On Playback Tick
    ├─ Isaac Read Simulation Time
    └─ ROS2 Publish Clock → /clock
```

### 7.2 이동 로봇별 그래프

| 방향 | 토픽 | 메시지 |
|---|---|---|
| Isaac → ROS | `/<id>/odom` | `nav_msgs/Odometry` |
| Isaac → ROS | `/<id>/scan` | `sensor_msgs/LaserScan` |
| Isaac → ROS | `/<id>/joint_states` | `sensor_msgs/JointState` |
| Isaac → ROS | `/tf`, `/tf_static` | `tf2_msgs/TFMessage` |
| ROS → Isaac | `/<id>/cmd_vel_smoothed` | `geometry_msgs/Twist` |

구동 그래프:

```text
ROS2 Subscribe Twist (/<id>/cmd_vel_smoothed)
    → Break linear/angular vector
    → Differential Controller
    → Articulation Controller
    → left/right wheel joints
```

센서·상태 그래프:

```text
On Physics Step
    ├─ Compute Odometry → ROS2 Publish Odometry
    ├─ Joint State Reader → ROS2 Publish Joint State
    ├─ RTX/physics LiDAR → ROS2 Publish Laser Scan
    └─ Transform Tree → ROS2 Publish Transform Tree
```

wheel radius, wheel separation, joint 이름은 Pinky USD의 실제 articulation과 정확히
일치해야 합니다. 틀리면 토픽은 보여도 로봇이 회전하거나 이동하지 않습니다.

### 7.3 프레임 규칙

현재 Nav2 설정과 같은 프레임을 사용합니다.

```text
map
└── pinky_01/odom
    └── pinky_01/base_link
        └── pinky_01/lidar_link
```

Gazebo와 Isaac Sim이 동시에 같은 `/tf`와 `/clock`을 발행하게 해서는 안 됩니다.
한 번에 물리 백엔드는 하나만 실행합니다.

---

## 8. 좌표 변환

RMF/Nav2 지도 좌표와 Isaac stage 좌표가 같아야 합니다. 프로젝트 설정은 다음 값을
MySQL `map_project_simulation_settings.coordinate_transform`에 저장할 수 있습니다.

```json
{
  "metersPerUnit": 1.0,
  "rmfOriginX": 0.0,
  "rmfOriginY": 0.0,
  "stageOriginX": 0.0,
  "stageOriginY": 0.0,
  "yawOffsetRad": 0.0,
  "invertY": false
}
```

기본 변환은 다음과 같습니다.

```text
RMF (x, y)
  → 원점 이동
  → 필요하면 Y 반전
  → yawOffsetRad 회전
  → metersPerUnit 적용
  → Isaac stage 원점 더하기
```

첫 검증에서는 다음 세 점을 비교합니다.

- 지도 원점
- `pinky_01` 충전 waypoint
- 원점에서 멀리 떨어진 waypoint 하나

한 점만 맞으면 회전·축 반전·scale 오류를 발견하지 못할 수 있습니다.

---

## 9. 앱에서 실행하기

1. GPU와 `nvidia-smi` 정상 여부 확인
2. Isaac 환경 변수를 둔 터미널에서 Flutter 앱 실행
3. 맵 프로젝트 열기
4. `설정 파일 → 디스크로 내보내기`
5. `백엔드 실행` 선택
6. 시뮬레이션 백엔드에서 `Isaac Sim` 선택
7. 필요하면 `Isaac Sim 3D 창`, `RViz` 선택
8. 실행

앱은 다음 순서로 동작합니다.

```text
Isaac launcher와 USD 확인
    ↓
Isaac Sim 실행
    ↓
/clock 최초 메시지 확인
    ↓
Open-RMF 실행
    ↓
Nav2와 Fleet Adapter 실행
```

`/clock`이 제한 시간 안에 나오지 않으면 RMF와 Nav2는 실행하지 않습니다.

---

## 10. 터미널에서 직접 실행하는 예

앱을 거치지 않고 같은 실행을 재현할 수 있습니다.

```bash
source /opt/ros/jazzy/setup.bash

export ROBOSAPIENS_ROOT=/home/gyi/robosapiens
export ISAAC_SIM_PYTHON=/home/gyi/isaac/isaacsim/_build/linux-x86_64/release/python.sh
export ROS_DOMAIN_ID=22
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

cd /home/gyi/robosapiens/rmf_maps/project1

SIM_BACKEND=isaac_sim \
SIMULATOR_GUI=true \
RVIZ=true \
./run_project1.sh
```

헤드리스 실행:

```bash
SIM_BACKEND=isaac_sim \
SIMULATOR_GUI=false \
RVIZ=false \
./run_project1.sh
```

중지:

```bash
./stop_project1.sh
```

Isaac stage 또는 실행기를 다른 위치에서 시험할 때:

```bash
ISAAC_SIM_PYTHON=/path/to/isaac/python.sh \
ISAAC_STAGE=/path/to/custom.usd \
ISAAC_PROJECT_SCRIPT=/path/to/start_project.py \
SIM_BACKEND=isaac_sim \
./run_project1.sh
```

---

## 11. ROS Topic Verification (ROS 토픽 검증)

다른 터미널에서도 같은 ROS/RMW/domain 환경을 사용합니다.

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=22
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
```

### 11.1 최소 준비 상태

```bash
ros2 topic echo /clock --once
ros2 topic info /pinky_01/odom --verbose
ros2 topic info /pinky_01/scan --verbose
ros2 topic info /pinky_01/cmd_vel_smoothed --verbose
ros2 run tf2_ros tf2_echo pinky_01/odom pinky_01/base_link
```

기대 결과:

- `/clock`: publisher 1개
- `odom`, `scan`: Isaac Sim publisher 존재
- `cmd_vel_smoothed`: Nav2 publisher와 Isaac subscriber 존재
- TF: 끊기지 않고 변환 출력

### 11.2 수동 이동 시험

Nav2를 띄우기 전 단독 시험에서만 실행합니다.

```bash
ros2 topic pub --rate 10 \
  /pinky_01/cmd_vel_smoothed geometry_msgs/msg/Twist \
  '{linear: {x: 0.1}, angular: {z: 0.0}}'
```

로봇이 앞으로 가지 않으면 다음을 확인합니다.

- subscriber topic 이름
- left/right wheel joint 이름
- articulation controller target prim
- wheel radius와 wheel separation
- drive joint 축과 sign

### 11.3 중복 백엔드 확인

```bash
ros2 topic info /clock --verbose
ros2 topic info /pinky_01/odom --verbose
pgrep -af 'gz sim|isaac-sim|start_project1.py'
```

`/clock` publisher가 2개면 Gazebo와 Isaac Sim 또는 Isaac stage 두 벌이 동시에
실행 중일 가능성이 큽니다. 모두 내린 뒤 하나만 다시 시작합니다.

---

## 12. MySQL Stored Values (MySQL에 저장되는 값)

선택한 백엔드와 화면 옵션은 프로젝트별로 자동 저장됩니다.

```sql
SELECT
  p.map_name,
  s.default_backend,
  s.simulator_gui,
  s.rviz_enabled,
  s.isaac_settings,
  s.coordinate_transform,
  s.updated_at
FROM map_project_simulation_settings s
JOIN map_projects p ON p.id = s.project_id;
```

로봇별 USD asset과 import/물리 설정은 다음 테이블에 둘 수 있습니다.

```sql
SELECT
  p.map_name,
  r.robot_id,
  r.backend,
  r.asset_uri,
  r.prim_path,
  r.settings
FROM map_project_robot_simulation r
JOIN map_projects p ON p.id = r.project_id
WHERE r.backend = 'isaac_sim';
```

USD 바이너리와 텍스처를 MySQL에 직접 넣지는 않습니다. MySQL에는 경로, prim,
좌표 변환, import 설정과 checksum 같은 재현 정보를 저장하고 실제 asset은
`rmf_maps/<프로젝트>/isaac/` 또는 별도의 asset 저장소에 둡니다.

---

## 13. 자주 발생하는 문제

### `Isaac Sim Python 실행기를 찾지 못했습니다`

소스 빌드 경로를 지정합니다.

```bash
export ISAAC_SIM_PYTHON=/home/gyi/isaac/isaacsim/_build/linux-x86_64/release/python.sh
```

### `Isaac Sim 프로젝트 산출물이 없습니다`

다음을 확인합니다.

```bash
ls -l /home/gyi/robosapiens/rmf_maps/project1/isaac/start_project1.py
ls -l /home/gyi/robosapiens/rmf_maps/project1/isaac/project1.usd
```

Python 파일이 없으면 앱에서 다시 내보냅니다. USD가 없으면 Isaac Sim에서 stage를
구성하고 해당 경로에 저장합니다.

### Isaac 창은 떴지만 `/clock`이 없다

- timeline이 Play 상태인지 확인
- `isaacsim.ros2.bridge`가 활성화됐는지 확인
- Clock Action Graph가 stage에 있는지 확인
- `ROS_DOMAIN_ID`와 `RMW_IMPLEMENTATION`이 같은지 확인
- Action Graph의 `ROS2 Context`가 올바른 domain을 쓰는지 확인

### 토픽 이름은 있지만 값이 없다

ROS graph에는 subscriber만 있어도 토픽 이름이 보일 수 있습니다.

```bash
ros2 topic info /pinky_01/scan --verbose
```

Publisher count와 실제 publisher node를 확인합니다. Isaac RTX LiDAR라면 렌더링,
sensor prim, render product와 helper node도 확인합니다.

### Nav2가 명령하지만 로봇이 움직이지 않는다

```bash
ros2 topic echo /pinky_01/cmd_vel_smoothed --once
ros2 topic info /pinky_01/cmd_vel_smoothed --verbose
```

명령이 나오면 Isaac subscriber·Differential Controller·Articulation Controller
연결 문제입니다. 명령이 안 나오면 Nav2 localization 또는 controller 상태를
확인합니다.

### 앱/RViz와 Isaac 위치가 다르다

- stage 단위가 meter인지 확인
- Y축 반전 여부 확인
- RMF origin과 stage origin 확인
- spawn yaw와 `yawOffsetRad` 확인
- `map → <id>/odom` TF가 중복 발행되는지 확인

### `nvidia-smi` 자체가 실패한다

Isaac 설정 문제가 아니라 NVIDIA 드라이버 또는 GPU 접근 문제입니다. 이 상태에서는
USD나 ROS graph를 수정하기 전에 호스트 GPU부터 정상화합니다.

---

## 14. 최초 성공 판정 체크리스트

- [ ] `nvidia-smi` 정상
- [ ] Isaac release `python.sh` 실행 가능
- [ ] ROS 2 Jazzy source 완료
- [ ] Isaac과 외부 ROS의 RMW가 동일
- [ ] Isaac과 프로젝트의 `ROS_DOMAIN_ID`가 동일
- [ ] `isaac/start_<프로젝트>.py` 존재
- [ ] `isaac/<프로젝트>.usd` 존재
- [ ] USD timeline Play
- [ ] `/clock` publisher 정확히 1개
- [ ] 각 Pinky의 `odom`, `scan`, joint states 발행
- [ ] `cmd_vel_smoothed`를 Isaac이 구독
- [ ] TF tree 연결
- [ ] 수동 직진·회전 성공
- [ ] Nav2 단일 로봇 목표 성공
- [ ] 두 번째 로봇 namespace 분리 확인
- [ ] RMF 작업 배차와 완료 상태 확인

처음에는 `pinky_01` 한 대만 완성한 뒤 다중 로봇과 OMX를 추가합니다. 여러 로봇과
센서를 한꺼번에 올리면 namespace, TF, 물리, GPU 성능 문제를 구분하기 어렵습니다.
