# QR·ArUco 지도 표식 및 물품 QR 데이터셋 설계

## 목적과 범위

창고 지도에 부착할 QR 코드와 ArUco marker의 위치·식별 정보를 기존 FMS MySQL v4 스키마에 저장하는 기준을 정의한다. 또한 상온·냉장·냉동 물품 11종에 대한 입고 QR payload 데이터셋을 CSV와 JSON으로 제공하고, 사용자가 수량을 입력한 뒤 개별 QR PNG를 생성할 수 있게 한다.

이번 작업은 기존 스키마를 변경하지 않는다. 실제 지도 좌표와 marker ID는 설치 시 확정해야 하므로 지도 데이터의 완성된 INSERT가 아니라 저장 규칙과 예시를 제공한다. QR PNG 파일 자체는 기본 데이터셋에 포함하지 않고 재현 가능한 생성 스크립트와 사용법을 제공한다.

## 기존 DB 테이블 매핑

### `locations`

창고, 랙, 슬롯, 작업 위치처럼 운영 의미가 있는 장소를 저장한다.

- `location_code`: 장소 고유 코드(예: `AMBIENT_RACK_01_SLOT_01`)
- `parent_location_id`: 랙과 슬롯의 계층 연결
- `location_type`: `rack`, `slot`, `waypoint`, `workstation` 등
- `zone_code`: 업무 구역 코드
- `temperature_zone`: `ambient`, `chilled`, `frozen`
- `map_name`, `rmf_waypoint_name`: RMF 지도와 waypoint 연결
- `pose_x`, `pose_y`, `pose_yaw`: 지도 좌표계 기준 위치와 방향
- `metadata`: 설치 높이 등 위치별 확장 정보

슬롯과 해당 슬롯에 보관되는 `inventory_lots.temperature_zone`의 일치는 Gateway가 검증한다.

#### 2층 선반 위치 코드

상온·냉장·냉동 창고는 각각 랙 1개, 2개 층, 층별 2개 슬롯으로 구성한다. 위치 코드는 다음 규칙을 사용한다.

```text
<TEMPERATURE>_RACK_<rack>_LEVEL_<level>_SLOT_<slot>
```

- `TEMPERATURE`: `AMBIENT`, `CHILLED`, `FROZEN`
- `rack`, `level`, `slot`: 두 자리 숫자
- 랙 행은 `AMBIENT_RACK_01`처럼 만들고 슬롯 행의 `parent_location_id`로 연결한다.
- 층은 별도 `location_type`이 없으므로 슬롯의 `metadata.level`에도 같은 숫자를 저장한다.

초기 시연용 배정은 다음과 같다. 실제 입고 시에는 이 표의 위치를 고정값으로 QR에 넣지 않고, FMS가 같은 온도 구역의 사용 가능한 슬롯을 예약한다.

| 온도 구역 | 층 | 슬롯 | `location_code` | 초기 품목 |
| --- | ---: | ---: | --- | --- |
| 상온 | 1 | 1 | `AMBIENT_RACK_01_LEVEL_01_SLOT_01` | 귤 |
| 상온 | 1 | 2 | `AMBIENT_RACK_01_LEVEL_01_SLOT_02` | 비어 있음 |
| 상온 | 2 | 1 | `AMBIENT_RACK_01_LEVEL_02_SLOT_01` | 오렌지 |
| 상온 | 2 | 2 | `AMBIENT_RACK_01_LEVEL_02_SLOT_02` | 딸기 |
| 냉장 | 1 | 1 | `CHILLED_RACK_01_LEVEL_01_SLOT_01` | 요구르트 |
| 냉장 | 1 | 2 | `CHILLED_RACK_01_LEVEL_01_SLOT_02` | 우유 |
| 냉장 | 2 | 1 | `CHILLED_RACK_01_LEVEL_02_SLOT_01` | 커피 |
| 냉장 | 2 | 2 | `CHILLED_RACK_01_LEVEL_02_SLOT_02` | 샌드위치 |
| 냉동 | 1 | 1 | `FROZEN_RACK_01_LEVEL_01_SLOT_01` | 아이스크림바 |
| 냉동 | 1 | 2 | `FROZEN_RACK_01_LEVEL_01_SLOT_02` | 아이스크림콘 |
| 냉동 | 2 | 1 | `FROZEN_RACK_01_LEVEL_02_SLOT_01` | 냉동 삼겹살 |
| 냉동 | 2 | 2 | `FROZEN_RACK_01_LEVEL_02_SLOT_02` | 냉동 만두 |

