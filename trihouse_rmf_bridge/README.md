# Trihouse Pinky–Open-RMF Bridge

`pinky_easy_fleet_adapter`는 Open-RMF EasyFullControl 이동 명령을 Pinky의
`/trihouse/transport/execute` action으로 전달한다. Pinky의 `fleet_node`만 Nav2 goal을
소유하며, adapter는 `RobotStatus`의 신선한 `map` pose와 실제 배터리 SOC만 RMF에
갱신한다.

## 실물 시험 전 준비

현재 `gwanghee` 기준 식별자는 다음과 같다.

- RMF fleet: `pinky_fleet`
- Pinky/RMF robot: `PK-01`
- RMF level: `L1`
- charger waypoint: `충전1`
- 시험 map revision: `gwanghee-2026-08-12`

navigation graph는 `gwanghee.building.yaml`을 수정할 때마다 다시 생성한다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/syw/rmf_ws/install/setup.bash
ros2 run rmf_building_map_tools building_map_generator nav \
  /home/syw/Trihouse/control_system/rmf_maps/gwanghee/gwanghee.building.yaml \
  /home/syw/Trihouse/control_system/rmf_maps/gwanghee/nav_graphs
```

DB에는 graph를 복제하지 않는다. `locations`의 업무 위치–waypoint 연결과 `devices`의
장비–RMF robot 연결만 넣는다. 스키마 변경 없이 사용할 INSERT/SELECT 방법은
[Pinky–Open-RMF 통합 설계](../docs/superpowers/specs/2026-08-12-pinky-open-rmf-integration-design.md)에 있다.

## 빌드

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
source /home/syw/rmf_ws/install/setup.bash
colcon build --base-paths \
  trihouse_interfaces \
  trihouse_rmf_bridge \
  trihouse_pinky/trihouse_pinky_fleet
source install/setup.bash
```

## 실행 순서

먼저 RMF schedule과 dispatcher를 시작하고 Pinky bringup을 실행한다. Pinky의
`map_revision`과 adapter 인자는 반드시 같아야 한다.

```bash
ROS_DOMAIN_ID=51 ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  robot_id:=PK-01 map_revision:=gwanghee-2026-08-12
```

AMCL이 수렴해 `/amcl_pose`와 `RobotStatus.frame_id=map`이 확인된 뒤 adapter를 실행한다.

```bash
ROS_DOMAIN_ID=51 ros2 launch trihouse_rmf_bridge \
  pinky_easy_fleet_adapter.launch.py \
  nav_graph:=/home/syw/Trihouse/control_system/rmf_maps/gwanghee/nav_graphs/0.yaml \
  robot_name:=PK-01 rmf_map_name:=L1 charger_waypoint:=충전1 \
  map_revision:=gwanghee-2026-08-12
```

## 등록 전 확인

```bash
ROS_DOMAIN_ID=51 ros2 topic echo --once /trihouse/status
ROS_DOMAIN_ID=51 ros2 action info /trihouse/transport/execute
ROS_DOMAIN_ID=51 ros2 topic echo --once /fleet_states
ROS_DOMAIN_ID=51 ros2 topic info /cmd_vel --verbose
ROS_DOMAIN_ID=51 ros2 action info /navigate_to_pose
```

다음 조건을 모두 만족해야 첫 RMF 작업을 제출한다.

- `RobotStatus.robot_id=PK-01`, `frame_id=map`, `ready=true`
- pose가 유한수이고 배터리가 0~100% 범위
- `ExecuteTransport` action server가 한 개
- Nav2 action server가 한 개
- 운영 `/cmd_vel` 발행자가 Safety Supervisor 한 개
- `/fleet_states`에 `pinky_fleet/PK-01`과 실제 SOC가 표시됨

## 1대 실물 인수 순서

1. `충전1` 또는 알려진 graph waypoint에서 Pinky를 등록한다.
2. 가까운 `대기1` 이동을 제출하고 RMF task ID와 Pinky command ID를 기록한다.
3. Nav2 goal이 한 개만 만들어지고 Safety gate를 통과하는지 확인한다.
4. Nav2 성공과 실제 정지 뒤에만 RMF가 한 번 완료되는지 확인한다.
5. 이동 중 RMF cancel을 보내 Pinky action과 Nav2가 취소되는지 확인한다.
6. 취소 뒤 늦게 도착한 과거 결과가 RMF 작업을 완료하지 않는지 확인한다.
7. `/trihouse/status`를 3초 넘게 끊어 decommission과 신규 작업 차단을 확인한다.
8. AMCL pose, 센서, 배터리 readiness가 회복된 뒤에만 recommission되는지 확인한다.
9. 실측 footprint, 제동거리, 속도, SOC 변화, charger pose를 기록하고 Fleet YAML을 보정한다.

