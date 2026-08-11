# Open-RMF 에너지 Bridge 설계

## 1. 목표

Open-RMF office 시뮬레이션에서 발행하는 실제 fleet 상태와 공식 RMF 경로·배터리 모델을 Trihouse의 `EstimateTaskEnergy` 계약에 연결한다.

이번 단계의 완료 조건은 다음과 같다.

- `/fleet_states`에서 `tinyRobot1`의 현재 위치, 운행 mode, task ID, 배터리 백분율을 수신한다.
- 설치된 office navigation graph를 공식 `rmf_traffic` planner로 탐색한다.
- 공식 `rmf_battery` motion·ambient sink로 예상 SOC 감소량을 계산한다.
- `/trihouse/rmf/estimate_task_energy` service가 이동시간, 전체 작업시간, 예상 SOC 감소량과 예상 종료 SOC를 응답한다.
- 기존 Control Tower `RmfEnergyEstimator`가 이 service 결과를 소비할 수 있다.
- 자동 테스트와 office 시뮬레이션 수동 검증 절차를 제공한다.

`pinky_pro`, `control_system`, `/home/syw/rmf_ws`의 기존 소스는 수정하지 않는다. 새 연결 코드는 `/home/syw/Trihouse`의 독립 ROS 2 패키지로 추가한다.

## 2. 범위와 제외 범위

### 포함 범위

- ROS 2 Jazzy용 C++ bridge 패키지
- RMF office graph 기반 구간별 경로 계획
- `/fleet_states` 최신 상태 추적과 freshness 검증
- RMF motion·ambient 배터리 소비 계산
- `EstimateTaskEnergy` service server
- service를 호출하는 Control Tower ROS client adapter
- office 설정·launch·자동 테스트
- 설치와 수동 검증 문서
- 기존 JSONL의 `rmf_energy_estimates.jsonl` 기록 경계 유지

### 제외 범위

- Trihouse 실제 navigation graph 제작
- `final_map_08`과 `robosapiens.png`의 좌표 정합
- 실제 Pinky를 RMF fleet에 등록하는 robot command handle
- `control_system` UI 수정
- RMF 전체 task dispatcher를 Trihouse 작업 workflow로 교체
- 실제 배터리 파라미터 보정

office 연동이 검증되면 동일 bridge의 graph·fleet·robot 설정을 Trihouse 값으로 교체한다.

## 3. 접근법 결정

독립 C++ bridge를 사용한다.

Python `rmf_adapter` binding은 graph와 planner를 제공하지만, 현재 설치된 Jazzy binding의 `SimpleMotionPowerSink`에는 `compute_change_in_charge()`가 노출되지 않는다. 임의 공식을 다시 구현하면 RMF 공식 배터리 모델을 사용한다는 요구를 충족하지 못한다.

C++에서는 다음 공식 API를 직접 사용할 수 있다.

- `rmf_traffic::agv::Planner`
- `rmf_traffic::agv::compute_plan_starts`
- `rmf_battery::agv::SimpleMotionPowerSink`
- `rmf_battery::agv::SimpleDevicePowerSink`

`rmf_demos_fleet_adapter`를 수정하는 방식은 demo 버전과 결합되고 나중에 Pinky adapter로 이전하기 어려우므로 사용하지 않는다.

## 4. 패키지 구조

새 패키지 이름은 `trihouse_rmf_bridge`로 한다.

```text
trihouse_rmf_bridge/
├── CMakeLists.txt
├── package.xml
├── include/trihouse_rmf_bridge/
│   ├── energy_estimator.hpp
│   └── fleet_state_store.hpp
├── src/
│   ├── energy_estimator.cpp
│   ├── fleet_state_store.cpp
│   └── energy_estimator_node.cpp
├── config/
│   └── office_bridge.yaml
├── launch/
│   └── office_energy_bridge.launch.py
└── test/
    ├── test_energy_estimator.cpp
    ├── test_fleet_state_store.cpp
    └── test_office_service.py
```

각 파일의 책임은 다음과 같다.

| 구성요소 | 책임 |
|---|---|
| `FleetStateStore` | 대상 fleet·robot의 최신 위치, mode, task ID, SOC와 수신시각을 보존하고 freshness를 판정한다. |
| `EnergyEstimator` | graph 경로 계획, trajectory 시간과 RMF 배터리 sink 계산만 담당한다. ROS 통신에 의존하지 않는다. |
| `EnergyEstimatorNode` | ROS 파라미터, `/fleet_states` 구독, service 요청·응답 변환과 오류 로그를 담당한다. |
| `office_bridge.yaml` | office graph, 대상 fleet·robot, 차량·배터리 모델과 timeout을 고정한다. |
| Control Tower ROS client | 비동기 ROS service를 기존 동기 `EstimateService` port에 맞춰 호출하고 timeout을 전달한다. |

