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
- Gazebo 기반 Pinky 2대와 계약 기반 OMX 2대 protocol simulation
- Vision/AI 서버의 관측 결과와 비상 판단
- `db/schema_mysql.sql`을 기준으로 초기화되는 MySQL

신규 배포만 지원한다. 기존 Control System 프로젝트, 수동 Lane, 과거 map migration,
Floor–SLAM 자동 정합은 지원 범위에서 제외한다. 2026-08-16 P0는 시뮬레이션과
장비 독립 계약을 완성하고, 2026-08-17 통합 gate 이후 P1에서 실제 Pinky, OMX-AI,
카메라, 4060/5080 처리량을 검증한다.

## 2. 권한과 데이터 흐름

```text
`control_ui` Flutter Web (Control System 기반)
  ├─ 상품·수량·우선순위·부분 출고 여부만 입력
  ├─ 관제, 지도·시설·규칙 작성
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
- Control Tower만 Job/Step, Pinky, OMX-AI, Packing Dock의 최종 배정을
  확정한다. Open-RMF는 배정된 Pinky를 임의로 재배정하지 않는다.
- Open-RMF는 배정된 Pinky 2대의 실제 Nav2 path를 기준으로 traffic
  schedule, 충돌 협상, 대기, 우회를 맡는다.
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

`control_system` 소스는 nested `.git`과 build/cache 산출물만 제외하고
`control_ui/`로 전체 복사한다. 다만 복사 직후 A의 `db/`와 Flutter 내부의
MySQL·schema migration·`ros2`·shell·filesystem 직접 접근을 제거하고 Gateway
REST/WebSocket adapter로 교체한다. 이 경계 전환은 복사와 하나의 P0
작업으로 취급한다.

### B를 참고해 A에 재구현

- FMS Gateway 기반 저장·조회 경계
- SLAM YAML/PGM 업로드와 map 좌표 처리
- 운영 Waypoint 역할, 시설, Safety/Bottleneck/금지·감속 Zone
- map validation, 불변 map revision, runtime profile gate
- Gateway 기반 Job/Event/감사 이력
- canonical 영어 DB 값과 한국어 UI label의 분리

### 채택하지 않음

- 수동 Lane 작성과 사용자가 만드는 Transit Waypoint
- 사용자가 저장하지 않은 변경을 암묵적으로 DB에 기록하는 autosave
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

P0 시뮬레이션의 위치 데이터 단일 기준은 다음 파일이다.

```text
control_system_test/rmf_control_ui/data/import/
  trihouse_test_01_physical_features.jsonl
