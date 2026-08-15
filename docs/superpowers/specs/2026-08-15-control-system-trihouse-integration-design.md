# Control System 기반 Trihouse 통합 설계

## 1. 목적과 기준

최신 `control_system`(A)을 최종 제품의 기준으로 삼고,
`control_system_test`(B)는 Trihouse 통합 요구를 시험한 참고 구현으로만 사용한다.
B를 A에 통째로 병합하지 않고, 최신 A에서 새 통합 브랜치를 만든 뒤 필요한 계약과
기능을 다시 구현한다. 최종 결과는 A 저장소에 PR로 반영하며 B는 병합 후 동결한다.

최종 제품은 다음을 한 운영 흐름으로 연결한다.

- Control System 기반 Flutter Web UI
- `control_tower` Task Manager와 정책 모듈
- `fms_gateway` REST/WebSocket 및 DB transaction 경계
- Open-RMF traffic schedule과 Fleet Adapter
- Nav2 기반 Pinky 주행
- Gazebo 기반 Pinky/OMX 시뮬레이션
- Vision/AI 서버의 관측 결과와 비상 판단
- `db/schema_mysql.sql`을 기준으로 초기화되는 MySQL

신규 배포만 지원한다. 기존 Control System 프로젝트, 수동 Lane, 과거 map migration,
Floor–SLAM 자동 정합은 지원 범위에서 제외한다.

## 2. 권한과 데이터 흐름

```text
Control System Flutter Web
  ├─ 주문 입력, 관제, 지도·시설·규칙 작성
  └─ 관리자 판단과 배포 요청
             │ REST / WebSocket
             ▼
FMS Gateway
  ├─ 공개 API, 인증·멱등성, DB transaction
  └─ 단일 운영 projection
             │
             ▼
Control Tower
  ├─ FEFO, 작업 sequence, 배차·재할당
  ├─ 병목·작업공간 예약, 비상 workflow
  └─ RMF/OMX/Vision adapter orchestration
             │
             ├─ Open-RMF schedule / Fleet Adapter
             ├─ Nav2 / Pinky
             ├─ OMX
             └─ Vision / Safety
```

- UI는 MySQL, ROS 2, RMF, Gazebo에 직접 접근하지 않는다.
- UI는 `/internal/v1/*`를 호출하지 않는다.
- FMS Gateway만 `trihouse_fms`에 transaction을 수행한다.
- Control Tower만 Job 상태와 다음 Step을 확정한다.
- Open-RMF는 다중 로봇 예상 trajectory와 traffic schedule을 맡는다.
- Nav2는 SLAM occupancy map에서 실제 global/local path를 계산한다.
- Pinky의 로컬 Safety Supervisor는 네트워크보다 먼저 정지할 권한을 갖는다.
- 영상·AI 모델의 대용량 바이너리는 파일/NAS/모델 서버에 두고 URI, 해시,
  장비·Job·incident 연결 정보는 `artifacts`에 저장한다.

## 3. A와 B의 채택 기준

### A에서 유지

- 최신 UI shell과 theme, RMF·OMX·로봇 모델 연동
- Gazebo/Open-RMF/Nav2 실행 산출물과 최신 upstream 테스트
- 로봇·워크셀 등록 화면 중 API 기반으로 바꿀 수 있는 presentation 계층
- RMF runtime 진단과 시각화에 필요한 모델

### B를 참고해 A에 재구현

- FMS Gateway 기반 저장·조회 경계
- SLAM YAML/PGM 업로드와 map 좌표 처리
- 운영 Waypoint 역할, 시설, Safety/Bottleneck/금지·감속 Zone
- map validation, 불변 map revision, runtime profile gate
- Gateway 기반 Job/Event/감사 이력
- canonical 영어 DB 값과 한국어 UI label의 분리

### 채택하지 않음

