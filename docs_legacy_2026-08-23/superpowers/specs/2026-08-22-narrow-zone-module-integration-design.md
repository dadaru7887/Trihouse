# Narrow-Zone Module Integration Design

## Scope

`origin/dev_driving`의 `driving_fms`, `driving_v1_first_run`,
`driving_v2_final`에 흩어진 창고 협로 규칙 주행을 현재 Trihouse의 FMS/RMF/ROS 2
경계에 맞춰 정리한다. 목표는 모든 협로 창고가 `Nav2 entry 접근 → 규칙 진입 → 도크
검증 → 다음 명령 시 규칙 탈출 → exit target 검증 → Nav2 재개`를 동일하게 따르게
하고, 이를 순수 모듈·실기 모듈·전체 통합의 세 단계로 시험할 수 있게 하는 것이다.

VLM/RL 복구, 주문 생성, OMX 적재 로직은 이번 범위에서 변경하지 않는다.

## Source audit

### Reuse

- `driving_fms/narrow3_rule_based_docking.py`
  - 창고별 `sequence`와 `sequence_exit`
  - map 좌표계의 방향성 직사각형 판정
  - 회전은 최단 각도, 직진은 실제 이동거리로 완료 판정
  - 목표에 가까워질수록 감속하고 단계별 timeout에서 정지
- `driving_fms/nav_recovery_executor.py`
  - timeout과 사용자 중단 시 활성 Nav2 goal을 명시적으로 취소하는 원칙
- `driving_fms/mission_goal_state_machine_v2.py`
  - 목적지 식별자를 협로 프로파일로 매핑하고 실행기에는 선택 결과만 전달하는 경계
- `driving_v1_first_run/orchestrate_fms_v1_drive.py`
  - 일반 구간은 Nav2, 협로 구간은 규칙 엔진으로 넘기는 분기
  - 한 구간이 실패하면 자동 재시도하지 않고 정지하는 원칙
- `driving_fms/fms_feature_points.jsonl`와
  `aruco_recognition_distance_tests.jsonl`
  - 상온 marker 2, 냉장 marker 1, 냉동 marker 0의 provenance

### Do not reuse

- `/cmd_vel` 직접 발행. 모든 규칙 명령은 `cmd_vel_dock`을 거쳐
  `safety_supervisor`만 실제 `cmd_vel`을 발행한다.
- `GatewayAPIStub`, 숫자 기반 `narrow_1/2/3` 런타임 식별자, private FSM 필드 직접
  변경. 현재 canonical `destination_code`와 Gateway assignment를 사용한다.
- `driving_v2_final`의 미학습 policy, 한 프레임 trigger, TODO recovery 실행 경로.
- 신호가 없을 때 계속 진행하거나 미실측 창고를 일반 Nav2 최종좌표로 대체하는 동작.

## Runtime invariant

협로가 필요한 창고 목적지는 실행 가능한 narrow-zone profile이 없으면 fail closed한다.
일반 Nav2 최종 도크 이동으로 폴백하지 않는다.

```text
ExecuteTransport(destination_code)
  → narrow catalog에서 destination 조회
  → profile 없음/disabled/unmeasured: REJECTED(NARROW_PROFILE_NOT_READY)
  → Nav2 NavigateToPose(profile.entry_pose)
  → 규칙 enter sequence를 cmd_vel_dock으로 실행
  → profile.dock_target/zone 검증
  → 도착 보고

다음 ExecuteTransport
  → 현재 map pose가 narrow zone 안이면 exit sequence 선행
  → profile.exit_target 검증
  → 원래 NavigateToPose 시작
```

`entry`는 Nav2가 정지할 좌표, `zone`은 도킹 후 로봇이 머무는 방향성 영역,
`enter/exit`은 로컬 규칙 단계, `dock_target/exit_target`은 완료 검증 좌표다.

## Module ownership

