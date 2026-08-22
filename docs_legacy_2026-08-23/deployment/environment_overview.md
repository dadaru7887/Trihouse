# Robosapiens 환경 구성

## 상태

- 기준일: 2026-08-10
- 현재 PC: Docker·Compose 설치, 개발·테스트 DB 작성 및 로컬 실행 검증 완료
- RTX 4060·5080: 역할별 Compose 작성·정적 검증 완료, 실제 서버 검증 예정
- 보호 경로: `pinky_pro/**`, `control_system/**`는 읽기·실행만 허용

## 호스트별 역할

| 호스트 | 책임 | 데이터 소유 |
|---|---|---|
| 현재 PC | Compose 작성, 정적 테스트, 회의 시연 준비 | 개발용 로컬 볼륨만 |
| RTX 4060 | 관제, Task Manager, MySQL, QR, 영상 저장·중계 | `trihouse_fms`, `trihouse_recovery`, 영상 artifact |
| RTX 5080 | YOLO, VLM, RL 학습·복구 정책 | GPU replay buffer, NVMe cache, 미전송 queue |
| OMX PC 01 | `/omx_01/execute` ROS bridge, Python 3.10 LeRobot worker | OMX_01 calibration, ACT cache |
| OMX PC 02 | `/omx_02/execute` ROS bridge, Python 3.10 LeRobot worker | OMX_02 calibration, ACT cache |

MySQL 8.4 서버는 4060 한 곳에 둔다. 5080은 DB 자격증명을 갖지 않고 Gateway
API와 export artifact를 사용한다. 네트워크가 끊기면 고유 `message_id`가 있는
recovery record를 로컬 queue에 보관하고 ACK까지 재전송한다.

## 역할별 Compose

| 파일 | 역할 | 현재 상태 |
|---|---|---|
| `compose.db.yaml` | 보존되는 개발 MySQL | 작성·정적 검증·로컬 실행 검증 완료 (`schema_mysql.sql` 계약 기준) |
| `compose.db_test.yaml` | tmpfs 테스트 MySQL | 작성·정적 검증·로컬 실행 검증 완료 (창고·QR 재고 시드 포함) |
| `compose.control.yaml` | FMS Gateway backend/API | 작성·정적 검증·로컬 build/readiness 검증 완료 |
| `compose.simulation.yaml` | RMF API/dashboard 지원 stack | 작성·정적 검증 완료, ROS 2/Gazebo는 현재 호스트 실행 |
| `compose.edge_4060.yaml` | MediaMTX와 4060 application 계약 | 작성·정적 검증 완료, QR·catalog image 구현 필요 |
| `compose.ai_5080.yaml` | 5080 AI image 실행 계약 | 작성·정적 검증 완료, env image·GPU 서버 검증 필요 |
| `compose.roles/omx.yaml` | 각 OMX PC의 ROS bridge + LeRobot worker | 실물 장치값 입력 후 검증 필요 |

Docker Engine은 호스트마다 하나만 설치한다. Compose 파일을 역할별로 나눈다는
뜻은 Docker를 여러 번 설치한다는 뜻이 아니라, 같은 Engine 위에서 수명주기와
장애 범위가 다른 서비스를 별도로 실행한다는 뜻이다.

## Control Tower 경계

현재 시연에서는 기존 `control_system` UI와 자체 Open-RMF/Gazebo 구성을 변경 없이
사용한다. `control_tower`는 Task Manager, API, projection, adapter/backend를 맡는다.
장기적으로 `control_system/robo_control`의 화면·theme·widget만
`control_tower/ui/`로 선별 이식하며 FleetEngine, SQLite, TCP 8788 권한은 복제하지
않는다. 자세한 경계는 [Control Tower 경계](../architecture/control_tower_boundary.md)를
참조한다.

## 실행 원칙

1. 새 호스트는 Docker와 GPU runtime을 최초 1회 준비한다.
2. 저장소의 `.env.example`을 참고해 호스트별 비밀값을 로컬 `.env`에 둔다.
3. DB → control → simulation/edge/AI 순서로 healthcheck를 통과시킨다.
4. 팀원은 장기적으로 `scripts/*_up.sh`를 사용하고, 호스트 설정은 bootstrap
   스크립트로 분리한다.
5. DB 초기화 SQL은 빈 볼륨에서만 자동 실행한다. 기존 볼륨 갱신은 migration으로
   수행한다.

`.env.example`은 필요한 변수 이름과 예시를 팀 전체가 공유하는 버전 관리 파일이므로
`.env`를 만든 뒤에도 삭제하지 않는다. 실제 비밀번호와 호스트별 장치 경로는 Git에서
제외되는 `.env`에만 둔다.

각 OMX PC에서는 저장소를 받은 뒤 그 PC에 맞는 `.env`를 만들고 다음처럼 실행한다.

```bash
./scripts/omx_stack up --build
./scripts/omx_stack doctor
./scripts/omx_stack logs
```

`doctor`는 모터를 움직이지 않는다. `ROS_DOMAIN_ID=12`, DB ID/namespace 조합,
serial·두 카메라·calibration/model 경로와 `/omx_0#/execute` Action 노출만 확인한다.

## 현재 구현 수준을 읽는 방법

- `compose.control.yaml`은 현재 코드로 실제 실행할 수 있다. `fms_gateway/Dockerfile`이
  Python 3.12 runtime을 만들고, `/ready`가 MySQL 연결까지 확인한다.
- `compose.simulation.yaml`은 기존 `run_office_web.sh`가 Docker로 실행하던 RMF API와
  dashboard를 Compose로 옮긴 대안이다. 둘을 동시에 실행하면 3000·8000 포트가
  충돌하므로 하나만 선택한다. Gazebo와 ROS 2 launch는 현재 호스트에서 실행한다.
