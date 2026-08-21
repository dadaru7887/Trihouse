# Pinky 세그멘테이션 학습·추론 파이프라인

Pinky 카메라 → GPU PC 실시간 세그멘테이션 추론까지의 전체 흐름과, 그 전 단계인
GPU 학습까지 정리한 문서입니다.

## 1. 전체 구조

연구 경로와 운영 경로는 **같은 RTSP 스트림 하나**를 봅니다.

```
Pinky (라즈베리파이)          PC1 (RTX 4060)              GPU PC (호스트)
┌──────────────────┐  RTSP   ┌──────────────────┐  RTSP  ┌─────────────────────┐
│ camera_streamer  │ ──────▶ │ MediaMTX 1.19.3  │ ─────▶ │ trihouse_train 컨테이너│
│  rpicam-vid      │  H.264  │ /pinky/CAM-PK-01 │ viewer │  ├─ train.py         │
│  + ffmpeg        │         │  + 녹화(fmp4)     │  계정  │  └─ inference_stream │
└──────────────────┘         └────────┬─────────┘        └─────────────────────┘
                                      │ 같은 스트림
                                      ▼
                             PC2 (RTX 5080) 운영 추론
```

### 왜 MJPEG 직송을 쓰지 않는가

학습에 필요한 것은 실시간 스트림이 아니라 **운영이 보는 것과 같은 픽셀**입니다.
예전 MJPEG 경로와 운영 RTSP 경로는 픽셀이 실제로 다릅니다.

|          | 연구 (MJPEG, 폐기) | 운영 (RTSP) |
|---|---|---|
| 코덱      | JPEG, 프레임 독립 | H.264 baseline, `-intra 15` |
| 화질      | `cv2.imencode(".jpg", frame)` 기본값(품질 95) | 2000 kbps |
| 프레임률  | 서버 루프 속도대로 무제한 | 15 fps |
| 해상도    | 미지정, `pinklib` 반환값 그대로 | 1280x720 |

세그멘테이션은 경계에 민감한데, H.264 baseline 2 Mbps 는 deblocking 과 저비트레이트
블록 아티팩트로 바로 그 경계를 뭉갭니다. MJPEG 은 그런 열화를 만들지 않습니다.
운영 추론은 여기에 더해 `-vf fps=15,scale=1280:720 -pix_fmt bgr24` 를 한 번 더
지나갑니다(`model/worker/common/stream.py`). 학습 코퍼스가 같은
인코딩·디코딩 사슬을 지나지 않으면, 학습 때 보지 못한 열화를 배치 후에 처음
만나게 됩니다.

전환 비용은 사실상 없습니다. `inference_stream.py` 는 `--source` 를
`cv2.VideoCapture` 로 넘기고, 이 클래스는 `rtsp://` 를 `http://` 와 똑같이 받습니다.
코드는 한 줄도 바뀌지 않습니다.

## 2. 네트워크

- Pinky와 GPU PC가 서로 통신하려면 **같은 WiFi**에 있어야 합니다.
- GPU PC는 무선랜 어댑터가 하나뿐이라, WiFi를 바꾸면 그 전 네트워크 연결은 끊깁니다
  (SSH 세션도 같이 끊김 — 원격으로 붙어있었다면 재확인 필요).
- Pinky IP 확인: Pinky Jupyter 터미널에서 `hostname -I`, 또는 Pinky Studio 앱의
  "상태 확인" 버튼.

## 3. GPU PC 도커 환경

### 이미지: `trihouse:ver2`
ROS2 Jazzy + conda `unified_env_ver2`(PyTorch, ultralytics 등) + Pointcept +
flash-attn이 포함된 이미지. 로컬(GPU 없는 머신)에서 빌드 후
`docker save | ssh ... docker load`로 GPU PC에 옮겨진 것.

### 컨테이너 진입/생성 커맨드

**이미 떠있으면 그냥 exec로 붙기** (컨테이너 여러 개 생기는 걸 방지하기 위해 `docker run`
대신 항상 이 방식 사용):
```bash
docker exec -it trihouse_train bash
```

**컨테이너가 없거나 새로 만들어야 하면** (예: 옵션 변경 후 재생성):
```bash
# 1) 호스트에서 한 번: 컨테이너가 화면에 그림을 그릴 수 있게 허용
xhost +local:root

# 2) 컨테이너 생성 (GPU 전체 할당 + shm 8g + Pinky 데이터셋 마운트 + X11 화면 공유)
docker run -dit --name trihouse_train --gpus all --shm-size=8g \
  -e DISPLAY=:1 \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v /home/user/Trihouse_segmentation:/workspace/Trihouse_segmentation \
  -w /workspace \
  trihouse:ver2 \
  bash -c '
source /opt/ros/jazzy/setup.bash
source /ros2_ws/install/setup.bash
exec bash
'
```

