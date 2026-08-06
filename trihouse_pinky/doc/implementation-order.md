# 구현 순서

> 상태: 작업 계획. 각 단계의 인터페이스와 검증을 끝낸 뒤 다음 단계로 이동한다.

## 전체 권장 순서

1. `trihouse_interfaces`를 확정하고 ROS 2 패키지로 만든다.
2. `trihouse_pinky_safety` 최소 속도 게이트를 만든다.
3. `trihouse_pinky_bringup` 최소 통합 launch를 만든다.
4. fleet이 구조화 작업 한 건을 받아 Nav2 한 지점으로 이동하고 결과를 회신하게 한다.
5. 관제 UI에서 작업 전송과 상태 반영을 연결한다.
6. vision RTSP 송신, `StreamHealth`, 캘리브레이션을 구현한다.
7. docking 정밀 정차를 구현한다.
8. 입·출고 전체 상태 머신을 연결한다.
9. heartbeat, 체크포인트, 중복 제거와 예외 처리를 강화한다.
10. 로봇 1·2호기와 시뮬레이션 운영 profile을 완성한다.

## 오늘: Pinky 카메라 영상 확인

전체 의존 순서와 별개로 하드웨어 리드타임을 줄이기 위해 vision의 Step 0/초기 송수신 검증은 먼저 수행할 수 있다. 이 작업은 ROS 패키지 구현이 아니라 카메라와 인코더 능력을 확인하는 spike다.

1. Pinky 보드 모델, `/dev/v4l/by-id/` 경로, 지원 포맷과 H.264 control을 기록한다.
2. 카메라 직출력 H.264 → Pi 4 하드웨어 인코딩 → x264 소프트웨어 인코딩 순으로 가능한 첫 경로를 선택한다.
3. `gst-launch-1.0`으로 MediaMTX의 `pinky_1` 또는 `pinky_2` 경로에 게시한다.
4. RTX 4060에서 `ffprobe`와 60초 decode로 해상도, FPS, timestamp 진행과 오류를 확인한다.
5. 10분 연속, 720p 10~15 FPS, 프레임 드롭 1% 이하와 Pinky CPU 여유를 측정한다.
6. 측정값을 고정한 다음에만 GStreamer Python 노드와 `StreamHealth` 구현 계획을 확정한다.

상세 명령과 판정 기준은 [vision README](../trihouse_pinky_vision/README.md)를 따른다.

## 최소 수직 흐름의 완료 조건

```text
UI 주문 → 작업 생성/배정 → Pinky 수락 → Nav2 목표 이동
→ safety 게이트 → 모터 → 결과와 현재 상태 UI 표시
```

vision과 docking을 통합하기 전에 이 흐름에서 safety 우회 발행자가 없고 map revision 불일치 작업이 거절되는지 확인한다.
