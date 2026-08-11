# SR-28·SR-29 핵심 작업 오케스트레이션 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Pinky와 OMX의 현재 단계 완료를 단순 Gate로 결합하고, 다음 명령을 한 번만 생성하며, 작업·단계 상태와 성공/실패 근거를 추적한다.

**Architecture:** `StageEngine`은 작업·단계의 현재 상태만 관리하고, `HandoverGate`는 동일한 작업·단계·배정 revision에서 Pinky와 OMX의 성공 완료 여부만 모은다. `TaskOrchestrator`는 완료 이벤트를 검증·분류한 뒤 Gate 또는 단일 실행 단계를 진행하며, 다음 명령을 멱등 키로 한 번만 생성한다. MySQL은 현재 상태와 별도로 단계별 실행 시도 이력을 `job_step_attempts`에 보존한다.

**Tech Stack:** Python 3.12, `dataclasses`, `enum.StrEnum`, `unittest`/`pytest`, MySQL 8 SQL

## Global Constraints

- `/home/syw/Trihouse/pinky_pro`와 `/home/syw/Trihouse/control_system`은 수정하지 않는다.
- Gate는 별도 상태 머신으로 확장하지 않는다. 두 역할의 성공 완료를 모으고 한 번 release하는 책임만 가진다.
- Open-RMF 상태는 이 구현의 입력 사실이며 Trihouse 작업 상태를 직접 덮어쓰지 않는다.
- 명령 생성은 Control Tower에서 exactly-once, 전송은 at-least-once로 취급한다.
- `method_code`는 명령 생성 시 결정하고, `outcome_reason_code`는 구조화된 실행 사실에서 결정적으로 계산한다.
- 각 구현 단계는 실패 테스트 확인 → 최소 구현 → 통과 확인 순서로 진행한다.

---

### Task 1: 실행 결과 계약과 결정적 분류기

**Files:**
- Create: `control_tower/task_manager/execution_result.py`
- Create: `control_tower/tests/test_execution_result.py`

**Step 1: 실패 테스트 작성**

다음 계약을 테스트한다.

- `ActorRole`: `PINKY`, `OMX`, `FMS`
- `AttemptState`: `CREATED`, `DISPATCHED`, `RUNNING`, `RECONCILING`, `FINISHED`
- `AttemptOutcome`: `SUCCEEDED`, `FAILED`, `ABORTED`, `CANCELLED`
- `FailureDomain`: `NONE`, `ROBOT`, `PERCEPTION`, `NAVIGATION`, `MANIPULATION`, `SAFETY`, `INTEGRATION`, `OPERATOR`, `UNKNOWN`
- `CompletionEvent(event_id, job_id, job_step_id, assignment_revision, actor_role, actor_id, success)`
- `ExecutionFact`에는 명령 UUID, method, 구조화된 판정 기준, metrics, 전후 관측, evidence, 정책/모델 계보가 포함된다.
- `classify_execution(fact)`는 명령 성공과 모든 판정 기준 통과 시에만 `SUCCEEDED`를 반환한다.
- 명령 실패, 판정 기준 실패, 취소/중단은 입력 사실에 따라 고정된 `outcome_reason_code`를 반환한다.
- 실패 detail이 비어 있더라도 reason code와 failure domain은 구조화된 값으로 남는다.

**Step 2: 테스트 실패 확인**

Run: `python3 -m pytest -q control_tower/tests/test_execution_result.py`

Expected: `execution_result` 모듈이 없어 import 단계에서 FAIL.

**Step 3: 최소 구현**

`Criterion`, `ExecutionFact`, `ExecutionOutcome`를 frozen dataclass로 만들고 `classify_execution()`을 순수 함수로 구현한다. 성공/실패 최종 라벨은 VLM 자유 텍스트가 아니라 `command_outcome`, criterion 결과, failure domain을 사용한다.

**Step 4: 테스트 통과 확인**

Run: `python3 -m pytest -q control_tower/tests/test_execution_result.py`

Expected: PASS.

### Task 2: revision과 중복 방지를 포함한 단순 Handover Gate

**Files:**
- Modify: `control_tower/task_manager/handover_gate.py`
- Replace tests: `control_tower/tests/test_handover_gate.py`

**Step 1: 실패 테스트 작성**

다음을 검증한다.