- `-v /home/user/Trihouse_segmentation:...` 마운트 덕분에, 호스트에서 그 폴더에 파일을
  넣고 빼면 컨테이너 안에서도 바로 보입니다 (반대도 마찬가지). 컨테이너를 지워도
  이 폴더 안 내용(학습 결과 포함)은 안 없어집니다.
- `DISPLAY=:1`은 **지금 세션 기준값**입니다. 재부팅/재로그인하면 세션 번호가 바뀔 수
  있으니(`:0`, `:1`, ...), `who` 명령어로 실제 세션 번호를 확인하고 맞춰주세요.
- `--shm-size=8g`: 기본값(64MB)이 너무 작아서 dataloader worker가 여럿이면 크래시 남.

### 컨테이너 안에서 파이썬 실행 시 필수

conda 환경(`unified_env_ver2`)을 먼저 activate해야 ultralytics/torch/opencv가 잡힙니다:
```bash
source /opt/conda/etc/profile.d/conda.sh
conda activate unified_env_ver2
```
(`set -u`가 걸린 스크립트에서 이걸 하면 conda의 activate.d 스크립트가 정의 안 된 변수를
참조해서 에러가 남 — `train.sh`/`infer.sh`에서는 이 activate 구간만 `set +u`/`set -u`로
감싸서 처리해뒀음.)

### nvitop (GPU 모니터링, 선택)
컨테이너 쓰기 레이어에만 설치되는 거라 컨테이너 재생성하면 다시 설치해야 함:
```bash
/opt/conda/envs/unified_env_ver2/bin/pip install nvitop
/opt/conda/envs/unified_env_ver2/bin/nvitop
```

## 4. 학습 (`train.py` / `train.sh`)

LEGO `person` 데이터셋의 무결성 검사, validation gate, test 평가와 재현 가능한 artifact까지 한 번에 관리하려면
[`worker-fall-detection/README.md`](../test/worker-fall-detection/README.md)의 파이프라인을 사용한다. 기존 `train.py`와 `train.sh`는 단독 학습 진입점으로 유지되며 새 파이프라인도 같은 S1~S5 augmentation과 YOLOE trainer를 재사용한다.

호스트에서 바로 실행하면 자동으로 컨테이너 안으로 들어가서 실행됩니다(`/.dockerenv`
존재 여부로 호스트/컨테이너를 자동 판별함). `docker exec` 따로 안 해도 됩니다.

```bash
cd /home/user/Trihouse_segmentation/Trihouse
./train.sh --model 26s --augmentation yes --data ../Trihouse_seg_dataset/data.yaml \
  --batch 16 --epochs 1000 --patience 50
```

- `--model`: `{11,26}+{n,s,m,l,x}` 조합 (예: `26s`) → `yoloe-26s-seg.pt`로 자동 변환.
- `--augmentation yes/no`: S1~S5 온라인 augmentation pool 적용 여부.
- 결과 폴더명: `{학습시작시각(KST)}_{모델명}_{aug|noaug}` 자동 생성
  (예: `20260805_181217_yoloe-26s-seg_aug`).
- `--project` 기본값이 절대경로(`/workspace/Trihouse_segmentation/Trihouse/runs/segment`)로
  고정되어 있음 — 상대경로로 두면 ultralytics 내부 기본값과 겹쳐서
  `runs/segment/runs/segment/...`처럼 중첩 저장되는 버그가 있었어서 이렇게 고쳐둠.

## 5. 카메라 스트림 받기

### 5.1 기본: PC1 MediaMTX 의 RTSP (연구·운영 공통)

Pinky 의 `camera_streamer` 노드가 `pinky/CAM-PK-01` 경로로 발행하고 있으면 그대로
읽으면 됩니다. **읽기는 계정 인증**이므로 URL 에 `viewer` 자격 증명이 필요합니다
(비밀번호는 PC1 `.env` 의 `MTX_VIEWER_PASS`).

```bash
rtsp://viewer:<MTX_VIEWER_PASS>@<PC1_LAN_IP>:8554/pinky/CAM-PK-01
```

랩 세션처럼 PC1 전체 스택이 필요 없을 때는 **MediaMTX 만** 띄우면 됩니다.
`compose.edge_4060.yaml` 의 `mediamtx` 서비스에는 `depends_on` 이 없어서 단독 기동이
가능합니다.

