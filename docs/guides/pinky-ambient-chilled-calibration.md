# PK_01 상온·냉장 협로 Calibration 왕복 시험

> **현재 상태: 주행 중단.** 2026-08-23 실기에서 `namespace:=/`와
> `bringup_robot_namespaced.launch.xml`을 함께 사용하면 `/scan.header.frame_id`가
> `/rplidar_link`로 발행되는 결함을 확인했다. tf2는 `/`로 시작하는 frame ID를
> 거부하므로 아래의 루트 namespace bringup은 원인 기록용이며 수정·재검증 전에는
> 다시 실행하지 않는다.

## 범위

이 문서는 `feat/physical-integration-v1`의 새벽 실기 복구 결과를 바탕으로 `PK_01`이
`new_map_2`에서 다음 경로를 시험하는 절차다.

```text
Nav2로 창고 entry 접근
→ Nav2 goal 취소와 완전 정차
→ entry 자세 정렬
→ 규칙 기반 진입
→ 도크 자세 검증
→ 규칙 기반 탈출
→ Nav2 제어 재개
```

이 절차는 FMS 주문, RMF 배차 또는 OMX 작업을 실행하지 않는다. 상온·냉장 profile은
아직 운영 승인 전이므로 `hardware_calibration` 출처의 `ExecuteTransport` goal만 사용한다.

현재 구성:

```text
개발 PC: 192.168.0.4
Pinky:   pinky@192.168.0.21
robot:   PK_01
map:     new_map_2
domain:  12
```

필요한 터미널은 개발 PC 세 개와 Pinky 한 개다.

물리 주행 전 경로를 비우고 E-stop 담당자를 배치한다. `safety.state`가 STOP 이상이거나,
`latched=true`, pose 불일치, Nav2 lifecycle 미활성, 배터리 정책 실패 중 하나라도 있으면
goal을 보내지 않는다.

## 1. 개발 PC 터미널 1: Discovery와 profile 배포

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1

git branch --show-current

source /opt/ros/jazzy/setup.bash
source install/setup.bash

export PINKY_IP='192.168.0.21'
export CONTROL_PC_IP='192.168.0.4'
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
unset ROS_STATIC_PEERS
export ROS_DISCOVERY_SERVER="$CONTROL_PC_IP:11811"
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
```

네트워크를 확인한다.

```bash
ip route get "$PINKY_IP"
ping -c 2 "$PINKY_IP"
ssh pinky@"$PINKY_IP" hostname
```

Discovery Server를 하나만 실행한다.

```bash
pgrep -af '[f]astdds discovery' || {
  setsid nohup fastdds discovery \
    -i 0 \
    -l "$CONTROL_PC_IP" \
    -p 11811 \
    > /tmp/trihouse_discovery_server.log 2>&1 < /dev/null &
}

sleep 3
pgrep -af '[f]astdds discovery'
ss -lunp | grep ':11811'
```

Pinky의 기존 profile을 백업한 뒤 현재 브랜치 파일을 배포한다.

```bash
ssh pinky@"$PINKY_IP" \
  'cp -a /home/pinky/narrow_zones.new_map_2.yaml /home/pinky/narrow_zones.new_map_2.yaml.backup'

rsync -avc --itemize-changes \
  config/narrow_zones.new_map_2.yaml \
  pinky@"$PINKY_IP":/home/pinky/narrow_zones.new_map_2.yaml

sha256sum config/narrow_zones.new_map_2.yaml
ssh pinky@"$PINKY_IP" \
  'sha256sum /home/pinky/narrow_zones.new_map_2.yaml'
```

두 checksum의 기대값은 다음과 같다.

```text
9add00b3cff347cc33bb20704e02a15679ddf300e5ceb4cab4d2746e19861eb9
```

## 2. Pinky 터미널: 기존 launch 정리와 bringup (재실행 금지 구성)

Pinky에 접속하고 overlay를 순서대로 읽는다.

```bash
ssh pinky@192.168.0.21

source /opt/ros/jazzy/setup.bash
source /home/pinky/pinky_pro/install/setup.bash
source /home/pinky/trihouse_ws/install/setup.bash
```

중복 launch를 확인한다.

```bash
pgrep -af \
  '^/usr/bin/python3 /opt/ros/jazzy/bin/ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py' ||