```

- canonical project/map name은 `trihouse_test_01`이다.
- 위 파일에 없는 pose를 seed, fixture, test에서 임의로 만들지 않는다.
- JSONL의 `source_map_name`, `target_map_name`은 출처 metadata일 뿐 import
  허용 조건이 아니다. 사용자가 열어 둔 임의의 project에 같은 파일을
  다시 업로드할 수 있다.
- 파일명·source map명·project명이 다르다는 이유로 차단하거나 별도 안전 확인
  팝업을 띄우지 않는다. 같은 SLAM인지 판단하는 책임은 업로드 사용자에게 있다.
- Dock 정차 pose와 ArUco recognition pose는 의미가 다른 별도 pose다.
  서로 병합하거나 덮어쓰지 않는다.
- 두 Bottleneck은 지름 `0.2m`, 반지름 `0.1m`다. 실행 기준은
  `radius_m=0.1`이며 기존 `source_radius_m=0.2`는 의미를
  `source_diameter_m=0.2`로 정정한다.

### 4.2 편집 대상

- Point: 작업 Waypoint, 충전소, ArUco, 카메라
- Polygon: 선반, 포장대, OMX 작업 영역, Safety Zone, Bottleneck Zone,
  금지 구역, 감속 구역, 시설 외곽
- Measurement line: Floor plan의 실제 길이 측정과 축척 확인

모든 영역 데이터는 GeoJSON Polygon 하나로 통일한다. 사각형 입력은 Polygon을
빠르게 만드는 UI 편의 모드일 뿐 별도 DB 타입이 아니다.

수동 Lane 편집, Transit Waypoint 작성, graph 연결 검사는 UI에서 제거한다.

P0에서는 SLAM map 로드, 실측 JSONL import, Waypoint/yaw/Bottleneck/marker
표시, 저장·삭제·배포만 구현한다. Floor 측정선, Polygon 직접 편집,
범용 시설 CSV/JSON import, Nav2/costmap/robot parameter 편집 form은 P1이다.
현재 JSONL의 `safety_zone_01`은 P0에서 Point Waypoint로 표시하며
Safety Polygon으로 승격하지 않는다.

### 4.3 Nav2와 Open-RMF

실제 실행 path와 RMF schedule이 다른 공간을 점유한다고 가정하지 않도록
다음 순서를 강제한다.

1. Control Tower가 목적지 Waypoint와 최종 Pinky를 확정한다.
2. Nav2 `ComputePathToPose`가 occupancy map과 costmap으로 실제 후보 path를
   계산한다. 이 단계에서는 로봇을 움직이지 않는다.
3. Fleet Adapter가 해당 path를 시간 trajectory로 변환해 RMF schedule에
   등록한다.
4. RMF가 다른 Pinky와의 충돌, 대기, 우회를 협상한다.
5. 승인된 path를 Nav2 `FollowPath`로 실행한다.
6. 장애물 등으로 새 path가 필요하면 우선 hold하고 2~5를 반복한다.

RMF 라이브러리 초기화에 내부 graph가 필요해도 로봇·충전소·Waypoint
등록용 배포 산출물로만 사용한다. UI에 노출하지 않고, 실제 충돌
판정의 원장으로 간주하지 않는다. Nav2 path와 RMF에 등록된 trajectory의
차이가 허용 범위를 넘으면 이동을 시작하지 않는다.

Control Tower가 Pinky·OMX-AI·Packing Dock을 함께 배정하고, 특정
`robot_name`을 지정한 RMF task를 보낸다. RMF Dispatcher는 배정된 Pinky를
다른 Pinky로 임의 재배정하지 않는다. 재배정은 Control Tower가 안전한
Step 경계에서 새 `assignment_revision`으로만 수행한다.

#### Bottleneck mutex

- 사용자는 Bottleneck 영역만 지정한다.
- 시스템이 Pinky footprint와 정지거리로 영역 밖 접근 영역을 자동
  계산한다. 수동 대기 Waypoint는 만들지 않는다.
- Pinky가 접근 영역에 도달하면 예약을 확인한다. 예약자가 없으면
  먼저 요청한 Pinky가 원자적으로 획득한다.
- `critical` 등 Job 우선순위는 통행권에 개입하지 않는다.
- 다른 Pinky가 예약 중이면 실제 Bottleneck 경계 밖에서 대기한다.
- 15초 대기하면 우회 path를 계산한다. 우회할 수 없으면 계속 대기한다.
- 예약 Pinky의 footprint 전체가 영역과 안전 여유를 빠져나온 뒤
  해제한다. 영역 내 정지·비상은 예약을 유지한다.

### 4.4 편집과 영속성

편집은 명시적 Draft다.

- `저장`은 Gateway를 통해 `map_projects`와 현재 source, Waypoint, feature를
  MySQL에 저장하고 `draft_revision`을 증가시킨다.
- 저장하지 않은 변경이 있는 상태로 화면을 나가면 저장/폐기 확인을 표시한다.
- `삭제`는 Draft와 배포 revision이 참조하지 않는 source를 삭제한다.
- 동일 이름 Draft가 있으면 새 프로젝트를 만들지 않고 기존 Draft를 연다.
- 동일 이름 Active 프로젝트가 있으면 기존 프로젝트를 열어 새 Draft
  revision으로 편집하도록 안내한다.
- Active revision 자체는 수정하지 않으며 새 배포가 성공할 때까지 계속 실행한다.

배포 coordinator는 staging directory에 임시 manifest를 두고 source, Waypoint,
Nav2/RMF 산출물과 runtime preflight를 검증한다. 일반 검증 실패는 UI
팝업과 서버 로그로 알리고 영구 실패 이력을 DB에 만들지 않는다. 강제 종료
후에는 시작 시 reconciler가 staging manifest를 읽어 미완료 runtime을 정리한다.

모든 검증이 성공하면 새 `map_revisions`와 운영 projection을 DB transaction으로
기록하고 runtime directory와 active pointer를 활성화한다. 활성화 전에 실패하면
새 Active revision은 생기지 않고 기존 Draft와 Active revision은 그대로 남는다.

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
map_project_sources
  source_uuid        immutable UUID
  project_id         FK → map_projects
  source_type        slam_yaml | slam_image | floor_plan | physical_features_import
  file_name
  mime_type
  content_bytes      LONGBLOB
  sha256
  byte_size
  metadata           JSON (image size, SLAM resolution/origin, import format)
  created_at
  PRIMARY KEY (source_uuid)
  INDEX (project_id, source_type, created_at)
```

원본 row는 immutable하다. Draft payload는 source type별로 현재 `source_uuid`를
참조하고, 배포된 `map_revisions.manifest`는 당시 source UUID와 hash를 고정한다.
같은 project에서 파일을 바꾸면 새 source row를 만들고, 저장만 반복할 때는
기존 UUID를 재사용한다.

`map_revisions.manifest`에는 배포 당시의 Waypoint/marker/feature canonical snapshot과
hash도 포함한다. `locations`는 현재 Active 운영 projection이고, 과거 배포 위치를
복원할 때는 manifest와 revision별 `map_features`를 사용한다. 배포 transaction에서
같은 map의 이전 `published` revision을 `retired`로 바꾸고 새 revision만
`published`로 둔다.

