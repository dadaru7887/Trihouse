# 목표 대비 현재 상태와 다음 할 일

작성: 2026-08-19 · 브랜치 `feat/pinky-edge-agent` (미커밋 변경 21 + 신규 5)
근거: `docs/{architecture,database,deployment,requirements}` + `docs/claude` 대조 및 **실행 중인 시스템 실측**

목표를 다시 적는다.

> 물류센터 **입/출고**와 **비상상황(작업자 쓰러짐)** 자동화. 그 안에서 **로봇 2대**가
> 여러 작업을 **스케줄링**으로 시간 효율적으로 처리한다. **주행 로봇과 로봇팔이
> 병렬로** 움직이고, 로봇이 적재 장소에 **도착하기 전에** 팔이 이미 파지 중이어야 한다.

---

# 갱신 — 2026-08-19 04:20 · **로봇이 처음으로 주행했다**

> 아래 0~7절은 04:20 이전에 쓴 것이다. **이 절이 최신이고, 충돌하면 이 절이 맞다.**

## U1. 번호 체계를 바로잡는다 — 이 문서가 낡았다

`docs/claude/p0-stack-reference.md` **10절이 결함 번호의 정본**이다. 이 문서에서
쓰던 D13~D18 은 **폐기한다.** 내가 찾은 것들은 이미 레퍼런스 번호로 흡수돼 있다.

| 레퍼런스 | 무엇 | 상태 |
|---|---|---|
| **D13** | Nav2 SUCCEEDED 와 정차 사이 대기 없음 → `robot is not idle` | **고침 (이번 세션)** |
| D14 | 시뮬 launch 에 `safety_supervisor` 없음 → cmd_vel 이 모터에 안 닿음 | 고침 |
| D15a | 시뮬 센서 주기가 안전 gate 보다 느림 | 고침 |
| **D15** | 순간 안전정지가 `dispatchable` 을 떨어뜨려 로봇을 fleet 에서 빼냄 | **미수정, 근본** |
| D16 | 취소한 job 을 러너가 되살림 | 고침 |
| D17 | `sim_teardown` 이 `camera_streamer` 를 안 죽여 세대 겹침 | 고침 |
| D18 | bringup 셸 닫으면 SIGHUP 으로 시뮬 전체 사망 | 미수정, 운용 |

**아직 레퍼런스에 없는 것은 아래 U4 에 D19~D22 로 제안한다.** 번호를 붙이기 전에
다른 창과 겹치지 않는지 확인이 필요하다.

## U2. 다른 창이 한 것 (04:00~04:03) — 검증함

| 시각 | 무엇 | 확인 |
|---|---|---|
| 04:00 | Gateway 재빌드 | `JOB_ALREADY_TERMINAL` 컨테이너에 **2** (이전 0). 별도 프로젝트 안 생김 |
| 04:03:25 | job 17 취소 | `cancelled` 로 **유지됨** → **D16 검증 완료** |
| 04:03:26 | job 18 자동 배정 | 큐에서 PK_01 을 받아 스스로 시작 |

정정 하나 — 이전 창이 "D11-b 가 컨테이너에 없다"고 적었으나 **있었다**
(`execute_fms_action` 3개). 01:42 재빌드에 이미 포함됐다. 재빌드가 필요했던 이유는
D16 하나다.

## U3. 로봇이 실제로 주행했다 — 이번 세션 최대 성과

```
[PK_01] RMF compose.dispatch-d79d39763c -> (0.841, -0.111, -1.089)   ← BOTTLENECK-01
[PK_01] Pinky 도착·정지 확인 후 RMF 이동을 완료했습니다.               ← ★ D13 수정 작동
[PK_01] RMF compose.dispatch-d79d39763c -> (1.201, -0.799, -1.089)   ← frozen dock
```

RMF 입찰(`cost 264.67`) → 낙찰 → PK_01 → **두 구간 이동 명령.** 첫 구간을 완주하고
**정차 판정을 통과해** 다음 구간으로 넘어갔다.

**두 번째 줄이 D13 수정의 실측 증거다.** 정차 대기가 없었다면 그 자리에서
`"waiting for stop"` 이 나고 phase 가 `NAVIGATING` 에 갇혀 이후 전부
`robot is not idle` 이 됐을 것이다.

판정 지표 전부 **0** — 남은 문제가 부하나 타이밍이 아니라는 뜻이다.

```
Unable to replan       0      robot is not idle      0
sensor_timeout         0      no running event loop  0
ASSIGNMENT_MISMATCH    0      RMF_TASK_REJECTED      0
```

### 그런데 원장은 실패로 적혀 있다

```
job 18  step 20 (navigate)  state=failed
  dispatch_task_request  dead_letter  attempts=5   DISPATCH_ATTEMPTS_EXHAUSTED
  execution_command      dead_letter  attempts=5   DISPATCH_ATTEMPTS_EXHAUSTED
job runner blocked: job 18: step 115 is failed     (매 주기 반복)
```

**로봇은 움직이는데 원장이 그것을 모른다.** 즉 **남은 것은 주행이 아니라 보고 계층이다.**
이건 큰 진전이다 — 물리·경로·교통·정차는 전부 통과했다.

## U4. 남은 벽 셋 — 전부 보고 계층 (D19~D21 제안)

| 제안 | 무엇 | 증거 | 크기 |
|---|---|---|---|
| **D19** | **Gateway 가 로봇 telemetry 를 거절한다.** `tcp_protocol.py:66-73` 이 `robot_status`·`task_event`·`heartbeat` 만 받는데 로봇은 `telemetry` 를 보낸다 | `FMS rejected telemetry/event: MESSAGE_TYPE_UNSUPPORTED` **× 42** | 작다 |
| **D20** | **낙찰 결과가 원장으로 안 돌아온다.** RMF 는 PK_01 에 낙찰했는데 워커가 `result.assignment is None` 으로 보고 `RMF_ASSIGNMENT_PENDING` 을 5회 반복 → `dead_letter` | `RMF dispatch cycle: claimed=1 accepted=0 rejected=0 indeterminate=1` 반복 | 중간 |
| **D21** | **`execution_command` 가 409 로 죽는다** | `executor error: step 115: HTTP Error 409: Conflict` **× 5** | 중간 |
| **D22** | `DISPATCH_ATTEMPTS_EXHAUSTED` 가 개별 거절 사유를 덮어써 원인이 DB 에 안 남는다 | 위 셋의 원인을 DB 만 보고는 못 찾았다. 로그가 있어서 찾았다 | 작다, 진단성 |

**D20 은 D8(assignment observer 배선)이 고쳤어야 하는 것이다.** 레퍼런스가 이미
단서를 적어 두었다 — **"`task_summaries` 는 publisher 는 있으나 아무것도 흐르지
않는다. `fleet_states` 가 실제 창구다."** observer 가 빈 토픽을 보고 있을 가능성이
가장 크다. 거기부터 확인한다.

