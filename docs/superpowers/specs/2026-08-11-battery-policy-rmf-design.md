# Battery Policy and Open-RMF Energy Estimate Design

## 목표

Pinky의 `sensor_msgs/msg/BatteryState`를 기반으로 배터리 상태를 추적하고, Open-RMF가 계산한 작업 완료 예상 SOC를 이용해 Control Tower가 작업 할당, 안전 대기, 적재 완료 후 복귀, 충전소 복귀와 비상 해제 후 재투입을 결정한다.

이번 POC는 `percentage`, `present`, `power_supply_status`, 첫 유효 메시지 수신 여부와 telemetry freshness만 정책 판단에 사용한다. `power_supply_health`, 전압, 전류, 온도와 저온 보정은 범위에서 제외한다.

## 책임 경계

| 구성요소 | 책임 |
|---|---|
| Pinky 로컬 노드 | `BatteryState` 검증, 첫 유효 sample·freshness 추적, 실제 충전 상태 보고 |
| Open-RMF adapter | 경로·교통·작업 고정시간과 power sink를 이용해 전체 작업시간 및 예상 SOC 감소량 계산 |
| Control Tower | RMF 예측값과 업무 규칙을 이용해 상태 및 행동 결정, 배차 허용·거절, 복귀 명령 생성 |
| `DispatchWorkflow` | Control Tower가 허용한 로봇만 실제 작업 후보로 선택 |
| `ExecuteTransport`/Nav2 | Control Tower의 결정에 따라 실제 대기·운반·충전소 복귀 이동 실행 |
| `control_system` | 상태, 예상 잔량, 이유와 관리자 개입 필요 여부 표시; 이번 변경에서는 수정하지 않음 |

`BatteryActionDecision`은 행동 결정 스냅샷이며 직접 모터를 움직이는 명령이 아니다. 실제 이동은 기존 `ExecuteTransport` action을 사용한다.

## POC 배터리 관측

유효한 sample은 다음 조건을 모두 만족한다.

- `BatteryState.present == true`
- `percentage`가 NaN이 아님
- `0.0 <= percentage <= 1.0`

정책과 UI에서는 `percentage`를 0~100 단위로 변환한다.

초기화 규칙:

- 첫 유효 sample 전에는 `UNKNOWN`, `ready=false`, `HOLD_SAFE`, `WAITING_FOR_FIRST_BATTERY_SAMPLE`이다.
- 시작 후 5초 동안 유효 sample이 없으면 상태와 행동은 유지하고 이유를 `BATTERY_STARTUP_TIMEOUT`으로 바꾼다.
- 첫 유효 sample을 받은 뒤 3초 동안 새 유효 sample이 없으면 `UNKNOWN`, `ready=false`, `BATTERY_TELEMETRY_STALE`로 전환한다.
- 운행 중 stale이 되면 급정지하지 않고 새 작업을 금지한 뒤 다음 등록 `SAFE_WAIT` waypoint에서 정지한다.
- `present=false`이면 `UNKNOWN`, `ready=false`, `HOLD_SAFE`, `BATTERY_NOT_PRESENT`로 처리한다.

## 상태와 행동

| State | 의미 | 주요 조건 | 가능한 Action |
|---|---|---|---|
| `UNKNOWN` | 배터리 상태를 신뢰할 수 없음 | 초기 sample 대기, invalid, absent, stale | `HOLD_SAFE` |
| `NORMAL` | 일반 작업 가능 | 일반 운행 중 실제 잔량 20% 초과 | `ALLOW_GENERAL_JOB` |
| `LOCAL_ONLY` | 냉동창고↔포장대 작업만 가능 | 실제 잔량 10% 초과 20% 이하 | `ALLOW_LOCAL_JOB`, `WAIT_AT_SAFE_NODE` |
| `RETURN_REQUIRED` | 새 작업 금지, 충전 복귀 필요 | 실제 잔량 10% 이하 | `COMPLETE_THEN_RETURN`, `RETURN_TO_CHARGE`, `HOLD_SAFE` |
| `CHARGE_WAIT` | 충전 waypoint 도착, 충전 시작 미확인 | charger 도착 후 status가 `CHARGING`이 아님 | `HOLD_SAFE` |
| `CHARGING` | 실제 충전 중 | `power_supply_status == CHARGING` | `WAIT_FOR_CHARGE` |
| `RECOVERY_CHECK` | 비상 해제 후 재투입 검사 중 | 복귀 후 점검 미완료 | `HOLD_SAFE`, `REQUIRE_OPERATOR` |

