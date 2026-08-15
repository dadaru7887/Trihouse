# ROS Control System Waypoint Architecture Mapping (ROS 관제 시스템 Waypoint 아키텍처 매핑)

## 1. 문서 목적

이 문서는 Open-RMF 맵의 주요 Waypoint 속성이 ROS 2 관제 시스템, Nav2,
로봇 하드웨어 및 외부 설비와 어떻게 연결되는지 설명합니다.

`building.yaml`의 Waypoint 속성은 위치와 역할을 정의합니다. 실제 픽업, 대기,
주차 및 충전 동작은 Fleet Adapter, 관제 서버와 로봇별 Action/Service 서버가
구현해야 합니다. 즉, 속성을 맵에 지정하는 것만으로 하드웨어 동작이 자동
완성되는 것은 아닙니다.

## 2. 전체 책임 구조

```text
주문·작업 시스템
       │ 작업 요청 및 상태
       ▼
Open-RMF / 관제 서버
       │ 경로 계획, 교통 협상, 자원 점유
       ▼
Fleet Adapter
       │ Nav2 Goal, Cancel, 로봇 명령 변환
       ▼
로봇 ROS 2 시스템
       ├─ Nav2 Action Server
       ├─ 그리퍼·컨베이어 Action/Service
       ├─ Docking Action Server
       └─ 센서·Localization
              │
              ▼
외부 설비·PLC
       Modbus TCP/RTU, TCP/IP, ROS Topic/Service/Action
```

핵심 원칙은 다음과 같습니다.

- Open-RMF는 작업 배정, 경로 및 공유 공간의 교통 조정을 담당합니다.
- Fleet Adapter는 RMF 경로를 로봇이 이해하는 Nav2 명령으로 변환합니다.
- 로봇의 그리퍼, 컨베이어 및 정밀 도킹은 별도의 ROS 2 인터페이스가 담당합니다.
- 외부 설비와 로봇의 물리 동작은 반드시 상태 확인과 시간 제한이 있는
  Handshake로 동기화합니다.

## 3. 픽업 및 드랍오프

### 3.1 Open-RMF 맵 속성

- 픽업: `pickup_dispenser`
- 드랍오프: `dropoff_ingestor`

이 속성은 단순한 이동 좌표가 아니라 해당 위치에서 연동할 설비 또는 작업
엔드포인트의 이름을 나타냅니다. 맵에 기록한 이름과 실제 Dispenser/Ingestor
장치 설정의 이름이 일치해야 합니다.

### 3.2 ROS 실행 구조

1. 관제 서버가 픽업 또는 드랍오프 작업을 로봇에 배정합니다.
2. Fleet Adapter가 Nav2 Action Client를 통해 해당 Waypoint로 이동 Goal을
   전달합니다.
3. Nav2가 `SUCCEEDED`를 반환하면 위치 및 자세 허용 오차를 다시 확인합니다.
4. 로봇과 외부 설비가 준비 Handshake를 수행합니다.
5. 그리퍼, 리프트 또는 컨베이어의 ROS Action/Service를 호출합니다.
6. 센서로 적재·하차 결과를 확인합니다.
7. 완료 상태를 설비와 관제 서버에 보고한 뒤 다음 작업을 시작합니다.

### 3.3 권장 Handshake 상태

```text
IDLE
  → RESERVE_REQUESTED
  → RESERVED
  → ROBOT_ARRIVED
  → READY
  → TRANSFERRING
  → VERIFYING
  → COMPLETED
```

어느 단계에서든 오류 또는 제한 시간 초과가 발생하면 다음과 같이 처리합니다.

```text
FAILED 또는 TIMEOUT
  → 장비 정지
  → 점유권 유지 또는 안전 해제
  → 관제 서버에 실패 원인 보고
  → 운영자 복구 또는 제한된 횟수만 재시도
```

PLC 통신은 Modbus TCP/RTU나 장비 전용 TCP/IP 프로토콜을 사용할 수 있습니다.
ROS 시스템 내부에서는 Topic보다 결과와 취소 상태가 명확한 Action 또는 Service를
우선 고려합니다. 반복 전송에 대비하여 동일 요청 ID를 다시 받아도 물리 동작이
중복 실행되지 않는 멱등성도 필요합니다.

## 4. 일반 대기 포인트

### 4.1 Open-RMF 맵 속성

- `is_holding_point`

Holding Point는 교차로, 좁은 통로 또는 공유 자원에 진입하기 전에 로봇을 잠시
정지시킬 수 있는 교통 제어 지점입니다. 장기 주차 장소와는 구분합니다.

### 4.2 ROS 실행 구조

1. Open-RMF가 로봇들의 예상 경로와 시간을 비교해 충돌 가능성을 판단합니다.
2. Fleet Adapter는 승인된 경로 구간까지만 로봇이 진행하도록 명령합니다.
3. 우선순위가 낮거나 점유권이 없는 로봇은 Holding Point에서 대기합니다.
4. 공유 구간이 해제되면 다음 경로 또는 Nav2 Goal을 전달합니다.

구현 방식에 따라 진행 중인 Nav2 Goal을 취소한 뒤 Holding Point로 새 Goal을
전달할 수 있습니다. 다만 Open-RMF의 경로 협상과 별개인 독립 세마포어를 동시에
운영하면 서로 다른 두 제어기가 로봇을 막을 수 있으므로, 점유권의 최종 관리자를
하나로 정해야 합니다.

좁은 통로처럼 동시에 한 대만 진입해야 하는 구간은 동일한 Mutex 그룹으로
묶습니다. 점유권은 로봇 진입 전에 획득하고 완전히 빠져나온 뒤 해제해야 합니다.