## U5. RTF — 지금은 고치지 않는다

```
real_time_factor  0.216 / 0.085 / 0.127        step_size 0.001  ← 벤더 물리
load average      62.15
```

`p0_world.sdf`(250Hz/0.004/iters 50)가 여전히 미배선이고
(`p0_simulation_bringup.sh:187`), 카메라 1280×720@30 `always_on` 이 GPU 없이
소프트웨어 렌더링 중이다.

**그런데 이 상태에서도 로봇이 주행했다.** 그리고 판정 지표가 전부 0이므로 **남은 벽
셋은 부하와 무관하다.** RTF 수정은 재기동이 필요하고, D17 수정 덕에 처음으로 깨끗해진
세대를 버리게 된다. **보고 계층 셋을 고친 뒤로 미룬다.**

## U6. 다음에 할 일 — 이 순서

### 1. D19 (가장 작다, 먼저)

`fms_gateway/app/tcp_protocol.py:66-73` 이 받는 타입과 로봇이 보내는 타입이 다르다.
**어느 쪽이 정본인지 먼저 정해야 한다** — Gateway 에 `telemetry` 를 추가할지,
로봇이 `robot_status` 로 보내게 할지. 프로토콜 계약 문서를 확인한 뒤 고친다.
42건이 계속 쌓이므로 로그도 이것으로 덮인다.

### 2. D20 (완주를 직접 막는 것)

`RosTaskSummaryObserver` 가 구독하는 토픽을 확인한다. `task_summaries` 면
`fleet_states` 로 바꾼다. 그게 맞으면 `dispatch_task_request` 가 `accepted` 로 닫히고
step 20 이 `running` 으로 넘어간다.

확인 명령:

```bash
export ROS_DOMAIN_ID=0
grep -n "create_subscription\|task_summaries\|fleet_states"   control_tower/rmf_adapter/ros_task_client.py
```

### 3. D21 (409 의 실제 원인)

멱등키 충돌인지 상태 충돌인지 구분한다. D11-a 가 멱등키를
`rmf:{task}:robot:{robot}:rev:{revision}` 로 바꿨으므로, 같은 revision 에서 두 번
쓰면 409 가 정상 동작일 수도 있다. **그렇다면 결함은 409 자체가 아니라 그것을
재시도로 처리하는 쪽이다.**

### 4. 그다음 — 다시 완주 시도

job 18 은 step 20 이 `failed` 라 되살릴 수 없다. **취소하고 새 주문**을 넣는다.
재고가 SKU 당 1 lot 이므로 지난 SKU 와 다른 것을 쓴다.

### 보류 (완주 기준선 뒤로)

| 무엇 | 왜 미루나 |
|---|---|
| RTF (`p0_world.sdf` 배선, 카메라) | 주행이 이미 됐다. 판정 지표 0 |
| D15 (안전정지가 로봇을 fleet 에서 빼냄) | 지금 안 터진다. 근본이지만 급하지 않다 |
| `locations` 접두사 정리 | `map_revision` 이 바뀌어 재기동이 필요하다 |
| 병렬(팔 ∥ 주행), 2대 스케줄링 | 완주 기준선이 먼저 (§5 의 이유 그대로) |

## U7. 사용자가 직접 해야 하는 것 하나

재고 `reserved 2` 가 갇혀 있다(D2 — 취소가 `reserved_qty` 를 안 돌려준다).
자동 모드가 운영 원장 직접 `UPDATE` 를 차단한다.

```bash
cd /home/syw/Trihouse
PW=$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)
docker exec trihouse-mysql mysql -uroot -p"$PW" --table -e "
UPDATE trihouse_fms.inventory_lots SET reserved_qty = 0 WHERE reserved_qty > 0;
SELECT SUM(available_qty) AS avail, SUM(reserved_qty) AS reserved FROM trihouse_fms.inventory_lots;
" 2>&1 | grep -v 'password on the command line'
```

기대 `avail 17 / reserved 0`. **다음 주문을 넣기 전에 필요하다.**

## U8. 축별 상태 갱신 (0절 표를 대체한다)

| 축 | 요구 | 코드 | 런타임 | 완주 |
|---|---|---|---|---|
| **1. 출고** | UR_02 | ✅ | ✅ | ⚠️ **주행은 됨. 보고 계층 3개 남음** |
| 2. 입고 | UR_01 | ⚠️ 부분 | ❌ 진입점 없음 | ❌ |
| 3. 비상(쓰러짐) | UR_10 | ✅ 있음 | ❌ import 0곳 | ❌ |
| 4. 2대 스케줄링 | UR_06 | ⚠️ first-fit | ✅ | ❌ 1대만 |
| 5. 팔 ∥ 주행 병렬 | UR_13 | ❌ 구조적 불가 | — | ❌ |

**축 1이 "주행 미확인" 에서 "주행 확인, 보고 미확인" 으로 올라갔다.**

---

## 0. 한 장 요약

목표를 다섯 축으로 갈라 각각의 실제 상태를 적는다. **"코드가 있다"와 "런타임에
돈다"는 다른 것이다** — 이 구분이 이 문서의 핵심이다.

| 축 | 요구 | 코드 | 런타임 연결 | 완주 확인 |
|---|---|---|---|---|
| **1. 출고** | UR_02 | ✅ 완성 | ✅ | ❌ **마지막 벽 1개** |
| **2. 입고** | UR_01 | ⚠️ 부분 | ❌ **진입점 없음** | ❌ |
| **3. 비상(쓰러짐)** | UR_10 | ✅ 있음 | ❌ **import 0곳** | ❌ |
| **4. 2대 스케줄링** | UR_06, UR_03/04 | ⚠️ first-fit | ✅ | ❌ 1대만 |
| **5. 팔 ∥ 주행 병렬** | UR_13 | ❌ **구조적 불가** | — | ❌ |

**가장 중요한 사실:** 축 1(출고 1건 완주)이 **한 번도 성공한 적이 없다.** 축 4·5는
그 위에 얹는 것이다. 완주가 안 된 상태에서 스케줄러를 바꾸면 새 결함과 기존 결함을
가를 수 없다 — `START-HERE.md` 0절이 정한 순서(검증 → 구현)가 그 이유다.

**축 1은 벽 하나만 남았고, 그 벽의 원인은 이번 세션에 코드로 확정했다.**

---

## 1. 축별 상세 — 무엇이 되어 있는가

### 1.1 출고 (UR_02) — 코드 완성, 완주 직전

주문 1건이 만드는 7단계가 DB에 실물로 있다. **사용자가 원한 경로와 정확히 같다.**

