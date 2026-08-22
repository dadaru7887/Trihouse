# Pinky 협로 주행 센서 시간축 안정화

> 상태: 설계 및 단위 필터 초안. `safety_supervisor` 실제 연결과 시뮬레이션
> 파라미터 검증 전에는 이 문서의 권장값을 운영값으로 간주하지 않는다.

## 1. 목적

협로에서는 LiDAR가 벽의 반사점·각도 변화로 짧은 거리 값을 한 프레임만 내거나,
초음파가 다중 반사로 단발 echo를 낼 수 있다. 이 값을 그대로 STOP 판정에 넣으면
로봇이 실제 장애물 없이 멈췄다 출발하기를 반복한다.

시간축 안정화의 목적은 **한 번의 노이즈로 인한 불필요한 STOP을 줄이는 것**이다.
장애물을 평균으로 희석하거나 센서가 끊긴 상태에서 주행을 허용하는 기능은 아니다.

## 2. 전체 판단 흐름

```text
LiDAR scan / 초음파 Range
        │
        ├─ 유효성 검사: NaN, inf, min/max 범위 밖 값 폐기
        │
        ├─ 공간 필터
        │   ├─ LiDAR: 진행 방향 직사각 보호 필드의 여유 거리
        │   └─ 초음파: 전방 거리
        │
        ├─ 시간 필터
        │   ├─ LiDAR: 최근 3 scan 중앙값
        │   └─ 초음파: 최근 5 sample 중앙값
        │
        ├─ 센서 융합: 전진 시 min(LiDAR, 초음파), 후진 시 LiDAR만
        │
        └─ Safety gate: STOP / SLOW / CLEAR
```

## 3. LiDAR: 3-scan 중앙값

LiDAR는 먼저 모든 빔을 평균하지 않는다. 한 scan에서 로봇 폭을 반영한 **직사각
보호 필드** 안의 가장 가까운 경로 여유를 하나 계산하고, 그 거리 값 세 개의 중앙값을
쓴다.

예를 들어 실제 여유가 약 `0.80m`인데 한 프레임만 `0.12m`가 들어오면 다음과 같다.

```text
입력:     0.80, 0.78, 0.12
중앙값:   0.78m
```

따라서 단발 반사로 STOP이 흔들리는 현상을 줄인다. 반면 실제 장애물이 계속 있으면
세 scan 안에 중앙값도 가까워져 STOP이 걸린다.

LiDAR 빔별 평균을 쓰지 않는 이유는 벽과 사람의 각도·거리 변화가 빔마다 다르기
때문이다. 빔을 섞으면 실제 경로 위 물체의 위치를 흐리게 만들 수 있다.

## 4. 초음파: 5-sample 중앙값

초음파에는 더 긴 5-sample 창을 쓴다. 초음파는 단발 다중반사 echo가 발생하기 쉬우며,
실제 발행 주기가 LiDAR보다 낮은 경우가 많기 때문이다.

```text
입력:     0.70, 0.71, 0.69, 0.70, 0.08
중앙값:   0.70m
```

`NaN`, `inf`, `min_range` 미만, `max_range` 초과 값은 창에 넣지 않는다. 버린 값은
센서 수신 시각도 갱신하지 않는다. 즉 값이 계속 비정상이면 freshness timeout이 나고
안전 gate는 STOP으로 전환한다.

## 5. 융합과 방향 규칙

| 주행 방향 | 사용 근거 | 이유 |
| --- | --- | --- |
| 전진 | `min(필터된 LiDAR, 필터된 전방 초음파)` | 둘 중 가까운 물체를 위험으로 본다. |
| 후진 | 필터된 후방 LiDAR만 | 현재 초음파는 전방을 보므로 후진 안전 근거가 될 수 없다. |
| 제자리 회전 | LiDAR의 회전 외접원 검사 | 회전은 옆 공간까지 쓸고 지나간다. |

협로의 옆벽은 LiDAR 직사각 보호 필드 바깥에 있어 전진 STOP 근거가 되지 않는다.
그러나 회전 중에는 옆벽과 충돌할 수 있으므로 외접원 검사를 더 보수적으로 적용한다.

## 6. STOP 해제 히스테리시스

STOP 진입과 해제에 같은 거리 경계를 쓰면 경계 근처 노이즈로 STOP/CLEAR가 반복된다.
따라서 다음 규칙으로 구현한다.

```text
STOP 진입:  필터 거리 ≤ stop_distance_m
STOP 해제:  필터 거리 ≥ stop_distance_m + release_hysteresis_m 가
            release_confirmations회 연속 관측될 때
```

초기 권장값은 `stop_distance_m=0.30m`, `release_hysteresis_m=0.10m`,
`release_confirmations=3`이다. 실제 제동거리·센서 주기·협로 폭을 측정한 뒤 조정한다.

단, 사람 감지·비상 latch·센서 timeout·keep-out은 히스테리시스로 해제하지 않는다.
각각의 별도 안전 절차가 해제 권한을 가진다.

## 7. 즉시 STOP 예외

중앙값은 노이즈를 줄이는 대신 최대 두 sample의 지연을 만들 수 있다. 따라서 매우
가까운 거리(`emergency_distance_m`)는 시간 필터를 기다리지 않고 원시 유효값 한 번으로
즉시 STOP한다. 이 임계값은 정상 STOP 거리보다 작아야 하며, 실제 속도와 제동 시험으로
정한다.

```text
raw distance ≤ emergency_distance_m  → 즉시 STOP
그 외                            → 중앙값 + 일반 STOP/SLOW 판단
```

## 8. 코드 연결 지점

- 최종 안전 gate와 센서 구독: `trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/safety_supervisor_node.py`
- LiDAR 유효값·직사각 보호 필드 계산: `trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/geometry.py`
- STOP/SLOW/CLEAR 정책: `trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/policy.py`
- 중앙값 필터 단위 테스트: `pinky_pro/trihouse_pinky/test/test_temporal_distance_filter.py`

## 9. 발표용 핵심 메시지

1. 협로의 옆벽은 장애물이 아니라 환경 경계이므로, 공간 필터로 경로 위 물체와 분리한다.
2. 단발 센서 노이즈는 시간 중앙값으로 제거하되, 센서가 끊기면 즉시 fail-closed STOP한다.
3. 전진은 LiDAR와 초음파의 더 가까운 값을 사용하고, 후진은 방향이 맞는 LiDAR만 쓴다.
4. 카메라 사람 감지·비상·keep-out은 거리 필터보다 상위 안전 신호다.
