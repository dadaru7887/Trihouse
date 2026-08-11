# SR_28·SR_29 통합 작업 조정 및 실행 이력 설계

## 1. 목적과 범위

SR_28 로봇 준비상태 동기화와 SR_29 작업 단계 통합 관리를 하나의 Control Tower
흐름으로 구현한다. 현재 작업·단계에 배정된 Pinky와 OMX의 성공 완료 이벤트를 모두
받았을 때만 다음 인수인계 동작을 한 번 생성하고, 모든 실행에 성공·실패 이유와 방법,
전후 관측과 증거를 남긴다.

배터리 SR과 동일하게 이번 POC는 순수 도메인 로직, 실제 메시지와 같은 이벤트 계약,
저장 경계와 자동 통합 테스트까지 구현한다. 실제 Open-RMF runtime과 실물 Pinky·OMX
동시 운용은 후속 연결 단계로 둔다. `pinky_pro`와 `control_system`은 수정하지 않는다.

## 2. 핵심 결정

- 새 `TaskOrchestrator`가 준비 완료, 실행 결과, 보류·재개·취소 이벤트의 단일 진입점이다.
- `StageEngine`은 허용된 작업·단계 전이 규칙을 담당하고 MySQL이 내구성 있는 현재 상태의
  원본이다.
- `HandoverGate`는 별도 상태기계가 아니다. 현재 `(job_id, job_step_id,
  assignment_revision)`에 대한 Pinky·OMX 성공 완료 두 개만 모은다.
- Open-RMF는 이동·교통·RMF task 상태의 원본이고, Trihouse는 물리 작업과 인수인계
  workflow의 원본이다.
- 상태 enum을 늘리지 않고 `job_step_attempts`의 method, reason, criteria, metrics와
  evidence를 풍부하게 기록한다.
- Control Tower는 명령과 상태 전이를 한 번만 만든다. 전달은 at-least-once이며 Adapter가
  idempotency key를 재시작 후에도 보존해야 물리 효과가 effectively-once가 된다.
- `trihouse_recovery` 장애는 로컬 안전정지와 FMS가 승인한 규칙 기반 안전 복귀를 막지
  않는다. episodic memory는 FMS outbox에서 나중에 backfill할 수 있다.

## 3. 구조와 책임

```text
Pinky completion / TaskEvent
OMX completion / Result
Open-RMF task state
          │ 정규화
          ▼
TaskOrchestrator
 ├─ StageEngine       작업·단계 전이 규칙
 ├─ HandoverGate      Pinky·OMX 성공 완료 집합
 ├─ OutcomeClassifier 구조화된 사실을 결과 기록으로 변환
 └─ Repository/UoW    상태·attempt·outbox·감사 기록
          │
          ▼
TaskCommand / integration_messages
          │
          ▼
향후 Pinky Gateway / OMX Adapter / RMF Adapter
```

| 컴포넌트 | 책임 |
|---|---|
| `TaskOrchestrator` | 외부 이벤트를 검증하고 Gate·단계 전이·다음 명령을 조정한다. |
| `StageEngine` | 작업 전체 상태와 순서 있는 단계의 허용 전이를 결정한다. |
| `HandoverGate` | 현재 assignment에서 성공 완료한 `PINKY`, `OMX` 역할을 모은다. |
| `OutcomeClassifier` | 장비·센서·RMF 사실을 성공/실패 기록으로 결정적으로 변환한다. |
| Repository/UoW | 상태, 실행 시도, outbox와 감사 event를 원자적으로 저장한다. |

기존 `TaskLifecycle`과 `JobStateMachine`은 기존 호출자 호환을 위해 바로 삭제하지 않지만
신규 SR_28·SR_29 흐름에서는 사용하지 않는다.

## 4. 단순 상태 모델

### 4.1 작업 전체 상태

