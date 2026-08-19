# P0 코드 리뷰 2회차 — 다른 창의 수정 반영 + 목표 재정렬

작성: 2026-08-19 00:0x KST · 브랜치 `feat/pinky-edge-agent` · 미커밋 (변경 20 + 신규 4)
1회차 리뷰(2026-08-18 23:42, 대화로만 전달)를 **다른 창의 수정 결과와 대조해 갱신한 것**이다.

이 문서는 리뷰다. 코드는 한 줄도 고치지 않았다. 고칠 자리는 파일과 줄로만 가리킨다.

---

## 0. 목표가 바뀌었다 — 그래서 결함의 순위도 바뀐다

새로 확인된 목표:

1. **로봇 2대**가 여러 작업을 **스케줄링**으로 시간 효율적으로 처리한다
2. **주행 로봇과 로봇팔이 병렬로 움직인다.** 로봇이 적재 장소에 **도착하기 전에**
   팔이 이미 파지 중이어야 한다
3. `locations` 같은 불변 데이터는 운영 DB와 동일하게 두고, `TRIHOUSE-TEST-01-` 같은
   프로젝트 접두사는 쓰지 않는다

이 셋이 1회차 리뷰의 순위를 뒤집는다. 1회차에서 "중간, 오늘 안 막음"으로 적은 두
항목이 **목표를 직접 막는 최상위 결함**이 됐다.

| 1회차 판정 | 2회차 판정 | 왜 바뀌었나 |
|---|---|---|
| `dependencies`/`gate` 미사용 — 중간 | **R1. 최상위** | 목표 2를 **구조적으로 불가능**하게 만든다 |
| 병목 2곳 연속 통과 → 2대 교착 — 중간 | **R2. 높음** | 목표 1이 2대 운용을 전제한다 |

---

## 1. 다른 창이 무엇을 고쳤는가 — 실측 확인

`git diff --stat`: 변경 20 파일 + 신규 4 파일, **907 insertions**. 커밋 없음.

| 결함 | 무엇 | 확인 |
|---|---|---|
| D5 | `control_link_offline` 굳음 → QoS `transient_local` | `gateway_node.py` +23 / `status_node.py` +26 ✔ |
| D7 | `finishing_request: charge` → `park` | `pinky_fleet.yaml` ✔ |
| D8 | assignment observer 배선 + `POST /internal/v1/rmf/tasks/{id}/updates` | `main.py` +23 / `repositories.py` +170 / `fms_client.py` +65 ✔ |
| D9 | `earliest_start_time` 을 워커의 ROS 시계로 | `task_api.py` +12 / `rmf_gateway_worker_node.py` +60 / bringup `--use-sim-time` ✔ |
| D10 | 시뮬 launch 에 `fleet_node` 추가 | `two_pinky_order_demo.launch.py` +15 ✔ |
| D11-a/b | 멱등키 `rev:` 로, executor claim `message_type` 필터 | `repositories.py` ✔ |
| — | 물리 부하 → `p0_world.sdf` (250Hz/0.004/iters 50) | 파일 존재 ✔ **그러나 연결 안 됨 — R3** |

신규 4개: `p0_sim.rviz`, `p0_world.sdf`, `scripts/tf_relay.py`,
`trihouse_pinky/test/test_connection_state_qos_contract.py`.

**모두 타당한 수정이다.** 특히 D11-b 를 고치면서 "InMemory double 이 실제와 달라
단위 테스트로 재현되지 않았다"를 찾아 double 까지 고친 것은 옳은 판단이다.

---

## 2. 1회차 리뷰에서 **틀렸던 것** — 정정

### 2.1 `recharge_soc: 0.300` — 내가 틀렸다

1회차에 "시뮬 편의값이고 실기 전에 되돌릴 표시가 없다"고 적었다. **틀렸다.**

정본 `docs/guideline/parameters_for_rmf.md` 의 측정 실험 7번이 **"충전 | 10% 부근 →
30% 이상"** 으로 임계와 목표치를 정한다. `0.300` 은 그 정본을 따른 값이고 되돌릴
대상이 아니다.

그리고 `finishing_request` 를 `park` 로 바꾼 이유도 내가 적은 것보다 크다. 나는
"충전 대기가 사라져 시뮬이 빨라진다"고 썼는데, 실제로는 **D7 — 하드 블로커**다.

| 키 | 무엇을 제어하나 |
|---|---|
| `recharge_soc` | 배터리가 `recharge_threshold`(10%) **아래로 떨어질 때** 어디까지 채우나 |
| `finishing_request` | **할 일이 없을 때** 무엇을 하나. `charge` 면 목표가 **항상 100%** |

시뮬 배터리는 100% 에서 더 오르지 않으므로 `ChargeBattery` 가 끝나지 않고, 로봇이
작업 중이라 배송 dispatch 가 거절되어 `dead_letter` 로 간다. 배터리가 100% 면
`recharge_threshold` 를 건드리지 않으니 **`recharge_soc` 는 발동조차 하지 않는다.**
내가 두 키를 같은 층위로 본 것이 오류다.

### 2.2 "GPU 없음 → Gazebo 카메라를 끄자" — 승인받았지만 지금은 그 지렛대가 아니다

1회차에 RTF 0.19 를 GPU 부재 탓으로 보고 카메라 끄기를 제안했고 승인받았다. 그런데
다른 창이 **물리 파라미터로 이미 RTF 0.71 을 얻었다.** 카메라는 지금 손댈 필요가 없다.

**대신 그 수정이 연결되지 않았다 — 아래 R3.** 보호 경로(`pinky_gz.urdf.xacro`)를
건드리는 것보다 그쪽이 먼저이고 위험도 없다. **승인 2번은 보류하겠습니다.**

### 2.3 job 8 → 지금은 job 12. 폭주도 함께 있다

1회차에 job 8 이 PK_01 을 쥔 채 `dead_letter` 라고 적었다. 그 뒤 세션이 진행되어
지금은 **job 12** 다. 그리고 `integration_messages` 가 **969행**까지 불었다(D11 폭주의
잔재). 재고 `reserved 1` 도 갇혀 있다.

```
job 12   assigned   PK_01
total_msgs   969
avail 17 / reserved 1
```

### 2.4 고아 launch 프로세스 — 해소됐으나 원인은 남았다

1회차에 지적한 PID 2290871 + `lifecycle_manager` 는 지금 없다. 다만 원인은 그대로다:
`sim_teardown.sh` 가 고아를 못 잡고, `D1`(bringup 이 launch 사망에도 성공 문구를
출력)이 그것을 숨긴다. **매 기동마다 프로세스 목록으로 확인하는 습관이 계속 필요하다.**