| step | executor | action | 위치 | 뜻 |
|---|---|---|---|---|
| 10 | arm | pick | `WH-FRZ-01-DOCK-01` | 팔이 집는다 |
| 20 | mobile | navigate | `frozen_storage_loading_dock_01` | **적재 장소로** |
| 30 | fms | load | 〃 | 적재 확정(게이트) |
| 40 | mobile | navigate | `packing_station_loading_dock_01` | **포장대로** |
| 50 | fms | handover | 〃 | 작업자 인계 |
| 60 | fms | wait | 〃 | 작업자 완료 대기 |
| 70 | mobile | return_home | → `charging_station_01` | **충전소 복귀** |

5층(DB → Gateway → 관제 → 로봇 → 로봇팔)이 이어 붙어 실제로 도는 것까지 확인됐다.
직전 세션들이 결함 **D1~D12 중 11개를 고쳤고** 전부 테스트가 붙어 있다.

마지막으로 확인된 지점 — **로봇이 RMF 작업을 손에 들었다.**

```
step 20        running
rmf_task       compose.dispatch-75bb442d4a
fleet_states   robot=PK_01  task_id='compose.dispatch-75bb442d4a'  mode=0
```

**남은 것은 바퀴가 도는 것 하나다.** 막는 것이 `[PK_01] robot is not idle` 이고,
그 원인을 이번 세션에 확정했다(§2.1).

### 1.2 입고 (UR_01) — 진입점이 없다

| 있는 것 | 없는 것 |
|---|---|
| 스키마: `chk_jobs_type CHECK (operation_type IN ('inbound','outbound',...))` (`db/schema_mysql.sql:407`) | **주문 API가 outbound 전용.** `models.py:160` 이 `Literal["outbound"] = "outbound"` |
| `inventory_lots.state` 에 `pending_inbound` (`:353`) | **입고 step 시퀀스가 없다.** `planned_outbound_steps()` 만 있다 |
| `inventory_workflow.py:58,112` — `reserve_inbound_slot`, `finalize_inbound` | 그 두 함수를 **부르는 곳이 없다** (테스트 제외) |
| `locations` 에 온도 구역별 slot 12개 (ambient/chilled/frozen 각 4) | 입고품을 **어느 구역에 넣을지 정하는 정책**이 실행 경로에 없다 |

즉 **그릇과 부품은 있고 조립이 안 되어 있다.** `POST /api/v1/orders`
(`main.py:267`)는 `create_outbound_order` 하나뿐이다.

### 1.3 비상 — 작업자 쓰러짐 (UR_10) — 코드는 있으나 아무도 부르지 않는다

이게 가장 크게 벌어진 곳이다.

```
control_tower/task_manager/emergency_workflow.py   236줄, 클래스 6개
  EmergencyWorkflow.open / blocks_assignment / affect_robot / release
  + decide / dismiss / is_held / decisions
```

**grep 결과: 이 클래스를 import 하는 곳은 테스트 2개뿐이다.**
`test_emergency_workflow.py`, `test_emergency_camera_selection.py`.
**런타임 경로 0곳.**

이건 레퍼런스가 D8에서 지적한 것과 **정확히 같은 종류**다 — "모듈이 존재하는 것과
런타임에 도는 것은 다르다". 그 표에 세 개가 이미 올라 있었고(`bottleneck.py`,
`traffic_reservation.py`, `RosTaskSummaryObserver`), **`EmergencyWorkflow` 가 네 번째다.**

감지 쪽도 끊겨 있다.

| 층 | 상태 |
|---|---|
| 쓰러짐 감지 모델 | `vision_perception/test/worker-fall-detection/` — **`test/` 아래의 실험 폴더**다. 학습·시각화·데이터로더가 있다 |
| 감지 → Gateway | 연결 확인 못 함 |
| `incidents` 테이블 | 존재. **행 0개** (실측) |
| Gateway incidents API | **없다.** 설계 10절이 이미 "`main.py` 에 `incident` 엔드포인트가 하나도 없다"고 확인 |
| 관제 UI | `incidents` 를 **읽기 전용**으로만 표시. 승인 버튼 없음 |

**결론: 쓰러짐을 감지해도 그것이 관제에 도달해 로봇을 멈추게 하는 경로가 없다.**

### 1.4 2대 스케줄링 (UR_06, UR_03/04) — 설계 승인, 절반 구현

`docs/claude/2026-08-18-reservation-scheduling-design.md` 8절의 10단계 중:

| # | 무엇 | 상태 |
|---|---|---|
| 1 | 취소 엔드포인트 | ✅ `main.py:900` |
| 2 | 만료 회수 | ✅ `main.py:925` |
| 3 | 이상 보고 + 승인 경로 | ✅ 커밋 `46316c7f` |
| 4 | 러너가 매 주기 회수 먼저 | ✅ 커밋 `237ad0df` |
| **5** | **ETA 추정기** | ❌ |
| **6** | **`available_at` 조회** | ❌ |
| **7** | **할당을 ETA 최소화로** | ❌ **← "시간 효율" 이 여기다** |
| **8** | **`time_slot` 전방 예약 + 대기열** | ❌ |
| **9** | **`in_use` 전이** | ❌ |
| **10** | **실제 경로 기반 ETA** | ❌ |

**지금 할당은 first-fit** — 비어 있는 첫 로봇을 잡는다. 설계가 스스로 적었듯
**단일 로봇에서는 first-fit과 ETA 최소화의 결과가 같다.** 그래서 5~10이 미뤄졌다.
**2대가 되는 순간 그 등가성이 깨지고, 그때부터 "시간 효율"은 5~10 없이는 없다.**

2대 운용 자체를 막는 것도 둘 있다.

| 막는 것 | 근거 |
|---|---|
| 부하 — 12코어에서 2대는 load 60~130, Nav2 lifecycle이 포기 | handoff 8절. GPU 없음(실측: `nvidia-smi` 없음) |
| 병목 교착 — 창고→포장이 mutex 두 개를 **연속** 요구 | `nav_graph.yaml`. `path_schedule.py` 미연결 |

### 1.5 팔 ∥ 주행 병렬 (UR_13) — 구조적으로 불가능

**목표:** 로봇이 도착하기 전에 팔이 파지 중.
**현실:** 팔이 **완전히 끝난 뒤에야** 로봇이 출발한다.

설계는 병렬을 정확히 표현한다.

```python
# control_tower/task_manager/outbound_sequence.py:103,128  ← 같은 선행조건 = 병렬
"dependencies": inherited_dependencies,
# :143  ← 합류 게이트
"dependencies": [pick_no, navigate_no],
"gate": "PINKY_READY+OMX_READY",
```

실행기는 그것을 읽지 않는다.

```python
# control_tower/task_manager/job_runner.py:113
for step in sorted(steps, key=lambda step: step.step_no):
    if step.state != "succeeded":
        return step                      # ← step_no 최솟값 하나만

# control_tower/task_manager/job_runner.py:238-240
if step.state == "running":
    cycle.awaiting.append(detail.job_id); return   # ← 그게 도는 동안 아무것도 안 한다
```

