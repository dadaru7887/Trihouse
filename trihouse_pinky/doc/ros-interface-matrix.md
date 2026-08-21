# Pinky ROS 인터페이스 매트릭스

공통 타입과 QoS의 원본은
[`trihouse_interfaces/doc/interface-catalog.md`](../../trihouse_interfaces/doc/interface-catalog.md)다.

## 역할별 생산·소비

| 역할 | 방향 | Endpoint | Type | 상대 역할 |
|---|---|---|---|---|
| io | 발행 | `/trihouse/battery` | `sensor_msgs/msg/BatteryState` | fleet |
| io | 발행 | `/trihouse/proximity/front` | `sensor_msgs/msg/Range` | safety |
| io | 구독 | `/trihouse/indicator/state` | `trihouse_interfaces/msg/IndicatorState` | safety/vision selector |
| localization | 구독 | `/imu_raw`, `/odom` | 표준 sensor/nav messages | Pinky Pro |
| localization | 발행 | `/imu/data_raw`, `/wheel/odometry`, `/odometry/filtered` | 표준 sensor/nav messages | EKF/Nav2/fleet |
| fleet | 구독 | `/trihouse/fms/state` | `trihouse_interfaces/msg/ConnectionState` | gateway |
| fleet | 발행 | `/trihouse/status` | `trihouse_interfaces/msg/RobotStatus` | gateway |
| fleet | 발행 | `/trihouse/navigation/state` | `trihouse_interfaces/msg/NavigationState` | task event/status |
| fleet | 발행 | `/trihouse/task/events` | `trihouse_interfaces/msg/TaskEvent` | gateway |
| fleet | 발행 | `/trihouse/handover/state` | `trihouse_interfaces/msg/HandoverState` | cargo/fleet |
| safety | 구독 | `/cmd_vel_nav`, `/cmd_vel_dock` | `geometry_msgs/msg/Twist` | Nav2/docking |
| safety | 구독 | `/scan`, `/trihouse/proximity/front` | `LaserScan`, `Range` | Pinky Pro/io |
| safety | 구독 | `/trihouse/vision/person_detection/base` | `trihouse_interfaces/msg/PersonDetection` | vision |
| safety | 구독 | `/trihouse/safety/keep_out_zones` | `trihouse_interfaces/msg/KeepOutZone` | gateway |
| safety | 발행 | `/cmd_vel` | `geometry_msgs/msg/Twist` | motor driver |
| safety | 발행 | `/trihouse/safety/state` | `trihouse_interfaces/msg/SafetyState` | fleet/io/gateway |
| vision | 발행 | `/trihouse/vision/stream_health` | `trihouse_interfaces/msg/StreamHealth` | readiness/health/gateway |
| vision gate | 발행 | `/trihouse/vision/readiness` | `trihouse_interfaces/msg/Readiness` | docking/handover/health |
| vision bridge | 발행 | `/trihouse/vision/person_detection/camera` | `trihouse_interfaces/msg/PersonDetection` | transformer |
| vision bridge | 발행 | `/trihouse/vision/object_detection/camera` | `trihouse_interfaces/msg/ObjectDetection` | transformer |
| vision bridge | 발행 | `/trihouse/vision/marker_observation/camera` | `trihouse_interfaces/msg/MarkerObservation` | transformer |
| gateway | 발행 | `/trihouse/vision/person_detection/base` | `trihouse_interfaces/msg/PersonDetection` | LED/safety |
| vision transform | (예정) | `/trihouse/vision/person_detection/base` | `trihouse_interfaces/msg/PersonDetection` | LED/safety |
| vision transform | 발행 | `/trihouse/vision/object_detection/base` | `trihouse_interfaces/msg/ObjectDetection` | fleet/safety |
| vision transform | 발행 | `/trihouse/vision/marker_observation/base` | `trihouse_interfaces/msg/MarkerObservation` | docking/fleet |
| docking | 구독 | `/trihouse/vision/marker_observation/base`, `/trihouse/vision/readiness` | `MarkerObservation`, `Readiness` | vision |
| docking | 발행 | `/cmd_vel_dock` | `geometry_msgs/msg/Twist` | safety |

## Services

| 제공 역할 | Endpoint | Type | 호출 역할 |
|---|---|---|---|
| safety | `/trihouse/safety/clear_emergency` | `trihouse_interfaces/srv/ClearEmergency` | gateway/operator adapter |
| Pinky LED | `/set_led` | `pinky_interfaces/srv/SetLed` | io LED client |

## Actions

| 제공 역할 | Endpoint | Type | 호출 역할 |
|---|---|---|---|
| fleet | `/trihouse/transport/execute` | `trihouse_interfaces/action/ExecuteTransport` | onboard gateway |
| docking | `/trihouse/dock` | `trihouse_interfaces/action/Dock` | fleet |
| Nav2 | `/navigate_to_pose` | `nav2_msgs/action/NavigateToPose` | fleet Nav2 adapter |

## 단일 소유 규칙

- Nav2 action client는 `nav2_command_adapter` 하나만 소유한다.
- `/cmd_vel` 운영 발행자는 safety velocity gate 하나만 존재한다.
- detection bridge는 camera-frame, transformer는 base-frame Topic만 발행한다.
- ROS publisher는 TCP 재전송을 수행하지 않고 onboard gateway가 NDJSON을 담당한다.
- IR 센서는 운영 안전 입력에 사용하지 않는다.