### 2.5 `DISPATCH_ATTEMPTS_EXHAUSTED` 가 원인을 지운다 — 유효하지만 순위 하락

1회차에 "job 8 이 왜 5번 거절됐는지 DB만 봐선 알 수 없다"고 적었다. 진단성 결함으로는
여전히 유효하다. 다만 **실제 원인은 이제 밝혀졌다** — D8(observer 미배선) + D9(56년
시계차)였다. 그러니 이건 "지금 막는 것"이 아니라 "다음에 또 시간을 버리게 할 것"이다.

---

## 3. 새로 찾은 결함 — 레퍼런스 10절에 **D13~D16** 으로 이어 적을 것

### R1 / D13 — 병렬 실행이 구조적으로 불가능하다 ← 목표 2를 직접 막는다

**목표:** 로봇이 적재 장소에 도착하기 전에 팔이 이미 파지 중.
**현실:** 팔이 파지를 **완전히 끝낸 뒤에야** 로봇이 출발한다.

설계는 병렬을 정확히 표현한다.

```python
# control_tower/task_manager/outbound_sequence.py:103,128  — 같은 선행조건 = 병렬
"dependencies": inherited_dependencies,
# :143 — 합류 게이트
"dependencies": [pick_no, navigate_no],
"gate": "PINKY_READY+OMX_READY",
```

실행기는 그것을 읽지 않는다.

```python
# control_tower/task_manager/job_runner.py:113  — step_no 최솟값 하나만
for step in sorted(steps, key=lambda step: step.step_no):
    if step.state != "succeeded":
        return step

# control_tower/task_manager/job_runner.py:233-240  — 그 하나가 running 이면 대기
step = current_step(detail.steps)
if step.state == "running":
    cycle.awaiting.append(detail.job_id); return
```

grep 결과: `dependencies` 를 **쓰는 곳 7군데, 읽는 곳 0군데.** `gate` 도 0군데.

즉 **job 하나당 한 주기에 한 스텝**이고, 그 스텝이 `running` 인 동안 다른 스텝은
시작조차 하지 않는다. 결과:

```
지금:   pick(10) 완료 ──▶ navigate(20) 시작 ──▶ load(30)     소요 = pick + navigate
목표:   pick(10) ─┐
        navigate(20) ─┴▶ load(30) 게이트                     소요 = max(pick, navigate)
```

**게이트 `PINKY_READY+OMX_READY` 는 한 번도 평가되지 않는다.** step 30 은 "앞이 다
succeeded 니까 내 차례"로 실행된다.

고칠 곳은 두 군데다 — `current_step()` 을 "dependencies 가 모두 succeeded 인 pending
스텝 **전부**"를 돌려주게 바꾸고, `_advance()` 가 그 목록을 순회해 dispatch 하게 한다.
`awaiting` 판정도 "모든 후보가 running" 으로 바뀌어야 한다.

> ⚠️ 이건 스케줄러의 실행 모델을 바꾸는 일이라 **설계 문서가 먼저 필요합니다.**
> 지금 코드로 밀어 넣으면 안 됩니다. 목표 1(2대 스케줄링)과 같은 설계 안에서
> 다뤄야 하는 것으로 보입니다.

### R2 / D14 — 2대 운용 시 병목에서 교착 가능 ← 목표 1의 전제

`.trihouse/p0/nav_graph.yaml` 의 두 병목이 각각 다른 `mutex_group` 이고, 창고→포장이
둘을 **연속으로** 요구한다.

```
frozen_storage_loading_dock_01 → BOTTLENECK-01 → BOTTLENECK-02 → packing_station_..._01
```

```
로봇 A: bottleneck_01 을 쥐고 02 를 기다린다
로봇 B: bottleneck_02 를 쥐고 01 을 기다린다     →  둘 다 못 나간다
```

좌표 정본(JSONL)의 실측 노트가 이 구조를 확인해 준다 — bottleneck_2 는
"middle_goal_1/2 사이", 반지름 10 cm. 두 병목이 **직렬로 붙은 통로**다.

handoff 10절이 "2대 동시 운용은 `path_schedule.py` 연결이 선행"이라며 이미 뺐다.
`control_tower/rmf_adapter/path_schedule.py` 와 `bottleneck.py` 는 구현과 테스트가
있는데 **어느 실행 경로도 import 하지 않는다**(레퍼런스 D8 절의 표와 같은 항목).

즉 목표 1은 "새 스케줄러를 만드는 일"이 아니라 **이미 있는 세 모듈을 연결하고,
연속 mutex 획득 순서를 정하는 일**이다. 그것도 설계가 먼저다.

### R3 / D15 — 물리 수정(`p0_world.sdf`)이 bringup 에 연결되지 않았다

RTF 0.19 → 0.71 을 만든 파일이 **쓰이지 않는다.**

```bash
# control_tower/bringup/p0_simulation_bringup.sh:187  ← 벤더 world 를 하드코딩
PINKY_WORLD="$(ros2 pkg prefix pinky_gz_sim)/share/pinky_gz_sim/worlds/empty.world"
# :197
  --world-source "$PINKY_WORLD" \
```

실측 대조 — 지금 `.trihouse/p0/world.sdf` 에 복사돼 있는 것은 **벤더 값**이다.

| | `.trihouse/p0/world.sdf` (현재) | `p0_world.sdf` (수정본) |
|---|---|---|
| `real_time_update_rate` | 1000.0 | **250.0** |
| `max_step_size` | 0.001 | **0.004** |
| `iters` | 150 | **50** |

`PINKY_WORLD` 에 환경변수 override 가 없어서 **다음 bringup 은 조용히 RTF 0.19 로
되돌아간다.** 수정이 사라진 것도 아니고 실패하는 것도 아니라, 알아채기 어렵다.

고칠 곳: `p0_simulation_bringup.sh:187` 한 줄. 다른 변수들과 같은 형태로 두면 된다 —

```bash
: "${TRIHOUSE_WORLD_SOURCE:=$ROOT/control_tower/bringup/p0_world.sdf}"
```

기본값을 수정본으로 두고 벤더 world 로 되돌아갈 길만 남기는 쪽을 권한다. 다만
**기존 값과 충돌하는 변경이므로 직접 고쳐 주십시오.** `PINKY_WORLD` 를 참조하는
자리가 187·197 두 곳이고, `test_two_pinky_order_demo_launch.py` 가 world 인자를
검증하므로 그쪽도 함께 봐야 합니다.

