# Trihouse Pinky 아키텍처

> 상태: 구현 전 설계 초안

## 패키지 경계

- `trihouse_pinky_bringup`: 실행 조합과 배포 설정만 소유한다.
- `trihouse_pinky_fleet`: 작업 상태 머신, 관제 연동, telemetry와 체크포인트를 소유한다.
- `trihouse_pinky_vision`: RTSP 송신, `StreamHealth`, 카메라 calibration과 좌표 변환을 소유한다.
- `trihouse_pinky_safety`: 정지·비상·keep-out을 판정하고 최종 속도를 출력한다.
- `trihouse_pinky_docking`: Nav2 종료 후 ArUco 기반 정밀 정차만 수행한다.

## 의존 방향

```text
trihouse_interfaces
  ├─ vision ──────> pinky_pro 카메라 프레임/시뮬 자산
  ├─ safety ──────> pinky_pro 센서·표시 서비스
  ├─ docking ─────> vision이 변환한 마커 관측
  └─ fleet ───────> Nav2, docking, safety 상태, 표시 서비스
        ^
      bringup (실행 조합만)
```

기능 패키지는 공용 인터페이스와 필요한 벤더 자산에 의존한다. safety는 fleet 상태를 조회하지 않으며, bringup은 업무 로직을 갖지 않는다.

## 데이터 흐름

```text
카메라 → H.264/RTSP → MediaMTX → 서버 추론
                                  └→ MarkerObservation/PersonDetection
                                      → vision 좌표 변환 → docking/safety

관제 TCP 8788 + NDJSON → fleet → Nav2 navigate_to_pose
Nav2 → /cmd_vel_nav ┐
                    ├→ safety → /cmd_vel → pinky_bringup
docking → /cmd_vel_dock ┘
```

## 오류 경계

- 관제 단절: 신규 작업을 거절하고 체크포인트를 기록한다.
- 카메라 단절: 영상 의존 동작을 중단하되 LiDAR 기반 안전 감시는 유지한다.
- 마커 소실: docking이 즉시 0 속도를 요청하고 제한된 횟수만 재시도한다.
- 비상 래치: 재연결이나 노드 재시작만으로 해제하지 않고 `ClearEmergency`를 요구한다.
- safety 입력 timeout: fail-safe로 정지한다.

## 검증 원칙

패키지는 독립 단위 테스트 후 실제 ROS graph에서 발행자와 remap을 검사한다. 특히 모터용 `/cmd_vel` 발행자가 safety 하나뿐인지 통합 시험마다 확인한다.

