# Pinky 출입구 진입 및 Safety Recovery 설계

## 목표

상온·냉장 창고 진입 시 출입구에서 제자리 회전하지 않고, 바깥쪽에서 진행 방향을
맞춘 뒤 저속 직진으로 통과하고 내부에서 도크 방향으로 회전한다. 모든 속도 명령은
기존 `cmd_vel_dock → safety_supervisor → cmd_vel_safe → Pinky motor` 경로를 유지한다.

## 확인된 현재 동작과 실패 원인

현재 `fleet_node`는 Nav2가 `entry_zone`에 들어오면 Nav2 goal을 취소하고
`EntryPoseController`로 `entry` 위치와 yaw를 맞춘다. 로봇이 이미 entry 위치에 있으면
controller는 바로 `MATCH_YAW`로 들어가 제자리 회전을 요청한다. 이어지는
`NarrowZoneController`의 첫 단계도 상온·냉장 모두 `rotate`다.

Safety Supervisor는 제자리 회전 명령에서 가장 가까운 LiDAR 반사가
`swept_clearance_m` 이하이면 `swept_stop`으로 최종 속도를 0으로 만든다. Fleet는 현재
SafetyState에서 emergency 여부만 보존하므로 `swept_stop`과 다른 STOP 원인을 구분해
entry recovery를 실행할 수 없다. 결과적으로 pose와 yaw가 바뀌지 않고
`entry_alignment_timeout` 또는 `step_timeout`으로 종료된다.

## 좌표 사용 원칙

신규 실측 좌표를 만들지 않는다. 첫 실물 시도는
`config/narrow_zones.new_map_2.yaml`에 현재 등록된 `entry`와 `dock_target`만 사용한다.

각 구역은 다음처럼 해석한다.

- `entry`: Nav2 approach 및 바깥쪽 alignment point
- `doorway`: `entry`와 `dock_target` 위치의 중점으로 계산한 시험값
- `inside_turn`: 현재 `dock_target`의 위치
- doorway 진행 heading: `atan2(dock_y - entry_y, dock_x - entry_x)`
- 최종 dock yaw: 현재 `dock_target.yaw`

계산된 1차 시험값은 다음과 같다.

| 구역 | alignment | doorway 시험값 | inside turn/dock | doorway heading | dock yaw |
|---|---|---|---|---:|---:|
| 상온 | `(0.9117481526, 0.7758764643)` | `(1.0533666719, 0.8253152649)` | `(1.1949851912, 0.8747540653)` | `0.3358713991` | `-2.8057212545` |
| 냉장 | `(0.7859059395, 0.8752449912)` | `(1.0561239087, 0.2881874149)` | `(1.3263418779, -0.2988701615)` | `-1.1394165202` | `2.4189105956` |

doorway 중점은 실측 doorway center라고 주장하지 않는다. calibration 전용 시험값이며,
실물 경로가 출입구 중심과 다르면 사용자가 alignment, doorway, inside-turn을 다시
측정해 YAML만 교체한다. 일반 주문 gate의 기존 `measured` 정책은 유지한다.

## 선택한 구조

ROS에 의존하지 않는 공통 `WarehouseEntryController`를 docking 패키지에 둔다. 상온과
냉장은 같은 controller를 쓰고 zone별 차이는 YAML profile로만 제공한다. 냉동과 충전
탈출은 현재 검증된 legacy `NarrowZoneController` 흐름을 유지한다.

Fleet의 전체 흐름은 다음과 같다.

```text
NAV2_APPROACH
  → ENTRY_ALIGNMENT
  → ENTER_STRAIGHT
  → INSIDE_CLEAR
  → TURN_TO_DOCK
  → DOCK_APPROACH
  → DOCKING/COMPLETE
```

`ENTRY_ALIGNMENT`는 alignment point에서 doorway heading으로 회전한다.
`ENTER_STRAIGHT`는 양의 `linear.x`와 제한된 작은 `angular.z` 보정만 사용해 doorway와
inside-turn을 통과한다. 위치가 inside-turn 허용오차 안에 들어온 뒤에만
`TURN_TO_DOCK`에서 dock yaw 회전을 허용한다. 이번 profile에서는 inside-turn과
dock-target 위치가 같으므로 `DOCK_APPROACH`는 최종 위치 허용오차를 확인하는 단계다.

## Profile 모델

기존 `entry`, `entry_zone`, `dock_target`, `enter`, `exit` 필드는 호환을 위해 유지한다.
상온·냉장에 선택적으로 다음 `entry_passage`를 추가한다.

```yaml
entry_passage:
  doorway: {x: ..., y: ...}
  inside_turn: {x: ..., y: ...}
  doorway_heading: ...
  entry_yaw_tolerance_rad: 0.05
  entry_straight_speed_mps: 0.06
  heading_correction_max_rps: 0.15
  recovery_distance_m: 0.05
  recovery_speed_mps: 0.03
  recovery_max_attempts: 2
  recovery_timeout_s: 10.0
```

