# 세 질문에 대한 답 + 완주 진행 상황

작성: 2026-08-19 · 브랜치 `feat/pinky-edge-agent`
테스트: `trihouse_pinky`+`control_tower`+`trihouse_rmf_bridge` **617 passed** / colcon exit=0

---

## Q1. 로봇팔 랑데부 — "도착 신호 + 준비 신호 → 바구니에 넣기" 코드가 없는가

**절반은 있고, 실행 경로가 없다.** 정확히 나누면 이렇다.

| 조각 | 상태 | 근거 |
|---|---|---|
| 랑데부 **지점**이 설계에 있다 | ✅ | step 30 `fms load` 의 `gate: "PINKY_READY+OMX_READY"` (`outbound_sequence.py:143`) |
| 로봇이 "도착했다" 를 낸다 | ✅ | `fleet_node.py:201` — 도착 시 `HandoverState.STATE_READY` publish |
| 로봇이 "바구니 열렸다" 를 받는다 | ✅ | `fleet_node.py:66` — `CargoState.STATE_UNLOCKED` + `phase is WAITING_HANDOVER` → `cargo_confirmed` |
| 그 신호가 다음 명령을 **막는다** | ✅ | `workflow.accept(..., cargo_confirmed=...)` → 없으면 `"cargo handover is not confirmed"` |
| 관제가 두 신호를 **합치는 게이트** | ⚠️ **있으나 안 돈다** | `handover_gate.py` 128줄. `task_orchestrator.py:13,69,73` 이 import 하지만 **`task_orchestrator` 자체가 런타임에 없다** (비테스트 import 0곳) |
| **`OMX_READY` 를 내는 쪽** | ❌ | 팔이 "집었고 놓을 준비됨" 을 내는 경로를 찾지 못했다 |
| **두 신호가 다 오면 팔에 "넣어라"** | ❌ | 그 판정을 하는 실행 경로가 없다 |

즉 **로봇 쪽 절반은 다 있고, 관제 쪽 게이트가 안 돌고, 팔 쪽 신호가 없다.**
`HandoverGate` 는 레퍼런스 D8이 지적한 "모듈은 있으나 런타임에 없는 것" 목록의
**다섯 번째**다(`bottleneck.py`, `traffic_reservation.py`, `RosTaskSummaryObserver`,
`EmergencyWorkflow` 에 이어).

**그리고 지금은 랑데부가 발생할 일 자체가 없다.** `job_runner` 가 step 을 직렬로만
돌리므로(§Q1 부록) 팔이 **완전히 끝난 뒤에** 로봇이 출발한다. 로봇이 도착할 때
팔은 이미 대기 상태다. 게이트가 있어도 항상 즉시 통과한다.

### 주행만 주력으로 — 옳은 선택입니다

step 10 `arm pick` 은 OMX **시뮬레이터**가 처리하고 즉시 끝난다. job 8 실측:

```
23:23:31.745  navigation.segment.dispatched   (omx)
23:23:32.567  execution.step.succeeded        (omx)   ← 0.8초
```

**팔이 주행 검증을 막지 않는다.** 실기 팔은 다른 팀원 담당이고 `trihouse_omx_adapter/**`
는 손대지 않는 규칙이 이미 있다. 주행 완주에 집중하는 것이 맞다.

### 부록 — 직렬인 이유 (한 줄로)

```python
# job_runner.py:113   step_no 최솟값 하나만 고른다
# job_runner.py:238   그게 running 이면 아무것도 안 한다
```

`dependencies` 를 쓰는 곳 7군데, **읽는 곳 0군데.** 병렬은 설계에만 있다.

---

## Q2. ETA 를 구간으로 쪼개면 되는가 — **됩니다. 재료가 이미 다 있습니다**

### 결론부터

말씀하신 분할이 그대로 맞고, **설계 문서의 접근보다 낫습니다.** 이유는 §Q2-3.

### Q2-1. 다섯 구간이 실제로 nav graph 에 다 있는지 확인했다

```
OK  charging_station_01 -> ambient    2 lane : charging_station_01 -> BN-01 -> ambient
OK  ambient -> chilled                2 lane : ambient -> BN-01 -> chilled
OK  chilled -> frozen                 2 lane : chilled -> BN-01 -> frozen
OK  frozen  -> packing_station        3 lane : frozen  -> BN-01 -> BN-02 -> packing
OK  packing -> charging_station_01     3 lane : packing -> BN-02 -> BN-01 -> charging_station_01
```