**grep: `dependencies` 를 쓰는 곳 7군데, 읽는 곳 0군데. `gate` 도 0군데.**

```
지금:  pick(10) 완료 ──▶ navigate(20) ──▶ load(30)      소요 = pick + navigate
목표:  pick(10) ──┐
       navigate(20) ┴─▶ load(30) 게이트                 소요 = max(pick, navigate)
```

게이트 `PINKY_READY+OMX_READY` 는 **한 번도 평가되지 않는다.**

---

## 2. 이번 세션에 새로 확정한 것

### 2.1 `robot is not idle` 의 근본 원인 — 코드로 확정 (D16)

직전 세션이 "원인을 모른다"고 남긴 마지막 벽이다.

```python
# fleet_node.py:84 — odom 콜백이 정차 여부만 갱신한다
self.stationary = abs(twist.linear.x) <= 0.01 and abs(twist.angular.z) <= 0.02

# fleet_node.py:195 — nav 결과가 온 그 순간에 딱 한 번 묻는다
arrived = self.workflow.nav_result(succeeded=..., stationary=self.stationary)

# workflow.py:72-73 — 안 멈춰 있으면 phase 를 그대로 둔다
if not stationary:
    return WorkflowResult(True, False, self.phase, "waiting for stop")

# workflow.py:54-55 — 이후 모든 명령이 여기서 거절된다
if self.phase is not JobPhase.IDLE:
    return WorkflowResult(False, False, JobPhase.REJECTED, "robot is not idle")
```

**연쇄:**

1. Nav2 `NavigateToPose` 는 goal tolerance 안에 들어오면 SUCCEEDED 를 준다.
   **속도 0을 요구하지 않는다.**
2. `velocity_smoother` → `collision_monitor` 체인 때문에 `cmd_vel` 은 그 뒤
   0.2~0.5초 더 감쇠한다. 즉 **결과가 도착하는 순간 로봇은 아직 굴러간다.**
3. `stationary=False` → phase 가 `NAVIGATING` 에 남는다.
4. **`nav_result` 를 다시 부르는 코드가 없다.** 호출 지점 152·163·195 중 앞 둘은
   실패 경로. `create_timer` **0곳**. odom 콜백은 workflow 를 건드리지 않는다.
5. **한 번의 타이밍 레이스가 로봇을 재기동 전까지 못 쓰게 만든다.**

**결함은 `workflow` 가 아니라 호출자에 있다.** `nav_result` 는 (succeeded, stationary)
의 순수 함수이고 `"waiting for stop"` 은 "정차한 뒤 다시 물어라"는 **정확한 대답**이다.
`cancel_navigation()` 이 `IDLE` 로 되돌리는 출구도 이미 있다. **한 번 묻고 포기하는
`fleet_node` 가 결함이다.**

**기존 테스트가 놓친 이유:** `test_pinky_sr_policies.py:141` 이 `nav_result` 를
**연달아 두 번** 부른다(`stationary=False` → `True`). 그 테스트는 운영 코드가 하지
않는 재폴링을 스스로 해 주고 있었다. D11-b의 "InMemory double이 실제와 달라
재현되지 않았다"와 같은 종류다.

**부하와 무관하다.** RTF 0.19에서든 0.71에서든 감쇠 시간은 그대로다.

### 2.2 `p0_world.sdf` 가 bringup 에 연결되지 않았다 (D15)

RTF 0.19 → 0.71을 만든 파일이 **쓰이지 않는다.**

```bash
# control_tower/bringup/p0_simulation_bringup.sh:187  ← 벤더 world 하드코딩, override 없음
PINKY_WORLD="$(ros2 pkg prefix pinky_gz_sim)/share/pinky_gz_sim/worlds/empty.world"
```

| | 지금 쓰이는 것 | `p0_world.sdf` |
|---|---|---|
| `real_time_update_rate` | 1000.0 | **250.0** |
| `max_step_size` | 0.001 | **0.004** |
| `iters` | 150 | **50** |

**다음 bringup 은 조용히 RTF 0.19로 되돌아간다.**

### 2.3 테스트 격리 결함이 두 곳 더 있다 (D17)

| 대상 | 함께 돌릴 때 | 단독 |
|---|---|---|
| `trihouse_rmf_bridge/test/test_office_service.py` | ERROR 2 | **2 passed** |
| `trihouse_pinky_vision/test/test_camera_streamer_node.py` | ERROR 5 | **5 passed** |

레퍼런스의 "`fms_gateway/tests/unit` 는 단독으로 돌린다"와 같은 종류다.

---

## 3. 지금까지 된 작업 — 수동 확인 명령어

**전제: 매 터미널에서 `export ROS_DOMAIN_ID=0`.** 실행 중 컨테이너가 0이고 스크립트
기본값은 52다. 안 맞추면 오류 없이 서로를 못 본다.

### 작업 A — 1층(Docker) 확인 → 터미널 1

```bash
cd /home/syw/Trihouse
export ROS_DOMAIN_ID=0

docker ps --format '{{.Names}}\t{{.Status}}'
docker inspect trihouse_p0-rmf_api-1 \
  --format '{{range .Config.Env}}{{println .}}{{end}}' | grep ROS_DOMAIN_ID
curl -s -o /dev/null -w 'control_ui     %{http_code}\n' http://127.0.0.1:3100/
curl -s -o /dev/null -w 'rmf_dashboard  %{http_code}\n' http://127.0.0.1:3000/
curl -s http://127.0.0.1:8080/ready; echo
```

기대: 컨테이너 **6개** Up (8개가 아니다 — `profiles` 로 막힌 미구현 둘을 센 것이
문서의 오류다), `ROS_DOMAIN_ID=0`, `200`, `200`,
`{"status":"ready","database":"ok"}`.

### 작업 B — Gateway 에 새 기능이 실제로 떴는지 → 터미널 1

파일에 문자열이 있는지가 아니라 **FastAPI 가 경로를 등록했는지**를 본다.

```bash
curl -s http://127.0.0.1:8080/openapi.json | python3 -c "
import json,sys
d=json.load(sys.stdin)
for p in sorted(d['paths']):
    if any(k in p for k in ('rmf','cancel','expire','worker-completion','incident')):
        print(' ', p, list(d['paths'][p].keys()))
"
```

기대 7개 — 특히 아래 셋이 축 1·4의 증거다.

```
  /internal/v1/jobs/{job_id}/cancel               ← 설계 8절 1
  /internal/v1/reservations/expire                ← 설계 8절 2
  /internal/v1/rmf/tasks/{rmf_task_id}/updates    ← D8 (assignment observer)
```

`incident` 가 **하나도 안 나오는 것**이 축 3의 공백을 확인하는 방법이다.

### 작업 C — 자원이 비어 있는지 → 터미널 1

