# 규칙 주행과 Open-RMF 를 함께 쓰는 방법

**질문:** 협로에 들어갈 때 ArUco 마커가 보이면 거기서부터 규칙 주행으로 넘겨 회전 후
후진 진입을 시키고 싶다. RMF 와 어떻게 공존시키는가.

**답 한 줄:** RMF 는 이런 경우를 위한 창구를 이미 셋 갖고 있다
(`override_schedule` · `dock_name` · 끊기지 않는 `update`). 지금 깨지는 이유는 그 셋을
안 쓰기 때문이 아니라, **규칙 주행이 안전 gate 를 때리고 그 여파로 adapter 가 RMF 에
말을 끊기 때문**이다. 그 연결만 고치면 규칙 주행과 RMF 는 원래 같이 돌 수 있다.

참조 구현: `~/vlm_rl_backup/Trihouse_segmentation/Trihouse/driving_fms/narrow3_rule_based_docking.py`
현재 구현: `trihouse_pinky_fleet/narrow_zone_pilot.py` + `fleet_node.py`

---

## 1. 지금 왜 깨지는가 — 4단 연쇄

2026-08-20 시뮬에서 2회 연속 재현. step 20 이 `RMF_TASK_CANCELLED` 로 죽는다.

```text
① 협로 진입 → 안전 gate 가 STOP
     safety_supervisor 기본값 stop_distance_m 0.30 · swept_clearance_m 0.191
     그런데 통로 폭은 0.20 m 고 도크는 0.30 m 안으로 기어들어가야 한다
     제자리 회전은 지름 0.40 m 를 쓸고 지나간다
         ↓
② dispatchable 이 false 가 된다
     status.py:80-91   safety_blocked → execution_ready=False → dispatchable=False
         ↓
③ adapter 가 RMF 에 말을 끊는다
     state.py:validate → PINKY_NOT_READY
     pinky_adapter_node.py:126-135
         update_handle.more().unstable_decommission()
         return                      ← ★ update() 를 아예 호출하지 않고 나간다
         ↓
④ RMF 가 로봇을 포기한다
     rmf_fleet_adapter/phases/MoveRobot.hpp:170
       "Requesting replan for [%s] because its command handle seems to be unresponsive"
     → replan → stop → Nav2 goal cancel → navigation canceled
     → step 20 cancelled → 러너가 회복 경로 없이 무한 반복
```

**결함은 규칙 주행 자체가 아니라 ③이다.** `dispatchable` 은 *"이 로봇에 **새 작업**을
줘도 되는가"* 인데, 그것을 *"지금 **수행 중인** 로봇을 fleet 에서 빼낼 근거"* 로 쓰고
있다. 순간 안전정지 한 번이 진행 중인 작업을 죽인다 — 결함 정본의 **D15** 이고,
협로 규칙 주행이 그것을 **매번** 확실히 밟는다.

---

## 2. RMF 가 이미 가진 창구 셋 — 실측 확인

```python
>>> import rmf_adapter.easy_full_control as efc
>>> [a for a in dir(efc.Destination) if not a.startswith('_')]
['dock', 'graph_index', 'inside_lift', 'map', 'name', 'position', 'speed_limit', 'xy', 'yaw']
>>> [a for a in dir(efc.CommandExecution) if not a.startswith('_')]
['finished', 'identifier', 'okay', 'override_schedule']
```

### ① `update_handle.update(state, activity)` — 끊지 않는 것

RMF 는 이 호출로 로봇이 살아 있고 **어떤 activity 를 수행 중인지**를 안다. 이것이
멎으면 ④가 발동한다. **규칙 주행 중에도 계속 불러야 한다.**

### ② `CommandExecution.override_schedule(map, path, hold)` — 계획 밖으로 간다고 말하기

```python
execution.override_schedule("L1", [[x, y, yaw], ...], hold_seconds)
```

**이것이 정확히 이 상황을 위한 API 다.** 규칙 주행은 RMF 가 세운 경로와 다른 궤적을
그린다. 이 호출로 실제 궤적을 교통 스케줄에 등록하면 RMF 는 *"내 계획과 다르네"* 로
replan 하지 않고, **다른 로봇도 그 구간을 피한다.** 로봇 2대 운용에서 필수다.

### ③ `Destination.dock` — 협로를 계획에 명시하기