창고끼리 직접 연결된 lane 은 없다 — **모든 창고 간 이동은 BOTTLENECK-01 을 지난다.**
경로는 다 있으니 ETA 는 계산되지만, 2대 운용에서 그 병목이 D14 교착의 원인이다.

### Q2-2. 계산 재료가 이미 구현돼 있다

**`trihouse_interfaces/srv/EstimateTaskEnergy.srv` — 이게 정확히 요청하신 것입니다.**

```
string[] waypoint_ids              # 순서대로 방문할 RMF waypoint
float64 expected_loading_duration_s
float64 expected_handover_duration_s
float64 task_time_buffer_s
---
bool    success
float64 travel_duration_s          # ← RMF 가 계산한 이동 시간
float64 total_duration_s           # ← 고정 단계까지 포함한 전체
float64 change_in_charge
float64 finish_state_of_charge
```

| 조각 | 상태 | 어디 |
|---|---|---|
| 서비스 계약 | ✅ | `trihouse_interfaces/srv/EstimateTaskEnergy.srv` |
| **서버 (C++)** | ✅ | `trihouse_rmf_bridge/src/energy_estimator_node.cpp`. `rmf_battery`+`rmf_traffic` 링크, `nav_graph_file` 파라미터 → **RMF 실제 플래너로 계산한다** |
| Python 클라이언트 | ✅ | `ros_energy_client.py` (`RosEstimateService`) |
| 포트 + fallback | ✅ | `energy_estimator.py` (`RmfEnergyEstimator`). RMF 가 없으면 시간 기반 fallback |
| **수동 검증 CLI** | ✅ | `estimate_energy_cli.py --waypoint A --waypoint B ...` |
| launch 에 서버가 있는가 | ❌ | `office_energy_bridge.launch.py` 에만. **그것도 office nav graph** |
| 배정이 이것을 부르는가 | ❌ | `assignment.py`/`job_runner` 에서 비테스트 import 0곳 |

**즉 만드는 일이 아니라 붙이는 일입니다.** 설계 8절 5번(ETA 추정기)과 10번(실제 경로
기반 ETA)이 사실상 이미 구현돼 있고, 연결이 없습니다.

### Q2-3. 구간 분할이 설계보다 나은 이유

**구간 경계가 이미 step 경계와 같습니다.** 각 `mobile navigate` step 이 정확히 한 구간입니다.

| 구간 | 대응하는 step |
|---|---|
| 충전소 → 창고 dock | step 20 `mobile navigate` |
| 창고 dock → 창고 dock | (다중 bundle 이면 다음 bundle 의 navigate) |
| 창고 dock → 포장대 | step 40 `mobile navigate` |
| 포장대 → 충전소 | step 70 `mobile return_home` |

그래서 새 분해가 필요 없고, 아래가 거의 공짜로 나옵니다.

```
구간 ETA        = 그 step 의 ETA
job ETA         = 남은 navigate step 들의 ETA 합
로봇 available_at = now + 남은 구간 합        ← 설계 8절 6번
```

설계 8절은 5(추정기) → 6(`available_at`) → 7(ETA 최소화 할당) → 10(실제 경로 ETA) 을
따로 뒀는데, **구간 = step 으로 보면 5·6·10 이 한 덩어리가 됩니다.** 남는 것은 7(할당
정책)뿐이고 그건 순수 함수로 쓸 수 있습니다.

### Q2-4. 구현 가능한 수준으로 쪼갠 순서

**1단계 — 코드 0줄. 구간별 ETA 가 실제로 나오는지 먼저 본다** *(권장 시작점)*

`office_energy_bridge.launch.py:21` 을 참고해 노드를 우리 nav graph 로 띄운다.
`nav_graph_file` 을 `.trihouse/p0/nav_graph.yaml` 로 준다.

```bash
export ROS_DOMAIN_ID=0
ros2 run trihouse_rmf_bridge trihouse_rmf_bridge_node --ros-args \
  -p nav_graph_file:=/home/syw/Trihouse/.trihouse/p0/nav_graph.yaml

# 다른 창에서 구간 하나씩
python3 -m control_tower.rmf_adapter.estimate_energy_cli \
  --robot-id PK_01 --map-revision trihouse_test_01 \
  --waypoint charging_station_01 --waypoint ambient_storage_loading_dock_01
```

