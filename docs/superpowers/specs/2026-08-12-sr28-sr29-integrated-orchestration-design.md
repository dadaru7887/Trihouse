# SR_28·SR_29 통합 작업 조정 및 실행 이력 설계

## 1. 문서 목적

이 문서는 SR_28 로봇 준비상태 동기화와 SR_29 작업 단계 통합 관리를 하나의
Control Tower 흐름으로 구현하기 위한 설계를 정의한다. 핵심 목표는 Pinky와 OMX가
같은 작업·단계에서 모두 준비된 경우에만 물리 인수인계를 시작하고, 모든 명령과 완료
이벤트를 정확히 한 번 처리하며, 실행 방법·성공 또는 실패 원인·증거를 추적 가능하게
기록하는 것이다.

배터리 SR과 동일하게 이번 POC는 순수 도메인 로직, 실제 메시지와 같은 이벤트 계약,
저장 경계, 자동 통합 테스트까지 구현한다. 실제 Open-RMF runtime, 실물 Pinky·OMX와의
동시 운용은 후속 연결 단계로 둔다.

`pinky_pro`와 `control_system`은 보호 경로이며 이 설계의 구현에서 수정하지 않는다.

## 2. 관련 요구사항

### SR_28

- 같은 작업 ID와 단계 ID에 배정된 Pinky와 OMX가 모두 준비돼야 적재·하차를 시작한다.
- 한쪽만 준비됐다면 준비된 장비는 안전 상태에서 기다린다.
- 취소·재배정·단계 변경은 이전 준비상태를 무효화한다.

### SR_29

- 작업은 대기, 배정, 실행, 보류, 완료, 실패를 포함한 명시적 상태로 관리한다.
- 각 단계에 작업·단계·실행 장비·시작/완료 시각·결과를 기록한다.
- 현재 작업·단계·장비·명령과 일치하는 완료 이벤트만 다음 단계를 활성화한다.
- 동일 완료 이벤트 재수신은 다음 단계를 중복 실행하지 않는다.
- 보류 후에는 마지막 성공 단계 다음부터 재개한다.

취소 상태는 SR_28의 준비상태 무효화 요구와 기존 업무 계약을 명시적으로 표현하기 위해
terminal 상태로 추가한다.

## 3. 기존 코드와 외부 상태 모델

현재 `HandoverGate`는 작업 ID 기준 Pinky·OMX 준비 여부를 판단하고,
`StageEngine`은 순서 있는 단계와 중복 result ID를 관리한다. 그러나 두 객체가 실제
이벤트 흐름으로 연결되지 않았고, 현재 happy-path 테스트는 호출자가 두 객체를 직접
순서대로 조작한다. `TaskLifecycle`과 `JobStateMachine`에도 유사한 상태가 존재하므로
새 흐름에서 여러 상태기계를 동시에 원본으로 쓰면 상태가 충돌할 수 있다.

설치된 Open-RMF API의 `task_state`는 다음 정보를 제공한다.

- task status, assigned agent, 시작·종료 시각과 ETA
- phase 목록과 completed/active/pending phase
- phase 내부 event 상태
- interruption, cancellation, killed 정보

Open-RMF status 값은 `uninitialized`, `blocked`, `error`, `failed`, `queued`,
`standby`, `underway`, `delayed`, `skipped`, `canceled`, `killed`, `completed`다.
legacy `rmf_task_msgs/msg/TaskSummary`는 `QUEUED`, `ACTIVE`, `COMPLETED`,
`FAILED`, `CANCELED`, `PENDING`을 제공한다. dispatch는 별도로 `queued`,
`selected`, `dispatched`, `failed_to_assign`, `canceled_in_flight` 상태를 가진다.

Open-RMF는 이동과 RMF task의 상태를 알지만 다음 물리 사실은 자동으로 알지 못한다.

- Pinky의 정밀 정차·자세와 바구니 준비 여부
- OMX의 실제 파지·접근 준비 여부
- 양측이 같은 `job_step_id`에 준비됐는지 여부
- 적재 센서 전환, 그리퍼 열림, OMX 안전 후퇴 여부
- 물리 인계와 재고 반영의 최종 일치 여부

