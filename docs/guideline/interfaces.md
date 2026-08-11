# 배터리 정책 인터페이스 가이드

## 책임 분리

| 구분 | 한 줄 책임 | 구현 위치 |
|---|---|---|
| 관측(`BatteryCondition`) | Pinky가 배터리 원본의 유효성과 최신성을 보고한다. | Pinky 로컬 노드 |
| 상태(`BatteryPolicyState`) | 현재 어떤 배터리 운영 모드인지 나타낸다. | Control Tower 정책 |
| 행동(`BatteryActionDecision`) | 현재 상태와 작업 맥락에서 무엇을 허용하거나 요청할지 결정한다. | Control Tower 정책 |
| 에너지 예측(`EstimateTaskEnergy`) | 경로와 작업 시간을 반영한 작업 종료 예상 SOC를 제공한다. | Open-RMF adapter |
| 이동 실행 | 결정된 waypoint로 실제 이동한다. | `ExecuteTransport`/Nav2 |

State는 **현재 상황**, Action은 **그 상황에서 선택한 다음 조치**다. 프로그램은 `state`, `action`, `reason_code`로 분기하며 사람이 읽는 `detail`로 분기하지 않는다.

## POC에서 사용하는 BatteryState 필드

| 입력 | 단위·범위 | 사용법 |
|---|---|---|
| `percentage` | 0.0~1.0 | 유효성 검사 후 0~100%로 변환해 임계값 판단 |
| `present` | bool | false이면 `UNKNOWN` |
| `power_supply_status` | `BatteryState` 상수 | `CHARGING`과 `FULL` 확인 |
| 첫 유효 sample 수신 여부 | 내부 추적 | 첫 sample 전에는 작업·이동 금지 |
| 마지막 유효 sample 시각 | monotonic 초 | 3초 freshness 판단 |

전압, 전류, 온도, `power_supply_health`와 저온 보정은 이번 POC 판단에서 사용하지 않는다. 유효 sample은 `present=true`, percentage가 NaN이 아니며 0.0~1.0 범위인 경우다. invalid sample은 마지막 유효 수신 시각을 갱신하지 않는다.

## 상태와 행동

| State | 조건·의미 | 기본 Action | 새 작업 |
|---|---|---|---|
| `UNKNOWN` | 첫 sample 전, absent, invalid, 3초 stale | `HOLD_SAFE` | 금지 |
| `NORMAL` | 일반 운행 중 20% 초과 | `ALLOW_GENERAL_JOB` | 일반 작업 허용 |
| `LOCAL_ONLY` | 10% 초과 20% 이하 | `ALLOW_LOCAL_JOB` 또는 `WAIT_AT_SAFE_NODE` | 냉동↔포장만 조건부 허용 |
| `RETURN_REQUIRED` | 실제 잔량 10% 이하 | `RETURN_TO_CHARGE`, 적재 시 `COMPLETE_THEN_RETURN`/`REQUIRE_OPERATOR` | 금지 |
| `CHARGE_WAIT` | 충전소 도착 후 충전 상태 미확인 또는 재투입 30% 미만 | `HOLD_SAFE` | 금지 |
| `CHARGING` | `POWER_SUPPLY_STATUS_CHARGING` | `WAIT_FOR_CHARGE` | 금지 |
| `RECOVERY_CHECK` | 비상 해제 후 점검 미완료 | `HOLD_SAFE` 또는 `REQUIRE_OPERATOR` | 금지 |

| Action | 의미 |
|---|---|
| `NONE` | 아직 구체적인 조치를 선택하지 않음 |
| `ALLOW_GENERAL_JOB` | 상온·냉장·냉동을 포함한 일반 작업 배정 허용 |
| `ALLOW_LOCAL_JOB` | 냉동창고↔포장대 작업만 허용 |
| `WAIT_AT_SAFE_NODE` | 냉동창고 또는 포장대 주변 등록 안전 위치에서 대기 |
| `COMPLETE_THEN_RETURN` | 적재물을 포장대에 인계한 뒤 충전소 복귀 |
| `RETURN_TO_CHARGE` | 새 작업 없이 충전 waypoint로 복귀 |
| `HOLD_SAFE` | 새 이동을 시작하지 않고 현재 또는 다음 안전 위치에서 대기 |
| `WAIT_FOR_CHARGE` | 충전 중 작업을 받지 않고 재투입 기준까지 대기 |
| `REQUIRE_OPERATOR` | 자동 운행 대신 운영자 확인 요청 |

## 상태 우선순위

| 순위 | State | 우선하는 이유 |
|---:|---|---|
| 1 | `UNKNOWN` | 신뢰할 수 없는 telemetry로는 잔량·충전 판단을 내릴 수 없다. |
| 2 | `RECOVERY_CHECK` | 비상 해제 후 안전 점검이 잔량 기반 재배정보다 우선한다. |
| 3 | `CHARGING` | 실제 충전 중인 로봇은 모든 작업 후보에서 제외한다. |
| 4 | `CHARGE_WAIT` | 충전 시작 확인 또는 30% 재투입 기준 충족을 기다린다. |
| 5 | `RETURN_REQUIRED` | 10% 이하에서는 새 작업보다 충전 복귀가 우선한다. |
| 6 | `LOCAL_ONLY` | 10% 초과 20% 이하에서는 가까운 지정 작업만 허용한다. |
| 7 | `NORMAL` | 상위 제한 조건이 없을 때 일반 작업을 허용한다. |

예시 1: 잔량이 18%여도 마지막 유효 sample이 3초를 넘기면 `LOCAL_ONLY`가 아니라 `UNKNOWN/HOLD_SAFE`다.

