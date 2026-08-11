# 실제 Pinky Open-RMF Waypoint·Graph 연결 가이드

## 1. occupancy map과 RMF graph의 역할

| 자산 | 역할 | 포함 정보 | 직접 대체할 수 없는 것 |
|---|---|---|---|
| Nav2 occupancy map | Pinky 위치추정과 장애물 기반 주행 | image, resolution, origin, 점유 임계값 | RMF waypoint·lane·holding·charger 의미 |
| RMF building map | 층·도면과 Traffic Editor 편집 정보 | level, 이미지, 좌표 변환, graph 편집 원본 | Nav2 localization 설정 |
| RMF navigation graph | fleet adapter의 경로 계획 | waypoint 이름·좌표, lane, charger, holding | 실제 모터 제어와 장애물 회피 |
| 관제 UI 배경 이미지 | 운영자에게 시설을 시각화 | 그림·레이블 | 좌표 정합 또는 주행 가능성 근거 |

SLAM map 이미지를 RMF 화면에 넣는 것만으로 graph가 생기지 않는다. 실제 Pinky pose와 같은 좌표계에 waypoint와 lane을 등록하고 연결성을 검증해야 한다.

## 2. 현재 지도 자산과 사용 제한

| 파일 | 현재 확인 내용 | 상태 | 사용 전 조치 |
|---|---|---|---|
| `/home/syw/Desktop/final_map_08.yaml` | `resolution=0.050`, `origin=[-0.277,-1.452,0]`, image=`final_map_08.pgm` | 초기 참고값 | 실제 SLAM 저장 원본인지 확인 |
| `/home/syw/Desktop/final_map_08.pgm` | 파일명 확장자는 PGM이나 현재 탐지 형식은 44×54 RGBA PNG | 검증 필요 | 원본 파일 재확인 후 Nav2가 읽는 image 형식·크기 검증 |
| `/home/syw/Trihouse/control_system/rmf_maps/robosapiens.png` | 2000×2402 RGBA PNG | UI 참고 이미지 | 좌표 변환 근거로 사용하지 않음 |

`robosapiens.png`는 관제 UI 표시용이다. 실제 Pinky graph 좌표의 근거로 사용하지 않는다. `control_system` 파일은 수정하지 않는다.

현재 `final_map_08.pgm`은 이름과 실제 탐지 형식이 다르므로 이 상태에서 graph 좌표를 확정하지 않는다. 다음 명령 결과와 실제 SLAM 원본을 대조한다.

```bash
sed -n '1,80p' /home/syw/Desktop/final_map_08.yaml
file /home/syw/Desktop/final_map_08.pgm
identify /home/syw/Desktop/final_map_08.pgm
```

## 3. level 이름과 좌표계 정합

### 3.1 이름 계약

아래 세 이름은 대소문자까지 같아야 한다.

```text
RMF graph level 이름
= /fleet_states.robots[].location.level_name
= fleet adapter가 Pinky 위치를 보고할 때 사용하는 map 이름
```

실제 level 이름은 현재 `미측정/미확정`이다. 예를 들어 `L1`을 사용할 수 있지만 office demo의 이름을 근거 없이 복사하지 않는다.

### 3.2 좌표 정합 절차

1. YAML의 resolution, origin, image 크기와 방향을 확인한다.
2. Nav2/RViz에서 쉽게 반복 접근할 수 있는 기준점 4개 이상을 선택한다.
3. 한쪽에 몰리지 않도록 지도의 네 영역에 기준점을 분산한다.
4. 각 기준점의 Nav2 map 좌표와 RMF Traffic Editor 좌표를 기록한다.
5. translation, rotation, scale이 일치하는지 계산한다.
6. 기준점에 Pinky를 3회 이상 정차시키고 RMF 표시 pose 오차를 기록한다.
7. 기준점 검증 전에는 waypoint 좌표 상태를 `미측정`으로 유지한다.

| 기준점 | Nav2 x/y | RMF x/y | 위치 오차 | 반복 | 상태 | 원본 로그 |
|---|---|---|---:|---:|---|---|
| REF_01 | 미측정 | 미측정 | 미측정 | 0 | 미측정 | 미생성 |
| REF_02 | 미측정 | 미측정 | 미측정 | 0 | 미측정 | 미생성 |
| REF_03 | 미측정 | 미측정 | 미측정 | 0 | 미측정 | 미생성 |
| REF_04 | 미측정 | 미측정 | 미측정 | 0 | 미측정 | 미생성 |

## 4. 필수 waypoint와 lane

### 4.1 waypoint 명명·속성