### `map_features`

지도에 고정 부착한 QR과 ArUco marker의 메타데이터를 저장한다. 실제 Nav2/RMF 지도 파일이나 이미지 파일은 DB에 넣지 않는다.

- `map_name`, `map_revision`: marker 좌표가 유효한 지도 버전
- `feature_code`: 사람이 읽을 수 있는 고유 코드
- `feature_type`: QR과 ArUco 모두 기존 허용값 `fiducial`
- `location_id`: marker가 나타내는 `locations` 행
- `marker_code`: 카메라가 읽는 숫자 ID
- `geometry`: 지도 좌표계 기준 point와 pose
- `properties.marker_kind`: `qr` 또는 `aruco`
- `properties.dictionary`: ArUco 사용 시 dictionary 이름
- `properties.physical_size_m`: 실제 marker 한 변의 길이
- `properties.payload_schema`: 지도 QR payload 형식 버전
- `active`: 현재 지도 revision에서 사용 여부

기존 유니크 키 `(map_name, map_revision, marker_code)` 때문에 같은 지도 revision에서는 QR과 ArUco를 포함해 marker ID가 중복되면 안 된다. QR payload에는 숫자 `marker_code`와 `feature_code`를 넣고, DB 조회 결과를 신뢰 가능한 위치 정보로 사용한다.

### `inventory_lots`

입고 완료 후 확정된 물품 lot과 재고를 저장한다.

- `product_code`: 상품 종류 코드
- `lot_code`: 추적 가능한 lot 고유 코드
- `item_name`: 한글 표시 이름
- `temperature_zone`: QR의 `storage_code`를 검증한 결과
- `location_id`: 최종 적재가 완료된 슬롯
- `expiry_date`: QR의 유통기한
- `available_qty`: 사용자가 입력한 수량
- `reserved_qty`: 초기값 `0`
- `state`: 입고 접수 시 `pending_inbound`, 최종 적재 완료 시 `stored`

시스템 요구사항에 따라 최종 적재 전에는 원본 재고를 확정하지 않는다. 입고 완료에 따른 수량 변경은 `inventory_moves` 기록과 같은 트랜잭션에서 처리한다.

### 작업 및 검증 이력

- `job_items`: 작업 대상 `product_code`, 수량, lot, QR 일치 상태를 저장한다.
- `job_items.metadata`: 스캔 ID와 QR payload 버전처럼 해당 작업 품목의 검증 부가정보를 저장한다.
- `operation_events`: QR 인식 실패, 불일치, 수동 검토 같은 운영 사건을 추가 전용 이력으로 남긴다.
- `inventory_moves`: 입고 완료 후 실제 재고 변동을 추가 전용 원장으로 남긴다.

## 물품 QR payload 계약

QR에는 UTF-8로 직렬화한 compact JSON을 넣는다.

```json
{"schema":"trihouse.item.v1","item_id":"ITEM-AMB-ORANGE-001","product_code":"ORANGE","item_name":"오렌지","expiry_date":"2026-08-13","storage_code":"ambient","quantity":1}
```

필드 규칙은 다음과 같다.

| 필드 | 형식 | 규칙 |
| --- | --- | --- |
| `schema` | string | `trihouse.item.v1` 고정 |
| `item_id` | string | 데이터셋 내 고유한 물품/라벨 ID |
| `product_code` | string | 영문 대문자 snake case 상품 코드 |
| `item_name` | string | 운영 화면용 한글 이름 |
| `expiry_date` | `YYYY-MM-DD` | 생성 기준일 이후 날짜 |
| `storage_code` | enum | `ambient`, `chilled`, `frozen` 중 하나 |
| `quantity` | positive integer | 사용자가 CSV에 입력하며 PNG 생성 전 필수 검증 |

정확한 `location_code`, 선반 번호와 슬롯 번호는 물품 QR에 넣지 않는다. QR의 `storage_code`는 보관해야 할 온도 구역이고, 실제 저장 위치는 FMS가 입고 시점의 빈 슬롯을 예약한 뒤 `inventory_lots.location_id`로 확정한다. 따라서 물품을 다른 슬롯으로 옮겨도 QR을 다시 만들 필요가 없다.

QR payload의 최소 필수 정보는 `schema`, `item_id`, `product_code`, `item_name`, `expiry_date`, `storage_code`, `quantity`이다. JSON 끝의 불필요한 따옴표를 붙이지 않으며, 실제 QR에는 Markdown 코드 블록이 아니라 중괄호 안 JSON 문자열만 인코딩한다.