같은 JSONL을 다른 project에 업로드하면 project별로 별도 row를 만든다.
프로젝트 이름으로 source 호환성을 검사하지 않고 전역 content deduplication을
구현하지 않는다. Active revision이 참조하는 source는 Draft 삭제로 제거하지
않는다. 초기 범위에서 source type별 현재 선택 파일은 하나만 허용한다.

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

`map_features.map_revision`은 `map_revisions.map_revision`과 같은 길이와 형식으로
맞추고 Gateway가 GeoJSON 형식, 유한 좌표, Polygon 폐합, 최소 점 수를
검증한다.

## 6. 주문과 자동 Task sequence

사용자는 Control UI에서 상품 코드/이름과 수량, 우선순위,
`allow_partial_fulfillment`만 입력한다. 위치, Waypoint, yaw, Pinky, OMX,
Packing Dock, Step은 고르지 않는다.

Control Tower는 다음 순서로 작업을 만든다.

1. `inventory_lots`에서 상품과 가용 수량을 조회한다.
2. 유통기한이 빠른 lot부터 FEFO 예약한다.
3. lot의 slot에서 parent warehouse와 온도 구역을 찾는다.
4. warehouse에 연결된 Loading Dock Waypoint와 yaw를 조회한다.
5. 물품을 `ambient → chilled → frozen` 순서로 그룹화하고 빈 구역은 생략한다.
6. 같은 온도 구역의 모든 품목을 하나의 Loading Dock 방문 묶음으로 합친다. 구역 안의
   선반별 이동은 OMX 작업이며 Pinky의 주행 경로를 추가하지 않는다.
7. Control Tower가 실행 가능한 Pinky와 해당 시설의 OMX를 함께
   배정한다. RMF는 배정을 바꾸지 않고 traffic cost·schedule을 제공한다.
8. Nav2/RMF ETA에서 준비 여유시간을 뺀 `prepare_at`에 OMX 선행 파지를 시작한다.
9. 구역마다 OMX의 prepare/pick branch와 Pinky의 navigate branch를 병렬로 시작하고
   verify/load readiness gate에서 합친다. `job_steps.input`의 dependency와
   `handover_group_id`로 이 관계를 표현하고 각 branch의 attempt를 따로 기록한다.
   Pinky는 OMX 준비 전에도 Dock에 진입해 대기할 수 있지만, 같은 Job/Step assignment
   revision의 `PINKY_READY`와 `OMX_READY`가 모두 확인되기 전에는 바구니 적재를
   시작하지 않는다.
10. Packing Dock 2개 중 예약 상태, RMF 예상 대기, Nav2 이동시간을
    합산한 예상 사용 가능 시간이 가장 빠른 Dock을 배정한다.
    해당 Dock으로 이동해 unload/handover하고 작업자 완료를 기다린다.
11. 작업자가 Control UI의 `작업 완료` 버튼을 눌러 성공한 transaction에서만 최종
    재고를 반영한다.
12. 작업 완료 후 `PK_01`은 `TRIHOUSE-TEST-01-CHG-01`, `PK_02`는
    `TRIHOUSE-TEST-01-CHG-02`로 복귀한다. 실측하지 않은 대기 Waypoint를
    추가하지 않는다.

Pinky ETA는 현재 pose에서 대상 Dock까지 Nav2 candidate path의 예상 이동시간에
RMF가 계산한 대기·충돌 조정 시간을 더한 값이다. 확정 도착 시각이 아니라 실행 중
계속 갱신되는 추정치다. path 재계산이나 RMF delay가 생기면 `prepare_at`도 갱신하되,
이미 안전하게 파지해 `OMX_READY`인 물품을 다시 내려놓고 episode를 반복하지 않는다.

작업자 완료 API는 `Idempotency-Key`가 필수다. 완료 전에는 inventory physical quantity를
바꾸지 않는다. 완료가 없으면 로봇과 포장대 reservation을 유지하고 관리자의 취소·복구
workflow만 허용한다.

UI의 우선순위 label `긴급`은 DB canonical 값 `critical`로 저장한다. `critical` Job은
아직 시작하지 않은 일반 Job보다 먼저 배차하되, 운반 중인 Job을 임의 중단하지 않고
안전한 Step 경계에서만 재정렬한다.

부분 출고는 주문의 `allow_partial_fulfillment=true`일 때만 허용한다. 허용된 주문은
가용 수량을 예약해 Job을 만들고 부족 수량은 `job_items.metadata`에 outstanding으로
남긴다. `false`인데 하나라도 부족하면 주문 전체를 거절하고 Job/Step/reservation을
만들지 않는다. 모든 품목의 가용 수량이 0이면 부분 출고 허용 여부와 관계없이 거절한다.
이 옵션은 주문 접수 시 재고 부족에만 적용한다. OMX 파지 실패의 재시도
허용 여부를 결정하지 않는다.

