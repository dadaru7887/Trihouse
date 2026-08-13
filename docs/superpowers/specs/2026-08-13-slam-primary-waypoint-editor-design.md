# SLAM 기반 Waypoint 편집기 설계

작성일: 2026-08-13  
대상: `/home/syw/Trihouse/control_system_test/rmf_control_ui`  
보호 대상: `control_system`, `pinky_pro` 수정 금지

## 1. 목적

새 맵 프로젝트의 기본 입력을 수동 축척 도면이 아니라 Nav2 `map_saver`가 만든
SLAM 지도 쌍(`map.yaml` + `map.pgm/png`)으로 바꾼다. 사용자는 실제 점유격자
위에서 Lane과 Waypoint를 직접 배치한다. UI는 YAML의 `resolution`과 `origin`을
이용해 클릭 위치를 ROS `map` 좌표로 자동 변환하고 FMS Gateway를 통해 canonical
map draft에 저장한다.

동시에 Waypoint 추가·수정 화면을 다음 운영 역할 계약으로 통일한다.

- Loading Dock
- Waiting Point
- Safety Zone
- Charging Station
- Parking Spot
- Transit Waypoint
- Inspection Point
- Workcell Station

기존 Floorplan 프로젝트는 호환 모드로 계속 열 수 있지만, 새 프로젝트 생성 시
기본 선택은 `SLAM Map`이다.

## 2. 확인된 현재 단절

1. SLAM YAML/이미지 파서와 로컬 저장 코드는 존재한다.
2. SLAM 지도는 현재 그리드맵 비교·원점 보정의 보조 자료다.
3. Waypoint 편집 화면은 Floorplan 픽셀과 Measurement의 `m/px`를 기준으로 한다.
4. `waypoint_operational_role.dart`에 canonical 역할 정의가 있지만 `main.dart`의
   Waypoint 추가·수정 화면과 편집 상태에는 연결되지 않았다.
5. 실제 화면에는 `대기/주차/홈/충전/픽업/드랍오프/설비`만 나타난다.
6. 따라서 역할 모델 단위 테스트가 통과해도 실제 UI와 Gateway payload는 기존
   category 계약을 계속 사용한다.

## 3. 선택한 접근

### 3.1 기본 모드

```text
새 프로젝트
  ├─ SLAM Map (기본)
  │    ├─ map.yaml 선택
  │    ├─ YAML image 경로의 PGM/PNG 자동 로드
  │    ├─ resolution/origin 자동 적용
  │    └─ Measurement 불필요
  └─ Floorplan (호환)
       ├─ PNG/JPG/PDF 업로드
       └─ Measurement로 축척 지정
```

이번 범위에서는 Floorplan과 SLAM을 반투명하게 겹쳐 수동 정합하는 기능은 넣지
않는다. SLAM이 주 편집 배경이고 ROS `map` 프레임이 좌표의 기준이다.

### 3.2 비목표

- SLAM 실행 또는 `map_saver_cli` 호출
- 센서 원본으로 점유격자 생성
- Gateway Publish 및 운영 `locations` projection 연결
- Gazebo/RMF 전체 실행
- `control_system` 또는 `pinky_pro` 변경

## 4. 컴포넌트 경계

### 4.1 `SlamMapSource`

SLAM 지도 원본과 좌표 변환에 필요한 불변 메타데이터를 가진다.

```text
type              slam
yamlFileName      warehouse.yaml
imageFileName     warehouse.pgm
width             image cell width
height            image cell height
resolution        meter per cell
origin            [x, y, yaw]
yamlSha256        source identity
imageSha256       source identity
```

Linux Desktop에서는 YAML의 상대 `image` 경로를 기준으로 같은 디렉터리의
이미지를 자동으로 읽는다. 경로를 찾지 못한 경우에는 사용자가 해당 PGM/PNG를
명시적으로 선택하게 한다. YAML에 지정된 이미지와 선택한 이미지 이름이 다르거나,
resolution이 0 이하이거나, origin을 읽지 못하거나, 지원하지 않는 이미지이면
프로젝트 생성을 거절한다. 오류가 있는 값을 0으로 대체하지 않는다.

### 4.2 좌표 변환기