예시 2: 잔량이 18%이고 실제 status가 `CHARGING`이면 `LOCAL_ONLY`가 아니라 `CHARGING/WAIT_FOR_CHARGE`다.

## reason_code와 detail

| 필드 | 대상 | 규칙 | 예시 |
|---|---|---|---|
| `reason_code` | 프로그램·검색·통계 | 안정적인 대문자 영문 코드. 로직 분기에 사용 | `BATTERY_TELEMETRY_STALE` |
| `detail` | UI·운영자·로그 | 현재 수치와 맥락을 사람이 이해할 문장. 로직 분기 금지 | `마지막 유효 배터리 수신 후 3.4초 경과` |

| 상황 | reason_code | detail 예시 |
|---|---|---|
| 첫 유효 배터리 sample을 기다림 | `WAITING_FOR_FIRST_BATTERY_SAMPLE` | `노드 시작 후 첫 유효 배터리 값을 기다리는 중` |
| RMF가 제한 시간 내 예상 SOC를 주지 못함 | `RMF_ENERGY_ESTIMATE_UNAVAILABLE` | `2초 timeout으로 1회 재시도했으나 응답 없음` |

주요 코드는 `BATTERY_STARTUP_TIMEOUT`, `BATTERY_NOT_PRESENT`, `BATTERY_PERCENTAGE_INVALID`, `BATTERY_TELEMETRY_STALE`, `BATTERY_NORMAL`, `BATTERY_LOCAL_WORK_ONLY`, `BATTERY_AT_OR_BELOW_RETURN_THRESHOLD`, `PREDICTED_FINISH_SOC_TOO_LOW`, `HANDOVER_RESERVE_UNSAFE`, `BATTERY_CHARGING`, `RECOVERY_CHECK_REQUIRED`다.

## 상황별 규칙

| 상황 | 결정 |
|---|---|
| 첫 유효 sample 전 | `UNKNOWN`, `ready=false`, `HOLD_SAFE`; 5초 후 reason만 `BATTERY_STARTUP_TIMEOUT`으로 변경 |
| 유효 sample 수신 | percentage 기준 state를 즉시 계산해 보고 |
| 수신 후 3초 timeout | `UNKNOWN`; 새 작업 금지, 진행 중이면 급정지 대신 다음 안전 waypoint에서 대기 |
| 일반 작업 중 20% 이하 | 현재 작업 완료 후 `LOCAL_ONLY` 적용 |
| LOCAL_ONLY·예상 종료 SOC 10% 초과 | 냉동↔포장 작업을 계속 허용(`ALLOW_LOCAL_JOB`) |
| LOCAL_ONLY·예상 종료 SOC 5% 초과 10% 이하 | 해당 냉동↔포장 작업까지만 완료하고 즉시 충전 복귀(`COMPLETE_THEN_RETURN`) |
| LOCAL_ONLY·예상 종료 SOC 5% 이하 | 새 작업 없이 즉시 충전 복귀(`RETURN_TO_CHARGE`) |
| LOCAL_ONLY·RMF ETA/SOC 없음 | 가까운 냉동창고 또는 포장대 안전 위치에서 대기(`WAIT_AT_SAFE_NODE`) |
| 실제 잔량 10% 이하·무적재 | 충전소 복귀 |
| 실제 잔량 10% 이하·적재 | 현재 5% 이상, 인계 후 SOC 3% 이상일 때만 인계 후 복귀 |
| 위 적재 안전 조건 실패 | 안전 대기 후 운영자 개입 요청 |
| 충전소 도착·충전 미확인 | `CHARGE_WAIT` |
| 충전 확인 | `CHARGING`; 배정 금지 |
| 충전·비상 복귀 이후 | 점검 완료 및 실제 잔량 30% 이상부터 `NORMAL` 재투입 |

## RMF 에너지 계약

운영 환경에서는 Open-RMF 예측이 authoritative 값이다. Control Tower는 이를 다시 계산하지 않고 구역·임계값 정책만 적용한다.

```text
total_duration_s
= rmf_travel_duration_s
 + expected_loading_duration_s(기본 30초)
 + expected_handover_duration_s(기본 30초)
 + task_time_buffer_s(기본 15초)
```

RMF service timeout은 2초이며 한 번 재시도한다. 실패 시 새 작업을 배정하지 않는다. `consumption_percent_per_minute` 계산은 Open-RMF가 없는 개발·단위 테스트에서 `allow_fallback=true`로 명시했을 때만 사용한다. 운영 기본은 `provider=open_rmf`, `allow_fallback=false`다.

## 발행 규칙과 QoS

QoS는 ROS 2 publisher와 subscriber가 데이터 전달 방식에 합의하는 설정이다. Reliability는 유실 처리, Durability는 늦게 접속한 구독자의 마지막 값 수신 여부, History/Depth는 보관 개수를 뜻한다.

| 데이터 | 발행 규칙 | Reliability | Durability | History |
|---|---|---|---|---|
| `/trihouse/battery` | vendor 또는 simulator 원본 1Hz | Reliable | Volatile | Keep Last 5 |
| `/trihouse/battery/condition` | 관측 변경 즉시 및 1Hz | Reliable | Volatile | Keep Last 5 |
| `BatteryPolicyState` | state/reason 변경 즉시 및 1Hz | Reliable | Transient Local | Keep Last 1 |
| `BatteryActionDecision` | action/target/reason 변경 시 | Reliable | Transient Local | Keep Last 1 |
| `RobotStatus` | 1Hz 및 중요 변경 즉시 | Reliable | Volatile | Keep Last 10 |

같은 결정을 재전송할 때 `decision_id`를 유지하며 수신자는 이미 처리한 ID를 다시 실행하지 않는다.