- `expect(job_id, job_step_id, assignment_revision, pinky_id, omx_id)`가 현재 pairing을 등록한다.
- `record(CompletionEvent)`는 기대한 역할/장비의 `success=True`만 완료 역할에 추가한다.
- 한 역할만 완료하면 release하지 않고, Pinky와 OMX가 모두 완료하면 정확히 한 번 `released=True`를 반환한다.
- 같은 `event_id` 재수신은 duplicate이며 release/명령을 다시 만들지 않는다.
- 실패 이벤트, 오래된 revision, 다른 단계, 다른 장비는 Gate를 열지 않는다.
- Pinky 재배정 또는 revision 변경은 기존 완료 역할과 event dedupe 범위를 초기화한다.
- 취소된 Gate 이벤트는 수락하지 않는다.

**Step 2: 테스트 실패 확인**

Run: `python3 -m pytest -q control_tower/tests/test_handover_gate.py`

Expected: 새 `expect`/`record` API가 없어 FAIL.

**Step 3: 최소 구현**

내부 `_Handover`에 단계 ID, revision, 기대 장비, `completed_roles`, `processed_event_ids`, `released`만 저장한다. 반환값은 `GateDecision(accepted, duplicate, released, reason_code)`로 고정한다.

**Step 4: 테스트 통과 확인**

Run: `python3 -m pytest -q control_tower/tests/test_handover_gate.py`

Expected: PASS.

### Task 3: 작업 상태와 단계 상태 분리

**Files:**
- Modify: `control_tower/task_manager/stage_engine.py`
- Replace tests: `control_tower/tests/test_stage_engine.py`

**Step 1: 실패 테스트 작성**

- Job: `QUEUED → ASSIGNED → RUNNING → COMPLETED`; 별도 `HELD`, `FAILED`, `CANCELLED`.
- Step: `PENDING → RUNNING → SUCCEEDED`; 별도 `FAILED`, `CANCELLED`.
- 생성 직후에는 첫 단계도 `PENDING`이다.
- `assign()`과 `start()`를 명시적으로 호출해야 첫 단계가 실행된다.
- 동일 result ID 재처리는 단계를 건너뛰지 않는다.
- hold/resume은 현재 단계 상태를 보존한다.
- fail/cancel은 현재 단계와 작업의 terminal 상태를 함께 맞춘다.

**Step 2: 테스트 실패 확인**

Run: `python3 -m pytest -q control_tower/tests/test_stage_engine.py`

Expected: `StageState`, `assign`, `start`, `fail`, `cancel`이 없어 FAIL.

**Step 3: 최소 구현**

`_Job`에 단계별 상태, hold 이전 상태, 처리 result ID를 저장한다. `complete()`는 현재 RUNNING 단계에 대해서만 성공하며 다음 단계는 PENDING으로 남긴다.

**Step 4: 테스트 통과 확인**

Run: `python3 -m pytest -q control_tower/tests/test_stage_engine.py`

Expected: PASS.

### Task 4: 오케스트레이터와 멱등 명령 생성

**Files:**
- Create: `control_tower/task_manager/execution_store.py`
- Create: `control_tower/task_manager/task_orchestrator.py`
- Create: `control_tower/tests/test_task_orchestrator.py`

**Step 1: 실패 테스트 작성**

- `StageSpec`은 단계 ID, 필요 역할, 다음 명령 종류/대상 역할, method code를 가진다.
- Gate 단계는 두 완료 이벤트가 모두 올 때까지 다음 단계를 시작하지 않는다.
- 두 번째 성공 완료에서 현재 Gate 단계를 완료하고 다음 단계 명령을 한 번 생성한다.
- 중복/역순 이벤트에도 같은 `idempotency_key` 명령은 한 건만 저장된다.
- 실패 이벤트는 Gate를 열지 않고 세부 `ExecutionOutcome`을 저장한다.
- hold 상태에서는 다음 명령을 생성하지 않으며 resume 후 안전 승인 입력이 있어야 재개한다.
- 취소/재배정 후 오래된 revision 이벤트는 무시한다.

**Step 2: 테스트 실패 확인**

Run: `python3 -m pytest -q control_tower/tests/test_task_orchestrator.py`

Expected: 오케스트레이터 모듈이 없어 FAIL.

**Step 3: 최소 구현**

`ExecutionStore` protocol과 `InMemoryExecutionStore`를 작성한다. `TaskOrchestrator.record_completion(event, fact)`는 이벤트/실행 결과 저장, Gate 또는 단일 단계 진행, 다음 단계 시작, 멱등 `TaskCommand` 저장을 한 흐름으로 수행한다. 명령 멱등 키는 `job_id:job_step_id:assignment_revision:actor_role:command_kind`로 계산한다.

