# Open-RMF 에너지 Bridge 검증 가이드

## 검증 대상

이 절차는 Open-RMF office demo의 `/fleet_states`와 실제 office navigation graph를 `trihouse_rmf_bridge`에 연결해 다음 항목을 확인한다.

| 항목 | 성공 기준 |
|---|---|
| 현재 상태 수신 | `tinyRobot/tinyRobot1`의 위치와 현재 배터리가 `/fleet_states`에 표시됨 |
| 경로 ETA | `pantry → hardware_2`의 `travel_duration_s`가 0보다 큼 |
| 전체 시간 | `total_duration_s = travel_duration_s + 75` |
| 배터리 소비 | `change_in_charge`가 0보다 크고 현재 SOC보다 작음 |
| 종료 SOC | `finish_state_of_charge = current_soc - change_in_charge` |
| 오류 계약 | 실패 시 `success=false`와 구체적인 `reason_code`가 반환됨 |

`pinky_pro`, `control_system`, `/home/syw/rmf_ws` 소스는 이 검증에서 수정하지 않는다.

## 1. 빌드 및 자동 테스트

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
source /home/syw/rmf_ws/install/setup.bash

colcon build \
  --packages-select trihouse_interfaces trihouse_rmf_bridge \
  --cmake-args -DBUILD_TESTING=ON

source /home/syw/Trihouse/install/setup.bash
colcon test --packages-select trihouse_rmf_bridge --event-handlers console_direct+
colcon test-result --verbose
```

자동 테스트는 작은 test graph 단위 테스트와 실제 office graph를 사용하는 ROS service 통합 테스트를 함께 실행한다.

## 2. 수동 테스트

### 터미널 1: office 시뮬레이션

```bash
source /opt/ros/jazzy/setup.bash
source /home/syw/rmf_ws/install/setup.bash
ros2 launch rmf_demos_gz office.launch.xml
```

Gazebo와 RMF demo가 완전히 기동할 때까지 기다린다.

### 터미널 2: Trihouse bridge

```bash
source /opt/ros/jazzy/setup.bash
source /home/syw/rmf_ws/install/setup.bash
source /home/syw/Trihouse/install/setup.bash
ros2 launch trihouse_rmf_bridge office_energy_bridge.launch.py
```

launch는 사용자 홈 경로를 설정에 고정하지 않고 `rmf_demos_maps` package share에서 `maps/office/nav_graphs/0.yaml`을 찾는다.

### 터미널 3: 입력 상태와 서비스 확인

```bash
source /opt/ros/jazzy/setup.bash
source /home/syw/rmf_ws/install/setup.bash
source /home/syw/Trihouse/install/setup.bash

ros2 topic echo /fleet_states rmf_fleet_msgs/msg/FleetState --once
ros2 service type /trihouse/rmf/estimate_task_energy
```

첫 명령 출력에서 fleet `tinyRobot`, robot `tinyRobot1`, `location`, `mode`, `task_id`, `battery_percent`를 확인한다. 두 번째 명령은 `trihouse_interfaces/srv/EstimateTaskEnergy`를 출력해야 한다.

### 터미널 4: 에너지 예측 요청

Trihouse 저장소 root에서 실행한다.

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
source /home/syw/Trihouse/install/setup.bash

python3 -m control_tower.rmf_adapter.estimate_energy_cli \
  --robot-id tinyRobot1 \
  --waypoint pantry \
  --waypoint hardware_2 \
  --loading-duration-s 30 \
  --handover-duration-s 30 \
  --buffer-duration-s 15
```

정상 출력 예시는 다음 형태의 한 줄 JSON이다. 실제 수치는 현재 위치에 따라 달라진다.

```json
{"change_in_charge": 0.001, "detail": "RMF route and energy estimate completed", "finish_state_of_charge": 0.799, "reason_code": "OK", "success": true, "total_duration_s": 110.0, "travel_duration_s": 35.0}
```

## 3. 오류 동작 확인

### 존재하지 않는 waypoint

```bash
python3 -m control_tower.rmf_adapter.estimate_energy_cli \
  --robot-id tinyRobot1 \
  --waypoint not_a_waypoint
```

예상 결과는 종료코드 `1`, `success=false`, `reason_code=RMF_WAYPOINT_NOT_FOUND`다.

### 첫 fleet state 전 또는 오래된 상태

- office demo 없이 bridge만 실행한 직후: `WAITING_FOR_FIRST_RMF_FLEET_STATE`
- 한 번 수신한 뒤 3초 넘게 대상 상태가 끊긴 경우: `RMF_FLEET_STATE_STALE`
- 대상 robot이 fleet 메시지에 없는 경우: `RMF_ROBOT_NOT_FOUND`
- `battery_percent`가 NaN 또는 `0..100` 밖인 경우: `RMF_BATTERY_PERCENT_INVALID`

이 오류에서는 이전 정상 예측값을 재사용하지 않고 새 작업 배정을 중단한다.

## 4. 자동 측정 로그

Control Tower composition에서 `RmfEnergyEstimator`에 `MeasurementLogWriter.from_environment(component="control_tower")`를 주입하면 요청·응답과 실패 코드가 다음 파일에 JSONL로 누적된다.

```bash
export TRIHOUSE_MEASUREMENT_RUN_ID=office_bridge_poc_01
export TRIHOUSE_MEASUREMENT_LOG_ROOT=$HOME/.ros/trihouse/measurements

tail -f \
  "$TRIHOUSE_MEASUREMENT_LOG_ROOT/$TRIHOUSE_MEASUREMENT_RUN_ID/rmf_energy_estimates.jsonl"
```

주요 기록값은 robot/task/waypoint, 작업 단계 시간, 호출 횟수, ETA, 전체 시간, 예상 SOC 감소량, 종료 SOC, source, `reason_code`다. 파일 기록 실패는 배차 판단을 바꾸지 않는다.

## 5. QoS 확인

bridge는 자주 갱신되고 과거 전체 이력이 필요 없는 fleet 상태에 `SensorDataQoS`를 사용한다. 실행 중 실제 endpoint 호환성은 다음 명령으로 확인한다.

```bash
ros2 topic info /fleet_states --verbose
```

bridge subscription이 표시되고 publisher와 reliability가 호환되어야 한다. service는 ROS 2 service 기본 QoS를 사용한다.