| ID 패턴 | 위치·용도 | RMF 속성 | 관련 배터리 Action |
|---|---|---|---|
| `FROZEN_PICKUP_<NN>` | 냉동창고 적재 정차점 | 정밀 정차, passthrough false | `ALLOW_LOCAL_JOB` |
| `PACKING_HANDOVER_<NN>` | 포장대 인계 정차점 | 정밀 정차, passthrough false | `ALLOW_LOCAL_JOB`, `COMPLETE_THEN_RETURN` |
| `FROZEN_SAFE_WAIT_<NN>` | 냉동창고 주변 안전 대기 | holding point | `WAIT_AT_SAFE_NODE`, `HOLD_SAFE` |
| `PACKING_SAFE_WAIT_<NN>` | 포장대 주변 안전 대기 | holding point | `WAIT_AT_SAFE_NODE`, `HOLD_SAFE` |
| `GENERAL_WAIT_<NN>` | 일반 운영 대기 | holding point | `NONE` |
| `CHARGE_<NN>` | 충전 정차 위치 | charger, passthrough false | `RETURN_TO_CHARGE`, `WAIT_FOR_CHARGE` |
| `AISLE_WAIT_<NN>` | 좁은 통로 진입 전 양보 | holding point | `HOLD_SAFE` |
| `RECOVERY_RETURN_<NN>` | 비상 해제 후 점검 복귀 | holding point | `HOLD_SAFE`, `REQUIRE_OPERATOR` |

`<NN>`은 01부터 증가시킨다. Traffic Editor, Control Tower 작업 template, `EstimateTaskEnergy.waypoint_ids`에서 동일한 문자열을 사용한다.

### 4.2 POC 필수 lane

최소 graph는 다음 경로를 모두 포함해야 한다.

| 출발 | 도착 | 방향 | 필요 이유 |
|---|---|---|---|
| `FROZEN_PICKUP_01` | `PACKING_HANDOVER_01` | 필수 | 적재물 배송 |
| `PACKING_HANDOVER_01` | `FROZEN_PICKUP_01` | 필수 | 빈 바구니·다음 작업 복귀 |
| 두 작업점 | 각 주변 `SAFE_WAIT` | 양방향 | LOCAL_ONLY 작업 없음·예측 불가 시 안전 대기 |
| 두 작업점 | `CHARGE_01` | 충전소 방향 필수 | 작업 종료 후 충전 복귀 |
| `CHARGE_01` | 운영 graph | 복귀 방향 필수 | 30% 이상 충전 후 재투입 |

lane은 벽과 장애물을 가로지르면 안 된다. 좁은 통로에는 필요 시 `AISLE_WAIT_01`을 두고 장시간 정차점은 통행을 막지 않는 위치로 검증한다.

## 5. waypoint pose 측정 기록표

실제 숫자를 추정해서 넣지 않는다. 각 pose는 최소 5회 접근하고 위치·yaw 허용오차 안의 성공률을 기록한다.

| waypoint ID | level | x(m) | y(m) | 접근 yaw(rad) | 위치 허용오차 | yaw 허용오차 | 성공/시도 | 상태 | 원본 로그 |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| `FROZEN_PICKUP_01` | 미확정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 0/0 | 미측정 | 미생성 |
| `PACKING_HANDOVER_01` | 미확정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 0/0 | 미측정 | 미생성 |
| `FROZEN_SAFE_WAIT_01` | 미확정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 0/0 | 미측정 | 미생성 |
| `PACKING_SAFE_WAIT_01` | 미확정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 0/0 | 미측정 | 미생성 |
| `CHARGE_01` | 미확정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 0/0 | 미측정 | 미생성 |

상태 변경 기준은 다음과 같다.

- `미측정`: pose와 허용오차가 없음
- `측정 완료`: 측정일·반복 결과·원본 로그가 있음
- `검증 완료`: 실제 정차와 작업/충전 성공 기준을 통과함

## 6. Traffic Editor 등록과 graph export

1. 검증된 occupancy map을 Traffic Editor building map의 level image로 등록한다.
2. section 3에서 확정한 level 이름과 좌표 정합값을 사용한다.
3. section 5의 waypoint 이름과 측정 pose를 입력한다.
4. SAFE_WAIT/AISLE_WAIT/GENERAL_WAIT에는 holding point를 설정한다.
5. `CHARGE_01`에는 charger 속성을 설정한다.
6. 정밀 정차·대기·충전 waypoint는 passthrough를 사용하지 않는다.
7. section 4.2의 필수 lane을 양방향 요구에 맞게 연결한다.
8. navigation graph YAML을 export하고 저장소에서 관리할 경로를 정한다.
9. export한 graph에서 이름 중복과 필수 waypoint 누락을 검사한다.

```bash
rg -n "FROZEN_PICKUP_01|PACKING_HANDOVER_01|FROZEN_SAFE_WAIT_01|PACKING_SAFE_WAIT_01|CHARGE_01" \
  /path/to/pinky/nav_graph.yaml
```

`/path/to/pinky/nav_graph.yaml`은 명령 예시이며 실제 경로가 아니다. export 위치가 확정되면 문서와 Pinky launch에서 동일한 경로를 사용한다.

## 7. bridge 설정 교체 위치

