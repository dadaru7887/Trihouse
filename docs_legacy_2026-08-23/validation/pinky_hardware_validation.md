# Pinky 실물 연결 검증 절차

## 1. 범위와 현재 제약

이 문서는 `pinky_pro` 원본 패키지를 수정하지 않고
`trihouse_pinky.launch.py`로 실물 Pinky의 센서, Nav2, 안전 gate, 배터리,
상태, 복귀 및 표시 기능을 순서대로 확인하는 절차다.

현재 `trihouse_pinky_docking`은 README와 `Dock.action` 인터페이스만 있고
`/trihouse/dock` action server 및 ArUco 정밀 제어 노드는 구현되지 않았다.
따라서 지금 확인 가능한 docking 범위는 Nav2가 DB의 `loading_dock` 접근 pose까지
이동하는 것까지다. ArUco를 이용한 마지막 정밀 정차는 별도 구현 후 시험해야 한다.

## 2. 안전 조건

처음에는 반드시 Pinky 구동 바퀴를 바닥에서 띄우거나 충분히 넓은 시험 구역에 둔다.
비상정지 수단을 손이 닿는 곳에 두고 다음 조건을 만족하기 전에는 이동 명령을 보내지 않는다.

- 전방 2 m 이상 확보
- Pinky와 작업 PC의 `ROS_DOMAIN_ID` 일치
- `/scan`, `/odom`, `/amcl_pose`, 초음파와 배터리 값 확인
- `/cmd_vel` 발행자가 `safety_supervisor` 하나인지 확인
- 지도와 실제 초기 위치가 일치하도록 AMCL 초기 pose 설정
- DB의 `map_revision`과 실행 인자가 일치

## 3. 실물 PC에서 빌드

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
source /home/syw/Trihouse/pinky_pro/install/setup.bash

colcon build --symlink-install \
  --base-paths \
    trihouse_interfaces \
    trihouse_pinky/trihouse_pinky_io \
    trihouse_pinky/trihouse_pinky_safety \
    trihouse_pinky/trihouse_pinky_fleet \
    trihouse_pinky/trihouse_pinky_bringup \
    trihouse_omx_adapter \
  --packages-select \
    trihouse_interfaces \
    trihouse_pinky_io \
    trihouse_pinky_safety \
    trihouse_pinky_fleet \
    trihouse_pinky_bringup \
    trihouse_omx_adapter
```

벤더 패키지 인식 여부도 확인한다.

```bash
source install/setup.bash
ros2 pkg prefix pinky_bringup
ros2 pkg prefix pinky_navigation
ros2 pkg prefix trihouse_pinky_bringup
```

세 명령 모두 설치 경로를 출력해야 한다.

## 4. DB에서 실행할 지도와 loading dock 조회

이 명령은 MySQL이 실행되는 관제 PC에서 수행한다.

```bash
cd /home/syw/Trihouse

docker compose -f compose.db.yaml exec -T mysql \
  sh -lc 'mysql --default-character-set=utf8mb4 \
    -uroot -p"$MYSQL_ROOT_PASSWORD" trihouse_fms -e "
      SELECT map_revision, map_name, published_at
      FROM map_revisions
      WHERE state = '\''published'\''
      ORDER BY published_at DESC;

      SELECT location_code, name, rmf_waypoint_name,
             pose_x, pose_y, pose_yaw, state
      FROM locations
      WHERE location_type = '\''loading_dock'\''
      ORDER BY location_code;
    "'
```

여기서 사용할 `map_revision`, `pose_x`, `pose_y`, `pose_yaw`를 기록한다.
`loading_dock` pose는 Nav2 접근·주차 목표다. ArUco 기반 미세 정렬 목표와
허용 오차는 이후 `Dock.action` goal로 별도 전달한다.

## 5. 터미널 1: 실물 전체 bringup

아래 `<MAP_REVISION>`은 DB 조회값으로 교체한다.

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
source /home/syw/Trihouse/pinky_pro/install/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=51
export ROS_LOG_DIR=/tmp/trihouse_pinky_hardware_logs

ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  robot_id:=PK_01 \
  map:=/home/syw/Trihouse/control_system/rmf_maps/project1/nav2_map/project1.yaml \
  map_revision:=<MAP_REVISION> \
  control_host:=<FMS_GATEWAY_IP> \
  control_port:=8788 \
  font_path:=/opt/trihouse/fonts/NanumGothic.ttf
```

