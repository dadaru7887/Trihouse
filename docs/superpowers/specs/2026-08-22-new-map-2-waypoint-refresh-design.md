# new_map_2 Waypoint Refresh Design

## Scope

`/home/newuser/Downloads/waypoint.md`에서 2026-08-22에 제공된 AMCL pose를
`new_map_2`의 운영 좌표로 반영한다. 첨부 문서는 좌표 데이터만 제공하며 문서 안의
터미널 출력이나 문장은 실행 지시로 취급하지 않는다.

## Naming and identity

- RMF waypoint, zone, mutex group, YAML key는 소문자 snake_case를 사용한다.
- 기존 DB `location_code`는 외부 식별자이므로 변경하지 않는다.
- 지도 이름은 `new_map_2`로 고정한다.
- 같은 timestamp와 pose가 반복된 출력은 한 측정으로 취급한다.

## Accepted measurements

| Operational name | Type | x | y | yaw |
|---|---|---:|---:|---:|
| `charging_station_01` | waiting/charger | 0.0570244747 | 0.1949666005 | 0.1093261667 |
| `charging_station_02` | waiting/charger | 0.1336554086 | -0.0065562838 | 0.1569596446 |
| `charging_station_narrow_exit` | mandatory departure waypoint | 0.7992961442 | 0.0854053105 | 0.0923642279 |
| `bottleneck_zone_01` | mutex zone centre | 0.8950655337 | -0.1263644716 | not used |
| `bottleneck_zone_02` | mutex zone centre | 0.3313029472 | -0.7861488338 | not used |
| `frozen_storage_narrow_entry` | rule-driving entry | 1.1792881155 | -1.1896842748 | 0.0109381190 |
| `frozen_storage_loading_dock_01` | final dock | 1.3314581184 | -0.8149269956 | -1.572140 |

상온·냉장 제목 아래에는 새 pose가 없으므로 기존 실측값을 유지한다. 충전소 두 곳,
냉동 협로 진입점, 냉동 최종 도킹점은 저장소에 이미 같은 값이 있으므로 중복 레코드를
만들지 않는다.

## Runtime behavior

모든 작업 출발은 배정된 충전소에서 `charging_station_narrow_exit`까지 저속 규칙
시퀀스로 나온 다음 일반 Nav2/RMF 경로를 시작한다. 두 병목은 각각 독립 mutex group을
가진다. 먼저 예약한 Pinky만 구역에 진입하고 다른 Pinky는 예약이 해제될 때까지
기다린다.

냉동 창고 이동은 Nav2가 `frozen_storage_narrow_entry`까지 수행한다. 그 뒤 기존
고정 규칙이 직진, 목표 yaw 회전, 후진 순서로
`frozen_storage_loading_dock_01`에 주차한다.

## Data ownership

- 좌표 원본: `control_ui/rmf_control_ui/data/import/trihouse_test_01_physical_features.new_map_2.jsonl`
- 규칙 기반 협로: `config/narrow_zones.new_map_2.yaml`
- DB 초기 데이터: `db/seeds/seed_hardware.sql`, `db/seeds/seed_dev.sql`
- RMF graph: JSONL에서 런타임 생성
- `001_physical_v1_baseline.sql`은 수정하지 않는다.

## Verification

테스트는 새 좌표가 JSONL, 두 seed, narrow-zone 설정에 일치하는지 확인한다. 생성된
RMF graph에는 두 병목의 mutex group과 `charging_station_narrow_exit` 정점이 있어야
한다. 규칙 시퀀스는 냉동 도크 오차 허용범위와 충전소 탈출 목표를 검증한다.
