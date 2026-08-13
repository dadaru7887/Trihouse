# FMS Inventory, QR Matching, and Development Seed Design

## 목적과 기준

`db/schema_mysql.sql`을 신규 DB 설치와 데이터 모델의 유일한 기준으로 사용한다.
`db/seed_dev.sql`은 이 스키마에 맞는 재현 가능한 로컬 통합 테스트 데이터를 넣고,
`docs/database/item_qr_payloads.json`의 QR `lot` 값은
`trihouse_fms.inventory_lots.lot_code`와 정확히 일치해야 한다.

이번 범위는 다음 결과를 만든다.

1. 상온·냉장·냉동 창고와 각 창고의 1층/2층 슬롯을 `locations`에 표현한다.
2. QR 11종에 대응하는 가상 재고를 `inventory_lots`에 넣는다.
3. 고정 테이블·컬럼 개수 대신 스키마 계약과 데이터 관계를 검증한다.
4. 주문이 선택한 lot와 실제 QR lot가 일치할 때만 파지를 승인하는 데이터 흐름을 정의한다.
5. 주문에서 Pinky·OMX·FMS 실행 순서를 만들 때 기존 `jobs`, `job_items`,
   `job_steps` 구조를 사용한다.

`schema_mysql.sql`의 테이블이나 컬럼은 이번 시드 정합화 때문에 변경하지 않는다.

## 검토한 대안

### 대안 A: 창고 없이 11개 슬롯만 생성

구현은 가장 간단하지만 슬롯이 어느 창고에 속하는지 FK로 표현할 수 없다.
온도 구역, UI 트리, OMX 대상 위치를 함께 관리하기 어려우므로 채택하지 않는다.

### 대안 B: 창고 3개와 최종 적재 슬롯 12개 생성 — 채택

창고는 `location_type='rack'`, 최종 구역은 `location_type='slot'`로 저장한다.
슬롯의 `parent_location_id`가 창고를 가리키고, 층과 같은 스키마 외 속성은
`metadata`에 넣는다. 현재 스키마의 자기 참조 FK와 JSON 확장 지점을 그대로 사용한다.

### 대안 C: 창고·층·슬롯을 모두 별도 행으로 생성

계층은 가장 상세하지만 현재 `location_type`에는 창고나 층 전용 값이 없고,
창고별 2층·층별 2슬롯인 현재 요구에는 불필요한 중간 행이 된다. 실제로 한 층에
다수 선반이 추가될 때 별도 설계로 확장한다.

## 위치 데이터 모델

### 기존 운영 위치 보존

`A-SLOT-01`, `OUT-DOCK-01`, `CHG-01`, `CHG-02`, `IN-WAIT-01`,
`NARROW-WAIT-01`, `OMX-WS-01`, `OMX-WS-02`는 현재 RMF 프로젝트와 코드의
호환성을 위해 유지한다. 특히 `A-SLOT-01`은 `project1/픽업1` 접근 지점으로
계속 사용하며 실제 상품 재고의 적재 슬롯으로 사용하지 않는다.

새 창고와 슬롯에는 실측하지 않은 `pose_x`, `pose_y`, `pose_yaw`를 만들지 않는다.
또한 하나의 RMF waypoint를 여러 Location에 중복 연결할 수 없으므로 새 창고와 물리
슬롯의 `map_name`과 `rmf_waypoint_name`은 모두 `NULL`로 둔다. 로컬 시뮬레이션의
이동 Step은 기존 접근 지점 `A-SLOT-01`을 사용하고, inspect/pick/verify Step은 실제
슬롯 `location_id`를 대상으로 사용한다.

사용자가 Control System UI에서 창고별 waypoint를 직접 생성한 뒤, 지도 저장·발행이
창고 Location의 `map_name`, `rmf_waypoint_name`, `pose_*`를 자동 반영하는지는
별도의 "연결 테스트 1"에서 검증한다. 시드는 이 테스트 결과를 미리 가정하지 않는다.

### 창고 행