OMX 파지 실패 후 운영 선택은 `재시도`와 `포장대에서 처리` 두 개다.

- `재시도`: 물체를 재관측하고 QR/ArUco를 다시 확인한 뒤 ACT episode를
  reset한다. 관리자가 선택할 수 있는 재시도는 최대 2회다.
- `포장대에서 처리`: 해당 품목을 주문에서 빼지 않고 OMX 자동화
  대상에서만 제외한다. `MANUAL_FULFILLMENT_REQUIRED`를 만들고 포장대
  작업자가 누락 품목을 보충한 뒤 전체 주문을 완료한다.

낙하가 감지되면 OMX와 해당 작업 영역을 hold하고 Pinky 출발을 금지한다.
작업자가 물체를 회수하고 영역 안전을 확인하기 전에는 `재시도`를
활성화하지 않는다. 2회 실패 후에는 `포장대에서 처리`로 전환한다.

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

아래 값은 `trihouse_test_01_physical_features.jsonl` 13개 record를 그대로 옮긴
것이다. importer와 fixture는 이 표에 없는 좌표를 보완하거나 추정하지 않는다.

| 종류 | 코드/ID | 이름 또는 대상 | x | y | yaw/radius |
|---|---|---|---:|---:|---:|
| Waypoint | `WH-AMB-01-DOCK-01` | `ambient_storage_loading_dock_01` | 1.234 | 0.743 | yaw 2.255 |
| Waypoint | `WH-CHL-01-DOCK-01` | `chilled_storage_loading_dock_01` | 1.260 | 0.193 | yaw -2.258 |
| Waypoint | `WH-FRZ-01-DOCK-01` | `frozen_storage_loading_dock_01` | 1.201 | -0.799 | yaw -1.408 |
| Waypoint | `PACKING-01-DOCK-01` | `packing_station_loading_dock_01` | 0.351 | -0.490 | yaw 0.231 |
| Waypoint | `PACKING-01-DOCK-02` | `packing_station_loading_dock_02` | 0.351 | -1.017 | yaw 0.231 |
| Waypoint | `TRIHOUSE-TEST-01-SAFETY-01` | `safety_zone_01` | 0.613 | -1.249 | yaw 0.000 |
| Waypoint | `TRIHOUSE-TEST-01-CHG-01` | `charging_station_01` | 0.065 | 0.227 | yaw -0.005 |
| Waypoint | `TRIHOUSE-TEST-01-CHG-02` | `charging_station_02` | 0.076 | -0.013 | yaw 0.239 |
| Bottleneck | `TRIHOUSE-TEST-01-BOTTLENECK-01` | `bottleneck_01` | 0.841 | -0.111 | radius 0.100 m |
| Bottleneck | `TRIHOUSE-TEST-01-BOTTLENECK-02` | `bottleneck_02` | 0.367 | -0.762 | radius 0.100 m |
| ArUco | marker 2 | `WH-AMB-01-DOCK-01` recognition | 1.234 | 0.743 | yaw 2.255 |
| ArUco | marker 1 | `WH-CHL-01-DOCK-01` recognition | 1.260 | 0.193 | yaw -2.258 |
| ArUco | marker 0 | `WH-FRZ-01-DOCK-01` recognition | 1.370 | -0.233 | yaw 1.772 |

두 Bottleneck의 원본 지름은 `0.2m`, 실행 반지름은 `0.1m`다. importer에서
상위 `radius_m=0.1`을 실행 값으로 사용하고, 원본 파일의 오해 소지가 있는
`source_radius_m=0.2`와 measurement 내부 `radius_m=0.2`는 좌표를 바꾸지 않고
`source_diameter_m=0.2`로 정규화한다. 냉동 Dock 정차 pose와 marker 0 인식 pose가
다른 것은 오류가 아니라 의도된 두 지점이다.

현재 seed의 slot과 parent warehouse만으로는 자동 이동 목적지를 만들 수 없으므로
위 map 배포가 주문 E2E의 선행조건이다.
P0 simulation 시작 pose도 임의 값을 쓰지 않고 `PK_01`은 충전소 1,
`PK_02`는 충전소 2 pose를 사용한다. 현재 개발 seed의 예시 pose `(2.0, 2.0)`과
`(2.5, 2.0)`은 `trihouse_test_01` 실행 pose로 사용하지 않는다.

### 주문 A: 전 온도 구역