## 5. 장기 주차 포인트

### 5.1 Open-RMF 맵 속성

- `is_parking_spot`

Parking Spot은 작업 큐가 비었거나 로봇을 장시간 대기시킬 때 사용하는 위치입니다.
통행 경로를 막지 않고 다른 로봇이 접근할 수 있도록 충분한 간격을 확보해야 합니다.

### 5.2 ROS 실행 구조

1. 관제 서버가 Idle 상태의 로봇과 비어 있는 Parking Spot을 찾습니다.
2. 거리, 배터리, 다음 작업 예상 위치와 점유 상태를 기준으로 주차 위치를
   할당합니다.
3. Fleet Adapter가 주차 위치로 이동을 요청합니다.
4. 도착 후 로봇 상태를 `PARKED` 또는 `IDLE`로 전환합니다.
5. 새 작업이 배정되면 주차 점유를 해제하고 작업 경로를 시작합니다.

주차 중 비필수 진단 데이터의 송신 주기를 낮춰 네트워크 사용량을 줄일 수
있습니다. 그러나 장애물 감지, 비상 정지, 배터리, 화재 감시와 같은 안전 관련
데이터는 계속 유지해야 합니다. AMCL 등 Localization 갱신 주기를 낮추는 최적화는
재출발 시 위치 불확실성이 커질 수 있으므로 실제 로봇에서 충분히 검증한 경우에만
적용합니다.

## 6. 충전 포인트

### 6.1 Open-RMF 맵 속성

- `is_charger`

충전 Waypoint는 일반 Nav2 주행의 종점이면서 정밀 도킹 절차의 시작점입니다.
Fleet 설정의 충전 Waypoint 이름과 맵의 이름이 일치해야 합니다.

### 6.2 2단계 접근 방식

1. **거친 접근**: Nav2로 충전기 앞의 사전 도킹 위치까지 이동합니다.
2. **정밀 도킹**: 전용 Docking Action Server가 저속으로 최종 정렬 및 접촉을
   수행합니다.

일반 주행 Localization만으로 충전 단자의 요구 정밀도를 만족하기 어려울 수
있으므로 다음 센서를 조합할 수 있습니다.

- LiDAR 반사판 또는 충전기 형상 매칭
- QR 코드 및 OpenCV 기반 영상 정렬
- AprilTag 또는 AR 마커 기반 상대 위치 추정
- 충전기 유도 신호, 접촉 센서 및 전류 센서

`ar_track_alvar` 같은 특정 패키지에 시스템을 고정하기보다는 사용 중인 ROS 2
배포판에서 유지되는 마커 검출 패키지와 카메라 드라이버의 지원 여부를 확인해야
합니다.

### 6.3 권장 Docking 상태

```text
NAVIGATING_TO_STAGING
  → SEARCHING_TARGET
  → ALIGNING
  → APPROACHING
  → CONTACT_CHECK
  → CHARGING_CONFIRMED
```

충전 전류 또는 충전기 상태가 제한 시간 안에 확인되지 않으면 후진하여 안전
거리로 빠진 다음 제한된 횟수만 재시도합니다. 반복 실패하면 해당 충전기를
사용 불가로 표시하고 다른 충전기 또는 운영자 점검을 요청합니다.

## 7. 공통 안전 및 장애 처리

모든 특수 Waypoint 동작에는 다음 항목이 필요합니다.

- 요청 ID를 이용한 중복 실행 방지
- 단계별 제한 시간과 명확한 실패 코드
- Action 취소 시 하드웨어를 안전 상태로 전환하는 처리
- 로봇과 설비 양쪽의 Emergency Stop 반영
- 점유권을 획득한 주체와 해제 조건 기록
- MySQL 작업 기록과 ROS 로그의 공통 작업 ID
- 통신 단절 후 상태 재동기화 절차
- 수동 복구 중 자동 작업 재개 방지

## 8. 권장 ROS 2 인터페이스 예시

| 기능 | 권장 인터페이스 | 주요 결과 |
|---|---|---|
| Waypoint 이동 | Nav2 `NavigateToPose` Action | 성공, 취소, 실패 |
| 픽업·하차 | 장비별 ROS 2 Action | 적재 확인, 하차 확인, 오류 코드 |
| PLC 단발 명령 | ROS 2 Service 또는 PLC Gateway | 요청 수락 여부 |
| PLC 상태 스트림 | ROS 2 Topic | 준비, 동작 중, 완료, 고장 |
| 정밀 충전 도킹 | Docking Action | 접촉 및 충전 확인 |
| 공유 구간 점유 | Open-RMF 경로 협상 및 Mutex | 소유 로봇, 점유 상태 |

Action 이름과 메시지 형식은 로봇 및 설비 드라이버에 따라 달라질 수 있습니다.
관제 서버는 벤더별 인터페이스를 직접 호출하기보다 Fleet Adapter나 장비 Gateway를
통해 공통 상태 모델로 변환하는 것이 좋습니다.

## 9. 구현 완료 조건

각 Waypoint 종류는 다음 조건을 만족해야 운영 준비가 완료된 것으로 판단합니다.

- 픽업·드랍오프: 이동, 설비 예약, 물리 이송과 결과 검증이 하나의 작업 ID로 연결됨
- Holding Point: 점유권 없는 로봇이 공유 구간에 진입하지 않음
- Parking Spot: 중복 배정이 방지되고 새 작업 시 점유가 정상 해제됨
- Charger: Nav2 접근과 정밀 도킹이 분리되며 실제 충전 전류까지 확인됨
- 공통: 실패, 취소, 통신 단절 및 재시작 시 상태가 안전하게 복구됨
