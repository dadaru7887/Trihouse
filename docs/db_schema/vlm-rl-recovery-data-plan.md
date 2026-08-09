# VLM/RL 복구 데이터 경계 계획

> 상태: **설계 확정, DDL·Gateway 구현 전**
>
> 범위: Pinky의 예외 복구를 위한 Reference Memory와 Episodic Memory.
> 입고·출고·재고·예약 원장을 VLM/RL 학습 구조 때문에 변경하지 않는다.

## 1. 한 문장 결정

기본 주행 기준점은 `trihouse_fms`에서 관리하고 VLM/RL의 **Reference
Memory**로 함께 사용한다. 실제 복구 경험은 별도 `trihouse_recovery`에
**Episodic Memory**로 저장한다. SAC replay buffer와 TGRPO trajectory group은
DB 테이블이 아니라 RTX 5080의 임시 메모리다.

```text
같은 MySQL 서버
├─ trihouse_fms          운영 원장 + Reference Memory
└─ trihouse_recovery     복구 경험(Episodic Memory)

RTX 5080 RAM             학습 중에만 존재하는 buffer
```

## 2. 기존 v3의 역할을 바꾸지 않는 이유

`trihouse_fms` v3는 다음을 이미 책임진다.

```text
locations / devices / device_states
inventory_lots / inventory_moves
jobs / job_items / job_steps / reservations
incidents / operation_events / artifacts
```

| 기존 테이블 | 계속 맡는 역할 |
| --- | --- |
| `locations` | 대기점·충전점·작업장·`safe_node`의 위치와 현재 점유 상태 |
| `jobs`, `job_steps` | 입고·출고·파지·운반이라는 업무 진행 상태와 결과 |
| `operation_events` | YOLO/VLM 제안, Safety 승인·거부, Nav2 취소의 append-only 이력 |
| `incidents` | 운영자가 조치해야 하는 실제 안전 사고 |
| `artifacts` | 영상·rosbag·dataset·model의 URI와 SHA-256 |

`job_steps`는 RL transition 로그가 아니다. 예를 들어 `냉동 구역에서
포장대로 운반`이라는 업무 단계 안에서 `대기 → 짧은 후진 → 재합류`가 여러 번
일어날 수 있다. 이 짧은 실제 행동만 복구 DB의 `recovery_steps`에 둔다.

## 3. Reference Memory는 FMS에 둔다

### 3.1 이유

기본 주행 기준점과 Reference Memory를 서로 다른 DB에 복사하면 지도 revision이나
좌표 변경 후 두 시스템이 다른 위치를 볼 수 있다. 따라서 좌표의 원본은 계속
`trihouse_fms.locations` 하나다.

```text
locations
  = 이곳은 어디이며, 지금 예약 또는 점유되었는가?

location_recovery_profiles
  = 이곳은 복구 목표로 지금 믿고 써도 되는가?
```

`locations.state = 'available'`은 비어 있다는 뜻일 뿐 안전하다는 뜻이 아니다.
반대로 신뢰할 수 있는 기준점도 다른 Pinky가 예약했다면 사용할 수 없다. 두 상태는
서로 다른 축이므로 profile을 1:0..1로 분리한다.

### 3.2 향후 FMS 추가 테이블

VLM/RL 복구를 실제 구현하는 시점에만 `trihouse_fms`에 아래 테이블 하나를
추가한다. 기존 `locations` 컬럼, 이름, 좌표를 변경하거나 복사하지 않는다.

```text
locations 1 ─── 0..1 location_recovery_profiles
```

| 컬럼 | 의미 |
| --- | --- |
| `reference_node_uuid` | FMS와 recovery DB가 함께 쓰는 안정적인 UUID |
| `location_id` | `locations` FK. `location_type = 'safe_node'`인 행만 연결 |
| `map_revision` | 이 기준점이 검증된 지도 revision |
| `recovery_roles` | `wait`, `retreat`, `detour`, `rejoin` 허용 목록 |
| `availability_status` | `active`, `suspect`, `quarantined`, `retired` |
| `reliability_alpha`, `reliability_beta` | 안전/위험 관측 누적값 |
| `last_verified_at`, `last_outcome_at` | 검증과 실제 결과의 최신 시각 |
| `reviewed_by_worker_id` | 재활성화 검토자 (`workers` FK) |
| `revision` | Gateway의 낙관적 동시성 제어용 버전 |
| `notes` | 운영자 메모 |

초기에는 정적 기준점만 쓰므로 `locations.location_type = 'safe_node'`만으로
시작할 수 있다. 신뢰도·격리·지도 revision 검증이 필요한 때 이 profile을 추가한다.

### 3.3 갱신 권한과 지도 변경

