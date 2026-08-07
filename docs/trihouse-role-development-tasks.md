# Trihouse 역할별 개발 태스크

## 분할 원칙

- 파일 하나가 아니라 독립 실행·시험 가능한 결과물 하나를 태스크로 둔다.
- producer와 consumer는 공통 인터페이스를 먼저 합의하고 각자 병렬 개발한다.
- ROS Topic publisher와 TCP/NDJSON 재전송을 같은 태스크에 넣지 않는다.
- 안전 gate, 복구, 분산 인계는 초보자용 단순 adapter와 분리한다.
- 인터페이스 message 파일별로 담당자를 나누지 않고 공통 계약 패키지 한 작업으로 묶는다.

## 선행 순서

```text
I-01 공통 인터페이스
 ├─ P-IO / P-LOC / P-VISION
 ├─ P-SAFETY
 ├─ P-FLEET
 ├─ CT-GATEWAY / CT-DATA
 └─ VS-COMMON
       ↓
Pinky-ControlTower 최소 수직 통합
       ↓
Docking · Handover · RMF · 고급 Vision
```

## 공통 인터페이스

| ID | 담당 폴더 | 작업 | 선행 | 완료 기준 |
|---|---|---|---|---|
| I-01 | `trihouse_interfaces/` | message 16개, service 2개, action 2개의 변경 관리와 호환성 시험 | 없음 | `colcon build`와 계약 pytest 통과 |

`I-01`은 이미 최초 계약이 구현된 상태다. 이후 필드 추가는 producer·consumer 양쪽
담당자 리뷰를 받은 뒤 메시지 끝에만 추가한다.

## Pinky 온보드

| ID | 난이도 | 담당 폴더 | 작업 묶음 | 입력 | 출력 | 선행 |
|---|---|---|---|---|---|---|
| P-IO-01 | 하 | `trihouse_pinky_io/` | 배터리·초음파 표준 adapter | `/batt_state`, `/us_sensor/range` | `/trihouse/battery`, `/trihouse/proximity/front` | I-01 |
| P-IO-02 | 하 | `trihouse_pinky_io/` | IndicatorState→기존 LED service 변환 | `/trihouse/indicator/state` | `/set_led` | I-01 |
| P-IO-03 | 중 | `trihouse_pinky_io/` | 사람·비상 LED 상태 선택 | PersonDetection(base), SafetyState | IndicatorState | P-IO-02, P-VIS-02, P-SAFE-02 |
| P-LOC-01 | 하 | `trihouse_pinky_localization/` | IMU·wheel odometry 이름·단위 adapter | `/imu_raw`, `/odom` | `/imu/data_raw`, `/wheel/odometry` | 없음 |
| P-LOC-02 | 중 | `trihouse_pinky_localization/` | EKF·TF·Nav2 filtered odometry 연결 | P-LOC-01 출력 | `/odometry/filtered`, `odom→base_link` | P-LOC-01 |
| P-SAFE-01 | 중 | `trihouse_pinky_safety/` | LiDAR 주 감지·초음파 근거리 guard | `/scan`, proximity Range | `proximity_stop` | P-IO-01 |
| P-SAFE-02 | 상 | `trihouse_pinky_safety/` | 속도 gate·비상 latch·keep-out | cmd_vel inputs, proximity, KeepOutZone | `/cmd_vel`, SafetyState, ClearEmergency | P-SAFE-01, I-01 |
| P-FLEET-01 | 중 | `trihouse_pinky_fleet/` | gateway session·heartbeat·ConnectionState | TCP session | `/trihouse/fms/state` | I-01, CT-GW-01 |
| P-FLEET-02 | 중 | `trihouse_pinky_fleet/` | telemetry·health ROS publisher | pose, battery, safety, readiness | RobotStatus, RobotHealth | P-LOC-02, P-SAFE-02 |
| P-FLEET-03 | 중 | `trihouse_pinky_fleet/` | NDJSON 명령→Nav2 adapter | gateway command, location map | NavigateToPose, NavigationState | P-FLEET-01 |
| P-FLEET-04 | 하 | `trihouse_pinky_fleet/` | NavigationState→TaskEvent 변환 | NavigationState | TaskEvent | P-FLEET-03 |
| P-FLEET-05 | 중 | `trihouse_pinky_fleet/` | 20% 절전·10% 충전 복귀 정책 실행 | BatteryPolicyState, RobotStatus | SpeedLimit, return request | P-FLEET-02, CT-FM-01 |
| P-DOCK-01 | 상 | `trihouse_pinky_docking/` | marker 기반 Dock action | MarkerObservation(base) | Dock result, `/cmd_vel_dock` | P-VIS-02, P-SAFE-02 |
| P-HAND-01 | 상 | `trihouse_pinky_fleet/`, `trihouse_pinky_safety/` | 인계 단계와 화물 잠금 | ExecuteTransport, CargoState | HandoverState, SetCargoLock | P-FLEET-03, P-DOCK-01 |
| P-BRING-01 | 중 | `trihouse_pinky_bringup/` | Domain 51/52 profile·통합 launch·readiness | common/robot YAML | `/trihouse/readiness` | 각 필수 노드 |

