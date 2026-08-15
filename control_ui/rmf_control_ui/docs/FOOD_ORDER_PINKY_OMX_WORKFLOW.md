# Food Order, Pinky, and OMX-AI Integration Design (식품 주문 · Pinky · OMX-AI 연동 설계)

## 1. 목적

상온·냉장·냉동 식품 주문을 접수한 뒤 재고와 온도 구역을 판별하고, Pinky가
해당 픽업 스테이션으로 이동하면 OMX-AI가 상품을 적재하며, 적재 성공 후 Pinky가
하차 지점으로 운반하는 전체 과정을 정의합니다.

로봇끼리 직접 다음 동작을 결정하지 않습니다. 중앙 작업 실행엔진이 주문,
재고, Pinky와 OMX-AI의 상태를 확인하고 각 단계의 시작을 승인합니다.

```text
식품 주문 접수
    ↓
상품 온도·재고·유통기한 확인
    ↓
픽업 스테이션과 OMX-AI 결정
    ↓
Pinky 배정 및 픽업 Waypoint 이동
    ↓ 도착 검증
OMX-AI 상품 픽업 및 Pinky 데크 적재
    ↓ 적재 성공 검증
Pinky 하차 Waypoint 이동
    ↓ 인수 확인
주문 완료
```

## 2. 주요 구성요소

### 2.1 주문 관리 서비스

주문 ID, 상품, 수량, 온도 보관 조건과 하차 위치를 받습니다.

```json
{
  "orderId": "ORDER-1042",
  "items": [
    {
      "sku": "MILK-001",
      "name": "우유",
      "quantity": 2,
      "temperature": "chilled"
    }
  ],
  "dropoff": "출고1"
}
```

온도 구분은 다음 표준값을 사용합니다.

| 값 | 의미 |
| --- | --- |
| `ambient` | 상온 |
| `chilled` | 냉장 |
| `frozen` | 냉동 |

### 2.2 재고·피킹 서비스

상품의 실제 저장 위치와 피킹 스테이션을 결정합니다. 상품 온도뿐 아니라 다음
조건을 함께 확인해야 합니다.

- 가용 재고와 예약 재고
- 유통기한과 FEFO(유통기한이 빠른 상품 우선)
- 스테이션과 OMX-AI의 운영 상태
- Pinky가 접근할 수 있는 Lane 경로
- 다른 작업의 스테이션 점유 여부
- 상품 무게와 Pinky 적재 한도

재고는 작업을 배차하기 전에 예약해야 중복 출고를 방지할 수 있습니다.

### 2.3 중앙 작업 실행엔진

다음 단계를 순서대로 실행하고 모든 상태 전이를 기록합니다.

```text
주문 접수 → 재고 예약 → Pinky 배정 → 픽업 이동 → 도착 검증
→ OMX-AI 적재 → 적재 검증 → 하차 이동 → 인수 확인 → 완료
```

### 2.4 장비 에이전트

- Pinky Edge Agent: 경로 수신, 주행, 정지, 위치·배터리·도착 보고
- OMX-AI Edge Agent: 적재 명령 수신, 로봇과 작업 확인, 팔 동작, 결과 보고
- 로컬 게이트웨이: 중앙 실행엔진과 장비 사이의 통신, 연결 상태와 안전 정지 관리

## 3. 스테이션과 맵 연결

각 온도 구역은 픽업 Waypoint와 담당 OMX-AI에 연결되어야 합니다.

```yaml
stations:
  - id: AMBIENT-01
    temperature: ambient
    waypoint: 상온픽업1
    arm_id: OMX-AMBIENT-01

  - id: CHILLED-01
    temperature: chilled
    waypoint: 냉장픽업1
    arm_id: OMX-CHILLED-01

  - id: FROZEN-01
    temperature: frozen
    waypoint: 냉동픽업1
    arm_id: OMX-FROZEN-01
```

OMX-AI 에이전트는 연결할 때 자신이 담당하는 스테이션과 온도 구역을 등록합니다.