```bash
docker compose -f compose.edge_4060.yaml up mediamtx
```

먼저 스트림이 살아 있는지 확인:
```bash
ffprobe -rtsp_transport tcp \
  "rtsp://viewer:<MTX_VIEWER_PASS>@<PC1_LAN_IP>:8554/pinky/CAM-PK-01"
```

### 5.2 학습 프레임은 MediaMTX 녹화본에서 뽑는다

MediaMTX 가 발행된 스트림을 그대로 녹화하고 있습니다(fmp4, 60초 분할, 168시간 보존).
이 녹화본은 운영 추론이 보는 것과 **같은 인코딩 사슬을 지난 프레임**이므로, 학습
코퍼스는 여기서 만듭니다. 별도 수집 장치가 필요 없습니다.

```bash
# PC1: TRIHOUSE_VIDEO_DIR 아래에 경로별로 쌓입니다
ls ${TRIHOUSE_VIDEO_DIR:-./runtime/video}/pinky/CAM-PK-01/

# 프레임 추출 (1초에 1장 예시)
ffmpeg -i <녹화본>.mp4 -vf fps=1 frames/CAM-PK-01_%06d.png
```

### 5.3 랩 폴백: `pinky_camera_server.py` (MJPEG)

**오프라인 랩 전용입니다. 여기서 나온 프레임은 학습 세트에 넣지 마십시오.**
§1 의 표대로 운영과 픽셀이 다르기 때문입니다. PC1 에 닿을 수 없는 자리에서
카메라 자체가 살아 있는지 눈으로 확인하는 용도로만 씁니다.

**Pinky에서** 실행 (Jupyter `http://<Pinky IP>:8888` 접속 → 새 파일/터미널):
```bash
python3 pinky_camera_server.py
# "스트리밍 시작 -- PC에서 http://<이 Pinky IP>:8080/stream.mjpg 로 접속" 뜨면 정상
```
- 의존성: `pinkylib`(Pinky 이미지에 기본 내장), `opencv-python` — 추가 설치 불필요.
- 화면 색이 반전되어 보이면 `--swap-rgb` 옵션 추가.
- `pinkylib.Camera`가 물리 카메라를 쓰는 라이브러리라 **반드시 Pinky 위에서만** 실행
  가능 (GPU PC에서 실행하면 `ModuleNotFoundError: No module named 'pinkylib'`).
- 자동으로 실행되는 곳은 없습니다. 사람이 직접 띄울 때만 돕니다.

## 6. 실시간 추론 (`inference_stream.py` / `infer.sh`)

호스트에서 바로 실행 (train.sh와 같은 자동 컨테이너 진입 패턴, X11까지 자동 설정):
```bash
cd /home/user/Trihouse_segmentation/Trihouse
./infer.sh \
  --model "runs/segment/20260805_181217_yoloe-26s-seg_aug/weights/best.pt" \
  --source "rtsp://viewer:<MTX_VIEWER_PASS>@<PC1_LAN_IP>:8554/pinky/CAM-PK-01"
```
- 화면 없이 콘솔 로그만 보려면 `--no-show` 추가 (§3의 X11 설정 전에도 이걸로 파이프라인
  동작만 먼저 검증 가능).
- 종료: 화면에서 `q` 또는 `ESC`.
- **스트림 단절 대응 로직** 포함: `2026-08-05-vision-streaming-architecture-draft.html`
  §8(스트림 단절 정의와 대응) 기준을 그대로 구현.
  - 상태: `HEALTHY` / `DEGRADED` / `DISCONNECTED` / `RECOVERING`
    (1초 무프레임=DEGRADED, 3초=DISCONNECTED, 5초 연속 목표FPS 90%↑=HEALTHY)
  - 단절된 카메라의 마지막 프레임을 반복해서 모델에 넣지 않음 (freeze 프레임도 감지)
  - DISCONNECTED 시 action queue·authorization 폐기 + 안전 정지, backoff 재접속
  - 재연결 후 재인증(`authorize_fn` 콜백, 지금은 no-op — 실제 배치 전 QR/DB 검증으로 교체 필요)
- 체크포인트(`best.pt`)를 불러올 때 `mixed_augmentation` 함수가 `__main__`에 없으면
  `AttributeError`가 남 (학습 때 저장된 augmentation 설정이 pickle로 같이 저장돼서) —
  `inference_stream.py` 상단에 더미 함수로 이미 처리해뒀음. 이 체크포인트를 다른
  스크립트에서 불러올 땐 동일하게 처리 필요.