다섯 구간을 각각 재서 표로 남긴다. **여기서 값이 안 나오면 그 다음은 의미가 없다.**
`fleet_config` 의 `linear: [0.250, 0.500]` 로 손계산한 값과 대조하면 타당성을 볼 수 있다
(예: 충전소→상온은 약 1.3 m → 0.25 m/s 면 5초 남짓 + 가감속).

**2단계 — launch 에 붙인다.** `two_pinky_order_demo.launch.py` 에 노드를 추가한다.
`nav_graph` launch 인자가 이미 있으므로 그대로 넘긴다.

**3단계 — `available_at` 을 구간 합으로.** Gateway 에 조회를 만든다(설계 4.2).
로봇의 남은 step 들의 ETA 합. 순수 계산이라 단위 테스트로 끝난다.

**4단계 — 할당을 ETA 최소화로.** `assignment.py` 의 first-fit 을 바꾼다.
동점 처리를 결정적으로 둔다(설계 4.3).

**단계마다 그 자체로 검증됩니다.** 1단계는 코드 없이 실측만, 2단계는 launch 테스트,
3·4단계는 순수 단위 테스트.

### Q2-5. 안 되는 것 하나 — 미리 알아 두실 것

설계 9절의 열린 질문이 3단계에서 실제로 막습니다.

**ETA 의 출발점이 필요합니다.** "로봇이 지금 어디 있는가". `status` 의 `pose` 는
`frame_id == map` 일 때만 유효하고, AMCL 수렴 전에는 못 씁니다. 그때는
**충전기 waypoint 를 출발점으로 두는 것이 안전한 기본값**입니다(설계도 그렇게 권고).

**공칭 속도의 정본도 정해야 합니다.** 파생 Nav2 params 의 `desired_linear_vel` 을
읽을지, `pinky_fleet.yaml` 의 `limits.linear` 를 쓸지. 설계는 전자를 권합니다 —
값이 두 곳이면 갈라지기 때문입니다. **다만 `EstimateTaskEnergy` 서버가 RMF 모델을
쓰므로, 그 서버를 쓰는 한 이 질문은 RMF fleet config 하나로 답이 됩니다.**

---

## Q3. 비상(작업자 쓰러짐) 현재 구현 수준

**네 층이 전부 끊겨 있습니다.** 오후에 vision 붙이실 때 볼 표입니다.

| 층 | 있는 것 | 없는 것 |
|---|---|---|
| **감지** | `vision_perception/test/worker-fall-detection/` — 학습·시각화·데이터로더·`realtime.py` | **`test/` 아래 실험 폴더다.** 운영 추론 서비스가 아니다 |
| **전달** | — | 감지 결과 → Gateway 경로를 찾지 못했다 |
| **원장** | `incidents` 테이블 (state, `acknowledged_by_worker_id`, geometry) | **행 0개** (실측). **Gateway 에 incident 엔드포인트 0개** — `openapi.json` 으로 확인 |
| **판정** | `emergency_workflow.py` 236줄 — `open`/`blocks_assignment`/`affect_robot`/`release`/`decide`/`dismiss` + 테스트 2개 | **비테스트 import 0곳.** 런타임에 안 돈다 |
| **화면** | 관제 UI 가 `incidents` 를 표시 | **읽기 전용.** 승인 버튼 없음 |

### 로봇 쪽 안전은 별개로 이미 있습니다

혼동하기 쉬운 지점이라 적어 둡니다.

| | 무엇 | 상태 |
|---|---|---|
| UR_09 | 로봇이 **사람을 안 치는 것** | ✅ `safety_supervisor` 가 20 Hz 로 `indicator/state` 를 덮어쓰고, 로컬 Safety 가 네트워크보다 우선 (`control_tower_boundary.md` 계약). `workflow.enter_emergency`/`clear_emergency` 도 있다 |
| UR_10 | **쓰러진 사람에 대응하는 것** | ❌ 위 표 |

즉 "로봇이 멈추는" 기능은 있고, **"사람이 쓰러졌다는 사실이 관제에 도달해 로봇 배정을
막는" 경로가 없습니다.**

### 오후에 시작하실 때 순서 (이유 포함)

