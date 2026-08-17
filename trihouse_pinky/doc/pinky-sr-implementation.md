# Pinky SR 구현·실행 안내

이 구현은 `docs/requirements/pinky_requirements.md`의 Pinky 범위
(SR_03, 23, 24, 25, 45, 48, 49, 54, 57)를
세 책임으로 분리한다.

## 요구사항 추적표

| SR | 구현 경계 | 자동 테스트/확인 |
| --- | --- | --- |
| SR_03 상태 공유 | `status_node`가 1초마다 map 위치·배터리·적재·안전·오류를 포함한 `RobotStatus` 발행 | stale scan이면 `ready=false`, stale AMCL pose는 RMF에서 거절 |
| SR_23 사람 충돌 방지 | `safety_supervisor`의 final velocity gate | 초음파 우선 정지·timeout 정지 |
| SR_24·48 운반 | `fleet_node`의 `ExecuteTransport → NavigateToPose` | readiness/적재 확인 거절, 도착+정지 |
| SR_25 복귀 | action `mode=RETURN_TO_WAIT/CHARGE` | 빈 바구니 복귀 허용 |
| SR_45 재배정 | 인계 대기 중 같은 작업을 새 Nav2 목표로 전환 | job ID 유지 |
| SR_49 표시 | LED priority 및 목적지 LCD code mapping | unknown code는 LCD clear |
| SR_54 비상 | safety latch, LED/red, GPIO buzzer | 명시적 clear 전 motion 차단 |
| SR_57 재투입 | `recovery_health`가 복귀 후 odom·scan·초음파·battery·cargo 점검 | 실패 시 작업 불가 |
| 완료 예상 시간 | `eta.EtaEstimator`가 구간별 실효 속도로 보수적 ETA 산정 | Nav2 계획이 그래프 ETA를 교체하고, 계획 없으면 보류 |

| 책임 | 패키지 | 핵심 규칙 |
| --- | --- | --- |
| 최종 주행 안전 | `trihouse_pinky_safety` | `/cmd_vel` 발행자는 safety 하나이며, 초음파/LiDAR timeout은 정지다. |
| 관제 작업·상태 | `trihouse_pinky_fleet` | readiness·OMX 적재 확인 전에는 Nav2 목표를 보내지 않는다. |
| 센서·표시 변환 | `trihouse_pinky_io` | Pinky Pro 원본 토픽/LED 서비스만 재사용한다. |
| 조합·준비 검사 | `trihouse_pinky_bringup` | `/scan`, `/odom`, Nav2 action server가 모두 준비되어야 작업을 받는다. |

## 완료 예상 시간 정책

`trihouse_pinky_fleet/eta.py`는 관제나 fleet 노드가 사용할 순수 계산기다. 통로,
좁은 통로·회전, 정밀 접근 각각에 대해 실제 주행 시험의 중앙값으로 얻은 **실효 속도**를
주입한다. 따라서 Nav2의 설정 최고 속도를 그대로 ETA에 쓰지 않는다.

- 작업 배정 전에는 FMS 그래프 길이로 `estimate_segment()`를 호출한다.
- Nav2가 `/plan`을 만들면 Pose 간 거리를 합산하여 `replace_with_nav2_plan()`에 전달한다. 반환값은 이전 그래프 ETA를 **대체**하며 더하지 않는다.
- Nav2 계획이 없으면 반환값은 `None`이다. 그 상태에서는 완료 시각을 확정하거나 OMX 출발을 승인하지 않는다.
- OMX 파지 시각은 `omx_command_at()`으로 계산한다. 도착 예상이 2초 이하로만 바뀌면 `should_reschedule_omx()`가 `False`를 반환해 불필요한 재예약을 막는다.

## 빌드와 정책 테스트

```bash
cd /home/syw/Trihouse
python3 -m unittest -v trihouse_pinky.test.test_pinky_sr_policies
colcon build --base-paths trihouse_interfaces trihouse_pinky/trihouse_pinky_io trihouse_pinky/trihouse_pinky_safety trihouse_pinky/trihouse_pinky_fleet trihouse_pinky/trihouse_pinky_bringup
source install/setup.bash
```

## Control Tower 명령 형식

`fleet_gateway`만 TCP 8788 NDJSON을 ROS action으로 바꾼다. 이전 `pinky_agent`의
waypoint follower는 이 launch에 포함하지 않는다. 최소 운반 명령 예시는 아래와 같다.

```json
{"type":"execute_transport","message_id":"cmd-001","job_id":"job-001","job_step_id":"deliver","map_revision":"map-7","dropoff_location_id":"packing-1","destination_code":"PACKING","dropoff_pose":{"frame_id":"map","x":1.2,"y":-0.5,"yaw":0.0},"mode":"TRANSPORT"}
```

`mode`은 `TRANSPORT`, `RETURN_TO_WAIT`, `RETURN_TO_CHARGE` 중 하나다. RMF adapter만
내부 mode `RMF_NAVIGATION`을 사용하며 Control Tower가 이 mode로 Pinky를 직접
우회 호출하지 않는다. gateway는
필수 필드·`map` frame·중복 `message_id`를 검사하고, 통과한 메시지만
`/trihouse/transport/execute` action으로 보낸다. 상태와 task event는 역방향 NDJSON으로
관제에 전달된다.

