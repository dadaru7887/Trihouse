# vision_ai 운영 개요

> 설계 **근거**(왜 이렇게 만들었는지)는 [설계 근거 문서](../../docs/vision_ai_design_rationale.md)에 있다.
> 이 문서는 운영 배치와 결정 규칙만 다룬다.

RTX 4060 영상 수신·저장과 RTX 5080 추론을 역할별로 분리한다. 영상은 RTSP로
처리하고 검출 결과만 JSON/NDJSON으로 Control Tower와 Pinky bridge에 전달한다.

| 위치 | 책임 |
|---|---|
| `robot/media/stream_hub/` | MediaMTX RTSP 수신·metrics |
| `robot/media/recording/` | 서버측 녹화·보존·evidence URI |
| `models/perception/detector.py` | 모델 로딩·GPU 추론 |
| `robot/perception/` | 자세 측정(`posture.py`)·낙상 상태(`fall_monitor.py`)·사람별 정책(`policy.py`)·프레임 평가(`frame.py`)·추론 루프(`worker.py`) |
| `robot/object/` | 바구니 보정 |
| `robot/marker/` | QR·ArUco 판독·pose 추정 |
| `models/perception/trainer/` | 인지 모델 학습 파이프라인 |
| `models/recovery/trainer/` | 복구 모델 오프라인 학습 |
| `utils/metrics.py` | box instance·mask pixel 지표 |
| `tests/` | recorded stream·장애 profile 통합 시험 |

진입점은 둘이다: 학습·검증은 `vision_ai.main`, 로봇 실시간은 `vision_ai.robot.main`.

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
cd "$REPO_ROOT"   # 저장소 루트
python3 - <<'PY'
from vision_ai.robot.media.stream_hub.ingress import (
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
  낙상 판정은 `fall_monitor.FallMonitor` 하나만 쓴다(track 마다 하나). 전에는 `observe_fall()`
  안에 별도 규칙이 있어 같은 판단을 두 곳에서 다르게 내렸다.
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
  `vision_ai/data_loader/perception/augmentation/generate_augmentation_candidates.py`의 저조도·노이즈·결로·반사
  생성기를 사용한다.

```bash
cd "$REPO_ROOT"   # 저장소 루트
python3 -m unittest -v \
  vision_ai.tests.worker.test_person_policy.PersonPolicyTest.test_roi_requires_consecutive_person_frames \
  vision_ai.tests.worker.test_person_policy.PersonPolicyTest.test_person_outside_roi_does_not_count_as_worker_presence \
  vision_ai.tests.worker.test_marker_policy \
  vision_ai.tests.worker.test_basket_correction \
  vision_ai.tests.worker.test_dataset_policy \
  vision_ai.tests.worker.test_recording_catalog \
  vision_ai.tests.worker.test_recorder
```

위 명령은 SR_19/20/44의 ROI 사람 감지 테스트만 실행한다.

SR_52 쓰러짐 감지는 **기술 조사가 끝났다**(2026-08-18~19 aspect ratio sweep, confidence
cutoff 분석, `re_1`~`re_6` 실낙상 확인). 그 결과가 `person_worker/fall_monitor.py` 와
`configs/realtime.yaml` 의 `monitor` 절이고, `observe_fall()` 이 그것을 쓴다. 남은 한계는
`training/README.md` 의 "알려진 한계" 절에 있다 — 요약하면 **이 판정은 최종 결론이 아니라
사람에게 볼 곳을 알려 주는 장치**다.


## 사람 + 낙상 — 모델 하나와 규칙 하나

학습되는 모델은 **하나**다. `data.yaml` 이 `nc=2, names=['obstacle','person']` 이고
**`fallen` 클래스는 없다.** 낙상은 학습된 것이 아니라 사람 mask 를 후처리하는
규칙이다.

```text
frame ─▶ yolo_inference_server/detector.py    1단계. 검출        ← 학습되는 모델
          └─▶ person_worker/posture.py         2단계. 자세 측정   ← 규칙 (갈아 끼울 자리)
                └─▶ person_worker/fall_monitor.py   시간축 상태 전이
```

한 번의 추론에서 두 갈래가 나온다. **사람 위치·신뢰도**는 로봇 안전 gate 로,
**낙상 상태**는 관제로 간다. 지연 요구가 정반대라 단계를 나눈다 — 검출은 매
프레임 돌아야 하고(로봇이 이 결과로 감속한다), 낙상은 어차피 debounce 로 1 초를
기다린다. 합치면 느린 쪽 비용이 빠른 쪽에 얹힌다.

**왜 `fallen` 을 클래스로 넣지 않는가**

- train 의 person 인스턴스가 129 개고 그중 69 개가 small object 다. 클래스를
  쪼개면 양쪽 다 나빠진다.
- 넘어진 사람도 사람이다. 클래스로 넣으면 **자세 오판이 검출 실패가 된다.**
- 검출기는 환경이 바뀔 때, 낙상 임계값은 영상 sweep 으로 튜닝한다. 합치면
  임계값 하나 만질 때마다 재학습이다.

2 단계를 규칙에서 모델로 바꾸려면 `posture_manifest` CSV(아직 없음)와 실낙상
데이터가 필요하다. 지금 확보된 실낙상 구간은 `re_3` 의 t=57~62 s, t=123~131 s
둘뿐이다.

## 학습·추론 명령

```bash
cd "$REPO_ROOT"   # 저장소 루트
# 학습 (GPU 필요)
venv/yolo_segmentation/bin/python -m vision_ai.models.perception.trainer.pipeline train \
  --config vision_ai/models/perception/trainer/configs/config.yaml
# 추론
venv/yolo_segmentation/bin/python -m vision_ai.robot.perception.worker \
  --weights <selected_model.json> --source rtsp://<host>:8554/pinky/CAM-PK-01 --headless
```

**경로는 전부 인자다.** 코드에 절대 경로를 넣지 않는다 — config 의 상대 경로는
저장소 루트 기준이고(`training/config_loader.py` 의 `REPOSITORY_ROOT`), 증강
recipe 위치는 `--augmentation-source` 로 바꾼다.
