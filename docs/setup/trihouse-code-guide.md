# Trihouse 코드 사용·수정 안내

이 문서는 현재 구현된 **정적 정책 코드**를 이해하고 바꾸는 출발점이다. 실제 Pinky, OMX,
Open-RMF, 카메라, GPU가 연결됐다는 뜻은 아니다. 요구사항별 정적/런타임 근거는
`docs/scenario/system-requirements-implementation-map.md`를 함께 본다.

## 먼저 알아둘 책임 경계

```text
Control Tower: 주문, 작업 단계, 재고, 장소 예약, 비상 구역
Open-RMF: 전역 교통·통로 진입 순서
Pinky Nav2: 로컬 경로와 장애물 회피
Pinky Safety Supervisor: 최종 /cmd_vel 제한과 비상 정지
OMX/MoveIt adapter: 실제 로봇팔 궤적·그리퍼 실행
Vision: 사람/마커/바구니 관측 결과만 전달
```

Vision 또는 FMS 정책은 Pinky의 `/cmd_vel`을 직접 발행하지 않는다. OMX 정책은 장비가 실제
파지·후퇴했다고 가정하지 않고, adapter가 보고한 결과를 받아 다음 단계만 결정한다.

## EXPLAINCODE: 기능을 읽는 시작점과 흐름

새 기능을 추가할 때는 다음 순서를 따른다.

1. 이 표의 **시작 파일**에서 입력·출력·권한 경계를 읽는다.
2. 연결된 **정책/상태 파일**에서 상태 전이와 금지 조건을 읽는다.
3. **테스트 파일**에서 정상·실패·중복 입력이 어떤 결과여야 하는지 확인한다.
4. 코드를 바꿀 때는 왜 이 경계가 필요한지, 실제 장비에서 아직 검증되지 않은 것은 무엇인지
   한국어 주석 또는 docstring으로 남긴다.

| 기능 | 시작 파일 | 다음 정책/상태 파일 | 자동 테스트 |
| --- | --- | --- | --- |
| Pinky 최종 안전 속도 | `trihouse_pinky_safety/safety_supervisor_node.py` | `policy.py`, `geometry.py` | `trihouse_pinky/test/test_pinky_sr_policies.py` |
| Pinky 운반·인계·복귀 | `trihouse_pinky_fleet/fleet_node.py` | `workflow.py`, `arrival.py`, `recovery_health.py` | `trihouse_pinky/test/test_pinky_sr_policies.py` |
| Pinky↔FMS TCP | `trihouse_pinky_fleet/gateway_node.py` | `protocol.py`, `ndjson_client.py`, `status_node.py` | `trihouse_pinky/test/test_pinky_sr_policies.py` |
| 입고·출고 재고 | `control_tower/fleet_manager/inventory_workflow.py` | `order_intake.py`, `outbound_result.py` | `test_inventory_workflow.py`, `test_order_intake.py`, `test_outbound_result.py` |
| 배차·교통·배터리 | `control_tower/fleet_manager/dispatch_workflow.py` | `battery_policy.py`, `rmf_adapter/traffic_reservation.py` | `test_dispatch_workflow.py`, `test_battery_policy.py`, `test_traffic_reservation.py` |
| OMX 작업 | `control_tower/task_manager/omx_workflow.py` | `gateway/omx_protocol.py`, `handover_gate.py`, `stage_engine.py` | `test_omx_workflow.py`, `test_omx_protocol.py` |
| 비상·관리자 승인 | `control_tower/task_manager/emergency_workflow.py` | `lifecycle.py`, `gateway/authorization.py`, `audit_repository.py` | `test_emergency_workflow.py`, `test_authorization.py`, `test_audit_repository.py` |
| 마커·바구니·ROI 사람 감지 | `vision_system/marker_worker/policy.py` | `object_worker/basket_correction.py`, `person_worker/policy.py` | `test_marker_policy.py`, `test_basket_correction.py`, 명시 ROI 테스트 2개 |
| H.264 녹화·보존 | `vision_system/recording_server/recorder.py` | `catalog.py` | `test_recorder.py`, `test_recording_catalog.py` |
| 독립 Trihouse 관제 UI | `control_tower/ui/operations/index.html` | `operations.js → gateway/http_server.py → operations_feed.py` | `test_operations_http_server.py` |