OMX 적재·인계 위치처럼 정밀 정차가 필요하면 `requires_precise_stop:true`를 지정한다.
이 경우 fleet은 Nav2 success만으로 인계를 시작하지 않고, odom 기준 목표와
`0.05m`, `5도(0.0873rad)` 이내인지 한 번 더 확인한다. 범위를 벗어나면 실패로
보고하며, FMS가 재접근 또는 docking action을 지시해야 한다.

사람 위급상황은 `{"type":"emergency_request","message_id":"emg-1"}`로 safety
latch를 요청한다. 해제는 운영자 신원을 포함한
`{"type":"clear_emergency","message_id":"clear-1","operator_id":"admin-1","reason":"onsite confirmed"}`만 허용한다.
Vision은 이 메시지를 만들 수는 있어도 `/cmd_vel`을 직접 발행하지 않는다.

고정 카메라가 감지한 구역은 `keep_out_zone`으로 보낸다. `points`는 `map` 좌표의
최소 3개 `[x,y]` 꼭짓점이며, Pinky는 자기 odom 위치가 해당 polygon 안에 있을 때만
정지한다. `valid_for_s`가 0이면 관제의 명시 해제/새 정책 전까지 유효하다.
`clear_keep_out_zone`에는 `message_id`, `zone_id`, `operator_id`가 모두 있어야 하며,
gateway는 해당 ID의 zone을 즉시 만료시킨다.

## 실제 Pinky 실행

`pinky_pro`와 위 패키지를 같은 ROS 2 Jazzy overlay로 빌드한 뒤 실행한다.

```bash
ROS_DOMAIN_ID=52 ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py robot_id:=PK-01
```

확인할 것:

```bash
ros2 topic info /cmd_vel --verbose
ros2 topic echo --once /trihouse/readiness
ros2 topic echo --once /trihouse/status
```

첫 명령은 `/cmd_vel` 운영 발행자가 `safety_supervisor` 하나인지 확인한다. readiness가
`READY`가 아니면 fleet은 운반 action을 거절해야 한다.

Open-RMF를 함께 실행할 때는 `/amcl_pose`가 신선해야 `RobotStatus.frame_id=map`이 된다.
AMCL pose가 없거나 오래되면 status는 odom frame을 명시하고 RMF adapter는 등록 또는
상태 갱신을 거절한다. 실행 순서와 확인 명령은 `trihouse_rmf_bridge/README.md`를 따른다.

## Gazebo 범위

Gazebo bridge로 확인 가능한 것은 `/clock`, `/tf`, `/scan`, `/camera`, `/odom`,
`/cmd_vel`이다. 초음파·배터리·실제 LED·부저는 mock publisher/service로 검사한 뒤
Pinky ARM64에서 별도로 확인한다. 비상 요청은 Vision이 직접 속도 명령을 내리지 않고
Control Tower/Safety authority가 `/trihouse/safety/emergency_request`로 보낸다.

## 아직 정해야 할 실물 값

`front_stop=0.30m`, `front_slow=0.70m`, `person_protective_distance=1.0m`,
`sensor_timeout=0.5s`는 안전한 초기값이다.
통로 폭, Pinky 제동거리, 초음파 노이즈를 측정한 뒤 `policy.py`의 경계와 launch parameter로
확정한다. 쓰러짐 검출을 emergency로 승격하는 관제 승인 규칙은 Vision/FMS 책임이며,
카메라 검출 자체가 `/cmd_vel`을 발행하지 않는다.

```bash
ROS_DOMAIN_ID=52 ros2 launch trihouse_pinky_bringup trihouse_pinky_sim.launch.py robot_id:=PK-01
```

이 launch는 `/trihouse/proximity/front`과 `/trihouse/battery`를 `sim_hardware`가
명시적으로 mock한다. 기본값은 전방 3m·배터리 100%다. stop/slow test는 별도 terminal에서
`front_distance_m` parameter를 변경하거나 실제 `Range` message를 발행해 확인한다.

부저는 `buzzer_indicator_client`가 `IndicatorState.EMERGENCY`일 때만 GPIO 24를 켠다.
Pinky의 실제 부저 결선이 다르면 `gpio_pin` launch parameter를 바꾸고, 비상 해제 후
GPIO가 LOW로 내려가는지 실물에서 반드시 확인한다.

## LCD 한글 폰트

`destination_display`는 목적지 코드 `FROZEN`, `CHILLED`, `AMBIENT`, `PACKING`,
`RETURN`만 각각 `냉동창고`, `냉장창고`, `상온창고`, `포장대`, `대기/충전소 복귀`로
표시한다. 알 수 없는 코드는 LCD를 비운다. 실행 보드에 한글 TrueType 폰트를 배치한 뒤
그 절대 경로를 전달한다.

```bash
ROS_DOMAIN_ID=52 ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  robot_id:=PK-01 font_path:=/opt/trihouse/fonts/NanumGothic.ttf
```

기존 `pinky_emotion` 애니메이션 노드와 LCD SPI 장치를 공유하므로 목적지 표시 운용 중에는
둘을 동시에 실행하지 않는다. `python3-pil`과 `pinky_emotion` 패키지가 Pinky에 설치되어야 한다.