| location_code | name | location_type | zone_code | temperature_zone | state |
| --- | --- | --- | --- | --- | --- |
| `WH-AMB-01` | 상온창고 | `rack` | `ambient` | `ambient` | `available` |
| `WH-CHL-01` | 냉장창고 | `rack` | `chilled` | `chilled` | `available` |
| `WH-FRZ-01` | 냉동창고 | `rack` | `frozen` | `frozen` | `available` |

현재 확인된 창고별 확장 정보가 없으므로 창고 `metadata`는 `NULL`로 둔다.
창고 번호는 `location_code`에서 이미 식별되고, 층·슬롯 수는 자식 슬롯 행에서 계산할
수 있다. RMF 접근 Location은 UI 연결 테스트 전까지 가정하지 않는다.

### 슬롯 행

각 슬롯은 `parent_location_id`로 해당 창고를 참조한다. `location_type='slot'`이며,
재고가 있는 슬롯은 `occupied`, 빈 `AMB-L1-S02`만 `available`이다.

```json
{
  "shelf_level": 1,
  "slot_index": 1
}
```

| location_code | parent | 층 | 위치 | 상품 | state |
| --- | --- | ---: | ---: | --- | --- |
| `AMB-L1-S01` | `WH-AMB-01` | 1 | 1 | Mandarin | `occupied` |
| `AMB-L1-S02` | `WH-AMB-01` | 1 | 2 | 비어 있음 | `available` |
| `AMB-L2-S01` | `WH-AMB-01` | 2 | 1 | Orange | `occupied` |
| `AMB-L2-S02` | `WH-AMB-01` | 2 | 2 | Strawberry | `occupied` |
| `CHL-L1-S01` | `WH-CHL-01` | 1 | 1 | Yogurt | `occupied` |
| `CHL-L1-S02` | `WH-CHL-01` | 1 | 2 | Milk | `occupied` |
| `CHL-L2-S01` | `WH-CHL-01` | 2 | 1 | Coffee | `occupied` |
| `CHL-L2-S02` | `WH-CHL-01` | 2 | 2 | Sandwich | `occupied` |
| `FRZ-L1-S01` | `WH-FRZ-01` | 1 | 1 | Ice bar | `occupied` |
| `FRZ-L1-S02` | `WH-FRZ-01` | 1 | 2 | Ice cone | `occupied` |
| `FRZ-L2-S01` | `WH-FRZ-01` | 2 | 1 | Pork belly | `occupied` |
| `FRZ-L2-S02` | `WH-FRZ-01` | 2 | 2 | Dumpling | `occupied` |

`locations`에는 창고·슬롯 자체만 저장한다. 상품명, lot, 수량, 유통기한은
`inventory_lots`에 저장하고 `inventory_lots.location_id`로 슬롯을 참조한다.

## 컬럼 최소화 검토

이번 데이터 때문에 `schema_mysql.sql`에 새 컬럼을 추가하지 않는다. 관련 기존 컬럼도
각각 다음 용도가 있어 삭제 대상으로 보지 않는다.

| 테이블.컬럼 | 유지 이유 |
| --- | --- |
| `locations.parent_location_id` | 슬롯과 창고의 계층 관계를 FK로 보장한다. |
| `locations.zone_code` | 업무 구역 코드이며 물품의 보관 조건인 `temperature_zone`과 의미가 다르다. |
| `locations.temperature_zone` | 해당 위치가 허용하는 온도 구역을 표현한다. |
| `locations.map_name`, `rmf_waypoint_name`, `pose_*` | 새 물리 슬롯에서는 NULL이지만 waypoint·도크·충전기 등 다른 Location 타입이 사용한다. |
| `locations.metadata` | 현재 스키마에 없는 슬롯의 층·슬롯 번호만 최소 저장한다. 창고 metadata는 현재 NULL이다. |
| `inventory_lots.product_code` | 서로 다른 lot를 같은 상품으로 검색·주문하기 위한 키다. |
| `inventory_lots.item_name` | 별도 상품 마스터 테이블이 없는 현재 UI의 표시명이다. 상품 마스터가 생기면 중복 여부를 재검토한다. |
| `inventory_lots.temperature_zone` | 상품 자체의 보관 요구조건으로, 현재 적재 위치의 온도와 독립적으로 검증한다. |
| `inventory_lots.unit_weight_kg` | OMX 파지와 Pinky 적재중량 판단에 사용한다. |
| `inventory_lots.available_qty`, `reserved_qty` | 물리 수량과 주문 예약 수량을 분리한다. |
| `inventory_lots.state` | 수량만으로 표현할 수 없는 보류·손상·만료 상태를 관리한다. |
| `inventory_lots.received_at`, `updated_at` | 입고 및 변경 감사 시각을 보존한다. |