편집 화면 좌표는 이미지의 왼쪽 위를 `(0, 0)`으로 하는 연속 좌표다. ROS map
원점은 이미지의 왼쪽 아래에 놓인 pose다. 이미지 높이를 `H`, 해상도를 `r`,
YAML origin을 `(ox, oy, θ)`라고 할 때 다음을 사용한다.

```text
local_x = image_x * r
local_y = (H - image_y) * r

map_x = ox + cos(θ) * local_x - sin(θ) * local_y
map_y = oy + sin(θ) * local_x + cos(θ) * local_y
```

역변환:

```text
dx = map_x - ox
dy = map_y - oy

local_x =  cos(θ) * dx + sin(θ) * dy
local_y = -sin(θ) * dx + cos(θ) * dy

image_x = local_x / r
image_y = H - local_y / r
```

점유격자 cell 중심을 선택하는 기능은 `(column + 0.5, row + 0.5)`를 입력으로
사용한다. 일반 Waypoint 클릭은 연속 좌표를 보존해 불필요한 cell-center 강제
반올림을 하지 않는다.

Waypoint의 로컬 진행각을 편집하게 되면 `map_yaw = normalize(origin_yaw +
local_yaw)`로 저장한다.

### 4.3 편집 상태

프로젝트는 `mapSourceMode = slam | floorplan`을 가진다.

- `slam`: YAML resolution/origin이 유일한 좌표 기준이며 Measurement를 요구하지
  않는다.
- `floorplan`: 기존 Measurement를 사용한다.

Waypoint별 편집 상태는 다음을 한 묶음으로 관리한다.

```text
waypointUuid
displayName
rmfWaypointName
operationalRole
category
locationCode
parentLocationCode
temperatureZone
imagePoint
mapPose [x, y, yaw]
```

표시 이름을 바꿔도 `waypointUuid`, `rmfWaypointName`, `locationCode`는 유지한다.
역할 또는 Parent Facility를 바꾸면 Lane 참조용 `waypointUuid`는 유지하고,
`rmfWaypointName`과 `locationCode`만 새 역할/Parent의 monotonic sequence로 다시
발급한다.

## 5. Waypoint UI 계약

### 5.1 추가와 수정 화면

Waypoint 추가와 수정은 동일한 form model을 사용한다. 별도의 legacy category
dropdown을 두지 않는다.

| Operational Role | category | Parent Facility | location projection |
|---|---|---|---|
| Loading Dock | `holding` | 필수 | `loading_dock` |
| Waiting Point (`bottleneck_waiting_point`) | `holding` | 필수 | `staging` |
| Safety Zone | `holding` | 불필요 | `safe_node` |
| Charging Station | `charger` | 불필요 | `charger` |
| Parking Spot | `parking` | 불필요 | `staging` |
| Transit Waypoint | `waypoint` | 불필요 | 생성하지 않음 |
| Inspection Point | `holding` | 선택 | `staging` |
| Workcell Station | `equipment` | 선택 | `workstation` |

Parent Facility 선택지:

| Facility | code | temperature |
|---|---|---|
| Ambient Storage | `WH-AMB-01` | `ambient` |
| Chilled Storage | `WH-CHL-01` | `chilled` |
| Frozen Storage | `WH-FRZ-01` | `frozen` |
| Packing Station | `PACKING-01` | `ambient` |

### 5.2 Stable identity

Chilled Storage의 첫 Loading Dock 예시:

```text
displayName         Chilled Storage Loading Dock 01
rmfWaypointName     chilled_storage_loading_dock_01
locationCode        WH-CHL-01-DOCK-01
operationalRole     loading_dock
category            holding
parentLocationCode  WH-CHL-01
temperatureZone     chilled
```

번호는 역할과 Parent Facility 단위의 monotonic counter로 관리한다. 삭제한 번호를
자동 재사용하지 않는다.

## 6. 원본과 DB 저장

UI는 MySQL에 직접 연결하지 않는다.

```text
UI
  → PUT /internal/v1/map-projects/{map_name}
  → FMS Gateway
  → map_projects / map_project_waypoints / map_project_lanes
```