SR_52 쓰러짐 감지는 이 표의 구현 흐름에 넣지 않는다. 시작점과 승인 전 단계는
`docs/scenario/sr52-fall-detection-research-plan.md`의 조사 계획을 따른다.

## Pinky를 조정할 때

| 바꾸려는 것 | 주 파일 | 테스트 |
| --- | --- | --- |
| 사람·거리·비상 시 속도 제한 | `trihouse_pinky_safety/.../policy.py` | `trihouse_pinky/test/test_pinky_sr_policies.py` |
| FMS 운반/복귀 상태 | `trihouse_pinky_fleet/.../workflow.py` | 같은 테스트의 `TransportWorkflowTest` |
| ETA·OMX 사전 파지 시각 | `trihouse_pinky_fleet/.../eta.py` | `trihouse_pinky/test/test_eta_policy.py` |
| 배터리 복귀 판단 | `control_tower/fleet_manager/battery_policy.py` | `control_tower/tests/test_battery_policy.py` |
| 목적지 LCD/LED/부저 | `trihouse_pinky_io/...` | `trihouse_pinky/test/test_pinky_sr_policies.py` |

`front_stop`, `front_slow`, 센서 timeout, 실효 속도, 배터리 소비계수는 초기 정책값이다. 실물
Pinky의 제동거리·통로·배터리 로그를 측정한 뒤 한 항목씩 바꾸고 대응 테스트도 함께 바꾼다.

## Control Tower를 조정할 때

| 목적 | 파일 |
| --- | --- |
| 입고/출고 원본 재고와 FEFO | `fleet_manager/inventory_workflow.py` |
| Pinky 배차·공간 예약 | `fleet_manager/dispatch_workflow.py` |
| 포장대 상태·작업자 기반 선택 | `fleet_manager/packing_station.py` |
| 작업 단계·보류·재개 | `task_manager/stage_engine.py`, `lifecycle.py` |
| Pinky/OMX 공동 준비 | `task_manager/handover_gate.py` |
| OMX 재시도·임시 슬롯·인계 | `task_manager/omx_workflow.py` |
| 좁은 통로 시간대 | `rmf_adapter/traffic_reservation.py` |
| 비상 구역·복귀 결정 | `task_manager/emergency_workflow.py` |

입고/출고 전체 흐름을 바꾸기 전에는 각각 `test_inbound_happy_path.py`,
`test_outbound_happy_path.py`를 읽는다. 재고 변경은 `finalize_inbound()` 또는
`finalize_outbound()`에서만 허용한다.

## Vision을 조정할 때

- 실제 저조도 증강 recipe는 `vision_perception/augmentation/generate_augmentation_candidates.py`에 있다.
  `vision_system/training/dataset_policy.py`는 이를 중복 구현하지 않고, 학습 전용 적용과 검증
  세트 분리를 지킨다.
- QR·ArUco 검증은 `vision_system/marker_worker/policy.py`, 바구니 잔여 정차 오차 보정은
  `vision_system/object_worker/basket_correction.py`에 있다.
- 영상 보존·증거 구간 선택은 `vision_system/recording_server/catalog.py`에 있고,
  `recorder.py`는 RTSP H.264를 60초 segment로 쓰는 FFmpeg 명령과 process lifecycle을 맡는다.
  실제 FFmpeg, file watcher, storage 삭제 권한은 서버 런타임에서 확인해야 한다.
- 사람 쓰러짐 감지(SR_52)는 기술 조사·데이터·수용 기준을 정하기 전까지 계획 단계다. 이 문서의
  현재 코드/테스트를 최종 쓰러짐 감지 구현으로 사용하지 않는다.

## 정적 정책 테스트