**Step 4: 테스트 통과 확인**

Run: `python3 -m pytest -q control_tower/tests/test_task_orchestrator.py`

Expected: PASS.

### Task 5: 기존 입고·출고 시나리오를 새 계약으로 전환

**Files:**
- Modify: `control_tower/tests/test_outbound_happy_path.py`
- Modify: `control_tower/tests/test_inbound_happy_path.py`

**Step 1: 실패 테스트 전환**

기존 `mark_ready` 수동 호출을 `CompletionEvent`와 `TaskOrchestrator` 흐름으로 바꾼다. 출고와 입고에서 Pinky·OMX 한쪽 완료만으로 다음 단계가 시작되지 않고, 양쪽 완료 후 단 한 개 명령이 생성되는지 검증한다.

**Step 2: 통합 테스트 실패 확인**

Run: `python3 -m pytest -q control_tower/tests/test_outbound_happy_path.py control_tower/tests/test_inbound_happy_path.py`

Expected: 기존 시나리오와 새 API 차이 때문에 FAIL.

**Step 3: 최소 연결 수정**

새 오케스트레이터 API만 사용하도록 두 시나리오를 갱신하고, 기존 재고/OMX/포장대 정책 검증은 유지한다.

**Step 4: 통합 테스트 통과 확인**

Run: `python3 -m pytest -q control_tower/tests/test_outbound_happy_path.py control_tower/tests/test_inbound_happy_path.py`

Expected: PASS.

### Task 6: MySQL 현재 상태·시도 이력 스키마 정렬

**Files:**
- Modify: `db/schema_mysql.sql`
- Modify: `db/tools/sync_schema_comments.py`
- Modify: `db/tests/test_schema_comments.py`
- Create: `db/tests/test_orchestration_schema.py`
- Modify: `docs/database/database_guide.md`

**Step 1: 실패 테스트 작성**

- `jobs.state` 제약이 `queued, assigned, running, held, completed, failed, cancelled`를 허용한다.
- `job_steps.state` 제약이 `pending, running, succeeded, failed, cancelled`를 허용한다.
- `job_steps`에 `assignment_revision`이 있다.
- `job_step_attempts`가 attempt 상태/결과, actor, command UUID, method/reason/failure domain/detail, criteria/metrics, 전후 관측/evidence, 정책/모델 계보, data quality를 보존한다.
- `(job_step_id, assignment_revision, actor_role, attempt_no)`와 `event_uuid`, `command_uuid`의 중복을 막는다.
- `integration_messages.idempotency_key`를 사용해 외부 전송 중복을 막는 기존 구조가 유지된다.

**Step 2: 테스트 실패 확인**

Run: `python3 -m pytest -q db/tests/test_orchestration_schema.py db/tests/test_schema_comments.py`

Expected: 새 테이블/필드가 없어 FAIL.

**Step 3: 최소 스키마 구현**

기존 current-state 테이블과 append-only attempt 이력을 분리한다. `operation_events`는 기존 감사 이벤트 역할을 유지하고, ML 학습용 구조화 실행 결과는 `job_step_attempts`에 저장한다. comment 동기화 메타데이터와 DB 가이드를 함께 갱신한다.

**Step 4: 테스트 통과 확인**

Run: `python3 -m pytest -q db/tests/test_orchestration_schema.py db/tests/test_schema_comments.py`

Expected: PASS.

### Task 7: 전체 회귀 검증과 문서 정합성 확인

**Files:**
- Verify: `control_tower/`
- Verify: `db/`
- Verify: `docs/superpowers/specs/2026-08-12-sr28-sr29-integrated-orchestration-design.md`

**Step 1: 핵심 테스트 실행**

Run: `python3 -m pytest -q control_tower/tests db/tests`

Expected: 전체 PASS.

**Step 2: Python 정적 구문 확인**

Run: `python3 -m compileall -q control_tower/task_manager`

Expected: exit 0.

**Step 3: 보호 경로 및 변경 범위 확인**

Run: `git status --short && git diff --check && git diff --name-only`

Expected: 구현 대상과 문서만 변경되고 `pinky_pro`, `control_system`에는 새 변경이 없다.

**Step 4: 기능별 커밋**

각 Task의 테스트가 통과할 때 관련 파일만 명시적으로 stage하여 작은 커밋으로 남긴다. `docs/superpowers`는 ignore 대상이므로 계획/설계 문서는 `git add -f`로 명시한다.
