# trihouse_pinky_safety

> 상태: 구현 계획. 현재는 README만 존재한다.

## 1. 목적과 책임

모든 속도 명령의 최종 게이트다. LiDAR, 근접 센서, 사람 검출과 운영 제한을 종합해 `CLEAR/SLOW/STOP/EMERGENCY`를 판정한다.

## 2. 넣지 않을 기능

경로 계획, 작업 상태 머신, 마커 docking 제어, 서버 영상 추론을 넣지 않는다.

## 3. 계획된 노드와 작업

- `velocity_gate`: 두 속도 입력 중 허용된 명령 선택/제한
- `safety_supervisor`: 센서 freshness, 거리, 사람, keep-out 판정
- 비상 래치와 명시적 해제
- speed limit/costmap filter 연동과 비상 표시 keep-alive

## 4. 발행·구독 토픽

`/cmd_vel_nav`, `/cmd_vel_dock`, `/scan`, `/trihouse/proximity/front`,
`/trihouse/vision/person_detection/base`, `/trihouse/safety/keep_out_zones`를 구독한다.
`/cmd_vel`, `/trihouse/safety/state`, `/trihouse/safety/proximity_stop`을 발행한다.

## 5. 제공·호출 서비스

`/trihouse/safety/clear_emergency` (`ClearEmergency`)를 제공한다. LED 색상은
`IndicatorState`를 통해 io 역할에 전달한다.

## 6. 제공·호출 액션

없음. 비상 또는 keep-out 발생 시 fleet/Nav2 cancel 경계는 별도 인터페이스로 확정한다.

## 7. 사용하는 공용 인터페이스

`PersonDetection`, `KeepOutZone`, `SafetyState`, `ClearEmergency`.

## 8. pinky_pro 참조

LiDAR, 초음파와 모터 입력을 이용한다. IR은 운영 안전 입력에 사용하지 않으며 벤더 코드는 변경하지 않는다.

## 9. 설정 파일 후보

센서별 stale timeout, stop/slow 거리, 사람 검출 최대 지연, 입력 우선순위, 최대 선속도/각속도, 비상 표시 주기와 keep-out policy를 계획한다.

## 10. 구현 순서와 완료 조건

1. 입력 timeout 시 0을 내는 최소 gate를 테스트한다.
2. Nav2/docking arbitration과 속도 clamp를 추가한다.
3. LiDAR/근접 센서 감속·정지를 추가한다.
4. 사람/keep-out/비상 래치를 추가한다.

완료 조건은 정상·stale·노드 장애·비상 상황에서 fail-safe 정지가 검증되고, 실제 ROS graph에서 `/cmd_vel`의 유일한 운영 발행자인 것이다.


## 안전 필드 (2026-08-20)

세 가지 모양을 쓰고, 지금 내리려는 **명령이 모양을 고른다.**

| 명령 | 보호 필드(STOP) | 왜 |
|---|---|---|
| 전진 | 로봇 폭 직사각형, **앞** | 위험은 경로 위에 있다. 좁은 통로 옆벽은 스쳐 지나갈 뿐이다 |
| 후진 | 로봇 폭 직사각형, **뒤** | 후진 도킹에서 위험은 뒤에 있다 |
| 제자리 회전 | 외접원 | 회전은 원 전체를 쓸고 지나간다. 옆에 있는 것이 곧 부딪히는 것이다 |

여유는 회전 중심이 아니라 **몸 끝**에서 잰다. 이 로봇은 앞뒤로 대칭이 아니어서
(바퀴 축이 앞쪽, 바구니가 뒤), 중심에서 재면 같은 `stop_distance_m` 이 앞에서는
범퍼까지 0.26 m, 뒤에서는 바구니까지 0.13 m 를 뜻하게 된다.

**후진에는 초음파를 쓰지 않는다.** `ultrasonic_link` 는 정면만 본다. 섞으면 뒤가
막혔는데 "정면 3 m" 가 최솟값 경쟁에서 이겨 통과한다 — 시뮬의 `sim_hardware` 는
실제로 3.0 m 상수를 낸다. 후진 근거는 라이다뿐이다.

감속(SLOW)의 근거는 벽이 아니라 **사람**이다. 벽은 지도에 있는 정적 장애물이고
옆을 스칠 뿐이라, 그것으로 속도를 낮추면 2.20 x 2.70 m 방에서는 늘 낮춘 상태가
된다. 사람은 카메라(`PersonDetection`)가 알려 준다.

발자국 값(`FOOTPRINT_FRONT_M`·`FOOTPRINT_REAR_M`·`PROTECTIVE_HALF_WIDTH_M`)은
`nav2_params.yaml` 과 계약 테스트로 묶여 있다. 한쪽만 고치면 테스트가 잡는다 —
갈라지면 Nav2 가 낸 회전을 gate 가 거절하거나(주행 불가), gate 가 통과시킨
회전에서 로봇이 벽을 친다. `SWEPT_RADIUS_M` 은 그 셋에서 파생한다.
