# Trihouse 공용 인터페이스 카탈로그

> 상태: 후보 계약 초안. 아래 파일은 아직 `.msg`, `.srv`, `.action`으로 구현되지 않았다. 예상 필드는 설계 검토를 위한 최소안이며 구현 전에 확정해야 한다.

## Messages

| 이름 | 목적 | 예상 필드 | 주 발행자 | 주 구독자 | 관련 SR | 상태 |
|---|---|---|---|---|---|---|
| `DeliveryOrder` | 입·출고 주문을 운반 작업으로 전달 | `schema_version`, `order_id`, `task_id`, `kind`, `map_revision`, `pickup`, `dropoff`, `priority`, `deadline` | 관제 | fleet, 로봇팔 | SR_01~07, SR_15 | 초안 |
| `RobotStatus` | 로봇의 운용 상태와 위치 보고 | `robot_id`, `task_id`, `phase`, `pose`, `battery_percent`, `safety_state`, `ready`, `stamp` | fleet | 관제/UI | SR_20, SR_36 | 초안 |
| `TaskEvent` | 작업 단계 변화와 결과 이벤트 | `event_id`, `task_id`, `robot_id`, `type`, `phase`, `reason`, `stamp` | fleet | 관제 | SR_44 | 초안 |
| `TaskTrace` | 재시도·지연을 포함한 추적 기록 | `task_id`, `seq`, `component`, `event`, `detail`, `stamp` | fleet | 관제/로그 | SR_50 | 초안 |
| `HandoverReady` | 인수인계 참여자의 준비 완료 알림 | `task_id`, `station_id`, `actor_id`, `role`, `ready`, `stamp` | fleet, 로봇팔 | 관제 | SR_40 | 초안 |
| `HandoverGo` | 관제가 검증 후 인수인계를 허가 | `task_id`, `station_id`, `authorization_id`, `expires_at` | 관제 | fleet, 로봇팔 | SR_40 | 초안 |
| `HandoverDone` | 인수인계 결과 보고 | `task_id`, `station_id`, `actor_id`, `success`, `reason`, `stamp` | fleet, 로봇팔 | 관제 | SR_40~41 | 초안 |
| `PackingAssistanceRequest` | 포장대 예외에 작업자 도움 요청 | `task_id`, `station_id`, `robot_id`, `reason`, `stamp` | fleet | 관제/UI | SR_49 | 초안 |
| `PackingDirective` | 관제가 포장대 행동을 지시 | `task_id`, `station_id`, `directive`, `authorization_id`, `expires_at` | 관제 | fleet, 로봇팔 | SR_46, SR_49 | 초안 |
| `PackingStationStatus` | 포장대 점유·작업자 상태 전달 | `station_id`, `occupied`, `worker_present`, `worker_id`, `stamp`, `source` | 관제/서버 추론 | fleet, 로봇팔 | SR_46 | 초안 |
| `PersonDetection` | 서버 사람 검출 결과 전달 | `camera_id`, `track_id`, `bbox`, `pose_class`, `distance_estimate`, `frame_id`, `capture_stamp`, `confidence` | 서버 추론 | vision → safety | SR_25~26, SR_32 | 초안 |
| `MarkerObservation` | 서버 마커 관측 결과 전달 | `camera_id`, `marker_id`, `pose`, `frame_id`, `capture_stamp`, `confidence` | 서버 추론 | vision → docking/fleet | SR_14, SR_40 | 초안 |
| `StreamHealth` | 영상 송신 상태 보고 | `camera_id`, `state`, `fps`, `bitrate_kbps`, `last_frame_stamp`, `detail`, `stamp` | vision | bringup readiness, fleet, 관제 | SR_14, SR_25, SR_40 | 초안 |
| `KeepOutZone` | 동적 진입 금지 구역 전달 | `zone_id`, `frame_id`, `polygon`, `reason`, `valid_until`, `revision` | 관제 | safety/Nav2 연동 | SR_29, SR_32 | 초안 |
| `EmergencyAlert` | 위급상황 후보와 증거 위치 보고 | `alert_id`, `robot_id`, `zone_id`, `camera_id`, `detected_pose`, `detected_stamp`, `evidence_stream_uri`, `state` | safety/fleet | 관제 | SR_32 | 초안 |

## Services

| 이름 | 목적 | 예상 요청 → 응답 | 서버 | 클라이언트 | 관련 SR | 상태 |
|---|---|---|---|---|---|---|
| `ClearEmergency` | 래치된 비상 상태의 명시적 해제 | `robot_id`, `operator_id`, `reason`, `request_id` → `accepted`, `message`, `cleared_at` | safety | 관제/관리자 도구 | SR_32 | 초안 |
| `GetLocation` | location ID와 지도 좌표 조회 | `location_id`, `map_revision` → `found`, `pose`, `kind`, `revision` | 관제 위치 레지스트리 | fleet/로봇팔 | SR_04, SR_06, SR_15 | 초안 |

## Actions

| 이름 | 목적 | Goal / Feedback / Result 예상 필드 | 서버 | 클라이언트 | 관련 SR | 상태 |
|---|---|---|---|---|---|---|
| `ExecuteTransport` | 구조화된 운반 작업 전체 수행 | Goal: `task_id`, `map_revision`, 위치/pose, 우선순위; Feedback: `phase`, `pose`, `progress`; Result: `success`, `code`, `message` | fleet | 관제 브리지 | SR_15, SR_36 | 초안 |
| `Dock` | Nav2 이후 마커 기반 정밀 정차 | Goal: `task_id`, `marker_id`, `target_offset`, 허용오차; Feedback: 상대 pose, 재시도, 상태; Result: 성공 여부와 최종 오차 | docking | fleet | SR_14 | 초안 |

## 확정 전 공통 검토

- 문자열 상태값을 상수로 둘지 별도 enum 메시지로 둘지 결정한다.
- 각 계약의 QoS, timeout, stale 기준, idempotency key를 확정한다.
- 외부 NDJSON `schema_version`과 각 ROS 필드의 매핑표를 관제 문서에 고정한다.
- 좌표 메시지는 `geometry_msgs` 타입과 프레임 규약을 확정한다.

