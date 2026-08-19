# `trihouse_recovery` 주행 중 데이터 적재 — 설계 (2026-08-18)

## 0. 이 문서가 정하는 것

**주행 중 복구 사건이 일어날 때 `trihouse_recovery` 에 데이터가 실제로 쌓이게 한다.**

[VLM/RL 복구 데이터 스키마 설계](../superpowers/specs/2026-08-09-vlm-rl-recovery-schema-design.md)
가 그릇을 만들면서 "Gateway API와 VLM/RL 실행 코드는 이번 변경 범위에 포함하지
않는다"고 명시적으로 미뤄 둔 부분이다. 그 미뤄 둔 것을 여기서 만든다.

**전제**: [백엔드 다섯 층 수동 검증](2026-08-18-backend-manual-test-design.md)이 먼저
끝나야 한다. 그 문서 11.8 이 세는 **0행이 이 설계의 출발선**이고, L1~L5 가 도는 것을
확인하지 않은 채 적재를 얹으면 새 결함과 기존 결함을 가를 수 없다.

정하지 않는 것: VLM 추론 자체, SAC 학습 루프, 5080 AI 스택 기동. 이 설계는
**데이터가 쌓이는 경로**만 만든다.

## 1. 지금 무엇이 있고 무엇이 없는가

| | 상태 |
|---|---|
| `trihouse_recovery` DB + 테이블 2개 | **있다.** `schema_mysql.sql:979-1076` 이 만든다 |
| `trihouse_fms.location_recovery_profiles` (Reference Memory) | 테이블은 **있고 행이 0개**. seed 에 `safe_node` location 도 0개 |
| Gateway 의 두 번째 DB 연결 | **없다.** `config.py:23` 이 `trihouse_fms` 하나뿐 |
| Gateway 의 recovery 라우트 | **없다.** 44개 중 0개 |
| 3308 의 Gateway 사용자 권한 | **없다.** `db/init/003_grant_gateway_recovery.sh` 가 `compose.db.yaml`·`compose.db_test.yaml` 에만 마운트돼 있다 |
| episode 를 여는 코드 | **없다** |

그릇·권한·연결·라우트·기록자 다섯 중 **그릇 하나만 있다.**

## 2. 누가 써야 하는가 — 경계부터 정한다

[control_tower 책임 경계](../architecture/control_tower_boundary.md)가 두 줄로 못박아
두었다.

> - DB transaction: FMS Gateway만 수행
> - 상태 전이: Task Manager만 확정

그리고 [시스템 개요](../architecture/system_overview.md)의 금지 연결에 **"5080 →
MySQL 직접 연결"** 이 있다.

따라서 경로는 하나뿐이다.

```text
로봇 (ROS 토픽으로 관측을 낸다)
        │
        ▼
control_tower / recovery_recorder_node   ← 새로 만든다
   복구 사건의 시작·행동·끝을 판정한다
        │ HTTP
        ▼
FMS Gateway   ← 라우트 3개와 두 번째 DB 연결을 새로 만든다
        │ SQL
        ▼
trihouse_recovery.recovery_episodes / recovery_steps
```

**로봇이 DB 에 직접 쓰지 않는다. 5080 도 쓰지 않는다.** 관측은 로봇이 내고, 판정은
관제가 하고, 기록은 Gateway 가 한다. 이 저장소가 이미 `job_runner`·`executor_worker`·
`rmf_gateway_worker` 세 워커에 쓰고 있는 것과 같은 모양이다.

## 3. 무엇을 복구 사건으로 볼 것인가

스키마가 trigger 를 넷으로 못박았다(`chk_recovery_episodes_trigger`). 각각을 **이미
발행되는 토픽**에서 판정한다. 새 센서나 새 메시지 타입을 만들지 않는다.

| trigger | 무엇을 보는가 | 시작 조건 | 끝 조건 |
|---|---|---|---|
| `blocked` | `<ns>/trihouse/navigation/state` | Nav2 가 경로를 못 찾거나 recovery behavior 로 들어간 상태가 **2초 이상** 지속 | 정상 주행 복귀 또는 goal 종료 |
| `person` | `<ns>/trihouse/safety/state` 의 `STATE_PERSON_DETECTED` | 그 상태 진입 | `CLEAR` 복귀 |
| `low_visibility` | `<ns>/trihouse/vision/stream_health` | `state != 1`(HEALTHY) 가 **3초 이상** | HEALTHY 복귀 |
| `localization` | `<ns>/trihouse/status` 의 `errors` | `map_pose_stale` 이 나타남 | 사라짐 |

