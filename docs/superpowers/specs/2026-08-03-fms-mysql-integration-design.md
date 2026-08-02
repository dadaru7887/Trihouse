# FMS MySQL Integration Design

## Goal

`control_system`의 Flutter UI와 로봇 연동 코드를 `trihouse_fms` MySQL 스키마에 연결한다. MySQL 쓰기는 FMS Gateway만 수행하며 UI, RMF, Pinky, OMX는 Gateway API 또는 Adapter를 통해서만 상태와 명령을 교환한다.

## Canonical schema

- 기준 스키마는 `db/schema_mysql.sql`이다.
- `control_system/db/schema.sql`은 기존 SQLite v2와 1:1 대응하는 별도 스키마이므로 새 연동에 사용하지 않는다.
- `control_system/db/migrate_sqlite_to_mysql.py`는 `robosapiens` 스키마 전용이므로 `trihouse_fms`에 실행하지 않는다.
- 현재 15개 도메인 테이블을 유지한다. 새 도메인 테이블은 추가하지 않는다.

## Architecture

```text
Flutter control_system UI
        | HTTPS / WebSocket
        v
FMS Gateway / Task Manager
        | MySQL transaction
        v
MySQL trihouse_fms

FMS Gateway <-> Safety Supervisor
FMS Gateway <-> RMF Adapter <-> Open-RMF
FMS Gateway <-> Pinky Adapter <-> Pinky-Pro / Nav2
FMS Gateway <-> OMX Adapter <-> Cyclo / MoveIt 2 / OMX-AI
```

Gateway는 유일한 DB 쓰기 주체다. Safety Supervisor는 승인, 거부, 정지의 최종 권한을 가진다. VLM/RL은 허용 목록 내 복구 제안만 생성하며 직접 명령을 실행하거나 업무 상태를 확정하지 않는다.

## Time policy

- 모든 업무 시각은 대한민국 표준시 `Asia/Seoul` 기준으로 저장하고 해석한다.
- MySQL 연결을 만들 때마다 세션 time zone을 `+09:00`으로 설정한다.
- `DATETIME(6)`에는 time zone 정보가 없으므로 API 요청과 응답은 ISO 8601의 `+09:00` 오프셋을 포함한다.
- Adapter가 보낸 외부 시각은 오프셋을 확인한 뒤 `Asia/Seoul`로 변환하여 저장한다.
- `observed_at`은 장비 관측 시각, `integration_messages.created_at`은 Gateway 수신 시각이다.
- 현재 대한민국은 DST를 사용하지 않으므로 DB 세션은 `+09:00`으로 고정할 수 있다. 애플리케이션 계층에서는 지역 이름 `Asia/Seoul`을 사용한다.

## Reservation scheduling

### Resource serialization

예약 계산은 대상 자원의 기준 행을 먼저 `SELECT ... FOR UPDATE`로 잠근다.

- 위치 예약: `locations` 행 잠금
- 장비 예약: `devices` 행 잠금
- 병목 예약: `map_features` 행 잠금

예약 행이 하나도 없는 경우에도 같은 자원에 대한 두 요청이 동시에 같은 시작 시각을 선택하지 않도록 기준 행 잠금이 필요하다.

### Automatic shift after conflicts

요청 구간 `[requested_start, requested_end)`의 duration을 보존한다. 동일 자원의 `reserved` 또는 `in_use` 예약과 겹치면 해당 충돌 예약의 `planned_end_at`을 새 시작 시각으로 삼고 다시 충돌을 검사한다. 더 뒤의 예약과 다시 겹치면 같은 과정을 반복한다. 충돌이 없어진 가장 이른 시각에 예약한다.

예시:

```text
기존 예약: 10:00-10:20, 10:25-10:40
요청 예약: 10:10-10:30 (20분)
1차 이동: 10:20-10:40 -> 두 번째 예약과 충돌
2차 이동: 10:40-11:00 -> 확정
```

알고리즘은 다음 조건을 만족해야 한다.

- 종료 시각과 다음 시작 시각이 같은 반개방 구간은 겹치지 않는다.
- duration은 자동 이동 전후 동일하다.
- `expires_at`은 확정된 `planned_end_at`에 Gateway 설정의 lease grace period를 더해 계산한다. 예약이 뒤로 이동하면 함께 다시 계산한다.
- 업무 `due_at`을 넘기는 후보는 예약할 수 있지만 Gateway가 지연 이벤트를 남기고 재계획 정책을 실행한다.
- 병목 `exclusive_lock`은 시간 이동 대상이 아니라 현재 활성 Lock이 해제된 뒤 다시 취득한다.
- `time_slot` 예약을 `in_use`로 전환할 때 생성 컬럼의 유일 키 충돌이 발생하면 다시 예약 계산을 수행한다.

`reservation_id`는 fencing token으로 명령 payload에 포함한다. Adapter는 더 오래된 token의 늦은 명령을 실행하지 않는다.

## Schema reinforcements

### Inventory invariants

`inventory_lots`는 다음 조건을 DB에서 보장한다.

```text
available_qty >= 0
reserved_qty >= 0
reserved_qty <= available_qty
```

`inventory_moves`에 실제 수량과 예약 수량의 변화를 모두 감사할 수 있도록 다음 컬럼을 추가한다.

```text
reserved_delta INT NOT NULL DEFAULT 0
reserved_after INT NOT NULL DEFAULT 0
```

실제 수량 또는 예약 수량 변경은 `inventory_lots UPDATE`, `inventory_moves INSERT`, `operation_events INSERT`를 한 트랜잭션으로 처리한다.

### Recovery lineage

`jobs.parent_job_id` nullable self-reference를 추가한다. 단순 재전송은 같은 `job_step`의 `retry_count`를 증가시키고, 별도의 회수 또는 복구 절차는 `operation_type='recovery'`인 새 job으로 만들며 `parent_job_id`로 원본을 가리킨다.