1. **`EmergencyWorkflow` 를 런타임에 붙인다** — 236줄이 이미 있고 테스트도 있다.
   새로 쓰는 것이 아니라 배선이다. `blocks_assignment` 가 위험구역 배정을 막고,
   `affect_robot` 이 적재 중 로봇을 처리한다
2. **Gateway incident API + 관제 승인 경로를 같은 단계에서** — 이게 중요합니다.
   설계 10절과 handoff 5절이 이미 경고했습니다: **승인 없이 incident 만 열면 아무도
   닫지 못해 job 이 영구히 멈춥니다.** job 12 가 자원을 붙잡았던 것과 같은 종류의
   교착을 새로 만드는 셈입니다
3. **감지를 운영 코드로** — 그다음. 1·2 가 없으면 감지 결과를 받을 그릇이 없다

**2번을 1·3번과 분리하지 마십시오.** 그것이 이 시스템에서 반복된 실패 패턴입니다.

---

## 완주 (1순위) — 이번 세션 진행

### 무엇을 했는가

**D16(`robot is not idle`)이 다른 창에서 이미 배선돼 있었습니다.** 제가 만든
`may_report_arrival` 을 `fleet_node._settle_before_arrival` 이 쓰고 있었습니다.
검토했더니 **결함 두 개**가 있어 고쳤습니다.

#### 결함 ① `asyncio.sleep` 이 rclpy executor 에서 죽는다 (치명)

```python
from asyncio import sleep      # ← 배선된 판본
...
await sleep(0.05)
```

rclpy 는 asyncio 이벤트 루프를 **돌리지 않습니다.**

```python
# rclpy/task.py  Task._execute_coroutine_step
result = coro.send(None)                # 직접 밀어 준다
...
elif isinstance(result, Future): ...    # Future 면 완료 시 재개
elif result is None: ...                # None 이면 다음 spin 에 재개
else: raise TypeError                   # 그 밖은 거부
```

`rclpy.task` 에 `asyncio` import 가 **하나도 없습니다.** 그리고
`asyncio.sleep(delay)` 는 `delay > 0` 이면 `get_running_loop()` 를 먼저 부릅니다.
직접 실행해 확인했습니다:

```
RuntimeError: no running event loop     (asyncio/tasks.py:659)
```

**하필 죽는 자리가 결함이 나는 자리와 같습니다.** 로봇이 이미 정차해 있으면
`may_report_arrival` 이 곧바로 True 를 돌려주고 `sleep` 에 닿지 않아 **정상으로
보입니다.** 감쇠 중일 때만 닿고 그때 죽습니다 — **고치려던 그 레이스에서만 터집니다.**
원래 버그와 같은 모양입니다.

**왜 테스트가 못 잡았는가:** `test_fleet_node_waits_for_stop.py` 는 전부
**소스 문자열 검사**입니다(`assert "may_report_arrival" in source`). 배선이 되었다는
것은 증명하지만 **그 배선이 실행되는지는 증명하지 않습니다.**

**고친 것:** rclpy 가 받는 `Future` 를 일회성 timer 로 완료시킵니다.
`None` yield 도 rclpy 는 받아 주지만 상한(2초)까지 executor 를 바쁘게 돌리므로,
GPU 없는 12코어 PC 에서는 timer 로 실제 간격을 뒀습니다.

**새 테스트** `test_settle_runs_under_rclpy_executor.py` — rclpy 의 `send(None)` +
yield 계약을 재현해 **코루틴을 실제로 실행합니다.** ROS 노드는 띄우지 않습니다.
그 테스트가 제 첫 구현의 버그도 잡았습니다 — 발화 콜백이 `create_timer` 가 돌아오기
전의 `timer` 를 참조해 `NameError` 가 났습니다. `add_done_callback` 으로 옮겼습니다.
timer 누수 검사도 넣었습니다(대기마다 만들므로 완주 한 번에 수십 개가 쌓일 수 있음).

#### 결함 ② 상한에 닿으면 여전히 갇힌다

배선된 판본에는 **`cancel_navigation()` 이 없었습니다.** 2초를 기다려도 안 멈추면
`nav_result` 가 여전히 `"waiting for stop"` 을 주고 phase 가 `NAVIGATING` 에 남습니다.
**2초 뒤에 똑같이 갇힙니다** — 대기가 확률만 낮춘 셈이 됩니다.