현재 macOS 개발 환경에는 ROS 2 Jazzy와 OMX 하드웨어가 없으므로 아래 검증은 장비 없는 정책
테스트다.

```bash
cd /Users/wonsiyeon/Documents/Codex/Trihouse
PYTHONPATH='trihouse_pinky/trihouse_pinky_fleet:trihouse_pinky/trihouse_pinky_safety:trihouse_pinky/trihouse_pinky_io:trihouse_pinky/trihouse_pinky_bringup' \
python3 -m unittest -q \
  trihouse_pinky.test.test_pinky_sr_policies \
  trihouse_pinky.test.test_eta_policy \
  control_tower.tests.test_operations_feed \
  control_tower.tests.test_operations_http_server \
  control_tower.tests.test_authorization \
  control_tower.tests.test_omx_protocol \
  control_tower.tests.test_omx_status \
  control_tower.tests.test_outbound_happy_path \
  control_tower.tests.test_inbound_happy_path \
  control_tower.tests.test_inventory_workflow \
  control_tower.tests.test_dispatch_workflow \
  control_tower.tests.test_storage_assignment \
  control_tower.tests.test_packing_station_policy \
  control_tower.tests.test_traffic_reservation \
  control_tower.tests.test_battery_policy \
  control_tower.tests.test_task_lifecycle \
  control_tower.tests.test_stage_engine \
  control_tower.tests.test_pick_failure_report \
  control_tower.tests.test_outbound_result \
  control_tower.tests.test_handover_gate \
  control_tower.tests.test_emergency_workflow \
  control_tower.tests.test_omx_workflow \
  control_tower.tests.test_audit_repository \
  control_tower.tests.test_order_intake \
  vision_system.tests.test_person_policy.PersonPolicyTest.test_roi_requires_consecutive_person_frames \
  vision_system.tests.test_person_policy.PersonPolicyTest.test_person_outside_roi_does_not_count_as_worker_presence \
  vision_system.tests.test_marker_policy \
  vision_system.tests.test_basket_correction \
  vision_system.tests.test_dataset_policy \
  vision_system.tests.test_recording_catalog \
  vision_system.tests.test_recorder
python3 -m compileall -q control_tower trihouse_pinky vision_system
git diff --check
```

기대 결과는 `OK`와 모든 테스트 통과다. 위 목록은 SR_52 쓰러짐 감지 테스트를 의도적으로
포함하지 않는다. 명령이 loopback HTTP 서버를 시작하므로, sandbox 환경에서는 포트 bind 권한이
필요할 수 있다.

## 실물 연동 전 확인 순서

1. ROS action, topic, message type을 실제 장비에서 확인한다. 기대 결과는 required interface가
   모두 준비 상태이고, Pinky `RobotStatus.ready=true`가 되는 것이다.
2. Pinky safety를 단독 실행해 `/cmd_vel` 발행자가 하나인지 확인한다. 전방 거리/센서 timeout에서
   최종 속도가 0이 되고 Nav2의 목적지는 취소되지 않아야 한다.
3. OMX adapter가 `omx_protocol.py`의 command/result ID를 보존하는지 확인한다. 중복 result는 다음
   단계가 두 번 진행되지 않고, 잘못된 job/step ID는 거부되어야 한다.
4. H.264 recorder가 카메라별 60초 파일을 만들고 `RecordingCatalog`에 시작/완료를 알리는지 확인한다.
   재생 중/기록 중인 파일은 저장 한도 초과에도 삭제되지 않아야 한다.
5. Gazebo 또는 실물에서 입고·출고 한 건씩 수행하고, 정적 통합 테스트와 실제 로그를 비교한다.
   원본 재고는 OMX 적재 완료 또는 작업자 전달 완료 전까지 변하지 않아야 한다.
6. RoboSapiens 관제 UI는 읽기 전용으로 유지한다. 실제 UI 연동 전에는
   `docs/setup/robosapiens-control-ui-integration.md`의 adapter/독립 배포 결정을 먼저 확정한다.