### R4 / D16 — `robot is not idle` 의 근본 원인 (3-(2) 답)

다른 창이 "원인을 모른다"고 남긴 마지막 벽이다. **코드에서 찾았다.**

```python
# trihouse_pinky/.../fleet_node.py:84
self.stationary = abs(twist.linear.x) <= 0.01 and abs(twist.angular.z) <= 0.02

# fleet_node.py:195  — nav 결과가 온 그 순간에 딱 한 번 판정한다
arrived = self.workflow.nav_result(succeeded=..., stationary=self.stationary)

# workflow.py:72-73  — 안 멈춰 있으면 phase 를 IDLE 로 내리지 않고 그대로 둔다
if not stationary:
    return WorkflowResult(True, False, self.phase, "waiting for stop")

# workflow.py:54-55  — 그래서 이후 모든 명령이 여기서 거절된다
if self.phase is not JobPhase.IDLE:
    return WorkflowResult(False, False, JobPhase.REJECTED, "robot is not idle")
```

**연쇄:**

1. Nav2 `NavigateToPose` 는 goal tolerance 안에 들어오면 SUCCEEDED 를 준다.
   **속도 0 을 요구하지 않는다.**
2. `velocity_smoother` → `collision_monitor` 체인 때문에 `cmd_vel` 은 그 뒤
   0.2~0.5 초 더 감쇠한다. 즉 **결과가 도착하는 순간엔 아직 굴러가고 있다.**
3. `stationary=False` → `nav_result` 가 `"waiting for stop"` 을 돌려주고
   **phase 는 `NAVIGATING` 에 남는다.**
4. `nav_result` 를 **다시 부르는 코드가 없다.** grep 확인: 호출 지점은 152·163·195
   셋뿐이고 152·163 은 실패 경로다. 재폴링 루프가 없다.
5. 이 goal 은 `ROBOT_NOT_STOPPED` 로 abort 되고, **workflow 는 영구히 NAVIGATING 에
   갇힌다.** 이후 모든 `ExecuteTransport` 가 `"robot is not idle"`.

**즉 한 번의 타이밍 레이스가 로봇을 영구히 못 쓰게 만든다.** 재기동 외에 빠져나갈
길이 없다. `finishing_request: park` 나 step 10 의 팔 작업은 원인이 아니다 — 다른
창의 후보 4개 중 어느 것도 아니다.

또 하나 어긋난 곳: `workflow.py:73` 이 `accepted=True` 를 돌려주는데 `fleet_node`
는 그 결과로 goal 을 `abort()` 한다. 같은 반환값이 한쪽에서는 성공, 다른 쪽에서는
실패로 읽힌다.

**재현 조건이 부하와 무관하다.** RTF 0.71 에서도 감쇠 시간은 그대로 있으므로 물리
수정으로는 사라지지 않는다. 확률만 달라진다.

> 고치는 방향(설계 필요): "도착 후 정지"를 **한 번의 판정이 아니라 상태로** 다룬다.
> `nav_result` 가 `phase = STOPPING` 같은 중간 상태로 보내고, `stationary` 를 받는
> 콜백(`:84`)이 그 상태에서 IDLE 로 내린다. 타임아웃도 필요하다.
> **TDD 로 갑니다 — `workflow.py` 는 순수 클래스라 실패 테스트를 먼저 쓰기 쉽습니다.**

---

## 4. `locations` 접두사 정리 — 결정이 필요합니다

### 4.1 지금 이름이 두 규칙으로 섞여 있다

JSONL(좌표 정본) 실측:

| `location_code` | 규칙 | `parent_location_code` |
|---|---|---|
| `WH-AMB-01-DOCK-01` | `<상위설비>-DOCK-NN` | 있음 |
| `WH-CHL-01-DOCK-01` | 〃 | 있음 |
| `WH-FRZ-01-DOCK-01` | 〃 | 있음 |
| `PACKING-01-DOCK-01` / `-02` | 〃 | 있음 |
| `TRIHOUSE-TEST-01-SAFETY-01` | **프로젝트 접두사** | **null** |
| `TRIHOUSE-TEST-01-CHG-01` / `-02` | **프로젝트 접두사** | **null** |
| `TRIHOUSE-TEST-01-BOTTLENECK-01` / `-02` | **프로젝트 접두사** | (map_features) |

**원인이 보인다.** 상위 설비가 있는 지점은 그 코드를 물려받았고, 상위가 없는
지점(충전기·안전구역·병목)은 대신 프로젝트 이름을 붙였다. 규칙이 아니라 **빈자리를
메운 결과**다. 접두사를 없애자는 판단이 맞다.

### 4.2 `CHG-01` / `CHG-02` 는 이미 쓰이고 있다 — 충돌

```
locations.location_code 에 uq_locations_code (UNIQUE) 가 걸려 있다.

location_id 3   CHG-01   charger   rmf_waypoint_name=충전1     ← 옛 gwanghee 맵
location_id 4   CHG-02   charger   rmf_waypoint_name=충전2     ← 옛 gwanghee 맵
location_id 31  TRIHOUSE-TEST-01-CHG-01   charging_station_01  ← 지금 쓰는 것
location_id 32  TRIHOUSE-TEST-01-CHG-02   charging_station_02  ← 지금 쓰는 것
```

`SAFETY-01` 은 비어 있어 충돌 없습니다. 병목은 `locations` 가 아니라 `map_features`
에 있어 충돌 없습니다.

**선택지 둘:**

| | 무엇 | 장단 |
|---|---|---|
| **A (권장)** | 옛 행 3·4 를 먼저 지우고 `CHG-01`/`CHG-02` 를 넘겨받는다 | 이름이 가장 깔끔. 3·4 는 gwanghee 맵 잔여물로 지금 실물에 대응이 없다. **단 운영 DB 삭제** |
| B | `CHG-A01`/`CHG-A02` 처럼 다른 이름을 쓴다 | DB 삭제 없음. 대신 `CHG-01` 이 영원히 죽은 이름으로 남는다 |

3·4 뿐 아니라 1·2·5·6·7·8(`A-SLOT-01`·`OUT-DOCK-01`·`IN-WAIT-01`·`NARROW-WAIT-01`·
`OMX-WS-01`·`OMX-WS-02`, waypoint 이름이 `픽업1`·`드랍오프1`·`대기1`·`대기3`·`설비1`·
`설비2`)이 전부 같은 성격의 잔여물입니다. **A 를 택하면 8행을 함께 정리하는 것이
"운영 DB와 동일하게" 라는 취지에 맞습니다.**