```bash
source .env
docker exec trihouse-mysql mysql -u"$FMS_DB_USER" -p"$FMS_DB_PASSWORD" --table trihouse_fms -e "
SELECT job_id, state, IFNULL(assigned_mobile_id,'-') robot,
       JSON_UNQUOTE(JSON_EXTRACT(context,'\$.assignment.mobile_id')) ctx_robot
  FROM jobs WHERE state IN ('queued','assigned','running','held');
SELECT SUM(available_qty) avail, SUM(reserved_qty) reserved FROM inventory_lots;
SELECT COUNT(*) total_msgs FROM integration_messages;
SELECT COUNT(*) incidents FROM incidents;
"
```

기대: 첫 쿼리 **0행**, `reserved 0`, `total_msgs` 안정, `incidents 0`.

`ctx_robot` 이 채워진 행이 있으면 **예약이 없어도 러너에게는 그 로봇이 잡혀 있다** —
러너가 DB `active_resource_key` 가 아니라 `jobs.context` 를 보기 때문이다
(`job_runner.py:319`, 설계 8절 6번 미구현). 그때는 취소로 풀어야 한다.

### 작업 D — 출고 7단계가 실제로 만들어지는지 (주문 없이) → 터미널 1

지난 job 의 step 을 읽으면 재고를 쓰지 않고 확인할 수 있다.

```bash
docker exec trihouse-mysql mysql -u"$FMS_DB_USER" -p"$FMS_DB_PASSWORD" --table trihouse_fms -e "
SELECT step_no, executor_type exec, action_type, IFNULL(assigned_device_id,'-') dev,
       target_location_id loc, state
  FROM job_steps WHERE job_id=(SELECT MAX(job_id) FROM jobs) ORDER BY step_no;
"
```

기대: **7행**이 §1.1 표와 같은 순서. `executor_type` 이 `arm`/`mobile`/`fms` 로 갈린다.

### 작업 E — 좌표·지도 정합 → 터미널 1

```bash
# 승인된 좌표 정본 (사람이 실측한 것)
python3 -c "
import json
for line in open('control_ui/rmf_control_ui/data/import/trihouse_test_01_physical_features.jsonl'):
    if not line.strip(): continue
    r=json.loads(line)
    if r.get('record_type') in ('waypoint','bottleneck'):
        print(r.get('record_type'), '|', r.get('location_code') or r.get('feature_code'),
              '|', r.get('rmf_waypoint_name'), '|', r.get('map_pose'))
"

# 지도 크기 — 44x54 px @ 0.05 = 2.20 x 2.70 m
head -3 control_ui/rmf_control_ui/data/rmf_maps/trihouse_map_01.pgm | tail -1
cat control_ui/rmf_control_ui/data/rmf_maps/trihouse_map_01.yaml
```

nav graph 정점 범위는 x 0.065~1.260, y -1.249~0.743. 지도는 origin `[-0.277,-1.452]`
기준 x -0.277~1.923, y -1.452~1.248. **전부 지도 안, 가장자리에서 0.2 m 이상 여유.**

### 작업 F — 축 3·5의 공백을 직접 확인 → 터미널 1

**"코드가 있다"와 "돈다"의 차이를 눈으로 보는 명령이다.**

```bash
# 축 5 — dependencies 를 읽는 곳이 있는가
echo "쓰는 곳:"; grep -rn '"dependencies"' --include=*.py control_tower | grep -v test | wc -l
echo "읽는 곳:"; grep -rn 'dependencies' --include=*.py control_tower/task_manager/job_runner.py | wc -l

# 축 3 — EmergencyWorkflow 를 부르는 곳이 있는가
grep -rn "EmergencyWorkflow" --include=*.py control_tower fms_gateway | grep -v tests | wc -l

# 축 2 — 주문 API 가 입고를 받는가
grep -n 'operation_type' fms_gateway/app/models.py
```

기대: 쓰는 곳 **7**, 읽는 곳 **0** / `EmergencyWorkflow` 비테스트 **0** /
`Literal["outbound"]`.

### 작업 G — 2층(호스트 ROS) 기동과 판정 → 터미널 2·3

**터미널 2 — 이 창은 절대 닫지 마십시오.** Ctrl+C 가 스택 정리입니다.

```bash
cd /home/syw/Trihouse
scripts/sim_teardown.sh
# 고아 확인 — 한 줄도 안 나와야 한다. pkill -f 는 쓰지 않는다
ps -eo pid,etime,args | grep -E "two_pinky_order_demo|lifecycle_manager|gz sim" | grep -v grep
uptime      # load 5 아래로 내려온 뒤에 다음으로

TRIHOUSE_ROBOTS=PK_01 \
TRIHOUSE_MAP_REVISION="trihouse_test_01:730111d2e446f5141c5ef069e5f2c1c8c5383aea79bdeffd05d3d34f2094b7ff" \
ROS_DOMAIN_ID=0 \
control_tower/bringup/p0_simulation_bringup.sh 2>&1 | tee /tmp/sim.log
```

**터미널 3 — 기동 2분 뒤.** bringup 의 `"올라왔습니다"` 를 믿지 않는다(D1 — launch 가
죽어도 그 줄이 나온다).

```bash
cd /home/syw/Trihouse
set +u; source /opt/ros/jazzy/setup.bash; source install/setup.bash; source pinky_pro/install/setup.bash; set -u
export ROS_DOMAIN_ID=0

grep -c 'Managed nodes are active' /tmp/sim.log      # 2
grep -c 'waiting for its battery' /tmp/sim.log       # 0   ← D7
pgrep -af 'lib/trihouse_pinky_fleet/fleet_node' >/dev/null && echo fleet_node_OK   # D10
python3 scripts/verify_robot_status.py pinky_01 20   # frame_id=map, dispatchable=true, errors=[]
```

`errors=[]` 를 **`docker restart` 없이** 보는 것이 D5 수정의 증거다.
`ros2 topic list`/`node list`/`param get` 은 부하에서 40초 멈추므로 쓰지 않는다.
기동 직후 1~2분은 AMCL 수렴 전이라 `frame_id=pinky_01/odom` 이 정상이다.

### 작업 H — 테스트 → 터미널 3

**3단 source 가 없으면 34개가 수집 단계에서 실패한다** (`rclpy` 없음).

```bash
set +u; source /opt/ros/jazzy/setup.bash; source install/setup.bash; source pinky_pro/install/setup.bash; set -u
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH="/home/syw/Trihouse:$PYTHONPATH" \
  .venv/bin/pytest trihouse_pinky control_tower trihouse_rmf_bridge -q

# fms_gateway 는 반드시 단독으로 (형제 모듈 import 가 깨진다)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH="/home/syw/Trihouse:$PYTHONPATH" \
  .venv/bin/pytest fms_gateway/tests/unit -q
```

기대: **605 passed** (실패 1 + 오류 7은 D17 격리 문제. 단독으로 돌리면 통과) /
**210 passed**. `PYTHONPATH` 는 **덮어쓰지 말고 더한다.**