**히스테리시스를 두는 이유**: 순간적인 깜빡임까지 episode 로 만들면 학습 데이터가
잡음으로 채워진다. 지속 시간 문턱은 파라미터로 열어 두고 기본값을 위 표대로 둔다.

`recovery_steps.action_type` 은 `wait`/`retreat`/`detour`/`rejoin`/`stop` 다섯이다.
**우리가 행동을 새로 만들지 않는다** — Nav2 가 이미 하는 것을 이 다섯으로 분류해
기록한다. 분류 규칙은 4.3 에 둔다.

## 4. 만들 것

### 4.1 Gateway — 두 번째 DB 연결

`config.py` 에 `recovery_database: str = "trihouse_recovery"` 를 더한다. **같은 MySQL
서버의 다른 스키마**이므로 새 커넥션 풀이 아니라 **같은 연결에서 스키마를 한정한
쿼리**로 쓴다(`INSERT INTO trihouse_recovery.recovery_episodes …`). 두 DB 사이 FK 가
없으므로 트랜잭션을 걸칠 일도 없다.

**권한이 먼저다.** `compose.yaml` 의 mysql 서비스에 GRANT 스크립트를 마운트한다.

```yaml
- ./db/init/003_grant_gateway_recovery.sh:/docker-entrypoint-initdb.d/003_grant.sh:ro
```

`docker-entrypoint-initdb.d` 는 **최초 초기화에서만 돈다.** 3308 볼륨은 이미 초기화가
끝났으므로 마운트만으로는 권한이 생기지 않는다. 기존 볼륨에는 GRANT 를 한 번 손으로
적용해야 하고, **그것은 되돌릴 수 없는 운영 DB 조작이므로 승인 게이트를 세운다**(6절).

### 4.2 Gateway — 라우트 3개

`job_step` outcome 계열과 같은 모양을 따른다: `Idempotency-Key` 필수, 재호출은 원래
답을 돌려준다.

| 메서드 | 경로 | 무엇 |
|---|---|---|
| `POST` | `/internal/v1/recovery/episodes` | episode 를 연다. `final_status='running'`, `ended_at=NULL` |
| `POST` | `/internal/v1/recovery/episodes/{uuid}/steps` | 실행된 복구 행동 하나를 덧붙인다 |
| `POST` | `/internal/v1/recovery/episodes/{uuid}/close` | `final_status` 를 종료값으로 바꾸고 `ended_at` 을 채운다 |

읽기도 하나 둔다. 검증과 export 에 쓴다.

| 메서드 | 경로 | 무엇 |
|---|---|---|
| `GET` | `/api/v1/recovery/episodes` | `map_revision`·`final_status`·기간으로 거른 목록 |

**Gateway 가 검사해야 하는 것** — 스키마 CHECK 로는 못 하는 것들이다.

- `fms_job_id`·`fms_job_step_id`·`source_event_uuid` 가 **실제로 `trihouse_fms` 에
  있는지.** 두 DB 사이 FK 가 없으므로 이 검사가 유일한 참조 무결성이다.
- `map_revision` 이 job 이 쓰는 revision 과 같은지.
- `reference_node_uuid` 를 주면 그 location 이 `location_type='safe_node'` 인지.
  MySQL CHECK 는 다른 행을 조회할 수 없어 DDL 로 강제되지 않는다 — 스키마 설계
  문서가 이 책임을 명시적으로 Gateway 에 넘겼다.

### 4.3 관제 — `recovery_recorder_node`

`job_runner_node` 와 같은 모양의 호스트 ROS 프로세스다. **ROS 는 관측을 받기 위해서만
쓰고 Gateway 와는 HTTP 로만 말한다.**

- 로직은 `control_tower/recovery/recorder.py` 에 ROS·DB 의존 없이 둔다.
- 노드는 `control_tower/recovery/recorder_node.py` 에 두고 구독과 폴링만 한다.
- 로봇마다 하나의 상태 기계를 들고, 3절 표의 시작/끝 조건으로 episode 를 연다.

**행동 분류** — 관측에서 다섯 `action_type` 으로 옮기는 규칙이다.

| 관측 | `action_type` |
|---|---|
| `cmd_vel` 이 0 이고 goal 이 살아 있다 | `wait` |
| `cmd_vel.linear.x < 0` | `retreat` |
| Nav2 가 새 global path 를 냈고 원래 경로와 갈라진다 | `detour` |
| 갈라졌던 경로가 원래 경로로 되돌아왔다 | `rejoin` |
| goal 이 취소·중단됐다 | `stop` |

**보상 성분**은 `reward_components` JSON 에 네 가지를 넣는다. 스키마 설계 문서가
정한 구성(progress, clearance, time, intervention)을 그대로 쓴다.

