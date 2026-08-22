# Control System UI and Map Data Layout Design

## Goal

웹 관제 UI의 정본을 `control_system/`으로 통일하고, 지도 운영 데이터가 UI 소스에
종속되지 않도록 분리한다. 기존 `control_ui/` 디렉터리는 제거한다.

## Canonical layout

```text
control_system/                         # 웹 관제 UI 정본 submodule
data/map_authoring/import/              # waypoint·zone JSONL 정본
pinky_pro_alpha/pinky_navigation/map/   # Nav2 occupancy map 정본
```

`new_map_2.yaml`과 `new_map_2.pgm`은
`pinky_pro_alpha/pinky_navigation/map/`에서만 읽는다. 지도 발행 스크립트는
`data/map_authoring/import/trihouse_test_01_physical_features.new_map_2.jsonl`을
같은 운영 지도의 waypoint·feature 입력으로 사용한다.

## Web control boundary

`compose.control.yaml`의 기존 `control_ui` 서비스와 포트 3100 구성을 제거한다.
시뮬레이션 웹 관제는 `compose.simulation.yaml`의 `rmf_dashboard` 서비스를 사용하며,
빌드 소스는 `control_system/openrmf/docker/rmf-web-dashboard`이다. Gateway 주문 API와
MySQL 작업 처리는 웹 UI와 독립적으로 유지되므로 UI를 열지 않아도 터미널의
`POST /api/v1/orders` 요청으로 주문을 생성할 수 있다.

`control_system/`은 외부 정본 submodule이므로 이번 변경에서 내부 소스를 수정하지
않는다. 새 worktree나 새 PC에서는 Compose 실행 전에 해당 submodule을 초기화해야 한다.

## Path migration

다음 두 JSONL을 `data/map_authoring/import/`로 이동한다.

- `trihouse_test_01_physical_features.jsonl`
- `trihouse_test_01_physical_features.new_map_2.jsonl`

지도 발행 및 시뮬레이션 스크립트는 새 데이터 경로와
`pinky_pro_alpha/pinky_navigation/map/`만 참조하도록 변경한다.

- `scripts/p0_publish_map.py`
- `scripts/p0_reset.sh`
- `scripts/p0_up.sh`
- `control_tower/bringup/p0_simulation_bringup.sh`

테스트와 운영 문서의 실행 경로도 함께 갱신한다. 실행 코드와 테스트에서
`control_ui/` 참조가 하나라도 남으면 구조 변경을 완료로 판정하지 않는다.

## Deletion policy

새 경로의 파일 내용과 테스트가 확인된 뒤 기존 `control_ui/` 전체를 삭제한다.
삭제 전에 새 JSONL의 레코드 수, 운영 map 이름, 실측 좌표를 검증하여 waypoint 정보가
손실되지 않도록 한다. Git으로 추적된 파일이므로 삭제 내역은 feature branch에서
검토하고 main 통합 전까지 복구 가능하다.

## Runtime flow after migration

```text
pinky_pro_alpha new_map_2.yaml/.pgm
        +
data/map_authoring/import/*.jsonl
        ↓
scripts/p0_reset.sh → Gateway map publication → MySQL map_revisions
        ↓
scripts/p0_up.sh → Nav2/RMF simulation

terminal curl → Gateway /api/v1/orders → MySQL jobs/job_items/job_steps

control_system RMF dashboard → 선택적 웹 관측
```

웹 관제 실행 여부는 지도 발행, 주문 저장, JobRunner 처리의 선행 조건이 아니다.

## Verification

1. 새 JSONL 경로에서 15개 레코드와 `target_map_name=new_map_2`를 확인한다.
2. `p0_publish_map.py`가 `pinky_pro_alpha` 지도와 새 JSONL만 선택하는지 테스트한다.
3. `p0_reset.sh`가 `new_map_2:*` revision을 발행하는지 확인한다.
4. Compose 병합 설정에 기존 `control_ui` 서비스와 포트 3100이 없는지 확인한다.
5. `control_system` 기반 `rmf_dashboard` 서비스가 설정에 남아 있는지 확인한다.
6. 추적 파일과 실행 코드에서 `control_ui/` 참조가 없는지 확인한다.
7. 관련 Python·DB·셸 테스트를 실행한다.
8. `p0_up.sh`의 Nav2 lifecycle과 LiDAR 판정을 별도로 통과시킨다.

## Non-goals

- `control_system/` submodule 내부 코드 수정
- Gateway 주문·DB 스키마 변경
- OMX 또는 Pinky 실물 통신 계약 변경
- 웹 UI가 없을 때 별도의 터미널 주문 API 추가
