# 영상 송수신 구현 지도

작성: 2026-08-20 · 브랜치 `feat/pinky-edge-agent`
**이 문서는 코드를 읽어 확인한 사실만 적는다.** 기준 아키텍처(왜 이렇게 정했는지)는
[vision_data_flow.md](../architecture/vision_data_flow.md) 이고, 이 문서는 그 규약이
실제로 **어느 파일에** 구현돼 있는지를 짚는다.

한 줄 요약: **모든 영상은 FFmpeg 로 H.264 RTSP 를 만들어 PC1(4060) MediaMTX 한 곳에
모으고, 소비자는 전부 그 canonical RTSP URL 만 읽는다.**

---

## 0. 전체 흐름

```text
[송신]                                [중계]                      [수신]
Pinky rpicam-vid → ffmpeg copy ──┐
USB MJPEG/YUYV → ffmpeg nvenc ───┼─→ MediaMTX 1.19.3 ──┬─→ PC2(5080) 추론: ffmpeg → BGR raw
USB H.264 → ffmpeg copy ─────────┘   rtsp://PC1:8554/   ├─→ 녹화: MediaMTX record + segment recorder
                                     <role>/<camera_id> ├─→ HLS(8888) / WebRTC(8889) → UI
                                                        └─→ ffprobe/ffmpeg 검증 · soak 계측
```

경로 규약은 `<역할 접두사>/<camera_id>` **두 segment** (`pinky/CAM-PK-01`).
`camera_id` 가 전역 유일하므로 `StreamHealth.msg` 가 `robot_id` 를 싣지 않고도 PK_01 과
PK_02 를 구분한다. 세 segment 규약(`pinky/<robot_id>/<camera_id>`)은 폐기됐다.

재인코딩은 **경계마다 한 번**이다. Native H.264 는 `-c:v copy` 로 흘려보내고,
MJPEG/YUYV 만 카메라가 붙은 호스트에서 한 번 H.264 로 인코딩한다. 4060 과 5080 에서
연속 재인코딩하지 않는다.

---

## 1. 송신 — Pinky 로봇 (rpicam-vid → FFmpeg → RTSP)

ROS 2 패키지 [trihouse_pinky_vision](../../trihouse_pinky/trihouse_pinky_vision/) 이 담당한다.

| 파일 | 줄 | 역할 |
|---|---|---|
| [command_builder.py](../../trihouse_pinky/trihouse_pinky_vision/trihouse_pinky_vision/command_builder.py) | 107 | `StreamConfig` 검증 + argv 2개 생성 |
| [camera_streamer_node.py](../../trihouse_pinky/trihouse_pinky_vision/trihouse_pinky_vision/camera_streamer_node.py) | 236 | 두 프로세스 감독 + `StreamHealth` 발행 |
| [process_supervisor.py](../../trihouse_pinky/trihouse_pinky_vision/trihouse_pinky_vision/process_supervisor.py) | 250 | 파이프 연결 · 종료 단계 · 재시작 backoff |
| [process_metrics.py](../../trihouse_pinky/trihouse_pinky_vision/trihouse_pinky_vision/process_metrics.py) | 87 | `ffmpeg -progress` 파싱, 비트레이트 산출 |
| [stream_health.py](../../trihouse_pinky/trihouse_pinky_vision/trihouse_pinky_vision/stream_health.py) | 194 | ROS 비의존 상태기계 |
| [launch/vision.launch.py](../../trihouse_pinky/trihouse_pinky_vision/launch/vision.launch.py) | 24 | `camera_streamer` 노드 기동 |
| [config/pinky_1.yaml](../../trihouse_pinky/trihouse_pinky_vision/config/pinky_1.yaml) | — | PK_01 송신 설정 |
| [scripts/verify_rtsp.sh](../../trihouse_pinky/trihouse_pinky_vision/scripts/verify_rtsp.sh) | — | 수신 확인 스크립트 |

**파이프라인.** `rpicam-vid` 가 libx264 baseline / `--libav-format mpegts` 로 stdout 에
뱉고, `ffmpeg` 가 `-f mpegts -i pipe:0 -c:v copy -f rtsp -rtsp_transport tcp` 로
재인코딩 없이 publish 한다. 운영 값은 1280×720 / 15 fps / 2000 kbps / GOP(`--intra`) 15
/ hflip·vflip.

**부팅 시점 강제.** `StreamConfig.__post_init__` 이 `publish_uri` 의 마지막 segment 와
`camera_id` 의 일치를 강제한다. 둘 중 하나만 고치면 노드가 뜨지 않는다. `transport` 는
`tcp` 만 허용.