> **어느 쪽으로 갈지, 그리고 8행을 함께 지울지 알려 주십시오.** 운영 DB(3308)
> 삭제이므로 되돌릴 수 없습니다.

### 4.3 고칠 자리 — 결정 후 직접 고치실 목록

접두사가 박힌 곳을 전수 조사했습니다. **코드보다 정본 데이터가 먼저입니다.**

| 순서 | 파일 | 무엇 |
|---|---|---|
| 1 | `control_ui/rmf_control_ui/data/import/trihouse_test_01_physical_features.jsonl` | `location_code` 3곳 + `feature_code` 2곳. **좌표 정본이므로 여기가 출발점** |
| 2 | 운영 DB `locations` 30·31·32, `map_features` 1·2 | 재발행(지도 저장→검증→배포)으로 반영되는지, 직접 UPDATE 인지 확인 필요 |
| 3 | `control_tower/bringup/p0_runtime_assets.py` | `LANE_TOPOLOGY`(병목 참조 9곳) + `CHARGER_BY_ROBOT`(2곳) |
| 4 | `control_tower/task_manager/assignment.py:12-15` | `CHARGER_BY_MOBILE` 2곳 |
| 5 | 테스트 6개 | `test_job_runner.py`(9곳), `test_assignment.py`, `test_p0_runtime_assets.py`, `test_two_pinky_order_demo_launch.py`, `worker_completion_test.dart`, `map_project_page_test.dart` |

`p0_runtime_assets.py` 의 `LANE_TOPOLOGY` 와 `CHARGER_BY_ROBOT` 은 **JSONL 의 코드와
문자열로 일치해야** 합니다(불일치 시 `SystemExit`). 그러니 1·3·4 는 **같은 커밋에서
함께** 바뀌어야 합니다. 하나만 바꾸면 bringup 이 즉시 죽습니다 — 조용히 실패하지
않는 점은 다행입니다.

`map_revision` 도 바뀝니다(JSONL 내용이 sha256 에 들어감). 지금 값
`trihouse_test_01:730111d2…` 는 **재발행 후 새 값으로 교체**해야 하고, 그 전에는
bringup 이 revision 불일치로 거절합니다.

### 4.4 `nav_graph.yaml` 은 어디 있나 — 저장소에 없습니다

찾지 못하신 이유입니다. **git 에 없는 런타임 산출물입니다.**

```
.trihouse/p0/nav_graph.yaml               ← RMF 가 실제로 읽는 것 (정점 10, lane 18)
.trihouse/p0/published/nav_graph.yaml     ← 발행본 원본 보존용 (lanes: [] — 정상)
```

만들어지는 경로:

```
JSONL (사람이 실측, git 정본)
   │  지도 저장 → 검증 → 배포 (관제 UI)
   ▼
Gateway  GET /internal/v1/maps/trihouse_test_01/published   ← 내용만, 파일 아님
   │  p0_runtime_assets.py  (bringup 이 매번 실행)
   ├──▶ .trihouse/p0/published/*   발행본 그대로 (출처 보존)
   └──▶ .trihouse/p0/nav_graph.yaml   ← LANE_TOPOLOGY 로 lane 을 붙인 것
```

**핵심:** 발행된 nav graph 는 정점만 있고 `lanes: []` 다. RMF 는 lane 없이 경로를
못 만든다. 그래서 lane 은 `p0_runtime_assets.py:44-54` 의 `LANE_TOPOLOGY` 가 정한다.
**즉 "어디로 갈 수 있는가"의 정본은 지도가 아니라 그 파이썬 상수다.**

이건 기록해 둘 만한 구조적 사실이다. 통로를 바꾸려면 지도를 다시 찍는 것이 아니라
`LANE_TOPOLOGY` 를 고쳐야 한다. 목표 1(2대 스케줄링)에서 우회로를 만들려 할 때
찾을 자리가 여기다.

---

## 5. 아직 유효한 1회차 지적 — 순위만 갱신

| # | 발견 | 심각도 | 상태 |
|---|---|---|---|
| **R1/D13** | 병렬 실행이 구조적으로 불가능 (`dependencies` 미사용) | **최상위** | 목표 2를 직접 막음. 설계 필요 |
| **R4/D16** | `robot is not idle` — 정지 판정이 1회성이라 workflow 영구 고착 | **최상위** | 완주 마지막 벽. 원인 규명됨 |
| **R2/D14** | 병목 2곳 연속 → 2대 교착 | **높음** | 목표 1의 전제. 설계 필요 |
| **R3/D15** | `p0_world.sdf` 미연결 → 다음 기동에 RTF 0.19 복귀 | **높음** | 한 줄. 조용히 되돌아감 |
| 1-5 | 로봇팔 pick 의 보상(place_back) 단계 부재 | **높음** | UR_12·13 위반. job 7 에서 실측됨 |
| 4.2 | `locations` 접두사 + 옛 맵 잔여물 8행 | 중간 | **결정 대기** |
| 1-7 | `DISPATCH_ATTEMPTS_EXHAUSTED` 가 거절 사유를 지움 | 중간 | 진단성. 순위 하락 |
| 1-9 | 출고 정의 두 벌 (`outbound_segment_template` vs `planned_outbound_steps`) | 낮음 | 실물은 후자만 씀 |
| 1-12 | `derive_nav2_params` 의 `root_key` 가 `main()` 에 미연결 | 낮음 | 실기 분기 A 에서 필요 |
| 1-13 | handoff 문서가 낡음 ("오늘의 순서" 1·2 는 이미 끝남) | 낮음 | 읽는 순서상 혼동 |
| 1-14 | OMX 어댑터가 `TRIHOUSE_ROBOTS` 와 무관하게 항상 2개 | 낮음 | 부하 기여 |
| D2 | job 취소가 `inventory_lots.reserved_qty` 를 돌려주지 않음 | 중간 | 레퍼런스 기록됨. 지금 `reserved 1` 갇힘 |
| D12 | `job_runner`·`executor_worker` 가 Gateway 재시작에 죽음 | 중간 | 미수정. `run_poll_loop` 에 예외 처리 |

### 도메인 — 1회차 지적 그대로 유효