---

## 4. 해야 할 작업 — 무엇을, 왜, 어떤 순서로

### 단계 0 — 지금 막힌 것을 푼다 (반나절)

#### 0-1. `p0_world.sdf` 를 bringup 에 연결 (D15)

**왜:** 안 하면 다음 기동이 RTF 0.19다. Nav2 타임아웃은 실시간 기준이라 **정상
코드도 타임아웃한다.** 결함을 찾는 동안 부하가 변수로 남으면 판정이 불가능하다.

**어디:** `control_tower/bringup/p0_simulation_bringup.sh:187`. 다른 변수와 같은 형태로.

```bash
: "${TRIHOUSE_WORLD_SOURCE:=$ROOT/control_tower/bringup/p0_world.sdf}"
```

187·197 두 곳과 `test_two_pinky_order_demo_launch.py` 를 함께 보셔야 합니다.
**기존 값과 충돌하는 변경이므로 직접 고쳐 주십시오.**

#### 0-2. D16 배선 — `robot is not idle` 실제 수정

**왜:** 축 1 완주의 마지막 벽. 원인은 §2.1로 확정됐고 재현이 확률적이라 방치하면
"간헐 실패"로 계속 시간을 먹는다.

**준비된 것:** 이번 세션에 순수 함수와 테스트 4개를 TDD로 만들었다.

```
 M trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/arrival.py   (+17)
?? trihouse_pinky/test/test_arrival_stop_settlement_contract.py          (신규, 4 passed)

def may_report_arrival(*, stationary: bool, waited_s: float, timeout_s: float) -> bool:
    return bool(stationary) or waited_s >= timeout_s
```

