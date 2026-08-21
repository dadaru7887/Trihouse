# step 10 `arm/pick` 구현 설계 — 팔을 고르고 ACT 로 집기까지 (2026-08-20)

작성: 2026-08-20 · 브랜치 `feat/pinky-edge-agent` · **구현 전 설계. 코드는 아직 고치지 않았다.**

> 구현자에게 넘길 작업 단위와 순서는 [인계서](2026-08-20-arm-pick-handoff.md)에 있다.
> 이 문서는 **왜 그렇게 정했는지**다.

대상: [p0-simulation-quick-run.md](../runbooks/p0-simulation-quick-run.md) 한 사이클의 첫 단계

```text
10 arm/pick          로봇팔이 물건을 집는다     ← 이 문서
20 mobile/navigate   로봇이 적재 지점으로 간다
30 fms/load          적재
```

## 0. 이 문서가 정하는 것

주문이 들어오면 [OutboundPlanner](../../control_tower/task_manager/outbound_planner.py) 가
FEFO 로 lot 을 고르고 **품목마다 `slot_location_id` 를 확정해** step 열을 만든다.
거기까지는 이미 돈다. 이 문서는 그 뒤 네 가지를 정한다.

| # | 무엇 | 지금 |
|---|---|---|
| ①(팔 선택) | 어느 OMX-AI 가 이 주문을 맡는가 | 알파벳 first-fit. 온도대·도크와 무관 |
| ②(명령 payload) | 그 팔에게 **무엇을** 집으라고 말하는가 | 품목이 `str(dict)` 로 뭉개져 나간다 |
| ③(ACT 호출) | **어떻게** 집는가 | 없음. 상태 문자열 세 개만 바뀐다 |
| ④(증거·게이트) | 집었다는 것을 무엇으로 아는가 | 없음. 명령을 보낸 것만으로 `succeeded` |

**정하지 않는 것**: 실기 팔의 기동 순서(A1~A9)와 벤더 저장소 도입은
[로봇팔 통신 패키지와 실제 파지 설계](2026-08-18-omx-arm-hardware-design.md)가 이미
정했다. 이 문서는 그 문서의 **A8(Gateway 계약에 물린다)을 양쪽에서 마중 나가는 배선**
이고, 시뮬에서 먼저 완성한다. VLM 은 넣지 않는다.