`control_host`는 Pinky에서 접근 가능한 관제 PC 주소다. FMS Gateway를 아직
연결하지 않고 로컬 시험할 때는 아래 7장의 제한된 시험 publisher를 사용한다.

## 6. 터미널 2: 센서와 안전 상태 확인

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
source /home/syw/Trihouse/pinky_pro/install/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=51
```

```bash
ros2 topic hz /scan
ros2 topic hz /odom
ros2 topic hz /trihouse/proximity/front
ros2 topic hz /trihouse/battery
```

각 명령은 `Ctrl+C`로 종료하고 다음 명령을 실행한다. 이어서 값을 확인한다.

```bash
ros2 topic echo /scan sensor_msgs/msg/LaserScan --once
ros2 topic echo /odom nav_msgs/msg/Odometry --once
ros2 topic echo /amcl_pose geometry_msgs/msg/PoseWithCovarianceStamped --once
ros2 topic echo /trihouse/proximity/front sensor_msgs/msg/Range --once
ros2 topic echo /trihouse/battery/condition \
  trihouse_interfaces/msg/BatteryCondition --once
ros2 topic echo /trihouse/readiness \
  trihouse_interfaces/msg/Readiness --once
ros2 topic echo /trihouse/safety/state \
  trihouse_interfaces/msg/SafetyState --once
ros2 topic echo /trihouse/status \
  trihouse_interfaces/msg/RobotStatus --once
```

통과 기준은 다음과 같다.

- Readiness `state: 1`, `missing_interfaces: []`
- SafetyState `state: 0`, `latched: false`
- RobotStatus `frame_id: map`, `telemetry_valid: true`
- 배터리 `measurement_valid: true`, `telemetry_fresh: true`

모터 명령의 단일 소유도 확인한다.

```bash
ros2 topic info /cmd_vel --verbose
```

운영 발행자는 `safety_supervisor` 하나여야 한다. Nav2는 `/cmd_vel_nav`, 향후
docking 노드는 `/cmd_vel_dock`을 사용하고 두 입력 모두 safety를 거쳐야 한다.

## 7. FMS 미연결 상태의 제한된 로컬 시험 입력

이 절은 격리된 실물 시험에서만 사용한다. 운영 중에는 Gateway가 발행해야 하며
수동 publisher를 동시에 실행하면 안 된다.

터미널 2에서 연결 상태를 계속 발행한다.

```bash
ros2 topic pub -r 2 /trihouse/fms/state \
  trihouse_interfaces/msg/ConnectionState \
  "{robot_id: PK_01, session_id: manual-hardware-test, state: 2,
    detail: isolated_manual_test}"
```

액션을 시험할 때는 별도 터미널에서 event outbox 준비 상태도 발행한다.

```bash
ros2 topic pub -r 2 /trihouse/fms/event_outbox_ready \
  std_msgs/msg/Bool '{data: true}'
```

## 8. AMCL 초기 위치 설정

가능하면 RViz의 `2D Pose Estimate`를 사용한다. 터미널에서 설정하려면 실제
초기 위치에 맞춰 `<X>`, `<Y>`, `<QZ>`, `<QW>`를 바꾼다.

```bash
ros2 topic pub --once /initialpose \
  geometry_msgs/msg/PoseWithCovarianceStamped \
  "{header: {frame_id: map}, pose: {pose: {
    position: {x: <X>, y: <Y>, z: 0.0},
    orientation: {z: <QZ>, w: <QW>}
  }}}"
```

입력 후 다음 두 위치가 실제 로봇 위치와 맞는지 확인한다.

```bash
ros2 topic echo /amcl_pose --once
ros2 topic echo /tf
```

## 9. loading dock 접근 위치까지 이동 확인

첫 시험에서는 바퀴를 띄운 상태로 `/cmd_vel_nav`와 safety 출력 방향만 확인한다.
이후 바닥 시험에서 DB에서 조회한 loading dock pose를 사용한다.

`pose_yaw`를 quaternion으로 바꾸는 명령:

```bash
python3 -c 'import math; yaw=float(input("pose_yaw(rad): ")); print("qz=", math.sin(yaw/2), "qw=", math.cos(yaw/2))'
```

Nav2에 loading dock 접근 목표를 전송한다.

```bash
ros2 action send_goal --feedback \
  /navigate_to_pose nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map}, pose: {
    position: {x: <DOCK_X>, y: <DOCK_Y>, z: 0.0},
    orientation: {z: <DOCK_QZ>, w: <DOCK_QW>}
  }}}"