| 상태 | 의미 | Open-RMF 참고 정보 |
|---|---|---|
| `QUEUED` | 장비·자원 배정 대기 | task/dispatch `queued` |
| `ASSIGNED` | Pinky·OMX·작업 위치 배정 완료 | dispatch `selected`/`dispatched`, `assigned_to` |
| `RUNNING` | 현재 단계 실행 중 | task `underway` |
| `HELD` | 작업 전체를 안전하게 보류 | `blocked` 또는 interruption은 보류 판단의 입력 |
| `COMPLETED` | 모든 필수 단계와 최종 물리 확인 완료 | task `completed` |
| `FAILED` | 자동 진행 불가능한 terminal 실패 | task `failed`/`error`는 실패 판단의 입력 |
| `CANCELLED` | 명시적 취소로 남은 단계·준비·명령 무효화 | task `canceled` |

부분 완료는 상태가 아니라 `jobs.result_code=partial`로 표현한다. `HELD` 원인은
`state_reason_code`로 분리한다.

### 4.2 단계 상태

| 상태 | 의미 |
|---|---|
| `PENDING` | 아직 실행 차례가 아님 |
| `RUNNING` | 실행 또는 Pinky·OMX 완료 이벤트를 기다리는 중 |
| `SUCCEEDED` | 해당 단계의 필수 성공 완료를 모두 수신 |
| `FAILED` | 장비 실패 또는 성공 조건 불충족 |
| `CANCELLED` | 작업 취소로 무효화 |

보류는 job에만 둔다. 보류 중인 현재 step은 실제 진행 위치를 잃지 않도록 `RUNNING` 또는
`PENDING`을 유지한다.

### 4.3 실행 시도 진행 상태와 결과

진행 상태와 최종 결과를 분리한다.

| attempt 상태 | 의미 |
|---|---|
| `CREATED` | 명령과 attempt 생성 |
| `DISPATCHED` | Adapter 전달 완료 |
| `RUNNING` | 실행 시작 확인 |
| `RECONCILING` | timeout 후 장비 실제 상태 대조 중 |
| `FINISHED` | terminal 결과 확정 |

`FINISHED`인 attempt만 `SUCCEEDED`, `FAILED`, `ABORTED`, `CANCELLED` 중 하나의
outcome을 가진다. `HELD`는 job 상태이고 `PARTIAL`은 작업 최종 결과이므로 attempt
outcome에 넣지 않는다.

## 5. 단순 Handover Gate

Gate가 보관하는 값은 다음뿐이다.

```text
job_id
job_step_id
assignment_revision
expected PINKY/OMX actor IDs
completed_roles
processed_event_ids
released
```

판정은 다음과 같다.

| Pinky 성공 완료 | OMX 성공 완료 | 처리 |
|---|---|---|
| false | false | 대기 |
| true | false | 대기 |
| false | true | 대기 |
| true | true | 다음 명령 한 번 생성 |

완료 이벤트는 `event_id`, `job_id`, `job_step_id`, `assignment_revision`,
`actor_role`, `actor_id`, `success`를 가진다. 현재 assignment와 모두 일치하고
`success=true`인 새 event만 `completed_roles`에 추가한다.

실패 event는 완료 집합에 넣지 않고 실행 결과로 기록해 재시도 또는 `HELD/FAILED`
정책으로 넘긴다. 같은 event ID는 무시한다. `released=true`이면 이후 완료 event로 다음
명령을 다시 만들지 않는다. 취소·재배정·단계 변경은 Gate를 비우고 revision을 바꾼다.

Safety 상태는 Gate에 넣지 않는다. 양측 완료 후 명령 생성 직전에 기존 안전 정책을
별도로 확인한다.

## 6. 세밀한 실행 결과 기록

복잡도는 상태가 아니라 각 Pinky·OMX 실행 결과에 둔다.

| 필드 | 의미 |
|---|---|
| `event_id`, `command_uuid` | 중복 제거와 명령 연결 |
| `job_id`, `job_step_id` | 작업·단계 연결 |
| `actor_role`, `actor_id` | Pinky 또는 OMX 실행 주체 |
| `attempt_no` | 같은 역할·단계의 재시도 번호 |
| `success`, `outcome` | 실제 성공 여부와 terminal 결과 |
| `method_code` | 어떻게 실행했는지 |
| `selection_reason_code` | 왜 이 방법을 선택했는지 |
| `outcome_reason_code` | 왜 성공·실패했는지 |
| `failure_domain` | navigation, perception, manipulation, handover, safety 등 |
| `detail` | 실제 수치가 포함된 사람용 설명 |
| `criteria` | 성공 조건별 expected/observed/pass |
| `metrics` | 오차·시간·거리·SOC·재시도 횟수 |
| `before_observation`, `after_observation` | 실행 전후 상태 snapshot 또는 URI |
| `evidence_refs` | 이미지·영상·ROS bag·RMF log 참조 |
| `policy_source`, `policy/model version` | RULE, RMF, NAV2, VLM, RL 계보 |