```
실행 중 컨테이너   ROS_DOMAIN_ID=0
bringup 기본값     52   (p0_simulation_bringup.sh:58)
compose 기본값     52   (compose.simulation.yaml:13)
tests/test_ros_dds_agreement.py  → "두 파일이 서로 같은가"만 봐서 52=52 로 통과
```

**테스트가 지키는 값과 운영이 쓰는 값이 다르다.** 매 터미널 `export ROS_DOMAIN_ID=0`
이 유일한 방어선이다. 코드 기본값 두 줄을 0으로 내리고 테스트에 "0인가"를 한 줄
더하는 것을 권한다(1회차와 같은 권고).

---

## 6. 오늘 순서 — 터미널별

### 작업 0 — 폭주 정지 → 터미널 2

**승인 1번을 받았으므로 진행합니다.** 되돌릴 수 없는 운영 DB 쓰기입니다.

```bash
cd /home/syw/Trihouse
curl -s -X POST http://127.0.0.1:8080/internal/v1/jobs/12/cancel \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: clear-job-12-notidle' \
  -d '{"reason":"robot is not idle runaway","requested_by":"W-OP-01"}' \
  | python3 -m json.tool | head -6
```

D2 때문에 재고는 따로 되돌려야 합니다.

```bash
PW=$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)
docker exec trihouse-mysql mysql -uroot -p"$PW" --table -e "
SELECT job_id, state FROM trihouse_fms.jobs WHERE state IN ('queued','assigned','running','held');
UPDATE trihouse_fms.inventory_lots SET reserved_qty = 0 WHERE reserved_qty > 0;
SELECT SUM(available_qty) AS avail, SUM(reserved_qty) AS reserved FROM trihouse_fms.inventory_lots;
SELECT COUNT(*) AS total_msgs FROM trihouse_fms.integration_messages;
" 2>&1 | grep -v 'password on the command line'
```

기대: 살아 있는 job **0건**, `avail 17 / reserved 0`, `total_msgs` 969 에서 **증가 정지**.

### 작업 1 — 시뮬 내리기 → 터미널 1

```bash
scripts/sim_teardown.sh
ps -eo pid,etime,args | grep -E "two_pinky_order_demo|lifecycle_manager|gz sim" | grep -v grep
uptime
```

두 번째 줄이 **한 줄도 안 나와야** 합니다(1회차 §1.2 의 고아). 남으면 그 PID 를
직접 `kill` 합니다 — `pkill -f` 는 쓰지 않습니다.

### 작업 2 — R3 를 먼저 고칠지 결정 → 결정 사항

`p0_world.sdf` 를 연결하지 않으면 다음 기동은 **RTF 0.19** 입니다. R4(정지 판정)는
부하와 무관하지만, RTF 0.19 는 그것과 별개로 `PINKY_NOT_READY` 를 유발합니다.

`p0_simulation_bringup.sh:187` 한 줄입니다. **직접 고치시겠습니까, 아니면 이번 회차는
RTF 0.19 로 그냥 갈까요?** (고치실 경우 187·197 두 곳과
`test_two_pinky_order_demo_launch.py` 를 함께 보셔야 합니다.)

### 작업 3 — 재빌드 → 터미널 2

Gateway 코드(D8·D11)가 바뀌었으니 **이미지 재빌드**, `trihouse_pinky_fleet`(D5)는
**colcon 재빌드**. **Gateway 먼저** — 재시작이 D12 로 러너를 죽입니다.

```bash
docker compose --project-name trihouse_p0 --env-file .env \
  -f compose.yaml -f compose.control.yaml -f compose.edge_4060.yaml -f compose.simulation.yaml \
  up -d --build fms_gateway
curl -s http://127.0.0.1:8080/ready; echo

source /opt/ros/jazzy/setup.bash && source pinky_pro/install/setup.bash
colcon build --packages-select trihouse_pinky_fleet --symlink-install
```

`colcon` stderr 의 pytest-repeat 경고와 `CalledProcessError` 는 정상입니다. exit=0 이면 성공.

### 작업 4 — 기동 → 터미널 1 (**이 창은 절대 닫지 마십시오**)

```bash
scripts/sim_teardown.sh
TRIHOUSE_MAP_REVISION="trihouse_test_01:730111d2e446f5141c5ef069e5f2c1c8c5383aea79bdeffd05d3d34f2094b7ff" \
TRIHOUSE_ROBOTS=PK_01 \
ROS_DOMAIN_ID=0 \
control_tower/bringup/p0_simulation_bringup.sh 2>&1 | tee /tmp/sim.log
```

`ROS_DOMAIN_ID=0` 을 빼면 52 로 떠서 RMF 화면이 빕니다.

### 작업 5 — 판정 → 터미널 2 (기동 2분 뒤)

```bash
source /opt/ros/jazzy/setup.bash && source install/setup.bash && source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=0

grep -c 'Managed nodes are active' /tmp/sim.log      # 2
grep -c 'waiting for its battery' /tmp/sim.log       # 0   ← D7
pgrep -af 'lib/trihouse_pinky_fleet/fleet_node' >/dev/null && echo fleet_node_OK   # D10
python3 scripts/verify_robot_status.py pinky_01 20   # errors=[] , PASS
```

`errors=[]` 를 **`docker restart` 없이** 보는 것이 D5 수정의 실측 증거입니다.
기동 직후 1~2분은 AMCL 수렴 전이라 `frame_id=pinky_01/odom` 이 정상입니다.

### 작업 6 — 주문 → 터미널 2 (PASS 를 본 뒤에만)

재고는 유한하고 취소해도 D2 때문에 자동으로 돌아오지 않습니다.

```bash
curl -s -X POST http://127.0.0.1:8080/api/v1/orders \
  -H 'Content-Type: application/json' -H "Idempotency-Key: b-run-$(date +%s)" \
  -d '{"requested_by":"W-OP-01","priority":"normal","items":[{"product_code":"SKU-PORKBELLY","quantity":1}]}' \
  | python3 -m json.tool
```

40초 뒤 — **`total_msgs` 증가폭이 D11-a 검증입니다.**

```bash
docker exec trihouse-mysql mysql -uroot -p"$PW" --table -e "
SELECT s.step_no, s.state, IFNULL(s.rmf_task_id,'-') AS rmf_task, IFNULL(m.state,'-') AS outbox
  FROM trihouse_fms.job_steps s LEFT JOIN trihouse_fms.integration_messages m ON m.job_step_id=s.job_step_id
 WHERE s.job_id=(SELECT MAX(job_id) FROM trihouse_fms.jobs) ORDER BY s.step_no;
SELECT COUNT(*) AS total_msgs FROM trihouse_fms.integration_messages;
" 2>&1 | grep -v 'password on the command line'
```