| Action | 의미 |
|---|---|
| `NONE` | 구체적인 행동 미선택 |
| `ALLOW_GENERAL_JOB` | 일반 작업 배정 허용 |
| `ALLOW_LOCAL_JOB` | 냉동창고↔포장대 작업만 허용 |
| `WAIT_AT_SAFE_NODE` | 냉동창고·포장대 주변 안전 waypoint에서 대기 |
| `COMPLETE_THEN_RETURN` | 적재물 전달을 완료한 뒤 충전소 복귀 |
| `RETURN_TO_CHARGE` | 새 작업 없이 충전 waypoint로 복귀 |
| `HOLD_SAFE` | 새 이동을 시작하지 않고 안전하게 대기 |
| `WAIT_FOR_CHARGE` | 충전 중 배정 없이 재투입 기준까지 대기 |
| `REQUIRE_OPERATOR` | 자동 처리 대신 운영자 확인 필요 |

상태 우선순위는 다음과 같다.

```text
UNKNOWN > RECOVERY_CHECK > CHARGING > CHARGE_WAIT
        > RETURN_REQUIRED > LOCAL_ONLY > NORMAL
```

- telemetry를 신뢰할 수 없으면 다른 잔량 상태보다 `UNKNOWN`이 우선한다.
- 비상 해제 후에는 잔량이 충분해도 `RECOVERY_CHECK`가 우선한다.
- 충전 중이거나 충전 시작을 기다리면 작업 배정보다 충전 workflow가 우선한다.

예시:

- 잔량 18%지만 비상 복귀 점검 중이면 `RECOVERY_CHECK/HOLD_SAFE`다.
- 잔량 18%이고 충전 status가 `CHARGING`이면 `CHARGING/WAIT_FOR_CHARGE`다.

## 배차 규칙

일반 운행 중 실제 잔량이 20%를 초과하면 `NORMAL`이다. 10% 초과 20% 이하이면 `LOCAL_ONLY`이고 냉동창고와 포장대를 왕복하는 작업 사이클만 허용한다. 상온·냉장창고 관련 새 작업은 금지한다.

일반 작업 수행 중 20% 이하로 내려가면 현재 작업은 취소하지 않고 완료한다. 완료 이후부터 `LOCAL_ONLY` 규칙을 적용한다. 작업 중 10% 이하가 되면 적재 여부에 따라 복귀 정책을 재평가한다.

`LOCAL_ONLY` 작업은 Open-RMF가 반환한 `finish_state_of_charge`가 0.10을 초과할 때만 허용한다. 예측 SOC가 0.10 이하이면 그 작업만 거절하며, 실제 잔량이 아직 10%를 초과했다면 충전소로 보내지 않고 다른 적격 작업을 검토하거나 `SAFE_WAIT`에서 대기한다.

## 적재 중 저전력

실제 잔량이 10% 이하이고 적재물이 없으면 충전소 복귀를 요청한다. 적재물이 있으면 새 작업을 금지하고 현재 handover만 완료한다.

- 현재 잔량이 5% 이상이고 handover 완료 후 예상 잔량이 3% 이상이면 `COMPLETE_THEN_RETURN`이다.
- 현재 잔량이 5% 미만이거나 handover 완료 후 예상 잔량이 3% 미만이면 다음 안전 waypoint에서 `HOLD_SAFE`하고 운영자 개입을 요청한다.
- handover 완료 후 충전소까지 도달할 수 없으면 포장대 주변 안전 waypoint에서 대기하고 운영자에게 알린다.

`5%` hard stop과 `3%` reserve는 POC 설정값이며 실험으로 보정한다.

## 충전과 재투입

충전 waypoint 도착 후 실제 `BatteryState.power_supply_status`가 `CHARGING`이 될 때까지 `CHARGE_WAIT`이다. `CHARGING` 확인 후에는 `ready=false`로 유지한다.

충전 또는 비상 복귀 후에는 실제 잔량 30% 이상이고 필요한 recovery check를 통과해야 `NORMAL`로 재투입한다. 일반 운행 중에는 20% 초과를 `NORMAL`로 유지하므로 충전·복구 재투입에만 30% hysteresis를 적용한다.

시뮬레이션 충전기는 charger 도착 후 `CHARGING`을 발행하고 설정된 속도로 percentage를 증가시킨다. 실제 hardware 연결 시에는 vendor `BatteryState`를 authoritative source로 사용한다.

## Open-RMF 에너지 예측

Open-RMF가 최종 authoritative estimator다. Control Tower에서 같은 배터리 모델을 중복 계산하지 않는다.

RMF custom task model에 다음 단계를 포함한다.

```text
현재 위치 → 냉동창고 이동
+ expected_loading_duration_s
+ 냉동창고 → 포장대 이동
+ expected_handover_duration_s
+ task_time_buffer_s
```