```json
{
  "external_reference": "DEMO-ORDER-ALL-ZONES-001",
  "priority": "normal",
  "allow_partial_fulfillment": false,
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
포장대 Dock → 작업자 완료 → 배정된 Pinky의 충전 위치다.

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
  "allow_partial_fulfillment": false,
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
  "allow_partial_fulfillment": false,
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

## 8. OMX-AI, ArUco, ACT와 적재 판정

### 8.1 장비 경계와 통신

- `OMX_01`, `OMX_02`는 각각 별도의 일반 PC에 USB로 연결하고 해당 PC의
  ROS 2와 ROBOTIS OMX-AI driver를 로컬로 유지한다.
- Pinky 2대도 각 장비의 ROS 2/Nav2를 로컬로 유지한다.
- 4060 관제 서버는 Control Tower, Gateway, OpenCV QR/ArUco 처리를 맡는다.
- OMEN 5080 서버는 ACT/VLM 등 딥러닝 모델 추론을 맡는다.
- PC 간 command/state/result는 Gateway의 versioned protocol을 사용하고,
  영상은 MediaMTX stream URI로 전달한다. 모든 장비를 하나의 광역 DDS
  domain에 직접 묶지 않는다.

P0의 OMX 2대는 단순히 상태 parameter를 반복하는 mock이 아니다. 실제 Gateway
command contract를 소비하고 `PREPARING`, `PICKING`, `OMX_READY`,
`LOADING`, `LOAD_CONFIRMED`, 실패 상태를 내는 deterministic protocol simulator다.
P1에서 같은 contract 뒤의 adapter만 실제 ROBOTIS driver로 바꾼다.

### 8.2 Pinky와 OMX의 marker 사용

선반에 이미 부착된 `DICT_5X5_50` marker 0, 1, 2를 그대로 쓴다. 별도 가상 ID
범위를 만들지 않는다.

- Pinky는 marker recognition pose에서 대상 marker와 상대 pose를 확인한 뒤
  협로/Dock 최종 정렬을 수행한다. Bottleneck reservation 획득은 별도 필수
  조건이며 marker 인식이 통행권을 대신하지 않는다.
- OMX는 손목 카메라 QR로 상품을 검증하고 ArUco 상대 pose로 pick frame을
  보정한 뒤 ACT 정책을 실행한다.
- Dock 정차 pose, marker recognition pose, OMX pick pose는 목적이 다른
  값이므로 같은 좌표로 강제하지 않는다.

### 8.3 ACT 정책 연결

실제 학습 checkpoint와 dataset은 Hugging Face repository에 있지만 repo ID는
아직 확정되지 않았다. 설정 계약은 다음처럼 둔다.

```text
ACT_MODEL_REPO_ID=UNCONFIGURED
ACT_MODEL_REVISION=UNCONFIGURED
ACT_POLICY_PROFILE=UNCONFIGURED
```

repo ID, revision, input feature, normalization 통계, 사용한 LeRobot version이
모두 고정되기 전에는 실제 OMX motion command를 내지 않는다. P0는 loader API,
model lineage schema, deterministic fake policy와 fixture inference까지 구현한다.
P1에서 실제 checkpoint를 주입해 관측 feature와 출력 action 범위를 검증한 뒤
실기 동작을 허용한다.

한 번의 pick attempt는 `QR 확인 → ArUco pose 보정 → 물체 재검출 → ACT episode
실행 → 파지 후 물체가 그리퍼와 함께 움직이는지 확인 → 인계`로 정의한다.
여기서 “함께 움직임”은 검출된 물체 track이 그리퍼가 닫힌 뒤 그리퍼의 이동과
일관되게 따라오는지를 뜻하며, 바구니 안에서 track이 단순히 끊기는 것을 성공으로
보지 않는다.

### 8.4 바구니 적재와 낙하 판정

Load cell이 없으므로 OMX 손목 카메라와 해당 작업 구역의 고정 카메라를 함께
사용한다. 그리퍼가 basket ROI 위에서 열리고, 물체가 ROI 안에 남으며, 그리퍼가
빈 상태로 물러나는 것을 확인해야 한다. 품목별 결과는 다음 네 상태 중 하나다.

- `LOAD_CONFIRMED`: 물체가 basket ROI에 남고 빈 그리퍼가 후퇴함
- `DROP_DETECTED`: basket ROI 밖 낙하 또는 이동 중 track 손실 후 낙하 증거가 있음
- `LOAD_UNCERTAIN`: 가림 등으로 성공과 낙하를 구분할 수 없음
- `GRASP_RETAINED`: 인계 후에도 물체가 그리퍼에 남음

`LOAD_CONFIRMED`가 아니면 Pinky 출발을 막는다. `LOAD_UNCERTAIN`은 성공으로
간주하지 않고 관리자 확인을 요청한다. `DROP_DETECTED`는 작업자 회수와 영역
안전 확인 전까지 재시도를 금지한다. 각 품목·attempt별 판정과 영상 evidence를
`job_step_attempts`와 `artifacts`에 연결한다.

## 9. 비상상황

Vision의 작업자 쓰러짐 후보가 들어오면 affected Zone의 로봇을 즉시 hold하고 해당
카메라 live stream을 UI에 자동 표시한다. 관리자는 두 동작만 선택한다.

- `비상경보 발령`: incident 확정, 영향 Zone/전체 로봇 정지, Job 보류, 대응 절차 시작
- `작업 계속 진행`: false positive와 관리자·사유 기록, hold 해제, Nav2 재계획 후
  기존 Job sequence 재개

팝업을 닫는 것만으로는 로봇을 재개하지 않는다. 모든 판단과 명령은
`operation_events`와 incident에 감사 가능하게 기록한다.

P0에는 다음 두 fixture를 필수로 포함한다.

1. Pinky 주행 중 쓰러짐 후보: 해당 Pinky 카메라를 열고 Pinky/RMF task를 hold한다.
2. 창고 내부 쓰러짐 후보: 해당 구역 고정 카메라를 열고 영향 작업을 hold한다.

두 fixture 모두 `작업 계속 진행`을 누르면 hold를 해제한 뒤 기존 경로를 그대로
맹목 재개하지 않고 Nav2 path 재계산과 RMF 재등록·승인을 거쳐 같은 Job을 이어간다.

## 10. Nav2·costmap 설정 UI

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

이 설정 form은 P1 범위다. P0는 `pinky_pro`의 기존 simulation profile을 읽어
manifest hash로 고정하고 UI에는 read-only 진단값만 표시한다.

## 11. 실시간 관제 화면

웹 map 위에 다음 레이어를 선택적으로 표시한다.

- SLAM occupancy map과 시설/Zone
- 로봇 pose, yaw, footprint, 배터리, 현재 Job
- Nav2 global/local path와 실제 주행 궤적
- global/local costmap
- 목적지 Waypoint와 yaw
- 병목 reservation과 대기 상태
- RMF 예상 trajectory, conflict, delay
- camera/incident marker

운영 화면의 주 경로는 Nav2가 현재 계산한 global/local path와 실제 주행 궤적이다.
내부 bootstrap graph는 숨기고 실행 경로처럼 표시하지 않는다. RMF에 등록된 timed
trajectory는 기본 화면이 아니라 진단 toggle에서만 Nav2 path와 겹쳐 비교한다.
두 값의 오차가 허용 범위를 넘으면 상태를 `PATH_SCHEDULE_MISMATCH`로 표시하고
출발을 막는다.

로봇 pose와 path는 WebSocket으로 전달한다. Camera는 MediaMTX WebRTC/HLS로
재생한다. 6개 영상을 항상 decode하거나 화면에 계속 재생하지 않고 다음 event에
맞는 tile만 자동으로 연다.

- OMX QR 확인·파지·적재: 해당 OMX 손목 카메라와 해당 작업 구역 고정 카메라
- Pinky 주행 중 쓰러짐 후보: 해당 Pinky 카메라
- 창고 내부 쓰러짐 후보: 해당 구역 고정 카메라
- 일반 주행: 관리자가 요청할 때 해당 Pinky 카메라

OMX 적재 화면에 Pinky 카메라를 성공 판정 근거로 사용하지 않는다. Pinky 카메라는
일반 주행 확인과 Pinky 주행 중 비상 판단용이다.

카메라 inventory는 고정 카메라 2대, OMX 손목 카메라 2대, Pinky 카메라 2대의 총
6 stream이다. 운영 UI는 보안실 CCTV처럼 6개 연결 상태를 한눈에 표시하되 event가
없으면 thumbnail/status만 유지한다. Event tile에는 QR bounding box와 값, ArUco
ID·축·상대 pose, ACT stage·model revision·attempt, gripper 상태, safety gate,
`LOAD_CONFIRMED`/실패 판정을 overlay한다. 성공하면 자동 닫고 재시도·낙하·불확실·
비상 상태면 관리자 판단까지 유지한다.

P0는 실제 카메라에 연결하지 않는다. 6개 fixture inventory와 synthetic/recorded
event stream으로 UI, protocol, 판정 코드를 검증한다. 실제 stream 연결과 camera별
calibration은 P1이다.

## 12. 영상 저장과 장비 용량

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
- 6 cameras, 2 Mbps: 약 129.6 GB/day
- 6 cameras, 4 Mbps: 약 259.2 GB/day

현재 350 GB 전체를 쓰지 않고 OS/개발용 100 GB를 남기면 녹화에 약 250 GB를 쓸 수
있다. 모든 stream을 2 Mbps로 계속 녹화한다는 가정에서는 약 1.9일이며, 7일에는
약 907 GB가 필요하다. 이는 용량 산식 예시일 뿐 실제 저장 정책이나 보존 일수의
확정값이 아니다.

P0는 fixture event clip만 보존한다. P1에서 실제 stream의 codec/bitrate와 저장 장치를
측정한 뒤 연속 녹화 또는 event 전후 ring-buffer 보존을 선택한다. MediaMTX recording을
활성화할 경우 H.264를 재인코딩하지 않고 fMP4 segment로 기록하고, segment metadata와
incident/job 연결만 DB `artifacts`에 둔다. 원본 영상은 MySQL에 넣지 않는다.

### OMEN RTX 5080

OMEN이라는 이름만으로 laptop/desktop, VRAM, RAM, SSD를 확정하지 않는다. 실제 배포
전 OMEN 5080 서버와 4060 관제 서버 각각에서 아래 정보를 수집한다.

```bash
nvidia-smi --query-gpu=name,memory.total,driver_version,power.limit --format=csv
free -h
lsblk -o NAME,MODEL,TRAN,SIZE,FSTYPE,MOUNTPOINTS
df -h
```

OMEN 5080과 4060 관제 PC의 동시 처리량 및 저장 일수는 **미정**이다. 아래 명령의 실제
결과와 6 stream soak test가 없으면 production profile을 승인하거나 보존 일수를
표시하지 않는다.

수치 확정 전의 P1 benchmark 항목은 다음과 같다.

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

장기 녹화 후보는 모델 서버와 장애 범위를 분리한 4060 측 전용 SSD 또는 별도
NAS/NFS/SMB다. 어느 쪽을 쓸지는 실제 6 stream bitrate와 확보 가능한 저장 공간을
측정한 뒤 정한다. 그 전까지 동시 처리량, 녹화 방식, 보존 일수는 모두
`UNMEASURED`이고 UI에도 숫자를 표시하지 않는다.

## 13. 한 명령 통합 기동

```bash
./scripts/control_stack up --mode simulation --project trihouse_test_01
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
8. Nav2/map server, Pinky 2대 simulation adapter, OMX 2대 protocol simulator
9. `control_ui` Flutter Web