```json
{
  "t": "hello",
  "kind": "arm",
  "id": "OMX-CHILLED-01",
  "station": "CHILLED-01",
  "zone": "chilled",
  "model": "OMX-AI"
}
```

## 4. 주문 실행 절차

### 4.1 주문 분류와 재고 예약

실행엔진은 주문 상품을 온도 구역별로 분류하고 FEFO 기준으로 재고를 예약합니다.

```text
ORDER-1042 · 우유 2개
→ chilled
→ CHILLED-01
→ 냉장픽업1
→ OMX-CHILLED-01
→ 출고1
```

### 4.2 Pinky 배정과 픽업 이동

실행엔진은 작업이 없고 배터리와 적재 용량이 충분하며 해당 구역에 접근 가능한
Pinky를 선택합니다. 선택한 Pinky에 Lane 경로를 보냅니다.

```json
{
  "t": "path",
  "task": "TASK-1042",
  "seq": 1,
  "waypoints": [[15.0, 20.0], [28.0, 20.0], [35.0, 30.0]]
}
```

Pinky가 마지막 Waypoint에 도착해 정지하면 다음 내용을 보고합니다.

```json
{
  "t": "arrived",
  "id": "PINKY-01",
  "task": "TASK-1042",
  "waypoint": "냉장픽업1"
}
```

실행엔진은 로봇 ID, 작업 ID, Waypoint, 정지 상태, 적재 공간과 OMX-AI 작업
범위를 모두 확인한 뒤 적재를 승인합니다.

### 4.3 OMX-AI 적재

도착 검증이 끝난 후에만 적재 명령을 전송합니다.

```json
{
  "t": "load",
  "task": "TASK-1042",
  "order": "ORDER-1042",
  "robot": "PINKY-01",
  "item": "우유",
  "sku": "MILK-001",
  "qty": 2,
  "x": 35.0,
  "y": 30.0
}
```

OMX-AI는 다음 조건을 확인합니다.

- 동일 작업을 이미 수행하지 않았는지
- 자신이 담당하는 스테이션과 상품인지
- 준비된 상품 수량이 주문과 일치하는지
- 올바른 Pinky가 적재 위치에 정지했는지
- Pinky 데크에 적재 공간이 있는지
- 팔, 그리퍼와 안전센서가 정상인지

### 4.4 적재 결과

성공하면 OMX-AI는 중앙 실행엔진에 결과를 보고합니다.

```json
{
  "t": "loaded",
  "id": "OMX-CHILLED-01",
  "task": "TASK-1042",
  "order": "ORDER-1042",
  "robot": "PINKY-01",
  "loadedItems": [{"sku": "MILK-001", "quantity": 2}]
}
```

실패하면 작업을 다음 단계로 넘기지 않고 원인을 보고합니다.

```json
{
  "t": "loadFailed",
  "id": "OMX-CHILLED-01",
  "task": "TASK-1042",
  "reason": "상품 파지 실패"
}
```

OMX-AI가 Pinky에 직접 출발 명령을 보내면 안 됩니다. 실행엔진이 `loaded` 내용과
실제 주문을 대조한 뒤 재고를 출고 처리하고 Pinky의 하차 이동을 시작합니다.

### 4.5 하차 이동과 완료

적재 검증 후 실행엔진은 하차 Waypoint까지의 경로를 Pinky에 전송합니다.

```json
{
  "t": "path",
  "task": "TASK-1042",
  "seq": 2,
  "waypoints": [[35.0, 30.0], [42.0, 30.0], [55.0, 18.0]]
}
```

하차 지점 도착만으로 주문을 완료하지 않습니다. 작업자 확인, 자동 하차 설비
응답 또는 데크 센서로 실제 인수를 확인한 후 완료 처리합니다.

## 5. 작업 상태