**멈춘 발행자 탈출.** `-rw_timeout 5000000`(5초)은 반쯤 닫힌 TCP 에 쓰다가 FFmpeg 가
무한히 멈추는 것을 막는다. 고장 *감지* 는 `disconnected_after_sec: 3.0` 이 이미 하므로
이 값은 3초보다 위여야 하고, 출력 옵션이라 출력 URL **앞**에 와야 한다.

**감독.** `ProcessSupervisor` 가 SIGINT(3s) → SIGTERM(2s) → SIGKILL 로 내리고,
`RestartBackoff` 가 1 → 2 → 4 → 8 → 16 → 30 초로 늘리되 30초 정상 지속 시 리셋한다.

**건강 상태.** `StreamHealthStateMachine` 은 UNKNOWN / HEALTHY / DEGRADED(1s 침묵) /
DISCONNECTED(3s) / RECOVERING(5s 지속해야 HEALTHY). `trihouse/vision/stream_health` 에
1 Hz, RELIABLE / KEEP_LAST(10) 로 발행한다.

---

## 2. 송신 — USB 카메라 (OMX 손목 · 창고 고정)

- [vision_system/stream_hub/ingress.py](../../vision_system/stream_hub/ingress.py)

`UsbIngressConfig` 가 v4l2 입력을 받아 FFmpeg argv 를 만든다. 입력이 H.264 면 `copy`,
MJPEG/YUYV422 면 `h264_nvenc`(`-preset p1 -tune ull`) 또는 `libx264`
(`veryfast` / `zerolatency`) 로 **한 번만** 인코딩한다. `copy` 는 H.264 입력이 아닐 때
거절된다. `StreamIdentity(role, camera_id)` 가 `<role>/<camera_id>` 경로와 publish URL
을 만들고, `mediamtx_base_url` 은 경로 없는 RTSP origin 이어야 한다.
기본값 1280×720 / 15 fps / 3000 kbps.

손목 카메라는 **OMX 가 붙은 일반 PC** 가, 고정 카메라는 **4060** 이 publish 한다.

---

## 3. 중계 — MediaMTX

- [config/mediamtx.yml](../../config/mediamtx.yml) — 인가 · 녹화 · 경로 정책
- [compose.edge_4060.yaml](../../compose.edge_4060.yaml) — 컨테이너와 주입값
- [compose.ai_5080.yaml](../../compose.ai_5080.yaml) — 수신 측 환경변수

**서버.** RTSP TCP 전용(`rtspTransports: [tcp]`), RTMP/SRT 끔, HLS(8888) ·
WebRTC(8889/8189udp) · API(9997) · metrics(9998) · playback(9996) 켬. 이미지 태그는
`bluenviron/mediamtx:1.19.3` 으로 핀 고정 — 2026-08-06 물리 검증(599.93 s, 8,997 frames)
이 그 버전 기준이다.

**인가는 비대칭이다.** publish 는 **출발지 IP 허용목록**, read 는 **`viewer` 계정**.
RTSP 는 자격 증명을 URL 안에만 실을 수 있어서 publish 를 계정으로 막으면 비밀번호가
로봇의 package-share YAML 과 `ps` 출력에 노출된다. 반면 PC2 는 이미 URL 을 환경변수로
받으므로 비밀번호를 붙여도 코드가 바뀌지 않는다. 감수하는 비용: DHCP 주소 예약이
필요하고 IP 위장은 막지 못한다.

**주의 세 가지.**
1. `config/mediamtx.yml` 안의 IP 는 전부 RFC 5737(192.0.2.0/24) 자리표시자다. 그대로
   배포하면 publish 가 전부 거절된다(fail closed). 실주소는 `.env` → Compose 주입.
2. MediaMTX 1.19.3 은 설정 파일 안의 `${VAR}` 를 전개하지 않는다. 그래서 비밀번호를
   파일에 적지 않고 `MTX_AUTHINTERNALUSERS_<n>_*` 환경변수로 넣는다. **그 색인은
   `authInternalUsers` 목록의 순서에 종속** — 순서를 바꾸면 로봇에 다른 로봇의 경로
   권한이 조용히 넘어간다.
3. `paths` 에 6개 경로를 명시하고 `all_others` 를 두지 않는다. 미등록 경로는 인가
   이전에 존재 자체가 400 으로 거절된다.

**녹화 기본값.** `record: yes`, `/recordings/%path/...`, fmp4, 60초 segment, 168h 보존.
`TRIHOUSE_RECORD_*` 로 `.env` 에서 조절한다.

---

## 4. 수신 — PC2(5080) 추론

