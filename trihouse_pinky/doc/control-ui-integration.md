# 중앙 관제 UI 연동

> 상태: 네트워크 계약 초안

## 기동 경계

관제 UI와 DB는 RTX 4060 등 중앙 PC에서 별도로 실행한다. 로봇의 최상위 launch는 UI 프로세스를 시작하거나 종료하지 않는다. `trihouse_pinky_fleet`만 설정된 관제 주소에 접속한다.

## 초기 전송 계약

기존 `control_system/robo_control/lib/core/robot_link.dart`와 `control_system/robo_pinky/src/robo_pinky_agent/robo_pinky_agent/control_link.py`의 TCP 8788 + 줄 단위 NDJSON 연결, hello, telemetry, 재접속 framing을 확장한다.

모든 payload는 최소 `schema_version`, `message_id`, `type`, `sent_at`, `robot_id`를 가진다. 작업은 `task_id`, 작업 종류, `map_revision`, pickup/dropoff/packing location ID와 pose, 우선순위 또는 기한을 포함한다. 로봇은 수락/거절, 현재 단계, pose, 배터리, safety, 성공/실패 결과를 회신한다. `message_id` 또는 `(task_id, seq)`로 중복을 제거한다.

ROS 사용자 정의 인터페이스는 로봇 내부 계약이고 NDJSON은 중앙 PC와 로봇 사이의 전송 계약이다. 브리지에서 명시적으로 변환하며 같은 wire format으로 간주하지 않는다.

## 작업 흐름

```text
UI 주문 → DB 작업/위치 조회 → 로봇 배정 → NDJSON 작업 전송
→ readiness 및 map revision 확인 → 수락/거절
→ ExecuteTransport → Nav2 이동 → 결과/telemetry → UI 반영
```

기존 `agent_node.py`의 waypoint follower와 직접 `/cmd_vel` 발행은 운영 launch에서 제외한다. 재사용 범위는 연결/재접속, hello/telemetry framing뿐이다.

## Readiness gate

다음 조건을 모두 만족해야 신규 작업을 수락한다.

- 필수 센서 토픽이 제한 시간 안에 갱신된다.
- Nav2 lifecycle 노드가 active이고 `navigate_to_pose` 서버가 응답한다.
- AMCL pose가 존재하고 공분산이 설정 임계값 이내다.
- 로봇과 작업의 `map_revision`이 일치한다.
- safety가 비상 정지 상태가 아니다.
- 관제 heartbeat가 정상이고 시각이 동기화됐다.
- 작업이 vision 또는 docking을 요구하면 해당 health가 정상이다.

거절 응답에는 기계 판독 가능한 reason code를 포함한다. 연결 복구 뒤에는 관제와 `task_id` 및 마지막 체크포인트를 대조한 후에만 재개한다.