### Idempotent external requests

`jobs.external_reference`를 unique key로 바꾼다. 내부 생성 job은 NULL을 사용할 수 있고 외부 요청은 전역적으로 유일한 UUID를 사용한다. 동일 요청이 재전송되면 기존 job을 반환한다.

### Optimistic job transitions

`jobs.revision BIGINT UNSIGNED NOT NULL DEFAULT 0`을 추가한다. UI 취소, RMF 완료, Safety 정지가 경쟁할 때 Gateway는 현재 revision과 허용된 이전 state를 조건으로 갱신한다. 조건부 갱신 결과가 0행이면 최신 job을 읽어 충돌 응답을 반환한다.

### Reservation validity and lookup

- `expires_at > created_at` CHECK를 추가한다.
- 병목 만료 조회를 위해 `(map_feature_id, state, expires_at)` 인덱스를 추가한다.
- 예약 만료 처리기는 만료된 활성 예약을 `expired`로 변경하고 연관 job/step을 재계획한다.

### Message retry

`integration_messages.next_attempt_at DATETIME(6) NULL`을 추가한다. Dispatcher는 `FOR UPDATE SKIP LOCKED`로 전송 대상을 선점하고 전송 전에 `attempts`, `sent_at`, `next_attempt_at`을 갱신한다. 전송은 at-least-once이며 Adapter가 `idempotency_key`를 내구성 있게 중복 제거해 물리 효과를 한 번만 적용한다.

전달 인덱스는 다음 순서로 구성한다.

```text
(direction, state, next_attempt_at, created_at)
```

### Dispatch and event indexes

- `jobs.priority_rank` generated column을 추가하고 `(state, priority_rank, due_at, created_at)`으로 배차한다.
- 전체 최신 운영 이벤트를 위해 `operation_events(occurred_at DESC)` 인덱스를 추가한다.

### Safety audit

`incidents`에 승인 이력을 위한 다음 컬럼을 추가한다.

```text
acknowledged_by_worker_id VARCHAR(64) NULL
acknowledged_at DATETIME(6) NULL
```

`operation_events`에는 판단 또는 조작 주체를 연결하는 `actor_worker_id VARCHAR(64) NULL`을 추가한다. VLM/RL 제안의 승인·거부는 `safety_decision`과 actor를 함께 기록한다.

## Transaction boundaries

다음 변경은 각각 하나의 MySQL 트랜잭션이다.

1. job, job_items, job_steps 생성과 최초 event 기록
2. job 배차, reservations 생성, outbound integration message 생성
3. inventory_lots 변경, inventory_moves 추가, event 기록
4. incident 상태 변경, safety message 생성, event 기록
5. inbound message 중복 확인, device/job 상태 반영, event 기록
6. recovery job 생성과 원본 job 상태 변경

Deadlock과 lock timeout은 동시성 경쟁의 정상 결과로 취급하고 Gateway가 제한된 횟수로 전체 트랜잭션을 재시도한다.

## UI integration

Flutter UI에 MySQL 드라이버를 넣지 않는다. 기존 동기식 `SqliteDataStore`를 억지로 원격 구현하지 않고, 비동기 `FmsApiClient`와 화면용 repository를 추가한다.

첫 수직 연동 범위는 다음과 같다.

1. Gateway `/health`와 `/ready`
2. `GET /devices`, `GET /inventory/lots`, `GET /jobs`
3. WebSocket을 통한 `device_states`, `jobs`, `incidents` 갱신
4. `POST /inventory/adjustments`
5. Flutter 재고 화면에서 변경 결과 확인

API 모드에서는 기존 SQLite 자동 demo seed를 비활성화한다. 개발 초기 데이터는 별도 seed SQL 또는 Gateway 관리 명령으로만 입력한다. 기존 SQLite 모드는 전환 기간의 회귀 테스트 용도로만 유지한다.

## Hardware-contract assumptions

실제 계약 확인 전에는 다음을 DB의 고정 의미로 확정하지 않는다.

- RMF task submit/cancel/replan API, fleet/robot 이름, `rmf_task_id` 생성 주체
- Pinky의 ROS 2 action/topic, frame, 단위, heartbeat, boot session과 상태 sequence
- Collision Monitor 정지 이벤트와 소프트웨어/하드웨어 E-stop 경계
- OMX/Cyclo/MoveIt skill 이름, tool/frame, 취소 가능 시점과 failure code
- 인계 정렬 허용 오차, 준비 완료 신호, 화물 소유권 전환과 검증 센서
- Adapter 재시작 후 idempotency key 보존 범위
- 통신 단절 시 각 장비의 독립 safe state와 최대 허용 지연

## Testing strategy

- 스키마 테스트: MySQL 8에서 DDL 적용과 CHECK/unique/FK 검증
- 예약 단위 테스트: 단일 충돌, 연속 충돌, 경계가 맞닿은 구간, 동시 요청, due/expiry 초과
- 재고 통합 테스트: 정상 조정, 예약 초과 거부, rollback 시 원장 미기록
- 메시지 통합 테스트: 동일 key 재전송, timeout 재전송, ACK 후 재전송 금지
- API 테스트: revision 충돌, 외부 참조 중복, Seoul offset 입출력
- UI 테스트: API 응답 표시와 WebSocket 갱신, API 모드에서 SQLite seed 미실행

## Out of scope for the first integration

- 실제 RMF/Pinky/OMX 하드웨어 명령 실행
- VLM/RL 모델 실행
- object storage 업로드 구현
- 장기 로그 아카이빙과 파티셔닝
- 기존 SQLite 데이터를 `trihouse_fms`로 자동 변환하는 일회성 마이그레이션
