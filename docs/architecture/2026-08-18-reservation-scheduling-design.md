# 예약 기반 작업 스케줄링 설계 (2026-08-18)

## 이 문서를 읽는 법

승인된 설계다. 구현은 아직 시작하지 않았다. 다음 세션은 8절의 순서를 위에서부터
따라가면 되고, 각 단계에 검증 방법이 붙어 있다.

환경을 다루는 방법(무엇이 어디에 떠 있는지, 테스트를 어떻게 돌리는지, 함정)은
[2026-08-18 P0 수동 테스트 절차](../validation/2026-08-18-p0-manual-test.md)에 있다.
이 문서는 그것을 되풀이하지 않는다.

## 1. 무엇을 고치는가

주문이 들어오면 로봇·로봇팔·포장 Dock 을 배정해야 한다. 지금 그 선택은
**first-fit** 이다.

```python
# control_tower/task_manager/job_runner.py:230
mobile = _first_free(devices, "mobile", reserved.mobiles)
arm = _first_free(devices, "arm", reserved.arms)
```

목록에서 처음 비어 있는 것을 집는다. 어느 로봇이 언제 끝날지, 어느 쪽이 가까운지
보지 않는다. 그래서 두 가지가 없다.

- **효율.** 곧 끝날 로봇이 있어도 목록 순서가 앞인 로봇을 기다린다.
- **순서.** 자원이 없으면 배정을 포기하고 다음 주기에 처음부터 다시 시도한다.
  줄이 없으므로 나중에 온 주문이 먼저 자원을 잡을 수 있고, 매 주기 같은 경고가
  반복된다(`job 4: no free robot, arm, or dock`).

그리고 한 번 잡은 자원이 **영구히 돌아오지 않는다.** 배정은 4시간 만료를 적어
두는데 그것을 걷어가는 코드가 없다.

```sql
-- fms_gateway/app/repositories.py:3525 부근
INSERT INTO reservations (job_id, device_id, reservation_mode, state, expires_at)
VALUES (%s, %s, 'exclusive_lock', 'reserved', DATE_ADD(NOW(6), INTERVAL 4 HOUR))
```

2026-08-18 실측: 예약 6건이 **만료 후 10시간**이 지나도 `reserved` 로 남아
PK_01·PK_02·OMX_01·OMX_02 와 Dock 두 곳을 붙잡고 있었다. 그래서 job 4·5 는
`no free robot` 으로 영구 대기했다. 실물에서 로봇이 멈추면 같은 일이 벌어진다.

## 2. 이미 있는 것 (다시 만들지 말 것)

조사해서 확인한 것들이다. 설계는 이것들을 **연결**하는 일이고 새 스케줄러를 만드는
일이 아니다.

| 있는 것 | 어디 | 무엇을 해 주는가 |
|---|---|---|
| 자원 배타성 | `db/schema_mysql.sql:604` `active_resource_key` + `UNIQUE KEY` | 같은 자원에 활성 예약이 둘 생기는 것을 **DB가** 막는다. 경쟁 상태에서도 안전하다 |
| 시간창 예약 정책 | `control_tower/rmf_adapter/traffic_reservation.py` | 단일 용량 통로에 대해 `start_s`~`end_s` 창을 앞으로 밀어 빈 자리를 찾는다 |
| 시간이 붙은 경로 | `control_tower/rmf_adapter/path_schedule.py` | Nav2 `ComputePathToPose` 로 **움직이기 전에** 경로를 계산해 시간이 붙은 itinerary 로 바꾼다 |
| 병목 lease | `control_tower/rmf_adapter/bottleneck.py` | 먼저 도착한 로봇이 통과권을 갖는다 |
| 사건 원장 | `operation_events` 테이블 | `severity`/`category`/`event_type`/`correlation_uuid` |
| 사람 판단 흐름 | `incidents` 테이블 | `state`: open/acknowledged/…, `acknowledged_by_worker_id` |
| 관제 실시간 피드 | `GET /api/v1/operations/ws` (`fms_gateway/app/main.py:690`) | UI 가 이미 사건을 tail 한다. 새 배관이 필요 없다 |

