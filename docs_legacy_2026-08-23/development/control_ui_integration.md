# RoboSapiens 관제 UI 연동 기준

## 보호 원칙

`control_system/`은 `gwangheeyi/robosapiens`의 작업 트리이며, 이 프로젝트에서는 **읽기
전용**이다. 2026-08-09에 확인한 원격 `origin/main` 기준 commit은 `0d069f9`다.

- `control_system/robo_control/`의 Dart/Flutter 코드, `robo_core/` 모델, pubspec, 테스트를
  수정·병합·체크아웃하지 않는다.
- `control_tower/`가 별도의 Gateway/FMS 정책 코드이고, RoboSapiens UI는 검증할 기존 운영 화면
  기준이다.
- UI 기능을 늘려야 하면 먼저 Trihouse 쪽에 **별도 adapter 또는 별도 배포 wrapper**를 추가한다.
  원본 UI를 복제하거나 직접 수정하지 않는다.

## 확인한 현재 UI 기능

`robo_control/lib/ui/app_shell.dart`는 다음 화면을 제공한다.

| 화면 | 기존 코드의 상태 소유자 | Trihouse 요구사항과의 관계 |
| --- | --- | --- |
| 종합 현황 / 실시간 맵 / 로봇 관제 | `FleetEngine.robots`, `beacons` | SR_01의 Pinky 위치·방향·배터리·안전·작업 표시 기반 |
| 태스크·주문 / 재고·FEFO | `FleetEngine.tasks`, `orders`, `lots` | SR_02, 06, 39~41, 50~51의 운영 표시 기반 |
| 안전 관리 / 운행 이력 | `FleetEngine.incidents`, `events` | SR_53~56의 경고·승인 이력 표시 기반 |

원격 `robo_control/lib/core/fleet_engine.dart`는 현재 `SqliteDataStore`와 자체 `FleetEngine`을
생성한다. 따라서 Trihouse `control_tower/gateway/operations_feed.py`의 REST/WebSocket read model을
그대로 소비하지 않는다.

또한 `robo_control/lib/core/robot_link.dart`는 TCP 8788에서 `{ "t": "hello" }`,
`telemetry`, `path`, `hold`, `speed` 형식의 RoboSapiens 전용 NDJSON을 사용한다. Trihouse Pinky
Gateway의 `execute_transport`, `robot_status`, `task_event` 형식과 이름과 의미가 다르며, 두 서버를
같은 8788 포트에 동시에 띄울 수 없다.

## 안전한 연동 선택지

현재는 다음 중 하나를 아키텍처 결정으로 선택해야 한다. 원본 RoboSapiens 코드의 수정은 어느
선택지에도 포함하지 않는다.

1. **RoboSapiens를 시연 UI로 유지:** 별도 Trihouse UI adapter가 `control_tower`의 snapshot/event를
   RoboSapiens가 이미 이해하는 상태로 변환해 전달한다. 다만 RoboSapiens의 자체 SQLite/FleetEngine이
   상태의 최종 권한자가 되지 않도록 읽기 전용 mirror로 한정해야 한다.
2. **Trihouse Gateway UI를 별도 배포:** 기존 RoboSapiens UI는 참조/시연 도구로 유지하고,
   `control_tower`의 REST/WebSocket 계약을 소비하는 독립 UI를 별도 저장소 또는 배포 단위로 만든다.
3. **향후 원본 저장소 소유자의 명시적 허가 후 adapter package 추가:** `robo_control` 본체가 아니라
   별도 Flutter package에서 Gateway client를 주입한다. 이 경우에도 `FleetEngine`과 FMS가 동시에
   배차·재고를 변경하지 않도록 단일 권한자를 먼저 정한다.

현재 요구사항의 권한 경계(FMS는 배차·재고·비상 구역, Pinky는 로컬 주행과 안전 정지)를 지키려면
1번의 read-only mirror 또는 2번이 적합하다. 양쪽 엔진이 동시에 작업을 만들거나 재고를 변경하는
연동은 금지한다.

## 이미 구현된 Trihouse 계약

- `GET /api/v1/operations`: robot/job/incident snapshot
- `GET /api/v1/events`: 우선순위 순 event polling
- `GET /api/v1/events/ws`: read-only WebSocket event payload

이 계약의 테스트는 `control_tower/tests/test_operations_feed.py`와
`control_tower/tests/test_operations_http_server.py`에 있다. 인증, 지속 WebSocket fan-out, 카메라
재생 URL 권한 검증은 실제 배포 전에 별도로 구현·검증해야 한다.