| 파일 | 역할 |
|---|---|
| [vision_system/inference_common/stream.py](../../vision_system/inference_common/stream.py) | RTSP → 고정 크기 BGR raw frame |
| [vision_system/person_worker/worker.py](../../vision_system/person_worker/worker.py) | 검출 → 자세 → 낙상 상태전이 |
| [vision_perception/segmentation/inference_stream.py](../../vision_perception/segmentation/inference_stream.py) | OpenCV 기반 로컬 검증 경로 |

`InferenceStreamConfig.from_env()` 가 `VISION_RTSP_URL` 을 읽는다. **`VISION_CAMERA_ID`
는 일부러 없다** — `camera_id` 는 URL 마지막 segment 에서 property 로 파생한다. 필드로
두면 `from_env` 바깥에서 만든 객체가 어긋난 값을 들 수 있지만, 파생하면 어긋난 값을
표현할 방법 자체가 없다. 발행자 쪽 규칙과 같은 규칙이다.

`build_ffmpeg_frame_command()` 는 `-fflags nobuffer -flags low_delay -probesize 32
-analyzeduration 0` 로 지연을 줄이고 `fps=N,scale=W:H` → `bgr24 rawvideo` 를 stdout 으로
낸다. 소비자는 반드시 `frame_size_bytes` 단위로 읽고, 모델이 느리면 과거 frame 을
처리하지 말고 decoder 를 재동기화하거나 latest-frame slot 을 써야 한다.

`person_worker` 는 한 번의 추론에서 두 갈래를 낸다 — 사람 위치·신뢰도(로봇 안전 gate 로)
와 낙상 이벤트(관제로). ROS 발행은 하지 않는다(GPU 서버에서 ROS 없이 돌릴 수 있게).

`inference_stream.py` 는 프레임 **해시**까지 봐서 freeze(연결은 살아 있는데 같은 프레임
반복)를 잡고, DISCONNECTED 면 action queue 와 authorization 을 즉시 폐기한다. 재연결
후에도 재인증 전에는 재개하지 않는다.

---

## 5. 수신 — 녹화

| 파일 | 줄 | 역할 |
|---|---|---|
| [recording_server/recorder.py](../../vision_system/recording_server/recorder.py) | 149 | 60초 H.264 분할 녹화 프로세스 |
| [recording_server/catalog.py](../../vision_system/recording_server/catalog.py) | 90 | segment 상태 · 보존 정책 |

`build_ffmpeg_segment_command()` 는 `-c:v copy -f segment -segment_time 60
-reset_timestamps 1 -strftime 1` 로 **재인코딩 없이** 자른다. recorder 는 파일을 직접
지우지 않는다 — 보존 정책이 안전하다고 판정한 segment ID 만 돌려주고 저장소 worker 가
지운다. 카탈로그는 완료(COMPLETE)됐고 재생 중이 아닌 segment 만 삭제 후보로 낸다.

MediaMTX 자체 녹화와 이 recorder 가 **둘 다** 있다. 녹화본은 감사 기록이자 학습
코퍼스이며, 학습 프레임을 녹화본에서 뽑는 이유는 학습 데이터가 운영 추론과 **같은
인코딩 사슬**을 지나게 하기 위해서다.

---

## 6. 수신 — 검증 · 계측 · UI

| 파일 | 역할 |
|---|---|
| [verify_rtsp.sh](../../trihouse_pinky/trihouse_pinky_vision/scripts/verify_rtsp.sh) | `ffprobe` 로 codec/profile/해상도/fps 확인 → `ffmpeg -xerror -f null -` 로 연속 디코딩(최대 3600s) |
| [scripts/camera_soak_test.py](../../scripts/camera_soak_test.py) | 6스트림 30분 soak. 1800초 미만이면 `UNMEASURED` 판정 |
| [camera_wall.dart](../../control_ui/rmf_control_ui/lib/trihouse/features/operations/camera_wall.dart) | 이벤트가 필요한 카메라만 여는 벽. 6대 동시 디코딩 안 함 |
| [live_view.dart](../../control_system/roboapp/lib/ui/live_view.dart) | flutter_webrtc 뷰어 |
| [pinky_camera_server.py](../../vision_perception/segmentation/pinky_camera_server.py) | MJPEG/HTTP 폴백 (기본 경로 아님) |

`verify_rtsp.sh` 는 다른 호스트에서 쓸 때 read 가 계정으로 막혀 있으므로 자격 증명을
URI 에 실어야 한다: `rtsp://viewer:$MTX_VIEWER_PASS@<PC1>:8554/pinky/CAM-PK-01`.

`pinky_camera_server.py` 의 프레임은 **학습 세트에 넣지 않는다.** JPEG 독립 프레임 ·
품질 95 · 무제한 fps 라서 운영(H.264 baseline 2 Mbps / 15 fps)과 픽셀이 다르고,
세그멘테이션이 민감한 경계를 저비트레이트 아티팩트가 뭉개기 때문이다. 카메라가 살아
있는지 눈으로 볼 때만 쓴다.