**할당 주체는 control_tower 다.** Open-RMF 의 `rmf_task_dispatcher` 도 입찰로 로봇을
고를 수 있지만, 이 시스템은 로봇을 지정해서 넘기고 RMF 가 다른 로봇을 배정하면
거부한다(`control_tower/rmf_adapter/rmf_gateway_worker.py:94-102`,
`ASSIGNMENT_MISMATCH`). 로봇 말고도 팔·Dock·충전기를 함께 배정해야 하므로 그 경계가
맞다. 그래서 ETA 할당을 control_tower 에 두는 것은 RMF 기능의 중복이 아니다.

## 3. 결정과 근거

**ETA 는 그래프 거리에서 시작해 실제 경로로 올린다.** 두 구현을 하나의 인터페이스
뒤에 둔다. 먼저 `nav_graph` 웨이포인트 거리 × 공칭 속도로 계산한다. 정확도가
목적이 아니라 **순서와 예약**이 먼저 필요하고, 이 방식은 로봇이 떠 있지 않아도
계산되므로 테스트로 증명된다. 나중에 `path_schedule` 기반으로 구현만 교체한다.

바로 실제 경로를 쓰지 않는 이유는 하나 더 있다. 후보 로봇마다 Nav2 가 살아 있어야
계산되는데, 이 개발 PC 에서는 부하 때문에 Nav2 기동 자체가 간헐 실패한다. 그러면
할당의 정확도가 아니라 할당의 **가능 여부**가 흔들린다.

**만료는 자원 종류를 구분하지 않고 전부 자동 해제한다.** 대신 원장과 현실이 어긋난
순간을 잡아 관제에 올려 사람이 판단하게 한다. 처음에는 병목 통로만 사람 승인으로
남기려 했으나, 규칙이 자원마다 갈리면 운영자가 무엇이 자동인지 기억해야 한다.
자동으로 통일하고 **이상을 보고하는 쪽**이 낫다.

**전방 예약은 스키마 변경 없이 된다.** `active_resource_key` 를 다시 읽으면:

```
reservation_mode = 'exclusive_lock' AND state IN ('reserved','in_use')  -> 활성 1개
reservation_mode = 'time_slot'      AND state = 'in_use'                -> in_use 1개
```

`time_slot` 은 `reserved` 를 배타성 판정에서 제외한다. 그래서 **한 로봇에 미래 창을
여러 개 걸 수 있고**(줄 서기), 실제 착수 때 `in_use` 로 올리면 그때 배타성이 걸린다.
스키마가 이 사용법을 이미 준비해 두었다.

## 4. 설계

### 4.1 ETA 추정기

```python
class EtaEstimator(Protocol):
    def estimate(self, *, start: str, via: Sequence[str]) -> float:
        """웨이포인트를 차례로 지나는 데 걸리는 초. 경로가 없으면 예외."""
```

`NavGraphEtaEstimator(graph, speed_m_s)` 가 첫 구현이다. `nav_graph` 의 lane 을 따라
최단 거리를 구하고 공칭 속도로 나눈다. 순수 함수이므로 로봇도 ROS 도 필요 없다.

공칭 속도는 지어내지 않는다. `pinky_pro` 의 Nav2 파라미터에 있는
`desired_linear_vel`(파생본 기준 0.2 m/s)을 정본으로 읽어 오고, 회전·감속 여유는
단일 계수 하나로만 둔다. 계수를 여러 개 두면 무엇이 오차의 원인인지 말할 수 없다.

### 4.2 로봇이 언제 비는가

로봇마다 활성 예약창의 끝을 본다.

```
available_at(robot) = max(now, 그 로봇의 reserved/in_use time_slot 중 가장 늦은 planned_end_at)
```

예약이 없으면 `now` 다. 이 값은 Gateway 가 예약 원장에서 계산해 돌려준다 — 주기 간
상태를 프로세스가 기억하지 않는다는 기존 `job_runner` 원칙을 지킨다.

### 4.3 할당

후보 로봇마다 완료 시각을 구해 가장 빠른 것을 고른다.

```
completion(robot) = available_at(robot) + eta(robot 현재 위치 -> 픽업 -> 포장 Dock)
```

