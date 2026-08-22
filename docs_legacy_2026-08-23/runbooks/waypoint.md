# 실기 Pinky waypoint 좌표 측정

이 문서는 실제 Pinky에서 지도 `new_map_2.yaml`을 띄우고, 수동 이동 뒤 AMCL
좌표를 waypoint 후보로 읽는 최소 절차다. 모든 ROS 터미널은 같은
`ROS_DOMAIN_ID=12`와 `ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET`을 써야 한다.

## 먼저 알아둘 점

`/amcl_pose`가 나온다고 모터가 준비된 것은 아니다. 수동조작 전에는
`cmd_vel_manual → safety_supervisor → cmd_vel → pinky_bringup`의 각 구독자를 확인해야
한다. 중간 토픽의 `Subscription count: 0`이면 키를 눌러도 로봇은 움직이지 않는다.

벤더 `pinky_bringup` 단독 launch는 모터와 LiDAR만 직접 기동한다. 이 문서의
waypoint 측정에는 `local_manual.launch.py`를 사용한다. 이 launch는 safety
supervisor를 모터 앞에 두고, FMS 없이도 현장 측정용 저속 teleop만 허용한다.
라이다·초음파·비상정지·장애물/사람 보호는 계속 적용된다.

## 터미널 1 — Raspberry Pi: 안전 local-manual bringup

Raspberry Pi에 접속한 터미널이다. 프롬프트가 `pinky@raspi`인지 먼저 확인한다.
`cook2`에서 이 명령을 실행하면 LiDAR 패키지나 시리얼 장치 오류가 나며, 모터는
기동되지 않는다. 먼저 수정된 Trihouse 소스를 Raspberry Pi의 workspace에 배포하고
빌드해야 한다.

```bash
source /opt/ros/jazzy/setup.bash
source <RASPI_PINKY_PRO_WS>/install/setup.bash
source <RASPI_TRIHOUSE_WS>/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

ros2 launch trihouse_pinky_bringup local_manual.launch.py
```

PASS 기준은 bringup 로그의 다음 문구다.

```text
safety_supervisor가 실행 중이고, /scan·/odom·/trihouse/proximity/front이 생성됨
```

이 launch는 `teleop → /cmd_vel_manual → safety_supervisor → /cmd_vel → pinky_bringup`
경로를 만든다. `/cmd_vel`을 직접 발행하는 teleop이나 Nav2는 이 현장 측정 절차에
사용하지 않는다.

## 터미널 2 — cook2: localization

```bash
cd /home/newuser/Trihouse/pinky_pro
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

ros2 launch pinky_navigation localization_launch.xml \
  map:=/home/newuser/Trihouse/pinky_pro/pinky_navigation/map/new_map_2.yaml \
  use_sim_time:=false
```

지도 파일은 절대경로로 준다. `map:=new_map_2.yaml`처럼 파일명만 주면 현재
디렉터리가 바뀐 경우 map server가 YAML을 찾지 못한다.

## 터미널 3 — cook2: RViz

```bash
cd /home/newuser/Trihouse/pinky_pro
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

ros2 launch pinky_navigation nav2_view.launch.xml
```

RViz에서 로봇이 실제로 서 있는 대략적인 위치에 `2D Pose Estimate`를 준다.

## 터미널 4 — cook2: teleop과 waypoint 좌표 읽기

먼저 모터 연결만 확인한다. 이 명령은 로봇을 움직이지 않는다.

```bash
cd /home/newuser/Trihouse
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

ros2 topic info /cmd_vel --verbose
ros2 topic echo --once /trihouse/safety/state
```

teleop을 실행한 뒤 별도 터미널에서 `ros2 topic info /cmd_vel_manual --verbose`를 실행한다.
PASS는 `/cmd_vel_manual`에 teleop 발행자와 safety 구독자가 각각 1개,
`/cmd_vel`에 safety 발행자와 `pinky_bringup` 구독자가 각각 1개인 상태다.
`/trihouse/safety/state`의 `detail`이 `sensor_timeout`, `front_stop`, `swept_stop`,
`emergency_latched`이면 키를 누르지 말고 원인을 해소한다. safety supervisor가 아니라
teleop이 모터 토픽을 직접 발행하는 구성은 안전 gate를 우회하므로 실기 주행에 쓰지 않는다.