**남은 것:** `fleet_node._execute` 배선.
[fleet_node.py:174-195](../../trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py#L174-L195)
의 `get_result_async()` 와 `nav_result()` **사이**에 정차 대기를 넣는다.

```python
started = self.get_clock().now()
while not may_report_arrival(
    stationary=self.stationary,
    waited_s=(self.get_clock().now() - started).nanoseconds / 1e9,
    timeout_s=self.stop_settle_timeout_s,   # ← 파라미터로 뺄 것
):
    await <폴링 간격만큼 양보>
```

그리고 **timeout 으로 빠져나온 경우 `self.workflow.cancel_navigation()` 을 불러야
한다.** 안 그러면 지금과 똑같이 굳고 확률만 낮아진다.

**제가 값을 넣지 않은 이유:** `stop_settle_timeout_s` 와 폴링 간격은 `velocity_smoother`
감쇠 시간의 실측이 필요하다. 추측해 넣으면 또 하나의 `physical_validation_required`
주석이 된다. `fleet_node.py:84` 의 정차 기준(`|v.x| <= 0.01`)도 실측된 값인지
확인하지 못했다. 실측 방법:

```bash
export ROS_DOMAIN_ID=0
ros2 topic echo /pinky_01/odom --field twist.twist.linear.x
# topic list 는 멈추지만 이름과 타입을 준 echo 는 동작한다
```

#### 0-3. 완주 3회 연속 확인

**왜:** 1회 성공은 우연과 구분되지 않는다. D16이 확률적 결함이므로 특히 그렇다.

재고는 SKU당 1 lot이고 취소해도 D2 때문에 돌아오지 않는다. **매번 다른 SKU를 쓴다** —
`SKU-DUMPLING` → `SKU-ICEBAR` → `SKU-ICECONE`.

step 60 `wait` 는 **사람의 완료 보고를 기다린다.** 이게 없으면 로봇이 포장대에 서
있고 step 70 `return_home` 이 시작되지 않는다. 충전소 복귀를 보려면 필수다.

```bash
curl -s -X POST http://127.0.0.1:8080/api/v1/jobs/<JOB_ID>/worker-completion \
  -H 'Content-Type: application/json' -d '{}' | python3 -m json.tool
```

기대: `state_reason_code=RETURNING_TO_FIXED_CHARGER` + `charging_station_01` 로 가는
`rmf` outbox 1건.

---

### 단계 1 — 팔 ∥ 주행 병렬 (축 5). **설계 문서 먼저**

**왜 설계가 먼저인가:** 이건 버그 수정이 아니라 **스케줄러 실행 모델의 변경**이다.
지금은 "job 하나당 한 주기에 한 스텝"이고, 바꾸면 "선행조건이 충족된 스텝 전부"가
된다. 그러면 아래가 전부 따라 움직인다.

| 따라 움직이는 것 | 왜 |
|---|---|
| `current_step()` → 복수 반환 | 단일 반환을 전제한 호출자 전부 |
| `_advance()` 의 dispatch 루프 | 지금 1건. `awaiting`/`blocked` 판정 기준이 바뀐다 |
| **실패 처리** | 병렬 두 갈래 중 **한쪽만 실패**하면? 지금은 그런 상태가 없다 |
| **보상(compensation)** | ← **가장 중요.** 아래 |

**보상 단계가 없는 것이 병렬화의 진짜 전제조건이다.**

job 7의 실측이 그것을 보여 준다.

```
step 10  arm pick  OMX_01  loc 27(냉동)  succeeded   ← 팔이 냉동품을 집었다
step 20~70                               cancelled
```

**팔이 냉동품을 집은 채 나머지가 전부 취소됐다.** 제자리에 돌려놓는 단계가 없다.
냉동품이 상온에 방치된다.

- UR_13: "로봇팔은 ... 실패하면 **안전하게 대응**한다"
- UR_12: "하던 일은 **안전하게 마무리**되거나 다른 로봇이 이어받는다"

**직렬 실행에서는 이 창이 좁다**(팔이 끝난 직후 실패해야 걸린다). **병렬로 만들면
그 창이 주행 시간 전체로 넓어진다.** 즉 병렬화는 이 결함을 **더 자주 터지게 만든다.**

> **그래서 순서는: 보상 단계 설계 → 병렬 실행 → 그다음.**
> 병렬을 먼저 하면 냉동품을 상온에 두는 빈도가 올라간다.

설계 문서에 담아야 할 것:

1. `dependencies`/`gate` 의 **평가 규칙** — 누가, 언제, 무엇을 보고 판정하나
2. **부분 실패 정책** — 두 갈래 중 하나가 실패하면 나머지를 취소하나, 기다리나
3. **보상 스텝** — `arm place_back` 을 언제 만들고 누가 실행하나
4. 게이트 타임아웃 — 팔이 끝났는데 로봇이 안 오면 얼마나 기다리나 (냉동품 노출 시간)
5. **온도 구역별 허용 노출 시간** — 냉동/냉장/상온이 다르다. 이 값의 정본이 어디인가

5번은 **아직 어느 문서에도 없다.** 3온도 물류센터인데 "냉동품을 몇 초까지 상온에
둘 수 있는가"의 정본이 없다. 병렬화의 게이트 타임아웃이 그 값에서 나와야 한다.

---

### 단계 2 — 2대 스케줄링 (축 4). 설계 8절 5~10

**왜 지금이 아닌가:** 단일 로봇에서 first-fit과 ETA 최소화는 **결과가 같다.**
2대가 되기 전에 만들면 차이를 관측할 수 없다.

**2대 전에 풀어야 하는 것 둘:**

#### 2-1. 부하

12코어, GPU 없음(실측), 2대면 load 60~130. RTF 0.71을 얻은 뒤에도 2대는 미지수다.
**측정 없이 2대로 가면 실패가 코드 결함인지 부하인지 구분되지 않는다.**

먼저 잴 것: RTF 0.71 상태에서 2대를 띄우고 `Managed nodes are active` 가 **4**가
되는지, `uptime` 이 얼마인지.

#### 2-2. 병목 교착 (D14)

```
로봇 A: bottleneck_01 을 쥐고 02 를 기다린다
로봇 B: bottleneck_02 를 쥐고 01 을 기다린다     →  둘 다 못 나간다
```

창고→포장이 두 mutex 를 **연속** 요구한다. 좌표 정본의 실측 노트가 확인해 준다 —
bottleneck_2 는 "middle_goal_1/2 사이", 반지름 10 cm. **직렬로 붙은 통로다.**

**이건 "새 스케줄러를 만드는 일"이 아니다.** 이미 있는 세 모듈을 연결하는 일이다.

| 모듈 | 상태 |
|---|---|
| `control_tower/rmf_adapter/path_schedule.py` | 구현·테스트 있음. **import 하는 곳이 테스트뿐** |
| `control_tower/rmf_adapter/traffic_reservation.py` | 〃 |
| `control_tower/rmf_adapter/bottleneck.py` | 〃 |

거기에 **연속 mutex 획득 순서 규칙**을 더한다 — 두 병목을 한 번에 잡거나(2-phase),
항상 같은 순서로만 잡거나(ordered locking). 어느 쪽이든 설계 판단이다.

**통로 자체의 정본은 지도가 아니라 파이썬 상수다.** 발행된 nav graph 는 정점만 있고
`lanes: []` 다. lane 은 `p0_runtime_assets.py:44-54` 의 `LANE_TOPOLOGY` 가 정한다.
우회로를 만들려면 거기를 고친다. (`nav_graph.yaml` 이 저장소에 없어 보이는 이유도
이것이다 — `.trihouse/p0/nav_graph.yaml` 은 bringup 이 매번 생성하는 런타임 산출물이다.)

#### 2-3. 그다음 설계 8절 5~10

5(ETA 추정기) → 6(`available_at`) → 7(ETA 최소화 할당) → 8(전방 예약+대기열) →
9(`in_use` 전이) → 10(실제 경로 ETA). **7번이 "시간 효율"의 본체다.**

설계 9절의 열린 질문 둘이 여기서 답이 필요해진다.

- **공칭 속도의 정본** — 파생 Nav2 params 의 `desired_linear_vel` 을 읽을지, 별도
  설정을 둘지. 설계는 전자를 권한다(값이 두 곳이면 갈라진다)
- **ETA 출발점** — 로봇 현재 위치. `status.pose` 는 `frame_id == map` 일 때만 유효.
  위치추정 전이면 충전기 waypoint 를 기본값으로

---

### 단계 3 — 비상: 작업자 쓰러짐 (축 3). **가장 많이 남았다**

UR_10은 안전 요구사항이고 **범위가 가장 크다.** 네 층이 다 끊겨 있다.

| # | 무엇 | 왜 필요한가 |
|---|---|---|
| 3-1 | 감지 모델을 `vision_perception/test/worker-fall-detection/` 에서 **운영 코드로** | 지금은 실험 폴더다. 학습 스크립트와 추론 서비스는 다른 것이다 |
| 3-2 | 감지 → Gateway **incident 생성 API** | `main.py` 에 incident 엔드포인트가 **하나도 없다** (설계 10절이 확인) |
| 3-3 | `EmergencyWorkflow` 를 **런타임에 연결** | 236줄이 테스트에서만 import 된다. `blocks_assignment`(위험구역 배정 차단), `affect_robot`(적재 중 로봇 처리)이 아무 경로에도 없다 |
| 3-4 | 관제 UI **승인 경로** | 지금 읽기 전용. 승인 없이 incident 만 열면 **아무도 닫지 못해 job 이 영구히 멈춘다** |

**3-4를 빠뜨리면 새 교착을 만든다.** 설계 10절과 handoff 5절이 이미 경고했다 —
job 12가 자원을 붙잡았던 것과 **같은 종류의 교착**이다. 그래서 3-2와 3-4는
**같은 단계에서** 해야 한다.

로봇 쪽 안전은 별개로 이미 있다. `safety_supervisor` 가 20 Hz로 `indicator/state` 를
덮어쓰고, 로컬 Safety가 네트워크보다 우선한다(`control_tower_boundary.md` 계약).
**즉 "로봇이 사람을 안 치는 것"(UR_09)과 "쓰러진 사람에 대응하는 것"(UR_10)은 다른
층이고, 후자가 비어 있다.**

---

### 단계 4 — 입고 (축 2)

| # | 무엇 |
|---|---|
| 4-1 | `POST /api/v1/orders` 가 `inbound` 를 받게 — `models.py:160` 의 `Literal["outbound"]` |
| 4-2 | `planned_inbound_steps()` — 출고의 거울상. 도착 → 검수(QR/ArUco) → 온도 구역 slot 배정 → 적재 → 복귀 |
| 4-3 | 구역 배정 정책을 실행 경로에 — `inventory_workflow.reserve_inbound_slot` 이 구현돼 있으나 부르는 곳이 없다 |
| 4-4 | `pending_inbound` → `stored` 전이 — `finalize_inbound` 도 부르는 곳이 없다 |

**왜 마지막인가:** 출고가 완주하면 입고는 **같은 부품의 재조립**이다. 자원 예약,
step dispatch, RMF 연동, 팔 연동이 전부 공유된다. 출고 전에 입고를 만들면 같은
결함을 두 번 만난다.

UR_03(유통기한 임박 우선)도 여기 딸려 온다 — `inventory_lots` 에 `expiry` 가 있고
FEFO 정렬이 출고 선택 정책에 필요하다. 지금 확인하지 못했다.

---

### 부수 정리 (언제든, 독립)

| # | 무엇 | 근거 |
|---|---|---|
| A | **도메인 정본 통일** — 코드 기본값 두 줄을 0으로, 테스트에 "0인가" 한 줄 추가 | 문서 0 / 코드 52 / 컨테이너 0. `test_ros_dds_agreement.py` 는 "두 파일이 같은가"만 봐서 52=52로 통과 |
| B | **`locations` 접두사 제거** — `TRIHOUSE-TEST-01-` 5곳 | **`CHG-01`/`CHG-02` 가 옛 gwanghee 행(3·4)에 이미 쓰여 충돌.** §부록 참조 |
| C | D2 — 취소가 `reserved_qty` 를 안 돌려줌 | 지금도 원장 직접 수정뿐 |
| D | D12 — `job_runner`·`executor_worker` 가 Gateway 재시작에 죽음 | `run_poll_loop` 에 예외 처리. 운영 중 재배포는 언제든 일어난다 |
| E | D17 — 테스트 격리 2곳 | §2.3 |
| F | `DISPATCH_ATTEMPTS_EXHAUSTED` 가 거절 사유를 덮어씀 | `repositories.py:5342`. 진단성 |
| G | 출고 정의 두 벌 | `outbound_segment_template()`(구, 6단계) vs `planned_outbound_steps()`(현, 7단계) |
| H | `derive_nav2_params` 의 `root_key` 가 `main()` 에 미연결 | 실기 분기 A에서 필요 |
| I | OMX 어댑터가 `TRIHOUSE_ROBOTS` 와 무관하게 항상 2개 | bringup 3)절. 단일 로봇 부하 저감 취지와 어긋남 |
| J | `pinky_fleet.yaml` 주석의 실측 기한(2026-08-12) 경과 | 값은 그대로. 주석이 거짓말 중 |

