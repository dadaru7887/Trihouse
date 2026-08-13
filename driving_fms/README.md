# Pinky 주행 FMS 프로토타입 (1차 버전)

Pinky 로봇 주행 관점에서 만든 규칙기반(rule-based) FMS 1단계 실행 스크립트. Nav2 위에서
동작하며, waypoint 그래프(`fms_feature_points.jsonl`)를 따라 start_zone -> 적재구역(들) ->
middle_goal -> end_zone 한 사이클을 자동 주행한다.

## 아직 안 된 것 (정직성 원칙)

- **VLM/RL(세그멘테이션+RL 정책)과 미연동.** 이 스크립트는 순수 FMS 계층(어디로 갈지,
  언제 대기할지)만 담당한다. VLM/RL은 아직 학습/자동화 작업이 더 필요해서 이번 버전에는
  포함하지 않았다.
- **Gateway API 실제 조회 미연동.** `mission_runner.py`의 `occupied_end_slots`/
  `occupied_bottlenecks`/`occupied_loading_zones`/`critical_claims`는 전부 `None`으로
  시작한다(다중 로봇 점유 신호 없음). DB 스키마의 `reservations` 테이블이 이 용도로 이미
  설계돼있는 걸 확인했으나(`FMS_DB_GAP_ANALYSIS.md` 참고), 실제 조회 엔드포인트는 아직 없다.
- `RobotStatus.ready`/`.dispatchable`는 항상 `False`로 고정된다 -- 진짜 fleet에 배차 가능한
  로봇으로 오인되지 않도록.
- ArUco 카메라 연동 전이라 지금은 NavigateToPose 도착 = 적재구역 방문 완료로 단순화했다.

## 실행법

```bash
python3 mission_runner.py --loading-targets 3 --zone-slot 1
python3 mission_runner.py --loading-targets 1,2 --zone-slot 1 --speed 0.1
```

## 의존성

- ROS2 Jazzy, Nav2 (RPP controller, NavigateToPose)
- `trihouse_interfaces` 패키지(`RobotStatus`/`TaskEvent`/`TaskContext`/`NavigationState`) --
  이 repo의 `trihouse_interfaces`를 colcon build 해야 import된다.
- 로봇 원본 토픽: `/battery/percent`, `/battery/voltage`, `/scan`, `/imu_raw`, `/odom`

## 파일 구성

- `mission_goal_state_machine.py` -- 규칙기반 FMS 엔진 (Stage 전이, 병목/적재구역/
  middle_goal 혼잡 대기, 배터리 CRITICAL override, safe_zone operator_release 게이트,
  ArUco 도착 게이트)
- `mission_runner.py` -- 실행 스크립트. `RobotStatus`/`TaskEvent`/배터리(`BatteryState`)/
  센서 요약값(`/trihouse/sensor_summary/*`)/작업 단위 배터리 이력(`/trihouse/battery/
  job_history`)까지 발행
- `battery_watcher.py` -- 배터리 비상 감시(CRITICAL 10%/LOW 20%), VLM/RL 정책과 무관하게
  결정론적으로 동작
- `nav_recovery_executor.py` -- Nav2 NavigateToPose action client 래퍼. VLM/RL의
  파일 중 FMS가 실제로  쓰는 NavigateToPose 부분만 남기고 트리밍함
- `check_aruco_detection.py` -- ArUco 마커 인식 거리/각도 실측 도구
- `export_for_db_handoff.py` -- `fms_feature_points.jsonl`/`aruco_recognition_distance_
  tests.jsonl`을 DB 스키마 필드명으로 변환해서 내보내는 논-디스트럭티브 스크립트
- `fms_feature_points.jsonl`, `aruco_recognition_distance_tests.jsonl` -- 실측 데이터
- `FMS_DB_GAP_ANALYSIS.md` -- FMS 코드 개념과 실제 Trihouse DB 스키마 간 갭 분석 문서
