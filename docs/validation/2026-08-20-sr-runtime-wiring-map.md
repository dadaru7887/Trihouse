# SR 기능별 — 파일이 어디 있고, 실제로 도는가

작성: 2026-08-20 · 방법: **기동 진입점 24 개에서 import 를 따라간 도달 가능 집합**과
`docs/requirements/system_requirements.md` 의 구현 경로 열을 대조. 라이브 Gateway
`/openapi.json` 으로 교차 확인.

실물 테스트 전에 **하나씩 열어 보며 확인**하기 위한 목록이다. 체크박스를 채워 나간다.

---

## 0. 먼저 알아야 할 것 — 스택이 **두 벌**이다

이것이 이 문서에서 가장 중요한 사실이고, 표를 읽는 방법을 정한다.

```text
설계 스택 (문서가 가리키는 곳)              운영 스택 (실제로 도는 곳)
control_tower/fleet_manager/*               fms_gateway/app/repositories.py   (7천 줄)
control_tower/task_manager/lifecycle.py     fms_gateway/app/main.py           (REST)
                    /stage_engine.py        control_tower/task_manager/job_runner.py
                    /omx_workflow.py                            /executor_worker.py
                    /handover_gate.py                           /assignment.py
                    /task_orchestrator.py   control_tower/rmf_adapter/rmf_gateway_worker.py
control_tower/gateway/http_server.py        trihouse_rmf_bridge/... (fleet adapter)
                     /authorization.py      trihouse_pinky/* (로봇 온보드)
control_tower/database/repositories/*
```

**왼쪽은 구현·테스트가 다 있는데 런타임 import 그래프에 없다.** 오른쪽이 실제로 돈다.

그래서 표의 **"안 돈다 ❌" 는 "기능이 없다" 가 아니다.** 대부분은 같은 기능이
Gateway 안에 다시 구현돼 있다. 실측으로 확인한 것:

| 기능 | `repositories.py` 안의 흔적 | 라이브 API |
|---|---|---|
| 재고 예약 (`reserved_qty`) | 22 곳 | `POST /api/v1/orders` |
| 유통기한 FEFO (`expiry`) | 11 곳 | 〃 |
| 온도 구역 | 38 곳 | 〃 |
| 예약 (`reservation`) | 87 곳 | `POST /internal/v1/reservations/expire` |
| 인계 (`handover`) | 22 곳 | `POST /api/v1/jobs/{id}/worker-completion` |
| 취소 | 54 곳 | `POST /internal/v1/jobs/{id}/cancel` |
| 감사 (`operation_events`) | 44 곳 | `GET /api/v1/operation-events` |
| 권한 (`role`/`ADMIN`) | 80 곳 | — (REST 노출 없음) |
| 사건 (`incident`) | 58 곳 | `POST /api/v1/incidents/{id}/decision` — **생성 API 는 없다** |

> **읽는 법.** ❌ 를 만나면 두 가지를 물어야 한다.
> ① 같은 기능이 Gateway 에 있는가? ② 있다면 **거기로 이어지는 진입점이 있는가?**
> `incident` 가 좋은 예다 — 로직 58 곳, 승인 API 1 개, **그런데 사건을 만들 API 가 없다.**
> 그래서 감지해도 관제에 도달할 길이 없다.

### 확인 명령 두 개

```bash
curl -s http://127.0.0.1:8080/openapi.json | python3 -c "import json,sys;[print(' '.join(sorted(m.upper() for m in v)), k) for k,v in sorted(json.load(sys.stdin)['paths'].items())]"
```
```bash
grep -n "<찾는 기능 이름>" fms_gateway/app/repositories.py | head
```

---

## 1. 범례

| 표시 | 뜻 |
|---|---|
| **돈다** | 그 파일이 기동 진입점에서 import 로 닿는다 |
| **일부** | 여러 파일 중 일부만 닿는다 |
| **안 돈다** | 파일은 있는데 런타임 그래프에 없다 → **§0 의 두 질문을 한다** |
| **코드 없음** | 요구사항 문서가 "구현 없음" 이라고 적었다 |
| ✅ / ❌ | 그 파일 하나의 도달 여부 |

**무게(로드셀)는 요구사항에서 제외된 항목이므로 이 표에 없다.**

---

## 2. 기능별 목록

### A. 출고 경로 — 실물 테스트가 직접 밟는 것