따라서 Open-RMF 상태를 복제하거나 대체하지 않고, Control Tower가 RMF 이동 상태와
Trihouse 물리 workflow를 연결한다.

## 4. 선택한 구조

새 `TaskOrchestrator`가 외부 이벤트의 단일 진입점이 되는 조합형 구조를 사용한다.

```text
Pinky HandoverState / TaskEvent
OMX Status / Result
Open-RMF task state
          │ 정규화
          ▼
TaskOrchestrator
 ├─ StageEngine       작업·단계 상태의 유일한 원본
 ├─ HandoverGate      현재 단계의 양측 준비상태 판단
 ├─ OutcomeClassifier 구조화된 사실을 결과 코드로 분류
 └─ Repository/UoW    상태·attempt·outbox·감사 기록
          │
          ▼
TaskCommand / integration_messages
          │
          ▼
향후 Pinky Gateway / OMX Adapter / RMF Adapter
```

### 컴포넌트 책임

| 컴포넌트 | 책임 |
|---|---|
| `TaskOrchestrator` | 준비·완료·보류·실패·RMF 이벤트를 받아 상태 전이와 다음 명령을 조정한다. |
| `StageEngine` | 작업 전체 상태, 현재 단계, 단계 순서와 terminal 여부의 유일한 원본이다. |
| `HandoverGate` | `(job_id, job_step_id)`별 예상 장비와 READY 여부만 관리한다. |
| `OutcomeClassifier` | 장비·센서·RMF의 구조화된 사실을 outcome, code, criteria, metrics로 결정적으로 변환한다. |
| `TaskExecutionRepository` | 하나의 transaction에서 상태, attempt, outbox와 event를 저장한다. |
| Adapter | ROS/NDJSON/RMF 입력을 domain event로 정규화하고 출력 명령을 실제 시스템에 전달한다. |

`TaskLifecycle`과 `JobStateMachine`은 기존 호출자와 테스트 호환을 위해 바로 삭제하지
않지만 신규 SR_28·SR_29 흐름에서는 사용하지 않는다. 호출자가 없어지는 시점에 별도
정리한다.

## 5. 상태 모델

### 5.1 작업 전체 상태

| Trihouse 상태 | 의미 | Open-RMF 대응 |
|---|---|---|
| `QUEUED` | 작업 생성 후 장비·자원 배정 대기 | task/dispatch `queued` |
| `ASSIGNED` | Pinky·OMX·작업 위치 배정 완료 | dispatch `selected`/`dispatched`, `assigned_to` |
| `RUNNING` | 현재 단계의 실행 명령이 발행됐거나 실행 중 | task `underway` |
| `HELD` | 안전하게 보류되어 새 물리 동작을 시작하지 않음 | `blocked` 또는 interruption |
| `COMPLETED` | 모든 필수 단계와 최종 물리 확인 완료 | `completed` |
| `FAILED` | 자동 진행 불가능한 terminal 실패 | `failed` 또는 `error` |
| `CANCELLED` | 명시적 취소로 남은 단계·준비·명령이 무효화됨 | `canceled` |

작업 부분 완료는 lifecycle 상태가 아니라 `result_code=partial`로 표현한다.

### 5.2 단계 상태

| 단계 상태 | 의미 |
|---|---|
| `PENDING` | 아직 실행 차례가 아님 |
| `WAITING_READY` | 현재 차례지만 양측 준비 확인 중 |
| `RUNNING` | 명령이 발행되고 결과를 기다리는 중 |
| `SUCCEEDED` | 해당 단계의 모든 성공 기준을 만족 |
| `HELD` | 현재 단계를 안전하게 보류 |
| `FAILED` | 해당 단계가 실패로 종료 |
| `CANCELLED` | 작업 취소로 단계가 무효화됨 |

Open-RMF가 실행하는 단계는 `rmf_task_id`, `rmf_phase_id`, `rmf_event_id`,
`rmf_status`, `rmf_status_observed_at`으로 연결한다. OMX 전용 단계에는 RMF ID가
없어도 된다.