### 코드 생성 규칙

`method_code`는 명령 생성 시 작업 template과 실제 명령에서 고정한다.
`selection_reason_code`는 정책이 방법을 선택한 시점에 기록한다.
`outcome_reason_code`, `failure_domain`, `criteria`, `metrics`, `detail`은 Adapter가 만든
구조화된 `ExecutionFact`를 `OutcomeClassifier`가 고정 규칙으로 변환해 채운다.

VLM은 후보와 선택 근거를 제안할 수 있지만 최종 성공·실패 label은 실제 센서와 장비
결과로 결정한다. `detail`은 분기에 사용하지 않는다. 분류할 사실이 부족하면 추측하지
않고 `UNCLASSIFIED_RESULT`, `data_quality_status=INCOMPLETE`를 사용한다.

### 대표 예

```yaml
actor_role: PINKY
success: false
method_code: NAV2_NAVIGATE_TO_HANDOVER_POSE
outcome_reason_code: NAVIGATION_GOAL_TOLERANCE_EXCEEDED
failure_domain: NAVIGATION
detail: 위치 오차 0.18m가 허용값 0.05m를 초과함
criteria:
  navigation_succeeded: true
  stationary: true
  position_within_tolerance: false
metrics:
  position_error_m: 0.18
  allowed_error_m: 0.05
```

```yaml
actor_role: OMX
success: true
method_code: OMX_TOP_GRASP_AND_READY
outcome_reason_code: OMX_CARGO_READY_CONFIRMED
detail: 대상 물품 파지와 인수인계 접근 자세 완료
criteria:
  target_item_matched: true
  grasp_confirmed: true
  approach_pose_reached: true
metrics:
  marker_confidence: 0.94
  grasp_attempts: 1
```

## 7. 통합 이벤트 흐름

출고 대표 단계는 `PICK → LOAD → TRANSPORT → UNLOAD → CONFIRM`이다.

1. 작업 생성 시 job은 `QUEUED`, 모든 step은 `PENDING`이다.
2. 장비·위치·자원을 배정하면 job을 `ASSIGNED`로 바꾼다.
3. 현재 step을 `RUNNING`으로 바꾸고 실행 명령 또는 완료 대기를 시작한다.
4. Gate 단계는 현재 job/step/revision의 Pinky·OMX 성공 완료를 수집한다.
5. 양측 완료 후 안전 정책을 확인하고 다음 명령·attempt·outbox·event를 하나의
   transaction에서 만든다.
6. 완료 result는 event, command, job, step, revision, actor를 검증한 뒤 attempt와
   step을 한 번만 전이한다.
7. 마지막 step 성공 시 물리 인계와 재고 transaction까지 확인한 뒤 job을
   `COMPLETED`로 바꾼다.

### Open-RMF 이동 사실

RMF 상태는 Trihouse 상태를 직접 덮어쓰지 않고 `ExecutionFact` 입력으로 사용한다.

| RMF 사실 | Trihouse 판단 입력 |
|---|---|
| `underway` | 이동 attempt 실행 중 증거 |
| `delayed` | 지연 event와 metrics |
| `blocked` | blocked timer 시작 |
| blocked timeout | job `HELD`와 recovery 후보 |
| `failed`/`error` | 실패 classifier 입력 |
| `completed` | Pinky 정차·허용오차 검증 시작 조건 |
| `canceled` | 취소 결과 입력 |

RMF completed만으로 이동 step을 성공시키지 않고 Pinky 물리 도착 조건도 확인한다.

### Timeout과 재개

- 명령 ACK timeout은 같은 idempotency key로 전달을 재시도한다.
- 결과 timeout은 attempt를 `RECONCILING`, job을 `HELD`로 바꾸고 장비 상태를
  대조한다. 이미 실행됐을 수 있으므로 새 attempt를 자동 생성하지 않는다.