```text
지도 또는 safe_node 변경
  → Gateway가 profile을 suspect로 전환하고 operation_events에 기록
  → VLM/RL cache를 무효화
  → 현재 map revision의 active profile만 다시 조회
```

- VLM/RL은 profile을 직접 수정하지 않는다.
- 안전 복구 결과는 Gateway에 보고한다.
- Gateway의 제한된 규칙만 `reliability_alpha/beta`를 갱신하거나 `suspect`로
  전환할 수 있다.
- `quarantined → active`는 `reviewed_by_worker_id`를 남기는 관리자 승인 후만
  가능하다.
- RMF/Nav2의 route graph와 실제 경로 계획은 계속 RMF/Nav2 설정이 원본이다.
  DB는 복구 목표로 허용된 안전 기준점만 관리한다.

## 4. Episodic Memory는 별도 DB에 둔다

### 4.1 `trihouse_recovery.recovery_episodes`

복구 Trigger부터 성공·중단·실패까지 한 사건을 저장한다.

| 컬럼 | 의미 |
| --- | --- |
| `recovery_episode_uuid` | 복구 사례의 UUID |
| `source_event_uuid` | FMS `operation_events.event_uuid`와 논리적으로 연결 |
| `device_id`, `fms_job_id`, `fms_job_step_id` | 어느 로봇과 업무 단계에서 발생했는지 |
| `map_name`, `map_revision` | 공간 문맥과 version gate |
| `trigger_type` | `blocked`, `person`, `low_visibility`, `localization` |
| `vlm_model_name/version` | VLM을 쓴 경우의 계보. rule-only이면 NULL |
| `recovery_policy_name/version` | 복구 정책 계보 |
| `started_at`, `ended_at`, `final_status` | 사건의 시간 범위와 결과 |
| `summary` | 사람이 읽는 간결한 결론 |

### 4.2 `trihouse_recovery.recovery_steps`

실제로 실행한 복구 행동 한 번을 저장한다. SAC replay의 원본은 이 테이블뿐이다.

| 컬럼 | 의미 |
| --- | --- |
| `recovery_step_id`, `recovery_episode_uuid`, `step_no` | 사례와 순서 |
| `reference_node_uuid` | 사용한 FMS Reference 기준점. 없으면 NULL |
| `action_type` | `wait`, `retreat`, `detour`, `rejoin`, `stop` |
| `target_pose` | 실제 Nav2에 전달한 목표 `(x, y, yaw, frame_id)` |
| `before/after_state_uri`, `before/after_state_sha256` | 실행 전후 관측 파일의 재현 가능한 참조 |
| `reward_components` | progress, clearance, time, intervention 보상 구성 |
| `outcome_class` | `safe`, `boundary`, `critical` |
| `execution_status`, `is_terminal` | 실제 실행 상태와 episode 종료 여부 |
| `started_at`, `completed_at` | 실행 시간 |

두 DB 사이에는 FK를 만들지 않는다. `reference_node_uuid`, `source_event_uuid`,
FMS job ID로 논리적으로 연결하고, Gateway가 존재 여부와 map revision을 검사한다.
이렇게 해야 운영 원장 백업·복구와 실험 DB의 보존 정책이 독립적이다.

## 5. 후보 로그와 replay buffer

```text
VLM 후보 생성 / Safety 승인·거부 / Nav2 취소
  → trihouse_fms.operation_events

실제로 실행한 복구 행동과 결과
  → trihouse_recovery.recovery_steps

SAC replay buffer
  → RTX 5080 RAM에서 recovery_steps export로 구성, 학습 종료 후 폐기

TGRPO trajectory group
  → GPU/RAM 임시 데이터, DB에 저장하지 않음
```

따라서 현재는 `safe_buffer`, `critical_buffer`, `candidate_rollouts`,
`reference_edges`, `policy_bundles`, `recovery_assessments` 테이블을 만들지
않는다. Safe/Boundary/Critical은 `outcome_class` 조건과 sampler 비율로 선택한다.

## 6. 구현 전 확인 항목

1. RMF/Nav2 map revision의 안정적인 문자열 형식
2. `safe_node`를 어떤 `locations` 행으로 등록할지
3. Gateway의 Reference 조회·복구 결과 보고 API 계약
4. rosbag/snapshot URI와 SHA-256을 생성하는 수집 경로
5. `suspect` 전환의 자동 기준과 관리자 재활성화 절차
6. SAC export의 최소 state/reward JSON schema

이 문서는 DB 경계와 데이터 계보의 설계만 확정한다. VLM/RL 복구 코드, 사람
쓰러짐 감지 코드, MySQL DDL, Gateway API는 이 문서만으로 새로 구현하지 않는다.