### 5.3 Handover Gate 파생 상태

| Gate 상태 | Pinky | OMX | 의미 |
|---|---|---|---|
| `WAITING_BOTH` | 미준비 | 미준비 | 양쪽 모두 기다림 |
| `WAITING_PINKY` | 미준비 | 준비 | Pinky 준비 대기 |
| `WAITING_OMX` | 준비 | 미준비 | OMX 준비 대기 |
| `READY_TO_START` | 준비 | 준비 | 명령 생성 가능 |
| `COMMAND_ISSUED` | 확인됨 | 확인됨 | 인수인계 명령을 한 번 생성함 |
| `CONFIRMED` | 물리 결과 확인 | 물리 결과 확인 | 인수인계 완료 |
| `INVALIDATED` | 무효 | 무효 | 취소·재배정·단계 변경으로 폐기 |
| `FAILED` | 무관 | 무관 | 실행 중 실패 |

Gate 상태는 작업 전체 상태를 대체하지 않는다. `READY_TO_START`도 행동 명령이 아니며,
실제 행동은 `TaskCommand`로 분리한다.

### 5.4 실행 시도 outcome

| outcome | 의미 |
|---|---|
| `SUCCEEDED` | 성공 기준을 모두 만족 |
| `FAILED` | 해당 실행 시도가 실패 |
| `HELD` | 조건 해제 또는 상태 대조까지 중단 |
| `CANCELLED` | 실행 전 철회 또는 명시적 취소 |
| `ABORTED` | 실행 도중 안전·운영 판단으로 강제 종료 |
| `PARTIAL` | 일부 기준만 만족해 운영자 판단 필요 |

## 6. 결과 코드와 실행 방법 생성

코드는 장비가 보내는 임의 문자열이나 VLM 자유문으로 채우지 않는다.

```text
장비/RMF/센서의 구조화된 결과
→ Adapter의 ExecutionFact
→ OutcomeClassifier 고정 규칙
→ outcome + code + criteria + metrics + detail
```

### 필드 구분

| 필드 | 의미 | 생성 시점 |
|---|---|---|
| `method_code` | 어떤 방법으로 실행했는가 | 명령 생성 시 |
| `selection_reason_code` | 왜 해당 행동·방법을 골랐는가 | 정책 결정 시 |
| `outcome_reason_code` | 왜 해당 실행 결과로 종료됐는가 | 결과 분류 시 |
| `state_reason_code` | 왜 현재 작업·단계 상태가 됐는가 | 상태 전이 시 |
| `failure_domain` | 실패 계층 | 실패 분류 시 |
| `detail` | 실제 수치를 포함한 사람용 설명 | event 생성 시 |

`detail`은 프로그램 분기에 사용하지 않는다. 실제 수치는 `criteria`와 `metrics`에도
구조화해 저장한다.

### 대표 매핑

| 구조화된 사실 | outcome | outcome reason |
|---|---|---|
| Nav2 성공, 정차, 위치·방향 허용오차 만족 | `SUCCEEDED` | `NAVIGATION_GOAL_REACHED` |
| Nav2 성공이나 목표 오차 초과 | `FAILED` | `NAVIGATION_GOAL_TOLERANCE_EXCEEDED` |
| RMF/Nav2 경로 없음 | `FAILED` | `NAVIGATION_PATH_UNAVAILABLE` |
| 그리퍼 닫힘, 물품 센서 미감지 | `FAILED` | `GRASP_EMPTY_AFTER_CLOSE` |
| 적재 센서·그리퍼 열림·안전 후퇴 확인 | `SUCCEEDED` | `HANDOVER_PHYSICALLY_CONFIRMED` |
| OMX READY timeout | `HELD` | `OMX_READINESS_TIMEOUT` |
| 다른 현재 단계의 결과 | attempt 변경 없음 | `STALE_JOB_STEP_EVENT` |
| 동일 result ID 재수신 | attempt 변경 없음 | `DUPLICATE_RESULT_EVENT` |

중복·stale 이벤트는 `operation_events`에 거부 사실을 남기되 현재 attempt를 실패로
바꾸지 않는다.