불필요했던 값은 DB 컬럼이 아니라 앞서 제안한 JSON metadata의 파생·구현 정보였다.
따라서 창고 metadata는 `NULL`, 슬롯 metadata는 `shelf_level`과 `slot_index`만
저장한다. 향후 컬럼 삭제를 검토할 때는 Gateway,
관제 UI, RMF import, migration, 운영 쿼리 사용처를 모두 확인하고 별도 migration으로
진행한다.

## 재고 데이터

모든 행은 `reserved_qty=0`, `state='stored'`을 사용한다. `received_at`은 시드가
처음 행을 만드는 시점의 `CURRENT_TIMESTAMP(6)`을 사용하며, 중복 키 갱신에서는
최초 입고 시각을 덮어쓰지 않는다.

| product_code | lot_code | item_name | zone | location_code | expiry_date | unit_weight_kg | available_qty |
| --- | --- | --- | --- | --- | --- | ---: | ---: |
| `SKU-ORANGE` | `LOT-AMB-ORANGE-001` | Orange | `ambient` | `AMB-L2-S01` | 2026-08-28 | 0.200 | 1 |
| `SKU-STRAWBERRY` | `LOT-AMB-STRAWBERRY-001` | Strawberry | `ambient` | `AMB-L2-S02` | 2026-08-27 | 0.250 | 1 |
| `SKU-MANDARIN` | `LOT-AMB-MANDARIN-001` | Mandarin | `ambient` | `AMB-L1-S01` | 2026-09-02 | 0.120 | 2 |
| `SKU-COFFEE` | `LOT-CHL-COFFEE-001` | Coffee | `chilled` | `CHL-L2-S01` | 2026-10-31 | 0.250 | 1 |
| `SKU-SANDWICH` | `LOT-CHL-SANDWICH-001` | Sandwich | `chilled` | `CHL-L2-S02` | 2026-09-10 | 0.180 | 2 |
| `SKU-YOGURT` | `LOT-CHL-YOGURT-001` | Yogurt | `chilled` | `CHL-L1-S01` | 2026-09-30 | 0.100 | 2 |
| `SKU-MILK` | `LOT-CHL-MILK-001` | Milk | `chilled` | `CHL-L1-S02` | 2026-09-20 | 0.200 | 1 |
| `SKU-PORKBELLY` | `LOT-FRZ-PORKBELLY-001` | Pork belly | `frozen` | `FRZ-L2-S01` | 2027-08-13 | 0.500 | 2 |
| `SKU-DUMPLING` | `LOT-FRZ-DUMPLING-001` | Dumpling | `frozen` | `FRZ-L2-S02` | 2027-08-20 | 0.400 | 1 |
| `SKU-ICEBAR` | `LOT-FRZ-ICEBAR-001` | Ice bar | `frozen` | `FRZ-L1-S01` | 2027-08-25 | 0.080 | 2 |
| `SKU-ICECONE` | `LOT-FRZ-ICECONE-001` | Ice cone | `frozen` | `FRZ-L1-S02` | 2027-08-31 | 0.150 | 2 |

시드는 `lot_code`의 UNIQUE KEY를 기준으로 멱등 처리한다. 재실행하면 사용자가 수동으로
변경한 운영 재고 수량을 되돌릴 수 있으므로, 이 파일은 폐기 가능한 개발 DB의 초기화와
명시적인 시드 재적용에만 사용한다.

