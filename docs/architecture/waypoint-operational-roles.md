# Canonical Warehouse Location and Waypoint Roles

이 문서는 Control System UI, FMS Gateway, Open-RMF와 `trihouse_fms`가 공유하는
영문 명칭과 저장 규칙이다. DB 값과 API 값은 영어로만 저장한다.

## 1. Single source and data flow

```text
Control System UI
  → FMS Gateway map-project draft API
  → validate / publish
  → trihouse_fms map authoring + operational projection
  → published nav graph
  → Open-RMF fleet scheduling
  → Nav2 physical movement
```

- 기준 스키마: `/home/syw/Trihouse/db/migrations/001_physical_v1_baseline.sql`
- 기준 DB: `trihouse_fms`
- UI는 MySQL에 직접 연결하지 않고 `FMS_GATEWAY_URL`만 사용한다.
- `control_system_test/db`는 upstream 참고 자료이며 실행 DB가 아니다.
- `map_projects`와 `map_project_waypoints`는 편집 원본이다.
- 검증된 revision을 publish할 때만 `locations`와 `map_features`를 갱신한다.
- Transit Waypoint는 RMF graph 전용이므로 `locations`에 만들지 않는다.

## 2. Canonical table

| Kind | UI label | `operational_role` | RMF category | `locations.location_type` | Temperature | Parent / code example | Meaning |
|---|---|---|---|---|---|---|---|
| Logical facility | Ambient Storage | — | — | `rack` | `ambient` | `WH-AMB-01` | 상온 창고. Dock/Waiting Point의 부모 시설이다. |
| Logical facility | Chilled Storage | — | — | `rack` | `chilled` | `WH-CHL-01` | 냉장 창고. Dock/Waiting Point의 부모 시설이다. |
| Logical facility | Frozen Storage | — | — | `rack` | `frozen` | `WH-FRZ-01` | 냉동 창고. Dock/Waiting Point의 부모 시설이다. |
| Logical facility | Packing Station | — | — | `workstation` | `ambient` | `PACKING-01` | 입고와 출고에 공통으로 사용하는 포장 시설이다. |
| Operational waypoint | Loading Dock | `loading_dock` | `holding` | `loading_dock` | parent 상속 | `WH-CHL-01-DOCK-01`, `PACKING-01-DOCK-01` | Pinky가 적재·하역을 위해 정확히 정차하는 방향 중립 지점이다. 입고/출고 Dock을 나누지 않는다. |
| Operational waypoint | Waiting Point | `bottleneck_waiting_point` | `holding` | `staging` | parent 상속 | `WH-CHL-01-WAIT-01` | 협로 진입 전에 반드시 정지하여 RMF mutex와 ArUco 허가를 기다리는 지점이다. |
| Operational waypoint | Safety Zone | `safety_zone` | `holding` | `safe_node` | — | `PROJECT1-SAFETY-01` | 위험·혼잡·복구 시 사용하는 안전 대기 지점이다. |
| Operational waypoint | Charging Station | `charging_station` | `charger` | `charger` | — | `PROJECT1-CHG-01` | 충전 목적지다. 장기 주차만 하는 지점과 구분한다. |
| Operational waypoint | Parking Spot | `parking_spot` | `parking` | `staging` | — | `PROJECT1-PARK-01` | 비충전 장기 대기·복귀 지점이다. |
| Graph-only waypoint | Transit Waypoint | `transit_waypoint` | `waypoint` | DB projection 없음 | — | `transit_01` | 경로 형상, 회전, Lane 분기를 위한 Open-RMF vertex다. 작업 목적지로 사용하지 않는다. |
| Operational waypoint | Inspection Point | `inspection_point` | `holding` | `staging` | — | `PROJECT1-INSPECT-01` | Vision, barcode 또는 작업자 확인을 위한 정지 지점이다. |
| Operational waypoint | Workcell Station | `workcell_station` | `equipment` | `workstation` | — | `PROJECT1-WORKCELL-01` | OMX, 로봇팔, 컨베이어 설비 좌표다. 이동 Lane에 연결하지 않는다. |
| Spatial feature | Bottleneck Zone | — | Lane mutex | `map_features`에 Point | — | `PROJECT1-BOTTLENECK-01` | 중심과 반경으로 협로 진입을 감지한다. 목적 Waypoint가 아니다. |

