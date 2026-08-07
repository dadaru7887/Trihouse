# Trihouse 공용 ROS 인터페이스 카탈로그

## 공통 규칙

- Pinky 1: `ROS_DOMAIN_ID=51`, `robot_id=PK-01`
- Pinky 2: `ROS_DOMAIN_ID=52`, `robot_id=PK-02`
- Topic 이름에는 robot ID를 넣지 않는다.
- 외부 Control Tower·Vision 서버는 TCP/NDJSON·REST·WebSocket을 사용하고 onboard gateway가 ROS로 변환한다.
- `TRANSIENT_LOCAL` 상태 Topic의 depth는 1이다.
- camera 관측의 `header.frame_id`는 `camera_optical_frame`, base 관측은 `base_link`다.

## Topics

| Topic | Type | QoS | Publisher | Subscriber |
|---|---|---|---|---|
| `/trihouse/battery` | `sensor_msgs/msg/BatteryState` | RELIABLE, 1 Hz | battery adapter | policy classifier, status |
| `/trihouse/battery/policy_state` | `trihouse_interfaces/msg/BatteryPolicyState` | RELIABLE + TRANSIENT_LOCAL, depth 1 | policy classifier | battery client, status |
| `/trihouse/fms/state` | `trihouse_interfaces/msg/ConnectionState` | RELIABLE + TRANSIENT_LOCAL, depth 1 | onboard gateway | fleet, health |
| `/trihouse/indicator/state` | `trihouse_interfaces/msg/IndicatorState` | RELIABLE + TRANSIENT_LOCAL, depth 1 | indicator selector | LED client |
| `/trihouse/navigation/state` | `trihouse_interfaces/msg/NavigationState` | RELIABLE, depth 10 | Nav2 command adapter | task event, status |
| `/trihouse/task/events` | `trihouse_interfaces/msg/TaskEvent` | RELIABLE, depth 50 | task event publisher | onboard gateway |
| `/trihouse/readiness` | `trihouse_interfaces/msg/Readiness` | RELIABLE + TRANSIENT_LOCAL, depth 1 | bringup checker | fleet, health |
| `/trihouse/health` | `trihouse_interfaces/msg/RobotHealth` | RELIABLE + TRANSIENT_LOCAL, depth 1 | health reporter | onboard gateway |
| `/trihouse/status` | `trihouse_interfaces/msg/RobotStatus` | RELIABLE, depth 10, 1 Hz | telemetry publisher | onboard gateway |
| `/trihouse/safety/proximity_stop` | `std_msgs/msg/Bool` | RELIABLE, depth 1 | ultrasonic guard | safety supervisor |
| `/trihouse/safety/state` | `trihouse_interfaces/msg/SafetyState` | RELIABLE + TRANSIENT_LOCAL, depth 1 | safety supervisor | fleet, LED selector, status |
| `/trihouse/safety/keep_out_zones` | `trihouse_interfaces/msg/KeepOutZone` | RELIABLE + TRANSIENT_LOCAL | gateway | safety supervisor |
| `/trihouse/handover/state` | `trihouse_interfaces/msg/HandoverState` | RELIABLE, depth 20 | handover manager | fleet, cargo controller |
| `/trihouse/cargo/state` | `trihouse_interfaces/msg/CargoState` | RELIABLE + TRANSIENT_LOCAL, depth 1 | cargo controller | fleet, health |
| `/trihouse/vision/stream_health` | `trihouse_interfaces/msg/StreamHealth` | RELIABLE, depth 10, 1 Hz | vision sender | readiness, health, gateway |
| `/trihouse/vision/readiness` | `trihouse_interfaces/msg/Readiness` | RELIABLE + TRANSIENT_LOCAL, depth 1 | observation gate | docking, handover, health |
| `/trihouse/vision/person_detection/camera` | `trihouse_interfaces/msg/PersonDetection` | RELIABLE, depth 10 | detection bridge | observation transformer |
| `/trihouse/vision/person_detection/base` | `trihouse_interfaces/msg/PersonDetection` | RELIABLE, depth 10 | observation transformer | LED selector, safety |
| `/trihouse/vision/object_detection/camera` | `trihouse_interfaces/msg/ObjectDetection` | RELIABLE, depth 10 | detection bridge | observation transformer |
| `/trihouse/vision/object_detection/base` | `trihouse_interfaces/msg/ObjectDetection` | RELIABLE, depth 10 | observation transformer | fleet, safety |
| `/trihouse/vision/marker_observation/camera` | `trihouse_interfaces/msg/MarkerObservation` | RELIABLE, depth 10 | detection bridge | observation transformer |
| `/trihouse/vision/marker_observation/base` | `trihouse_interfaces/msg/MarkerObservation` | RELIABLE, depth 10 | observation transformer | docking, fleet |

표준 센서·제어 Topic은 `/scan`, `/imu/data_raw`, `/wheel/odometry`,
`/odometry/filtered`, `/trihouse/proximity/front`, `/cmd_vel_nav`,
`/cmd_vel_dock`, `/cmd_vel`을 사용한다.

## Services

| Service | Type | Server | Client |
|---|---|---|---|
| `/trihouse/safety/clear_emergency` | `trihouse_interfaces/srv/ClearEmergency` | safety supervisor | gateway/operator adapter |
| `/trihouse/cargo/set_lock` | `trihouse_interfaces/srv/SetCargoLock` | cargo controller | handover manager |

Pinky LED는 기존 `/set_led` (`pinky_interfaces/srv/SetLed`)를 그대로 사용한다.

## Actions

| Action | Type | Server | Client |
|---|---|---|---|
| `/trihouse/dock` | `trihouse_interfaces/action/Dock` | docking | fleet |
| `/trihouse/transport/execute` | `trihouse_interfaces/action/ExecuteTransport` | fleet | onboard gateway |
| `/navigate_to_pose` | `nav2_msgs/action/NavigateToPose` | Nav2 | Nav2 command adapter |

## 외부 통신 경계

| 외부 경로 | 방향 | ROS 대응 |
|---|---|---|
| TCP 8788 NDJSON `execute_transport`, `hold`, `cancel_task` | Control Tower → gateway | `ExecuteTransport`, Nav2 adapter |
| NDJSON `robot_status`, `device_event` | gateway → Control Tower | `RobotStatus`, `RobotHealth`, `SafetyState` |
| NDJSON `task_feedback`, `task_result` | gateway → Control Tower | `TaskEvent` |
| NDJSON detection messages | Control Tower → vision bridge | camera-frame detection Topics |
| RTSP `/pinky_1`, `/pinky_2` | Pinky → MediaMTX | ROS 영상 Topic 없음 |