`trihouse_pinky_docking.narrow_zone`이 설정 모델, 파서, 기하 판정, 상태 기반 제어기를
유일하게 소유한다. `fleet_node`는 목적지 선택과 Nav2/협로 순서만 조정한다.
기존 `trihouse_pinky_fleet.narrow_zone_pilot`과
`trihouse_pinky_docking.sequence/zones`의 중복 구현은 새 모듈을 재수출하는 호환 계층으로
축소한 뒤 호출부가 모두 전환되면 제거할 수 있게 한다.

이번 단계에서는 새 ROS interface를 늘리지 않는다. `fleet_node`가 새 순수 제어기를
사용하되 발행 토픽을 `cmd_vel_dock`으로 바꾼다. marker 기반 `Dock` action은 별도
피드백 제어 경로로 유지한다.

## Profile readiness

창고 profile은 다음 조건을 모두 만족해야 실행 가능하다.

- `enabled: true`
- `measured.entry_pose`, `measured.dock_pose`, `measured.enter`, `measured.exit`가 참
- 유효한 `entry`, `zone`, 비어 있지 않은 `enter`, 비어 있지 않은 `exit`
- 창고 profile에는 `dock_target`과 `exit_target`이 모두 존재
- 현재 map 이름과 YAML `map_name`이 일치

오늘 일부만 실측된 `new_map_2`에서는 냉동 profile만 실행 대상으로 유지한다.
상온·냉장은 파일에 보존하되 readiness가 false라 실제 motion test에서 거절한다.

## Test strategy

### 1. Pure module tests

ROS 없이 profile 파싱, 목적지 선택, 방향성 zone, 최단 회전, 거리 기반 감속, 단계
전이, timeout, cancel, enter/exit 완료 자세를 검증한다. `origin/dev_driving`의 실측
수치는 literal fixture로 고정하되 map이 다른 값은 실행하지 않는다.

### 2. Hardware module test

`pytest -m hardware` 테스트 클라이언트가 실제 `ExecuteTransport` action을 사용해 한
창고의 `approach`, `enter`, `exit`, `roundtrip` 중 하나를 수행한다. 테스트가
`cmd_vel`을 직접 발행하지 않는다. 다음 gate가 모두 충족돼야 수집 후 실행한다.

- `--enable-motion`
- `--robot-namespace`와 `--destination`
- Readiness READY, SafetyState가 emergency 아님
- `cmd_vel`의 유일한 발행자가 safety supervisor
- 실행 가능한 measured profile

한 pytest 실행은 한 번의 bounded attempt만 수행한다. 실패한 규칙을 자동 재시도하지
않고 0 속도, action cancel, 측정 trace를 남긴다. YAML을 수정한 뒤 사람이 다시 실행한다.

### 3. Full integration test

공개 주문 API에서 시작해 Gateway job/step, RMF dispatch, `ExecuteTransport`, Nav2 entry,
규칙 enter/exit, OMX handover, packing, charger return을 관찰한다. 시뮬레이션에서는
가짜 모션 성공으로 대체하지 않고 실제 ROS action/result와 pose 전이를 확인한다.
실기는 별도 `hardware` marker와 동일한 motion gate를 요구한다.

## Error and cancellation rules

- profile 미준비: motion 전에 거절
- Nav2 entry 실패: 규칙 주행 시작 금지
- pose 소실, emergency, step timeout, cancel: 즉시 0 속도 발행 후 실패
- enter 완료 자세 불일치: 도착 보고 금지
- exit target 불일치: 다음 Nav2 goal 시작 금지
- 자동 규칙 재시도 없음

## Acceptance

- 협로 창고는 entry로만 Nav2 goal이 전송된다.
- 창고 zone 안에서 받은 다음 명령은 exit를 먼저 실행한다.
- 미실측/disabled 창고는 일반 Nav2로 폴백하지 않는다.
- 규칙 속도는 `cmd_vel_dock`으로만 나간다.
- 냉동 profile은 오늘 실측 좌표로 enter/exit 완료 자세를 검증한다.
- 세 단계 테스트가 서로 다른 marker와 실행 명령으로 제공된다.
