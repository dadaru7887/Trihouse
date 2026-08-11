# Open-RMF Waypoint 등록 가이드

## 명명 규칙과 용도

| ID 패턴 | 위치·용도 | 기본 동작 | 관련 배터리 Action |
|---|---|---|---|
| `FROZEN_PICKUP_<NN>` | 냉동창고 적재 정차점 | OMX 적재를 위한 정밀 정차 | `ALLOW_LOCAL_JOB` |
| `PACKING_HANDOVER_<NN>` | 포장대 인계 정차점 | 적재물 인계를 위한 정밀 정차 | `ALLOW_LOCAL_JOB`, `COMPLETE_THEN_RETURN` |
| `FROZEN_SAFE_WAIT_<NN>` | 냉동창고 주변 통행 방해 없는 안전 대기 | LOCAL_ONLY 작업 미배정 시 대기 | `WAIT_AT_SAFE_NODE`, `HOLD_SAFE` |
| `PACKING_SAFE_WAIT_<NN>` | 포장대 주변 통행 방해 없는 안전 대기 | 예측 SOC 부족 또는 인계 후 대기 | `WAIT_AT_SAFE_NODE`, `HOLD_SAFE` |
| `GENERAL_WAIT_<NN>` | 일반 운영 대기 위치 | 정상 유휴 대기 | `NONE` |
| `CHARGE_<NN>` | 무선 충전 정차 위치 | charger 접속 및 충전 확인 | `RETURN_TO_CHARGE`, `WAIT_FOR_CHARGE` |
| `AISLE_WAIT_<NN>` | 좁은 통로 진입 전 양보 위치 | traffic conflict 해소까지 대기 | `HOLD_SAFE` |
| `RECOVERY_RETURN_<NN>` | 비상 해제 후 점검 복귀 위치 | recovery check 수행 | `HOLD_SAFE`, `REQUIRE_OPERATOR` |

`<NN>`은 같은 종류의 지점을 01부터 구분한다. 코드·문서·Traffic Editor 이름은 대소문자까지 동일해야 한다.

## Traffic Editor 등록 항목

| 항목 | 기록 규칙 | 확인 사항 |
|---|---|---|
| waypoint ID | 위 명명 규칙 사용 | 중복 금지, 코드의 ID와 일치 |
| map/floor | RMF level 이름 | `EstimateTaskEnergy.map_revision`과 호환 |
| 위치 x/y | 실제 측량 또는 검증된 map 좌표 | POC 주행 시험 후 확정 |
| 접근 yaw | 적재·인계·충전에 필요한 로봇 전방 방향 | OMX/충전 접점 방향과 일치 |
| `is_charger` | `CHARGE_<NN>`만 true | 실제 또는 시뮬레이션 charger와 매핑 |
| holding point | SAFE_WAIT, GENERAL_WAIT, AISLE_WAIT에 true | 장시간 정차해도 통행을 막지 않음 |
| passthrough | 정밀 정차·충전·대기점은 false | 목적점을 지나치지 않도록 설정 |
| 위치 허용오차 | 현장 시험값 기록 | pickup/handover/charge는 보수적으로 설정 |
| yaw 허용오차 | 현장 시험값 기록 | 로봇팔·충전 정렬 성공률로 보정 |
| 담당 workflow | frozen pickup, packing handover 등 | 배차 구역 문자열과 연결 |

## 등록 순서

1. 실제 map과 floor 이름을 확정한다.
2. 냉동창고, 포장대, 충전소의 정차 위치와 접근 방향을 측량한다.
3. 각 작업점 주변에서 통행을 방해하지 않는 SAFE_WAIT를 최소 하나 등록한다.
4. Traffic Editor graph에 ID, holding, charger, passthrough 속성을 입력한다.
5. 동일 ID를 Control Tower 작업 template과 `EstimateTaskEnergy.waypoint_ids`에 연결한다.
6. 무적재·적재 주행으로 위치/yaw 허용오차와 RMF ETA를 검증한다.
7. 충전 도착 후 `BatteryState.power_supply_status == CHARGING` 전환을 확인한다.

## POC 검증표

| 시나리오 | 확인 결과 |
|---|---|
| `FROZEN_PICKUP_01 → PACKING_HANDOVER_01` RMF 경로 생성 | 미검증 |
| `PACKING_HANDOVER_01 → FROZEN_PICKUP_01` 빈 바구니 복귀 경로 생성 | 미검증 |
| 두 작업점에서 가장 가까운 SAFE_WAIT 선택 | 미검증 |
| 모든 작업점에서 `CHARGE_01` 경로 생성 | 미검증 |
| 적재·인계 정차 허용오차 내 도착 | 미검증 |
| 충전 정렬 후 실제 CHARGING 상태 수신 | 미검증 |

좌표와 허용오차는 현재 임의로 넣지 않는다. Open-RMF map을 연결한 뒤 현장 측정값으로 이 표와 Traffic Editor graph를 함께 갱신한다.