동점은 robot id 의 사전순으로 깬다. 결정적이어야 테스트가 흔들리지 않는다.

고른 뒤 로봇·팔·Dock 에 `time_slot` 예약을 만든다. `planned_start_at` 은
`available_at`, `planned_end_at` 은 `completion` 이다.

`expires_at` 은 `planned_end_at + RESERVATION_GRACE` 로 둔다. `RESERVATION_GRACE` 는
설정값 하나이고 기본 10분이다. 4시간 고정은 짧은 작업에는 너무 길어 자원이 오래
잡히고, 긴 작업에는 짧아 정상 작업이 만료된다. 여유를 두는 이유는 ETA 가 낙관적일
때 정상 작업이 만료되지 않게 하는 것이고, 그래도 만료되면 4.6 이 그것을 보고한다.

값을 계수 하나로만 두는 이유는 오차의 원인을 말할 수 있게 하기 위해서다. 여유를
자원마다 다르게 두면 어떤 자원이 왜 일찍 풀렸는지 추적할 수 없다.

### 4.4 대기열

자원이 지금 없으면 배정을 **포기하지 않고** 미래 창을 예약한다. 그래서
`no free robot` 은 사라지고 `job N: 착수 예정 T` 가 한 번만 보고된다. 매 주기 같은
경고가 반복되지 않는다.

줄 순서는 `priority` 다음 `created_at` 이다. 이미 창을 잡은 job 은 나중에 온 job 에게
밀리지 않는다 — 예약이 곧 순서다.

선점(진행 중인 job 을 밀어내기)은 하지 않는다. 3절의 범위 밖이다.

### 4.5 만료 회수

새 프로세스를 만들지 않는다. 회수는 **Gateway 저장소 안**에서 한다. 행 잠금과 상태
전이 불변식이 이미 거기 있고, 두 곳에서 같은 전이를 하면 어긋난다.

```
POST /internal/v1/reservations/expire
  -> expires_at < NOW() 이고 state IN ('reserved','in_use') 인 예약을 'expired' 로.
     각 건마다 operation_event 를 남긴다(category='policy',
     event_type='reservation.expired').
     응답: 해제된 예약과 그때 job 이 활성이었는지.
```

`job_runner` 가 매 주기 이것을 먼저 호출한 뒤 배정을 계산한다. 그러면 다음 주기에
자원이 실제로 비어 보인다.

### 4.6 이상 보고

만료 자체는 정상일 수 있다(job 이 이미 끝났는데 예약만 남은 경우). 위험한 것은
**자원은 풀렸는데 로봇이 아직 거기 있을 수 있는 상태**다. P0 에서 정직하게 잡을 수
있는 신호는 하나다.

> 예약이 만료되어 해제됐는데, 그 job 의 현재 step 이 아직 종료 상태가 아니다.

이때 `incidents` 에 `incident_type='reservation_expired_while_active'`,
`severity='warning'`, `state='open'` 으로 열고 `operation_events` 에 같은
`correlation_uuid` 로 연결한다. 관제 UI 는 기존 WebSocket 으로 그것을 받는다.

사람이 `acknowledged` 로 바꾸기 전까지 그 job 은 다시 배정되지 않는다. 자동 재시도를
넣지 않는 것은 기존 판단과 같다 — 창고 한복판의 실물 로봇에게 무엇을 되풀이해도
안전한지는 별도 정책이다.

### 4.7 취소

```
POST /internal/v1/jobs/{job_id}/cancel
  헤더: Idempotency-Key (필수)
  본문: {"reason": str, "requested_by": str}
  -> 한 트랜잭션에서:
       jobs.state           -> 'cancelled'
       종료되지 않은 job_steps -> 'cancelled'
       활성 reservations     -> 'cancelled'
       operation_event 기록  (event_type='job.cancelled')
```

이미 `cancelled` 인 job 은 오류가 아니라 같은 응답을 돌려준다. 종료된 job(`succeeded`)
은 `409` 다 — 끝난 일을 취소했다고 말하면 원장이 거짓이 된다.

