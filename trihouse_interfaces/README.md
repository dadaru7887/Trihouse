# trihouse_interfaces

> 상태: 공통 계약 구현 — message 16개, service 2개, action 2개가 ROSIDL에 등록되어 있다.

주행 로봇, 로봇팔, 중앙 관제가 공유할 ROS 2 계약 전용 패키지다. 실행 노드와 장치별 로직은 두지 않는다. 공용 계약을 `trihouse_pinky`나 `trihouse_omx` 아래에 두면 다른 장치가 특정 장치 패키지에 의존하므로 저장소 루트에 독립시킨다.

## 문서

- [인터페이스 카탈로그](doc/interface-catalog.md)
- [Pinky ROS 인터페이스 매트릭스](../trihouse_pinky/doc/ros-interface-matrix.md)

## 구성

- `msg/`: 배터리·연결·주행·안전·작업·인계·화물·비전 관측 계약
- `srv/`: 비상 해제와 화물 잠금 요청/응답
- `action/`: 운반 작업과 정밀 도킹의 장기 실행 계약

## 호환성 규칙

1. 이름 변경·필드 삭제·타입 변경은 주행 로봇, 로봇팔, 관제의 합의와 동시 배포 없이는 금지한다.
2. 호환 필드는 메시지 끝에 추가하고, 신규 소비자가 구버전 송신자를 처리할 기본값을 정한다.
3. `schema_version`이 있는 외부 TCP/NDJSON payload와 ROS 계약의 의미를 대응시키되 두 전송 형식을 같은 것으로 취급하지 않는다.
4. 시간 필드는 ROS time으로 통일하고 관측 데이터에는 처리 시각이 아닌 `capture_stamp`를 둔다.
5. 좌표가 있는 필드는 `frame_id` 또는 명시된 기준 프레임을 포함한다.

## 과도한 분리 방지

- 작업 진행률은 `NavigationState.progress`와 `RobotStatus.task_progress`에 둔다.
- 추론 health는 Vision 서버 내부 event/HTTP로 유지한다.
- ROS 비상 상태는 `SafetyState` 하나로 표현하고 gateway가 incident NDJSON으로 바꾼다.
- Domain 간 위치 조회 ROS service는 만들지 않고 REST와 배포 location map을 사용한다.

## 핵심 흐름

- Nav2 action client는 `nav2_command_adapter`만 소유하고 `NavigationState`를 발행한다.
- `task_event_publisher`는 `NavigationState`를 `TaskEvent`로 변환한다.
- Vision bridge는 camera-frame 관측을 발행하고 transformer가 base-frame 관측을 발행한다.
- 상태 publisher는 ROS Topic만 발행하고 gateway가 NDJSON 송신·ACK·재전송을 담당한다.
- 영상 본체는 ROS Topic이 아니라 H.264 RTSP로 전송한다.

전체 endpoint와 QoS는 [인터페이스 카탈로그](doc/interface-catalog.md)를 따른다.
