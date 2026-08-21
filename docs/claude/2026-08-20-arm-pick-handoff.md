# step 10 `arm/pick` 구현 인계서

작성 2026-08-20 · 브랜치 `feat/pinky-edge-agent` · **아직 아무 코드도 바뀌지 않았다**

받는 사람: step 10 을 구현할 사람
설계 배경: [2026-08-20-arm-pick-step-implementation.md](2026-08-20-arm-pick-step-implementation.md)
(왜 그렇게 정했는지가 거기 있다. 이 문서는 **무엇을 어떤 순서로 하는지**만 적는다)

---

## 1. 한 장 요약

주문이 들어오면 원장은 이미 **어떤 lot 을 어느 slot 에서 집어야 하는지** 안다.
그런데 로봇팔에게는 그 정보가 **뭉개져서** 전달되고, 팔은 상태 문자열 세 개만 바꾼 뒤
`succeeded` 를 돌려준다. 지금의 step 10 은 "명령이 왕복했다" 는 뜻이지
"집었다" 는 뜻이 아니다.

할 일은 일곱 덩어리(W1~W7)이고, **W1~W4 는 팔이 한 번도 안 움직이는데
step 10 의 의미를 거의 다 만든다.**

| # | 무엇 | 팔 | 하드웨어 필요 |
|---|---|---|---|
| W1 | 팔에게 품목을 제대로 알려 준다 | 안 움직임 | 아니오 |
| W2 | 온도대로 팔을 고른다 | 안 움직임 | 아니오 |
| W3 | 집었다는 증거를 원장에 남긴다 | 안 움직임 | 아니오 |
| W4 | ACT 정책을 **고르고 불러온다**(추론만) | 안 움직임 | GPU |
| W5 | pick 상태 기계 + 파지 확인 | 안 움직임 | 아니오 |
| W6 | 카메라 둘을 붙인다 | 안 움직임 | 카메라 2 대 |
| W7 | 실제 파지 | **움직임** | 팔 전체 |

**W4 를 W1 보다 먼저 하지 않는다.** 정책에게 무엇을 집으라고 말할 수 없는 상태에서
정책을 붙이면 그 위의 모든 것이 헛돈다.

---

## 2. 어느 폴더, 어느 파일을 보는가

### 2.1 폴더 지도 — 이 저장소는 무엇으로 나뉘어 있나

| 폴더 | 무엇 | 이번 작업 |
|---|---|---|
| **`control_tower/`** | 관제 로직. 계획·배정·실행기·Gateway 클라이언트. **DB 를 직접 안 만진다** | **주 작업지** |
| **`trihouse_omx_adapter/`** | 로봇팔 어댑터. ACT 정책·프로토콜 시뮬레이터·ROS 노드 | **주 작업지** |
| **`fms_gateway/`** | 원장 API(FastAPI + MySQL). **상태의 유일한 심판** | API·게이트만 |
| `db/` | 스키마와 seed. `schema_mysql.sql`, `seed_dev.sql` | seed·metadata |
| `config/` | 런타임 설정 정본. `act.simulation.yaml`, `cameras.yaml`, `mediamtx.yml` | 설정 추가 |
| `vision_system/` | 인식·녹화·마커 정책 | **가져다 쓴다** |
| `vision_edge/` | 로봇 위 QR/ArUco 디코더 | **가져다 쓴다** |
| `trihouse_pinky/` | 주행 로봇 ROS 패키지(안전 gate, fleet) | 안 건드린다 |
| `trihouse_rmf_bridge/` | Open-RMF 연동과 시뮬 launch | 안 건드린다 |
| `scripts/` | `p0_reset.sh`, `p0_up.sh` 등 운용 스크립트 | 안 건드린다 |
| ~~`control_system/`~~ | **git submodule**(외부 저장소). 옛 스택 | **손대지 않는다** |
| ~~`pinky_pro/`~~ | **git submodule**(벤더). 로봇 드라이버 | **손대지 않는다** |

`control_system/` 안에도 `arm_node.py`·`arms.yaml` 이 있어서 검색하면 걸린다.
**옛 스택이고 submodule 이다. 참고만 하고 고치지 않는다.**

### 2.2 읽는 순서 — 이 여섯 개를 이 순서로 읽으면 전체가 보인다

코드를 쓰기 전에 **주문 하나가 팔까지 가는 길**을 한 번 따라가는 것이 가장 빠르다.

