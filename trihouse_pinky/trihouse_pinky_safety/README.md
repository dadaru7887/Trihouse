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

`/cmd_vel_nav`, `/cmd_vel_dock`, `/scan`, 초음파/IR, base-frame `PersonDetection`, `KeepOutZone`을 구독한다. `/cmd_vel`, safety 상태, `EmergencyAlert`, 필요 시 `nav2_msgs/SpeedLimit`을 발행할 계획이다.

## 5. 제공·호출 서비스

`ClearEmergency`를 제공하고 LED/램프/LCD 표시 서비스를 호출한다.

## 6. 제공·호출 액션

없음. 비상 또는 keep-out 발생 시 fleet/Nav2 cancel 경계는 별도 인터페이스로 확정한다.

## 7. 사용하는 공용 인터페이스

`PersonDetection`, `KeepOutZone`, `EmergencyAlert`, `ClearEmergency`.

## 8. pinky_pro 참조

LiDAR, 초음파/IR, 모터 입력과 표시 서비스를 토픽 구독/서비스 호출로 이용한다. 벤더 코드는 변경하지 않는다.

## 9. 설정 파일 후보

센서별 stale timeout, stop/slow 거리, 사람 검출 최대 지연, 입력 우선순위, 최대 선속도/각속도, 비상 표시 주기와 keep-out policy를 계획한다.

## 10. 구현 순서와 완료 조건

1. 입력 timeout 시 0을 내는 최소 gate를 테스트한다.
2. Nav2/docking arbitration과 속도 clamp를 추가한다.
3. LiDAR/근접 센서 감속·정지를 추가한다.
4. 사람/keep-out/비상 래치를 추가한다.

완료 조건은 정상·stale·노드 장애·비상 상황에서 fail-safe 정지가 검증되고, 실제 ROS graph에서 `/cmd_vel`의 유일한 운영 발행자인 것이다.