CSV 템플릿의 `quantity`는 빈 칸이고 JSON 템플릿의 값은 `null`이다. QR PNG 생성기는 수량이 비어 있거나 양의 정수가 아니면 생성하지 않고 해당 행과 원인을 출력한다. 생성되는 실제 QR payload에는 반드시 양의 정수가 들어간다.

## 데이터셋 구성

발표일 `2026-08-25`를 생성 기준일 `D`로 고정하여 반복 실행에도 동일한 결과를 얻는다. 상온은 `D+3일`부터 `D+5일`, 냉장은 `D+5일`부터 `D+7일`, 냉동은 `D+365일`부터 `D+368일` 사이로 배정한다.

| 온도 구역 | 물품 | 유통기한 정책 |
| --- | --- | --- |
| 상온 | 오렌지, 딸기, 귤 | 발표일로부터 3~5일 (`2026-08-28`~`2026-08-30`) |
| 냉장 | 커피, 우유, 샌드위치, 요구르트 | 상온 범위보다 1~2일 긴 5~7일 (`2026-08-30`~`2026-09-01`) |
| 냉동 | 냉동 삼겹살, 아이스크림콘, 아이스크림바, 냉동 만두 | 발표일로부터 약 1년 (`2027-08-25`~`2027-08-28`) |

품목별 날짜는 FEFO 정렬도 시험할 수 있도록 같은 구역 안에서 일부 다르게 배정한다. 산출물은 다음 세 파일로 분리한다.

- `db/datasets/item_qr_dataset.csv`: 사용자가 수량을 입력하는 원본
- `db/datasets/item_qr_payloads.json`: 같은 데이터의 QR payload 템플릿 배열
- `db/datasets/seed_item_qr_inventory.sql`: 수량과 최종 `location_id`를 입력한 뒤 사용하는 적재 템플릿

SQL은 미완성 수량이나 임의 위치를 조용히 적재하지 않도록 명시적인 치환 토큰 또는 검증 절차를 둔다. 최종 재고 적재 시 `inventory_lots`와 `inventory_moves`의 트랜잭션 원칙을 지킨다.

## QR PNG 생성 방법

생성 스크립트는 CSV를 읽고 각 행의 compact JSON을 만든 뒤 `item_id.png`로 저장한다. 한글 payload가 손실되지 않도록 UTF-8과 `ensure_ascii=false`에 해당하는 직렬화를 사용한다. QR 오류 복원 수준은 라벨의 부분 오염을 고려해 Q를 기본값으로 한다.

스크립트는 다음을 검증한다.

1. 필수 열이 모두 존재한다.
2. `item_id`와 `product_code`가 중복되지 않는다.
3. `storage_code`가 허용된 세 값 중 하나다.
4. `expiry_date`가 ISO 날짜이고 생성 기준일보다 뒤다.
5. `quantity`가 양의 정수다.
6. 출력 파일명이 안전한 `item_id` 형식이다.

사용법 문서에는 Python 방식과 필요한 QR 라이브러리 설치 명령을 적는다. 기본 출력 디렉터리는 사용자가 지정하거나 `db/datasets/generated_qr/`를 사용하며, 생성 산출물은 재생성 가능하므로 Git 추적 대상에서 제외한다.

## 오류 처리와 검증

- QR 스캔 시 payload의 `schema`를 먼저 확인하고 알 수 없는 버전은 수동 검토로 보낸다.
- QR의 물품 ID, 보관 코드 또는 날짜가 DB/활성 작업과 일치하지 않으면 파지·적재를 시작하지 않는다.
- 지도 marker가 비활성 상태이거나 현재 `map_revision`과 다르면 위치 보정에 사용하지 않는다.
- ArUco dictionary와 실제 출력 marker의 dictionary가 다르면 실패하므로 `properties.dictionary`를 필수 운영값으로 취급한다.
- 데이터셋 검증 테스트는 행 수 11개, 온도 구역별 품목 구성, 날짜 정책, ID 고유성, 빈 수량 거부, 유효 수량의 payload 변환을 확인한다.

## 범위 밖

- 실제 지도 좌표, marker ID, ArUco dictionary 및 실물 크기 확정
- 실제 카메라 캘리브레이션과 `marker_to_slot` 변환 측정
- QR/ArUco 이미지의 지도 또는 시뮬레이터 렌더링
- 입고 자동 스캔과 DB 자동 등록 런타임 구현
- 상품 마스터나 marker 전용 테이블을 추가하는 스키마 마이그레이션