`Ambient Storage`, `Chilled Storage`, `Frozen Storage`, `Packing Station`은
Waypoint 선택지가 아니라 `Loading Dock`과 `Waiting Point`를 만들 때 고르는
`Parent Facility`다. 따라서 시설마다 번호가 독립적으로 증가한다.

```text
WH-CHL-01 (Chilled Storage)
├─ WH-CHL-01-WAIT-01 / chilled_storage_waiting_point_01
├─ WH-CHL-01-DOCK-01 / chilled_storage_loading_dock_01
└─ WH-CHL-01-DOCK-02 / chilled_storage_loading_dock_02

PACKING-01 (Packing Station)
└─ PACKING-01-DOCK-01 / packing_station_loading_dock_01
```

## 3. Why the relational columns are required

| Column | Example | Purpose |
|---|---|---|
| `operational_role` | `loading_dock` | RMF graph category만으로 알 수 없는 업무 의미를 저장한다. |
| `temperature_zone` | `chilled` | 로봇·화물의 온도 구역 적합성을 배차 전에 검사한다. Dock/Waiting Point는 parent에서 상속한다. |
| `parent_location_code` | `WH-CHL-01` | 여러 Dock/Waiting Point를 같은 논리 시설에 묶고 표시명 변경과 무관한 관계를 유지한다. |

`parent_location_code`는 편집 draft의 `map_project_waypoints` 컬럼이다. Publish 후
운영 projection인 `locations`에서는 문자열을 중복 저장하지 않고
`parent_location_id` 외래키로 바꾼다. 운영 조회에서 부모 코드를 표시할 때는
`locations`의 부모 행을 self join한다.

UI draft 예시:

```json
{
  "name": "Chilled Storage Loading Dock 02",
  "rmfWaypointName": "chilled_storage_loading_dock_02",
  "locationCode": "WH-CHL-01-DOCK-02",
  "operationalRole": "loading_dock",
  "category": "holding",
  "temperatureZone": "chilled",
  "parentLocationCode": "WH-CHL-01",
  "mapPose": [2.4, -5.1, 1.570796]
}
```

Publish 후 `locations` 예시:

```text
location_code       = WH-CHL-01-DOCK-02
name                = Chilled Storage Loading Dock 02
location_type       = loading_dock
temperature_zone    = chilled
parent_location_id  = location_id(WH-CHL-01)
map_name             = project1
rmf_waypoint_name    = chilled_storage_loading_dock_02
pose_x/y/yaw         = 2.4 / -5.1 / 1.570796
```

## 4. Narrow-entrance policy

창고 입구의 권장 순서는 다음과 같다.

```text
Normal Lane
  → Waiting Point 도착 및 정지
  → FMS/RMF mutex lock 획득
  → OpenCV ArUco marker 확인
  → entry clearance 발급
  → Nav2 narrow-lane 진입
  → Loading Dock 도착
  → 적재/하역
  → 반대편 Waiting Point 또는 진입 Waiting Point로 퇴출
  → mutex lock 반환
```

`Waiting Point` 하나만 찍는 것으로 ArUco 진입 제어가 완성되지는 않는다.
`bottleneckZones`는 최소 다음 필드를 가져야 한다.

```json
{
  "featureCode": "PROJECT1-BOTTLENECK-01",
  "featureType": "bottleneck",
  "mapPose": [4.2, -1.3],
  "radiusM": 1.5,
  "mutexGroup": "chilled_entrance_01",
  "entryWaitingPoint": "WH-CHL-01-WAIT-01",
  "exitWaitingPoint": "WH-CHL-01-WAIT-02",
  "arucoMarkerId": 17
}
```

같은 `mutexGroup`을 협로 Lane에도 지정해야 한다. Gateway는 연결 Lane이 없거나
Waiting Point 역할이 잘못됐으면 validate/publish를 거절한다. OpenCV는 marker를
관측하고, FMS는 mutex·task context·marker 결과를 결합해 진입 허가를 내리며,
실제 속도와 경로 실행은 Nav2가 담당한다.

## 5. Job sequence example

