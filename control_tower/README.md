# control_tower

Trihouse 중앙 관제 서버의 역할별 모듈 루트다. Pinky와는 TCP 8788 NDJSON으로,
운영 UI와는 REST/WebSocket으로 통신한다. 각 Pinky ROS Domain에 직접 업무 로직을
배포하지 않는다.

| 폴더 | 책임 |
|---|---|
| `gateway/` | robot session, heartbeat, ACK, NDJSON↔내부 event 변환 |
| `task_manager/` | 작업 단계·취소·인계·incident workflow |
| `fleet_manager/` | 배차·로봇 상태·배터리·충전소 정책 |
| `rmf_adapter/` | Open-RMF task/traffic 연동 |
| `database/` | migration과 repository |
| `monitoring/` | health, metrics, audit, alert, report |
| `ui/` | operations, RMF diagnostics, map authoring |
| `tests/` | gateway·workflow·다중 로봇 통합 시험 |

`gateway/operations_feed.py`는 SR_01/53 UI용 read model 계약이다. REST/WebSocket 어댑터는
`OperationsSnapshot`과 우선순위가 매겨진 `OperationsEvent`만 직렬화한다. UI가 DB, RMF,
ROS를 직접 읽지 않으며, `INCIDENT_OPEN` 이벤트는 보통 로봇·작업 업데이트보다 먼저 전달된다.
`gateway/http_server.py`는 `GET /api/v1/operations`, `GET /api/v1/events`의 표준 라이브러리
REST 어댑터다. `GET /api/v1/events/ws`는 WebSocket upgrade 뒤 한 번의 event payload를 push한다.
인증·지속 연결·다중 구독 fan-out은 실제 운영 배포 전 추가한다.
`ui/operations/index.html`과 `operations.js`는 RoboSapiens 원본을 수정하지 않고 별도로 배포하는
Trihouse 운영 화면이다. Gateway snapshot/event만 읽으며 DB·RMF·ROS에 직접 접근하지 않는다.
카메라 재생 URL은 사용자가 camera를 선택할 때만 `/api/v1/cameras/<camera_id>/playback`에서 조회하고,
이 화면은 녹화 process를 시작·중지하지 않는다.
`gateway/authorization.py`는 검증된 Gateway 사용자 역할의 권한 판단을 맡는다. `ADMIN`만
`RELEASE_EMERGENCY`, `EDIT_KEEP_OUT_ZONE`을 수행할 수 있고 `OPERATOR`는 인지·작업 취소·재할당만
요청할 수 있다. 실제 JWT/SSO 검증은 HTTP adapter 앞단의 별도 배포 책임이다.

`gateway/omx_protocol.py`는 SR_11/47의 Control Tower↔OMX NDJSON 형식이다. `omx_pick`,
`omx_place_shelf`, `omx_load_pinky`에는 message/job/step/order/item/shelf/slot ID가 모두 필요하다.
`omx_result`는 원래 command ID와 job/step이 일치하고 새 message ID일 때만 다음 단계 엔진에 전달한다.
`gateway/omx_status.py`는 SR_03 OMX 상태 heartbeat 정책이다. adapter는 준비·동작·파지·적재·안전·오류를
담은 `OmxStatus`가 1초 경과 또는 상태 변경으로 `should_publish()`를 통과할 때 FMS로 전송한다.

`tests/test_outbound_happy_path.py`는 SR_06/07/28/29/40/43/46/47/50/51의 정적 출고 통합
시나리오다. FEFO 예약부터 Pinky 배차·공동 준비·OMX 인계·포장대 도착·최종 재고 차감까지를
외부 장비 없이 한 번에 검증한다.

`tests/test_inbound_happy_path.py`는 SR_06/28/29/34/35/37/38의 정적 입고 통합 시나리오다.
QR 보관 코드의 zone 결정부터 슬롯 예약, 공동 준비, OMX 선반 적재 완료, 최종 재고 생성까지를
검증한다.

## 현재 구현 시작점

`fleet_manager/inventory_workflow.py`는 UI·ROS·DB에 독립적인 SR_06/34/35/38/39/40/51
재고 도메인이다. 중간 파지·적재·운반 단계는 원본 수량을 바꾸지 않고, OMX 적재 완료 또는
작업자 전달 완료에서만 한 번 반영한다. 실행 방법은 다음과 같다.

`fleet_manager/order_intake.py`는 SR_39의 주문 접수 경계다. 재고 snapshot으로 전량 또는
허용된 부분 수량만 확정하고, 전량 주문에 부족분이 있거나 부분 출고에도 확정 물품이 없으면
작업을 만들지 않고 취소한다. 이 모듈은 재고를 차감·예약하지 않는다. 확정 결과만
`inventory_workflow.reserve_outbound()`로 전달해 실제 lot 예약을 수행한다.

`fleet_manager/dispatch_workflow.py`는 SR_07/08/09/41/43의 단일 Pinky 배정, 작업
공간 예약, 우선순위 대기열, 안전한 재배정을 맡는다. `task_manager/lifecycle.py`는
SR_02/55/56의 관리자 확인·멱등 요청·비상 보류를 맡는다. 둘 다 ROS action이나 DB 저장소를
직접 호출하지 않는 순수 도메인 계층이므로, gateway가 반환 상태를 저장하고 이벤트로 발행한다.