### 코드 관리

POC에서는 `Outcome`, `FailureDomain`, `SelectionReasonCode`, `OutcomeReasonCode`,
`MethodCode`를 `StrEnum`으로 정의하고 문서·테스트로 고정한다. DB는 확장 가능한
`VARCHAR`로 저장한다. terminal 결과가 분류되지 않으면 추측하지 않고
`UNCLASSIFIED_RESULT`와 `data_quality_status=INCOMPLETE`를 사용한다.

## 7. 통합 작업 흐름

출고 작업의 대표 단계는 다음과 같다.

| 순서 | 단계 | 실행 주체 | Gate |
|---:|---|---|---|
| 1 | `PICK` | OMX | 없음 |
| 2 | `LOAD` | Pinky+OMX | 필요 |
| 3 | `TRANSPORT` | Pinky/RMF | 없음 |
| 4 | `UNLOAD` | Pinky+OMX | 필요 |
| 5 | `CONFIRM` | FMS | 없음 |

### 생성과 배정

작업 생성 시 job은 `QUEUED`, 모든 step은 `PENDING`이다. 장비·위치·자원이 배정되면
job을 `ASSIGNED`로 전이하고 `JOB_ASSIGNED` event를 기록한다. 이 시점에는 아직
물리 명령을 발행하지 않는다.

### 일반 단계

Gate가 필요 없는 현재 단계는 `TaskCommand`, `job_step_attempts`, outbox message를
생성하고 step과 job을 `RUNNING`으로 바꾼다. `method_code`와
`selection_reason_code`는 이 명령에 고정된다.

### Gate 단계

Gate 단계가 현재 차례가 되면 step을 `WAITING_READY`로 바꾸고 예상 Pinky·OMX를
등록한다. READY event는 job, step, role, actor가 모두 예상값과 일치하고 freshness를
만족할 때만 수락한다.

양측 READY가 되면 하나의 transaction에서 다음을 수행한다.

1. Gate가 `READY_TO_START`인지 재확인
2. `job_step_attempts` 생성
3. 단계와 job을 `RUNNING`으로 변경
4. 동일 idempotency key의 `integration_messages` 생성
5. Gate를 `COMMAND_ISSUED`로 변경
6. 명령 발행 event 기록

같은 READY가 재수신돼도 unique idempotency key 때문에 추가 명령을 만들지 않는다.

### READY 해제

명령 발행 전 `ready=false`가 들어오면 해당 역할 READY를 제거한다. 명령 발행 뒤에는
READY 해제로 실행을 되돌리지 않고 실제 장비 결과 또는 안전 event로 처리한다.

### 완료 event

event ID, command UUID, job, step, actor, 현재 단계 상태를 모두 검증한다. 일치하면
`ExecutionFact`를 분류해 attempt를 종료하고 step을 `SUCCEEDED`, `HELD`, `FAILED`
등으로 전이한다. 성공이면 다음 step을 활성화하고 마지막 단계면 job을
`COMPLETED`로 전이한다.

### Open-RMF 이동 단계

| RMF/Pinky 입력 | Trihouse 처리 |
|---|---|
| RMF `queued`/`standby` | 시작 대기 |
| RMF `underway` | step `RUNNING` |
| RMF `delayed` | `RUNNING` 유지, 지연 event 기록 |
| RMF `blocked` | blocked timer 시작 |
| blocked timeout | `HELD`, recovery 후보 생성 |
| RMF `failed`/`error` | failure classifier 또는 recovery |
| RMF `completed`만 수신 | Pinky 도착 확인 대기 |
| RMF completed + Pinky 정차·허용오차 만족 | `SUCCEEDED` |
| RMF `canceled` | `CANCELLED` |

### Timeout, 보류와 재개

| 상황 | 처리 |
|---|---|
| READY timeout | job/step `HELD` |
| 명령 ACK timeout | 같은 idempotency key로 전송 재시도 |
| 결과 timeout | `HELD` 후 실제 장비 상태 대조 |
| RMF status timeout | `HELD`, 새 이동 금지 |