최신 `control_system` source는 root의 `control_ui/`로 모두 복사하되 nested `.git`,
build, cache 산출물만 제외한다. 복사 직후 `control_ui/db`와 직접 DB/migration/ROS/
process/filesystem adapter를 제거하고 Gateway client로 교체해야 `up`의 UI 단계에
포함할 수 있다. 이후 제품 source의 기준 경로와 표시 명칭은 `control_ui`다. 첫
통합에서는 내부 Flutter package 이름을 일괄 변경하지 않아 upstream 비교 가능성을
유지한다.

기본은 Gazebo headless다. `--gazebo-gui`, `--rviz`를 명시한 경우에만 진단 창을
띄운다. `compose.ai_5080.yaml`과 모델 weight는 이 명령에 포함하지 않는다. Control
stack은 원격 AI health와 model version만 확인하며 simulation mode에서는 fixture
Vision event를 사용할 수 있다.

## 14. 검증 기준

- 사용자 UI에 Lane 작성 기능이 없다.
- 상품/수량/우선순위/부분 출고 여부만으로 상온 → 냉장 → 냉동 → 포장대 sequence가
  생성된다.
- 빈 온도 구역은 생략되고 같은 구역 다품목은 단일 Loading Dock 방문으로 묶인다.
- `trihouse_test_01_physical_features.jsonl`의 13개 record만 P0 위치 원장으로 쓰며
  fixture가 임의 좌표를 만들지 않는다.
