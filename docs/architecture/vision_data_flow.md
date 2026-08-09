# 영상 데이터 흐름

## 상태

Pinky RTSP health contract와 4060/5080 역할을 통합한 기준 아키텍처다. 실제 주소,
codec, FPS는 hardware 측정 후 profile로 고정한다.

```text
Pinky/고정 카메라
  └─ RTSP/encoded stream
       ├─ 4060 relay/recording ── artifact storage
       ├─ 4060 QR inference ── Vision Adapter
       └─ 5080 YOLO/VLM inference ── Gateway/Task Manager
```

## 책임

- Pinky streamer: capture, encode, bounded restart, `StreamHealth`
- 4060: stream registry, QR, relay, retention, 5080 전달
- 5080: YOLO/VLM inference와 학습용 feature 생성
- Control Tower: 결과의 업무 의미와 안전 승인

## 필수 식별자

`robot_id`, `camera_id`, `stream_id`, `captured_at`, `sequence`, `codec`,
`resolution`, `model_version`, `trace_id`를 전달한다. 영상과 추론 결과의 timestamp가
허용 오차를 넘으면 제어 입력으로 사용하지 않는다.

## 금지 연결

- vision service가 장비 actuator를 직접 제어하지 않는다.
- 5080이 원본 영상 보존 정책이나 DB transaction을 소유하지 않는다.
- stream 단절을 단순 검출 실패와 동일하게 처리하지 않는다.
- 무제한 subprocess restart나 무제한 queue를 사용하지 않는다.