결과 timeout에서는 장비가 이미 실행했을 수 있으므로 새 attempt를 자동 생성하지 않는다.
재개 시 마지막 성공 단계, 미확정 attempt와 장비 실제 상태를 대조한다. Gate 단계는 READY를
처음부터 다시 수집한다.

### 재배정과 취소

재배정은 기존 Gate와 아직 전송되지 않은 명령을 무효화하고 새 장비 기준으로 READY를
다시 수집한다. 기존 Pinky에 화물이 남아 있으면 자동 재배정하지 않고 `HELD`와 운영자
개입으로 전환한다.

취소는 job과 미완료 step을 `CANCELLED`, Gate를 `INVALIDATED`로 바꾸고 미전송
outbox를 취소한다. 실행 중 장비에는 cancel 요청을 만들며 늦은 성공 event가 작업을
재활성화하지 못하게 한다.

## 8. DB 모델과 transaction

`trihouse_fms`가 운영 원본이고 `trihouse_recovery`는 복구·학습용 파생 저장소다.

### 8.1 `jobs`

`state`를 `queued`, `assigned`, `running`, `held`, `completed`, `failed`,
`cancelled`로 정규화한다. `state_reason_code`, `state_detail`, `result_code`,
`updated_at`을 추가한다. 기존 `revision` optimistic lock은 유지한다.

기존 `pending`, `planned`, `waiting`, `blocked`, `safety_hold`는 상태와 원인이
섞여 있으므로 신규 상태와 reason code로 변환한다.

### 8.2 `job_steps`

`state`를 `pending`, `waiting_ready`, `running`, `succeeded`, `held`, `failed`,
`cancelled`로 정규화한다. RMF 연결 필드와 `final_outcome_reason_code`,
`final_method_code`를 추가한다. `result`는 단계 최종 criteria·metrics 요약만 저장한다.

### 8.3 신규 `job_step_attempts`

실행 한 번당 한 행을 저장한다. 최소 필드는 다음과 같다.

- `attempt_uuid`, `job_step_id`, `attempt_no`, `actor_device_id`, `command_uuid`
- `state`, `method_code`, `selection_reason_code`, `outcome_reason_code`
- `failure_domain`, `policy_source`, `policy_name`, `policy_version`
- `parameters`, `criteria`, `metrics`, `detail`
- `started_at`, `completed_at`

`(job_step_id, attempt_no)`와 `command_uuid`는 각각 unique다. terminal attempt에는
method, outcome reason과 완료 시각이 필요하고 실패 attempt에는 failure domain도
필요하다.

`job_steps.retry_count`와 최종 `result`만으로는 이전 실패 attempt가 사라지므로
학습·감사 요구를 충족하지 못한다. 이 테이블 추가는 필수다.

### 8.4 `operation_events`

추가 전용 감사 로그로 유지하면서 `correlation_uuid`, `causation_event_uuid`,
`attempt_uuid`, `command_uuid`, `outcome`, `reason_code`, `method_code`를 추가한다.
가변적인 센서 관측·후보 행동·증거는 기존 `payload` JSON에 저장한다.

### 8.5 `integration_messages`

기존 테이블을 transactional outbox로 사용한다. 단계 상태·attempt·outbox·event는
하나의 MySQL transaction에서 commit한다. adapter 전송은 at-least-once이며
idempotency key가 물리 효과의 중복을 막는다.

예시 key는 `JOB-01:LOAD-02:ATTEMPT-01:OMX_LOAD`다.

### 8.6 결과 처리 transaction

한 transaction에서 다음을 수행한다.

1. event UUID 중복 검사
2. command/job/step/actor 검증
3. 결과 분류
4. attempt 종료
5. step 상태 갱신
6. 다음 step 활성화 또는 job 종료
7. 감사 event 추가

DB 저장에 실패하면 ACK를 보내지 않아 동일 event 재전송으로 복구할 수 있게 한다.

## 9. VLM/RL Episodic Memory

정상 실행·실패·재시도는 `trihouse_fms.job_step_attempts`, `operation_events`,
`artifacts`에 저장한다. 실제 navigation recovery가 시작된 경우만
`trihouse_recovery.recovery_episodes`와 `recovery_steps`에 투영한다.