`entry_straight_speed_mps=0.06`과 yaw tolerance `0.05`는 기존 협로 MotionLimits 값을
그대로 사용한다. heading correction은 큰 회전이 되지 않게 기존 최대 회전속도
`0.5rad/s`보다 낮은 `0.15rad/s`로 제한한다. recovery 속도 `0.03m/s`는 기존
DriveOnHeading recovery 속도와 같고, recovery 거리 `0.05m`는 현재 entry-zone 길이와
같은 첫 시험값이다. 이 값들은 실물 결과에 따라 YAML에서만 조정한다.

`entry_passage`가 없는 profile은 기존 흐름을 그대로 쓴다. 필드가 일부만 있거나 값이
유효하지 않으면 profile issue로 기록하고 해당 신규 진입을 시작하지 않는다.

## swept_stop 전용 Recovery

Fleet는 최신 SafetyState의 `state`, `detail`을 보존해 controller에 전달한다.

```text
ENTRY_ALIGNMENT + swept_stop
  → 현재 회전 명령 0
  → RECOVER_ROTATION_SPACE
  → 저속 후진 명령을 cmd_vel_dock으로 발행
  → Safety Supervisor가 후방 path clearance를 다시 판정
  → 설정 거리 이동 및 Safety CLEAR/SLOW 확인
  → ENTRY_ALIGNMENT 재시도
```

Recovery 중에도 Safety Supervisor가 최종 명령을 소유한다. 후진이 `front_stop`으로
막히거나 Safety 원인이 emergency, sensor timeout, keep-out, control-link lost이면
controller는 즉시 0 속도를 반환하고 안전 실패한다. recovery 횟수 또는 timeout을
초과하면 각각 `entry_recovery_attempts_exhausted`, `entry_recovery_timeout`을 반환한다.

SafetyState가 STOP인데 detail이 `swept_stop`이 아닌 경우에는 recovery를 시작하지
않는다. Emergency는 기존 workflow emergency 전환도 유지한다.

## Safety 기본값

`swept_clearance_m` 기본값을 `SWEPT_RADIUS_M + 0.02`에서 `SWEPT_RADIUS_M`으로
변경한다. `SWEPT_RADIUS_M`은 footprint와 `PROTECTIVE_HALF_WIDTH_M`에서 이미 파생된
보호 외접반경이다. `<=` 경계와 `swept_stop` 판정은 그대로 유지하며 Safety를 끄는
옵션은 추가하지 않는다.

Safety node는 `swept_stop` transition 또는 throttle된 경고에 desired velocity,
nearby range, swept clearance를 기록한다.

## Fleet 실패 정리

Entry alignment, passage, recovery 또는 docking 실패의 모든 terminal 경로에서 0 속도를
발행하고 workflow를 IDLE로 정리한다. 실패한 action 뒤 다음 요청이
`robot is not idle`로 영구 거절되는 상태를 남기지 않는다.

## 로그

Fleet는 controller phase가 바뀌거나 recovery attempt가 바뀔 때만 구조화된 한 줄을
남긴다. 로그에는 zone, phase, 현재 pose, 목표 pose, 위치/yaw 오차, Safety level/detail,
recovery attempt와 transition reason을 포함한다. 20Hz 반복 로그는 남기지 않는다.

## 테스트 전략

1. Safety 기본 threshold와 `<`, `==`, `>` 경계 동작을 테스트한다.
2. emergency, stale sensor, control-link lost, keep-out, front obstacle, person slow 정책의
   기존 회귀 테스트를 실행한다.
3. 상온·냉장 profile이 각각 alignment, doorway, inside-turn, dock yaw를 로드하는지
   literal 좌표로 검증한다.
4. 순수 controller에서 정상 상태 전이를 pose fixture로 검증한다.
5. `swept_stop → recovery → clear → alignment retry`를 검증한다.
6. recovery max attempts와 timeout을 검증한다.
7. swept_stop 이외 STOP에서 recovery velocity가 나오지 않는지 검증한다.
8. Fleet wiring이 최신 SafetyState를 controller에 전달하고 모든 terminal 실패에서
   workflow를 정리하는지 검증한다.
9. launch와 기존 frozen/charging narrow profile 회귀 테스트를 실행한다.

각 production 변경은 먼저 실패하는 테스트를 확인한 뒤 최소 구현으로 통과시킨다.

## 실물 검증 전제와 남은 위험

- 계산된 doorway 중점이 실제 문 중심이라는 측정 근거는 없다.
- 특히 냉장 alignment-to-dock 선분은 약 `1.293m`이므로 경로 전체가 비어 있는지 사람이
  확인해야 한다.
- inside-turn 위치가 실제로 회전 보호 외접원만큼 넓은지는 실측되지 않았다.
- recovery `0.05m` 후진으로 회전 여유가 확보되는지는 실측되지 않았다.
- 첫 calibration은 E-stop 담당자와 함께 상온 한 구역만 수행하고, 성공 후 냉장을
  수행한다.
- 실패하면 alignment, doorway center, inside-turn pose와 recovery 거리를 다시 측정해
  config만 교체한다.

코드·simulation 테스트 통과는 실물 주행 성공을 증명하지 않는다.