`control_tower/task_manager/lifecycle.py:56` 에 이미 `cancel(job_id, request_id,
confirmed)` 가 있다. 그 정책을 다시 쓰지 않고 Gateway 가 그 결정을 실행하는
경로로만 쓴다.

## 5. 데이터 변경

스키마 변경은 **없다.** 쓰는 방식만 바뀐다.

| 컬럼 | 지금 | 앞으로 |
|---|---|---|
| `reservation_mode` | 항상 `exclusive_lock` | 로봇·팔·Dock 은 `time_slot` |
| `planned_start_at` | 비어 있음 | `available_at` |
| `planned_end_at` | 비어 있음 | `available_at + eta` |
| `expires_at` | `NOW() + 4 HOUR` | `planned_end_at + 여유` |
| `state` | `reserved` 에서 멈춤 | `reserved` -> `in_use` -> `released`/`expired`/`cancelled` |

기존 6건(만료 10시간 초과)은 회수 경로가 생기면 첫 주기에 `expired` 로 정리된다.
그것이 이 작업의 첫 실측 검증이다.

## 6. 범위에서 뺀 것

- **선점.** 급한 주문이 진행 중인 job 을 밀어내는 것.
- **혼잡 반영 재계획.** ETA 는 한 번 계산하고 다시 재지 않는다.
- **다중 창고·다중 층.**
- **시간대별 인력 계획.** `time_slot` 을 사람 근무에 쓰는 것.

이것들을 지금 넣으면 검증할 수 없는 코드가 늘어난다.

## 7. 위험

**ETA 가 틀리면 줄 순서가 틀린다.** 그래프 거리는 회피·혼잡을 모른다. 완화는 두
가지다. 첫째, ETA 를 인터페이스 뒤에 두어 실제 경로 기반으로 바꿀 수 있게 한다.
둘째, 예약창이 실제보다 짧게 잡히면 만료가 먼저 오는데, 그때 4.6 의 이상 보고가
울리므로 **틀렸다는 사실 자체가 관측된다.**

**만료 자동 해제는 실물에서 위험할 수 있다.** 로봇이 병목에 멈춰 있는데 예약만
풀리면 다른 로봇이 들어간다. 그래서 4.6 이 필수이고 선택이 아니다. 실기 이행 전에
이 경로가 관제 화면에 실제로 뜨는지 사람이 확인해야 한다.

**`time_slot` 으로 바꾸면 배타성이 늦게 걸린다.** `reserved` 가 여럿 가능해지므로,
착수 시 `in_use` 로 올리는 전이를 빠뜨리면 두 job 이 같은 로봇을 동시에 쓴다고 믿게
된다. 그 전이는 반드시 Gateway 의 같은 트랜잭션 안에서 하고, 테스트로 못박는다.

## 8. 구현 순서

각 단계는 그 자체로 검증되고, 앞 단계를 되돌리지 않는다.

1. **취소 엔드포인트** (`fms_gateway`). 4.7 대로. 독립적이라 먼저 한다.
   *검증*: 단위 테스트(멱등, 예약 해제, 끝난 job 은 409) + 실제로 job 2·3 을 취소해
   PK_01·PK_02 가 회수되는지 확인.
2. **만료 회수 엔드포인트** (`fms_gateway`). 4.5 대로, 이상 보고 없이.
   *검증*: 만료된 예약이 `expired` 로 바뀌고 `operation_event` 가 남는가. 만료되지
   않은 예약은 건드리지 않는가.
3. **이상 보고 + 승인 경로** (`fms_gateway`, `control_tower/ui`). 4.6 과 10절 대로.
   incident 를 여는 것만으로는 끝나지 않는다 — 목록·승인 API 와 UI 버튼이 없으면
   열린 incident 를 아무도 닫지 못해 job 이 영구히 멈춘다.
   *검증*: job 이 활성인 채 만료되면 incident 가 열리고 끝난 job 이면 열리지 않는가.
   승인하면 그 job 이 다시 배정 대상이 되는가.
4. **`job_runner` 가 매 주기 회수를 먼저 호출.**
   *검증*: 노드 테스트에서 호출 순서가 회수 -> 배정인가.
5. **ETA 추정기** (`control_tower`). 4.1 대로. 순수 단위 테스트.
   *검증*: 알려진 그래프에서 알려진 거리를 낸다. 경로가 없으면 예외.