`P-HAND-01`은 업무 인계와 물리 잠금이 함께 검증돼야 하므로 전체 acceptance는 하나로
두되, 구현 리뷰는 fleet state machine과 cargo controller 두 모듈로 나눈다.

## Control Tower

| ID | 우선순위 | 담당 폴더 | 작업 묶음 | 입력 | 출력 | 선행 |
|---|---:|---|---|---|---|---|
| CT-GW-01 | 1 | `control_tower/gateway/` | TCP 8788 session·heartbeat·ACK·중복키 | Pinky NDJSON | 내부 event bus, command NDJSON | I-01 |
| CT-DATA-01 | 1 | `control_tower/database/` | migration·repository·command outbox | 내부 events | MySQL transaction API | 없음 |
| CT-TM-01 | 1 | `control_tower/task_manager/` | 기본 운송 workflow | REST job, TaskEvent | execute/cancel command, job events | CT-GW-01, CT-DATA-01 |
| CT-UI-01 | 1 | `control_tower/ui/operations/` | 로봇·작업 상태 운영 화면 | REST/WS | operator REST commands | CT-TM-01 |
| CT-FM-01 | 2 | `control_tower/fleet_manager/` | 배차·배터리·충전소·자원 예약 | RobotStatus, jobs | assignment, speed/return command | CT-TM-01 |
| CT-RMF-01 | 2 | `control_tower/rmf_adapter/` | RMF fleet/traffic adapter | RMF tasks, robot state | internal fleet commands/events | CT-FM-01 |
| CT-MON-01 | 2 | `control_tower/monitoring/` | health·audit·alert·KPI | gateway/workflow events | metrics, incident, report API | CT-GW-01, CT-DATA-01 |
| CT-TEST-01 | 3 | `control_tower/tests/` | 두 로봇·장애·장시간 통합 시험 | simulator, fault profiles | JUnit, metrics, trace | 우선순위 1·2 작업 |

REST route, WebSocket event, DB repository를 각각 별도 태스크로 쪼개지 않는다. 한 workflow가
저장·명령·상태 반영까지 통과해야 검토 가능한 결과물이 되기 때문이다.

## Vision Server·Pinky Vision

| ID | 우선순위 | 담당 폴더 | 작업 묶음 | 입력 | 출력 | 선행 |
|---|---:|---|---|---|---|---|
| P-VIS-01 | 1 | `trihouse_pinky_vision/` | RTSP sender·StreamHealth·Pinky 2 profile | CSI camera | RTSP, StreamHealth | I-01 |
| VS-HUB-01 | 1 | `vision_system/stream_hub/` | MediaMTX 두 stream 수신·metrics | RTSP push | latest stream, health | P-VIS-01 |
| VS-COM-01 | 1 | `vision_system/inference_common/` | latest frame bus·공통 JSON schema·전달 | MediaMTX frames | worker frame, detection event | VS-HUB-01, I-01 |
| VS-PER-01 | 2 | `vision_system/person_worker/` | 사람 검출·추적·자세 후보 | latest frame | PersonDetection JSON | VS-COM-01 |
| VS-OBJ-01 | 2 | `vision_system/object_worker/` | 객체 검출·segmentation·추적 | latest frame | ObjectDetection JSON | VS-COM-01 |
| VS-MARK-01 | 2 | `vision_system/marker_worker/` | QR·ArUco 판독·pose | frame, calibration | MarkerObservation JSON | VS-COM-01 |
| P-VIS-02 | 2 | `trihouse_pinky_vision/` | NDJSON bridge·camera→base TF 변환 | detection JSON, TF | camera/base ROS Topics | Vision worker, I-01 |
| VS-REC-01 | 3 | `vision_system/recording_server/` | incident 녹화·보존·URI/hash | stream, incident | server storage metadata | VS-HUB-01, CT-MON-01 |
| VS-MODEL-01 | 3 | `vision_system/model_registry/`, `training/`, `evaluation/` | 모델 승인·평가·rollback | dataset/model | immutable model release | Vision workers |

사람·객체·마커 worker는 GPU 실행과 평가 기준이 달라 병렬 태스크로 유지한다. 반대로 frame
reader, schema 검사, health를 worker마다 반복하지 않고 `VS-COM-01` 한 작업으로 묶는다.

## 최소 통합 마일스톤

1. `P-IO-01`, `P-LOC-01`, `P-SAFE-02`, `P-BRING-01`로 센서·안전 기동을 완성한다.
2. `CT-GW-01`, `CT-DATA-01`, `CT-TM-01`, `P-FLEET-01~04`로 작업 한 건을 이동·완료한다.
3. `P-VIS-01`, `VS-HUB-01`, `VS-COM-01`, `VS-PER-01`, `P-VIS-02`, `P-IO-03`으로 사람 LED를 연결한다.
4. Dock·handover·RMF·고급 vision은 최소 수직 흐름 검증 후 연결한다.