```text
Outbound Job
├─ Step 10: Current Position → Chilled Storage Waiting Point 01
├─ Step 20: Acquire Mutex + Verify ArUco Entry
├─ Step 30: Waiting Point 01 → Chilled Storage Loading Dock 01
├─ Step 40: Load Cargo
├─ Step 50: Loading Dock → Packing Station Loading Dock 01
├─ Step 60: Unload Cargo
└─ Step 70: Parking Spot or Charging Station
```

입고 작업도 동일한 Loading Dock을 반대 방향의 Step에서 참조한다. 위치를
`inbound_dock`과 `outbound_dock`으로 복제하지 않는다.

## 6. Stable identity and numbering

- 표시명은 사용자가 바꿀 수 있다.
- `rmfWaypointName`과 `locationCode`는 rename으로 바꾸지 않는다.
- 역할 또는 parent 시설이 바뀌면 새 identity를 발급한다.
- 번호는 `operationalRoleCounters`에 저장하며 삭제된 번호를 재사용하지 않는다.
- parent가 필요한 역할은 `${role}:${parent_code}` 단위로 번호를 관리한다.
- 동시 편집은 `If-Match: <draft_revision>`으로 막는다.

## 7. Existing database migration

새 빈 volume은 `schema_mysql.sql`과 `seed_dev.sql`로 초기화한다. 기존 volume에는
백업 후 migration을 순서대로 적용한다. `011`은 `008`이 생성하는
`operational_role`, `temperature_zone`, `parent_location_code`를 사용하므로 반드시
`008`을 먼저 적용한다. 방향 중립 Dock/Waiting Point 계약은 `011`에 들어 있다.
`008`은 MySQL DDL의 자동 commit을 고려해 컬럼과 제약의 존재 여부를 확인한다.
따라서 과거 실행이 컬럼 추가 후 중단된 경우에도 같은 `008` 파일을 다시 실행해
category 변환과 제약 생성을 마칠 수 있다. 변환 전에 한글 category 전용 체크를
제거하고, 변환이 끝난 뒤 canonical English 체크를 다시 생성한다. 기존 한글 값은
`HEX(category)`로 판별하므로 실행한 MySQL client의 기본 문자셋에 의존하지 않는다.

```bash
cd /home/syw/Trihouse

docker compose -f compose.db.yaml exec -T mysql \
  sh -lc 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" trihouse_fms' \
  < db/archive/pre_physical_v1/008_add_waypoint_operational_roles.sql

docker compose -f compose.db.yaml exec -T mysql \
  sh -lc 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" trihouse_fms' \
  < db/archive/pre_physical_v1/011_unify_loading_dock_and_waiting_point.sql
```

Migration `011`을 먼저 실행해 중간에 실패했더라도 `008`을 적용한 뒤 `011`을
다시 실행하면 된다. `011`의 선행 구문은 upsert와 동일 값 갱신으로 구성되어
재실행할 수 있다. Migration `011`은 기존 `inbound_dock`과 `outbound_dock`을 `loading_dock`으로
통합하고, 과거 storage access 및 packing handover 역할을 `loading_dock`으로
정규화한다. 기존 volume에는 자동 init이 다시 실행되지 않으므로 위 migration을
명시적으로 적용해야 한다.

## 8. UI and Gateway startup

터미널 1 — MySQL:

```bash
cd /home/syw/Trihouse
docker compose -f compose.db.yaml up -d mysql
```

터미널 2 — FMS Gateway:

```bash
cd /home/syw/Trihouse
python3 -m uvicorn fms_gateway.app.main:create_app \
  --factory --host 127.0.0.1 --port 8080
```

터미널 3 — UI:

```bash
cd /home/syw/Trihouse/control_system_test/rmf_control_ui
RMF_ROOT=/home/syw/Trihouse/control_system_test \
RMF_WS=/home/syw/rmf_ws \
FMS_GATEWAY_URL=http://127.0.0.1:8080 \
flutter run -d linux
```

UI의 Waypoint 추가/수정 화면에서 `Operational Role`을 고른다. Loading Dock 또는
Waiting Point를 고르면 `Parent Facility`가 추가로 나타난다. 저장된 draft는
Gateway가 UUID/category/관계를 정규화하여 canonical schema에 원자적으로 쓴다.