단일 Pinky 흐름을 통과한 뒤 mutex group과 실제 다중 Pinky traffic 시험을 진행한다.

## Open-RMF + Gazebo 예약 검증

다음 조합 launch는 Pinky Gazebo/Nav2/mock sensor, Open-RMF traffic schedule,
task dispatcher, EasyFullControl adapter를 같은 simulation clock으로 시작한다.
`nav_graph`와 Nav2 `map`은 반드시 같은 좌표계와 waypoint를 나타내야 한다.

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
source /home/syw/rmf_ws/install/setup.bash
source install/setup.bash
export ROS_LOG_DIR=/tmp/trihouse-ros-log

ros2 launch trihouse_rmf_bridge pinky_rmf_gazebo_validation.launch.py \
  nav_graph:=/home/syw/Trihouse/control_system/rmf_maps/gwanghee/nav_graphs/0.yaml \
  map:=/home/syw/Trihouse/control_system/rmf_maps/gwanghee/nav2_map/gwanghee.yaml \
  robot_name:=PK-01 map_revision:=gwanghee-2026-08-12
```

`rmf_ws` 설치 상태 자체는 아래 표준 데모로 별도 확인할 수 있다. 이 데모의
`tinyRobot1/2`는 Open-RMF slotcar이므로 Pinky adapter 검증을 대체하지는 않는다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/syw/rmf_ws/install/setup.bash
ROS_DOMAIN_ID=87 ros2 launch rmf_demos_gz office.launch.xml headless:=true
```

- 외부 OMX gate가 필요 없는 단일 waypoint 주문은 live RMF dispatch로 시험한다.
- 다중 waypoint 주문은 gate action executor가 연결될 때까지 composed payload와 DB 예약
  dry-run만 허용한다. 중간 작업을 성공한 것처럼 생략해 주행하지 않는다.
- PK-02를 추가하려면 별도 namespace/topic, 초기 pose, charger, Fleet YAML robot 등록이
  필요하다. 현재 기본 config는 PK-01 한 대다.
- `start_rmf_core:=false`는 이미 외부 schedule/dispatcher를 실행 중일 때만 사용한다.

## 배터리 시뮬레이션

Gazebo mock은 초기 SOC, 충전 상태, 충·방전률을 launch argument로 제공한다. 방전률 기본값은
`0.0 %/s`이므로 기존 demo 동작은 그대로이며, 임계값 시험에서만 가속률을 준다.

```bash
# 21%에서 1초마다 1%p 방전: LOCAL_ONLY(20%) 경계 재현
ros2 launch trihouse_rmf_bridge pinky_rmf_gazebo_validation.launch.py \
  nav_graph:=/home/syw/Trihouse/control_system/rmf_maps/gwanghee/nav_graphs/0.yaml \
  map:=/home/syw/Trihouse/control_system/rmf_maps/gwanghee/nav2_map/gwanghee.yaml \
  battery_percentage:=0.21 discharge_percent_per_second:=1.0

# 20%에서 충전 상태와 SOC 상승 재현
ros2 launch trihouse_rmf_bridge pinky_rmf_gazebo_validation.launch.py \
  nav_graph:=/home/syw/Trihouse/control_system/rmf_maps/gwanghee/nav_graphs/0.yaml \
  map:=/home/syw/Trihouse/control_system/rmf_maps/gwanghee/nav2_map/gwanghee.yaml \
  battery_percentage:=0.20 charging:=true charge_percent_per_second:=1.0
```

검증 채널은 의도적으로 둘로 분리한다.

1. `sim_hardware`: 결정적 `BatteryState` 충·방전과 20%/10% 정책 임계값 이동
2. RMF energy estimator: navigation graph, robot profile, motion/ambient sink 기반 예상 종료 SOC

Control Tower는 현재 유효 SOC와 RMF의 `finish_state_of_charge`를 함께 사용하지만, mock
방전률로 RMF 에너지 모델을 자동 보정하지 않는다. Gazebo 통과는 실물 배터리 용량·전압
곡선, 적재 중 소비전류, 바닥 마찰, charger 접촉/전류, 정밀 docking, 통신 단절 복구를
검증하지 않는다. 이 항목은 실물 시험에서 별도로 측정한다.