echo 'PASS: 기존 launch 없음'
```

기존 launch가 있으면 SIGINT로 정상 종료한다. 이 명령은 실행 중인 Nav2와 주행도 중단한다.

```bash
LAUNCH_PIDS="$(
  pgrep -f \
    '^/usr/bin/python3 /opt/ros/jazzy/bin/ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py' ||
  true
)"

if [ -n "$LAUNCH_PIDS" ]; then
  kill -INT $LAUNCH_PIDS
  sleep 8
fi

pgrep -af \
  '[r]os2 launch trihouse_pinky_bringup|[s]afety_supervisor|[f]leet_node|[v]elocity_smoother' ||
echo 'PASS: 기존 motion process 없음'
```

새벽 실기 복구에서 readiness까지 확인했던 루트 namespace 구성이다. 2026-08-23 실제
주행에서 LiDAR frame 결함이 드러났으므로 아래 명령은 재현 기록으로만 보관하며 실행하지
않는다.

```bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
unset ROS_STATIC_PEERS
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4

export CONTROL_HOST='192.168.0.4'
export MAP_REVISION='new_map_2:df9a7f70eab87135a0e1a73c2b63a0a15aae2de3512a6c760a3259d0337a32ed'

NAV2_PARAMS="$(
  ros2 pkg prefix pinky_navigation
)/share/pinky_navigation/params/nav2_params.yaml"

setsid nohup ros2 launch \
  trihouse_pinky_bringup \
  trihouse_pinky.launch.py \
  namespace:=/ \
  robot_id:=PK_01 \
  map:=/home/pinky/map/new_map_2.yaml \
  map_revision:="$MAP_REVISION" \
  nav2_params_file:="$NAV2_PARAMS" \
  narrow_zones_file:=/home/pinky/narrow_zones.new_map_2.yaml \
  narrow_map_name:=new_map_2 \
  allow_narrow_calibration:=true \
  control_host:="$CONTROL_HOST" \
  control_port:=8788 \
  vision_enabled:=false \
  docking_enabled:=false \
  > /tmp/trihouse_pinky_rule.log 2>&1 < /dev/null &

sleep 40
```

Launch와 lifecycle을 확인한다.

```bash
pgrep -af \
  '^/usr/bin/python3 /opt/ros/jazzy/bin/ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py'

ACTIVE_COUNT="$(
  grep -ac 'Managed nodes are active' /tmp/trihouse_pinky_rule.log
)"
echo "activation_count=$ACTIVE_COUNT"

grep -aE \
  'No critics defined|Failed to bring up|Failed to change state|process has died|Traceback' \
  /tmp/trihouse_pinky_rule.log ||
echo 'PASS: bringup error 없음'
```

합격 조건은 launch 한 개, `activation_count=2` 이상, 치명적 오류 없음이다.

여기에 다음 LiDAR/TF 검사를 반드시 추가한다. 하나라도 실패하면 goal을 보내지 않는다.

```bash
timeout 10 ros2 topic echo /scan sensor_msgs/msg/LaserScan --once |
  sed -n '/frame_id/p'

timeout 10 ros2 topic echo /tf_static tf2_msgs/msg/TFMessage --once |
  grep -E 'frame_id:|child_frame_id:'
```

`/scan.header.frame_id`에 선행 `/`가 없어야 하고 TF의 child frame과 정확히 같아야 한다.
현재 실패 구성에서는 각각 `/rplidar_link`, `rplidar_link`로 서로 다르다.

## 3. 개발 PC 터미널 2: go/no-go와 safety 감시

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
source /opt/ros/jazzy/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
unset ROS_STATIC_PEERS
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
```

```bash
timeout 15 ros2 topic echo --no-daemon --spin-time 8 \
  /trihouse/readiness trihouse_interfaces/msg/Readiness --once

timeout 15 ros2 topic echo --no-daemon --spin-time 8 \
  /trihouse/status trihouse_interfaces/msg/RobotStatus --once

timeout 15 ros2 topic echo --no-daemon --spin-time 8 \
  /trihouse/safety/state trihouse_interfaces/msg/SafetyState --once

ros2 action info /trihouse/transport/execute
ros2 topic info /cmd_vel --verbose
ros2 topic info /cmd_vel_safe --verbose
```

합격 조건:

```text
readiness.state=1
missing_interfaces=[]
status.frame_id=map
status.map_revision 일치
telemetry_valid=true
execution_ready=true
dispatchable=true
ready=true
errors=[]
safety.state < STATE_STOP
safety.latched=false
/cmd_vel_safe의 유일한 발행자가 safety_supervisor
/cmd_vel_safe의 구독자가 vendor motor node
ExecuteTransport action server 존재
실물 위치와 status.pose 일치
```

확인 뒤 이 터미널은 safety 감시에 사용한다.

```bash
ros2 topic echo \
  /trihouse/safety/state \
  trihouse_interfaces/msg/SafetyState
```

## 4. 개발 PC 터미널 3: calibration goal 함수

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
source /opt/ros/jazzy/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
unset ROS_STATIC_PEERS
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
export MAP_REVISION='new_map_2:df9a7f70eab87135a0e1a73c2b63a0a15aae2de3512a6c760a3259d0337a32ed'
```

```bash
send_calibration_goal() {
  local destination="$1"
  local target_x="$2"
  local target_y="$3"
  local target_qz="$4"
  local target_qw="$5"
  local run_id

  run_id="$(date +%s%N)"

  ros2 action send_goal \
    /pinky_01/trihouse/transport/execute \
    trihouse_interfaces/action/ExecuteTransport \
    "{
      task_context: {
        active: true,
        job_id: $run_id,
        job_step_id: $run_id,
        assignment_revision: 1,
        rmf_task_id: 'calibration-$run_id',
        command_id: '$destination-$run_id',
        map_revision: '$MAP_REVISION',
        command_source: 'hardware_calibration'
      },
      dropoff_location_id: '$destination',
      destination_code: '$destination',
      dropoff_pose: {
        header: {frame_id: 'map'},
        pose: {
          position: {x: $target_x, y: $target_y, z: 0.0},
          orientation: {x: 0.0, y: 0.0, z: $target_qz, w: $target_qw}
        }
      },
      priority: 0,
      requires_precise_stop: true,
      handover_expected: false,
      mode: 3
    }" \
    --feedback
}
```

## 5. 상온 왕복

상온 진입:

```bash
send_calibration_goal \
  ambient_storage_loading_dock_01 \
  1.194985191182392 \
  0.874754065282721 \
  -0.9859319099073992 \
  0.16714744696329686
```

2026-08-24 변경 설치본의 예상 경로는 Nav2 상온 entry 접근, 완전 정차, 넓은 곳에서
출입구 heading `0.335871` 정렬, 양의 선속도로 내부 좌표까지 직선 진입, 완전 정지,
내부에서 dock yaw `-2.805721` 회전이다. 출입구에서 제자리 회전하거나 `0.30 m` 후진하는
것은 구형 경로이므로 즉시 중단한다. 결과와 실물 정차를 확인한 뒤에만 탈출한다.

```bash
send_calibration_goal \
  narrow_calibration_exit_target \
  0.911748152598201 \
  0.77587646431032 \
  -0.9999840410590615 \
  0.005649568761360869
```

## 6. 냉장 왕복

상온 왕복 뒤 배터리, safety, pose를 다시 확인한다.

```bash
send_calibration_goal \
  chilled_storage_loading_dock_01 \
  1.3263418779273253 \
  -0.2988701614809928 \
  0.9354235723271759 \
  0.3535289808978392
```

2026-08-24 변경 설치본의 예상 경로는 Nav2 냉장 entry 접근, 완전 정차, 넓은 곳에서
출입구 heading `-1.139417` 정렬, 양의 선속도로 내부 좌표까지 직선 진입, 완전 정지,
내부에서 dock yaw `2.418911` 회전이다. entry에서 내부까지 약 `1.293 m`인 긴 시험 구간은
실제 통로 중심과 장애물을 사람이 먼저 확인해야 한다. 결과와 실물 정차를 확인한 뒤에만
탈출한다.

```bash
send_calibration_goal \
  narrow_calibration_exit_target \
  1.1013315221281241 \
  -0.10045055614140724 \
  -0.9999840410590615 \
  0.005649568761360869