nav graph 의 lane 에 `dock_name` 을 넣으면, RMF 는 그 구간에서 같은 `navigate`
콜백을 부르되 `destination.dock` 을 채워 준다. *"여기서부터는 로봇이 자기 방식대로
간다"* 가 **계획에 박힌다.**

우리 adapter 는 이미 그 값을 읽고 있다.

```python
# pinky_adapter_node.py:242
goal.requires_precise_stop = bool(getattr(destination, "dock", None))
```

RMF graph 파서가 읽는 정점/lane 속성 키에 `dock_name` 이 있는 것도 확인했다
(`is_charger` · `is_holding_point` · **`mutex`** · `merge_radius` · `door_name` ·
**`dock_name`** · `speed_limit`).

> **주의 — 같은 자리의 별개 결함.** 우리 nav_graph 생성기는 병목에 `mutex_group:` 을
> 쓰는데 RMF 가 읽는 키는 **`mutex:`** 다. 지금 상호배제가 통째로 꺼져 있다
> (`p0_runtime_assets.py:272`). 2대 운용 전에 같이 고친다.

---

## 3. 제안 구조

```text
RMF 계획
  └─ lane [bottleneck_01 → frozen_dock]  dock_name: narrow_frozen_01
        │
        ▼  navigate(destination.dock="narrow_frozen_01", execution)
   pinky_adapter_node
        │  ExecuteTransport goal (mode=DOCK, dock_name, marker_id)
        ▼
   fleet_node
        ├─ ① execution.override_schedule(...) 로 실제 궤적 등록
        ├─ ② status 갱신을 끊지 않게 유지 (§4)
        ├─ ③ ArUco 마커 pose 를 기다린다  ← 사용자가 원한 트리거
        ├─ ④ narrow_zone_pilot: 회전 → 후진   (cmd_vel_dock 로 발행)
        └─ ⑤ verify_pose → execution.finished()
                  ▲
            ArUco 검출 노드 (RTSP → detectMarkers → solvePnP → PoseStamped)
```

### ArUco 를 "트리거" 가 아니라 "기준 프레임" 으로 쓰기를 권한다

사용자 안은 *"마커가 보이면 그때부터 규칙 주행"* 이다. 트리거로만 쓰면 **시작 시점만**
정확해지고, 회전 각도와 후진 거리는 여전히 AMCL 절대 좌표에서 온다. 그 오차가
0.08~0.11 m 이고 편측 여유가 0.03 m 다 — **문제가 그대로 남는다.**

마커 **상대 좌표**로 회전량·후진량을 계산하면 셋이 한꺼번에 풀린다.

| | 트리거로만 | 기준 프레임으로 |
|---|---|---|
| AMCL 오차 | 그대로 들어온다 | **빠진다** |
| 바퀴 미끄러짐 | 못 고친다 (개루프) | 마커를 다시 보고 **고친다** |
| 지도 재작성 | 존 표를 다시 재야 한다 | **영향 없다** |

**지금 하려는 `new_map_2` 좌표 재측정에 직접 영향이 있다.** 마커 기반으로 가면
협로 진입점·회전·후진 값은 지도에 묶이지 않으므로 **협로 재측정을 안 해도 된다.**
waypoint 좌표(도크 앞 대기 지점까지)만 다시 재면 된다.

이건 새 판단이 아니다 — `docs/architecture/marker-docking-design.md` 가 이미
*"마커는 확인 신호가 아니라 제어 입력으로 쓴다"* 로 결론지어 두었고, 엔진은
`opennav_docking` + `SimpleNonChargingDock` 을 쓰라고 정해 두었다
(`use_external_detection_pose` 로 외부 검출 pose 를 받는다). 그쪽을 쓰면 대기 지점
이동·재시도·타임아웃·**충돌 감시**를 공짜로 얻는다.

---

## 4. 안전 gate — `cmd_vel_dock` 이 이미 있다

`safety_supervisor` 는 두 채널을 구독하고 **dock 이 우선**이다.

```python
# safety_supervisor_node.py:98-99, 181
self.create_subscription(Twist, 'cmd_vel_nav',  self._on_nav,  10)
self.create_subscription(Twist, 'cmd_vel_dock', self._on_dock, 10)
...
desired = self.dock if self.dock is not None else self.nav
```