---

## 7. 식별자 정본

| 파일 | 역할 |
|---|---|
| [config/cameras.yaml](../../config/cameras.yaml) | 카메라 명부 정본 6대 |
| [control_tower/gateway/camera_registry.py](../../control_tower/gateway/camera_registry.py) | 위 YAML 검증 로더 (155줄) |
| `trihouse_interfaces` `StreamHealth.msg` | camera_id / state / fps / bitrate_kbps / last_frame_stamp / detail / stamp |

명부를 파일 하나로 두는 이유는 두 가지다. `map_revisions.manifest` 는 스키마가 불변이라
카메라 주소가 바뀔 때마다 지도 내용이 같은 새 revision 을 발행해야 하고(주행 revision 이
흔들린다), Pinky 의 `camera_streamer` 는 부팅 시 이 값이 필요한데 네트워크 조회에
의존하면 네트워크 장애 진단 수단이 네트워크에 묶인다.

운영 경로(`stream_path`)는 저장하지 않고 `ROLE_STREAM_PREFIX`(pinky_travel→`pinky`,
omx_wrist→`omx`, warehouse_fixed→`fixed`)와 `camera_id` 로 파생한다. 반면 P0 fixture
경로는 이름 규칙이 카메라마다 달라 파생할 수 없으므로 `simulation_path` 로 적고,
`fixtures/` 접두사로 실스트림과 구분한다. 로봇에 붙은 카메라에 `map_pose` 를 주는 것은
거절된다 — 함께 움직이는 카메라의 고정 좌표는 언제나 거짓이다.

---

## 8. 테스트

**송신:** [test_command_builder.py](../../trihouse_pinky/trihouse_pinky_vision/test/test_command_builder.py) ·
[test_camera_streamer_node.py](../../trihouse_pinky/trihouse_pinky_vision/test/test_camera_streamer_node.py) ·
[test_process_supervisor.py](../../trihouse_pinky/trihouse_pinky_vision/test/test_process_supervisor.py) ·
[test_process_metrics.py](../../trihouse_pinky/trihouse_pinky_vision/test/test_process_metrics.py) ·
[test_stream_health.py](../../trihouse_pinky/trihouse_pinky_vision/test/test_stream_health.py) ·
[test_verify_rtsp_script.py](../../trihouse_pinky/trihouse_pinky_vision/test/test_verify_rtsp_script.py) ·
[test_vision_launch.py](../../trihouse_pinky/trihouse_pinky_vision/test/test_vision_launch.py)

**수신:** [test_stream_ingress.py](../../vision_system/tests/test_stream_ingress.py) ·
[test_inference_stream.py](../../vision_system/tests/test_inference_stream.py) ·
[test_recorder.py](../../vision_system/tests/test_recorder.py) ·
[test_recording_catalog.py](../../vision_system/tests/test_recording_catalog.py)

**계약:** [test_vision_compose_contract.py](../../vision_system/tests/test_vision_compose_contract.py)
가 `config/cameras.yaml`(정본)과 `config/mediamtx.yml`(파생 사본)의 경로 목록을 대조한다.

---

## 9. 아직 비어 있는 곳

| 항목 | 상태 |
|---|---|
| UI 실시간 재생 | [live_view.dart](../../control_system/roboapp/lib/ui/live_view.dart) 는 **로컬 웹캠**을 띄운다. MediaMTX WebRTC(8889) 시그널링 접속 + 원격 트랙 구독이 미구현. 렌더러와 화면 구성은 그대로 쓸 수 있다 |
| `recording_catalog` 컨테이너 | `application_images` profile 로 비활성. MediaMTX API 가 loopback(항목 [7])만 허용해서 compose 브리지에서 오는 요청은 거절된다. 켜기 전에 "compose subnet 에 `api` 권한을 주기" vs "디스크에서 녹화 트리를 읽기" 중 하나를 **의도적으로** 골라야 한다 — API 는 설정을 다시 쓸 수 있으므로 loopback 규칙을 반사적으로 넓히지 말 것 |
| `qr_worker` 컨테이너 | 같은 profile 로 비활성. 장수 entrypoint 가 생긴 뒤에 켠다 |
| MediaMTX 인가 IP | 자리표시자(fail closed). `.env` 에 `PINKY_PK_01_IP` / `PINKY_PK_02_IP` / `OMX_PC_01_IP` / `OMX_PC_02_IP` / `PC1_PUBLISHER_IP` / `MTX_VIEWER_PASS` 를 채워야 뜬다 |
| 6스트림 soak | `camera_soak_test.py` 는 있으나 실제 호스트 30분 계측 전까지 상태는 `UNMEASURED` |