SLAM source metadata는 `map_projects.payload.mapSource`에 저장한다. 원본 지도
이미지는 기존 `payload.drawing.bytes`에 base64로 담아 Gateway가
`map_projects.drawing_bytes`에 projection하게 한다. 원본 YAML은
`map_project_files`에 `kind=nav2_map_yaml`인 text file로 저장한다. 이미지
바이트를 `map_project_files.content`에 다시 넣어 중복 보관하지 않는다. DB에서
프로젝트를 다시 열 때 `drawing_bytes`, YAML, `mapSource`를 함께 사용해 동일한
SLAM 편집 배경과 좌표계를 복원한다.

`map_project_waypoints.map_x/map_y/map_yaw`는 YAML resolution/origin으로 계산한
값이다. 사용자가 Measurement 값을 입력해 덮어쓸 수 없다.

프로젝트 저장은 전체 aggregate와 `If-Match: draft_revision`을 사용해 다른 편집
세션의 변경을 조용히 덮지 않는다.

## 7. 호환과 migration

- `mapSource`가 없는 기존 프로젝트는 `floorplan`으로 해석한다.
- 한글 legacy category는 로드 시 canonical 역할로 변환한다.
- `픽업`과 `드랍오프`는 모두 `loading_dock`으로 변환한다.
- Parent Facility를 알 수 없는 legacy Loading Dock는 자동 추측하지 않고 UI에
  `Parent Facility required`로 표시하며 저장을 막는다.
- 기존 Waypoint UUID와 RMF 이름은 가능한 한 보존한다.
- SLAM 프로젝트는 Measurement 누락 경고를 내지 않는다.

## 8. 검증과 오류 처리

### 8.1 단위 테스트

- YAML의 image/resolution/origin 파싱
- PGM과 PNG 로드
- origin yaw 0에서 pixel → map 변환
- origin yaw가 0이 아닐 때 pixel → map 변환
- map → pixel 역변환 왕복 오차
- 이미지 경계와 cell center 변환
- 모든 operational role 노출
- Loading Dock/Waiting Point의 Parent Facility 필수성
- 역할별 category, location code, temperature mapping
- rename 시 stable identity 유지
- 역할/parent 변경 시 새 identity 발급

### 8.2 Widget/계약 테스트

- 새 프로젝트 기본 선택이 `SLAM Map`
- YAML 선택 후 Measurement 없이 Lane/Waypoint 단계 진입
- 추가와 수정 화면이 legacy category를 노출하지 않음
- 저장 payload에 `mapSource`와 모든 Waypoint 운영 필드 포함
- Gateway에서 재조회 후 같은 위치와 역할로 복원
- Floorplan legacy 프로젝트가 계속 열림

### 8.3 수동 Gate

1. 실제 `map.yaml + map.pgm/png` 업로드
2. 지도 벽과 통로가 정상 방향으로 보이는지 확인
3. Chilled Storage Waiting Point와 Loading Dock 배치
4. 프로젝트 저장
5. Gateway GET으로 `payload.mapSource`와 Waypoint 확인
6. MySQL에서 `map_project_waypoints.map_x/map_y/map_yaw` 확인
7. UI 재시작 후 DB 프로젝트를 열어 같은 픽셀에 표시되는지 확인

## 9. 구현 순서

1. SLAM pixel/map 좌표 변환기를 테스트 우선으로 추가
2. `mapSourceMode`와 SLAM source serialization 추가
3. 새 프로젝트 dialog의 기본 모드를 SLAM으로 변경
4. SLAM image를 Map editor canvas 배경으로 연결
5. Waypoint 추가·수정 form을 canonical 역할로 교체
6. 운영 metadata와 stable counter를 undo/save/load에 연결
7. Gateway aggregate에 SLAM 원본 파일과 payload 저장
8. 집중 Flutter 테스트와 수동 DB 저장 Gate 수행

## 10. 완료 조건

- 새 프로젝트 생성 시 SLAM Map이 기본이다.
- Measurement 없이 실제 SLAM 이미지 위에서 Waypoint를 찍을 수 있다.
- UI 추가·수정 화면의 역할이 운영 역할 표와 일치한다.
- 클릭 위치가 YAML resolution/origin을 반영한 정확한 `mapPose`로 저장된다.
- 프로젝트 재조회·재실행 후 위치와 stable identity가 유지된다.
- `control_system`과 `pinky_pro`에는 변경이 없다.
