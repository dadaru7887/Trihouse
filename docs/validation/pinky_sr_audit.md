# Pinky SR 정적 구현 완료 감사

이 문서는 `Pinky SR.md`의 High/Medium 9개 요구사항을 현재 코드와 자동 테스트에 대조한
결과다. 여기서 **정적 구현 완료**는 ROS 2 없이 실행할 수 있는 정책·입력 검증·상태 전이가
테스트되었다는 뜻이며, Pinky 실물 또는 Gazebo에서 주행·센서·GPIO가 동작했다는 뜻은 아니다.

## 범위와 경계

- Pinky는 FMS가 승인한 위치까지 이동하고 정차하며, 자동 하차하지 않는다.
- FMS는 전역 배차·예약·복귀 판단을 맡고, Pinky는 Nav2 목표 실행과 안전한 정차를 맡는다.
- Safety Supervisor만 최종 `/cmd_vel`을 발행한다. Vision은 사람 위험 정보를 전달할 뿐
  속도 명령을 만들지 않는다.
- 사람 쓰러짐의 인식 방식은 별도 기술 조사 대상이다. 이 문서는 그 감지 모델을 완료 근거로
  사용하지 않으며, FMS의 명시적 비상 요청이 Pinky 비상 latch로 들어오는 경계만 다룬다.

## 요구사항별 증거

| SR | 정적 구현 근거 | 자동 테스트 근거 | 남은 런타임 검증 |
| --- | --- | --- | --- |
| SR_03 상태 공유 | `trihouse_pinky_fleet/status_node.py`가 위치·배터리·적재·안전·주행·오류를 `RobotStatus`로 1초/상태 변경 시 발행하고 `gateway_node.py`가 NDJSON으로 전달한다. | `StatusPolicyTest`의 stale 센서 작업 불가 판정 | 실제 `RobotStatus` 직렬화와 FMS TCP 연결, OMX 상태 agent |
| SR_23 사람 충돌 방지 | `trihouse_pinky_safety/policy.py`, `safety_supervisor_node.py`가 전방 거리·LiDAR·사람 위험·stale sensor를 최종 속도 gate에 적용한다. | `SafetyPolicyTest`의 초음파 우선 정지, 보호거리, timeout stop | `/scan`, `/us_sensor/range`, YOLO 결과와 Nav2 속도 입력 동시 주행 |
| SR_24 물품 운반 | `fleet_node.py`가 `ExecuteTransport`를 `NavigateToPose`로 변환하고, 도착과 정차 조건을 모두 확인한다. | `TransportWorkflowTest`의 cargo/readiness 거부 및 도착 정차 조건 | Nav2 action 결과와 실제 map frame/정차 정확도 |
| SR_25 대기·충전소 복귀 | `battery_policy.py`(FMS), `workflow.py`, `fleet_node.py`가 일반 이동과 대기/충전 위치 복귀를 구분한다. | 빈 바구니 복귀 및 비상 이후 health-check 전환 | 실제 소비계수, 대기·충전 waypoint, 충전은 제외 |
| SR_45 포장대 대기·재배정 | `workflow.py.reassign()`이 인계 대기 중 같은 job/cargo를 유지한 채 FMS 새 목표로 전환한다. | `test_waiting_handover_can_move_to_fms_reassigned_packing_station` | FMS 포장대 예약과 Pinky action 취소/새 목표 연결 |
| SR_48 전달 위치 운반 | `fleet_node.py`는 적재 확인 전 출발을 거부하고, 도착 뒤 `WAITING_HANDOVER` 상태를 유지한다. | cargo readiness 거부, 도착·정차, handover confirm 테스트 | OMX handover event 및 작업자 전달 UI 연결 |
| SR_49 포장 준비 표시 | `destination_display.py`는 승인된 목적지 코드만 한글 LCD 문구로 바꾸며, `indicator.py`는 안전 표시 우선순위를 고정한다. | 허용 외 destination clear, 비상 > 사람 > 일반 표시 테스트 | Korean font asset, Pinky LCD, LED/ws2811, GPIO buzzer |
| SR_54 비상 대응 | `safety_supervisor_node.py`가 비상 latch·keep-out을 적용하고, `gateway_node.py`는 검증된 비상/해제/구역 명령만 전달한다. | latch 지속, polygon 검증, 익명 해제 거부 테스트 | RMF temporary keep-out, 물리 LED/buzzer, FMS 승인 요청 |
| SR_57 해제 후 복귀·재투입 | `recovery_health.py`, `workflow.py`가 지정 위치 복귀 뒤 odom/scan/ultrasonic/battery/cargo를 점검하고 자동 재개를 막는다. | stale battery 또는 cargo가 있으면 `UNAVAILABLE`, 정상 점검 후에만 `IDLE` | 실제 토픽 주기, 화물 상태 source, FMS 새 작업만 수락하는 통합 시험 |

## 재현 가능한 정적 검증

명령별 의미, 테스트를 읽는 순서와 headless Gazebo 부분 검증은
[Pinky SR 수동 정적 검증과 코드 분석](pinky_sr_manual_validation.md)에 정리한다.

```bash
cd /home/syw/Trihouse
PYTHONPATH='trihouse_pinky/trihouse_pinky_fleet:trihouse_pinky/trihouse_pinky_safety:trihouse_pinky/trihouse_pinky_io:trihouse_pinky/trihouse_pinky_bringup' \
python3 -m unittest -v trihouse_pinky.test.test_pinky_sr_policies trihouse_pinky.test.test_eta_policy
python3 -m compileall -q trihouse_pinky
```

`test_pinky_sr_policies.py`는 ROS 라이브러리를 import하지 않는 순수 정책 시험이다. 따라서
통과 결과는 구현 계약의 회귀 방지 증거이며, ROS graph 또는 장비 동작의 대체 증거가 아니다.

## 다음 실행 순서

1. `trihouse_pinky_bringup` launch를 Gazebo에서 실행해 `/scan`, `/odom`, `/cmd_vel`과
   readiness 상태를 확인한다.
2. simulator mock의 초음파·배터리·cargo를 바꿔 safety stop, return, recovery health를
   topic 단위로 확인한다.
3. 실물 Pinky에서 LCD font, LED, GPIO buzzer와 거리 임계값·Nav2 정차 오차를 보정한다.
4. FMS/OMX와 연결할 때 status heartbeat, handover event, emergency clear 권한을 통합 시험한다.
