# trihouse_interfaces

> 상태: 부분 구현 — ROS 2 패키지와 `StreamHealth.msg`가 구현되었고 나머지 계약은 초안이다.

주행 로봇, 로봇팔, 중앙 관제가 공유할 ROS 2 계약 전용 패키지다. 실행 노드와 장치별 로직은 두지 않는다. 공용 계약을 `trihouse_pinky`나 `trihouse_omx` 아래에 두면 다른 장치가 특정 장치 패키지에 의존하므로 저장소 루트에 독립시킨다.

## 문서

- [인터페이스 카탈로그](doc/interface-catalog.md)
- [Pinky ROS 인터페이스 매트릭스](../trihouse_pinky/doc/ros-interface-matrix.md)

## 계획된 구성

- `msg/`: 상태, 이벤트, 관측, 인수인계 계약
- `srv/`: 비상 해제와 위치 조회 요청/응답
- `action/`: 운반 작업과 정밀 도킹의 장기 실행 계약

## 호환성 규칙

1. 이름 변경·필드 삭제·타입 변경은 주행 로봇, 로봇팔, 관제의 합의와 동시 배포 없이는 금지한다.
2. 호환 필드는 메시지 끝에 추가하고, 신규 소비자가 구버전 송신자를 처리할 기본값을 정한다.
3. `schema_version`이 있는 외부 TCP/NDJSON payload와 ROS 계약의 의미를 대응시키되 두 전송 형식을 같은 것으로 취급하지 않는다.
4. 시간 필드는 ROS time으로 통일하고 관측 데이터에는 처리 시각이 아닌 `capture_stamp`를 둔다.
5. 좌표가 있는 필드는 `frame_id` 또는 명시된 기준 프레임을 포함한다.

## 첫 구현 완료 조건

- `package.xml`과 `CMakeLists.txt`를 추가하고 `rosidl_generate_interfaces`로 모든 확정 계약을 빌드한다.
- 세 트랙 담당자가 필드와 QoS를 검토한다.
- 예제 publisher/subscriber 또는 인터페이스 직렬화 테스트가 통과한다.

## 현재 구현

- `msg/StreamHealth.msg`: 카메라 식별자, 상태, FPS, 비트레이트, 마지막 프레임 시각과 진단 사유를 전달한다.
- 상태 상수: `UNKNOWN`, `HEALTHY`, `DEGRADED`, `DISCONNECTED`, `RECOVERING`.
- 영상 본체는 이 패키지나 ROS 2 토픽으로 전달하지 않는다.
