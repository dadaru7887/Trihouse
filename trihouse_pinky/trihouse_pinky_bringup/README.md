# trihouse_pinky_bringup

> 상태: 구현 계획. 현재는 README만 존재한다.

## 1. 목적과 책임

벤더 하드웨어/Nav2 launch와 Trihouse 기능 노드를 하나의 온보드 실행 구성으로 조합하고 로봇별 값을 주입한다. 업무 로직은 소유하지 않는다.

## 2. 넣지 않을 기능

작업 상태 머신, 영상 처리, 안전 판정, docking 제어, 중앙 UI/DB 프로세스를 넣지 않는다.

## 3. 계획된 실행 요소

- `pinky_bringup/bringup_robot.launch.xml`
- `pinky_navigation/bringup_launch.xml`
- `pinky_imu_bno055`, `pinky_sensor_adc`, 표시 장치 노드
- safety, vision, docking, fleet 노드
- 실제 로봇용 최상위 launch와 동일 인터페이스의 simulation launch
- 센서, Nav2, AMCL, map, safety, heartbeat, 선택 기능 health를 검사하는 readiness aggregator

## 4. 발행·구독 토픽

자체 업무 토픽은 두지 않는다. readiness aggregator는 필수 health/센서 토픽을 구독하고 준비 상태를 fleet에 제공할 계획이다. 정확한 이름은 [매트릭스](../doc/ros-interface-matrix.md)에서 확정한다.

## 5. 제공·호출 서비스

없음. lifecycle 상태 확인이 필요하면 Nav2 표준 서비스를 호출한다.

## 6. 제공·호출 액션

없음. `navigate_to_pose` 가용성을 readiness 조건으로 확인한다.

## 7. 사용하는 공용 인터페이스

`StreamHealth`, `RobotStatus`의 health/readiness 필드 사용을 검토한다.

## 8. pinky_pro 참조

하드웨어와 navigation launch를 include하고 각 센서/표시 노드를 실행한다. 벤더 파일은 수정하지 않고 Nav2 속도 출력은 overlay/remap으로 `/cmd_vel_nav`에 연결한다.

## 9. 설정 파일 후보

`robot_id`, 카메라 device/RTSP URI, map 이름/revision, 관제 host/port, safety·docking 임계값을 가진 `pinky_1.yaml`, `pinky_2.yaml`, `sim.yaml`을 계획한다.

## 10. 구현 순서와 완료 조건

1. 벤더 bringup + safety만 포함한 최소 launch를 만든다.
2. Nav2 출력 remap과 모터 입력을 확인한다.
3. 센서와 readiness 검사를 추가한다.
4. vision, docking, fleet을 차례로 조합한다.

완료 조건은 최상위 launch 한 번으로 온보드 필수 프로세스가 뜨고, readiness 전에는 작업을 거절하며, `/cmd_vel` 발행자가 safety 하나뿐인 것이다.