### Recovery 시작

RMF/Nav2 blocked timeout, 지속 경로 차단, localization 저하, 저시야 등이 후보가 된다.
사람 보호 영역 진입은 VLM/RL 행동을 실행하지 않고 안전 해제를 기다린다. 배터리 부족은
recovery가 아니라 배터리 정책으로 처리한다.

FMS는 job을 `HELD`, 현재 attempt를 `HELD` 또는 `FAILED`로 바꾸고
`RECOVERY_EPISODE_REQUESTED` event와 recovery outbox를 같은 transaction에 저장한다.

두 DB를 분산 transaction으로 묶지 않는다. Recovery Gateway가 outbox를 받아
`source_event_uuid`로 멱등하게 episode를 생성한다. `source_event_uuid`는 recovery DB에서
unique로 만든다. Recovery DB 장애 중에는 FMS `HELD`를 유지하고 새 복구 행동을 실행하지
않는다.

### `recovery_episodes` 보완

`final_reason_code`, `final_method_code`, `termination_type`, `outcome_metrics`,
`data_quality_status`, `schema_version`을 추가한다. episode 성공 여부와 실제 성공 방법을
분리한다.

### `recovery_steps` 보완

기존 before/action/reward/after 구조에 다음을 추가한다.

- `fms_attempt_uuid`, `decision_event_uuid`, `result_event_uuid`
- `method_code`, `selection_reason_code`, `outcome_reason_code`, `failure_domain`
- `action_parameters`, `candidate_actions`, `criteria`, `metrics`
- `safety_decision`, `termination_type`
- `state_schema_version`, `reward_version`, `data_quality_status`

후보 행동은 FMS `operation_events`가 운영 원본이다. Recovery DB에는 episode를 독립적으로
export하고 재현할 수 있도록 실행 시점 snapshot을 중복 저장한다. 이 선택은 기존
`2026-08-09-vlm-rl-recovery-schema-design.md`의 “후보는 FMS에만 저장” 결정을 학습 데이터
자급성 요구에 한해 확장한다.

`started_at`은 queued 상태를 위해 nullable로 바꾸고 상태별 시각 일관성을 CHECK로
강제한다.

| execution status | started_at | completed_at |
|---|---|---|
| `queued` | NULL | NULL |
| `running` | NOT NULL | NULL |
| terminal | NOT NULL | NOT NULL |

### RL export

한 recovery step은 다음 transition으로 export한다.

```text
observation_t
+ candidate_actions
+ selected_action/action_parameters
+ reward_components
+ observation_t+1
+ termination_type
```

reward는 실행 중 임의로 만들지 않는다. 시간, 진행도, 안전거리, 개입, 에너지 같은 원본
component를 저장하고 버전이 지정된 dataset builder가 계산한다.

학습 기본 export는 observation·action·next observation 무결성, method/reason,
terminal 일관성, artifact hash와 reward schema가 모두 검증된
`data_quality_status=COMPLETE` record만 사용한다.

이 설계는 기존 FMS MySQL 통합 설계의 “새 도메인 테이블을 추가하지 않는다” 제한을
SR_29의 attempt 보존 요구에 한해 갱신한다. `job_step_attempts` 없이 재시도별 원인과
방법을 보존할 수 없기 때문이다.

## 10. QoS와 전달 신뢰성

| 데이터 | Reliability | Durability | History |
|---|---|---|---|
| `TaskEvent` | Reliable | Volatile | Keep Last 50 |
| `HandoverState` | Reliable | Transient Local | Keep Last 10 |
| `RobotStatus` | Reliable | Volatile | Keep Last 10 |
| Control Tower 명령 | NDJSON ACK/retry | outbox 보존 | idempotency key |

`TaskEvent`는 stale event 자동 재생을 피하고 event ID로 중복 제거한다.
`HandoverState`는 late subscriber를 위해 최근 snapshot을 제공하되 freshness timeout을
넘긴 과거 READY는 사용하지 않는다.

## 11. 오류 처리