### `pose` 명령 등록

같은 터미널에서 아래 함수를 한 번 등록한다. ROS 기본 CLI를 그대로 쓰므로 복잡한
Python 붙여넣기나 namespace 변수 오류를 피할 수 있다. 현재 단일 로봇 절차는 루트
`/amcl_pose`를 쓴다.

```bash
unset -f pose 2>/dev/null
pose() { ros2 topic echo --once /amcl_pose; }
```

### 수동 이동 및 측정

안전 check를 통과한 구성에서만 텔레옵을 시작한다. teleop은 local-manual 입력
`cmd_vel_manual`로 보내고, safety supervisor만 모터 `cmd_vel`을 발행한다.

```bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard \
  --ros-args -r /cmd_vel:=/cmd_vel_manual
```

`local_manual.launch.py`가 아니라 벤더 `bringup_robot.launch.xml`만 단독으로 띄운
경우에는 safety supervisor가 없다. 이 경우 위 check가 PASS가 되지 않으므로 teleop으로
실물 바퀴를 움직이지 않는다.

키는 `i` 전진, `,` 후진, `j` 좌회전, `l` 우회전, `k` 정지다. 처음에는 `x`를
여러 번 눌러 선속도를 `0.06 m/s` 이하로 낮춘다.

목표 물리 지점에 도착한 뒤 `Ctrl+C`로 teleop을 끝내면 로봇은 정지한다. **같은
터미널**에서 다음만 실행하면 waypoint 후보 좌표를 읽을 수 있다.

```bash
pose
```

출력의 `position.x`, `position.y`가 map 좌표이고, `orientation.z`,
`orientation.w`가 방향 quaternion이다. `covariance[0]`, `covariance[7]`,
`covariance[35]`는 각각 x, y, yaw의 분산이다. 예시 출력이다.

```text
position:
  x: 0.5260
  y: 0.0150
orientation:
  z: -0.0105
  w: 0.9999
```

## waypoint 확정 기준

목표 지점마다 `pose`를 3번 실행한다. 이 단계 전제는 RViz의 `/scan` 점이 지도 벽과
대체로 겹치는 것이다. scan이 맵 밖으로 튀거나 particle cloud가 넓게 퍼진 경우에는
주행·측정을 멈추고 초기 pose, TF, 라이다 방향을 먼저 점검한다. 세 측정값이 서로 비슷하고 `stddev x`,
`stddev y`가 모두 `0.12 m` 이하면 중앙값 또는 평균을 확정값으로 기록한다.
그보다 크면 로봇을 실제 위치에서 조금 전진·후진·회전시켜 AMCL을 더 수렴시킨 뒤
다시 측정한다.

기록값은 `map` 좌표계다.

```text
map_pose.x   = pose의 x
map_pose.y   = pose의 y
map_pose.yaw = pose의 yaw (rad)
```

`data/map_authoring/import/trihouse_test_01_physical_features.new_map_2.jsonl`에는
확정한 값만 반영한다. 충전소의 "반드시 빠져나와야 하는" 실제 탈출 경로는 JSONL이
아니라 `config/narrow_zones.new_map_2.yaml`의 `exit` 및 `exit_target`이 결정한다.

## 2026-08-21 PK02 충전소 재측정값

quaternion의 `z`, `w`를 yaw로 변환한 최종 `map` pose다.

| waypoint | x | y | yaw (rad) |
|---|---:|---:|---:|
| `charging_station_01` | `0.0570244747` | `0.1949666005` | `0.1093261667` |
| `charging_station_02` | `0.1336554086` | `-0.0065562838` | `0.1569596446` |

첨부 기록은 각 충전소의 동일 timestamp와 동일 수치가 세 번 반복되어 있으므로,
독립 측정 3회의 분산값으로 취급하지 않는다. 좌표는 최종 pose로 반영하고 실제 복귀
시험 전에 AMCL 정합을 한 번 더 눈으로 확인한다.