- 수동 Lane 작성과 사용자가 만드는 Transit Waypoint
- 첫 프로젝트 이름 입력이나 편집 중의 DB draft 저장
- UI가 내부 Job/Step을 직접 만들거나 담당 로봇을 지정하는 흐름
- 브라우저에서 `mysql`, `ros2`, `gz`, shell script를 실행하는 흐름
- B의 별도 DB schema와 메모리 기반 운영 projection
- PGM/PNG를 `map_project_files.content`의 base64로 저장하는 방식
- B의 대형 `main.dart` 변경을 통째로 병합하는 방식

## 4. 지도 작성과 배포

### 4.1 좌표 원장

SLAM `map` frame의 미터 좌표를 유일한 실행 좌표로 사용한다. 사용자는 Nav2
`map.yaml`과 PGM/PNG occupancy image를 필수로 올린다.

Floor plan은 선택적인 실측 보조 자료다. SLAM과 자동 정합하지 않는다. 사용자는
Floor plan에서 실제 길이를 아는 벽을 선으로 긋고 `6.25m`처럼 값을 입력해 시설의
실제 크기를 확인한 다음, 해당 시설을 SLAM map 위의 실측 위치에 직접 배치한다.
현장에서 Pinky를 수동 주행시켜 얻은 `map` pose를 시설이나 Waypoint 위치로 가져올
수도 있다.

Waypoint는 실행용 `map_x`, `map_y`, `map_yaw`만 갖는다. Floor 좌표와 SLAM 좌표의
자동 변환, similarity/affine transform, 동시 좌표 표시는 구현하지 않는다.

### 4.2 편집 대상

- Point: 작업 Waypoint, 충전소, 주차 위치, 대기 위치, ArUco, 카메라
- Polygon: 선반, 포장대, OMX 작업 영역, Safety Zone, Bottleneck Zone,
  금지 구역, 감속 구역, 시설 외곽
- Measurement line: Floor plan의 실제 길이 측정과 축척 확인

모든 영역 데이터는 GeoJSON Polygon 하나로 통일한다. 사각형 입력은 Polygon을
빠르게 만드는 UI 편의 모드일 뿐 별도 DB 타입이 아니다.

수동 Lane 편집, Transit Waypoint 작성, graph 연결 검사는 UI에서 제거한다.

### 4.3 Nav2와 Open-RMF

작업 시작 시 Control Tower가 DB의 목적지 Waypoint `(x, y, yaw)`를 Nav2에 전달한다.
Nav2 `ComputePathToPose`가 occupancy map과 costmap으로 실제 path를 계산한다.

Fleet Adapter는 계산된 path를 단순화해 Open-RMF schedule에 예상 trajectory로
제공한다. 재계획이 일어나면 남은 trajectory를 갱신한다. 사용자는 graph를 보거나
편집하지 않는다. Open-RMF 호환을 위해 내부 graph가 필요한 구현에서는 Nav2 path로
자동 생성하며 배포 산출물로만 취급한다.

Control Tower는 Safety/Bottleneck Zone과 path의 교차를 검사해 mutex와 진입 순서를
적용한다. 예약이 없으면 등록된 대기 Waypoint에서 기다린다.

### 4.4 편집과 영속성

신규 프로젝트 이름 입력, 업로드, 편집, 미리보기, 검증 중에는 DB 행을 만들지 않는다.
작업 사본은 브라우저 세션에만 존재한다. 편집을 폐기하거나 화면을 나가면 사라지며,
같은 이름으로 새로 시작할 수 있다.

배포는 DB와 runtime filesystem을 하나의 deployment coordinator가 묶어 수행한다.
두 저장소를 물리적인 단일 transaction으로 만들 수 없으므로, 실패 시 원상 복구하는
보상 transaction까지 포함해 사용자 관점에서 원자성을 보장한다.

1. 서버 staging에서 SLAM source, 시설, Waypoint, Zone, Nav2/RMF 산출물을 검증한다.
2. staging runtime을 기동 전 검사하고 최종 directory에 원자적으로 이동할 준비를 한다.
3. 모든 검증이 성공하면 `map_projects`, 세부 map tables, `map_revisions`, source,
   artifact metadata를 한 DB transaction에 기록한다.