- 재개는 마지막 성공 step과 미확정 attempt를 대조한 뒤 수행한다.
- 재배정은 assignment revision을 올리고 이전 Gate 결과를 폐기한다.
- 기존 Pinky에 화물이 있으면 자동 재배정하지 않고 운영자 개입으로 전환한다.
- 취소 후 도착한 늦은 성공 event는 작업을 재활성화하지 않는다.

## 8. DB 변경과 transaction

### `jobs`

도메인 상태는 `QUEUED`, `ASSIGNED`, `RUNNING`, `HELD`, `COMPLETED`, `FAILED`,
`CANCELLED`로 사용한다. POC MySQL을 새로 생성하는 경우 DB 값도 동일 의미의 소문자로
정리하고 `state_reason_code`, `state_detail`, `result_code`, `updated_at`을 추가한다.
기존 운영 데이터가 있는 환경에는 별도 migration이 필요하며 이번 실행에서는 자동
migration하지 않는다.

### `job_steps`

상태를 `pending`, `running`, `succeeded`, `failed`, `cancelled`로 단순화한다.
`rmf_task_id`, `rmf_phase_id`, `rmf_event_id`, `rmf_status`,
`rmf_status_observed_at`, `final_outcome_reason_code`, `final_method_code`를 보관한다.

### 신규 `job_step_attempts`

Pinky와 OMX 실행 한 번당 한 행을 저장한다. 최소 컬럼은 다음과 같다.

- `attempt_uuid`, `job_step_id`, `assignment_revision`, `actor_role`, `actor_device_id`
- `attempt_no`, `event_uuid`, `command_uuid`, `state`, `outcome`, `success`
- `method_code`, `selection_reason_code`, `outcome_reason_code`, `failure_domain`
- `policy_source`, `policy_name`, `policy_version`
- `parameters`, `criteria`, `metrics`, `observations`, `evidence_refs`, `detail`
- `data_quality_status`, `started_at`, `completed_at`

`event_uuid`, `command_uuid`, `(job_step_id, assignment_revision, actor_role,
attempt_no)`는 각각 unique다.

### `operation_events`

추가 전용 감사 로그로 유지한다. `correlation_uuid`, `causation_event_uuid`,
`attempt_uuid`만 정규화해 추가하고 결과의 세부 구조는 attempt와 event `payload`에 둔다.
동일 method/reason을 여러 테이블의 독립 원본으로 중복 관리하지 않는다.

### Transactional outbox

기존 `integration_messages`를 outbox로 사용한다. 양측 완료 처리 시 하나의 transaction에서
Gate release 확인, attempt, step 전이, outbox 명령과 감사 event를 commit한다. result
처리도 중복 검사, attempt 종료, step과 다음 단계 전이, 감사 event를 하나의 transaction에
묶는다. DB 저장에 실패하면 ACK를 보내지 않는다.

## 9. VLM/RL Episodic Memory

정상 성공·실패·재시도는 `trihouse_fms.job_step_attempts`, `operation_events`,
`artifacts`에 저장한다. navigation recovery가 실제로 시작된 경우만
`trihouse_recovery`에 투영한다.

`recovery_episodes`에는 `final_reason_code`, `final_method_code`,
`termination_type`, `outcome_metrics`, `data_quality_status`, `schema_version`을 추가한다.

`recovery_steps`에는 필수 조회값인 `fms_attempt_uuid`, `method_code`,
`outcome_reason_code`, `failure_domain`, `termination_type`, `data_quality_status`,
`schema_version`을 정규 컬럼으로 두고, 후보 행동·선택 근거·Safety 판단·파라미터는
`decision_snapshot` JSON으로 묶는다. 성공 조건과 수치는 `criteria`, `metrics` JSON으로
둔다. 기존 before/after URI와 hash, reward components는 유지한다.

queued recovery step은 아직 시작하지 않았으므로 `started_at`을 nullable로 바꾸고 다음
시각 규칙을 적용한다.

| execution status | started_at | completed_at |
|---|---|---|
| `queued` | NULL | NULL |
| `running` | NOT NULL | NULL |
| terminal | NOT NULL | NOT NULL |

