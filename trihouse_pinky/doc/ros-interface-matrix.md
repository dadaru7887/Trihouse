# ROS 인터페이스 매트릭스

> 상태: 가칭을 포함한 구현 전 초안. `/trihouse/*` 이름과 사용자 정의 타입은 구현 전에 확정한다.

## 토픽

| 패키지 | 방향 | 이름 | 타입 | 상대 | 비고 |
|---|---|---|---|---|---|
| bringup | 감시 | 필수 센서/노드 health | 표준/진단 | 각 노드 | readiness 조합만 계획 |
| fleet | 발행 | `/trihouse/robot_status` | `trihouse_interfaces/RobotStatus` | 관제 브리지 | 가칭 |
| fleet | 발행 | `/trihouse/task_event`, `/trihouse/task_trace` | `TaskEvent`, `TaskTrace` | 관제 브리지 | 가칭 |
| fleet | 발행/구독 | `/trihouse/handover/*` | `HandoverReady/Go/Done` | 관제/로봇팔 | 가칭 |
| fleet | 구독 | `/trihouse/packing_station_status`, `/trihouse/packing_directive` | `PackingStationStatus`, `PackingDirective` | 관제 | 가칭 |
| fleet | 구독 | `/amcl_pose`, `/battery/*`, `/odom` | ROS 2 표준 | pinky_pro | 상태/readiness |
| vision | 발행 | `/trihouse/vision/stream_health` | `StreamHealth` | fleet/관제/bringup | 영상 본체 아님 |
| vision | 구독 | `/trihouse/vision/marker_observation/camera` | `MarkerObservation` | 서버 추론 브리지 | camera frame |
| vision | 발행 | `/trihouse/vision/marker_observation/base` | `MarkerObservation` | docking/fleet | `base_link` 변환 |
| vision | 구독/발행 | `/trihouse/vision/person_detection/{camera,base}` | `PersonDetection` | 서버 추론/safety | stale 검사 포함 |
| safety | 구독 | `/cmd_vel_nav`, `/cmd_vel_dock` | `geometry_msgs/Twist` | Nav2/docking | 표준 타입 |
| safety | 발행 | `/cmd_vel` | `geometry_msgs/Twist` | pinky_bringup | 유일한 운영 발행자 |
| safety | 구독 | `/scan`, `us_sensor/range`, `ir_sensor/range` | ROS 2 표준/벤더 | pinky_pro | 장애물 판정 |
| safety | 구독 | `/trihouse/keep_out_zone` | `KeepOutZone` | 관제 | 가칭 |
| safety | 발행 | `/trihouse/emergency_alert` | `EmergencyAlert` | 관제 | 가칭 |
| docking | 구독 | `/trihouse/vision/marker_observation/base` | `MarkerObservation` | vision | fresh 관측만 사용 |
| docking | 발행 | `/cmd_vel_dock` | `geometry_msgs/Twist` | safety | Nav2 종료 후만 |

## 서비스

| 제공 패키지 | 이름 | 타입 | 호출자 | 상태 |
|---|---|---|---|---|
| safety | `/trihouse/clear_emergency` | `ClearEmergency` | 관제 관리자 | 가칭/초안 |
| 관제 | `/trihouse/get_location` | `GetLocation` | fleet | 가칭/초안 |

fleet은 `pinky_led`, `pinky_lamp_control`, `pinky_emotion`의 기존 표시 서비스를 호출할 계획이다. 정확한 서비스 이름과 타입은 실제 ROS graph에서 확인한다.

## 액션

| 제공 패키지 | 이름 | 타입 | 호출자 | 상태 |
|---|---|---|---|---|
| fleet | `/trihouse/execute_transport` | `ExecuteTransport` | 관제 브리지 | 가칭/초안 |
| docking | `/trihouse/dock` | `Dock` | fleet | 가칭/초안 |
| Nav2 | `/navigate_to_pose` | `nav2_msgs/action/NavigateToPose` | fleet | ROS 2 표준/기존 |

## 일관성 규칙

- vision은 `StreamHealth`와 변환된 관측을 발행하고 docking/safety는 이를 구독한다.
- fleet은 `/cmd_vel*`을 발행하지 않는다.
- docking은 `/cmd_vel_dock`, Nav2는 `/cmd_vel_nav`만 발행한다.
- ROS 2 이미지 토픽은 실물 운영 영상 전송 계약에 포함하지 않는다.