4. runtime directory와 active pointer를 원자적으로 활성화한다.
5. 3번 이후 하나라도 실패하면 새 runtime을 제거하고 보상 transaction으로 이번
   배포가 만든 DB 행을 모두 삭제한다.

따라서 첫 배포가 실패하면 canonical map/project 기록과 active runtime을 모두 남기지
않는다. 같은 프로젝트 이름으로 즉시 다시 배포할 수 있다.

## 5. 최소 DB 변경

운영 schema의 유일한 기준은 `db/schema_mysql.sql`이다. A/B 내부 schema는 사용하지
않는다.

기존 테이블만으로 여러 지도 source를 정상적으로 보존할 수 없다.

- `map_projects.drawing_bytes`는 한 source만 표현한다.
- `map_project_files.content`는 text이므로 binary image 저장에 부적합하다.
- `artifacts`는 외부 `storage_uri`와 무결성 metadata용이며 source bytes를 저장하지
  않는다.
- `map_revisions`는 manifest와 생성 artifact hash만 보존한다.

최소 변경은 기존 테이블에 source별 column을 계속 추가하는 것이 아니라, 다음 한 개
child table을 추가하는 것이다.

```text
map_revision_sources
  map_revision       FK → map_revisions
  source_type        slam_yaml | slam_image | floor_plan | facility_import
  file_name
  mime_type
  content_bytes      LONGBLOB
  sha256
  byte_size
  metadata           JSON (image size, SLAM resolution/origin, import format)
  PRIMARY KEY (map_revision, source_type)
```

배포 전에는 `map_revision`이 없으므로 이 테이블에도 기록하지 않는다. 초기 범위에서
source type별 파일은 하나만 허용한다.

추가로 새 테이블을 만들지 않고 다음 기존 구조를 재사용한다.

- Waypoint pose/yaw: `map_project_waypoints.map_x/map_y/map_yaw`
- 시설 master와 업무 연결: `locations`
- 시설 footprint와 Zone: `map_features.geometry/properties`
- Nav2/costmap/robot 설정: `map_project_fleets.settings` JSON과
  `map_revisions.manifest`의 profile hash
- 생성 YAML/launch/script: `map_project_files`
- 외부 영상·모델·dataset: `artifacts`

`map_features.feature_type` check에는 `facility_footprint`, `safety_zone`,
`speed_zone`을 추가한다. `bottleneck`, `no_go_zone`, `fiducial`은 기존 값을 사용한다.
`map_project_lanes`는 신규 배포 경로에서 읽거나 쓰지 않는다. 호환성 요구가 없으므로
최종 schema 정리 단계에서 삭제할 수 있지만, 첫 PR에서는 수동 Lane 제거와 무관한
DDL 변경을 줄이기 위해 deprecated 상태로 둔다.

## 6. 주문과 자동 Task sequence

사용자는 상품 코드/이름과 수량, 우선순위만 입력한다. 위치, Waypoint, yaw, 로봇,
OMX, Step은 고르지 않는다.

Control Tower는 다음 순서로 작업을 만든다.

1. `inventory_lots`에서 상품과 가용 수량을 조회한다.
2. 유통기한이 빠른 lot부터 FEFO 예약한다.
3. lot의 slot에서 parent warehouse와 온도 구역을 찾는다.
4. warehouse에 연결된 Loading Dock Waypoint와 yaw를 조회한다.
5. 물품을 `ambient → chilled → frozen` 순서로 그룹화하고 빈 구역은 생략한다.
6. 같은 온도 구역의 모든 품목을 하나의 Loading Dock 방문 묶음으로 합친다. 구역 안의
   선반별 이동은 OMX 작업이며 Pinky의 주행 경로를 추가하지 않는다.
