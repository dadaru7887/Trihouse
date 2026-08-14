# 영상 데이터 흐름

## 상태

Pinky RTSP health contract와 4060/5080 역할을 통합한 기준 아키텍처다. 실제 주소,
codec, FPS는 hardware 측정 후 profile로 고정한다.

```text
Native RTSP/H.264 ───────────────────────┐
USB H.264 ── FFmpeg stream copy ─────────┤
USB MJPEG/YUYV ── FFmpeg H.264 encode ───┘
                    │
                    ▼
PC1 MediaMTX: rtsp://PC1:8554/pinky/<robot_id>/<camera_id>
  ├─ recording/QR
  └─ PC2 YOLO/VLM inference ── observation ── FMS Gateway/Task Manager
```

카메라 종류는 PC1 MediaMTX 앞의 ingress adapter에서만 구분한다. Native H.264는
재인코딩하지 않고 전달하고, MJPEG/YUYV만 카메라가 연결된 호스트에서 한 번 H.264로
인코딩한다. PC2는 항상 위 canonical RTSP URL만 소비한다.

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
- 4060과 5080에서 영상을 연속으로 재인코딩하지 않는다.