Recovery Gateway는 FMS outbox의 고유 `source_event_uuid`로 episode를 멱등 생성한다.
Recovery DB가 중단되면 FMS outbox를 재시도하고 데이터 품질은 미확정으로 남긴다. 로컬
안전정지와 FMS가 승인한 규칙 기반 안전 복귀는 학습 DB 가용성과 분리한다.

RL export는 `before observation + decision snapshot + selected action + reward components
+ after observation + termination` 구조다. reward는 원본 component를 저장하고 버전이
지정된 dataset builder가 계산한다. 무결성이 검증된 `COMPLETE` record만 기본 학습
export에 사용한다.

## 10. QoS와 오류 처리

| 데이터 | Reliability | Durability | History |
|---|---|---|---|
| `TaskEvent` | Reliable | Volatile | Keep Last 50 |
| `HandoverState`/완료 사실 | Reliable | Volatile | Keep Last 10 |
| `RobotStatus` | Reliable | Volatile | Keep Last 10 |
| Control Tower 명령 | at-least-once | outbox | idempotency key |

완료 사실은 event ID와 assignment revision으로 검증한다. 과거 READY snapshot 재생 문제를
피하기 위해 POC의 handover 완료 QoS는 Volatile로 둔다.

| 오류 | 처리 |
|---|---|
| 필수 ID·revision·actor 불일치 | 전이 거부, 감사 event |
| 중복 event | 멱등 ACK, 상태 유지 |
| stale step result | 감사 기록 후 무시 |
| 알 수 없는 결과 | `UNCLASSIFIED_RESULT`, 학습 제외 |
| DB transaction 실패 | ACK 금지, 재수신 대기 |
| outbox 전송 실패 | 같은 idempotency key로 재시도 |
| 결과 timeout | `RECONCILING`과 job `HELD` |
| artifact 누락 | 운행 결과 유지, 데이터 품질 `INCOMPLETE` |
| VLM/RL 출력 검증 실패 | 행동 실행 금지, 실패 기록 |

## 11. 구현 단계

### 1단계: SR_28·SR_29 핵심

- 단순 상태 모델과 Gate
- `TaskOrchestrator`, `OutcomeClassifier`
- `job_step_attempts`와 outbox transaction 경계
- 입고·출고 모의 통합 테스트

### 2단계: Open-RMF projection

- RMF task/phase/event 정규화
- Pinky 물리 도착 검증과 결합
- delayed/blocked/failed 처리 테스트

### 3단계: Recovery dataset

- recovery episode/step 스키마 보완
- decision snapshot과 데이터 품질 검사
- 학습 export contract 테스트

세 단계를 순서대로 구현하고 각 단계마다 별도 검증·커밋 경계를 둔다.

## 12. 테스트와 완료 기준

- Pinky만 또는 OMX만 성공 완료하면 다음 명령이 없다.
- 같은 job/step/revision의 양측 성공 완료 후 다음 명령이 한 번만 생성된다.
- wrong actor, stale step/revision, duplicate event는 상태를 바꾸지 않는다.
- 실패 이벤트는 Gate를 열지 않고 method/reason/criteria/metrics를 보존한다.
- 보류 후 마지막 성공 단계 다음부터 재개한다.
- 재배정·취소는 이전 완료 집합과 미실행 명령을 무효화한다.
- RMF 상태는 외부 사실로 저장되며 Trihouse 상태를 직접 덮어쓰지 않는다.
- 모든 terminal attempt에 method와 outcome reason이 있고 실패에는 failure domain이 있다.
- outbox 생성과 단계 전이는 transaction에서 함께 성공하거나 rollback된다.
- incomplete evidence는 운행 결과를 바꾸지 않고 학습 export에서 제외된다.
- 기존 배터리·Control Tower·Pinky 테스트가 계속 통과한다.
- `pinky_pro`, `control_system`을 수정하지 않는다.

## 13. 범위 밖

- 실물 Open-RMF/Pinky/OMX 동시 연결
- Adapter의 재시작 내구성 idempotency 저장 구현
- VLM/RL 모델 학습과 online inference
- object storage 업로드
- 기존 운영 MySQL 데이터 자동 migration
- Flutter 관제 UI 변경