7. Pinky와 해당 시설에 사용 가능한 OMX를 배정한다.
8. Nav2/RMF ETA에서 준비 여유시간을 뺀 `prepare_at`에 OMX 선행 파지를 시작한다.
9. 구역별 prepare/pick → navigate → verify/load Step을 만든다. Pinky는 OMX 준비 전에도
   Dock에 진입해 대기할 수 있지만, 같은 Job/Step assignment revision의 `PINKY_READY`와
   `OMX_READY`가 모두 확인되기 전에는 바구니 적재를 시작하지 않는다.
10. 마지막에 Packing Station Dock으로 이동해 unload/handover하고 작업자 완료를 기다린다.
11. 작업자가 Control UI의 `작업 완료` 버튼을 눌러 성공한 transaction에서만 최종
    재고를 반영한다.
12. 배터리 정책에 따라 Charging Station 또는 Parking/Waiting Point로 복귀한다.

작업자 완료 API는 `Idempotency-Key`가 필수다. 완료 전에는 inventory physical quantity를
바꾸지 않는다. 완료가 없으면 로봇과 포장대 reservation을 유지하고 관리자의 취소·복구
workflow만 허용한다.

UI의 우선순위 label `긴급`은 DB canonical 값 `critical`로 저장한다. `critical` Job은
아직 시작하지 않은 일반 Job보다 먼저 배차하되, 운반 중인 Job을 임의 중단하지 않고
안전한 Step 경계에서만 재정렬한다.

부분 출고는 주문의 `allow_partial_fulfillment=true`일 때만 허용한다. 허용된 주문은
가용 수량을 예약해 Job을 만들고 부족 수량은 `job_items.metadata`에 outstanding으로
남긴다. 모든 품목의 가용 수량이 0이면 부분 출고 허용 여부와 관계없이 거절한다.

각 논리 Step과 재시도는 `job_steps`와 append-only `job_step_attempts`에 저장한다.
시도에는 성공 기준, 관측값, 시간·거리·ETA 오차 같은 metric, 실패 domain/reason,
정책·VLM/RL model lineage, 이미지·영상·ROS bag artifact 참조를 포함한다. 성공 판정은
구조화된 기준이 모두 통과한 경우에만 `succeeded`가 되며, 누락된 관측은 성공으로
간주하지 않는다.

## 7. Seed 기반 주문 예시

현재 `db/seed_dev.sql`은 다음 상품을 포함한다.

- 상온: Orange, Strawberry, Mandarin
- 냉장: Coffee, Sandwich, Yogurt, Milk
- 냉동: Pork belly, Dumpling, Ice bar, Ice cone
- 이동 로봇: `PK_01`, `PK_02`
- 로봇팔: `OMX_01`, `OMX_02`

지도 첫 배포는 기존 parent 시설에 다음 운영 위치를 생성해야 한다.

```text
WH-AMB-01-DOCK-01  / ambient_loading_dock_01
WH-CHL-01-DOCK-01  / chilled_loading_dock_01
WH-FRZ-01-DOCK-01  / frozen_loading_dock_01
PACKING-01-DOCK-01 / packing_loading_dock_01
PROJECT1-WAIT-01   / project1_waiting_01
```

각 위치에는 SLAM `map` pose와 yaw가 있어야 한다. 현재 seed의 slot과 parent warehouse만
으로는 자동 이동 목적지를 만들 수 없으므로 이 map 배포가 주문 E2E의 선행조건이다.

### 주문 A: 전 온도 구역

```json
{
  "external_reference": "DEMO-ORDER-ALL-ZONES-001",
  "priority": "normal",
  "requested_by": "W-OP-01",
  "items": [
    {"product_code": "SKU-MANDARIN", "quantity": 1},
    {"product_code": "SKU-YOGURT", "quantity": 1},
    {"product_code": "SKU-DUMPLING", "quantity": 1}
  ]
}
```