| 오류 | 처리 |
|---|---|
| 필수 ID 누락·불일치 | 전이·명령 거부, 감사 event |
| 중복 event | 멱등 ACK, 상태 유지 |
| stale step event | 감사 기록 후 무시 |
| 알 수 없는 code | `UNCLASSIFIED_RESULT`, 학습 제외 |
| DB transaction 실패 | ACK 금지, 재수신 대기 |
| outbox 전송 실패 | 같은 idempotency key로 재시도 |
| 결과 timeout | `HELD`, 장비 상태 대조 |
| Recovery DB 장애 | FMS `HELD`, 복구 명령 금지 |
| artifact 누락 | 운행 결과 유지, 데이터 품질 `INCOMPLETE` |
| VLM/RL 출력 오류 | 행동 실행 금지, 검증 실패 기록 |

VLM/RL은 후보 행동을 제안할 수 있지만 최종 성공·실패는 실제 센서와 장비 결과로
판정한다. Safety Supervisor의 허용 목록과 승인을 통과하지 못한 행동은 실행하지 않는다.

## 12. 테스트 전략

### 단위 테스트

- `StageEngine`: 전체·단계 상태, 순서, terminal, hold/resume/cancel
- `HandoverGate`: job/step/actor 일치, 양측 READY, revoke, 재배정, 취소
- `OutcomeClassifier`: 성공·실패·timeout·미분류 규칙과 criteria/metrics
- RMF mapper: dispatch/task/phase/event 상태와 Trihouse 전이

### 멱등성 테스트

동일 Pinky READY, OMX READY와 완료 event를 각각 세 번 전달해도 attempt, outbox 명령,
단계 전이와 다음 단계 활성화는 각각 한 번만 발생해야 한다.

### transaction 테스트

SQLite 기반 POC repository로 다음 원자성을 검증한다.

- READY 완료 시 attempt, step, outbox, event 동시 commit/rollback
- 결과 처리 시 attempt, step, 다음 단계, event 동시 commit/rollback
- event ID와 command idempotency key unique

MySQL DDL은 MySQL 8 환경에서 CHECK, unique와 시간 제약을 검증한다. 컨테이너 또는 서버가
없는 환경에서는 정적 contract test만 수행하고 runtime DDL 검증이 생략됐음을 보고한다.

### 통합 시나리오

- 정상 출고: PICK → LOAD gate → RMF TRANSPORT → UNLOAD gate → 재고 확정
- 정상 입고: Pinky 운반 → gate → OMX 선반 적재 → 물리·재고 확정
- wrong/stale/duplicate event 거부
- READY revoke, READY timeout과 결과 timeout
- 보류 후 마지막 미완료 단계 재개
- 화물 유무에 따른 재배정 분기
- 취소 후 늦은 성공 event 무효화
- RMF blocked → recovery request → 멱등 episode 생성
- 불완전 evidence의 dataset export 제외

기존 배터리·Control Tower·Pinky 테스트도 계속 통과해야 한다.

## 13. 완료 기준

- 같은 job·step의 Pinky와 OMX가 모두 READY일 때만 인수인계 명령을 만든다.
- 실행 명령과 완료 전이는 중복 입력에도 정확히 한 번만 발생한다.
- job, step, actor와 command가 일치하는 결과만 수락한다.
- 보류·재배정·취소가 기존 READY와 미실행 명령을 올바르게 무효화한다.
- Open-RMF 상태와 Trihouse 물리 workflow 상태를 구분해 저장한다.
- 모든 실행 attempt에 method와 선택·결과 reason을 기록한다.
- 실패·성공 모두 criteria, metrics와 증거 연결을 보존할 수 있다.
- recovery episode와 step은 observation-action-outcome 계보와 데이터 품질을 가진다.
- 보호 경로인 `pinky_pro`, `control_system`을 수정하지 않는다.

## 14. 범위 밖

- 실제 Open-RMF API/Fleet Adapter runtime 연결
- 실물 Pinky와 OMX의 동시 자동 시연
- VLM/RL 모델 학습과 online inference
- object storage 업로드 구현
- 기존 운영 MySQL 데이터의 자동 migration 실행
- `control_system` Flutter UI 변경