```text
RECEIVED
→ INVENTORY_RESERVED
→ ROBOT_ASSIGNED
→ MOVING_TO_PICKUP
→ WAITING_FOR_ARM
→ LOADING
→ LOADED
→ MOVING_TO_DROPOFF
→ UNLOADING
→ COMPLETED
```

| 오류 상태 | 의미 |
| --- | --- |
| `OUT_OF_STOCK` | 가용 재고 부족 |
| `ROBOT_BLOCKED` | Pinky가 장애물 또는 경로 문제로 정지 |
| `ARM_OFFLINE` | 담당 OMX-AI 연결 끊김 |
| `LOAD_FAILED` | 파지·적재 또는 검증 실패 |
| `TIMEOUT` | 단계별 제한 시간 초과 |
| `CANCELLED` | 운영자 또는 상위 시스템이 작업 취소 |

현재 상태와 맞지 않는 응답은 거부해야 합니다. 예를 들어
`MOVING_TO_PICKUP` 상태에서 수신한 `loaded`로 하차 이동을 시작해서는 안 됩니다.

## 6. 혼합 온도 주문

### 6.1 한 Pinky의 순차 방문

```text
상온픽업1 → 냉장픽업1 → 냉동픽업1 → 출고1
```

구성이 단순하지만 콜드체인 노출 시간을 줄이기 위해 상온부터 방문하고 냉동을
마지막에 적재하는 것이 좋습니다. 데크 내부의 온도 분리 가능 여부도 확인해야
합니다.

### 6.2 온도별 Pinky 분리

```text
Pinky-01 → 상온 상품 ┐
Pinky-02 → 냉장 상품 ├→ 출고1에서 주문 병합
Pinky-03 → 냉동 상품 ┘
```

처리량과 콜드체인 안정성이 중요하거나 Pinky 데크가 온도별로 분리되지 않았다면
온도별 운반 후 출고 지점에서 주문을 병합하는 방식을 권장합니다.

## 7. 오류·재시도 원칙

- 모든 명령에 변하지 않는 `task`와 `order` ID를 포함합니다.
- 동일한 명령을 재전송해도 중복 적재되지 않도록 멱등성을 보장합니다.
- 이동, 도착 대기, 팔 적재와 하차 확인에 각각 제한 시간을 둡니다.
- `loadFailed` 발생 시 Pinky는 출발하지 않고 안전하게 정지합니다.
- 재시도 전에 상품 위치, 그리퍼, 데크 공간과 작업 ID를 다시 검증합니다.
- 장비 연결이 끊기면 즉시 안전 정지하고 실행엔진에 오류를 기록합니다.
- 재시도 횟수를 초과하면 작업자를 호출하고 재고 예약을 자동 해제하지 말고
  실제 상품 상태를 먼저 확인합니다.

## 8. 구현 체크리스트

- [ ] 주문 입력 API
- [ ] 상품 온도·재고·유통기한 데이터베이스
- [ ] FEFO 재고 예약과 해제
- [ ] 온도 구역별 Waypoint–OMX-AI 매핑
- [ ] Pinky 배차와 `path` 전송
- [ ] Pinky `arrived` 보고 및 위치 검증
- [ ] OMX-AI `load` 전송
- [ ] `loaded`·`loadFailed` 실시간 처리
- [ ] 실제 응답 기반 연속 작업 단계 전환
- [ ] 하차 및 인수 완료 확인
- [ ] 단계별 타임아웃, 재시도와 취소
- [ ] 작업·재고·장비 오류 이력 영구 저장
- [ ] 다수 Pinky의 RMF 교통 협상과 충돌 회피

## 9. 현재 UI와 실장비의 경계

`rmf_control_ui`의 연속 작업 편집기와 실행엔진은 현재 앱 내부 동작을 확인하는
단계입니다. 실제 장비 운영에서는 로컬 Linux Edge Agent와 게이트웨이가 Pinky 및
OMX-AI에 명령을 전달해야 합니다. 실제 OMX-AI 단계는 고정 시간이 아니라 반드시
`loaded` 응답을 받은 후 완료되어야 합니다.