예상 lot은 각각 `LOT-AMB-MANDARIN-001`, `LOT-CHL-YOGURT-001`,
`LOT-FRZ-DUMPLING-001`이다. 예상 방문 순서는 상온 Dock → 냉장 Dock → 냉동 Dock →
포장대 Dock → 작업자 완료 → 대기/충전이다.

논리 Step 예시는 다음과 같다. 실제 `step_no`는 10 단위로 생성한다.

```text
navigate ambient dock
verify/pick/load Mandarin
navigate chilled dock
verify/pick/load Yogurt
navigate frozen dock
verify/pick/load Dumpling
navigate packing dock
unload/handover
wait worker completion
return_home
```

### 주문 B: 빈 온도 구역 생략

```json
{
  "external_reference": "DEMO-ORDER-CHL-FRZ-001",
  "priority": "high",
  "requested_by": "W-OP-01",
  "items": [
    {"product_code": "SKU-MILK", "quantity": 1},
    {"product_code": "SKU-ICECONE", "quantity": 1}
  ]
}
```

상온 구역을 생략하고 냉장 Dock → 냉동 Dock → 포장대 Dock 순서로 이동한다.

### 주문 C: 재고 부족 거절

```json
{
  "external_reference": "DEMO-ORDER-INSUFFICIENT-001",
  "priority": "normal",
  "requested_by": "W-OP-01",
  "items": [
    {"product_code": "SKU-ORANGE", "quantity": 2}
  ]
}
```

현재 Orange 가용 수량은 1이므로 Job/Step과 reservation을 만들지 않고 전체 주문을
거절한다. 부분 출고는 별도 명시 옵션이 없는 한 허용하지 않는다.

### 주문 D: 긴급 우선순위

```json
{
  "external_reference": "DEMO-ORDER-CRITICAL-001",
  "priority": "critical",
  "allow_partial_fulfillment": false,
  "requested_by": "W-OP-01",
  "items": [
    {"product_code": "SKU-STRAWBERRY", "quantity": 1},
    {"product_code": "SKU-PORKBELLY", "quantity": 1}
  ]
}
```

UI에는 `긴급`으로 표시한다. 대기 중인 normal/high Job보다 먼저 PK/OMX를 배정하고
상온 Dock → 냉동 Dock → 포장대 Dock 순으로 수행한다.

### 주문 E: 부분 출고 허용

```json
{
  "external_reference": "DEMO-ORDER-PARTIAL-001",
  "priority": "normal",
  "allow_partial_fulfillment": true,
  "requested_by": "W-OP-01",
  "items": [
    {"product_code": "SKU-SANDWICH", "quantity": 3},
    {"product_code": "SKU-ICEBAR", "quantity": 1}
  ]
}
```

현재 Sandwich 수량 2와 Ice bar 수량 1을 예약해 냉장 Dock → 냉동 Dock → 포장대
Dock을 수행하고 Sandwich 1은 outstanding으로 기록한다. UI는 출고 가능 3/요청 4를
작업 시작 전에 명확히 표시한다.

### 주문 F: 같은 구역 다품목과 단일 Dock

```json
{
  "external_reference": "DEMO-ORDER-AMBIENT-BUNDLE-001",
  "priority": "high",
  "allow_partial_fulfillment": false,
  "requested_by": "W-OP-01",
  "items": [
    {"product_code": "SKU-ORANGE", "quantity": 1},
    {"product_code": "SKU-MANDARIN", "quantity": 1}
  ]
}
```

두 품목의 선반 위치가 달라도 Pinky는 상온 Loading Dock을 한 번만 방문한다. OMX는
Pinky ETA 전에 두 품목을 순서대로 준비한다. Pinky가 먼저 도착해도 양측 준비 신호가
모인 뒤 하나의 load 묶음으로 인계한다. 여섯 주문 예시는 각각 fresh seed에서 독립
실행한다.

## 8. 비상상황

Vision의 작업자 쓰러짐 후보가 들어오면 affected Zone의 로봇을 즉시 hold하고 해당
카메라 live stream을 UI에 자동 표시한다. 관리자는 두 동작만 선택한다.