`trihouse_rmf_bridge/config/office_bridge.yaml`은 office 회귀 검증용으로 유지한다. 실제 Pinky 연결 구현에서는 별도 Pinky config와 launch를 만들고 다음 값만 검증된 실제 값으로 교체한다.

| 설정 | 실제 Pinky 근거 | 현재 상태 |
|---|---|---|
| `nav_graph_file` | section 6에서 export·검증한 graph | 미측정 |
| `fleet_name` | Pinky fleet adapter 등록 이름 | 미확정 |
| `robot_name` | `/fleet_states`에 나타나는 실제 이름 | 미확정 |
| 운동·외형·배터리 파라미터 | `parameters_for_rmf.md`의 검증값 | 미측정 |

서비스 `/trihouse/rmf/estimate_task_energy`와 입력 topic `/fleet_states` 계약은 바꾸지 않는다.

## 8. `/fleet_states` pose와 graph start 결합

bridge는 다음 값을 `rmf_traffic::agv::compute_plan_starts`에 전달한다.

```text
location.level_name, location.x, location.y, location.yaw
```

### 8.1 입력 확인

```bash
ros2 topic echo /fleet_states rmf_fleet_msgs/msg/FleetState --once
ros2 topic info /fleet_states --verbose
```

확인 항목은 fleet 이름, robot 이름, `level_name`, x/y/yaw, battery percent다. 실제 level 이름이 graph와 다르면 먼저 adapter 설정을 수정한다.

### 8.2 start 결합 확인

실제 Pinky를 graph waypoint 또는 lane 근처에 세우고 유효 waypoint로 에너지 예측을 요청한다.

```bash
python3 -m control_tower.rmf_adapter.estimate_energy_cli \
  --robot-id PINKY_ROBOT_NAME \
  --waypoint FROZEN_PICKUP_01
```

- `success=true`: 현재 pose가 graph에 결합되고 목적지 경로가 생성됨
- `RMF_START_NOT_ON_GRAPH`: level/좌표 정합, pose 보고값, merge 거리 확인
- `RMF_WAYPOINT_NOT_FOUND`: graph export와 waypoint 이름 확인
- `RMF_ROUTE_UNAVAILABLE`: lane 방향·연결 단절 확인

`PINKY_ROBOT_NAME`은 실제 `/fleet_states` 이름으로 바꾼다.

## 9. 필수 경로와 오류 코드 검증

| 시나리오 | 기대 결과 | 상태 | 원본 로그 |
|---|---|---|---|
| `FROZEN_PICKUP_01 → PACKING_HANDOVER_01` | `success=true`, ETA·SOC 감소 양수 | 미측정 | 미생성 |
| `PACKING_HANDOVER_01 → FROZEN_PICKUP_01` | `success=true`, ETA·SOC 감소 양수 | 미측정 | 미생성 |
| 냉동 작업점→`FROZEN_SAFE_WAIT_01` | `success=true` | 미측정 | 미생성 |
| 포장 작업점→`PACKING_SAFE_WAIT_01` | `success=true` | 미측정 | 미생성 |
| 두 작업점→`CHARGE_01` | `success=true` | 미측정 | 미생성 |
| graph 밖 pose | `RMF_START_NOT_ON_GRAPH` | 미측정 | 미생성 |
| 단절 waypoint | `RMF_ROUTE_UNAVAILABLE` | 미측정 | 미생성 |

## 10. 단계별 완료 체크리스트

### 지도 준비

- [ ] `final_map_08.pgm`의 실제 형식·크기와 SLAM 원본을 확인했다.
- [ ] YAML image, resolution, origin이 실제 Nav2 실행 설정과 같다.
- [ ] RMF level 이름과 `/fleet_states.location.level_name`을 확정했다.
- [ ] 기준점 4개 이상의 좌표 오차를 기록했다.

### waypoint와 graph

- [ ] 필수 waypoint의 실제 x/y/yaw를 측정했다.
- [ ] 각 waypoint를 최소 5회 접근해 허용오차와 성공률을 기록했다.
- [ ] 냉동↔포장 양방향 lane을 등록했다.
- [ ] 작업점↔SAFE_WAIT와 작업점→충전 경로를 등록했다.
- [ ] Traffic Editor에서 graph를 export하고 버전·경로를 기록했다.

### bridge 연결

- [ ] 실제 `fleet_name`, `robot_name`, `nav_graph_file`을 확인했다.
- [ ] 실제 Pinky `/fleet_states`를 수신했다.
- [ ] `compute_plan_starts` 결합이 성공했다.
- [ ] section 9의 필수 경로가 모두 성공했다.
- [ ] `parameters_for_rmf.md` 필수값이 `측정 완료` 이상이다.
- [ ] 모든 증거 링크와 적용 승인이 있고 핵심 pose 상태가 `검증 완료`다.

모든 항목을 통과하기 전에는 “실제 Pinky RMF graph 연결 완료”로 표시하지 않는다.