## 5. ROS 인터페이스

### 입력 topic

```text
/fleet_states
rmf_fleet_msgs/msg/FleetState
```

대상은 파라미터로 필터링한다.

```yaml
fleet_name: tinyRobot
robot_name: tinyRobot1
```

`RobotState.battery_percent`는 0~100 범위이므로 내부 SOC 0.0~1.0으로 변환한다.

### 출력 service

```text
/trihouse/rmf/estimate_task_energy
trihouse_interfaces/srv/EstimateTaskEnergy
```

요청의 `waypoint_ids`는 현재 위치 이후 순서대로 방문할 graph waypoint 이름이다. office 검증에서는 `pantry`, `hardware_2`를 사용한다.

응답 규칙은 다음과 같다.

| 필드 | 규칙 |
|---|---|
| `success` | 모든 입력 검증과 전체 구간 계획·계산이 성공했을 때만 true |
| `travel_duration_s` | 모든 RMF trajectory 구간의 실제 계획시간 합 |
| `total_duration_s` | 이동+loading+handover+buffer |
| `change_in_charge` | motion sink+ambient sink의 SOC 감소량 |
| `finish_state_of_charge` | `max(0, current_soc-change_in_charge)` |
| `reason_code` | 프로그램 분기용 고정 영문 코드 |
| `detail` | 운영자와 로그가 읽는 진단 문장 |

## 6. 경로와 에너지 계산

### 시작 위치

최신 `/fleet_states`의 `location.level_name`, `x`, `y`, `yaw`를 `compute_plan_starts`에 전달한다. graph와 결합할 수 있는 start가 없으면 요청을 거절한다.

### 다중 waypoint

`waypoint_ids` 순서대로 구간을 계획한다.

```text
현재 위치 → waypoint[0] → waypoint[1] → ...
```

각 구간의 종료 waypoint와 종료시각·방향을 다음 구간의 시작으로 사용한다. 하나의 구간이라도 연결되지 않으면 전체 요청을 실패시킨다. 부분 결과로 SOC를 판단하지 않는다.

### 시간

```text
travel_duration_s
= segment trajectory end time - segment start time

total_duration_s
= travel_duration_s
 + expected_loading_duration_s
 + expected_handover_duration_s
 + task_time_buffer_s
```

요청의 작업 단계 시간은 0 이상이어야 한다.

### 배터리

각 계획의 itinerary에 포함된 모든 trajectory를 `SimpleMotionPowerSink`에 전달하고 감소량을 합산한다.

`SimpleDevicePowerSink`의 ambient 소비는 전체 작업시간에 적용한다. OMX는 Pinky 배터리를 사용하지 않는다는 기존 결정에 따라 tool power는 이번 bridge에 포함하지 않는다.

```text
change_in_charge
= motion_change
 + ambient_change(total_duration_s)

finish_state_of_charge
= max(0.0, current_state_of_charge - change_in_charge)
```

계산 결과가 유한수가 아니거나 감소량이 음수이면 실패한다.

## 7. office 설정

`office_bridge.yaml`의 초기값은 설치된 `rmf_demos 2.3.0` office fleet 설정과 동일하게 둔다.

| 설정 | 값 |
|---|---:|
| linear velocity | 0.5 m/s |
| linear acceleration | 0.75 m/s² |
| angular velocity | 0.6 rad/s |
| angular acceleration | 2.0 rad/s² |
| footprint | 0.3 m |
| vicinity | 0.5 m |
| reversible | true |
| nominal voltage | 12.0 V |
| capacity | 24.0 Ah |
| charging current | 5.0 A |
| mass | 20.0 kg |
| moment of inertia | 10.0 kg·m² |
| friction coefficient | 0.22 |
| ambient power | 20.0 W |
| fleet state timeout | 3.0 s |

nav graph 경로는 launch에서 `rmf_demos_maps` package share의 `maps/office/nav_graphs/0.yaml`로 해석한다. 특정 사용자 홈 경로를 코드나 설정 기본값에 저장하지 않는다.

## 8. 오류 처리

| 상황 | reason_code | 처리 |
|---|---|---|
| 첫 fleet state 전 | `WAITING_FOR_FIRST_RMF_FLEET_STATE` | 실패 응답, 새 작업 배정 금지 |
| state timeout | `RMF_FLEET_STATE_STALE` | 실패 응답, 새 작업 배정 금지 |
| 대상 robot 없음 | `RMF_ROBOT_NOT_FOUND` | 다른 robot 상태를 사용하지 않음 |
| SOC 범위 오류 | `RMF_BATTERY_PERCENT_INVALID` | 실패 응답 |
| 빈 waypoint 목록 | `RMF_WAYPOINTS_REQUIRED` | 실패 응답 |
| waypoint 이름 없음 | `RMF_WAYPOINT_NOT_FOUND` | 실패 응답 |
| 현재 위치 graph 결합 실패 | `RMF_START_NOT_ON_GRAPH` | 실패 응답 |
| 경로 단절 | `RMF_ROUTE_UNAVAILABLE` | 실패 응답 |
| 음수 단계 시간 | `RMF_TASK_DURATION_INVALID` | 실패 응답 |
| 모델 생성·계산 오류 | `RMF_ENERGY_MODEL_INVALID` | 실패 응답 |