| | SR | 우선 | 기능 | 상태 | 요구사항 문서가 가리키는 파일 |
|---|---|---|---|---|---|
| [ ] | **SR_39** | High | 주문 접수 기능 | **안 돈다** | control_tower/fleet_manager/order_intake.py ❌ |
| [ ] | **SR_40** | High | 유통기한 기반 출고 물품 선정 기능 | **안 돈다** | control_tower/fleet_manager/inventory_workflow.py ❌ |
| [ ] | **SR_07** | High | 작업 할당 기능 | **안 돈다** | control_tower/fleet_manager/dispatch_workflow.py ❌<br>trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/eta.py ❌ |
| [ ] | **SR_29** | High | 작업 단계 통합 관리 기능 | **안 돈다** | control_tower/task_manager/stage_engine.py ❌ |
| [ ] | **SR_28** | High | 로봇 준비상태 동기화 기능 | **안 돈다** | control_tower/task_manager/handover_gate.py ❌ |
| [ ] | **SR_24** | High | 물품 운반 기능 | **돈다** | trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py ✅<br>trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/arrival.py ✅ |
| [ ] | **SR_48** | High | 포장대·작업자 전달 위치 운반 기능 | **돈다** | trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py ✅ |
| [ ] | **SR_46** | High | Pinky 물품 적재 기능 | **안 돈다** | control_tower/task_manager/omx_workflow.py ❌ |
| [ ] | **SR_47** | High | 적재 인수인계 확인 기능 | **안 돈다** | control_tower/gateway/omx_protocol.py ❌ |
| [ ] | **SR_11** | High | 물품 파지 기능 | **안 돈다** | control_tower/task_manager/omx_workflow.py ❌<br>control_tower/gateway/omx_protocol.py ❌ |
| [ ] | **SR_13** | High | 파지 실패 재시도 기능 | **안 돈다** | control_tower/task_manager/omx_workflow.py ❌ |
| [ ] | **SR_15** | High | 다중 물품 임시 적재 기능 | **안 돈다** | control_tower/task_manager/omx_workflow.py ❌ |
| [ ] | **SR_17** | High | 물품 정보 일치 확인 기능 | **안 돈다** | model/worker/marker/policy.py ❌ |
| [ ] | **SR_18** | High | 선반·슬롯 위치 확인 기능 | **안 돈다** | model/worker/marker/policy.py ❌ |
| [ ] | **SR_50** | High | 전달 완료 입력·기록 기능 | **안 돈다** | control_tower/task_manager/outbound_result.py ❌ |
| [ ] | **SR_51** | High | 출고 결과 확정 기능 | **안 돈다** | control_tower/fleet_manager/inventory_workflow.py ❌ |
| [ ] | **SR_06** | High | 작업 완료 후 원본 DB 반영 기능 | **안 돈다** | control_tower/fleet_manager/inventory_workflow.py ❌ |
| [ ] | **SR_25** | High | 대기·충전소 복귀 기능 | **일부** | control_tower/fleet_manager/battery_policy.py ❌<br>trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/workflow.py ✅ |
| [ ] | **SR_49** | Medium | 포장 준비완료 표시 기능 | **일부** | trihouse_pinky/trihouse_pinky_io/trihouse_pinky_io/destination_display.py ✅<br>trihouse_pinky/trihouse_pinky_io/trihouse_pinky_io/indicator.py ❌ |

### B. 안전 — 사람 옆에서 돌기 전에

| | SR | 우선 | 기능 | 상태 | 요구사항 문서가 가리키는 파일 |
|---|---|---|---|---|---|
| [ ] | **SR_23** | High | 사람 충돌 방지 주행 기능 | **일부** | trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/safety_supervisor_node.py ✅<br>trihouse_omx_adapter/trihouse_omx_adapter/policy.py ❌ |
| [ ] | **SR_16** | High | 로봇팔 사람 충돌 방지 기능 | **안 돈다** | control_tower/task_manager/omx_workflow.py ❌ |
| [ ] | **SR_19** | High | 로봇팔 작업영역 사람 감지 기능 | **안 돈다** | model/worker/person/policy.py ❌ |
| [ ] | **SR_20** | High | Pinky 주행경로 사람 감지 기능 | **안 돈다** | model/worker/person/policy.py ❌ |
| [ ] | **SR_09** | High | 공유 작업공간·경로 예약 기능 | **안 돈다** | control_tower/rmf_adapter/traffic_reservation.py ❌ |
| [ ] | **SR_27** | Medium | 배터리 기반 작업 제한 기능 | **안 돈다** | control_tower/fleet_manager/battery_policy.py ❌ |
| [ ] | **SR_03** | High | 로봇 상태 공유 기능 | **일부** | trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/status_node.py ✅<br>control_tower/gateway/omx_status.py ❌<br>trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/gateway_node.py ✅<br>trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/status.py ✅ |

