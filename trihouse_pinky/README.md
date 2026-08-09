# trihouse_pinky

> 상태: safety·fleet·io·bringup의 최소 수직 흐름은 구현 중이다. Vision 이외의 docking,
> 관제 TCP/NDJSON과 실물 Pinky 검증은 아직 완료되지 않았다.

Pinky-Pro 벤더 자산 위에 Trihouse 운반 로봇 기능을 추가하는 패키지 모음이다. `pinky_pro`는 수정하지 않고 launch include, 토픽 구독, 서비스 호출, remap 또는 알고리즘 참고로만 사용한다.

## 패키지

| 패키지 | 책임 | 상태 |
|---|---|---|
| [bringup](trihouse_pinky_bringup/README.md) | 벤더 launch와 Trihouse 노드 조합, 로봇별 설정 | 최소 구현 |
| [fleet](trihouse_pinky_fleet/README.md) | 관제 연결, 작업 상태 머신, Nav2 실행, telemetry | 최소 구현 |
| [vision](trihouse_pinky_vision/README.md) | 카메라 H.264/RTSP 송신, 상태, 캘리브레이션/TF | 계획 |
| [safety](trihouse_pinky_safety/README.md) | 모든 속도 명령의 최종 안전 게이트 | 최소 구현 |
| [docking](trihouse_pinky_docking/README.md) | ArUco 기반 마지막 정밀 정차 | 계획 |

## 전체 문서

- [아키텍처](doc/architecture.md)
- [관제 UI 연동](doc/control-ui-integration.md)
- [ROS 인터페이스 매트릭스](doc/ros-interface-matrix.md)
- [pinky_pro 참조 지도](doc/pinky-pro-reference-map.md)
- [구현 순서](doc/implementation-order.md)
- [Pinky SR 구현·실행 안내](doc/pinky-sr-implementation.md)
- [공용 인터페이스 카탈로그](../trihouse_interfaces/doc/interface-catalog.md)

## 변하지 않는 경계

- 중앙 관제 UI/DB는 로봇 launch와 별도 프로세스로 실행한다.
- 영상 본체는 RTSP/SRT로 전송하고 ROS 2에는 상태와 관측 결과만 전달한다.
- Nav2와 docking 출력은 각각 `/cmd_vel_nav`, `/cmd_vel_dock`으로 보내며 safety만 모터용 `/cmd_vel`을 발행한다.
- 노드가 실행 중이라는 이유만으로 준비 완료로 보지 않고 readiness gate를 통과한 뒤 작업을 받는다.
