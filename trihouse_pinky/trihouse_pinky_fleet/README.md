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
- `task_event_publisher`: `NavigationState`를 `TaskEvent`로 변환
- pickup, navigation, docking, handover, packing, dropoff, return 상태 머신

## 4. 발행·구독 토픽

`/trihouse/status` (`RobotStatus`), `/trihouse/navigation/state`
(`NavigationState`), `/trihouse/task/events` (`TaskEvent`),
`/trihouse/handover/state` (`HandoverState`)를 발행한다. 배터리·safety·readiness·cargo·vision health를 구독한다.

## 5. 제공·호출 서비스

외부 location ID는 Control Tower가 배포한 versioned location map에서 조회한다.
Domain 간 ROS 위치 조회 service는 사용하지 않는다.

## 6. 제공·호출 액션

`/trihouse/transport/execute` (`ExecuteTransport`)를 제공하고 Nav2
`/navigate_to_pose`와 `/trihouse/dock` (`Dock`)을 호출한다. Nav2 goal이 끝나거나
취소된 뒤에만 docking을 시작한다.

## 7. 사용하는 공용 인터페이스

`RobotStatus`, `NavigationState`, `TaskEvent`, `HandoverState`,
`BatteryPolicyState`, `SafetyState`, `Readiness`, `StreamHealth`, `ExecuteTransport`, `Dock`.

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

## 사람 관측 하향 경로 (2026-08-20)

5080 의 추론 결과는 로봇에 직접 꽂히지 않는다. `system_overview.md` 의 금지 연결에
`VLM/RL → Safety Supervisor 우회` 가 있다.

```text
5080 추론 ──▶ 4060 관제(Vision Adapter) ──▶ gateway_node._drain
                                              └─▶ /trihouse/vision/person_detection/base
                                                    └─▶ safety_supervisor  (사람 보이면 SLOW)
```

`keep_out_zone` 과 같은 링크를 쓰지만 **처리는 다르다.** 그쪽은 명령이라 `message_id`
중복 검사와 건건 ack 가 있고, 이쪽은 10~15 Hz 로 흐르는 **관측**이라 둘 다 없다.
명령 규약을 씌우면 `seen` 목록이 무한히 커지고 ack 가 역류해 링크를 채운다.
신선도는 `ttl_ms` 가 싣고 `safety_supervisor` 가 그것으로 만료를 본다.

**`pose` 는 캘리브레이션 전까지 비어 있다.** 카메라 내부 파라미터가 없어 픽셀을
미터로 바꿀 수 없다 — `config/cameras.yaml` 이 같은 이유로 `map_pose` 를 `null` 로
둔다. 그래도 안전은 동작한다: gate 가 `confidence > 0` 을 사람 있음으로 읽어 거리와
무관하게 SLOW 를 건다. 캘리브레이션은 나중에 이것을 **좁히는** 역할이다(멀리 있는
사람에는 감속하지 않도록).

아직 없는 것: 5080 → 4060 구간과 4060 의 Vision Adapter. Gateway API 모양이 정해진
뒤 붙인다. 파서(`protocol.parse_person_detection`)는 전송 방식과 무관하므로 그대로
재사용된다.