**전제**: [실물 준비 공백 H6](2026-08-20-hardware-readiness-gaps.md#h6-로봇팔--이번엔-뺀다-결정됨)
에서 **이번 실물 출고 테스트는 팔을 뺀다**고 결정했다. 그래서 이 설계의 완성 기준은
실기가 아니라 **시뮬 완주에서 step 10 이 진짜 일을 하는 것**이다. 실기는 그다음이다.

---

## 1. 지금 step 10 은 실제로 무엇을 하는가

코드를 따라간 경로다. 로그가 아니라 코드가 근거다.

```text
POST /api/v1/orders
  └─ OutboundPlanner.plan()                      lot·slot 확정 (FEFO)
     └─ planned_outbound_steps()                 step 10 arm/pick 을 만든다
        input = {items:[{line_no, product_code, lot_id,
                         slot_location_id, reserved_quantity}], ...}
        └─ job_steps INSERT                      target_location_id = 도크
           └─ 배정(assign)                       assigned_device_id = assignment.omx_id
              └─ JobRunner.current_step()        step_no 가 가장 작은 미완료 step
                 └─ dispatch_step()              channel=omx, message_type=execute_action
                    └─ ExecutorWorker._run_arm() prepare 명령 1회
                       └─ OmxProtocolSimulator   PREPARING→PICKING→OMX_READY
                          └─ record_executor_outcome()  succeeded, PICK_CONFIRMED
```

| 위치 | 하는 일 |
|---|---|
| [outbound_sequence.py:93-118](../../control_tower/task_manager/outbound_sequence.py#L93-L118) | pick step 을 만든다. `items` 에 품목·lot·slot 이 이미 들어 있다 |
| [repositories.py:3718-3722](../../fms_gateway/app/repositories.py#L3718-L3722) | 배정 때 `executor_type='arm'` 인 step 전부에 `omx_id` 를 박는다 |
| [repositories.py:5462-5471](../../fms_gateway/app/repositories.py#L5462-L5471) | dispatch payload 는 step 의 `input` 을 **그대로** 싣는다 |
| [executor_worker.py:181-201](../../control_tower/task_manager/executor_worker.py#L181-L201) | `prepare` 한 번. 품목 루프도, 파지도, 확인도 없다 |
| [protocol_simulator.py:31-37](../../trihouse_omx_adapter/trihouse_omx_adapter/protocol_simulator.py#L31-L37) | 상태 문자열 전이만. `published_ros_topics()` 는 빈 튜플 |
| [repositories.py:5860-5870](../../fms_gateway/app/repositories.py#L5860-L5870) | `policy_source='rule'` 하드코딩. 모델 계보 칸은 비어 남는다 |

**즉 지금의 step 10 은 "명령 계약이 왕복했다" 는 뜻이지 "집었다" 는 뜻이 아니다.**
런북의 `10 arm pick succeeded PICK_CONFIRMED` 는 이 사실을 가린다.

### 1.1 구현 전에 알고 있어야 하는 세 가지 제약

**(가) 10 과 20 은 병렬이 아니다.** 계획은 `branch`/`dependencies` 로 병렬 분기를
적지만([outbound_sequence.py:85-145](../../control_tower/task_manager/outbound_sequence.py#L85-L145)),
그 필드를 **읽는 곳이 없다.** 러너는 `step_no` 가 가장 작은 미완료 step 하나만 보고
([job_runner.py:107-115](../../control_tower/task_manager/job_runner.py#L107-L115)),
Gateway 는 앞 번호가 전부 `succeeded` 가 아니면 dispatch 를 거절한다
([repositories.py:5433-5440](../../fms_gateway/app/repositories.py#L5433-L5440)).
**파지가 30 초 걸리면 로봇은 30 초 동안 출발하지 않는다.** ③(ACT 호출)을 붙이는
순간 이것이 체감된다. 병렬화는 이 문서의 범위 밖이지만, **파지 시간을 재서 남기는
것**(④)은 범위 안이다. 그 표본이 병렬화 판단의 근거가 된다.

**(나) pick step 의 목적지는 slot 이 아니라 도크다.**
`target_location_id = bundle.dock_location_id`
([outbound_sequence.py:96](../../control_tower/task_manager/outbound_sequence.py#L96)).
집을 자리는 `input.items[].slot_location_id` 에만 있다. P0 실측 공간은 2.20 × 2.70 m
라 선반과 workcell 이 사실상 같은 자리지만, **명령을 만들 때 둘을 구분해서 실어야**
나중에 떨어져도 그대로 돈다.

**(다) 팔은 시뮬 월드에 존재하지 않는다.**
[two_pinky_order_demo.launch.py](../../trihouse_rmf_bridge/launch/two_pinky_order_demo.launch.py)
는 OMX 를 스폰하지 않는다. `gazebo_omx_adapter` 는 화물 상태 토픽만 내는 대역이다
([gazebo_adapter_node.py](../../trihouse_omx_adapter/trihouse_omx_adapter/gazebo_adapter_node.py)).
Gazebo 에서 팔이 실제로 움직이게 하려면 모델과 controller 를 새로 세워야 한다 — §4.4.

---

## 2. ①(팔 선택) — 어느 OMX-AI 인가

### 2.0 정정 — 고칠 곳은 `assignment.py` 가 아니다

`ControlTowerAssigner`([assignment.py:52](../../control_tower/task_manager/assignment.py#L52))
는 **런타임에서 아무도 부르지 않는다.** `grep -rn "ControlTowerAssigner"` 가 내는
호출자는 [test_assignment.py](../../control_tower/tests/test_assignment.py) 뿐이다.

실제로 팔을 고르는 곳은 여기다.

```text
JobRunner._select_assignment()          job_runner.py:257-285
  └─ _first_free(devices, "arm", ...)   job_runner.py:341-354   ← 사전순 첫 번째
     └─ JobAssignmentRequest(omx_id=…)
        └─ POST /internal/v1/jobs/{id}/assignment
           └─ repositories.py:3718      arm step 전부에 그 omx_id 를 박는다
```

`_first_free` 는 `device_type == "arm"` 과 `assignable`(automatic·idle·ok) 만 본다.
**온도대는 애초에 이 함수에 들어오지도 않는다.**

### 2.1 온도대는 이미 두 곳에 있다 — 새로 조회할 필요가 없다

| 어디 | 무엇 | 확인 |
|---|---|---|
| job 상세의 pick step `input.temperature_zone` | 계획이 bundle 온도대를 적어 둔다 | `GET /api/v1/jobs/{id}` 응답의 `steps[].input` 에 **이미 실려 있다**([repositories.py:4807-4822](../../fms_gateway/app/repositories.py#L4807-L4822)) |
| `GET /api/v1/inventory/lots` | lot 마다 `temperature_zone`·`location_code` | 이미 노출된다 |

**따라서 "물품 DB 를 다시 검색" 할 필요가 없다.** 주문 시점에 planner 가 FEFO 로
lot 을 고르면서 온도대를 이미 확정했고([outbound_planner.py:170-200](../../control_tower/task_manager/outbound_planner.py#L170-L200)),
그 값이 step `input` 에 실려 원장에 저장돼 있다. 러너는 **자기가 방금 읽은 job 상세에서
꺼내 쓰기만 하면 된다.** 재조회는 두 값이 갈라질 자리를 만들 뿐이다.

막는 것은 딱 두 개의 **투영 누락**이다.

| 누락 | 지금 | 고칠 곳 |
|---|---|---|
| step 의 `input` 이 러너까지 안 온다 | `JobStepDetail` 에 `input` 필드가 없어 `from_dict` 가 버린다 | [fms_client.py:146-159](../../control_tower/gateway/fms_client.py#L146-L159) 에 `input: JsonObject = field(default_factory=dict)` 한 줄 |
| 장비의 `capabilities` 가 안 온다 | `list_devices` SELECT 에 열이 없다 | [repositories.py:1277-1288](../../fms_gateway/app/repositories.py#L1277-L1288) SELECT 에 `d.capabilities` 추가 + [fms_client.py:96-108](../../control_tower/gateway/fms_client.py#L96-L108) `DeviceSummary` 에 필드 추가 |

둘 다 **데이터는 이미 DB 에 있다.** 투영만 넓히면 된다.

### 2.2 무엇을 근거로 고르는가 — `capabilities` JSON

스키마는 건드리지 않는다. `devices.capabilities` 가 이미 JSON 열이다.

```jsonc
// devices.capabilities — OMX_01
{
  "pick": true, "place": true,
  "workcell_location_code": "OMX-WS-01",
  "served_temperature_zones": ["ambient", "chilled", "frozen"],
  "served_dock_location_codes": ["OUT-DOCK-01"],
  "reach_radius_m": 0.28,
  "payload_limit_kg": 0.5
}
```

**P0 재고는 온도대가 셋이다**(`ambient`/`chilled`/`frozen` — `GET /api/v1/inventory/lots`
로 확인된다). 팔은 둘뿐이므로 **한 팔이 여러 온도대를 담당하는 것이 정상**이고,
`served_temperature_zones` 는 그래서 목록이다. 실물 배치가 정해지면 좁힌다.

### 2.3 만들 것 — 순수 함수 하나와 배선 네 줄

**`control_tower/task_manager/arm_selection.py` (신규).** DB 도 ROS 도 모른다.

```python
@dataclass(frozen=True)
class ArmCandidate:
    device_id: str
    assignable: bool
    served_temperature_zones: tuple[str, ...]
    served_dock_location_codes: tuple[str, ...]
    payload_limit_kg: float | None


class ArmUnavailable(Exception):
    """요구 조건을 만족하는 팔이 없다. 배정을 미룬다."""


def choose_arm(
    candidates: tuple[ArmCandidate, ...],
    *,
    temperature_zones: frozenset[str],      # 이 job 이 건드리는 온도대 전부
    dock_location_codes: frozenset[str],
    reserved: frozenset[str],
    max_item_weight_kg: float | None = None,
) -> str:
    """조건을 만족하는 팔 중 사전순 첫 번째. 없으면 ArmUnavailable."""
```

규칙 넷.

1. `assignable` 이고 `reserved` 에 없을 것
2. `served_temperature_zones` 가 `temperature_zones` 를 **전부** 덮을 것
3. `served_dock_location_codes` 가 `dock_location_codes` 를 **전부** 덮을 것
4. `payload_limit_kg` 가 `max_item_weight_kg` 이상일 것 (값이 없으면 이 규칙은 건너뛴다)

**fail-closed 로 만든다.** `capabilities` 에 키가 없는 팔은 "아무 데나 쓸 수 있는 팔"
이 아니라 **후보에서 빠진다.** 그래야 seed 를 채우는 것을 잊으면 조용히 잘못 배정되는
대신 `ArmUnavailable` 로 눈에 띈다.

**배선.** [job_runner.py:264](../../control_tower/task_manager/job_runner.py#L264) 의
`_first_free(devices, "arm", reserved.arms)` 를 `choose_arm(...)` 으로 바꾸고, 온도대와
도크는 `detail.steps` 의 pick step `input` 에서 모은다.

```python
zones = frozenset(
    step.input["temperature_zone"]
    for step in detail.steps
    if step.action_type == "pick" and step.input.get("temperature_zone")
)
```

`ArmUnavailable` 이면 `_select_assignment` 는 지금처럼 `None` 을 돌려준다 — 러너가
다음 주기에 다시 본다. **주문을 실패시키지 않는다.**

`mobile` 쪽 `_first_free` 는 **그대로 둔다.** 이 커밋의 범위는 팔이다.

### 2.4 알고 넘어갈 구조적 한계 — 한 job 에 팔은 하나뿐

`AssignmentRevision` 은 `omx_id` **하나**를 갖고
([assignment.py:37-44](../../control_tower/task_manager/assignment.py#L37-L44)),
배정 SQL 은 `executor_type='arm'` 인 **모든** step 에 그 하나를 박는다
([repositories.py:3718-3722](../../fms_gateway/app/repositories.py#L3718-L3722)).
그런데 계획은 **온도대마다 bundle 을 만들고 bundle 마다 pick step 을 낸다.**
상온+냉동 주문이면 pick 이 둘인데 팔은 하나로 고정된다.

그래서 §2.3 의 규칙 2 가 "**전부** 덮을 것" 이다. 팔 하나가 그 job 의 온도대를 전부
담당할 수 없으면 배정 자체를 미룬다 — **틀린 팔에 보내는 것보다 기다리는 것이 낫다.**

step 별로 다른 팔을 쓰려면 `assigned_device_id` 를 배정이 아니라 **계획이** 정해야
한다. 옛 템플릿
[outbound_segment_template](../../control_tower/task_manager/outbound_sequence.py#L21-L60)
에 그 자리(`assigned_device_id="OMX_01"`)가 남아 있고, 배정 SQL 의 `WHEN 'arm' THEN %s`
를 `COALESCE(assigned_device_id, %s)` 로 바꾸면 산다. **이번에는 하지 않는다.**

## 3. ②(명령 payload) — 무엇을 집으라고 말하는가

### 3.1 지금 나가는 명령은 품목을 말하지 못한다

[executor_worker.py:325-332](../../control_tower/task_manager/executor_worker.py#L325-L332):

```python
items = step_input.get("expected_items") or step_input.get("items")
if isinstance(items, (list, tuple)) and items:
    return tuple(str(item) for item in items)
```

계획이 싣는 `items` 는 **dict 의 리스트**다. 그래서 팔이 받는 `expected_items` 는

```text
("{'line_no': 1, 'product_code': 'SKU-PORKBELLY', 'lot_id': 3, 'slot_location_id': 7, 'reserved_quantity': 1}",)
```

한 덩어리 문자열이다. 시뮬레이터는 "빈 문자열이 아닐 것" 만 요구하므로
([protocol_simulator.py:138-145](../../trihouse_omx_adapter/trihouse_omx_adapter/protocol_simulator.py#L138-L145))
**아무 불평 없이 통과한다.** `marker_id` 도 입력에 없어 언제나 `0` 이다
([executor_worker.py:334-343](../../control_tower/task_manager/executor_worker.py#L334-L343)).
테스트는 `expected_items` 를 문자열 리스트로 주는 경로만 덮는다
([test_executor_worker.py:215-223](../../control_tower/tests/test_executor_worker.py#L215-L223)).

**ACT 를 붙이기 전에 이것부터 고친다.** 정책에게 무엇을 집으라고 말할 수 없으면
그 뒤의 어떤 것도 의미가 없다.

### 3.2 pick 명령의 최종 모양

기존 `prepare` 를 유지하고 **`pick` kind 를 새로 연다.** `prepare` 는 "자세를 잡아라",
`pick` 은 "이 품목을 집어라" 로 뜻이 갈린다.

```jsonc
{
  "command_uuid": "omx-<job_step_id>-rev-<revision>-item-<job_item_id>",
  "kind": "pick",
  "job_step_id": 41, "assignment_revision": 1, "omx_id": "OMX_01",
  "expected_items": ["SKU-PORKBELLY"],          // 하위호환: 기존 필수 필드 유지
  "marker_id": 0,                                //  〃
  "targets": [                                   // 새로 는다
    {
      "job_item_id": 11, "line_no": 1,
      "product_code": "SKU-PORKBELLY", "lot_id": 3, "lot_code": "LOT-...",
      "quantity": 1,
      "slot_location_id": 7, "slot_location_code": "A-SLOT-01",
      "shelf_marker_id": 0,                      // ArUco DICT_5X5_50
      "unit_weight_kg": 0.35,
      "place_location_id": 12                    // 도크. 팔이 내려놓을 자리
    }
  ],
  "act": {"policy_key": "ambient_box", "model_lineage": "fake-act/p0-v1"}
}
```

만드는 순서 — **payload 를 넓히는 것이 아니라 원장이 아는 것을 옮기는 것**이다.

| 필드 | 출처 | 없으면 |
|---|---|---|
| `job_item_id` | `job_items` | ④(증거)에서 품목별 증거를 못 적는다. **필수** |
| `product_code`/`lot_id`/`slot_location_id`/`quantity` | 이미 step `input.items` 에 있다 | — |
| `slot_location_code` | `locations` 조회 | 사람이 로그를 못 읽는다 |
| `shelf_marker_id` | **원장에 없다** → §3.3 | QR/ArUco 확인을 못 한다 |
| `unit_weight_kg` | `inventory_lots` 에 열이 있으나 **아무도 안 읽는다** | payload 한계 대조를 못 한다 |
| `place_location_id` | step 의 `target_location_id` | 어디에 놓을지 모른다 |

`job_item_id` 와 `unit_weight_kg` 는 계획 시점에 `input.items` 에 함께 싣는 것이
가장 싸다 — [outbound_sequence.py:104-114](../../control_tower/task_manager/outbound_sequence.py#L104-L114)
의 dict 에 두 키를 더하면 dispatch payload 가 그대로 옮겨 준다
([repositories.py:5470](../../fms_gateway/app/repositories.py#L5470)). 그러려면
`PlannedItem` 이 두 값을 들고 있어야 하고, 그것은 planner 가 이미 lot 행을 읽으므로
가능하다. **Gateway 에 새 조회를 넣지 않는 쪽을 고른다.**

### 3.3 marker_id 는 원장 어디에도 없다

`marker_id` 를 요구하는 곳은 셋인데
([omx_protocol.py:124-126](../../control_tower/gateway/omx_protocol.py#L124-L126),
[protocol_simulator.py:147-149](../../trihouse_omx_adapter/trihouse_omx_adapter/protocol_simulator.py#L147-L149),
[marker_worker/policy.py](../../vision_system/marker_worker/policy.py)),
**그 값을 낳는 곳이 없다.** 설계는 "선반에 이미 붙은 `DICT_5X5_50` 의 0·1·2 를 그대로
쓴다" 고 정했다([2026-08-18 설계 1절](2026-08-18-omx-arm-hardware-design.md)).

`locations.metadata` JSON 에 넣는다. 새 열도 새 테이블도 필요 없다.

```jsonc
// locations.metadata — A-SLOT-01
{"aruco_dict": "DICT_5X5_50", "aruco_marker_id": 0}
```

`slot` 타입 location 에 채우고, 계획이 `input.items[].shelf_marker_id` 로 옮긴다.
**값이 없는 slot 은 pick 후보에서 뺀다.** 지금처럼 `0` 을 지어내면 "0 번 마커가 안
보인다" 는 거짓 실패가 나거나, 더 나쁘게는 엉뚱한 선반에서 집는다.

### 3.4 프로토콜 확장의 규칙

[protocol_simulator.py:19-29](../../trihouse_omx_adapter/trihouse_omx_adapter/protocol_simulator.py#L19-L29)
의 `REQUIRED_FIELDS` 와 `SUPPORTED_KINDS`, 그리고
[omx_protocol.parse_omx_assigned_command](../../control_tower/gateway/omx_protocol.py#L96-L136)
가 같은 계약의 양쪽이다. **둘을 한 커밋에서 같이 바꾼다.**

- `SUPPORTED_KINDS` 에 `"pick"` 을 더하고 `_TRANSITIONS["pick"] = ("PICKING", "GRASPED", "OMX_READY")`
- `targets` 는 `kind == "pick"` 일 때만 필수. 나머지 kind 는 지금 그대로
- `targets` 검증은 `expected_items` 와 **같은 엄격함**으로 — 빈 리스트, 빈 문자열,
  0 이하 수량, 음수 marker 는 `INCOMPLETE_COMMAND`
- `command_uuid` 에 `job_item_id` 를 넣는 이유: 시뮬레이터가 `command_uuid` 로 응답을
  캐시하므로([protocol_simulator.py:79-82](../../trihouse_omx_adapter/trihouse_omx_adapter/protocol_simulator.py#L79-L82))
  품목마다 달라야 두 번째 품목이 첫 번째의 응답을 되받지 않는다

---

## 4. ③(ACT 호출) — 어떻게 집는가

### 4.1 지금의 ACT 는 계보와 게이트뿐이다

[ActPolicyLoader](../../trihouse_omx_adapter/trihouse_omx_adapter/act_policy.py#L88-L129)
는 `repo_id`/`revision`/`profile` 세 값이 모두 실제 값일 때만 hardware mode 를 연다.
`run_episode` 는 **stage 이름 다섯 개를 순서대로 늘어놓을 뿐 추론하지 않는다**
([act_policy.py:62-86](../../trihouse_omx_adapter/trihouse_omx_adapter/act_policy.py#L62-L86)).
`config/act.simulation.yaml` 은 셋 다 `UNCONFIGURED` 다.

그리고 [executor_worker_node.py:77-90](../../control_tower/task_manager/executor_worker_node.py#L77-L90)
은 real motion 정책이 실리면 **기동을 거부한다.** 이 게이트는 옳고, 그대로 둔다.

### 4.2 붙일 것 — 모듈 넷과 그 경계

[2026-08-18 설계 3절](2026-08-18-omx-arm-hardware-design.md)이 정한 이름을 그대로 쓴다.
**경계 원칙 하나**: 위로 갈수록 순수하고, 아래로 갈수록 하드웨어를 안다.
`pick_sequence` 는 ROS 를 모르고, `act_runner` 는 Gateway 를 모르고,
`arm_backend` 만 모터를 안다.

```text
trihouse_omx_adapter/trihouse_omx_adapter/
├─ pick_sequence.py     (신규) 순수 상태 기계. 관측을 받아 결정만 낸다
├─ act_runner.py        (신규) 정책 로드 + 관측→action 추론
├─ perception.py        (신규) 손목 카메라 프레임 + QR/ArUco pose  → §4.5
└─ arm_backend.py       (신규) action 을 어디로 보내는가 (contract/gazebo/hardware)
```

**`pick_sequence.py` — 순수 상태 기계.** ROS 도 하드웨어도 모른다.

```python
class PickStage(StrEnum):
    QR_REQUIRED = 'QR_REQUIRED'
    MARKER_ALIGNING = 'MARKER_ALIGNING'
    OBJECT_REDETECT = 'OBJECT_REDETECT'
    ACT_RUNNING = 'ACT_RUNNING'
    GRASP_VERIFYING = 'GRASP_VERIFYING'
    HANDOVER_READY = 'HANDOVER_READY'
    RETRY_OFFSET = 'RETRY_OFFSET'
    ITEM_HELD = 'ITEM_HELD'          # fail-closed 종점


@dataclass(frozen=True)
class PickObservation:
    """이 모듈은 관측을 **만들지 않는다.** 받아서 판단만 한다."""
    qr: QrObservation | None
    marker: MarkerObservation | None
    gripper_position: float | None       # 0.0 = 완전 닫힘
    gripper_closed_position: float | None
    marker_moved_with_arm: bool | None
    act_episode_done: bool = False


@dataclass(frozen=True)
class PickDecision:
    stage: PickStage
    reason_code: str                     # 원장에 그대로 들어간다
    retry_offset: tuple[float, float] | None = None
    grasp_confirmed: bool = False


class PickSequence:
    def __init__(self, *, authorization: PickAuthorization,
                 workflow: OmxWorkflow, job_id: str) -> None: ...

    def advance(self, observation: PickObservation) -> PickDecision: ...
```

- QR/ArUco 판정은 [marker_worker.MarkerPolicy](../../vision_system/marker_worker/policy.py)
  를 **그대로 부른다.** 새로 만들지 않는다
- 재시도 offset 과 소진 판정은 이미 있는
  [OmxWorkflow.authorize_pick/pick_failed](../../control_tower/task_manager/omx_workflow.py#L59-L88)
  를 부른다 — **지금 테스트만 import 하는 그 모듈이 처음으로 런타임에 들어간다**
- 운영자 선택(재시도/포장대 처리)은 [PickRecovery](../../control_tower/task_manager/omx_workflow.py#L155-L246)

**파지 확인이 이 모듈의 핵심이다.** `GRASP_VERIFYING` 에서 두 근거 중 하나 이상이
참일 때만 `HANDOVER_READY` 로 간다.

```python
def _grasp_confirmed(o: PickObservation) -> bool:
    held = (o.gripper_position is not None
            and o.gripper_closed_position is not None
            and o.gripper_position > o.gripper_closed_position + GRIPPER_OBJECT_MARGIN_M)
    tracked = o.marker_moved_with_arm is True
    return held or tracked          # 둘 다 None 이면 False — fail-closed
```

**둘 다 관측이 없으면 `False` 다.** `None` 을 "아마 됐을 것" 으로 읽지 않는다.
[로봇팔 작업·안전 경계](../architecture/robot_arm_safety.md)의 fail-closed 규정 그대로다.

**`act_runner.py` — 정책을 부른다.**

```python
@dataclass(frozen=True)
class ActObservation:
    wrist_image: "np.ndarray"            # HxWx3 uint8
    joint_positions: tuple[float, ...]
    gripper_position: float


@dataclass(frozen=True)
class ActAction:
    joint_positions: tuple[float, ...]
    gripper_position: float
    model_lineage: str                   # ④(증거) 에 그대로 들어간다


class ActRunner:
    def __init__(self, policy: ActPolicy) -> None: ...

    def reset(self, *, command_uuid: str, assignment_revision: int) -> None:
        """episode 경계. 재시도할 때 반드시 부른다
        (PickRecovery 가 reset_act_episode=True 를 내는 그 자리)."""

    def step(self, observation: ActObservation) -> ActAction: ...
```

- 정책이 `is_fake` 면 `step()` 은 **현재 joint 를 그대로 돌려준다.** 움직이지 않는
  action 이지 예외가 아니다 — 계약 경로는 그대로 돌아야 하기 때문이다
- 실제 추론은 LeRobot ACT policy 를 부른다. **모터에 직접 쓰지 않는다** —
  반드시 `arm_backend` 를 거쳐 `open_manipulator_collision` 의 충돌 검사를 살린다
- 5080 원격 추론은 나중에 `step()` 내부만 HTTP 로 바꾸면 된다. **이 서명은 안 바뀐다**

**품목별 정책 선택.** `config/act.*.yaml` 에 목록을 더한다.

```yaml
# config/act.hardware.yaml — 실제 값이 확인되었다(2026-08-20). §4.6 참조
policies:
  - product_code: SKU-PORKBELLY
    repo_id: 2usang/act_trihouse-porkbelly
    revision: 50939ab8953b2574c586898366308064a8de56f1   # 커밋 SHA 로 못박는다
    profile: omx_follower
```

`select_policy(product_code) -> ActPolicy` 를 `ActPolicyLoader` 옆에 둔다.
**맞는 정책이 없으면 기본으로 조용히 떨어지지 않고 거절한다.** 어떤 정책으로 집었는지가
④(증거)에 남아야 하기 때문이다.

**`arm_backend.py` — 문 하나, 구현 셋.**

```python
class ArmBackend(Protocol):
    def observe(self) -> ActObservation: ...
    def apply(self, action: ActAction) -> None: ...
    def open_gripper(self) -> None: ...
    def retreat(self) -> None: ...
```

| 구현 | `apply` 가 하는 일 | 팔이 움직이나 |
|---|---|---|
| `ContractArmBackend` | 아무것도. `OmxProtocolSimulator` 상태만 민다 | 아니오 |
| `GazeboArmBackend` | `/omx_01/arm_controller/joint_trajectory` 로 발행 | 시뮬 안에서 예 |
| `HardwareArmBackend` | MoveIt / `joint_trajectory_controller` | 예 |

### 4.3 실행기는 어떻게 이것을 부르는가

[ExecutorWorker._run_arm](../../control_tower/task_manager/executor_worker.py#L181-L201)
이 지금 `prepare` 한 번 보내는 자리를 **품목 루프**로 바꾼다. 의사코드다.

```python
def _run_arm(self, dispatch):
    targets = _pick_targets(dispatch)              # §3.2
    driver = self._drivers[self._actor_device(dispatch)]
    segments = {}
    for target in targets:
        started = self._clock_ms()
        result = driver.pick(                      # ← OmxPickDriver (신규)
            command_uuid=f"{_command_uuid(dispatch)}-item-{target.job_item_id}",
            target=target,
            assignment_revision=dispatch.assignment_revision,
        )
        segments[f"pick_{target.job_item_id}_ms"] = self._clock_ms() - started
        self._gateway.record_pick_attempt(...)     # §5.2 — 성공이든 실패든 남긴다
        if not result.grasp_confirmed:
            raise PickNotConfirmed(result.reason_code)   # step 은 failed 로 닫힌다
    return segments
```

`OmxPickDriver` 가 `PickSequence` + `ActRunner` + `ArmBackend` 를 묶는 얇은 조립층이고,
`trihouse_omx_adapter` 안에 둔다. **실행기는 팔의 내부를 모른 채 `pick()` 하나만 안다** —
지금 `simulator.execute()` 하나만 아는 것과 같은 깊이다.

### 4.4 어느 backend 로 돌지는 환경이 정한다 — 양방향으로 막는다

[executor_worker_node.py:77-90](../../control_tower/task_manager/executor_worker_node.py#L77-L90)
의 게이트를 환경별로 가른다.

| `--environment` | 허용 | 거절 |
|---|---|---|
| `simulation` | `contract`·`gazebo`, fake 정책 | real motion 정책 → `SystemExit` (지금 그대로) |
| `hardware` | `hardware`, real 정책 | **fake 정책 → `SystemExit`** (새로) |

**시뮬에서 실물이 도는 것도 사고지만, 실기에서 fake 가 조용히 도는 것도 사고다** —
팔이 가만히 있는데 step 은 `succeeded` 로 닫히고 아무도 눈치채지 못한다. 지금
정확히 그 상태다.

### 4.5 카메라 — 손목만으로는 부족하다. **`front` 와 `wrist` 둘 다** 필요하다

**정정(2026-08-20).** 실제 checkpoint 의 `config.json` 을 읽어 보니 정책 입력이
`observation.images.front` 와 `observation.images.wrist` **둘**이다(§4.6). 손목 하나만
붙이면 정책이 돌지 않는다.

**손목 쪽은 자리가 이미 잡혀 있다.** 명부에 등록돼 있다.

| 있는 것 | 어디 |
|---|---|
| `CAM-OMX-01-WRIST` / `CAM-OMX-02-WRIST`, `role: omx_wrist`, `attached_to: OMX_01/02` | [config/cameras.yaml](../../config/cameras.yaml) |
| 스트림 경로 `omx/CAM-OMX-01-WRIST` (역할 접두사에서 파생) | [camera_registry.py:31-35](../../control_tower/gateway/camera_registry.py#L31-L35) |
| MediaMTX 의 그 경로 | [config/mediamtx.yml:159-160](../../config/mediamtx.yml#L159-L160) |
| RTSP → raw frame 변환 계약 | [common/stream.py](../../model/worker/common/stream.py) |
| 녹화 구간 조회(`camera_id + 시각 → segment`) | [recording_server/catalog.py](../../model/worker/media/recording/catalog.py) |

**`front` 카메라는 명부에 없다.** `config/cameras.yaml` 의 역할은 `pinky_travel`,
`omx_wrist`, `warehouse_fixed` 셋뿐이고, OMX 작업대를 정면에서 보는 카메라가 없다.
`CAM-FIXED-01/02`(`warehouse_fixed`)를 그 자리에 쓸 수 있는지, 아니면 `omx_front`
역할을 새로 여는지가 **결정 사항**이다. 역할을 새로 열면
[ROLE_STREAM_PREFIX](../../control_tower/gateway/camera_registry.py#L31-L35) 와
[mediamtx.yml](../../config/mediamtx.yml#L156-L162) 의 경로도 함께 는다.

**없는 것은 실제 카메라와, 그것을 그 경로로 밀어 주는 프로세스뿐이다.**
`simulation_path: fixtures/omx_01_wrist` 는 P0 가 카메라를 물리적으로 안 붙였다는 뜻이다.

**경로를 둘로 나눈다. 이것이 이 절의 유일한 설계 결정이다.**

| 용도 | 경로 | 왜 |
|---|---|---|
| **ACT 추론 입력** | 팔 PC 에서 `/dev/video*` 를 **로컬로 직접** 연다 | RTSP 왕복은 인코딩·버퍼로 100 ms 단위 지연이 붙는다. 정책 제어 루프에 그 지연을 넣으면 파지가 흔들린다 |
| **증거·감시** | 같은 프레임의 사본을 MediaMTX `omx/CAM-OMX-01-WRIST` 로 publish | 녹화·운영 화면·`evidence_refs` 는 지연을 신경 쓰지 않는다 |

즉 `perception.py` 가 카메라를 **한 번 열고 프레임을 두 갈래로 낸다.** 두 프로세스가
같은 `/dev/video0` 을 열려고 다투게 두지 않는다.

```python
class WristCamera:
    """한 번 열고 최신 프레임 하나만 들고 있는다. 프레임 큐를 쌓지 않는다."""
    def latest(self) -> "np.ndarray": ...
    def marker_pose(self, expected_marker_id: int) -> MarkerObservation | None: ...
    def qr(self) -> QrObservation | None: ...
```

**QR/ArUco 디코딩은 `model.worker.marker`의 것을 쓴다**([model/worker/marker/edge_perception.py](../../model/worker/marker/edge_perception.py)).
설계가 정한 대로 `DICT_5X5_50` 의 0·1·2 이고 새 ID 범위를 만들지 않는다.

**실물에서 30 초면 끝나는 확인 셋** (A5 단계에서):

1. 카메라가 손목에 달렸을 때 **집는 자리가 화면에 들어오는가**. 안 들어오면 마운트를
   옮기는 것이지 소프트웨어로 풀 문제가 아니다
2. `marker_moved_with_arm` 판정에 필요한 **프레임률이 나오는가**. 팔이 움직이는 동안
   마커를 계속 잡아야 한다
3. **조명.** 냉동고 앞은 어둡다. 노출을 고정하지 않으면 프레임마다 밝기가 튄다

**P0 시뮬에서는 fixture 로 간다.** `simulation_path` 가 그 자리다. `gazebo` backend 를
만든다면 Gazebo 카메라 센서를 손목 링크에 붙여 그 이미지를 쓴다 —
[pinky_gz.urdf.xacro 의 센서가 조용히 버려졌던 사고](../runbooks/p0-simulation-quick-run.md#이-pc-에서-고친-것)
와 같은 함정이 있으므로, 붙인 뒤 **토픽이 실제로 나오는지 반드시 확인**한다.

### 4.6 실제 checkpoint — 확인된 사실 (2026-08-20)

`https://huggingface.co/2usang` 에 모델 18 개가 있고, 그중 **품목별 ACT 정책 10 개**가
지금 재고의 SKU 와 대응한다. `huggingface.co/api/models?author=2usang` 로 확인했다.

**열 정책의 계약이 완전히 동일하다.** 코드 경로는 하나면 되고 checkpoint 만 갈린다.

| 항목 | 값 |
|---|---|
| `type` | `act` |
| `observation.state` | `[6]` — `shoulder_pan / shoulder_lift / elbow_flex / wrist_flex / wrist_roll / gripper` (`.pos`) |
| `observation.images.front` | `[3, 480, 640]` |
| `observation.images.wrist` | `[3, 480, 640]` |
| `action` | `[6]` (state 와 같은 순서) |
| `chunk_size` / `n_action_steps` | 100 / 100 |
| `n_obs_steps` | 1 |
| `device` | `cuda` |
| 학습 데이터 | `robot_type: omx_follower`, 30 fps, 40 episode / 41,274 frame |

여기서 곧바로 따라오는 것 넷.

1. **카메라가 둘이다.** §4.5 참조. 손목만으로는 정책이 돌지 않는다
2. **6 자유도다**(5 관절 + 그리퍼). `devices.model = 'OMX-AI'` 와 맞는다. `joint_states`
   의 **이름과 순서와 단위**가 위 목록과 일치하는지 실물에서 확인해야 한다 —
   순서가 어긋나면 정책은 오류 없이 **엉뚱한 관절을 움직인다**
3. **GPU 가 필요하다.** 팔 PC 에 없으면 5080 원격 추론이 선택이 아니라 전제가 된다
4. **한 번에 100 step 을 낸다.** `ActRunner.step()` 이 매번 추론하는 것이 아니라
   **chunk 를 받아 소비하는 구조**여야 한다. 30 fps 기준 100 step ≈ 3.3 초

### 4.7 SKU → 모델 이름 파생은 **하지 않는다**

`SKU-PORKBELLY` → `porkbelly` → `act_trihouse-porkbelly` 는 **재고 SKU 11 개 중
8 개만** 맞는다. 실제로 대조한 결과다.

| SKU | 파생 이름 | 실제 저장소 |
|---|---|---|
| `SKU-STRAWBERRY` / `-ORANGE` / `-SANDWICH` / `-MILK` / `-YOGURT` / `-COFFEE` / `-PORKBELLY` / `-DUMPLING` | 그대로 | `2usang/act_trihouse-<이름>` ✅ |
| `SKU-ICECONE` | `icecone` | **`act_trihouse-icecorn`** — 철자가 다르다 ❌ |
| `SKU-ICEBAR` | `icebar` | **후보 둘** — `act_trihouse-icebar`, `omx_trihouse-icebar` ❌ |
| `SKU-MANDARIN` | `mandarin` | **없다** ❌ |

**문자열 파생은 세 가지 방식으로 조용히 틀린다** — 없는 이름(404), 다른 철자(404),
같은 이름 둘(어느 쪽인지 모름). 그리고 이것은 **품목이 늘 때마다 다시 틀린다.**

그래서 §4.2 처럼 **설정 파일에 명시적으로 적고, 없으면 거절한다.**

- 매핑은 `product_code → (repo_id, revision, profile)` 정본 하나
- `revision` 은 **커밋 SHA 로 못박는다.** `main` 을 가리키면 어제 돌던 것과 오늘
  돌던 것이 달라지고, ④(증거)의 `model_version` 이 무의미해진다
- 매핑에 없는 SKU 는 주문 접수나 배정 단계에서 **미리** 거절한다. 팔 앞에서
  알게 되면 로봇은 이미 도크에 가 있다

`SKU-MANDARIN` 은 지금 재고에 2 개 있는데 정책이 없다. **정책 없는 SKU 를 어떻게
할지가 결정 사항이다** — 주문을 거절하든, 수동 처리로 넘기든, 둘 중 하나를 정해야 한다.

---

## 5. ④(증거·게이트) — 집었다는 것을 무엇으로 아는가

### 5.1 원장은 이미 받을 준비가 되어 있다

`job_step_attempts` 에 칸이 전부 있다
([schema_mysql.sql:497-585](../../db/migrations/001_physical_v1_baseline.sql#L497-L585)):
`criteria`, `before_observation`, `after_observation`, `evidence_refs`,
`policy_source`(`rl` 허용), `policy_name`/`policy_version`,
`model_name`/`model_version`. **비어 있을 뿐이다.**

`load` 는 이 길을 이미 걸었다. 품목마다 `LOAD_CONFIRMED` 증거를 내고
([executor_worker.py:227-300](../../control_tower/task_manager/executor_worker.py#L227-L300)),
Gateway 가 그것 없이는 step 을 닫아 주지 않는다
([repositories.py:5812-5834](../../fms_gateway/app/repositories.py#L5812-L5834)).
**`pick` 에 같은 구조를 만든다.**

### 5.2 만들 것

| 무엇 | 어떻게 |
|---|---|
| `POST /internal/v1/job-steps/{id}/pick-attempts` | `load-attempts`([main.py:1070](../../fms_gateway/app/main.py#L1070))와 같은 모양. `result` 는 `PICK_CONFIRMED`/`PICK_FAILED`/`MANUAL_FULFILLMENT_REQUIRED` |
| pick 게이트 | `record_executor_outcome` 에서 `action_type == 'pick'` 이고 성공이면, 그 step 의 `targets` 품목이 전부 `PICK_CONFIRMED` 인지 확인. 아니면 `PICK_ITEMS_NOT_CONFIRMED` |
| 모델 계보 | `policy_source` 하드코딩([repositories.py:5868](../../fms_gateway/app/repositories.py#L5868))을 요청값으로 바꾼다. pick 은 `rl`, 나머지는 지금대로 `rule` |
| 증거 참조 | `evidence_refs` 에 손목 카메라 녹화 구간. [RecordingCatalog](../../model/worker/media/recording/catalog.py) 가 이미 `camera_id + timestamp → segment` 를 준다 — [PickFailureReporter](../../control_tower/task_manager/pick_failure_report.py) 가 쓰는 그 경로다 |

**`policy_name`/`model_name` 을 비워 두지 않는 것이 이 절의 요점이다.** 지금
`load` 는 `"policy_name": "cargo-sensor-gate", "model_name": "none"` 으로 정직하게
적고 있다([executor_worker.py:288-296](../../control_tower/task_manager/executor_worker.py#L288-L296)).
pick 은 `ActPolicy.model_lineage` 를 그 자리에 넣는다. `fake-act/p0-v1` 이면
**기록에 그렇게 남아야 한다** — 나중에 "이 완주는 진짜 팔이 집은 것인가" 를 원장만
보고 답할 수 있다.

### 5.3 실패 경로는 이미 설계되어 있다

[PickRecovery](../../control_tower/task_manager/omx_workflow.py#L155-L246) 가 재시도
2 회 · 낙하 hold · 포장대 처리를 정해 두었고,
[record_pick_recovery](../../fms_gateway/app/repositories.py#L4613)가 그것을 원장에
쓴다. **새로 만들지 말고 `pick_sequence` 가 그 결정을 그대로 부르게 한다.**

---

## 6. 순서 — 이대로 간다

각 단계가 **앞 단계 통과 뒤** 시작한다. 매 단계 끝에 런북 한 사이클이 그대로 돌아야 한다.

| # | 무엇 | 통과 기준 | 팔이 움직이나 |
|---|---|---|---|
| P1 | ②(payload) 의 품목 정보를 제대로 싣는다 | `expected_items` 가 `("SKU-PORKBELLY",)`. `targets[0].job_item_id` 가 실제 ID | 아니오 |
| P2 | marker_id 를 원장에 넣는다 | `A-SLOT-01.metadata.aruco_marker_id` 가 있고, 없는 slot 은 주문이 거절된다 | 아니오 |
| P3 | ①(팔 선택) 을 zone/dock 기준으로 | 상온 주문이 `OMX_01` 에 간다. 조건 밖이면 `AssignmentUnavailable` | 아니오 |
| P4 | ④(증거) 배선 — `pick-attempts` + 게이트 | 증거 없이 pick 을 닫으려 하면 `PICK_ITEMS_NOT_CONFIRMED` 로 거절된다 | 아니오 |
| P5 | ③(ACT) `pick_sequence` + `act_runner`, backend=`contract` | 품목마다 episode 가 돌고 계보가 원장에 남는다. 파지 확인 실패를 주입하면 `ITEM_HELD` | 아니오 |
| P6 | backend=`gazebo` (별도 판단, §4.3) | 시뮬 팔이 실제로 궤적을 돈다. 빈 그리퍼로는 `HANDOVER_READY` 로 **가지 않는다** | 시뮬 안에서 예 |
| P7 | 실기 — [2026-08-18 설계](2026-08-18-omx-arm-hardware-design.md) A1~A9 | 그 문서의 게이트 O1~O5 | 예 |

**P1~P4 는 팔이 한 번도 움직이지 않는데 step 10 의 의미를 거의 다 만든다.**
"명령이 왕복했다" 가 "이 lot 의 이 품목을, 이 팔이, 이 정책으로 집었다" 가 된다.
P5 부터가 실제 파지다.

---

## 7. 검증

관례대로 **고치기 전에 실패하는 테스트를 먼저 쓴다.** 하드웨어 없이 도는 것을 늘린다.

| 층 | 테스트 | 하드웨어 |
|---|---|---|
| 순수 | `choose_arm` — zone/dock 불일치 거절, 예약 회피, 후보 없음 | 아니오 |
| 순수 | `pick_sequence` 전이 — 여섯 단계, 파지 확인 실패 시 offset 재시도, 소진 시 `ITEM_HELD` | 아니오 |
| 순수 | `select_policy` — 품목에 맞는 정책이 없으면 거절(기본으로 안 떨어진다) | 아니오 |
| 순수 | `payload_limit_kg` 초과 품목을 pick 인가 전에 거절 | 아니오 |
| 회귀 | **`_expected_items` 가 계획이 만든 `items`(dict 리스트)를 받는 경우** — 지금 없는 케이스 | 아니오 |
| 계약 | `kind="pick"` 검증 — `targets` 누락·빈 값·음수 marker 는 `INCOMPLETE_COMMAND` | 아니오 |
| 계약 | 품목이 둘일 때 `command_uuid` 가 갈라진다(캐시 되받기 없음) | 아니오 |
| 계약 | `--environment hardware` 에서 fake 정책 거절, `simulation` 에서 real 정책 거절 | 아니오 |
| Gateway | 증거 없는 pick 종료가 `PICK_ITEMS_NOT_CONFIRMED` | 아니오 |
| Gateway | pick attempt 가 `policy_source='rl'` 과 모델 계보를 남긴다 | 아니오 |
| 통합 | 런북 한 사이클 완주 — 7 단계 전부 `succeeded` | 아니오(P5 까지) |
| 수동 | P6·P7 | 예 |

---

## 8. 이 문서를 쓰며 확인한 결함

구현 전에 고쳐야 하는 것들이다. **아직 고치지 않았다.**

| # | 증상 | 원인 | 수정 방향 |
|---|---|---|---|
| A1 | 팔에 나가는 `expected_items` 가 `"{'line_no': 1, ...}"` 한 덩어리 | 계획은 dict 리스트를 싣는데 `_expected_items` 가 `str(item)` 한다([executor_worker.py:325-332](../../control_tower/task_manager/executor_worker.py#L325-L332)) | §3.2 — `product_code` 를 뽑고 `targets` 를 따로 싣는다 |
| A2 | `marker_id` 가 언제나 `0` | 원장 어디에도 marker ID 가 없다. 폴백이 `0` 을 지어낸다([executor_worker.py:334-343](../../control_tower/task_manager/executor_worker.py#L334-L343)) | §3.3 — `locations.metadata.aruco_marker_id`. 없으면 후보에서 뺀다 |
| A3 | 팔이 아무 일도 안 했는데 step 이 `PICK_CONFIRMED` 로 닫힌다 | pick 에는 `load` 같은 증거 게이트가 없다 | §5.2 — `pick-attempts` + `PICK_ITEMS_NOT_CONFIRMED` |
| A4 | 어느 모델로 집었는지 원장에 안 남는다 | `policy_source='rule'` 하드코딩, 모델 칸 미사용([repositories.py:5868](../../fms_gateway/app/repositories.py#L5868)) | §5.2 — 요청값으로 받고 `ActPolicy.model_lineage` 를 적는다 |
| A5 | 계획의 `branch`/`dependencies` 를 **읽는 곳이 없다** — 10 과 20 이 병렬로 안 돈다 | 러너가 `step_no` 순 하나씩만 보고, dispatch 가 앞 번호 전부 `succeeded` 를 요구한다 | 이번 범위 밖. §1.1(가) — 먼저 파지 시간을 재서 남긴다 |
| A6 | 한 job 에 온도대가 둘이면 두 pick 이 같은 팔로 고정된다 | `AssignmentRevision.omx_id` 가 하나 | §2.4 — 이번엔 "온도대를 전부 덮는 팔" 을 요구해 회피한다 |
| A7 | 실기에서 fake ACT 가 돌아도 아무도 못 막는다 | 게이트가 한 방향뿐(시뮬만 보호) | §4.4 — `hardware` 에서 fake 거절 |
| A8 | **`ControlTowerAssigner` 는 죽은 코드다** — 배정 정책을 고쳐도 아무 일도 안 일어난다 | 런타임 경로는 `JobRunner._select_assignment` → `_first_free`([job_runner.py:264](../../control_tower/task_manager/job_runner.py#L264)). `assignment.py` 의 호출자는 테스트뿐 | §2.0 — 고칠 곳을 `job_runner` 로 잡는다. 죽은 정책을 어떻게 할지는 별건 |

---

## 9. 열린 결정 — 구현 시작 전에 답이 필요한 것

1. **`gazebo` backend 를 만드는가**(§4.4). 안 만들면 fail-closed 를 실물에서 처음
   시험하게 된다. 만들면 월드·controller·그리퍼 접촉이 새 일감이다.
2. **ACT checkpoint 의 `repo_id`/`revision`/`profile`.** 아직 없다. P5 까지는 fake 로
   갈 수 있고, P6 부터 필요하다.
3. **품목별 정책인가 하나인가.** §4.2 의 `policies:` 목록은 품목별을 전제한다.
   정책이 하나뿐이면 `product_codes: []` 하나로 두고 구조만 남긴다.
4. **P0 월드에 팔 자리가 있는가.** 2.20 × 2.70 m 에서 받침대가 통로를 먹으면
   주행이 막힌다. 1번을 "만든다" 로 정하면 이것부터 잰다.

---

## 10. 지금 눈으로 확인하는 절차 — 명령 하나씩

**전부 이 문서를 쓰면서 실제로 돌려 본 것이다.** 시뮬을 띄우지 않아도 되고
(⑤·⑥ 제외), 아무것도 바꾸지 않는다. 각 항목의 마지막 줄이 **고칠 파일**이다.

모든 명령은 저장소 루트에서 시작한다.

```bash
cd /home/newuser/Trihouse
```

### ① 주문이 만드는 step 10 은 무엇을 아는가

```bash
python3 -c "
from datetime import date, datetime
from control_tower.task_manager.outbound_planner import *
from control_tower.task_manager.outbound_sequence import planned_outbound_steps
import json
order = OutboundOrder('ord-1', None, 'W-OP-01', 'normal', False, (OrderLine(1,'SKU-PORKBELLY',1),))
inv = (InventoryLotSnapshot(8,'LOT-FRZ-PORKBELLY-001','SKU-PORKBELLY','Pork Belly','frozen',31,2,0,date(2026,12,1),datetime(2026,8,1)),)
plan = OutboundPlanner().plan(order, inv, PlanningLocations({'frozen':41},(42,),(43,)))
s = planned_outbound_steps(plan)[0]
print(s.step_no, s.executor_type, s.action_type, 'target=', s.target_location_id)
print(json.dumps(s.input, ensure_ascii=False, indent=2))"
```

`temperature_zone: "frozen"`, `items[].slot_location_id`, `product_codes` 가 **이미 다
들어 있다.** "물품 위치 파악" 은 끝나 있다는 증거다.
→ [outbound_sequence.py:93](../../control_tower/task_manager/outbound_sequence.py#L93)

### ② 그런데 팔에게는 무엇이 나가는가 — A1·A2

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

```text
expected_items = ("{'line_no': 1, 'product_code': 'SKU-PORKBELLY', ...}",)
marker_id      = 0
```

**품목 이름이 dict 문자열 한 덩어리로 뭉개져 나간다.** `product_codes` 가 입력에
버젓이 있는데 쓰지 않는다. `marker_id` 는 언제나 0 이다.
→ [executor_worker.py:325-343](../../control_tower/task_manager/executor_worker.py#L325-L343)

### ③ 팔은 무엇을 보고 골라지는가 — A8

```bash
curl -s http://127.0.0.1:8080/api/v1/devices | python3 -c "
import sys, json
from control_tower.gateway.fms_client import DeviceSummary
from control_tower.task_manager.job_runner import _first_free
rows = json.load(sys.stdin)
devs = tuple(DeviceSummary.from_dict(r) for r in rows)
print('arm 후보 :', [d.device_id for d in devs if d.device_type=='arm' and d.assignable])
print('고른 팔  :', _first_free(devs, 'arm', set()))
print('온도대·capabilities 필드:', [k for k in rows[0] if 'zone' in k or 'capab' in k] or '없음')"
```

```text
arm 후보 : ['OMX_01', 'OMX_02']
고른 팔  : OMX_01
온도대·capabilities 필드: 없음
```

**사전순 첫 번째다.** 온도대는 함수에 들어오지도 않는다.
→ [job_runner.py:264](../../control_tower/task_manager/job_runner.py#L264) ·
[job_runner.py:341](../../control_tower/task_manager/job_runner.py#L341)

배정 정책이라고 적힌 쪽은 호출자가 없다.

```bash
grep -rn "ControlTowerAssigner" --include=*.py . | grep -v "/build/\|/install/"
```

`test_assignment.py` 와 자기 자신뿐이다.
→ [assignment.py:52](../../control_tower/task_manager/assignment.py#L52)

### ④ 온도대는 어디에 있나 — 새로 만들 필요가 없다는 증거

```bash
curl -s http://127.0.0.1:8080/api/v1/inventory/lots | python3 -c "
import sys, json
for r in json.load(sys.stdin):
    print(' ', r['lot_id'], r['product_code'], r['temperature_zone'], r['location_code'],
          'avail=%s resv=%s' % (r['available_qty'], r['reserved_qty']))"
```

세 온도대가 실재한다(`ambient`/`chilled`/`frozen`). `SKU-PORKBELLY` 는 **냉동**이다.
→ [seed_dev.sql:44-118](../../db/seeds/seed_dev.sql#L44-L118)

step `input` 이 러너까지 오는지는 job 상세로 본다(job 이 있을 때).

```bash
curl -s http://127.0.0.1:8080/api/v1/jobs/1 | python3 -c "
import sys, json
j = json.load(sys.stdin)
for s in j['steps']:
    print(s['step_no'], s['executor_type'], s['action_type'],
          '| input.temperature_zone =', (s.get('input') or {}).get('temperature_zone'))"
```

seed 의 job 1 은 `navigate` 한 단계뿐이라 `None` 이 나온다. 주문으로 생긴 job 이면
`frozen` 이 찍힌다. **어느 쪽이든 HTTP 응답에는 `input` 이 실려 있다** — 그것을 버리는
곳이 `JobStepDetail` 이다.
→ [fms_client.py:146](../../control_tower/gateway/fms_client.py#L146)

### ⑤ ACT 는 지금 무엇인가 — 계보만 있고 추론이 없다

```bash
PYTHONPATH=trihouse_omx_adapter python3 -c "
from trihouse_omx_adapter.act_policy import ActPolicyLoader
p = ActPolicyLoader().load_file('config/act.simulation.yaml')
print('mode        =', p.mode)
print('real_motion =', p.real_motion_enabled)
print('lineage     =', p.model_lineage)
ep = p.run_episode(command_uuid='omx-41-rev-1', assignment_revision=1)
print('stages      =', [s.name for s in ep.stages])
print('emitted     =', ep.real_motion_emitted)"
```

stage 이름 다섯 개를 늘어놓을 뿐 **추론하지 않는다.**
→ [act_policy.py:62](../../trihouse_omx_adapter/trihouse_omx_adapter/act_policy.py#L62)

### ⑥ 명령 왕복 — 이것이 지금의 "집는다" 전부다

```bash
echo '{"command_uuid":"omx-41-rev-1","kind":"prepare","job_step_id":41,"assignment_revision":1,"omx_id":"OMX_01","expected_items":["SKU-PORKBELLY"],"marker_id":0}' \
| PYTHONPATH=trihouse_omx_adapter python3 -m trihouse_omx_adapter.simulator_node --omx-id OMX_01
```

`PREPARING → PICKING → OMX_READY` 세 줄. **모터도 좌표도 없다.**
→ [protocol_simulator.py:31](../../trihouse_omx_adapter/trihouse_omx_adapter/protocol_simulator.py#L31)

`kind` 에 `"pick"` 을 넣어 보면 계약이 무엇을 모르는지 바로 보인다.

```bash
echo '{"command_uuid":"x-1","kind":"pick","job_step_id":41,"assignment_revision":1,"omx_id":"OMX_01","expected_items":["SKU-PORKBELLY"],"marker_id":0}' \
| PYTHONPATH=trihouse_omx_adapter python3 -m trihouse_omx_adapter.simulator_node --omx-id OMX_01
```

`{"error": "UNSUPPORTED_COMMAND", ...}` — §3.4 가 여는 자리다.

### ⑦ 손목 카메라 — 자리는 이미 있다

```bash
python3 -c "
from control_tower.gateway.camera_registry import load_camera_registry
for c in load_camera_registry():
    if c.role == 'omx_wrist':
        print(c.camera_id, '| attached_to =', c.attached_to)
        print('   publish     :', c.publish_url('rtsp://127.0.0.1:8554'))
        print('   sim fixture :', c.simulation_path)"
```

```text
CAM-OMX-01-WRIST | attached_to = OMX_01
   publish     : rtsp://127.0.0.1:8554/omx/CAM-OMX-01-WRIST
   sim fixture : fixtures/omx_01_wrist
```

MediaMTX 경로도 이미 뚫려 있다.

```bash
grep -n "omx/" config/mediamtx.yml
```

→ [config/cameras.yaml](../../config/cameras.yaml) · [config/mediamtx.yml:159](../../config/mediamtx.yml#L159)

실물 카메라를 꽂았을 때 확인하는 두 줄(팔 PC 에서).

```bash
v4l2-ctl --list-devices
```
```bash
ffmpeg -f v4l2 -i /dev/video0 -t 2 -f null - 2>&1 | tail -5
```

### ⑧ pick 증거를 받을 API 가 있는가 — A3

```bash
curl -s http://127.0.0.1:8080/openapi.json | python3 -c "
import sys, json
d = json.load(sys.stdin)
for p in sorted(d['paths']):
    if 'attempt' in p or 'outcome' in p or 'pick' in p:
        print(' ', ' '.join(sorted(m.upper() for m in d['paths'][p])), p)"
```

```text
POST /internal/v1/job-steps/{id}/load-attempts     ← load 는 있다
POST /internal/v1/job-steps/{id}/outcome
POST /internal/v1/job-steps/{id}/pick-recovery     ← 실패 처리만 있다
```

**`pick-attempts` 가 없다.** 성공 증거를 낼 자리가 아예 없다.
→ [main.py:1070](../../fms_gateway/app/main.py#L1070) 의 `load-attempts` 를 본뜬다

원장 쪽은 이미 받을 준비가 되어 있다.

```bash
sed -n '528,533p' db/migrations/001_physical_v1_baseline.sql
```

`policy_name`/`policy_version`/`model_name`/`model_version` 칸이 비어 있을 뿐이다.
→ [schema_mysql.sql:496](../../db/migrations/001_physical_v1_baseline.sql#L496) ·
[repositories.py:5868](../../fms_gateway/app/repositories.py#L5868)

### ⑨ 지금 테스트는 어디까지 지키는가

**`tests/__init__.py` 를 수집하면 ROS 의 `launch_testing` 플러그인이 죽는다.
파일을 직접 지정한다.**

```bash
python3 -m pytest trihouse_omx_adapter/tests/test_act_policy.py trihouse_omx_adapter/tests/test_protocol_simulator.py -q
```
```bash
python3 -m pytest control_tower/tests/test_executor_worker.py control_tower/tests/test_assignment.py -q
```

`test_executor_worker.py` 는 `expected_items` 를 **문자열 리스트로 주는 경로만** 덮는다.
계획이 실제로 만드는 dict 리스트는 테스트가 없다 — 그래서 A1 이 살아남았다.
→ [test_executor_worker.py:215](../../control_tower/tests/test_executor_worker.py#L215)

### ⑩ 전 구간을 한 번 돌려 보고 싶을 때

[p0-simulation-quick-run.md](../runbooks/p0-simulation-quick-run.md) 그대로다.
**절대 규칙**: job 하나가 끝나기 전에 새 주문을 넣지 않는다.

```bash
curl -s http://127.0.0.1:8080/api/v1/jobs | python3 -c "
import sys, json
for j in json.load(sys.stdin): print(j['job_id'], j['state'], j.get('assigned_mobile_id'))"
```

돌아가는 job 이 있으면 먼저 끝내거나 `scripts/p0_reset.sh` 부터 한다.