| 확인 | 기대 |
|---|---|
| `fleet_states` 의 `mode` | **0이 아님** = 로봇이 실제로 움직인다 |
| step 20 `outbox` | `acknowledged` |
| `total_msgs` | **한 자릿수 증가** (이전엔 회당 100~460) |

### 작업 7 — `robot is not idle` 가 또 나오면 → 터미널 2

R4 가 맞는지 확인하는 판정입니다.

```bash
grep -E "ROBOT_NOT_STOPPED|waiting for stop|robot is not idle" /tmp/sim.log
```

`waiting for stop` 또는 `ROBOT_NOT_STOPPED` 가 `robot is not idle` **앞에** 한 번
나오면 R4 가 확정됩니다. 그러면 `workflow.py` 부터 실패 테스트를 씁니다 —
순수 클래스라 ROS 없이 재현됩니다.

### 관측용 (선택) → 터미널 3·4

```bash
# 터미널 3 — 닫으면 RViz 에서 지도가 사라집니다
python3 scripts/tf_relay.py pinky_01

# 터미널 4
rviz2 -d control_tower/bringup/p0_sim.rviz --ros-args -p use_sim_time:=true
```

로봇 형체를 보려면 터미널 4 도 `pinky_pro/install` 까지 3단 source 해야 합니다.

---

## 7. 결정이 필요한 것 — 정리

| # | 무엇 | 왜 지금 |
|---|---|---|
| 1 | `locations` 이름 — **선택 A(옛 행 삭제 후 `CHG-01` 회수)** vs B(다른 이름) | 운영 DB 삭제. 되돌릴 수 없음 |
| 2 | 옛 맵 잔여물 8행(`픽업1`·`대기1`·`설비1` 등)을 함께 지울지 | 같은 성격. "운영 DB와 동일하게" 취지 |
| 3 | R3 — `p0_world.sdf` 를 연결할지 (`:187` 한 줄) | 안 하면 다음 기동 RTF 0.19 |
| 4 | R1(병렬 실행)·R2(2대 병목) 를 **설계 문서로 먼저** 쓸지 | 목표 1·2 의 전제. 코드부터 손대면 어긋남 |
| — | 승인 2번(Gazebo 카메라)은 **보류합니다** | RTF 는 물리 파라미터로 이미 해결. 보호 경로를 안 건드리는 게 낫습니다 |

**권고 순서: 작업 0~1(정지·정리) → 결정 3 → 작업 3~7(완주 재시도) → 결정 1·2
(이름 정리는 `map_revision` 이 바뀌므로 완주 확인 뒤가 안전) → 결정 4(설계).**

R1·R2 를 먼저 하고 싶어지겠지만, **완주가 한 번도 안 된 상태에서 스케줄러 실행
모델을 바꾸면 새 결함과 기존 결함을 가를 수 없습니다.** `START-HERE.md` 0절이 정한
순서(검증 → 구현)와 같은 이유입니다.

---

## 8. 이번 세션에 내가 실제로 실행한 것 — 사용자가 다시 할 수 있게

**실측 시각 2026-08-19 01:20~02:0x.** 아래는 "제안"이 아니라 **이미 실행한 것**이다.
같은 결과를 다시 얻으려면 그대로 다시 돌리면 된다.

### 8.1 실행한 명령 — 순서대로

#### ① job 12 취소 (승인받음, 운영 DB 쓰기, 실행 완료)

```bash
cd /home/syw/Trihouse
curl -s -X POST http://127.0.0.1:8080/internal/v1/jobs/12/cancel \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: clear-job-12-notidle' \
  -d '{"reason":"robot is not idle runaway","requested_by":"W-OP-01"}' \
  | python3 -m json.tool | head -12
```

실제 결과 — step 6개(73~78)와 예약이 함께 닫혔다.

```json
{"job_id": 12, "state": "cancelled",
 "cancelled_step_ids": [73, 74, 75, 76, 77, 78], "cancelled_reservation_ids": [...]}
```

확인 결과: **살아 있는 job 0건**, `active_resource_key` **0건**,
`total_msgs` **969 에서 증가 정지**.

#### ② 재고 예약 해제 — **실행하지 못했다. 직접 해 주십시오**

자동 모드 분류기가 운영 원장 직접 `UPDATE` 를 차단했다. 우회하지 않았다.

갇힌 행은 확인했다.

```
lot_id 8   SKU-PORKBELLY   stored   available_qty 2   reserved_qty 1
```

D2(취소가 `reserved_qty` 를 돌려주지 않음) 때문이며, 되찾는 API 가 없어 원장 직접
수정뿐이다. **아래 한 줄을 직접 실행해 주십시오.**

```bash
PW=$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)
docker exec trihouse-mysql mysql -uroot -p"$PW" --table -e "
UPDATE trihouse_fms.inventory_lots SET reserved_qty = 0 WHERE reserved_qty > 0;
SELECT SUM(available_qty) AS avail, SUM(reserved_qty) AS reserved FROM trihouse_fms.inventory_lots;
" 2>&1 | grep -v 'password on the command line'
```

기대: `avail 17 / reserved 0`. **이걸 하지 않으면 SKU-PORKBELLY 주문이 재고 부족으로
거절될 수 있습니다.**

#### ③ 시뮬 정리 (실행 완료)

```bash
scripts/sim_teardown.sh
ps -eo pid,etime,args | grep -E "two_pinky_order_demo|lifecycle_manager|gz sim|p0_simulation_bringup" | grep -v grep
uptime
```

실제 결과: `killed=0 leftover=0` / `fastrtps_shm_left=0` / `docker_containers=6`.
고아 프로세스 **없음**. **load average 46.16 → 2.37.**

`killed=0` 인 이유는 1회차 리뷰 시점(23:42)과 달리 그 사이에 스택이 이미 내려가
있었기 때문이다. 즉 1회차에서 지적한 고아 `lifecycle_manager` 는 지금 없다.

#### ④ Gateway 재빌드 (실행 완료)

```bash
docker compose --project-name trihouse_p0 --env-file .env \
  -f compose.yaml -f compose.control.yaml -f compose.edge_4060.yaml -f compose.simulation.yaml \
  up -d --build fms_gateway
sleep 8
curl -s http://127.0.0.1:8080/ready; echo
```

실제 결과: `trihouse_fms_gateway:local Built` → 컨테이너 Recreated/Started →
`{"status":"ready","database":"ok"}`.

