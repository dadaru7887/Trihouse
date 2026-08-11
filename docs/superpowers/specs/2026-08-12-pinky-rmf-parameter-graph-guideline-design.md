# 실제 Pinky RMF 파라미터·Graph 가이드라인 재구성 설계

## 1. 목표

현재 office demo 기준으로 구현된 `trihouse_rmf_bridge`를 실제 Pinky와 Trihouse 지도에 연결할 때 필요한 측정, graph 제작, 설정 반영, 검증 절차를 문서화한다.

문서의 핵심 안전 규칙은 다음과 같다.

- office demo 값은 실제 Pinky 설정값이 아니라 `초기 참고값`으로만 표시한다.
- 측정하지 않은 실제 Pinky 값은 숫자를 추정하지 않고 `미측정`으로 표시한다.
- 설정 반영 전에는 측정 근거와 검증 결과를 남긴다.
- `pinky_pro`, `control_system`, `/home/syw/rmf_ws`는 수정하지 않는다.

## 2. 문서 책임

### `docs/guideline/parameters_for_rmf.md`

실제 Pinky의 차량, 배터리, 작업시간 파라미터를 어떻게 측정하고 RMF bridge 설정에 반영할지 설명한다.

포함할 내용은 다음과 같다.

- 값의 상태 체계
- office 참고값과 실제 Pinky 값 비교표
- POC에 반드시 필요한 최소 파라미터
- 항목별 측정 방법, 반복 횟수, 원본 증거
- 측정 결과 기록표
- `office_bridge.yaml` 필드와 실제 Pinky 설정의 대응
- 배터리·ETA 모델 보정 순서와 적용 승인 기준
- Open-RMF가 계산해 주는 값과 사용자가 직접 측정해야 하는 값의 구분

### `docs/guideline/waypoint.md`

SLAM 지도를 RMF navigation graph와 연결하고 실제 Pinky waypoint와 lane을 검증하는 절차를 설명한다.

포함할 내용은 다음과 같다.

- occupancy map과 RMF graph의 역할 차이
- 현재 지도 자산의 용도와 사용 전 확인 사항
- map/level 이름과 좌표계 정합 절차
- 필수 waypoint·lane 명명과 속성
- 좌표, 접근 yaw, 위치·방향 허용오차 측정표
- Traffic Editor 등록과 graph export 절차
- bridge의 graph/fleet/robot 설정 교체 지점
- `/fleet_states` pose와 graph start 결합 검증
- 필수 경로와 실패 코드 확인 절차

### `docs/guideline/open_rmf_energy_bridge_test.md`

office 검증 문서의 책임은 유지한다. 실제 Pinky 전환은 위 두 문서를 먼저 완료해야 한다는 링크와 단계만 추가한다.

## 3. 값 상태 계약

모든 실제 적용값은 다음 상태 중 하나를 가진다.

| 상태 | 의미 | 실제 설정 반영 |
|---|---|---|
| `미측정` | 실제 Pinky에서 아직 측정하지 않음 | 금지 |
| `초기 참고값` | office demo 또는 제조사 자료에서 가져온 비교용 값 | 실제 적용 금지 |
| `측정 완료` | 측정일, 조건, 원본 로그가 있는 값 | 제한된 시험 설정에 반영 가능 |
| `검증 완료` | 반복 시험과 POC 허용 기준을 통과한 값 | POC 운영 설정에 반영 가능 |

`미측정`은 단순한 빈칸이 아니다. 해당 값이 준비되지 않았으므로 실제 Pinky RMF 설정을 확정하면 안 된다는 차단 표시다.

## 4. 파라미터 측정 범위

POC에서 반드시 측정하거나 근거를 확보해야 하는 최소 범위는 다음과 같다.

- 선속도·선가속도 제한
- 각속도·각가속도 제한
- footprint·vicinity 반경
- nominal voltage, usable capacity, charging current
- 기본 질량과 POC 최대 적재 질량
- ambient power
- 관성모멘트와 마찰계수의 초기 근거 및 왕복 실험 보정값
- 적재·인계 시간과 고정 buffer
- 실제 이동시간, 시작 SOC, 종료 SOC

저온 보정과 OMX tool power는 현재 POC 범위에서 제외한다. 단, 제외 상태를 표에 명시해 나중에 실제 냉동 환경으로 전환할 때 누락으로 오인하지 않게 한다.

## 5. Graph 연결 범위

Graph 제작은 다음 순서를 따른다.

1. SLAM occupancy map 파일의 형식, resolution, origin, image 경로를 확인한다.
2. RMF level 이름과 Pinky `/fleet_states.location.level_name`을 동일하게 결정한다.
3. 서로 멀리 떨어진 기준점 4개 이상으로 Nav2 map과 RMF 좌표 정합을 확인한다.
4. 필수 작업·대기·충전 waypoint의 실제 정차 pose를 반복 측정한다.
5. Traffic Editor에 waypoint, lane, holding, charger 속성을 등록하고 nav graph를 export한다.
6. 실제 Pinky pose가 `compute_plan_starts`에 결합되는지 확인한다.
7. 냉동↔포장 양방향, 각 작업점→안전대기점, 각 작업점→충전소 경로를 검증한다.

현재 알려진 지도 파일은 후보 입력 자산으로만 기록한다.

- `/home/syw/Desktop/final_map_08.yaml`
- `/home/syw/Desktop/final_map_08.pgm`
- `/home/syw/Trihouse/control_system/rmf_maps/robosapiens.png`

`robosapiens.png`는 관제 UI 표시용 이미지이며 좌표가 정합된 RMF graph의 근거로 간주하지 않는다. `control_system` 파일은 수정하지 않는다.

## 6. 설정 반영 경계

현재 `trihouse_rmf_bridge/config/office_bridge.yaml`은 office demo 검증용으로 유지한다. 실제 Pinky 연결 시 별도의 Pinky 설정과 launch를 만드는 것을 후속 구현 원칙으로 문서화한다.

교체 대상은 다음과 같다.

- `fleet_name`
- `robot_name`
- `nav_graph_file`
- 속도·가속도·footprint·vicinity
- 배터리·기계·ambient 파라미터

서비스 계약 `/trihouse/rmf/estimate_task_energy`와 `/fleet_states` 입력 계약은 유지한다.

## 7. 검증과 완료 기준

문서상 실제 Pinky 연결 준비 완료는 다음 조건을 모두 만족할 때만 선언한다.

- 필수 파라미터가 모두 `측정 완료` 이상이다.
- 핵심 waypoint의 pose와 허용오차가 `검증 완료`다.
- 실제 Pinky가 설정된 fleet/robot 이름으로 `/fleet_states`에 나타난다.
- 실제 pose에서 graph start 결합이 성공한다.
- 필수 경로의 `EstimateTaskEnergy.success`가 모두 true다.
- 예측 이동시간과 실제 이동시간의 오차를 기록했다.
- 예측 종료 SOC와 실제 종료 SOC의 오차를 기록했다.
- office 초기 참고값이 실제 Pinky 설정에 남아 있지 않음을 검토했다.

POC 허용 오차의 숫자는 측정 전 임의로 확정하지 않는다. 5회 이상 반복 실험 결과를 얻은 후 운영팀이 허용 기준을 승인하고 `검증 완료`로 전환한다.
