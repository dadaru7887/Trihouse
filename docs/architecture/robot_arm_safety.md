# OMX 로봇팔 작업·안전 경계

## 소유자

- 업무 순서와 인계 승인: Control Tower Task Manager
- QR/물품 관측: Vision Adapter
- pick/place skill 실행: OMX Adapter와 로봇 제어기
- 충돌·작업공간·비상정지: 로컬 Safety Supervisor
- 결과·감사 기록: FMS Gateway

## 작업 흐름

```text
Task Manager 작업 생성
  → Pinky 인계 위치 도착 확인
  → QR·재고·location 일치 검증
  → OMX skill 및 workspace 승인
  → pick/place 실행
  → 결과와 실패 원인 기록
  → 다음 업무 상태 전이
```

모방학습 정책은 승인된 skill 내부의 동작 후보를 제공할 수 있지만, 작업 ID·물품·위치
일치 검사와 안전 veto를 우회하지 않는다. depth 또는 vision 신뢰도가 부족하면
fail-closed로 중단하고 운영자 확인을 요청한다.

## 금지 연결

- UI 또는 VLM이 joint command를 직접 발행하지 않는다.
- QR 한 항목만으로 pick을 승인하지 않는다.
- Pinky 도착 확인 전에 handover zone을 활성화하지 않는다.
- 정책 timeout, stale observation, 통신 단절 상태에서 동작을 계속하지 않는다.