- Waypoint와 yaw는 배포 시 JSONL에서 `locations`로 반영된 값으로만 결정된다.
- Dock 정차 pose와 marker recognition pose를 별도 값으로 유지한다.
- 두 Bottleneck은 지름 0.2m, 반지름 0.1m로 import되고 표시된다.
- 작업자 완료 전에는 최종 재고가 변하지 않는다.
- `저장`한 Draft는 재접속 후 복구되고 `삭제`할 수 있다. 저장하지 않은 변경은
  이탈 확인 후 폐기할 수 있다.
- 동일 이름 Draft는 기존 Draft를 열고, 동일 이름 Active는 기존 project의 새 Draft
  revision을 열도록 안내한다.
- 배포 실패 시 기존 Active는 유지되고 Draft에서 고칠 수 있으며, 영구 failure audit
  row는 만들지 않는다.
- SLAM source와 JSONL import는 `map_project_sources`와 배포 revision manifest에
  UUID/hash로 보존된다.
- UI에 DB/ROS/process 직접 접근 코드가 없다.
- Control Tower가 특정 Pinky·OMX·Packing Dock을 배정하며 RMF가 로봇을 바꾸지 않는다.
- Nav2 `ComputePathToPose` 결과가 RMF에 등록·승인된 뒤 `FollowPath`로 실행된다.
- 실제 Nav2 path, robot pose, costmap, reservation/conflict가 웹 지도에 표시되고
  내부 graph는 기본 화면에 노출되지 않는다.
- Bottleneck은 외부 접근 영역에서 원자적으로 예약하며 15초 뒤 우회 가능 여부를
  계산하고, priority는 통행권에 개입하지 않는다.