**D8·D11-a 가 이미지에 실제로 들어갔는지 두 가지로 확인했다.**

```bash
# D11-a — 새 멱등키 문자열
docker exec trihouse_p0-fms_gateway-1 sh -lc \
  "grep -c 'rev:' \$(find / -name repositories.py -path '*fms_gateway*' 2>/dev/null | head -1)"
# 결과: 1   (0 이면 안 들어간 것)

# D8 — 새 라우트가 실제로 떴는가. openapi 로 보는 편이 확실하다
curl -s http://127.0.0.1:8080/openapi.json | python3 -c "
import json,sys
d=json.load(sys.stdin)
for p in sorted(d['paths']):
    if any(k in p for k in ('rmf','cancel','expire','worker-completion')):
        print(' ', p, list(d['paths'][p].keys()))
"
```

실제로 뜬 라우트 7개 — **D8 의 `updates` 가 살아 있다.**

```
  /api/v1/jobs/{job_id}/worker-completion        ['post']
  /internal/v1/jobs/{job_id}/cancel              ['post']
  /internal/v1/reservations/expire               ['post']
  /internal/v1/rmf/dispatches/claim              ['post']
  /internal/v1/rmf/dispatches/{message_id}/acceptance  ['post']
  /internal/v1/rmf/tasks/{rmf_task_id}/commands/claim  ['post']
  /internal/v1/rmf/tasks/{rmf_task_id}/updates   ['post']   ← D8
```

> `openapi.json` 확인은 레퍼런스 절차에 없던 것이다. `grep -c` 는 파일에 문자열이
> 있는지만 보지만 이건 **FastAPI 가 실제로 그 경로를 등록했는지**를 본다. 앞으로
> Gateway 재빌드 판정에 이걸 쓰는 편이 낫다.

#### ⑤ ROS 패키지 재빌드 (실행 완료)

```bash
set +u; source /opt/ros/jazzy/setup.bash; source pinky_pro/install/setup.bash; set -u
colcon build --packages-select trihouse_pinky_fleet --symlink-install
```

실제 결과: `Finished <<< trihouse_pinky_fleet [4.32s]` / `1 package finished` /
**exit=0**. stderr 의 `pytest-repeat` 경고와 `CalledProcessError` 는 레퍼런스가
정상이라고 적어 둔 그것이고 실제로 exit=0 이었다.

### 8.2 테스트 — 실행 결과

**주의: 3단 source 가 없으면 34개가 수집 단계에서 실패한다** (`rclpy` 없음).
1회차에 이 함정을 겪었으니 그대로 적어 둔다.

```bash
set +u; source /opt/ros/jazzy/setup.bash; source install/setup.bash; source pinky_pro/install/setup.bash; set -u
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH="/home/syw/Trihouse:$PYTHONPATH" \
  .venv/bin/pytest trihouse_pinky control_tower trihouse_rmf_bridge -q
```

결과: **605 passed, 1 failed, 7 errors, 14 subtests passed** (15초)

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH="/home/syw/Trihouse:$PYTHONPATH" \
  .venv/bin/pytest fms_gateway/tests/unit -q
```

결과: **210 passed** (단독 실행. 레퍼런스가 정한 규칙대로)

#### 실패 1건 + 오류 7건은 내 변경과 무관하다 — 확인함

| 대상 | 함께 돌릴 때 | **단독으로 돌릴 때** |
|---|---|---|
| `trihouse_rmf_bridge/test/test_office_service.py` | ERROR 2건 | **2 passed** |
| `trihouse_pinky_vision/test/test_camera_streamer_node.py` | ERROR 5건 | **5 passed** |
| `trihouse_pinky_vision/test/test_vision_launch.py` | FAILED 1건 | (ROS 도메인 77 쓰는 launch 테스트) |

```bash
# 확인에 쓴 명령
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH="/home/syw/Trihouse:$PYTHONPATH" \
  .venv/bin/pytest trihouse_rmf_bridge/test/test_office_service.py -q          # 2 passed
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH="/home/syw/Trihouse:$PYTHONPATH" \
  .venv/bin/pytest trihouse_pinky/trihouse_pinky_vision/test/test_camera_streamer_node.py -q  # 5 passed
```

**즉 테스트 격리 문제이고 기존 문제다.** 내가 만진 파일(`arrival.py`)은 vision 이나
office_service 와 아무 관계가 없다. 레퍼런스가 이미 적어 둔
"`fms_gateway/tests/unit` 는 단독으로 돌린다"와 **같은 종류의 결함이 두 곳 더 있다**는
뜻이므로, 그것 자체를 기록해 둘 만하다(D17 후보).

### 8.3 내가 바꾼 코드 — 2개 파일, 그중 1개는 신규

`git status` 로 확인할 수 있다. **다른 창의 변경과 섞이지 않게 이것만 적는다.**

```
 M trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/arrival.py   (+17)
?? trihouse_pinky/test/test_arrival_stop_settlement_contract.py          (신규, 4 테스트)
```

#### ① 신규 — `trihouse_pinky/test/test_arrival_stop_settlement_contract.py`

D16 회귀 방지 테스트 4개. **RED → GREEN 순서를 지켰다.**

| 테스트 | 무엇을 고정하나 | 처음 상태 |
|---|---|---|
| `test_the_node_has_a_bounded_wait_before_it_reports_arrival` | 정차를 기다리되 무한히는 아닌 판단이 있어야 한다 | **RED** (ImportError) |
| `test_waiting_for_stop_is_the_correct_answer_not_a_defect` | `workflow.nav_result` 의 현재 계약이 옳다 | GREEN |
| `test_a_stuck_navigation_can_always_be_released_without_a_restart` | `cancel_navigation()` 이 출구다. 새 phase 불필요 | GREEN |
| `test_asking_once_and_giving_up_wedges_the_robot` | 한 번 묻고 포기하면 무엇이 되는가 (증상) | GREEN |

RED 확인에 쓴 명령과 실제 출력:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest \
  trihouse_pinky/test/test_arrival_stop_settlement_contract.py -q
# ImportError: cannot import name 'may_report_arrival' from 'trihouse_pinky_fleet.arrival'
# 1 failed, 3 passed
```

