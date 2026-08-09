# System Requirements 구현·검증 지도

기준 문서: `System Requirements.md`의 Low 제외 항목이다. `정적 정책 완료`는 이 저장소에서
입력·상태 전이·불변식을 자동 테스트했다는 뜻이다. ROS/Jazzy, Open-RMF, OMX, 카메라, GPU,
H.264 recorder, 실제 REST/WebSocket 서버가 필요한 항목은 별도 런타임 검증 전에는 완료로
표시하지 않는다.

| SR | 현재 코드·테스트 | 현재 증거 | 다음 런타임/통합 검증 |
| --- | --- | --- | --- |
| 01 | `gateway/operations_feed.py`, `gateway/http_server.py`, `control_tower/ui/operations/`; 읽기 전용 `control_system/robo_control` | 별도 Trihouse UI의 Gateway-only snapshot/event·선택형 camera playback URL 테스트 | 인증·지속 WebSocket fan-out·실제 camera URL 권한·운영 배포 |
| 02 | `task_manager/lifecycle.py` | 확인·멱등·보류·재할당 테스트 | UI 확인 dialog와 Gateway 요청 연결 |
| 03 | Pinky `status_node.py`; `gateway/omx_status.py` | Pinky·OMX 1초 heartbeat/변경 즉시 전송 정책 테스트 | OMX state agent, TCP 연결 |
| 04 | `audit_repository.py`, `recording_server/recorder.py`, `recording_server/catalog.py` | 작업/승인 이력·RTSP H.264 60초 segment argv·process lifecycle·보존 테스트 | 실제 FFmpeg/RTSP·file watcher·파일 삭제 권한 검증 |
| 05 | 기존 `vision_perception/augmentation`; `training/dataset_policy.py` | split/실시간 비증강 테스트 | 학습·원본/저조도 평가 지표 |
| 06, 38, 51 | `inventory_workflow.py` | 최종 결과만 재고 반영·멱등 테스트 | DB transaction과 주문 결과 저장 |
| 07, 08, 09, 41 | `dispatch_workflow.py`, `rmf_adapter/traffic_reservation.py`, Pinky `eta.py` | 우선순위·공간/통로 시간 예약·ETA 재계산 테스트 | Open-RMF traffic/주행 graph API 연동 |
| 11, 13, 15, 16, 37, 46, 47 | `task_manager/omx_workflow.py` | QR/marker 전제·재시도·임시슬롯·pause·인계 테스트 | OMX/MoveIt adapter와 실제 그리퍼·후퇴 확인 |
| 14 | `object_worker/basket_correction.py` | 제한 보정·재정차 요청 테스트 | YOLO OBB/camera calibration 정확도 |
| 17, 18 | `marker_worker/policy.py` | QR·marker ID·오차 gate 테스트 | OpenCV QR/ArUco 입력 변환 |
| 19, 20, 44 | `person_worker/policy.py` | 쓰러짐 로직과 분리한 ROI·연속 프레임·작업자 존재 테스트 | YOLO tracker/RTSP와 실제 좌표·FPS |
| 52 | **계획 단계, 구현 보류**; `sr52-fall-detection-research-plan.md` | 쓰러짐 감지 코드를 완료 근거로 사용하지 않음 | 데이터·오경보/지연 수용 기준·운영자 승인 흐름 확정 후 shadow mode 평가 |
| 21 | `pick_failure_report.py` | 실패 물품 보류·증거 세그먼트 테스트 | UI evidence 링크와 FMS task hold |
| 23, 24, 25, 45, 48, 49, 54, 57 | `trihouse_pinky/*` | 안전 gate·운반·복귀·표시·비상 정책 테스트 | ROS/Jazzy·Nav2·Pinky 실물/Gazebo |
| 27 | `battery_policy.py` | 정상/작업제한/복귀필요·거리/여유 기반 판단 테스트 | 실제 소비계수와 threshold 보정 |
| 28 | `handover_gate.py` | 같은 job Pinky/OMX readiness gate 테스트 | 양측 status event 연결 |
| 29 | `stage_engine.py` | 단계 ID 일치·중복 방지·재개 테스트 | persistent event consumer 연결 |
| 34, 35 | `storage_assignment.py`, `inventory_workflow.py` | QR code only zone·슬롯 예약 테스트 | QR parser/DB slot data 연결 |
| 39, 40 | `fleet_manager/order_intake.py`, `inventory_workflow.py` | 전량/부분 주문 확정·부족 취소·FEFO reservation 테스트 | 주문 API와 재고 snapshot/lot reservation 연결 |
| 43, 45 | `packing_station.py` | 예약·사용 중·작업자 기반 재배정 테스트 | RMF 진입순서·Pinky 새 목표 전달 |
| 50, 51 | `task_manager/outbound_result.py`, `inventory_workflow.finalize_outbound()` | 부분전달 분류·최종 1회 차감 테스트 | UI 입력/DB order result record |
| 53, 56 | `operations_feed.py`, `audit_repository.py`, `emergency_workflow.py`, `gateway/authorization.py` | 우선 알림·승인 기록·관리자 역할 해제 테스트 | UI 경고/실제 identity provider 연결 |
| 54, 55, 56, 57 | `emergency_workflow.py`, Pinky safety/recovery | zone block·영향 로봇 복구 분기 테스트 | RMF temporary keep-out, Pinky return action |

Pinky SR의 9개 High/Medium 항목은 정적 정책 구현·테스트 기준으로 별도 감사했다.
요구사항별 코드, 자동 테스트, 그리고 아직 완료가 아닌 ROS/Gazebo/실물 검증의 경계는
[`pinky-sr-completion-audit.md`](pinky-sr-completion-audit.md)에 기록했다.

## 공통 정적 검증

```bash
cd /Users/wonsiyeon/Documents/Codex/Trihouse
PYTHONPATH='trihouse_pinky/trihouse_pinky_fleet:trihouse_pinky/trihouse_pinky_safety:trihouse_pinky/trihouse_pinky_io:trihouse_pinky/trihouse_pinky_bringup' \
python3 -m unittest discover -v
python3 -m compileall -q control_tower trihouse_pinky vision_system
git diff --check
```

`unittest discover`는 현재 저장소의 다른 의존성 기반 테스트까지 찾을 수 있으므로, 의존성 없는
현재 정책 스위트는 README들에 적힌 명시 목록으로 실행한다. 위 명령을 최종 게이트로 채택하기
전에는 ROS/외부 패키지 테스트의 실행 가능 여부를 실제 CI에서 확인해야 한다.

## 현재 통합 시나리오

`control_tower/tests/test_outbound_happy_path.py`는 하나의 출고 물품이 FEFO 예약된 뒤 Pinky에
배차되고, Pinky·OMX 준비 게이트와 OMX 인계를 통과해 포장대에 도착하고, 최종 인계에서만
원본 재고가 차감되는 경로를 검증한다. 이 테스트는 실제 ROS/RMF/OMX 통신을 대체하지 않지만,
각 정책 모듈의 연결 순서와 재고 변경 시점을 고정한다.

`control_tower/tests/test_inbound_happy_path.py`는 QR 보관 코드 → 허용 구역의 첫 빈 슬롯 예약 →
Pinky·OMX 공동 준비 → OMX 선반 적재 완료 → 최종 lot 생성 순서를 검증한다. QR은 zone만
결정하며, slot은 FMS가 예약하고 재고는 실제 적재 완료 전까지 변하지 않는다.