6. **`available_at` 조회** (`fms_gateway`). 4.2 대로.
   *검증*: 예약이 없으면 now, 있으면 가장 늦은 `planned_end_at`.
7. **할당을 ETA 최소화로 교체** (`control_tower`). 4.3 대로.
   *검증*: 바쁜 창을 주면 더 빨리 끝나는 로봇을 고르는가. 동점은 결정적인가.
8. **`time_slot` 전방 예약과 대기열** (양쪽). 4.3·4.4 대로.
   *검증*: 한 로봇에 `reserved` 둘은 되고 `in_use` 둘은 DB 가 막는가. `no free robot`
   대신 착수 예정이 한 번만 보고되는가.
9. **`in_use` 전이.** 착수 시점에 올린다.
   *검증*: 전이를 빠뜨리면 실패하는 테스트가 있는가(7절의 위험).
10. **ETA 를 실제 경로로 교체** (`PathScheduleEtaEstimator`). 구현만 바꾼다.
    *검증*: 5번의 테스트를 인터페이스 수준에서 재사용.

1~4 까지만 해도 "잡힌 자원이 돌아온다" 는 오늘의 문제는 해소된다. 5~9 가 사용자가
요청한 효율적 할당이고, 10 은 정확도 향상이다.

## 9. 열린 질문

- **공칭 속도의 정본.** 파생 Nav2 파라미터의 `desired_linear_vel` 을 읽을지, 별도
  설정 값을 둘지. 전자를 권한다 — 값이 두 곳에 있으면 갈라진다.
- **로봇의 현재 위치.** ETA 의 출발점이 필요하다. `status` 의 `pose`(frame_id 가
  `map` 일 때만 유효)를 가장 가까운 웨이포인트로 눌러 쓸 수 있다. 로봇이 아직
  위치추정을 못 하면 ETA 를 낼 수 없으므로, 그때는 충전기 웨이포인트를 출발점으로
  두는 것이 안전한 기본값이다.
- ~~`incidents` 를 사람이 처리하는 화면.~~ **확인했다. 없다.** 아래를 보라.

## 10. 확인된 공백: 사람이 판단할 경로가 아직 없다

4.6 은 사람이 판단하는 것을 전제하는데, 그 경로가 지금 끊겨 있다.

- `incidents` 테이블은 있다(`state`, `acknowledged_by_worker_id` 포함).
- **Gateway 에 incidents API 가 없다.** `fms_gateway/app/main.py` 에 `incident` 를
  다루는 엔드포인트가 하나도 없다.
- 관제 UI(`control_tower/ui/operations/operations.js:22`)는 `incidents` 를 보여 주지만
  **읽기 전용**이고, 그나마 지금 보여 주는 것은 카메라 기반 항목이다(`camera_id`,
  `location_id` 를 가진다). 상태를 `확인됨`/`확인 필요` 로 표시할 뿐 승인을 보내는
  경로가 없다.

그래서 8절 3번 단계는 incident 를 **여는** 것만으로 끝나지 않는다. 최소한 이 둘이
함께 필요하다.

```
GET  /api/v1/incidents?state=open      열린 항목 목록
POST /api/v1/incidents/{id}/acknowledge {"worker_id": str, "note": str}
```

그리고 UI 에 승인 버튼 하나. 이것이 없으면 incident 는 열리기만 하고 아무도 닫지
못하며, 4.6 이 "그 job 은 승인 전까지 재배정하지 않는다" 고 정한 규칙 때문에 job 이
**영구히 멈춘다** — 지금 job 2·3 이 자원을 붙잡고 있는 것과 같은 종류의 교착을 새로
만드는 셈이다.

대안은 4.6 을 "보고만 하고 막지는 않는다" 로 낮추는 것이다. 그러면 UI 작업 없이도
진행할 수 있지만, 로봇이 병목에 남아 있을 수 있는 상태에서 다음 job 이 그대로
들어간다. **승인 경로를 함께 만드는 쪽을 권한다.** 사람이 판단하게 하려면 판단을
입력할 곳이 있어야 한다.