| 성분 | 무엇에서 나오는가 |
|---|---|
| `progress` | 행동 전후 goal 까지 남은 거리의 차 |
| `clearance` | 행동 중 `scan` 최소 거리 |
| `time` | 행동 소요 시간(음의 보상) |
| `intervention` | 사람이 개입했는가 — `clear_emergency` 서비스 호출 또는 job 취소 |

**이번 범위에서 뺀 것**: `before_state_uri`/`after_state_uri`. 관측 스냅샷을 저장할
artifact 저장소 경로가 아직 정해지지 않았고, 스키마가 두 열을 NULL 허용으로 두었다.
**둘 다 NULL 로 남긴다** — `chk_recovery_steps_before_state` 가 "둘 다 NULL 이거나 둘
다 값" 을 요구하므로 반쪽으로 채우면 INSERT 가 거부된다.

### 4.4 Reference Memory — 이번에는 손대지 않는다

`location_recovery_profiles` 는 행이 0개고 `safe_node` location 도 0개다. 채우려면
**지도에 안전 노드를 새로 정의해야 하고**, 그것은 지도 작성 쪽 일이다.
`recovery_steps.reference_node_uuid` 는 NULL 허용이므로 **NULL 로 두고 진행한다.**

## 5. 검증 — 무엇으로 됐다고 말할 것인가

이 저장소의 관례대로 **고치기 전에 실패하는 테스트를 먼저 쓴다.**

| 층 | 테스트 |
|---|---|
| 순수 로직 | `recorder.py` 의 상태 기계 — 문턱 미만의 깜빡임은 episode 를 만들지 않는다, 네 trigger 가 각각 열리고 닫힌다, 다섯 `action_type` 분류 |
| Gateway 단위 | 라우트 3개의 `Idempotency-Key` 재호출, 없는 `fms_job_id` 거부, `safe_node` 아닌 `reference_node_uuid` 거부 |
| Gateway 통합 (3307) | 실제 MySQL 에 episode+step 을 넣고 `chk_recovery_steps_time`·`chk_recovery_episodes_time` 이 지켜지는지, 두 DB 사이 FK 가 여전히 0개인지 |
| 수동 (3308) | 시뮬 완주 중 사람이 로봇 앞을 막아 `blocked` 를 만들고, `recovery_episodes` 가 **0행 → 1행** 이 되는 것을 본다 |

마지막 줄이 이 설계의 통과 기준이다. **검증 문서 11.8 이 "0행" 을 관측한 바로 그
쿼리가 "1행" 을 내면 끝난 것이다.**

```sql
SELECT COUNT(*) FROM trihouse_recovery.recovery_episodes;
SELECT e.trigger_type, e.final_status, COUNT(s.recovery_step_id) AS steps
  FROM trihouse_recovery.recovery_episodes e
  LEFT JOIN trihouse_recovery.recovery_steps s USING (recovery_episode_uuid)
 GROUP BY e.recovery_episode_uuid;
```

## 6. 승인 게이트

| # | 조작 | 왜 |
|---|---|---|
| R1 | 3308 에 GRANT 를 손으로 적용 | 되돌릴 수 없는 운영 DB 권한 변경. initdb 는 이미 지나갔다 |
| R2 | 시뮬 주행 중 로봇 앞을 막는다 | 로봇이 움직이는 중에 사람이 개입한다. 안전 조건을 먼저 확인한다 |
| R3 | `fms_gateway` 이미지 재빌드 | 라우트가 늘어나므로 필요하다. 그 사이 Gateway 가 끊긴다 |

## 7. 남는 것 — 이 설계가 만들지 않는 것

정직하게 적는다. 아래는 데이터가 쌓이기 시작한 **뒤에** 판단할 일이다.

- **VLM 계보 열**(`vlm_model_name`/`vlm_model_version`)은 **NULL 로 남는다.** rule-only
  복구이기 때문이고, 스키마가 "둘 다 NULL 이거나 둘 다 값" 으로 그것을 허용한다.
  5080 이 붙으면 그때 채운다.
- **SAC replay export** 는 만들지 않는다. `recovery_steps` 가 그 원본이라는 것까지가
  스키마의 약속이고, 꺼내 쓰는 것은 학습 쪽 일이다.
- **`location_recovery_profiles` 의 베타 분포 갱신**(`reliability_alpha`/`beta`)도
  하지 않는다. 4.4 에서 Reference Memory 자체를 미뤘기 때문이다.
- **duration 표본과의 통합**도 하지 않는다. 검증 문서 11.9 가 확인하듯
  `job_step_attempts.metrics` 는 이미 쌓이고 `duration_baselines` 는 비어 있다. 둘을
  잇는 것은 스케줄링 쪽 일이다(검증 문서 14.7).