- `비상경보 발령`: incident 확정, 영향 Zone/전체 로봇 정지, Job 보류, 대응 절차 시작
- `작업 계속 진행`: false positive와 관리자·사유 기록, hold 해제, Nav2 재계획 후
  기존 Job sequence 재개

팝업을 닫는 것만으로는 로봇을 재개하지 않는다. 모든 판단과 명령은
`operation_events`와 incident에 감사 가능하게 기록한다.

## 9. Nav2·costmap 설정 UI

Raw YAML 대신 schema 기반 form을 제공한다.

- 로봇 폭·길이, footprint polygon/padding, 회전 반경
- costmap resolution, inflation radius, cost scaling
- obstacle/raytrace range, update/publish frequency
- 최대 선속도·각속도, 가속·감속, goal tolerance
- planner/controller, scan/odom topic
- 안전 정지·감속 거리와 통신 timeout

필드마다 단위, 허용 범위, 권장 기본값, 기존 값과 diff를 표시한다. Simulation과 Real
profile은 분리하고 배포 시 profile hash를 map revision manifest에 고정한다.
기본값은 `pinky_pro/pinky_navigation/params/nav2_params.yaml`의 controller, planner,
AMCL, global/local costmap 설정과 `pinky_pro/pinky_bringup/config/pinky_params.yaml`의
wheel radius/separation에서 읽는다. UI가 원본 파일을 직접 덮어쓰지 않고 Gateway가
검증한 revision별 profile을 생성해 Nav2 launch에 전달한다.

## 10. 실시간 관제 화면

웹 map 위에 다음 레이어를 선택적으로 표시한다.

- SLAM occupancy map과 시설/Zone
- 로봇 pose, yaw, footprint, 배터리, 현재 Job
- Nav2 global/local path와 실제 주행 궤적
- global/local costmap
- 목적지 Waypoint와 yaw
- 병목 reservation과 대기 상태
- RMF 예상 trajectory, conflict, delay
- camera/incident marker

로봇 pose와 path는 WebSocket으로 전달한다. Camera는 MediaMTX WebRTC/HLS로 재생하고,
UI 재생 여부와 무관하게 녹화한다.

카메라 inventory는 고정 카메라 2대, OMX 손목 카메라 2대, Pinky 카메라 2대의 총
6 stream이다. 운영 UI는 6개 상태와 recording 상태를 모두 표시하되, 기본 재생은
선택한 한 stream만 수행하고 incident 시 관련 stream만 자동 재생한다.

## 11. 영상 저장과 장비 용량

### 현재 접속 장비

실측된 현재 장비는 LG `15UD50T-GX5JK`다.

- CPU: Intel Core i5-1334U, 10 core/12 thread
- RAM: 16 GiB, 점검 시 available 약 5.2 GiB, swap 4 GiB 대부분 사용
- GPU: Intel Iris Xe, NVIDIA GPU/driver 없음
- SSD: 500 GB NVMe, 사용 가능 약 350 GB

이 장비는 Flutter Web, 개발 DB, Gateway, H.264 copy recording에는 사용할 수 있다.
NVIDIA 추론, 여러 로봇 Gazebo GUI, VLM과 전체 stack의 동시 실행 장비로는 사용하지
않는다. 메모리 여유를 위해 개발 시 Gazebo는 headless, AI는 원격 5080을 사용한다.
6개 실제 camera 동시 입력은 이 장비의 확정 성능 기준으로 간주하지 않는다. 개발
profile은 synthetic/recorded fixture 6개를 등록하되 최대 2개만 720p 5 FPS로 decode하고,
나머지는 연결 상태와 pre-recorded event만 검증한다.

H.264 고정 bitrate 기준 저장량은 다음과 같다.

```text
저장량(GB/day) = bitrate(Mbps) × 10.8 × camera_count
```

- 1 camera, 2 Mbps: 약 21.6 GB/day
- 4 cameras, 2 Mbps: 약 86.4 GB/day
- 4 cameras, 4 Mbps: 약 172.8 GB/day

