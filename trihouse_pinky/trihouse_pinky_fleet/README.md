# trihouse_pinky_fleet

> 상태: 구현 계획. 현재는 README만 존재한다.

## 1. 목적과 책임

관제 연결, `ExecuteTransport` 상태 머신, Nav2/docking 호출, telemetry, 체크포인트와 중복 작업 방지를 담당한다.

## 2. 넣지 않을 기능

직접 `/cmd_vel` 발행, 카메라 스트리밍/좌표 변환, 안전 센서 판정, docking P 제어를 넣지 않는다.

## 3. 계획된 노드와 작업

- `fleet_node`: 작업 수락/거절과 단계 전이
- `control_link`: TCP 8788 + NDJSON hello, heartbeat, 재접속, schema 변환
- `checkpoint_store`: `task_id`, 마지막 완료 단계, sequence 영속화
- `display_mapper`: 상태를 LED/램프/LCD 서비스로 매핑
- pickup, navigation, docking, handover, packing, dropoff, return 상태 머신

## 4. 발행·구독 토픽

`RobotStatus`, `TaskEvent`, `TaskTrace`, `HandoverReady/Done`, `PackingAssistanceRequest`를 발행하고 `HandoverGo`, `PackingDirective`, `PackingStationStatus`, pose/battery/safety/vision health를 구독할 계획이다.

## 5. 제공·호출 서비스

관제의 `GetLocation`과 벤더 표시 장치 서비스를 호출할 계획이다.

## 6. 제공·호출 액션

`ExecuteTransport`를 제공하고 Nav2 `NavigateToPose`와 `Dock`을 호출한다. Nav2 goal이 끝나거나 취소된 뒤에만 docking을 시작한다.

## 7. 사용하는 공용 인터페이스

`DeliveryOrder`, `RobotStatus`, `TaskEvent`, `TaskTrace`, handover/packing 메시지, `StreamHealth`, `GetLocation`, `ExecuteTransport`, `Dock`.

## 8. pinky_pro 참조

`nav2_web_server.py`의 goal/cancel/TF/상태 판정은 알고리즘 참고만 한다. `agent_node.py` waypoint follower와 직접 속도 발행은 운영 경로에서 제외하고 `control_link.py`의 TCP 연결 패턴만 재사용한다.

## 9. 설정 파일 후보

관제 host/port, heartbeat 주기와 실패 횟수, 체크포인트 경로, map revision, 상태별 timeout, 표시 mapping을 계획한다.

## 10. 구현 순서와 완료 조건

1. NDJSON schema와 중복 제거 키를 확정한다.
2. 한 건의 작업 수락/거절과 heartbeat를 구현한다.
3. Nav2 한 지점 이동 및 결과 회신을 구현한다.
4. 체크포인트와 복구를 추가한다.
5. docking/handover/packing 단계를 확장한다.

최소 완료 조건은 작업 한 건을 readiness에 따라 수락하거나 거절하고, Nav2 결과와 telemetry를 관제 UI에 일관되게 반영하는 것이다.