- 비상 후보에서 로봇 hold와 camera 표시가 먼저 일어나며, 두 관리자 결정 모두
  감사 이력에 남는다.
- 한 명령으로 MySQL부터 Open-RMF, Gazebo, Nav2, UI까지 올라오고 `down`으로 정리된다.
- 최신 A의 OMX/RMF 회귀 테스트와 Trihouse Job/DB 통합 테스트가 모두 통과한다.
- OMX는 Pinky ETA 기반 `prepare_at`에 시작하고 `PINKY_READY`와 `OMX_READY`가 같은
  assignment revision에 모이기 전에는 적재 동작을 허용하지 않는다.
- Pinky/OMX의 QR·ArUco fixture와 OMX protocol simulator 2대가 실제 command/state
  contract를 검증한다.
- ACT repo가 `UNCONFIGURED`면 실제 motion을 차단하면서도 P0 fake policy로 전체
  orchestration을 검증할 수 있다.
- `LOAD_CONFIRMED` 전 Pinky 출발이 차단되고 낙하·불확실·grasp retained가 품목별
  attempt와 영상 evidence에 남는다.
- UI의 `작업 완료` 버튼은 멱등 완료 API 성공 후에만 완료 상태를 표시한다.
- 긴급 주문과 opt-in 부분 출고가 canonical DB 값으로 저장되고 감사 이력이 남는다.
- 모든 Step attempt의 성공 기준·관측·metric·evidence·model lineage가 DB에 남는다.
- 작업 완료 후 `PK_01`, `PK_02`가 각각 정해진 충전소로 복귀하고 Packing Dock 2개가
  예상 사용 가능 시간 기준으로 배정된다.
- 6 camera production profile은 4060/5080 실제 측정 artifact 없이는 활성화되지 않는다.

## 15. 일정과 테스트 범위

### 2026-08-16까지: 시뮬레이션 검증

- 필수: 최신 A 전체를 `control_ui`로 복사하고 직접 DB/migration/ROS/process/filesystem
  접근을 Gateway REST/WebSocket으로 전환한다.
- 필수: `trihouse_test_01` JSONL import, Draft 저장·삭제, 배포와 두 Packing Dock,
  두 충전소를 검증한다.
- 필수: Pinky 2대, Open-RMF, Nav2, Gazebo headless, Control Tower, Gateway, MySQL,
  Control UI, OMX protocol simulator 2대를 한 명령으로 기동한다.
- 필수: 주문 A~F를 fresh seed에서 실행해 온도 구역 순서, 단일 Dock 묶음, 긴급 배차,
  부분 출고, 재고 부족, 작업자 완료와 복귀를 검증한다.
- 필수: 두 Pinky가 동시에 서로 다른 Job을 수행하고 Nav2가 계산한 실제 path를 RMF에
  등록·협상한 뒤 실행하며, actual path와 선택적 RMF trajectory가 UI에 표시된다.
- 필수: OMX 2대의 ETA 선행 준비, 양측 READY gate, 품목별 load 판정, 재시도와 포장대
  처리 분기를 protocol simulator로 검증한다.
- 필수: OpenCV QR/ArUco 처리 코드와 Pinky/OMX fixture를 검증한다.
- 필수: ACT adapter, `UNCONFIGURED` 차단, deterministic fake policy와 lineage 저장을
  검증한다.
- 필수: 6 camera fixture inventory와 event 영상 UI를 검증하고, Pinky 주행 중 비상과
  창고 내부 비상 두 fixture에서 hold → 작업 계속 진행 → Nav2/RMF 재계획을 확인한다.
- 제외: 실제 Pinky/OMX/camera 연결, 실제 ACT checkpoint motion, 장비 처리량과 보존
  일수 확정은 P0 gate가 아니다.

### 2026-08-17: 통합 gate와 이후 P1

- A에서 복사한 `control_ui`, Control Tower, Gateway, canonical MySQL, Open-RMF,
  Nav2/Gazebo, MediaMTX를 통합한다.
- P0 simulation regression을 통합 gate로 실행한 뒤 실제 Pinky/OMX/camera 작업을
  P1으로 진행한다.
- 4060 QR/ArUco와 원격 5080 VLM/ACT endpoint는 health/model-version 계약으로
  실제 연결하고 OMX 2대의 일반 PC adapter와 Pinky adapter를 검증한다.
- ACT Hugging Face repo ID/revision/features/normalization/LeRobot version을 고정하고
  실제 motion 전용 acceptance test를 통과시킨다.
- 실제 camera calibration, Floor 측정, Polygon editor, 범용 CSV/JSON import,
  Nav2/costmap/robot parameter form을 진행한다.
- 실제 장비 처리량과 저장 일수는 4060/5080의 필수 명령 결과와 6 camera soak test가
  준비된 경우에만 확정한다. 준비되지 않으면 `UNMEASURED` 배포 차단 상태를 유지한다.