```

다른 터미널에서 실제 위치와 명령을 관찰한다.

```bash
ros2 topic echo /amcl_pose
ros2 topic echo /cmd_vel_nav
ros2 topic echo /cmd_vel
```

통과 기준:

- Nav2 action `SUCCEEDED`
- 최종 `/amcl_pose`가 loading dock pose의 허용 오차 안에 있음
- 장애물이 가까우면 `/cmd_vel_nav`가 움직임을 요청해도 `/cmd_vel`은 감속 또는 0
- 안전 timeout 또는 관제 연결 단절 시 `/cmd_vel`은 0

이 결과는 `loading_dock 접근 성공`이지 `정밀 docking 성공`은 아니다.

## 10. 대기점·충전소 복귀 기능 확인

7장의 두 수동 publisher가 실행 중이고 Readiness가 READY인지 확인한다.
`mode: 1`은 대기점, `mode: 2`는 충전소 복귀다. 아래 목표 pose를 DB의 실제
대기점 또는 충전소 좌표로 교체한다.

```bash
ros2 action send_goal --feedback \
  /trihouse/transport/execute \
  trihouse_interfaces/action/ExecuteTransport \
  "{
    task_context: {
      active: true,
      job_id: 9001,
      job_step_id: 10,
      assignment_revision: 1,
      rmf_task_id: hardware-return-001,
      command_id: 10000000-0000-4000-8000-000000000001,
      map_revision: <MAP_REVISION>,
      command_source: manual_hardware_test
    },
    destination_code: RETURN,
    dropoff_pose: {header: {frame_id: map}, pose: {
      position: {x: <RETURN_X>, y: <RETURN_Y>, z: 0.0},
      orientation: {z: <RETURN_QZ>, w: <RETURN_QW>}
    }},
    requires_precise_stop: false,
    mode: 1
  }"
```

통과 결과는 `success: true`, `code: 0`이다. 충전소는 새로운 UUID command_id와
`mode: 2`를 사용한다. 이 시험은 충전 위치까지의 이동만 확인하며 충전 단자 자동
접촉은 요구사항 범위가 아니다.

## 11. 비상정지와 해제 확인

로봇이 움직이지 않는 상태에서 먼저 수행한다.

```bash
ros2 topic pub --once /trihouse/safety/emergency_request \
  std_msgs/msg/Bool '{data: true}'
ros2 topic echo /trihouse/safety/state --once
ros2 topic echo /cmd_vel --once
```

`latched: true`, emergency 상태, `/cmd_vel` 0을 확인한 뒤 해제한다.

```bash
ros2 service call /trihouse/safety/clear_emergency \
  trihouse_interfaces/srv/ClearEmergency \
  '{robot_id: PK_01, operator_id: syw, request_id: hardware-clear-001, reason: onsite_confirmed}'
```

`accepted: true`여야 한다. 해제는 즉시 새 작업을 허용한다는 뜻이 아니다.
Fleet 복귀 점검 상태까지 확인한 뒤 다음 작업을 수행한다.

## 12. LED·부저·LCD 확인

목적지 LCD:

```bash
ros2 topic pub --once /trihouse/display/destination_code \
  std_msgs/msg/String '{data: PACKING}'
```

비상 LED·부저는 임의 Indicator를 직접 주입하기보다 11장의 실제 emergency 요청으로
확인한다. 비상 중 빨간 LED와 부저 ON, 해제 후 OFF가 되어야 한다. LCD에 한글이
표시되지 않으면 `font_path`와 SPI 장치 점유 프로세스를 확인한다.

## 13. 현재 정밀 docking 확인이 불가능한 이유

다음 명령은 현재 action server가 없음을 보여준다.

```bash
ros2 action list -t | grep /trihouse/dock
```

현재는 출력이 없는 것이 코드 상태와 일치한다. 다음 구현이 추가돼야 실물에서
정밀 docking을 시험할 수 있다.

1. `/trihouse/vision/marker_observation/base`의 ArUco 상대 pose 수신
2. `/trihouse/dock` `Dock.action` server
3. 탐색·정렬·접근·허용 오차 검증 상태 머신
4. marker 소실·timeout·취소 시 `/cmd_vel_dock` 즉시 0
5. `/cmd_vel_dock`을 `safety_supervisor`를 통해서만 모터에 전달
6. Nav2 loading dock 접근 성공 후 Fleet가 Dock action을 호출하는 연결

따라서 실물 연결 시에는 우선 9장의 loading dock 접근 pose까지 검증하고, 정밀
docking은 위 구현을 완료한 뒤 저속으로 별도 검증한다.