`ROBOT_NOT_STOPPED` 인 경우에만 `workflow.cancel_navigation()` 을 부르게 했습니다.
다른 두 사유는 `nav_result(succeeded=False)` 가 이미 phase 를 IDLE 로 내립니다.

**이 테스트도 한 번 잘못 썼습니다.** 처음 판본은 `ROBOT_NOT_STOPPED` 를 문자열로
찾아 **45줄의 주석**에 걸리고, 그 뒤 `_cancel` 콜백(244줄)의 무관한
`cancel_navigation` 을 찾아 **수정 없이 통과**했습니다. 코드에만 나타나는 표현식
(`else 'ROBOT_NOT_STOPPED'`)으로 시작해 `_execute` 안만 보도록 좁혔습니다.

### 바뀐 파일

```
 M trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/arrival.py   (+17, may_report_arrival)
 M trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py
?? trihouse_pinky/test/test_arrival_stop_settlement_contract.py          (6 테스트)
?? trihouse_pinky/test/test_settle_runs_under_rclpy_executor.py          (4 테스트)
```

검증: **617 passed** (직전 605 + 이번 12) / `colcon build --packages-select
trihouse_pinky_fleet --symlink-install` **exit=0**.

실패 1 + 오류 7은 D17 격리 문제이며 단독으로 돌리면 전부 통과합니다.

### 완주까지 남은 것 — 한 줄과 한 번의 실행

| | 무엇 | 누가 |
|---|---|---|
| 1 | **D15** — `p0_simulation_bringup.sh:187` 을 `p0_world.sdf` 로 | **직접 고쳐 주십시오** (기존 값과 충돌) |
| 2 | 재고 예약 해제 (`reserved_qty`) | **직접** — 자동 모드가 원장 UPDATE 를 차단합니다 |
| 3 | 시뮬 기동 → 주문 → 완주 | 1·2 뒤 |

#### 1. D15 — 고칠 자리

`control_tower/bringup/p0_simulation_bringup.sh:187`

```bash
# 지금 — 벤더 world 하드코딩, override 없음
PINKY_WORLD="$(ros2 pkg prefix pinky_gz_sim)/share/pinky_gz_sim/worlds/empty.world"
```

`p0_world.sdf` 를 기본값으로 두고 벤더로 돌아갈 길만 남기는 형태를 권합니다.
`PINKY_WORLD` 를 쓰는 자리가 **187·197 두 곳**이고,
`test_two_pinky_order_demo_launch.py` 가 world 인자를 검증하므로 함께 보셔야 합니다.

안 고치면 RTF 0.19 로 돌아가고, Nav2 타임아웃은 실시간 기준이라 **정상 코드도
타임아웃합니다.**

#### 2. 재고 — 직접 실행

```bash
PW=$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)
docker exec trihouse-mysql mysql -uroot -p"$PW" --table -e "
UPDATE trihouse_fms.inventory_lots SET reserved_qty = 0 WHERE reserved_qty > 0;
SELECT SUM(available_qty) avail, SUM(reserved_qty) reserved FROM trihouse_fms.inventory_lots;
" 2>&1 | grep -v 'password on the command line'
```

기대 `avail 17 / reserved 0`. lot 8(`SKU-PORKBELLY`)이 갇혀 있습니다(D2).

#### 3. 기동과 완주 → 터미널별

##### 시뮬 기동 → 터미널 1 (**이 창은 절대 닫지 마십시오**)

```bash
cd /home/syw/Trihouse
scripts/sim_teardown.sh
ps -eo pid,etime,args | grep -E "two_pinky_order_demo|lifecycle_manager|gz sim" | grep -v grep
uptime      # load 5 아래로 내려온 뒤에

TRIHOUSE_ROBOTS=PK_01 \
TRIHOUSE_MAP_REVISION="trihouse_test_01:730111d2e446f5141c5ef069e5f2c1c8c5383aea79bdeffd05d3d34f2094b7ff" \
ROS_DOMAIN_ID=0 \
control_tower/bringup/p0_simulation_bringup.sh 2>&1 | tee /tmp/sim.log
```

##### 판정 → 터미널 2 (기동 2분 뒤)