```

## 7. 중단 및 판정

다음 중 하나라도 발생하면 다음 goal을 보내지 않는다.

```text
safety.state가 STOP 이상
latched=true
scan_stale 또는 nav_unavailable
battery_not_dispatchable
robot is not idle
NARROW_PROFILE 오류
entry 정렬 실패
도크 또는 탈출 target 불일치
Nav2 abort
로봇이 완전히 정차하지 않음
```

상온은 `dock_pose=false`, 냉장은 `dock_pose=false`, `enter=false`, `exit=false`다.
실물 왕복과 실제 pose를 사람이 확인하기 전에는 일반 FMS 주문용으로 승인하지 않는다.

진단 로그:

```bash
ssh pinky@192.168.0.21 \
  "grep -aE '협로|entry|도크|탈출|FAILED|REJECTED|swept_stop|navigation failed' /tmp/trihouse_pinky_rule.log | tail -100"
```

## 8. 2026-08-23 상온 진입 실패 기록

대상 goal은 action server에 수락됐고, Nav2도 현재 위치 `(0.68, 0.01)`에서 상온
entry `(1.01, 0.92)`로 주행을 시작했다. 따라서 action discovery, map revision,
calibration gate 또는 destination profile 거부가 원인은 아니다.

확인된 실패 흐름:

```text
/scan.header.frame_id = /rplidar_link
/tf_static child_frame_id = rplidar_link
→ tf2가 선행 '/'가 있는 frame ID를 거부
→ local/global costmap의 LaserScan 변환과 갱신이 반복 실패
→ controller_server: Failed to make progress
→ Nav2 recovery도 safety front_stop으로 움직이지 못함
→ controller_server: Costmap timed out waiting for update
→ bt_navigator abort, ExecuteTransport code=3 navigation failed
```

선행 `/`의 생성 위치는 Pinky에 설치된 다음 launch다.

```text
/home/pinky/pinky_pro/install/pinky_bringup/share/pinky_bringup/launch/
bringup_robot_namespaced.launch.xml
```

이 파일이 `frame_id`를 `$(var namespace)/rplidar_link`로 조합한다. Trihouse launch가
`namespace:=/`를 벤더에 빈 문자열로 넘기므로 결과가 `/rplidar_link`가 되는 반면,
robot state publisher의 TF는 `rplidar_link`로 남는다.

실패 직후 safety는 `front_stop`, `latched=false`였고 `ready=false`,
`execution_ready=false`, `errors=[safety_blocked]`였다. 장애물 또는 로봇 위치를 사람이
확인해 safety block을 해소하고, LiDAR frame 결함을 수정·검증하기 전에는 상온·냉장
goal을 다시 보내지 않는다. safety threshold를 낮춰 우회하지 않는다.

## 9. 2026-08-24 변경본 배포와 단계별 재시험

이 절은 앞의 구형 진입 설명보다 우선한다. 현재 `entry_passage`의 doorway는 실측점이 아니라
기존 `entry`와 `dock_target`의 중점으로 계산한 1차 시험값이다. 실패하면 임의 보정하지 않고
로봇을 수동 배치해 좌표를 다시 측정한다.

### 개발 PC 터미널 1 — 소스와 profile 배포

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1

export PINKY_IP=192.168.0.21
export REMOTE_REPO=/home/pinky/trihouse_ws/src/Trihouse

ssh pinky@"$PINKY_IP" \
  "test -f '$REMOTE_REPO/trihouse_pinky/trihouse_pinky_fleet/package.xml'"

scp \
  trihouse_pinky/trihouse_pinky_docking/trihouse_pinky_docking/narrow_zone.py \
  pinky@"$PINKY_IP":"$REMOTE_REPO/trihouse_pinky/trihouse_pinky_docking/trihouse_pinky_docking/narrow_zone.py"

scp \
  trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py \
  trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/narrow_zone_routing.py \
  pinky@"$PINKY_IP":"$REMOTE_REPO/trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/"

scp \
  trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/geometry.py \
  trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/safety_supervisor_node.py \
  pinky@"$PINKY_IP":"$REMOTE_REPO/trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/"

scp config/narrow_zones.new_map_2.yaml \
  pinky@"$PINKY_IP":/home/pinky/narrow_zones.new_map_2.yaml
```

첫 번째 `test -f`가 실패하면 원격 소스 경로가 다른 것이므로 복사를 중단하고 다음으로 찾는다.

```bash
ssh pinky@"$PINKY_IP" \
  "find /home/pinky/trihouse_ws/src -path '*/trihouse_pinky_fleet/package.xml' -print"
```

