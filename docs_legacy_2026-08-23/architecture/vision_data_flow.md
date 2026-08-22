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
PC1 MediaMTX 1.19.3: rtsp://PC1:8554/<role>/<camera_id>
  예) pinky/CAM-PK-01, omx/CAM-OMX-01-WRIST, fixed/CAM-FIXED-01
  ├─ recording/QR ── 학습 코퍼스(/recordings/<role>/<camera_id>/)
  └─ PC2 YOLO/VLM inference ── observation ── FMS Gateway/Task Manager
```

카메라 종류는 PC1 MediaMTX 앞의 ingress adapter에서만 구분한다. Native H.264는
재인코딩하지 않고 전달하고, MJPEG/YUYV만 카메라가 연결된 호스트에서 한 번 H.264로
인코딩한다. PC2는 항상 위 canonical RTSP URL만 소비한다.

## 경로 규약

경로는 `<역할 접두사>/<camera_id>` 두 segment 다. `camera_id` 는 `CAM-PK-01`
처럼 전역 유일한 논리 ID 이고, `config/cameras.yaml` 이 그 정본이다.

`pinky/<robot_id>/<camera_id>` 세 segment 규약은 폐기됐다. `StreamHealth.msg` 가
`camera_id` 만 싣고 `robot_id` 는 싣지 않기 때문에, 세 segment 아래에서는 노드의
`camera_id` 가 `front` 같은 역할 이름이 되어 PK_01 과 PK_02 의 건강 메시지를
구분할 수 없었다. 마지막 segment 를 전역 유일한 ID 로 두면 그 구분이 공짜로
따라오고, Control Tower 가 이미 쓰던 ID 와도 같아서 대응표가 필요 없다.

## 인가

- **publish 는 출발지 IP 로 막는다.** RTSP 는 자격 증명을 URL 안에만 실을 수
  있어서, 계정으로 막으면 비밀번호가 로봇의 package-share YAML 과 `ps` 출력에
  노출된다. 대신 로봇 주소를 DHCP 로 예약해야 하고 IP 위장은 막지 못한다.
- **read 는 `viewer` 계정으로 막는다.** PC2 는 이미 URL 을 환경변수로 받으므로
  비밀번호를 붙여도 코드가 바뀌지 않는다. 연구용 호스트도 같은 계정을 쓴다.
- 정책은 `config/mediamtx.yml` 에 있고 Compose 가 마운트한다. 마운트하지 않으면
  MediaMTX 는 익명 publish/read 기본값으로 뜬다.

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