### C. 관제·기록

| | SR | 우선 | 기능 | 상태 | 요구사항 문서가 가리키는 파일 |
|---|---|---|---|---|---|
| [ ] | **SR_01** | High | 통합 관제 화면 기능 | **안 돈다** | control_tower/gateway/http_server.py ❌<br>control_tower/gateway/operations_feed.py ❌ |
| [ ] | **SR_02** | High | 관리자 개입 기능 | **안 돈다** | control_tower/task_manager/lifecycle.py ❌<br>control_tower/gateway/authorization.py ❌<br>control_tower/database/repositories/audit_repository.py ❌ |
| [ ] | **SR_04** | High | 작업·비상 이력 및 영상 기록 기능 | **안 돈다** | model/worker/media/recording/recorder.py ❌<br>control_tower/task_manager/pick_failure_report.py ❌<br>model/worker/media/recording/catalog.py ❌ |
| [ ] | **SR_53** | High | 사람 위급상황 알림 기능 | **안 돈다** | control_tower/gateway/operations_feed.py ❌ |
| [ ] | **SR_21** | High | 최종 파지 실패 보고 기능 | **안 돈다** | control_tower/task_manager/pick_failure_report.py ❌ |

### D. 다중 로봇·포장대

| | SR | 우선 | 기능 | 상태 | 요구사항 문서가 가리키는 파일 |
|---|---|---|---|---|---|
| [ ] | **SR_43** | Medium | 포장대 사용 상태 관리 기능 | **돈다** | control_tower/fleet_manager/packing_station.py ✅ |
| [ ] | **SR_44** | Medium | 포장대 작업자 부재 감지 기능 | **안 돈다** | model/worker/person/policy.py ❌ |
| [ ] | **SR_45** | Medium | 포장대 대기·재배정 기능 | **돈다** | control_tower/fleet_manager/packing_station.py ✅ |
| [ ] | **SR_08** | Medium | 작업 재할당 기능 | **안 돈다** | control_tower/fleet_manager/dispatch_workflow.py ❌ |
| [ ] | **SR_41** | Medium | 긴급 주문 우선 처리 기능 | **안 돈다** | control_tower/fleet_manager/dispatch_workflow.py ❌ |

### E. 비상 (작업자 쓰러짐)

| | SR | 우선 | 기능 | 상태 | 요구사항 문서가 가리키는 파일 |
|---|---|---|---|---|---|
| [ ] | **SR_52** | High | 사람 위급상황 감지 기능 | **코드 없음** | - |
| [ ] | **SR_54** | High | 비상 대응 구역·로봇 동작 제어 기능 | **안 돈다** | control_tower/task_manager/emergency_workflow.py ❌ |
| [ ] | **SR_55** | High | 비상 영향 작업 보류·재할당 기능 | **안 돈다** | control_tower/task_manager/lifecycle.py ❌ |
| [ ] | **SR_56** | High | 비상 대응 해제 승인 기능 | **안 돈다** | control_tower/gateway/authorization.py ❌ |
| [ ] | **SR_57** | High | 비상 해제 후 복귀·재투입 기능 | **돈다** | trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/recovery_health.py ✅ |

### F. 입고

| | SR | 우선 | 기능 | 상태 | 요구사항 문서가 가리키는 파일 |
|---|---|---|---|---|---|
| [ ] | **SR_34** | High | QR 보관 방법 기반 구역 결정 기능 | **안 돈다** | control_tower/fleet_manager/storage_assignment.py ❌ |
| [ ] | **SR_35** | High | 입고 선반·슬롯 배정 기능 | **안 돈다** | control_tower/fleet_manager/inventory_workflow.py ❌ |
| [ ] | **SR_37** | High | 지정 선반 적재 기능 | **안 돈다** | control_tower/task_manager/omx_workflow.py ❌ |
| [ ] | **SR_38** | High | 입고 위치·재고 갱신 기능 | **안 돈다** | control_tower/fleet_manager/inventory_workflow.py ❌ |
| [ ] | **SR_14** | High | 바구니 위치·자세 보정 기능 | **안 돈다** | model/worker/object/basket_correction.py ❌ |