### Pinky_01 터미널 1 — 기존 motion 종료, 빌드, bringup

기존 launch를 `Ctrl-C`로 내린 뒤 남은 프로세스가 없을 때만 빌드한다.

```bash
pkill -INT -f \
  '^/usr/bin/python3 /opt/ros/jazzy/bin/ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py' || true
sleep 8

pgrep -af \
  '[r]os2 launch trihouse_pinky_bringup|[f]leet_node|[s]afety_supervisor|[c]ontroller_server' ||
echo 'PASS: 기존 motion process 없음'

cd /home/pinky/trihouse_ws
source /opt/ros/jazzy/setup.bash
source /home/pinky/pinky_pro/install/setup.bash
colcon build --symlink-install --packages-select \
  trihouse_pinky_docking \
  trihouse_pinky_safety \
  trihouse_pinky_fleet \
  trihouse_pinky_bringup
source install/setup.bash
```

```bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
unset ROS_STATIC_PEERS
unset FASTRTPS_DEFAULT_PROFILES_FILE

ros2 launch \
  trihouse_pinky_bringup \
  trihouse_pinky.launch.py \
  namespace:=pinky_01 \
  robot_id:=PK_01 \
  map:=/home/pinky/map/new_map_2.yaml \
  map_revision:='new_map_2:df9a7f70eab87135a0e1a73c2b63a0a15aae2de3512a6c760a3259d0337a32ed' \
  nav2_params_file:=/home/pinky/hardware_pinky_01.yaml \
  narrow_zones_file:=/home/pinky/narrow_zones.new_map_2.yaml \
  narrow_map_name:=new_map_2 \
  allow_narrow_calibration:=true \
  control_host:=192.168.0.4 \
  control_port:=8788 \
  vision_enabled:=false \
  docking_enabled:=false
```

이 터미널은 bringup 전용으로 유지한다.

### Pinky_01 터미널 2 — 정지 상태 검증과 로그

```bash
source /opt/ros/jazzy/setup.bash
source /home/pinky/pinky_pro/install/setup.bash
source /home/pinky/trihouse_ws/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
unset ROS_STATIC_PEERS
unset FASTRTPS_DEFAULT_PROFILES_FILE

timeout 30 ros2 topic echo \
  /pinky_01/trihouse/status \
  trihouse_interfaces/msg/RobotStatus --once

timeout 30 ros2 topic echo \
  /pinky_01/trihouse/safety/state \
  trihouse_interfaces/msg/SafetyState --once

ros2 topic info /pinky_01/cmd_vel_dock --verbose
ros2 topic info /pinky_01/cmd_vel_safe --verbose
```

`ready=true`, `dispatchable=true`, `frame_id=map`, safety CLEAR/SLOW를 확인한다. 그 다음 로그를
연속 관찰한다.

```bash
tail -F /tmp/trihouse_pinky_pinky01.log | \
  grep -aE 'rule_transition|swept_stop|front_stop|FAILED|ERROR'
```

### 개발 PC 터미널 2 — 좌표 goal 시험 순서

위 4절의 함수를 사용하되 action 이름을 namespace까지 명시한다.

```bash
# send_calibration_goal 함수 안의 action 경로
/pinky_01/trihouse/transport/execute
```

시험 순서는 다음과 같다.

1. 로봇을 움직이지 않고 status·safety·action server·publisher 경로를 확인한다.
2. 상온 좌표 goal을 한 번 보내고 사람이 출입구 밖 정렬 → 직선 진입 → 내부 회전을 확인한다.
3. 상온 성공 후에만 냉장 경로의 약 1.293 m 직선 구간을 사람이 비우고 냉장 goal을 보낸다.
4. 냉장 성공 후 냉동 calibration으로 기존 경로가 유지되는지 회귀 확인한다.
5. 세 좌표 시험과 왕복이 모두 성공한 뒤에만 FMS 주문 시험으로 넘어간다.

`swept_stop` 복구는 출입구 밖 정렬 중에만 허용된다. 첫 틱은 정지하고, safety가 CLEAR/SLOW로
돌아오면 `0.03 m/s`로 최대 `0.05 m` 후진한 뒤 다시 정렬한다. 최대 2회 또는 10초를 넘기면
실패한다. `front_stop`, emergency, `keep_out`, 센서 timeout, control link 단절에서는 절대
복구 이동하지 않는다.