- `compose.edge_4060.yaml`의 `mediamtx`는 기본 실행 대상이다. `qr_worker`와
  `recording_catalog`은 장기 실행 entrypoint를 가진 image가 생긴 뒤
  `--profile application_images`로 활성화한다.
- `compose.ai_5080.yaml`은 `origin/env`의 backend Docker 작업으로 만든
  `TRIHOUSE_AI_IMAGE`를 실행한다. 현재 branch에서 거대한 AI 환경을 중복 build하지
  않으며, 5080 서버에서 NVIDIA Container Toolkit 검증 후 실행한다.

## PC1 MediaMTX와 PC2 Vision 연결

표준 스트림 경로는 다음 하나로 고정한다.

```text
rtsp://<PC1_LAN_IP>:8554/<role>/<camera_id>
```

예시는 `rtsp://10.0.0.40:8554/pinky/CAM-PK-01`이다. `camera_id`는 전역 유일한
논리 ID이고 정본은 `config/cameras.yaml` 하나다. PC1의 `.env`에는
`EDGE_BIND_ADDRESS=<PC1_LAN_IP>`를 두고 PC2의 `.env`에는 동일 URL을
`VISION_RTSP_URL`로 둔다. 카메라 정체를 따로 넘기는 `VISION_CAMERA_ID`는 없다 —
URL의 마지막 segment가 곧 `camera_id`이므로 둘이 어긋날 수 없다. 8554/tcp는
PC2와 카메라 송신 호스트에서만 접근하도록 방화벽 범위를 제한한다.

### 인가

MediaMTX는 설정을 마운트하지 않으면 익명 publish·read 기본값으로 뜬다. 정책은
`config/mediamtx.yml`에 있고 Compose가 마운트한다.

- **publish는 출발지 IP 허용목록**이다. 로봇 주소를 **DHCP로 예약**해야 하며,
  주소가 바뀌면 그 로봇만 조용히 발행에 실패한다.
- **read는 `viewer` 계정**이다. PC2와 연구용 호스트가 같은 계정을 쓴다.

`.env`에 실제 값을 채운다(`.env.example`의 값은 전부 자리표시자다).

```bash
MTX_VIEWER_PASS=<열람 계정 비밀번호>
PINKY_PK_01_IP=<PK_01 예약 주소>
PINKY_PK_02_IP=<PK_02 예약 주소>
PC1_PUBLISHER_IP=<USB 카메라를 발행하는 호스트 주소>
```

읽을 때는 URL에 자격 증명을 싣는다.

```text
rtsp://viewer:<MTX_VIEWER_PASS>@<PC1_LAN_IP>:8554/pinky/CAM-PK-01
```

PC1에서 MediaMTX를 시작한다.

```bash
cd /home/syw/Trihouse
docker network inspect trihouse_control_edge >/dev/null 2>&1 || \
  docker network create trihouse_control_edge
docker compose -f compose.edge_4060.yaml up -d mediamtx
docker compose -f compose.edge_4060.yaml ps
curl --fail http://127.0.0.1:9997/v3/paths/list
curl --fail http://127.0.0.1:9998/metrics | grep 'paths\|readers\|publishers'
```

Native RTSP/H.264 카메라는 재인코딩 없이 표준 경로로 전달한다.

```bash
export CAMERA_RTSP_URL='rtsp://CAMERA_IP/native-stream'
export VISION_RTSP_URL='rtsp://viewer:MTX_VIEWER_PASS@PC1_LAN_IP:8554/pinky/CAM-PK-01'
ffmpeg -nostdin -rtsp_transport tcp -i "$CAMERA_RTSP_URL" \
  -map 0:v:0 -an -c:v copy -f rtsp -rtsp_transport tcp "$VISION_RTSP_URL"
```

USB 카메라는 먼저 출력 포맷을 확인한다.

```bash
v4l2-ctl --device /dev/video0 --list-formats-ext
```

`H264`가 있으면 `model.worker.media.stream_hub.ingress`의 `VideoEncoder.COPY`,
MJPEG/YUYV만 있으면 RTX 4060의 `VideoEncoder.NVENC`를 사용한다. CPU fallback은
`VideoEncoder.LIBX264`이며 두 호스트에서 다시 인코딩하지 않는다.

PC2에서는 스트림이 보이는지 먼저 확인하고 AI Compose를 시작한다.

```bash
export VISION_RTSP_URL='rtsp://viewer:MTX_VIEWER_PASS@PC1_LAN_IP:8554/pinky/CAM-PK-01'
ffprobe -v error -rtsp_transport tcp \
  -select_streams v:0 -show_entries stream=codec_name,width,height,r_frame_rate \
  -of default=noprint_wrappers=1 "$VISION_RTSP_URL"

# 한 프레임을 실제로 디코딩할 수 있는지 확인한다. timeout은 끊긴 stream에서 무한 대기하지 않게 한다.
timeout 10 ffmpeg -nostdin -v error -rtsp_transport tcp -i "$VISION_RTSP_URL" \
  -map 0:v:0 -frames:v 1 -f framemd5 -

docker compose -f compose.ai_5080.yaml up -d ai_runtime
docker compose -f compose.ai_5080.yaml logs -f --tail=100 ai_runtime
```

기대 codec은 `h264`다. 현재 저장소는 PC2 image에 전달할 RTSP 환경 계약과 FFmpeg
raw-frame 입력 argv까지 제공한다. 실제 YOLO/VLM model entrypoint와 모델 weight는
`TRIHOUSE_AI_IMAGE`에서 연결하고 서버 GPU에서 별도 검증한다.