오류는 service 응답으로 반환하며 node process를 종료하지 않는다. 마지막 정상 예측값을 재사용하지 않는다.

## 9. Control Tower 연결

기존 `control_tower/rmf_adapter/energy_estimator.py`의 `RmfEnergyEstimator`와 정책 코드는 유지한다. 새 ROS client adapter가 `EstimateRequest`를 ROS service request로 변환하고 응답을 `RmfEstimateResponse`로 변환한다.

service timeout은 기존 결정대로 2초이고 한 번 재시도한다. service 실패·timeout·`success=false`는 `RMF_ENERGY_ESTIMATE_UNAVAILABLE` 또는 server reason을 로그에 기록하고 `LOCAL_ONLY` 새 작업을 배정하지 않는다.

이번 단계에서는 전체 Control Tower daemon을 새로 만들지 않는다. client adapter는 composition root가 생길 때 주입 가능한 독립 구성요소와 수동 검증 CLI로 제공한다.

## 10. 테스트 설계

### C++ 단위 테스트

- 작은 test graph에서 연결 경로 ETA가 양수인지 검증한다.
- motion과 ambient 감소량이 양수인지 검증한다.
- 전체 작업시간이 세 단계 시간과 buffer를 포함하는지 검증한다.
- 다중 waypoint 구간을 순서대로 합산하는지 검증한다.
- 없는 waypoint와 단절 경로를 거절하는지 검증한다.
- 음수 단계 시간을 거절하는지 검증한다.

### 상태 저장소 테스트

- 다른 fleet과 robot 상태를 무시한다.
- 100%와 18%를 각각 1.0과 0.18로 변환한다.
- 첫 상태 전과 timeout 후에는 unavailable이다.
- NaN과 0~100 범위 밖의 배터리를 거절한다.

### ROS 통합 테스트

- 가짜 `/fleet_states`를 발행하되 실제 office graph와 RMF planner·battery library를 사용한다.
- `pantry → hardware_2` service 응답의 ETA·감소량·종료 SOC를 확인한다.
- state 미수신, stale, robot 없음, waypoint 없음 응답 코드를 확인한다.
- Control Tower client의 정상 응답·timeout·실패 변환을 확인한다.

### 전체 회귀

- `colcon build`로 `trihouse_interfaces`와 `trihouse_rmf_bridge`를 빌드한다.
- bridge C++·launch 테스트를 실행한다.
- 기존 Control Tower, interface, Pinky 테스트를 실행한다.
- `pinky_pro`와 `control_system`의 기존 dirty 상태 외에 새 변경이 없는지 확인한다.

## 11. 수동 검증 결과물

문서에는 터미널별로 다음 과정을 제공한다.

1. ROS 2, RMF, Trihouse overlay source
2. `rmf_demos_gz office.launch.xml` 실행
3. `/fleet_states`의 `tinyRobot1.battery_percent` 확인
4. office bridge 실행
5. service type·availability 확인
6. `pantry → hardware_2` 에너지 요청
7. 반환 ETA·SOC 감소량 확인
8. `dispatch_loop`로 실제 시뮬레이션 이동 실행
9. 이동 전후 `/fleet_states` SOC 비교
10. JSONL 에너지 예측·정책 판단 확인

GUI 실행이 불가능한 자동 환경에서는 실제 Gazebo 대신 가짜 FleetState publisher와 실제 office graph/library를 사용하는 통합 테스트로 같은 계산 경계를 검증한다.

## 12. 지도 파일 후속 처리

이번 office bridge는 다음 파일을 수정하거나 graph 입력으로 사용하지 않는다.

- `/home/syw/Desktop/final_map_08.pgm`
- `/home/syw/Desktop/final_map_08.yaml`
- `/home/syw/Trihouse/control_system/rmf_maps/robosapiens.png`

확인된 SLAM YAML은 해상도 0.05m/pixel, 원점 `[-0.277, -1.452, 0]`이다. 다만 현재 `.pgm` 파일 내용은 44×54 PNG로 인식되므로 Trihouse graph 제작 전에 원본 occupancy map인지 다시 확인한다.

`robosapiens.png`는 2000×2402 UI 도식이며 resolution과 origin이 없다. 후속 단계에서는 원본 SLAM map을 좌표 기준으로 사용하고, UI 이미지는 별도 affine transform으로 표시 좌표에 맞춘다.