## QR 조회와 파지 승인 계약

QR payload는 다음 최소 형식이다.

```json
{"v": 1, "lot": "LOT-CHL-MILK-001"}
```

처리 순서는 다음과 같다.

1. `v`가 지원 버전 `1`인지 확인한다.
2. `lot`을 `inventory_lots.lot_code`로 조회한다.
3. lot가 `stored` 상태이고 `available_qty - reserved_qty`가 요청 수량 이상인지 확인한다.
4. `inventory_lots.location_id`로 `locations`를 조회하고 슬롯, 부모 창고,
   온도 구역, 층, 슬롯 번호를 반환한다.
5. 주문 생성 시 FMS가 선택한 `job_items.lot_id`와 인식된 lot의 `lot_id`를 비교한다.
6. 예상 슬롯과 실제 관측 슬롯 또는 ArUco가 제공한 Location도 비교한다.
7. 모두 일치하면 `job_items.verification_state='matched'`, 다르면 `mismatch`로 기록한다.
8. `matched`인 경우에만 다음 `pick` Step이 실행 가능하다.

QR은 상품 검색 키이면서 파지 직전 확인값이다. QR만 읽었다는 이유로 주문에 예약되지 않은
상품을 파지해서는 안 된다.

ArUco marker 번호와 실측 geometry는 아직 정해지지 않았으므로 이번 시드에 임의 값을 넣지
않는다. 나중에 `map_features(feature_type='fiducial', marker_code, location_id,
geometry, properties)`로 슬롯 또는 창고와 연결한다.

## 주문 및 작업 시퀀스

주문 헤더는 `jobs`, 품목과 예약 lot는 `job_items`, 실행 순서는 `job_steps`에 저장한다.
`job_steps`에는 `job_item_id` 컬럼이 없으므로 상품별 Step은 `input.job_item_id`,
`input.expected_lot_code`, `input.expected_location_code`로 연결한다.

상품별 처리 순서는 다음과 같다.

| 순서 | executor_type | action_type | target | 의미 |
| ---: | --- | --- | --- | --- |
| 1 | `fms` | `verify` | 실제 슬롯 | 재고와 예약 lot 검증 |
| 2 | `mobile` | `navigate` | `A-SLOT-01` | 로컬 시뮬레이션 창고 접근 지점 이동 |
| 3 | `mobile` | `dock` | `OMX-WS-01` | 로컬 시뮬레이션 Pinky·OMX 정렬 |
| 4 | `arm` | `inspect` | 실제 슬롯 | ArUco/슬롯 관측 |
| 5 | `fms` | `verify` | 실제 슬롯 | QR lot와 예약 lot 비교 |
| 6 | `arm` | `pick` | 실제 슬롯 | 검증된 물품 파지 |
| 7 | `arm` | `load` | `OMX-WS-01` | Pinky에 적재 |

모든 주문 품목의 적재가 끝나면 다음 공통 Step을 붙인다.

| 순서 | executor_type | action_type | target | 의미 |
| ---: | --- | --- | --- | --- |
| N+1 | `mobile` | `navigate` | `OUT-DOCK-01` | 출고 도크 이동 |
| N+2 | `mobile` | `handover` | `OUT-DOCK-01` | 물품 인계 |
| N+3 | `fms` | `verify` | `OUT-DOCK-01` | 완료 수량 확인 및 재고 확정 |
| N+4 | `mobile` | `return_home` | 배정 로봇 충전기 | 복귀 |

여러 상품 주문은 창고·층·슬롯 순으로 묶어 불필요한 이동을 줄인다. 단, 현재
`job_steps`는 엄격한 순차 실행이므로 먼저 정확성과 감사 가능성을 검증하고 병렬 실행은
추후 범위로 둔다.

## 시드 예제 Job