---

## 5. 순서를 이렇게 두는 이유

```
0. 완주        ──▶  1. 병렬(보상 먼저)  ──▶  2. 2대 스케줄링
   (지금)             (축 5)                  (축 4)
                                                │
                          3. 비상 ◀─────────────┘   4. 입고
                          (축 3)                     (축 2)
```

- **0이 먼저인 이유:** 층이 도는 것을 확인하지 않은 채 구현을 얹으면 새 결함과
  기존 결함을 가를 수 없다. 직전 세션의 실측이 이걸 증명했다 — **벽 넷이 순차적으로만
  관측됐다.** 예약을 고치자 costmap 이 보이고, 그것을 고치자 RMF worker 의 죽음이
  보이고, 그것을 고치자 fleet 등록 실패가 보였다.
- **1에서 보상이 병렬보다 먼저인 이유:** 병렬화는 냉동품이 팔에 매달려 있는 창을
  주행 시간 전체로 넓힌다. 보상 없이 병렬화하면 UR_12·13 위반 빈도가 올라간다.
- **2가 1 뒤인 이유:** 단일 로봇에서 first-fit과 ETA 최소화는 결과가 같다. 차이를
  관측할 수 없는 것은 검증할 수 없다.
- **3이 큰 이유:** 네 층이 다 끊겨 있고, 3-4(승인 경로)를 빠뜨리면 새 교착을 만든다.
- **4가 마지막인 이유:** 출고가 완주하면 입고는 같은 부품의 재조립이다.

**축 4·5(사용자가 요청한 것)를 먼저 하고 싶어지겠지만, 완주가 한 번도 안 된 상태에서
스케줄러 실행 모델을 바꾸면 무엇이 고쳐졌는지 말할 수 없습니다.** 완주까지는
벽 하나(D16, 원인 확정됨)와 한 줄(D15) 남았습니다.

---

## 부록 — `locations` 접두사 제거의 이름 충돌

JSONL 이 두 규칙으로 섞여 있다. 상위 설비가 있는 지점은 그 코드를 물려받고
(`WH-FRZ-01-DOCK-01`), 상위가 `null` 인 충전기·안전구역·병목만 프로젝트 이름으로
빈자리를 메웠다. **규칙이 아니라 빈자리를 메운 결과**이므로 없애는 판단이 맞다.

그런데 `location_code` 에 `uq_locations_code` (UNIQUE) 가 걸려 있고:

```
location_id  3   CHG-01                    charger   rmf_waypoint_name=충전1     ← 옛 gwanghee
location_id  4   CHG-02                    charger   rmf_waypoint_name=충전2     ← 옛 gwanghee
location_id 31   TRIHOUSE-TEST-01-CHG-01             charging_station_01         ← 지금 쓰는 것
location_id 32   TRIHOUSE-TEST-01-CHG-02             charging_station_02         ← 지금 쓰는 것
```

`SAFETY-01` 은 비어 있어 충돌 없음. 병목은 `map_features` 에 있어 충돌 없음.

| | 무엇 | 장단 |
|---|---|---|
| **A (권장)** | 옛 행 3·4 를 지우고 `CHG-01`/`CHG-02` 회수 | 이름이 가장 깔끔. 3·4 는 실물 대응이 없다. **단 운영 DB 삭제** |
| B | `CHG-A01` 등 다른 이름 | 삭제 없음. `CHG-01` 이 영원히 죽은 이름으로 남음 |

1·2·5·6·7·8 도 같은 성격의 잔여물이다(`A-SLOT-01`·`OUT-DOCK-01`·`IN-WAIT-01`·
`NARROW-WAIT-01`·`OMX-WS-01`·`OMX-WS-02`, waypoint 이름이 `픽업1`·`드랍오프1`·
`대기1`·`대기3`·`설비1`·`설비2`). **"운영 DB와 동일하게" 라는 취지에는 A + 8행 정리가
맞습니다.**

고칠 자리 — **정본 데이터가 코드보다 먼저다.**

| 순서 | 파일 | 무엇 |
|---|---|---|
| 1 | `control_ui/.../trihouse_test_01_physical_features.jsonl` | `location_code` 3곳 + `feature_code` 2곳. **좌표 정본이 출발점** |
| 2 | 운영 DB `locations` 30·31·32, `map_features` 1·2 | 지도 재발행(저장→검증→배포)으로 반영되는지 확인 필요 |
| 3 | `control_tower/bringup/p0_runtime_assets.py` | `LANE_TOPOLOGY`(병목 9곳) + `CHARGER_BY_ROBOT`(2곳) |
| 4 | `control_tower/task_manager/assignment.py:12-15` | `CHARGER_BY_MOBILE` 2곳 |
| 5 | 테스트 6개 | `test_job_runner.py`(9곳), `test_assignment.py`, `test_p0_runtime_assets.py`, `test_two_pinky_order_demo_launch.py`, `worker_completion_test.dart`, `map_project_page_test.dart` |

1·3·4 는 **같은 커밋에서 함께** 바뀌어야 한다 — 불일치 시 `p0_runtime_assets.py` 가
`SystemExit` 로 즉시 죽는다(조용히 실패하지 않는 점은 다행이다).

**`map_revision` 도 바뀐다** (JSONL 내용이 sha256 에 들어간다). 지금 값
`trihouse_test_01:730111d2…` 는 재발행 후 새 값으로 교체해야 하고, 그 전에는 bringup
이 revision 불일치로 거절한다. **그래서 이 작업은 완주 확인 뒤가 안전하다.**