후진 보호 필드도 이미 붙어 있다(커밋 `f174a49d`) — `path_clearance(reverse=True)` 가
뒤쪽 필드를 보고, 초음파는 정면만 보므로 후진 판정에서 제외한다.

**빠진 것 둘.**

| # | 무엇 | 지금 |
|---|---|---|
| 1 | `narrow_zone_pilot` 이 `cmd_vel_dock` 이 아니라 `cmd_vel_nav` 로 쏜다 | `fleet_node.py:122` |
| 2 | dock 채널에 **별도 임계 프로파일이 없다** | `apply_safety_gate(desired, inputs, self.config)` — 채널과 무관하게 같은 `config` |

②가 핵심이다. 도킹은 정의상 `stop_distance_m 0.30` 안으로 들어가는 동작이라, 같은
임계를 쓰는 한 gate 가 **정상 동작으로서** 막는다. 도킹 프로파일이 필요하다.

```text
주행 프로파일   stop 0.30  slow 0.60  swept 0.191
도킹 프로파일   stop 0.05  slow 0.10  swept 0.03   ← 실측으로 정해야 하는 값
```

**임계를 낮추는 것이 안전을 낮추는 것과 같지 않다** — 발행자는 여전히 safety 하나이고,
비상 래치·사람 감지·keep-out 은 프로파일과 무관하게 그대로 걸린다. 낮추는 것은
"벽까지의 거리" 판정뿐이고, 도킹은 벽에 다가가는 것이 목적이다.

---

## 5. 무엇을 어떤 순서로

| # | 무엇 | 크기 | 왜 이 순서 |
|---|---|---|---|
| **1** | **adapter 가 수행 중에는 `update()` 를 끊지 않게** — `telemetry_valid` 로 판정하고, decommission 은 telemetry 가 죽었을 때만 | 작다 | **이것만 고쳐도 지금의 취소가 멎는다.** 나머지는 그 위에 얹는 것 |
| 2 | `narrow_zone_pilot` → `cmd_vel_dock` + 도킹 안전 프로파일 | 작다 | gate 가 규칙 주행을 막는 것을 없앤다 |
| 3 | `execution.override_schedule(...)` 호출 | 중간 | RMF 가 replan 하지 않게. 2대 운용에 필수 |
| 4 | ArUco 검출 노드 + 마커 상대 제어 | 크다 | 정밀도의 본체. 협로 재측정을 없앤다 |
| 5 | nav_graph lane 에 `dock_name` | 중간 | 협로를 계획에 명시 |
| 6 | `mutex_group:` → `mutex:` | **한 단어** | 2대 운용의 통로 상호배제 |

**1 과 2 는 이번 실물 테스트 전에 해야 한다.** 3~5 는 그 뒤여도 된다.

그리고 **어느 쪽을 골라도 따로 고쳐야 하는 것 하나** — 러너가 취소된 step 에서
영구히 멈춘다(`job runner blocked: step N is cancelled` 무한 반복 + adapter 409 폭주).
실기에서는 취소가 더 자주 일어난다.

---

## 6. 결정이 필요한 것

| # | 질문 | 선택지 |
|---|---|---|
| A | 마커를 **트리거로만** 쓸 것인가, **기준 프레임**으로 쓸 것인가 | 기준 프레임을 권한다 (§3). 협로 재측정이 없어진다 |
| B | 도킹 엔진을 `opennav_docking` 으로 갈 것인가, `narrow_zone_pilot` 을 유지할 것인가 | `marker-docking-design.md` 는 전자를 정해 뒀다. 후자는 충돌 감시를 스스로 만들어야 한다 |
| C | 도킹 안전 프로파일 값 | **실측이 필요하다.** 로봇 정지거리를 재기 전에는 숫자를 넣지 않는다 |
| D | `dock_name` 을 lane 에 넣을 것인가 | 넣으면 협로가 RMF 계획에 명시된다. 안 넣으면 adapter 가 목적지 이름으로 추측해야 한다 |

---

관련 문서
- 마커 도킹: [marker-docking-design.md](marker-docking-design.md)
- 협로 규칙 주행: [narrow-zone-pilot-design.md](narrow-zone-pilot-design.md)
- 현재 통합 설계: [narrow-zone module integration](../superpowers/specs/2026-08-22-narrow-zone-module-integration-design.md)
- 협로 실측: [p0-narrow-zone-measurement.md](../runbooks/p0-narrow-zone-measurement.md)