초기 POC 고정시간은 loading 30초, handover 30초, buffer 15초다. OMX 로봇팔 자체 소비전력은 Pinky 배터리에서 빼지 않으며, OMX 작업 중 Pinky 대기시간의 ambient consumption만 Pinky 모델에 포함한다.

Open-RMF adapter는 `travel_duration_s`, `total_duration_s`, `change_in_charge`, `finish_state_of_charge`를 반환한다. Control Tower는 이 값을 이용해 업무 구역 제한과 임계값 정책만 적용한다.

RMF 응답 timeout은 2초이고 한 번 재시도한다. 실패하면 작업을 배정하지 않고 `RMF_ENERGY_ESTIMATE_UNAVAILABLE`로 안전 대기한다.

Open-RMF가 없는 단위 테스트·개발 환경에서만 `consumption_percent_per_minute` 기반 fallback estimator를 사용할 수 있다. 운영 설정은 `provider=open_rmf`, `allow_fallback=false`다.

## 인터페이스 분리

### `BatteryCondition.msg`

POC 판단에 필요한 배터리 관측값만 포함한다: stamp, robot ID, 0~100 percentage, present, power supply status, measurement validity, valid sample 수신 여부, telemetry freshness.

### `BatteryPolicyState.msg`

`BatteryCondition`, state, ready, reason code와 detail을 포함한 현재 정책 스냅샷이다. `RobotStatus`가 이 메시지를 포함한다.

### `BatteryActionDecision.msg`

decision ID, sequence, 유효시간, robot/job ID, action, target waypoint, RMF 예상시간·예상 종료 잔량, reason code와 detail을 포함한다. 실제 이동 명령은 아니다.

### `EstimateTaskEnergy.srv`

robot/task/map revision, ordered waypoint IDs와 loading/handover/buffer 시간을 요청하고 RMF의 주행·전체 시간 및 SOC 예측 결과를 반환한다.

`reason_code`는 프로그램용 안정적인 영문 코드이고 `detail`은 UI·로그용 설명이다. 프로그램은 `detail` 문자열로 분기하지 않는다.

## 발행과 QoS

| 데이터 | 발행 규칙 | QoS |
|---|---|---|
| `/trihouse/battery` | 1Hz vendor/simulator 원본 | Reliable, Volatile, Keep Last 5 |
| `BatteryCondition` | 유효성·freshness 변경 즉시 및 1Hz | Reliable, Volatile, Keep Last 5 |
| `BatteryPolicyState` | state/reason 변경 즉시 및 1Hz heartbeat | Reliable, Transient Local, Keep Last 1 |
| `BatteryActionDecision` | action/target/reason 변경 시 | Reliable, Transient Local, Keep Last 1 |
| `RobotStatus` | 1Hz heartbeat 및 중요 상태 변경 즉시 | Reliable, Keep Last 10 |

`BatteryActionDecision` 재전송은 같은 `decision_id`를 유지하며 수신자는 같은 결정을 중복 실행하지 않는다.

## Waypoint 가이드

`docs/guideline/waypoint.md`에 다음 항목의 이름 규칙, RMF graph 속성, 용도, 정차 정밀도와 관련 action을 표로 정리한다.

- 냉동창고 pickup 접근·정차 waypoint
- 포장대 handover 접근·정차 waypoint
- 냉동창고·포장대 주변 `SAFE_WAIT`
- 일반 대기 waypoint
- 충전 waypoint
- 좁은 통로 진입 전 대기 waypoint
- 비상 해제 후 복귀 waypoint

현재 좌표는 확정하지 않으며 추후 Traffic Editor에서 동일한 ID로 등록한다.

## 검증

- 메시지와 service 생성 계약 검증
- 첫 sample, startup timeout, invalid, absent, stale 상태 테스트
- NORMAL/LOCAL_ONLY/RETURN_REQUIRED 경계값 테스트
- 냉동↔포장 작업만 허용하는 배차 테스트
- RMF 예측 SOC 기준 허용·거절 테스트
- 적재 중 complete/hold/return 테스트
- CHARGE_WAIT/CHARGING/30% 재투입 테스트
- 비상 복귀 recovery check 우선순위 테스트
- RMF timeout/retry/fallback 테스트
- QoS profile 계약 테스트

## 비변경 범위

- `pinky_pro`와 `control_system`은 수정하지 않는다.
- 실제 Open-RMF 설치, graph 생성, fleet adapter 구현과 Flutter UI는 후속 단계다.
- POC에서 배터리 health, 전압, 전류, 온도와 저온 보정은 작업 판단에 사용하지 않는다.