현재 350 GB 전체를 쓰지 않고 OS/개발용 100 GB를 남기면 녹화에 약 250 GB를 쓸 수
있다. 4 camera × 2 Mbps에서는 약 2.9일이다. 7일 보존에는 약 605 GB가 필요하므로
시연에는 1 TB 이상 USB SSD를 권장한다.

MediaMTX는 H.264를 재인코딩하지 않고 fMP4 1분 segment로 기록한다. 기본 보존은 7일,
디스크 high-water mark는 85%로 두며 오래된 완료 segment부터 삭제한다. Segment
metadata와 incident/job 연결은 DB `artifacts`에 기록한다.

### OMEN RTX 5080

OMEN이라는 이름만으로 laptop/desktop과 RAM/SSD를 확정할 수 없다. HP의 RTX 5080
구성은 OMEN MAX 16 laptop과 OMEN 35L desktop 모두 존재하며 GPU VRAM은 16 GB다.
실제 배포 전 해당 PC에서 아래 정보를 수집한다.

```bash
nvidia-smi --query-gpu=name,memory.total,driver_version,power.limit --format=csv
free -h
lsblk -o NAME,MODEL,TRAN,SIZE,FSTYPE,MOUNTPOINTS
df -h
```

OMEN 5080과 4060 관제 PC의 동시 처리량 및 저장 일수는 **미정**이다. 아래 명령의 실제
결과와 6 stream soak test가 없으면 production profile을 승인하거나 보존 일수를
표시하지 않는다.

확정 전 보수적 검증 목표는 다음과 같다.

- H.264 1080p 입력 최대 4개 수신
- YOLO small/medium 계열은 camera별 5 FPS 목표로 round-robin/batch 추론
- QR/ArUco는 4060 관제 PC에서 OpenCV로 처리
- VLM은 모든 frame이 아니라 event/실패 snapshot에만 실행
- 모델과 녹화를 같은 SSD에 두지 않음
- 추론 FPS는 실제 model, resolution, precision별 benchmark로 확정

고정 2 + OMX 손목 2 + Pinky 2 camera에 대해 stream별 실제 codec, resolution,
bitrate, source FPS를 기록한 다음 QR/ArUco latency·CPU/GPU·RAM·drop rate와 MediaMTX
저장량을 함께 30분 이상 측정한다. `nvidia-smi`, `free -h`, `lsblk`, `df -h` 원문과
benchmark JSON을 배포 승인 artifact로 보존한다.

장기 녹화는 모델 서버와 장애 범위를 분리해 4060 측 전용 SSD 또는 별도 NAS/NFS/SMB를
사용한다. 실제 6 stream bitrate와 확보 가능한 전용 저장 공간이 측정되기 전까지
UI의 예상 보존 일수는 숫자 대신 `UNMEASURED`로 표시한다.

## 12. 한 명령 통합 기동

```bash
./scripts/control_stack up --mode simulation --project warehouse_01
./scripts/control_stack status
./scripts/control_stack logs
./scripts/control_stack down
./scripts/control_stack doctor
```

`up`은 다음 순서를 보장한다.

1. MySQL
2. FMS Gateway
3. Control Tower Task Manager와 workers
4. MediaMTX와 recording catalog
5. Open-RMF schedule, dispatcher, API, visualization
6. Fleet Adapter
7. Gazebo
8. Nav2/map server와 Pinky/OMX simulation adapters
9. Control System Flutter Web

최신 `control_system` source는 root의 `control_ui/`로 복사하되 nested `.git`, build,
cache 산출물은 제외한다. 이후 제품 source의 기준 경로와 표시 명칭은 `control_ui`다.
첫 통합에서는 내부 Flutter package 이름을 일괄 변경하지 않아 upstream 비교 가능성을
유지한다.