| # | 파일 | 무엇을 확인 |
|---|---|---|
| 1 | [outbound_planner.py](../../control_tower/task_manager/outbound_planner.py) | FEFO 로 lot·slot·온도대를 확정하는 곳. **여기서 "물품 위치 파악" 이 끝난다** |
| 2 | [outbound_sequence.py:76-145](../../control_tower/task_manager/outbound_sequence.py#L76-L145) | 그 결과로 step 10 `arm/pick` 의 `input` 을 만드는 곳 |
| 3 | [job_runner.py:107-285](../../control_tower/task_manager/job_runner.py#L107-L285) | 팔을 고르고(`_first_free`) step 을 하나씩 내보내는 곳 |
| 4 | [executor_worker.py:143-201](../../control_tower/task_manager/executor_worker.py#L143-L201) | 팔 명령을 실제로 만들어 보내는 곳. **`_run_arm` 이 이번 작업의 한복판** |
| 5 | [protocol_simulator.py](../../trihouse_omx_adapter/trihouse_omx_adapter/protocol_simulator.py) | 팔이 명령을 받아 상태를 바꾸는 곳(지금은 문자열뿐) |
| 6 | [act_policy.py](../../trihouse_omx_adapter/trihouse_omx_adapter/act_policy.py) | ACT 정책을 불러오는 곳. **추론이 없다는 것을 여기서 확인** |

곁들여 읽을 것 둘 — [omx_workflow.py](../../control_tower/task_manager/omx_workflow.py)
(재시도·복구 정책. **이미 다 짜여 있고 아무도 안 쓴다**)와
[robot_arm_safety.md](../architecture/robot_arm_safety.md)(금지 연결 네 가지).

### 2.3 작업별로 손댈 파일

**새로 만드는 파일은 다섯 개뿐이다.** 나머지는 전부 기존 파일을 넓히는 일이다.

| 작업 | 새로 만든다 | 고친다 |
|---|---|---|
| **W1** 품목 전달 | — | [executor_worker.py:325-343](../../control_tower/task_manager/executor_worker.py#L325-L343)<br>[outbound_sequence.py:104](../../control_tower/task_manager/outbound_sequence.py#L104)<br>[omx_protocol.py:96](../../control_tower/gateway/omx_protocol.py#L96)<br>[protocol_simulator.py:19-37](../../trihouse_omx_adapter/trihouse_omx_adapter/protocol_simulator.py#L19-L37)<br>[db/seeds/seed_dev.sql:56](../../db/seeds/seed_dev.sql#L56) (slot 에 `aruco_marker_id`) |
| **W2** 팔 선택 | `control_tower/task_manager/`<br>**`arm_selection.py`** | [job_runner.py:264](../../control_tower/task_manager/job_runner.py#L264)<br>[fms_client.py:96](../../control_tower/gateway/fms_client.py#L96), [:146](../../control_tower/gateway/fms_client.py#L146)<br>[repositories.py:1280](../../fms_gateway/app/repositories.py#L1280)<br>[db/seeds/seed_dev.sql:129](../../db/seeds/seed_dev.sql#L129) (`capabilities`) |
| **W3** 증거·게이트 | — | [main.py:1070](../../fms_gateway/app/main.py#L1070) 을 본뜬 새 라우트<br>[repositories.py:5812](../../fms_gateway/app/repositories.py#L5812), [:5868](../../fms_gateway/app/repositories.py#L5868)<br>[models.py](../../fms_gateway/app/models.py) (요청 스키마)<br>[fms_client.py](../../control_tower/gateway/fms_client.py) (클라이언트 메서드) |
| **W4** 정책 적재 | `trihouse_omx_adapter/trihouse_omx_adapter/`<br>**`act_runner.py`**<br>`config/`**`act.hardware.yaml`** | [act_policy.py:88](../../trihouse_omx_adapter/trihouse_omx_adapter/act_policy.py#L88) (`select_policy`)<br>[executor_worker_node.py:77](../../control_tower/task_manager/executor_worker_node.py#L77)<br>[config/act.simulation.yaml](../../config/act.simulation.yaml) |
| **W5** 상태 기계 | `trihouse_omx_adapter/trihouse_omx_adapter/`<br>**`pick_sequence.py`**<br>**`arm_backend.py`** | [executor_worker.py:181](../../control_tower/task_manager/executor_worker.py#L181)<br>[setup.py](../../trihouse_omx_adapter/setup.py) (진입점) |
| **W6** 카메라 | `trihouse_omx_adapter/trihouse_omx_adapter/`<br>**`perception.py`** | [config/cameras.yaml](../../config/cameras.yaml)<br>[camera_registry.py:31](../../control_tower/gateway/camera_registry.py#L31)<br>[config/mediamtx.yml:156](../../config/mediamtx.yml#L156) |
| **W7** 실제 파지 | — | [hardware_adapter_node.py](../../trihouse_omx_adapter/trihouse_omx_adapter/hardware_adapter_node.py) — skeleton 을 실물로 |

### 2.4 테스트를 넣을 곳

| 대상 | 어디 |
|---|---|
| `arm_selection`, `executor_worker`, `job_runner` | `control_tower/tests/` — [test_executor_worker.py](../../control_tower/tests/test_executor_worker.py) 옆 |
| `pick_sequence`, `act_runner`, 프로토콜 계약 | `trihouse_omx_adapter/tests/` — [test_protocol_simulator.py](../../trihouse_omx_adapter/tests/test_protocol_simulator.py) 옆 |
| `pick-attempts` API·게이트 | `fms_gateway/tests/unit/` — [test_load_attempt_api.py](../../fms_gateway/tests/unit/test_load_attempt_api.py) 를 본뜬다 |

**`test_load_attempt_api.py` 와 [executor_worker.py 의 `_confirm_load`](../../control_tower/task_manager/executor_worker.py#L227-L300)
가 W3 의 교본이다.** `load` 는 이미 같은 길을 걸었으므로 베껴 쓰면 된다.

---

## 3. 지금 코드가 실제로 하는 일

```text
POST /api/v1/orders
 └ OutboundPlanner.plan()               FEFO 로 lot·slot 확정        ✅ 됨
   └ planned_outbound_steps()           step 10 arm/pick 생성        ✅ 됨
     input = {temperature_zone, product_codes, items:[{lot_id, slot_location_id, …}]}
     └ 배정                              모든 arm step 에 omx_id      ⚠️ 사전순 first-fit
       └ JobRunner.current_step()        step_no 순 하나씩
         └ dispatch_step()               channel=omx
           └ ExecutorWorker._run_arm()   prepare 1 회                ❌ 품목 루프 없음
             └ OmxProtocolSimulator      PREPARING→PICKING→OMX_READY ❌ 모터 없음
               └ record_executor_outcome() succeeded                 ❌ 증거 없음
```

**핵심**: 물품 위치 파악은 끝나 있다. 없는 것은 그 뒤 전부다.

---

## 4. 반드시 먼저 읽고 갈 사실 넷

### 3.1 `expected_items` 는 팔에게 전달된다. 그런데 두 가지가 어긋나 있다

전달은 된다 — 명령의 **필수 필드**이고 검증도 양쪽에서 한다
([executor_worker.py:196](../../control_tower/task_manager/executor_worker.py#L196) →
[omx_protocol.py:96](../../control_tower/gateway/omx_protocol.py#L96) →
[protocol_simulator.py:19](../../trihouse_omx_adapter/trihouse_omx_adapter/protocol_simulator.py#L19)).

**(가) 내용이 뭉개진다.** 계획은 `items` 를 dict 리스트로 싣는데 `_expected_items` 가
`str(item)` 한다.

```text
expected_items = ("{'line_no': 1, 'product_code': 'SKU-PORKBELLY', 'lot_id': 8, …}",)
```

같은 `input` 에 `product_codes: ["SKU-PORKBELLY"]` 가 **버젓이 있는데 쓰지 않는다.**

**(나) 그 값이 모델 선택에 닿지 않는다.** ACT 정책은 프로세스가 뜰 때 설정 파일에서
한 번 적재되고([simulator_node.py:38](../../trihouse_omx_adapter/trihouse_omx_adapter/simulator_node.py#L38)),
`run_episode()` 는 `command_uuid` 와 `assignment_revision` 만 받는다.
**`expected_items` → 모델 선택 경로는 코드에 존재하지 않는다.** W1 과 W4 가 그 선을
새로 잇는 일이다.

### 3.2 팔 선택 코드는 `assignment.py` 가 아니다

`ControlTowerAssigner`([assignment.py:52](../../control_tower/task_manager/assignment.py#L52))
는 **런타임 호출자가 없다**(테스트뿐). 실제 경로는

```text
JobRunner._select_assignment()   job_runner.py:257
 └ _first_free(devices, "arm")   job_runner.py:341   ← 사전순 첫 번째
```

`_first_free` 는 `device_type`·`assignable` 만 본다. **온도대는 함수에 들어오지도 않는다.**

### 3.3 10 과 20 은 병렬이 아니다

계획이 `branch`/`dependencies` 를 적지만 **읽는 곳이 없다.** 러너는 `step_no` 순으로
하나씩만 보고([job_runner.py:107](../../control_tower/task_manager/job_runner.py#L107)),
Gateway 는 앞 번호가 전부 `succeeded` 가 아니면 dispatch 를 거절한다
([repositories.py:5433](../../fms_gateway/app/repositories.py#L5433)).

**파지가 30 초 걸리면 로봇은 30 초 동안 출발하지 않는다.** 병렬화는 이번 범위 밖이지만
**파지 시간을 측정해 남기는 것(W3)은 범위 안이다.** 그 표본이 병렬화 판단 근거가 된다.

### 3.4 ACT checkpoint 는 실재하고, 계약이 확정돼 있다

`https://huggingface.co/2usang` 에 품목별 ACT 정책 **10 개**가 있고
**열 개의 입출력 계약이 완전히 동일하다.** 코드 경로는 하나, checkpoint 만 갈린다.

| 항목 | 값 |
|---|---|
| `type` | `act` |
| `observation.state` | `[6]` = `shoulder_pan`, `shoulder_lift`, `elbow_flex`, `wrist_flex`, `wrist_roll`, `gripper` (`.pos`) |
| `observation.images.front` | `[3, 480, 640]` |
| `observation.images.wrist` | `[3, 480, 640]` |
| `action` | `[6]` (state 와 같은 순서) |
| `chunk_size` / `n_action_steps` | 100 / 100 |
| `n_obs_steps` | 1 |
| `device` | `cuda` |
| 학습 데이터 | `robot_type: omx_follower`, 30 fps, 40 episode / 41,274 frame |

여기서 따라오는 것 넷.

1. **카메라가 둘이다** — `front` 와 `wrist`. 손목만으로는 정책이 돌지 않는다
2. **6 자유도**(5 관절 + 그리퍼). `joint_states` 의 **이름·순서·단위**가 위와 같은지
   실물에서 확인해야 한다. **어긋나면 오류 없이 엉뚱한 관절이 움직인다**
3. **GPU 가 필요하다.** 팔 PC 에 없으면 5080 원격 추론이 전제가 된다
4. **한 번에 100 step 을 낸다.** 매 프레임 추론이 아니라 **chunk 를 받아 소비하는
   구조**여야 한다. 30 fps 기준 100 step ≈ 3.3 초

---

## 5. SKU → 모델 매핑 — 문자열 파생은 쓰지 않는다

`SKU-PORKBELLY` → `porkbelly` → `act_trihouse-porkbelly` 는 **재고 SKU 11 개 중 8 개만 맞는다.**

| SKU | 파생 | 실제 |
|---|---|---|
| `-STRAWBERRY` `-ORANGE` `-SANDWICH` `-MILK` `-YOGURT` `-COFFEE` `-PORKBELLY` `-DUMPLING` | 그대로 | `2usang/act_trihouse-<이름>` ✅ |
| `SKU-ICECONE` | `icecone` | `act_trihouse-**icecorn**` — 철자가 다르다 ❌ |
| `SKU-ICEBAR` | `icebar` | 후보 둘: `act_trihouse-icebar`, `omx_trihouse-icebar` ❌ |
| `SKU-MANDARIN` | `mandarin` | **없다** (재고에는 2 개 있다) ❌ |

파생은 **세 가지 방식으로 조용히 틀리고**(없는 이름·다른 철자·같은 이름 둘),
**품목이 늘 때마다 다시 틀린다.** 정본 매핑을 설정에 적는다.

```yaml
# config/act.hardware.yaml
mode: hardware
policies:
  - product_code: SKU-PORKBELLY
    repo_id: 2usang/act_trihouse-porkbelly
    revision: 50939ab8953b2574c586898366308064a8de56f1
    profile: omx_follower
  - product_code: SKU-DUMPLING
    repo_id: 2usang/act_trihouse-dumpling
    revision: 49ef50500433…
  # …
```

규칙 셋.

- **`revision` 은 커밋 SHA 로 못박는다.** `main` 을 가리키면 어제 돌던 것과 오늘
  돌던 것이 달라지고 증거의 `model_version` 이 무의미해진다
- **매핑에 없는 SKU 는 거절한다.** 기본 정책으로 조용히 떨어지지 않는다
- **거절은 가능한 한 앞에서** — 주문 접수나 배정 단계. 팔 앞에서 알게 되면 로봇은
  이미 도크에 가 있다

**결정 필요**: `SKU-MANDARIN` 처럼 정책 없는 SKU 를 어떻게 할 것인가
(주문 거절 / 수동 처리 / 정책 추가). 코드를 쓰기 전에 답이 필요하다.

---

## 6. 작업 단위

각 항목은 **앞 항목이 통과해야** 시작한다. 매 항목 끝에 시뮬 한 사이클이 그대로 돌아야 한다.

### W1 — 팔에게 품목을 제대로 알려 준다

| | |
|---|---|
| 고칠 파일 | [executor_worker.py:325-343](../../control_tower/task_manager/executor_worker.py#L325-L343) · [outbound_sequence.py:104](../../control_tower/task_manager/outbound_sequence.py#L104) · [omx_protocol.py:96](../../control_tower/gateway/omx_protocol.py#L96) · [protocol_simulator.py:19](../../trihouse_omx_adapter/trihouse_omx_adapter/protocol_simulator.py#L19) |
| 하는 일 | `expected_items` 를 `product_codes` 에서 뽑는다. `kind: "pick"` 과 `targets[]` 를 프로토콜에 연다. `job_item_id`·`unit_weight_kg` 를 계획이 `input.items` 에 함께 싣는다 |
| 완료 기준 | `expected_items == ("SKU-PORKBELLY",)`. `targets[0].job_item_id` 가 실제 ID |
| 테스트 | **계획이 만드는 dict 리스트 입력에 대한 회귀 테스트를 먼저 쓴다** — 지금 그 케이스가 없어서 결함이 살아남았다 |

`command_uuid` 에 `job_item_id` 를 넣는다. 시뮬레이터가 `command_uuid` 로 응답을
캐시하므로([protocol_simulator.py:79](../../trihouse_omx_adapter/trihouse_omx_adapter/protocol_simulator.py#L79))
품목마다 달라야 둘째 품목이 첫째의 응답을 되받지 않는다.

**`marker_id` 는 원장에 값이 없다.** 지금은 언제나 `0` 을 지어낸다.
`locations.metadata` 에 `aruco_marker_id` 를 넣고(slot 행에 `shelf_level` 등이 이미
JSON 으로 있다), **값 없는 slot 은 후보에서 뺀다.** 0 을 지어내면 엉뚱한 선반에서 집는다.

### W2 — 온도대로 팔을 고른다

| | |
|---|---|
| 고칠 파일 | [job_runner.py:264](../../control_tower/task_manager/job_runner.py#L264) · [fms_client.py:96](../../control_tower/gateway/fms_client.py#L96), [:146](../../control_tower/gateway/fms_client.py#L146) · [repositories.py:1280](../../fms_gateway/app/repositories.py#L1280) · [seed_dev.sql:129](../../db/seeds/seed_dev.sql#L129) |
| 새 파일 | `control_tower/task_manager/arm_selection.py` |

온도대는 **이미 두 곳에 있다.** 새로 조회하지 않는다.

- job 상세의 `steps[].input.temperature_zone` — HTTP 응답에 이미 실려 온다
- `GET /api/v1/inventory/lots` 의 lot 별 `temperature_zone`

막는 것은 **투영 누락 둘**뿐이다(데이터는 DB 에 있다).

| 누락 | 고침 |
|---|---|
| `JobStepDetail` 에 `input` 필드가 없어 `from_dict` 가 버린다 | 필드 한 줄 추가 |
| `list_devices` SELECT 에 `capabilities` 가 없다 | SELECT + `DeviceSummary` 필드 |

`devices.capabilities`(이미 JSON 열)에 적는다.

```jsonc
{"pick": true, "place": true,
 "workcell_location_code": "OMX-WS-01",
 "served_temperature_zones": ["ambient", "chilled", "frozen"],
 "served_dock_location_codes": ["OUT-DOCK-01"],
 "reach_radius_m": 0.28, "payload_limit_kg": 0.5}
```

```python
def choose_arm(candidates, *, temperature_zones, dock_location_codes,
               reserved, max_item_weight_kg=None) -> str:
    """조건을 만족하는 팔 중 사전순 첫 번째. 없으면 ArmUnavailable."""
```

규칙 넷: `assignable` · 온도대를 **전부** 덮음 · 도크를 덮음 · payload 한계 이상.
**`capabilities` 가 비어 있는 팔은 후보에서 뺀다**(fail-closed). `ArmUnavailable` 이면
`_select_assignment` 는 지금처럼 `None` — 다음 주기에 다시 본다. **주문을 실패시키지 않는다.**

한 job 에 팔은 하나만 배정되므로(`AssignmentRevision.omx_id`), 온도대가 둘인 주문은
**한 팔이 둘 다 덮을 때만** 배정된다. **틀린 팔에 보내는 것보다 기다리는 것이 낫다.**

`mobile` 쪽 `_first_free` 는 **건드리지 않는다.**

### W3 — 집었다는 증거를 원장에 남긴다

| | |
|---|---|
| 고칠 파일 | [main.py:1070](../../fms_gateway/app/main.py#L1070) 을 본뜬 새 라우트 · [repositories.py:5812](../../fms_gateway/app/repositories.py#L5812), [:5868](../../fms_gateway/app/repositories.py#L5868) |

원장은 **이미 받을 준비가 되어 있다.** `job_step_attempts` 에 `criteria`,
`before/after_observation`, `evidence_refs`, `policy_source`(`rl` 허용),
`policy_name/version`, `model_name/version` 칸이 전부 있다
([schema_mysql.sql:496](../../db/migrations/001_physical_v1_baseline.sql#L496)). 비어 있을 뿐이다.

`load` 가 이미 같은 길을 걸었다. 그대로 본뜬다.

1. `POST /internal/v1/job-steps/{id}/pick-attempts` — `result` 는
   `PICK_CONFIRMED` / `PICK_FAILED` / `MANUAL_FULFILLMENT_REQUIRED`
2. `record_executor_outcome` 에 게이트 추가 — `action_type == 'pick'` 이고 성공이면
   `targets` 품목이 전부 `PICK_CONFIRMED` 여야 한다. 아니면 `PICK_ITEMS_NOT_CONFIRMED`
3. `policy_source='rule'` 하드코딩을 요청값으로 — pick 은 `rl`
4. `model_name`/`model_version` 에 **실제 repo_id 와 SHA** 를 적는다

**계보를 비워 두지 않는 것이 이 항목의 요점이다.** fake 정책이면 `fake-act/p0-v1` 로
정직하게 남아야 한다. 그래야 "이 완주는 진짜 팔이 집은 것인가" 를 원장만 보고 답할 수 있다.

실패 경로는 이미 있다 — [PickRecovery](../../control_tower/task_manager/omx_workflow.py#L155)
와 `POST /internal/v1/job-steps/{id}/pick-recovery`. **새로 만들지 말고 부른다.**

### W4 — 정책을 고르고 불러온다 (추론만, 모터로 안 보냄)

| | |
|---|---|
| 새 파일 | `trihouse_omx_adapter/trihouse_omx_adapter/act_runner.py` · `config/act.hardware.yaml` |
| 고칠 파일 | [act_policy.py:88](../../trihouse_omx_adapter/trihouse_omx_adapter/act_policy.py#L88) (`select_policy` 추가) · [executor_worker_node.py:77](../../control_tower/task_manager/executor_worker_node.py#L77) |

```python
@dataclass(frozen=True)
class ActObservation:
    front_image: "np.ndarray"      # HxWx3 uint8, 480x640
    wrist_image: "np.ndarray"
    joint_positions: tuple[float, ...]   # 6, §4.4 의 이름 순서
    gripper_position: float


@dataclass(frozen=True)
class ActAction:
    joint_positions: tuple[float, ...]
    gripper_position: float
    model_lineage: str             # W3 의 증거에 그대로 들어간다


class ActRunner:
    def __init__(self, policy: ActPolicy) -> None: ...
    def reset(self, *, command_uuid: str, assignment_revision: int) -> None:
        """episode 경계. 재시도할 때 반드시 부른다
        (PickRecovery 가 reset_act_episode=True 를 내는 그 자리)."""
    def step(self, observation: ActObservation) -> ActAction: ...
```

- `policy.is_fake` 면 `step()` 은 **현재 joint 를 그대로 돌려준다.** 움직이지 않는
  action 이지 예외가 아니다 — 계약 경로는 그대로 돌아야 한다
- **chunk 를 내부에서 소비한다.** 100 step 을 받아 두고 소진되면 다시 추론한다
- 5080 원격 추론으로 옮겨도 **이 서명은 안 바뀐다**. `step()` 내부만 HTTP 가 된다

**게이트를 양방향으로 막는다.** 지금은 시뮬만 보호한다.

| `--environment` | 허용 | 거절 |
|---|---|---|
| `simulation` | fake 정책 | real motion 정책 → `SystemExit` (지금 그대로) |
| `hardware` | real 정책 | **fake 정책 → `SystemExit`** (새로) |

**실기에서 fake 가 조용히 도는 것도 사고다** — 팔이 가만히 있는데 step 은
`succeeded` 로 닫히고 아무도 눈치채지 못한다. 지금 정확히 그 상태다.

### W5 — pick 상태 기계와 파지 확인

| | |
|---|---|
| 새 파일 | `trihouse_omx_adapter/trihouse_omx_adapter/pick_sequence.py` · `arm_backend.py` |

```text
QR_REQUIRED → MARKER_ALIGNING → OBJECT_REDETECT → ACT_RUNNING
            → GRASP_VERIFYING → HANDOVER_READY
                      └→ (실패) RETRY_OFFSET → QR_REQUIRED
                      └→ (소진) ITEM_HELD        ← fail-closed 종점
```

`advance(PickObservation) -> PickDecision` 하나. **관측을 만들지 않고 판단만 한다.**
ROS 도 하드웨어도 모른다.

**있는 것을 쓴다. 새로 만들지 않는다.**

- QR/ArUco 판정 → [marker_worker.MarkerPolicy](../../vision_system/marker_worker/policy.py)
- 재시도 offset·소진 → [OmxWorkflow](../../control_tower/task_manager/omx_workflow.py#L59)
  (**지금 테스트만 import 하는 그 모듈이 처음 런타임에 들어간다**)
- 운영자 선택 → [PickRecovery](../../control_tower/task_manager/omx_workflow.py#L155)

**파지 확인이 핵심이다.** "episode 가 끝났다" 는 성공이 아니다.

```python
def _grasp_confirmed(o) -> bool:
    held = (o.gripper_position is not None
            and o.gripper_closed_position is not None
            and o.gripper_position > o.gripper_closed_position + GRIPPER_OBJECT_MARGIN_M)
    tracked = o.marker_moved_with_arm is True
    return held or tracked          # 둘 다 None 이면 False
```

**`None` 을 "아마 됐을 것" 으로 읽지 않는다.**

`arm_backend.py` 는 문 하나(`observe`/`apply`/`open_gripper`/`retreat`)에 구현 셋 —
`contract`(상태만), `gazebo`(joint_trajectory 발행), `hardware`(MoveIt).
**ACT action 을 모터에 직접 쓰지 않는다.** MoveIt / `joint_trajectory_controller` 를
거쳐야 `open_manipulator_collision` 의 충돌 검사가 산다.

실행기 쪽([executor_worker.py:181](../../control_tower/task_manager/executor_worker.py#L181))은
`prepare` 한 번을 **품목 루프**로 바꾼다. 품목마다 `pick()` → 증거 기록 → 파지
미확인이면 step 을 `failed` 로 닫는다. **실행기는 팔의 내부를 모른 채 `pick()` 하나만
안다** — 지금 `simulator.execute()` 하나만 아는 것과 같은 깊이다.

### W6 — 카메라 둘

| | |
|---|---|
| 새 파일 | `trihouse_omx_adapter/trihouse_omx_adapter/perception.py` |
| 고칠 파일 | [config/cameras.yaml](../../config/cameras.yaml) · [camera_registry.py:31](../../control_tower/gateway/camera_registry.py#L31) · [config/mediamtx.yml:156](../../config/mediamtx.yml#L156) |

**손목은 자리가 이미 잡혀 있다** — `CAM-OMX-01-WRIST`(`role: omx_wrist`,
`attached_to: OMX_01`), MediaMTX 경로 `omx/CAM-OMX-01-WRIST` 까지. 없는 것은 실제
카메라와 그 경로로 밀어 주는 프로세스뿐이다.

**`front` 는 명부에 없다.** 역할이 `pinky_travel`/`omx_wrist`/`warehouse_fixed` 셋뿐이고
OMX 작업대를 정면에서 보는 카메라가 없다. **결정 필요**: `CAM-FIXED-01` 을 쓸 것인가,
`omx_front` 역할을 새로 열 것인가. 후자면 `ROLE_STREAM_PREFIX` 와 MediaMTX 경로도 는다.

**경로를 둘로 나눈다. 이것이 이 항목의 유일한 설계 결정이다.**

| 용도 | 경로 | 왜 |
|---|---|---|
| ACT 추론 입력 | 팔 PC 에서 `/dev/video*` 를 **로컬로 직접** | RTSP 왕복은 인코딩·버퍼로 100 ms 단위 지연. 제어 루프에 넣으면 파지가 흔들린다 |
| 증거·감시 | 같은 프레임의 사본을 MediaMTX 로 publish | 녹화·운영 화면·`evidence_refs` 는 지연을 신경 쓰지 않는다 |

**카메라를 한 번 열고 프레임을 두 갈래로 낸다.** 두 프로세스가 같은 `/dev/video0` 을
두고 다투게 두지 않는다.

QR/ArUco 디코딩은 [model/worker/marker/edge_perception.py](../../model/worker/marker/edge_perception.py) 를 쓴다.
`DICT_5X5_50` 의 0·1·2 이고 **새 ID 범위를 만들지 않는다.**

### W7 — 실제 파지

[2026-08-18 로봇팔 설계](2026-08-18-omx-arm-hardware-design.md)의 A1~A9 과 승인 게이트
O1~O5 를 그대로 따른다. **이 인계서는 거기까지 가는 배선을 다룬다.**

W7 이전에 **fail-closed 를 먼저 시험한다** — 빈 그리퍼로 ACT 를 돌려
`HANDOVER_READY` 로 가지 **않는** 것을 본다. 성공 경로보다 이 실패 경로를 먼저 확인한다.

---

## 7. 지금 상태를 눈으로 확인하는 명령

전부 돌려 본 것이다. 시뮬을 띄우지 않아도 되고 아무것도 바꾸지 않는다.
**전체 목록은 [설계 문서 §10](2026-08-20-arm-pick-step-implementation.md#10-지금-눈으로-확인하는-절차--명령-하나씩)**
에 10 개 있다. 여기에는 인계에 꼭 필요한 셋만 옮긴다.

```bash
cd /home/newuser/Trihouse
```

**① 팔에게 무엇이 나가는가** (W1 의 출발점)

```bash
python3 -c "
from control_tower.gateway.fms_client import ExecutorDispatch
from control_tower.task_manager.executor_worker import _expected_items, _marker_id
inp = {'temperature_zone':'frozen','product_codes':['SKU-PORKBELLY'],
       'items':[{'line_no':1,'product_code':'SKU-PORKBELLY','lot_id':8,'slot_location_id':31,'reserved_quantity':1}]}
d = ExecutorDispatch(message_id='m', job_id=2, job_step_id=41, channel='omx',
    message_type='execute_action', action_type='pick', executor_type='arm',
    payload={'input': inp}, assigned_device_id='OMX_01', assignment_revision=1)
print('expected_items =', _expected_items(d))
print('marker_id      =', _marker_id(d))"
```

**② 팔은 무엇을 보고 골라지는가** (W2 의 출발점)

```bash
curl -s http://127.0.0.1:8080/api/v1/devices | python3 -c "
import sys, json
from control_tower.gateway.fms_client import DeviceSummary
from control_tower.task_manager.job_runner import _first_free
rows = json.load(sys.stdin); devs = tuple(DeviceSummary.from_dict(r) for r in rows)
print('고른 팔:', _first_free(devs, 'arm', set()))
print('온도대·capabilities 필드:', [k for k in rows[0] if 'zone' in k or 'capab' in k] or '없음')"
```

**③ 모델 계약 확인** (W4 의 출발점)

```bash
python3 -c "
import json, urllib.request
def g(u): return json.load(urllib.request.urlopen(u, timeout=25))
info = g('https://huggingface.co/api/models/2usang/act_trihouse-porkbelly')
cfg  = json.load(urllib.request.urlopen('https://huggingface.co/2usang/act_trihouse-porkbelly/resolve/main/config.json', timeout=25))
print('sha :', info['sha'])
print('in  :', {k: v['shape'] for k, v in cfg['input_features'].items()})
print('out :', {k: v['shape'] for k, v in cfg['output_features'].items()})
print('chunk:', cfg['chunk_size'], '| device:', cfg['device'])"
```

**테스트 주의**: `pytest trihouse_omx_adapter/tests` 처럼 **디렉터리로 주면 ROS 의
`launch_testing` 플러그인이 죽는다.** 파일을 직접 지정한다.

```bash
python3 -m pytest trihouse_omx_adapter/tests/test_act_policy.py trihouse_omx_adapter/tests/test_protocol_simulator.py -q
```
```bash
python3 -m pytest control_tower/tests/test_executor_worker.py control_tower/tests/test_assignment.py -q
```

---

## 8. 지켜야 할 규칙

- **관례대로 고치기 전에 실패하는 테스트를 먼저 쓴다.** 하드웨어 없이 도는 것을 최대한 늘린다
- **fail-closed.** 관측이 없으면 성공으로 읽지 않는다. 설정이 비어 있으면 기본값으로
  떨어지지 않는다. 지어낸 값(`marker_id = 0`)을 원장에 넣지 않는다
- **판정은 로그의 성공 문구가 아니라 측정값으로 한다**
- **있는 것을 쓴다.** `OmxWorkflow`, `PickRecovery`, `MarkerPolicy`, `RecordingCatalog`,
  `vision_edge` 디코더는 이미 있고 테스트도 있다. 새로 만들면 두 벌이 된다
- **job 하나가 끝나기 전에 새 주문을 넣지 않는다**([런북 절대 규칙](../runbooks/p0-simulation-quick-run.md#절대-규칙))
- 막히면 손으로 풀지 말고 `scripts/p0_reset.sh` 부터

---

## 9. 시작 전에 답이 필요한 것

| # | 질문 | 막는 것 |
|---|---|---|
| Q1 | 정책 없는 SKU(`SKU-MANDARIN`)를 어떻게 하는가 — 주문 거절 / 수동 처리 / 정책 추가 | W4 |
| Q2 | `SKU-ICEBAR` 는 `act_trihouse-icebar` 인가 `omx_trihouse-icebar` 인가 | W4 |
| Q3 | `front` 카메라를 `CAM-FIXED-01` 로 쓰는가, `omx_front` 역할을 새로 여는가 | W6 |
| Q4 | 추론을 팔 PC 에서 하는가 5080 에서 하는가 (팔 PC 에 GPU 가 있는가) | W4 |
| Q5 | `joint_states` 의 이름·순서·단위가 `shoulder_pan…gripper` 와 같은가 | W7 · **실물 확인** |
| Q6 | `gazebo` backend 를 만드는가 — 안 만들면 fail-closed 를 실물에서 처음 시험하게 된다 | W5 |

---

## 10. 관련 문서

| 문서 | 무엇 |
|---|---|
| [2026-08-20-arm-pick-step-implementation.md](2026-08-20-arm-pick-step-implementation.md) | 이 인계서의 근거. 왜 그렇게 정했는지와 확인 명령 10 개 |
| [2026-08-18-omx-arm-hardware-design.md](2026-08-18-omx-arm-hardware-design.md) | 실물 기동 A1~A9, 승인 게이트 O1~O5, 벤더 저장소 |
| [robot_arm_safety.md](../architecture/robot_arm_safety.md) | 금지 연결 네 가지. **이 설계의 제약** |
| [2026-08-20-hardware-readiness-gaps.md](2026-08-20-hardware-readiness-gaps.md#h6-로봇팔--이번엔-뺀다-결정됨) | H6 — 이번 실물 출고 테스트에서는 팔을 뺀다는 결정 |
| [p0-simulation-quick-run.md](../runbooks/p0-simulation-quick-run.md) | 시뮬 한 사이클 실행 절차 |