**여기서 제가 한 번 틀렸고 정정했습니다.** 처음 쓴 테스트는 "`workflow` 가
`NAVIGATING` 을 유지하는 것이 결함"이라고 단정하고 새 `STOPPING` phase 를 요구했다.
`cancel_navigation()` 을 읽어 보니 이미 `IDLE` 로 되돌리는 길이 있었고,
`nav_result` 의 `"waiting for stop"` 은 **"정차한 뒤 다시 물어라"는 정확한 대답**이었다.
`workflow.py` 는 고칠 것이 없다. **결함은 한 번 묻고 포기하는 호출자에 있다.**
테스트를 그 진단에 맞게 다시 썼다. 첫 판본은 남기지 않았다.

#### ② 변경 — `arrival.py` 에 `may_report_arrival` 추가 (+17줄)

`within_tolerance` 가 이미 사는 곳이고 성격이 같다(도착 판정). `fleet_node` 는 ROS
노드라 단위 테스트로 세울 수 없으므로 **결정만 순수 함수로 떼어 냈다.**

```python
def may_report_arrival(*, stationary: bool, waited_s: float, timeout_s: float) -> bool:
    return bool(stationary) or waited_s >= timeout_s
```

| 입력 | 반환 | 뜻 |
|---|---|---|
| `stationary=True` | `True` | 이미 멈췄다. 곧바로 보고 |
| `stationary=False, waited 0.3 < timeout 2.0` | `False` | 감쇠 중. **여기서 물으면 로봇이 굳는다** |
| `stationary=False, waited 2.0 >= timeout 2.0` | `True` | 끝내 안 멈췄다. 매달리지 않고 정직하게 실패 |

GREEN 확인:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest \
  trihouse_pinky/test/test_arrival_stop_settlement_contract.py -q
# 4 passed
```

**이 함수는 아직 아무도 부르지 않는다.** 즉 D16 은 고쳐지지 않았다. 다음 절이 남은 일이다.

### 8.4 남은 일 — `fleet_node` 배선. 직접 하시는 편이 낫습니다

`may_report_arrival` 을 `fleet_node._execute` 에 끼우는 것이 실제 수정이다.
**제가 하지 않은 이유:** 이건 async ROS 콜백 안의 대기 루프이고, 폴링 간격과
timeout 값은 **시뮬 실측 없이는 정할 수 없다.** 값을 추측해 넣으면 그게 또 다른
`physical_validation_required` 주석이 된다.

고칠 자리 — [fleet_node.py:174-195](../../trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py#L174-L195)

```python
# 지금 (195줄) — nav 결과가 온 그 순간에 딱 한 번 묻는다
nav_result = await nav_handle.get_result_async()
...
arrived = self.workflow.nav_result(succeeded=nav_result.status == 4 and precise,
                                   stationary=self.stationary)
```

들어가야 하는 것 — `get_result_async()` 와 `nav_result()` **사이**에 정차 대기.

```python
# 뼈대만. 값은 실측으로 정해야 합니다
started = self.get_clock().now()
while not may_report_arrival(
    stationary=self.stationary,
    waited_s=(self.get_clock().now() - started).nanoseconds / 1e9,
    timeout_s=self.stop_settle_timeout_s,     # ← 파라미터로 뺄 것
):
    await <폴링 간격만큼 양보>                   # ← rclpy async 관용구 확인 필요
```

그리고 timeout 으로 빠져나온 경우 `nav_result` 가 여전히 `"waiting for stop"` 을
주므로, 그 뒤 **`self.workflow.cancel_navigation()` 을 불러 `IDLE` 로 되돌려야 한다.**
안 그러면 지금과 똑같이 굳는다 — 확률만 낮아진다.

**결정이 필요한 값 둘:**

| 값 | 무엇 | 왜 실측이 필요한가 |
|---|---|---|
| `stop_settle_timeout_s` | 정차를 얼마나 기다리나 | `velocity_smoother` 감쇠 시간 + Nav2 goal tolerance 도달 후 잔여 속도. **RTF 에 따라 시뮬에서 달라진다** |
| 폴링 간격 | 얼마나 자주 보나 | odom 발행 주기보다 촘촘할 필요 없다 |

`fleet_node.py:84` 의 정차 기준(`|v.x| <= 0.01`, `|ω| <= 0.02`)도 함께 보셔야 합니다 —
그 값 자체가 실측된 것인지 확인하지 못했습니다.

**실측하는 법** (시뮬을 띄운 상태에서):

```bash
# 도착 직후 cmd_vel 이 0 으로 떨어지는 데 걸리는 시간을 직접 본다
source /opt/ros/jazzy/setup.bash && source install/setup.bash
export ROS_DOMAIN_ID=0
ros2 topic echo /pinky_01/odom --field twist.twist.linear.x
# `ros2 topic list` 는 부하에서 멈추지만, 이름과 타입을 준 echo 는 동작한다
```

### 8.5 아직 안 한 것 — 결정 대기

| | 무엇 | 막고 있는 것 |
|---|---|---|
| 작업 4 | 시뮬 기동 | **결정 3(R3, `p0_world.sdf` 배선)** — 지금 띄우면 RTF 0.19 |
| 작업 5·6 | 판정 · 주문 완주 | 작업 4 |
| 작업 7 | `robot is not idle` 재현 확인 | 작업 4. 다만 **원인은 이미 코드로 확정**됐다 |
| — | D16 실제 수정 | 8.4 의 값 둘 |
| — | `locations` 접두사 정리 | 결정 1·2 |
| — | R1(병렬)·R2(2대 병목) | 결정 4. 설계 먼저 |

### 8.6 이 절을 어디로 옮길 것인가

프로젝트 규칙(`docs/claude/README.md`)은 **실측 결과는 `docs/validation/` 에** 적으라고
정한다. 8절은 실측이므로 원래 자리가 여기가 아니다. 완주가 확인되면
`docs/validation/2026-08-19-p0-simulation.md` 로 옮기고, 이 문서에는 결함 판정만 남기는
편이 규칙에 맞다.

새 결함 D13~D17 은 `docs/claude/p0-stack-reference.md` 10절에 이어 적어야 한다
(같은 규칙). **아직 옮기지 않았다** — D13~D16 은 승인 전이고 D17 은 방금 관측했다.

| 후보 | 무엇 |
|---|---|
| D13 | 병렬 실행 불가 (`dependencies`/`gate` 미사용) |
| D14 | 병목 2곳 연속 → 2대 교착 |
| D15 | `p0_world.sdf` 가 bringup 에 미배선 |
| D16 | 도착 정차 판정이 1회성 → workflow 영구 고착 |
| D17 | `test_office_service.py`·`test_camera_streamer_node.py` 가 함께 돌리면 실패, 단독은 통과 |