기존 `JOB-DEV-001` 스모크 데이터는 삭제하지 않고 QR 기준 데이터로 정합화한다.
예제 품목은 `LOT-AMB-ORANGE-001`, 수량 1, 원본 슬롯 `AMB-L2-S01`, 목적지
`OUT-DOCK-01`을 사용한다. 시드 Job은 전체 오케스트레이션을 대신하지 않으며 API와 UI
목록이 기본 데이터를 읽는지 확인하는 용도다.

## 테스트 설계

고정 숫자 `16`, `18`, `253`, `4`를 현재 숫자로 교체하는 방식은 다시 쉽게 깨지므로
사용하지 않는다.

1. 스키마 테스트는 필요한 FMS/Recovery 테이블 이름의 집합을 비교한다.
2. 주석 테스트는 행 개수가 아니라 모든 테이블·컬럼 주석이 비어 있지 않고 ASCII이며
   한글을 포함하지 않는지 검증한다.
3. 시드를 두 번 적용한 뒤 창고 3개, 슬롯 12개, QR lot 11개가 중복 없이 존재하는지
   검증한다.
4. QR JSON의 lot 집합과 DB `inventory_lots.lot_code` 집합이 정확히 일치하는지 검증한다.
5. 각 재고의 슬롯 부모, 층, 슬롯 번호, 온도 구역, 수량을 정확히 검증한다.
6. 빈 `AMB-L1-S02`에는 재고가 없고 `state='available'`인지 검증한다.
7. 예제 Job의 `job_items.lot_id`와 출발 슬롯이 새 QR 기준 데이터와 일치하는지 검증한다.
8. 새 창고와 슬롯의 RMF waypoint 및 pose가 시드 단계에서는 NULL인지 검증한다.

## 연결 테스트 1: UI waypoint 자동 반영

시드와 Gateway 검증이 끝난 뒤 Control System UI를 실행한다. 사용자가 창고별 waypoint를
지도에 직접 생성하고 각 waypoint의 `locationCode`를 `WH-AMB-01`, `WH-CHL-01`,
`WH-FRZ-01` 중 하나로 지정한다. 지도 초안 저장과 발행 후 다음을 확인한다.

1. `map_project_waypoints.location_code`와 `rmf_waypoint_name`이 UI 입력값과 일치한다.
2. 지도 발행 후 `locations`의 해당 창고 행에 `map_name`, `rmf_waypoint_name`,
   `pose_x`, `pose_y`, `pose_yaw`가 자동 반영된다.
3. 자식 슬롯의 waypoint는 계속 NULL이고 부모 창고를 통해 접근 위치를 찾는다.
4. 기존 `A-SLOT-01/픽업1` 등 운영 Location 매핑이 깨지지 않는다.
5. 자동 반영되지 않으면 DB를 수동 수정하지 않고 Gateway의 지도 발행 경로와
   Location 갱신 로직을 진단한다.

## 오류 처리와 운영 경계

- 알 수 없는 QR 버전 또는 lot는 파지를 거절한다.
- DB lot와 주문 예약 lot가 다르면 `mismatch`로 기록하고 파지를 거절한다.
- 온도 구역이나 위치 관계가 맞지 않으면 데이터 오류로 보고 파지를 거절한다.
- 수량 부족, `on_hold`, `depleted`, `expired`, `damaged` 상태는 예약하지 않는다.
- QR/ArUco 인식 실패는 재고를 변경하지 않는다.
- 실제 인계가 성공한 뒤에만 `inventory_lots` 수량 변경과 `inventory_moves` 추가를 같은
  트랜잭션에서 처리한다.
- `seed_dev.sql`은 개발 데이터 전용이며 운영 DB에 자동 재적용하지 않는다.

## 로컬 통합 테스트 범위

PC 한 대에서 우선 DB, FMS Gateway, RMF/Gazebo, 관제 UI를 순서대로 시작한다.
DB와 Gateway만으로 QR 조회·주문 데이터·Step 생성을 먼저 검증하고, 그 다음 기존
`project1`의 `A-SLOT-01(픽업1)`과 `OUT-DOCK-01(드랍오프1)`을 이용해 RMF 이동을
확인한다. 물리 창고별 RMF waypoint와 ArUco 실측값은 확정 후 추가한다.