```bash
cd /home/syw/Trihouse
set +u; source /opt/ros/jazzy/setup.bash; source install/setup.bash; source pinky_pro/install/setup.bash; set -u
export ROS_DOMAIN_ID=0

grep -c 'Managed nodes are active' /tmp/sim.log      # 2
grep -c 'waiting for its battery' /tmp/sim.log       # 0   ← D7
pgrep -af 'lib/trihouse_pinky_fleet/fleet_node' >/dev/null && echo fleet_node_OK   # D10
python3 scripts/verify_robot_status.py pinky_01 20   # errors=[] , PASS
```

##### 주문 → 터미널 2

```bash
curl -s -X POST http://127.0.0.1:8080/api/v1/orders \
  -H 'Content-Type: application/json' -H "Idempotency-Key: run-$(date +%s)" \
  -d '{"requested_by":"W-OP-01","priority":"normal","items":[{"product_code":"SKU-PORKBELLY","quantity":1}]}' \
  | python3 -m json.tool
```

##### 포장대에서 멈추면 정상 — 작업자 완료를 넣어야 복귀합니다

step 60 `wait` 는 사람의 보고를 기다립니다. 이게 없으면 step 70 `return_home` 이
시작되지 않아 **충전소 복귀를 볼 수 없습니다.**

```bash
curl -s -X POST http://127.0.0.1:8080/api/v1/jobs/<JOB_ID>/worker-completion \
  -H 'Content-Type: application/json' -d '{}' | python3 -m json.tool
```

##### D16 이 실제로 고쳐졌는지 판정 → 터미널 2

**이번 수정의 실측 증거입니다.**

```bash
# ① 정차 대기가 돌았는가 — 있으면 대기가 작동한 것
grep -E "waiting for stop|ROBOT_NOT_STOPPED" /tmp/sim.log

# ② asyncio 오류가 없어야 한다 (수정 전이면 여기서 터졌다)
grep -E "no running event loop|RuntimeError" /tmp/sim.log      # 0줄

# ③ 갇히지 않았는가
grep -c "robot is not idle" /tmp/sim.log                       # 0

# ④ 로봇이 실제로 움직였는가 — mode 가 0이 아니면 주행 중
ros2 topic echo /fleet_states --once --field robots
```

| 결과 | 뜻 |
|---|---|
| ② 가 0줄이고 ③ 이 0 | **D16 수정 확인.** 완주 경로가 열렸다 |
| ① 에 `waiting for stop` 이 있고 ③ 이 0 | 레이스가 실제로 일어났고 대기가 막아 냈다 — **가장 강한 증거** |
| ① 에 `ROBOT_NOT_STOPPED` 가 있으면 | 상한(2초) 안에 안 멈췄다. `arrival_stop_timeout_s` 를 올려야 한다 |
| ③ 이 0이 아니면 | 다른 원인이다. §Q1 의 `cargo handover is not confirmed` 도 후보 |

##### `arrival_stop_timeout_s` 값은 실측으로 확정하십시오

기본 2.0초는 보수적으로 넉넉히 둔 값이고 **실측된 값이 아닙니다.**
`fleet_node.py:84` 의 정차 기준(`|v.x| <= 0.01`, `|ω| <= 0.02`)도 실측 근거를
확인하지 못했습니다.

```bash
# 도착 직후 cmd_vel 이 0 으로 떨어지는 데 걸리는 시간
ros2 topic echo /pinky_01/odom --field twist.twist.linear.x
# topic list 는 부하에서 멈추지만 이름과 타입을 준 echo 는 동작한다
```

측정값의 3~5배를 상한으로 두면 충분합니다. 결과는 `docs/validation/` 에 적으십시오.

---

## 순서 요약

```
[지금] D15 한 줄 + 재고 한 줄  ──▶  기동  ──▶  완주 3회
                                                 │
                    ┌────────────────────────────┘
                    ▼
        Q2-1 구간 ETA 실측 (코드 0줄)  ──▶  launch 배선  ──▶  available_at  ──▶  ETA 할당
                                                                                    │
                                          Q1 병렬(보상 먼저)  ◀────────────────────┘
                                                    │
                                          [오후] Q3 비상 (2번을 1·3과 함께)
```

**Q2-1(구간 ETA 실측)은 완주와 독립이고 코드를 안 바꿉니다.** 완주 대기 중에 돌려
볼 수 있는 유일한 작업이라 병렬로 진행하기 좋습니다.
