# vision_system

RTX 4060 영상 수신·저장과 RTX 5080 추론을 역할별로 분리한다. 영상은 RTSP로
처리하고 검출 결과만 JSON/NDJSON으로 Control Tower와 Pinky bridge에 전달한다.

| 폴더 | 책임 |
|---|---|
| `stream_hub/` | MediaMTX RTSP 수신·metrics |
| `recording_server/` | 서버측 녹화·보존·evidence URI |
| `inference_common/` | 최신 frame bus, 공통 schema, health |
| `yolo_inference_server/` | 모델 로딩·GPU 추론 orchestration |
| `person_worker/` | 사람 검출·추적·자세 후보 |
| `object_worker/` | 객체 검출·segmentation·추적 |
| `marker_worker/` | QR·ArUco 판독·pose 추정 |
| `model_registry/` | 모델 승인·배포·rollback |
| `training/`, `evaluation/` | 학습과 재현 가능한 평가 |
| `tests/` | recorded stream·장애 profile 통합 시험 |

## PC1 → PC2 표준 영상 입력

모든 카메라는 최종적으로 다음 RTSP 경로를 제공한다.

```text
rtsp://<PC1_LAN_IP>:8554/<role>/<camera_id>
예) pinky/CAM-PK-01, omx/CAM-OMX-01-WRIST, fixed/CAM-FIXED-01
```

- Native RTSP/H.264: PC1 MediaMTX로 stream-copy한다.
- USB H.264: `UsbVideoFormat.H264`와 `VideoEncoder.COPY`를 사용한다.
- USB MJPEG/YUYV: 카메라 연결 호스트에서 `NVENC`로 한 번 인코딩하고, GPU를 사용할 수
  없을 때만 `LIBX264`를 사용한다.
- PC2: `InferenceStreamConfig.from_env()`로 `VISION_RTSP_URL`을 읽고
  `build_ffmpeg_frame_command()`의 BGR24 frame을 YOLO/VLM 입력으로 사용한다.

명령 확인 예시:

```bash
cd /home/syw/Trihouse
python3 - <<'PY'
from vision_system.stream_hub.ingress import (
    StreamIdentity, UsbIngressConfig, UsbVideoFormat, VideoEncoder,
    build_usb_ingress_command,
)

config = UsbIngressConfig(
    identity=StreamIdentity(role='fixed', camera_id='CAM-FIXED-01'),
    device='/dev/video0',
    mediamtx_base_url='rtsp://PC1_LAN_IP:8554',
    input_format=UsbVideoFormat.MJPEG,
    encoder=VideoEncoder.NVENC,
)
print(' '.join(build_usb_ingress_command(config)))
PY
```

출력된 명령을 카메라가 연결된 호스트에서 실행한다. 실제 `/dev/video0` 지원 포맷은
`v4l2-ctl --device /dev/video0 --list-formats-ext`로 먼저 확인한다.

## 현재 구현된 결정 규칙

- `person_worker/policy.py`는 모델의 사람 box·track·자세·움직임 결과에 ROI와 연속 프레임
  조건을 적용한다. 사람 검출 자체로 로봇 속도 명령을 내리지 않으며, 확정 이벤트는 Control Tower에 전달한다.
- `marker_worker/policy.py`는 OMX 동작 전의 QR 주문·물품 일치와 ArUco 선반 ID·오차 범위를 검사한다.
- `object_worker/basket_correction.py`는 YOLO OBB가 준 바구니 외곽 네 모서리 기반 보정을 적용한다.
  병진·회전이 구성한 잔여 정차 오차 한계를 넘거나 네 모서리가 불완전하면 OMX 동작 대신
  `REQUEST_PINKY_REPOSITION`을 반환한다.
- `recording_server/recorder.py`는 RTSP를 재인코딩하지 않고 H.264 stream-copy로 60초 segment를
  만드는 FFmpeg argv와 shell 없는 process runner를 제공한다. 배포의 file watcher가 segment 생성/종료를
  `RecordingSession`에 전달한다. `catalog.py`의 `enforce_retention()`은 용량 초과 시 가장 오래된
  `COMPLETE`·미재생 segment ID만 반환하므로, storage worker는 그 ID의 파일만 삭제한다.
  `RECORDING` 또는 `playing=True` 파일은 삭제하지 않는다.
- `training/dataset_policy.py`는 SR_05의 학습 경계다. 밝기·대비·노이즈 등 증강은 `TRAIN`에서만
  허용하고, 원본·저조도 validation sample ID는 겹치지 않게 한다. `inference_input()`은 실시간
  프레임을 수정하지 않는다. 실제 증강 recipe 구현은 중복하지 않고 기존
  `vision_perception/augmentation/generate_augmentation_candidates.py`의 저조도·노이즈·결로·반사
  생성기를 사용한다.

```bash
cd /home/syw/Trihouse
python3 -m unittest -v \
  vision_system.tests.test_person_policy.PersonPolicyTest.test_roi_requires_consecutive_person_frames \
  vision_system.tests.test_person_policy.PersonPolicyTest.test_person_outside_roi_does_not_count_as_worker_presence \
  vision_system.tests.test_marker_policy \
  vision_system.tests.test_basket_correction \
  vision_system.tests.test_dataset_policy \
  vision_system.tests.test_recording_catalog \
  vision_system.tests.test_recorder
```

위 명령은 SR_19/20/44의 ROI 사람 감지 테스트만 실행한다. SR_52 쓰러짐 감지의 기존 테스트와
`observe_fall()`은 기술 조사·승인 전까지 실행·수정하지 않는다.