### G. 저우선순위 · 미구현

| | SR | 우선 | 기능 | 상태 | 요구사항 문서가 가리키는 파일 |
|---|---|---|---|---|---|
| [ ] | **SR_05** | High | 저조도 데이터 증강 기반 인식 기능 | **안 돈다** | model/perception/dataset/augmentation/generate_augmentation_candidates.py ❌<br>model/perception/segmentation/training/dataset_policy.py ❌ |
| [ ] | **SR_10** | Low | 다량 물품 작업 분할 기능 | **코드 없음** | - |
| [ ] | **SR_12** | Low | 공통 물품 위치·존재 인식 기능 | **코드 없음** | - |
| [ ] | **SR_22** | Low | 미끄럼 감지·주행 보정 기능 | **코드 없음** | - |
| [ ] | **SR_26** | Low | 주행 예외 복구 기능 | **코드 없음** | - |
| [ ] | **SR_30** | Low | 통신 단절 안전정지·작업복구 기능 | **코드 없음** | - |
| [ ] | **SR_31** | Low | 입고 QR 인식 기능 | **코드 없음** | - |
| [ ] | **SR_32** | Low | 입고 물품 정보 자동 등록 기능 | **코드 없음** | - |
| [ ] | **SR_33** | Low | 입고 정보 검수 기능 | **코드 없음** | - |
| [ ] | **SR_36** | Low | 입고 전처리 자동화 기능 | **코드 없음** | - |
| [ ] | **SR_42** | Low | 작업자 요청 우선 처리 기능 | **코드 없음** | - |

---

## 3. 실물 테스트 관점 — 먼저 볼 다섯

전부 훑기 전에, **출고 3회 완주를 직접 막는 것**만 고르면 이 다섯이다.

| # | 무엇 | 왜 지금 |
|---|---|---|
| 1 | **SR_24 · SR_48 (운반)** — 유일하게 온전히 "돈다" | 여기가 무너지면 나머지는 볼 필요가 없다. 지금 협로에서 취소된다 |
| 2 | **SR_23 (사람 충돌 방지 주행)** — `safety_supervisor` | 실기 launch 에서 gate 가 모터 경로 밖에 있다 |
| 3 | **SR_28 (준비상태 동기화)** — `handover_gate.py` ❌ | 운영 스택은 `job_runner` 가 대신한다. **같은 판정인지 확인 필요** |
| 4 | **SR_50 · SR_51 (전달 완료·출고 확정)** | `worker-completion` API 는 살아 있다. step 60→70 이 그것으로 닫힌다 |
| 5 | **SR_09 (공유 작업공간·경로 예약)** — `traffic_reservation.py` ❌ | 2대 운용의 통로 경합. **Open-RMF `mutex` 로 대체 가능**(키 이름 한 단어) |

## 4. 이 표로 무엇을 판단하면 안 되는가

- **"돈다" 가 "맞게 돈다" 는 아니다.** import 로 닿는다는 것뿐이다. 동작은 실행해서 봐야 한다.
- **"안 돈다" 가 "기능이 없다" 는 아니다.** §0.
- **로봇 온보드는 launch 인자에 달려 있다.** `vision_enabled:=false` 면 카메라 노드는
  import 로는 닿아도 뜨지 않는다. 실제 기동 여부는 `ros2 topic list` 로 본다.
- **`control_system/`, `pinky_pro/` 는 도달 계산에서 뺐다.** 보호 경로이고 우리가 고치지 않는다.

## 5. 다시 만드는 법

기능을 옮기거나 배선을 바꾼 뒤 이 표를 갱신하려면, 기동 진입점 24 개에서 import 를
따라가는 계산을 다시 돌린다. 진입점 목록은 아래에서 나온다.

```bash
grep -ohE "executable='[a-z_]+'|executable=\"[a-z_]+\"" trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_pinky.launch.py trihouse_rmf_bridge/launch/two_pinky_order_demo.launch.py | sort -u
```
```bash
for f in $(find . -name setup.py -not -path "./build/*" -not -path "./install/*" -not -path "./pinky_pro/*" -not -path "./control_system/*"); do grep -oE "'[a-z_]+ = [a-z_]+\.[a-z_]+:main'" $f; done
```