기본은 Gazebo headless다. `--gazebo-gui`, `--rviz`를 명시한 경우에만 진단 창을
띄운다. `compose.ai_5080.yaml`과 모델 weight는 이 명령에 포함하지 않는다. Control
stack은 원격 AI health와 model version만 확인하며 simulation mode에서는 fixture
Vision event를 사용할 수 있다.

## 13. 검증 기준

- 사용자 UI에 Lane 작성 기능이 없다.
- 상품/수량만으로 상온 → 냉장 → 냉동 → 포장대 sequence가 생성된다.
- 빈 온도 구역은 생략되고 같은 구역 다품목은 단일 Loading Dock 방문으로 묶인다.
- Waypoint와 yaw는 DB `locations`에서만 결정된다.
- 작업자 완료 전에는 최종 재고가 변하지 않는다.
- 편집 폐기와 첫 배포 실패 후 같은 프로젝트 이름을 다시 사용할 수 있다.
- 배포 성공 전 map/project canonical DB 행이 생기지 않는다.
- SLAM source, Floor plan, 시설 import는 배포 revision과 함께 보존된다.
- UI에 DB/ROS/process 직접 접근 코드가 없다.
- Nav2 path, robot pose, costmap, reservation/conflict가 웹 지도에 표시된다.
- 비상 후보에서 로봇 hold와 camera 표시가 먼저 일어나며, 두 관리자 결정 모두
  감사 이력에 남는다.
- 한 명령으로 MySQL부터 Open-RMF, Gazebo, Nav2, UI까지 올라오고 `down`으로 정리된다.
- 최신 A의 OMX/RMF 회귀 테스트와 Trihouse Job/DB 통합 테스트가 모두 통과한다.
- OMX는 Pinky ETA 기반 `prepare_at`에 시작하고 `PINKY_READY`와 `OMX_READY`가 같은
  assignment revision에 모이기 전에는 적재 동작을 허용하지 않는다.
- UI의 `작업 완료` 버튼은 멱등 완료 API 성공 후에만 완료 상태를 표시한다.
- 긴급 주문과 opt-in 부분 출고가 canonical DB 값으로 저장되고 감사 이력이 남는다.
- 모든 Step attempt의 성공 기준·관측·metric·evidence·model lineage가 DB에 남는다.
- 6 camera production profile은 4060/5080 실제 측정 artifact 없이는 활성화되지 않는다.

## 14. 일정과 테스트 범위

### 2026-08-16까지: 시뮬레이션 검증

- 필수: Pinky 2대, Open-RMF, Nav2, Gazebo headless, Control Tower, Gateway, MySQL,
  Control UI를 한 명령으로 기동한다.
- 필수: 주문 A~F를 fresh seed에서 실행해 온도 구역 순서, 단일 Dock 묶음, 긴급 배차,
  부분 출고, 재고 부족, 작업자 완료와 복귀를 검증한다.
- 필수: 두 Pinky가 동시에 서로 다른 Job을 수행하고 Nav2가 계산한 실제 path와 RMF
  예상 trajectory가 UI에 표시되는 것을 확인한다.
- 필수: 6 camera fixture가 등록되고 선택 영상·incident 영상·recording metadata가 UI와
  DB에 연결되는 것을 확인한다.
- 가능하면: OMX 2대의 ETA 선행 파지와 load handover를 Gazebo 또는 protocol simulator로
  검증한다. OMX simulation이 불완전해도 Pinky 2대 필수 gate를 낮추지 않는다.

### 2026-08-17: 통합 검증

- A에서 복사한 `control_ui`, Control Tower, Gateway, canonical MySQL, Open-RMF,
  Nav2/Gazebo, MediaMTX를 통합한다.
- 4060 QR/ArUco와 원격 5080 VLM endpoint는 health/model-version 계약으로 연결한다.
- 실제 장비 처리량과 저장 일수는 4060/5080의 필수 명령 결과와 6 camera soak test가
  준비된 경우에만 확정한다. 준비되지 않으면 `UNMEASURED` 배포 차단 상태를 유지한다.