`fleet_manager/battery_policy.py`는 Pinky SR의 SR_25 복귀 판단이다. 현재 작업·충전소
복귀 거리 각각에 실험으로 보정한 소비량과 여유를 더해 `CONTINUE`, `COMPLETE_THEN_RETURN`,
`HOLD_CURRENT_AND_RETURN`, `IMMEDIATE_RETURN` 중 하나를 반환한다. 임계값과 소비계수는
Pinky 실주행 측정 후 설정값으로 확정해야 한다. SR_27용 `status()`는 `NORMAL`,
`WORK_LIMITED`, `RETURN_REQUIRED`을 제공하며 `can_accept_new_job()`은 작업 거리와 복귀
여유를 모두 만족할 때만 새 배차를 허용한다.

`fleet_manager/packing_station.py`는 SR_43~45의 포장대 상태와 선택 정책이다. Vision의
작업자 ROI 결과는 `worker_present` 입력일 뿐 예약을 직접 바꾸지 않는다. FMS는 예약→도착 시
사용 중→인계/취소 시 해제를 관리하고, 작업자가 없으면 사용 가능한 다른 포장대로 옮기거나 대기
노드에서 작업자 배치를 기다린다.

`fleet_manager/storage_assignment.py`는 SR_34 입고 구역 결정이다. QR의 사전 등록 보관
코드만 zone으로 변환하며, 누락·허용 외 값은 다른 상품 속성으로 추론하지 않고 `INBOUND_HOLD`로
반환한다. `inventory_workflow.reserve_inbound_slot()`은 이 결과가 `ZONE_ASSIGNED`인 경우에만 호출한다.

`rmf_adapter/traffic_reservation.py`는 SR_09의 좁은 통로 시간대 예약 정책이다. 실제 Open-RMF
API 호출 전에 단일 용량 resource의 겹치는 진입을 지연시키고, 지연된 Pinky에는 등록된 대기 노드를
반환한다. 우선순위는 신규 배치 순서에만 적용하며 이미 예약된 이동을 선점하지 않는다.

`task_manager/omx_workflow.py`는 SR_11/13/15/16/37/46/47의 장비 독립 OMX 단계 정책이다.
실제 OMX/MoveIt adapter는 `QR·ArUco 승인 → pick offset → 결과`를 보고하고, 이 정책은
재인식·등록된 보정좌표 재시도·임시 슬롯 예약·사람 정지·인계 완료 여부를 결정한다. 이 경계를
두면 확인되지 않은 OMX ROS 토픽이나 실제 로봇 동작을 추측하지 않아도 된다.

`database/repositories/audit_repository.py`는 SR_04/50/51/53/56의 이력 기반이다.
작업 단계·운영자 개입은 `task_audit_events`에 저장하고, `request_id`는 unique라서
REST/WebSocket 재전송이 같은 취소·재할당 기록을 중복 생성하지 않는다. 사람 위급상황은
`incidents`에 열고, 식별된 운영자의 승인이 있어야만 `RELEASED`로 변경한다.

`task_manager/emergency_workflow.py`는 SR_54~57의 FMS 판단을 분리한다. 비상 polygon 안
목표의 새 배정만 막고, 즉시 정지는 Pinky Safety Supervisor가 담당한다. 운영자 해제 뒤에도
영향 Pinky는 원래 작업을 재개하지 않는다. 빈 바구니는 `RETURN_AND_HEALTH_CHECK`, 화물이
남은 경우는 `ADMIN_INTERVENTION_REQUIRED` 결과를 gateway/RMF adapter에 전달한다.

`task_manager/handover_gate.py`는 SR_28의 Pinky·OMX 공동 준비 확인이다. 같은 작업에
등록된 두 로봇의 readiness가 모두 일치해야 적재·하차 단계를 시작할 수 있다. 취소 또는
Pinky 재배정은 기존 readiness를 폐기한다.

`task_manager/stage_engine.py`는 SR_29의 순서 있는 작업 단계 엔진이다. 현재 작업·단계와
일치하는 완료 결과 ID만 한 번 받아 다음 단계로 전진한다. 보류 후 재개는 완료된 단계를 반복하지
않으며, terminal handover를 받아야만 작업 전체를 완료로 표시한다.

`task_manager/pick_failure_report.py`는 SR_21 최종 파지 실패 보고 형식이다. 실패한
물품·선반·OMX·마지막 결과와 같은 시각의 `recordings/<camera>/<minute>.h264`를 함께
반환한다. 기본값은 실패 물품만 `ITEM_HELD_CONTINUE_OTHERS`로 보류한다.

`task_manager/outbound_result.py`는 SR_50/51의 작업자 전달 완료 입력 검증이다. 모든 예상
물품을 전달됨 또는 보류됨으로 정확히 한 번 분류해야 주문 결과를 `COMPLETED`,
`PARTIALLY_COMPLETED`, `FAILED`로 확정한다. 이 결과에서 전달된 물품만
`inventory_workflow.finalize_outbound()`에 전달한다.

```bash
cd /Users/wonsiyeon/Documents/Codex/Trihouse
python3 -m unittest -v \
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
  control_tower.tests.test_order_intake
```