거기에 Docker 로 뜨는 `fms_gateway/app/main.py` 와 bringup 이 `python3 -m` 으로 띄우는
셋(`job_runner_node` · `executor_worker_node` · `rmf_gateway_worker_node`)을 더한 것이
진입점 전부다.

---

관련 문서
- 실물 준비 공백: [2026-08-20-hardware-readiness-gaps.md](../claude/2026-08-20-hardware-readiness-gaps.md)
- 실행 절차: [p0-hardware-quick-run.md](../runbooks/p0-hardware-quick-run.md)
- 협로 ↔ RMF: [narrow-zone-rmf-integration-design.md](../architecture/narrow-zone-rmf-integration-design.md)
- 요구사항 정본: [system_requirements.md](../requirements/system_requirements.md)

---

## 2-A. 출고 경로 — "안 돈다" 의 실제 대응 (실측)

group A 의 ❌ 는 대부분 **Gateway 로 옮겨간 것**이다. 어디로 갔는지 짚어 둔다.
**이 열이 비어 있는 행이 진짜 공백이다.**

| SR | 문서가 가리키는 곳 ❌ | **실제로 도는 곳** | 확인 |
|---|---|---|---|
| SR_39 주문 접수 | `fleet_manager/order_intake.py` | `fms_gateway/app/main.py` → `repositories.create_outbound_order` | `POST /api/v1/orders` 살아 있음 |
| SR_40 FEFO | `fleet_manager/inventory_workflow.py` | `repositories.py:2795` `ORDER BY lot.expiry_date, lot.lot_id` | 주문 시 자동 |
| SR_07 작업 할당 | `fleet_manager/dispatch_workflow.py` · `eta.py` | `task_manager/job_runner.py` + `assignment.py` | **first-fit 이다. ETA 최소화는 없다** |
| SR_29 단계 관리 | `task_manager/stage_engine.py` | `job_runner.py` `current_step()` + `job_steps` 테이블 | `GET /api/v1/jobs/{id}/timeline` |
| SR_28 준비상태 동기화 | `task_manager/handover_gate.py` | `status.py` → `dispatchable` → fleet adapter | **판정 기준이 같은지 미확인** |
| SR_11·13·15·46 OMX | `task_manager/omx_workflow.py` | `executor_worker.py` + `trihouse_omx_adapter/*` | **`OmxSimulator` 프로토콜 왕복만. 실제 motion 없음** |
| SR_47 인수인계 확인 | `gateway/omx_protocol.py` | `executor_worker.py:225` `handover_group_id`/`pinky_id`/`omx_id` | 〃 |
| SR_17·18 QR·ArUco | `model/worker/marker/policy.py` | `model/worker/marker/edge_perception.py` (4060 워커) | **워커가 기동 진입점에 없다 — 진짜 공백** |
| SR_50 전달 완료 | `task_manager/outbound_result.py` | `main.py:924` `POST /api/v1/jobs/{id}/worker-completion` | 살아 있음 |
| SR_51 출고 확정 | `fleet_manager/inventory_workflow.py` | `repositories.py` (`reserved_qty` 22 곳) | **취소가 예약을 안 돌려준다(D2)** |
| SR_06 DB 반영 | 〃 | 〃 | 〃 |
| SR_25 복귀 | `fleet_manager/battery_policy.py` ❌ | 로봇 `workflow.py` ✅ + step 70 `return_home` | 관제쪽 배터리 정책은 안 돈다 |

**진짜 공백 셋** — 위 표에서 "실제로 도는 곳" 이 없거나 대체가 프로토콜 왕복뿐인 것.

1. **SR_17·18 (QR·ArUco 확인)** — `model.worker.marker` 워커를 띄우는 진입점이 어디에도 없다.
   물품이 맞는지 **아무도 확인하지 않고** 출고가 진행된다.
2. **SR_11·13·15·46·47 (OMX)** — 프로토콜만 오간다. 실제 파지는 없다(결정됨: 이번엔 제외).
3. **SR_07 (시간 효율 할당)** — first-fit. 2대가 되면 "스케줄링" 이라 부를 것이 없다.
