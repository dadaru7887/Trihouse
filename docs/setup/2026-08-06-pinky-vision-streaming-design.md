# Pinky Vision RTSP 스트리밍 ROS 2 설계

> 구현 기준 문서. 최소 ROS 2 송신·상태감시 범위가 `trihouse_interfaces`와
> `trihouse_pinky_vision`에 구현되었으며, 하드웨어 인수 테스트는 현장에서 수행한다.

## 1. 목표

2026-08-06에 검증한 카메라 경로를 로봇 하드웨어 없이도 빌드·테스트할 수 있는
ROS 2 패키지로 만들고, 이후 Pinky에서 하드웨어 인수 테스트를 수행한다. 이
패키지는 카메라 캡처, H.264 게시, 프로세스 복구, `StreamHealth`를 소유하며,
영상 자체는 ROS 2로 전달하지 않는다.

## 2. 범위

이 설계는 빌드 가능한 ROS 2 패키지 두 개를 추가한다.

- `trihouse_interfaces`: 첫 공용 인터페이스인 `StreamHealth.msg`.
- `trihouse_pinky/trihouse_pinky_vision`: 검증된 카메라 송신 파이프라인을
  관리하고 상태를 보고하는 Python ROS 2 패키지.

서버 측 검증 스크립트와 하드웨어 인수 절차도 함께 제공한다. MediaMTX는
저장 서버 PC의 독립 서비스이며 로봇 ROS 그래프에 포함하지 않는다.

### 배포 경계

`trihouse_pinky`는 엣지 장치 전용 디렉터리다. Pinky-Pro에서 실행하는 카메라
캡처, RTSP 게시, 프로세스 복구, 엣지 스트림 상태 코드만 둔다. 녹화, YOLO,
서버 오케스트레이션, 서버 배포 코드는 이 경로에 넣지 않는다.

최종 시스템은 서로 다른 서버 PC 두 대를 사용한다.

- **저장 서버 PC**: MediaMTX를 실행하고 RTSP 스트림을 녹화하며 녹화·저장
  상태를 보고한다.
- **YOLO 추론 서버 PC**: MediaMTX를 독립적으로 구독하여 최신 프레임을
  디코딩하고 YOLO를 실행하며, 검출 결과와 추론 상태를 보고한다.

두 서버 역할은 독립적으로 배포한다. YOLO 장애가 녹화를 멈추게 해서는 안 되며,
녹화 장애도 YOLO 서버의 실시간 스트림 수신을 멈추게 해서는 안 된다. 서버 코드는
`vision_perception` 아래에 두고, 공용 메시지 정의는 `trihouse_interfaces`에
두어 관제/FMS 계층에서 소비한다.

다음은 이 설계 범위에서 명시적으로 후속 처리한다.

- 카메라 intrinsic/extrinsic 보정과 TF 게시
- `MarkerObservation`, `PersonDetection` 좌표 변환
- 서버 추론·녹화 worker
- systemd 및 최종 `trihouse_pinky_bringup` 통합
- Wi-Fi, NetworkManager, 방화벽, OS 설정의 자동 변경

## 3. 검증된 기준 구성

구현은 성공한 2026-08-06 spike에서 측정한 다음 값을 유지해야 한다.

| 항목 | 검증값 |
|---|---|
| Robot | `pinky_1`, IP `192.168.0.21` |
| Board | Raspberry Pi 5 Model B Rev 1.1, `aarch64` |
| OS family | Ubuntu 24.04 (`noble`) |
| ROS domain | `ROS_DOMAIN_ID=11` |
| Camera | CSI OV5647, camera index `0` |
| Camera tool | `rpicam-apps v1.5.3`, libav enabled |
| Encoder | `libx264` software H.264 |
| Geometry | 1280x720, 15 FPS, horizontal and vertical flip |
| Rate control | target 2,000 kbps, IDR interval 15 frames |
| H.264 policy | baseline, zero latency, no local file output |
| Transport | RTSP over TCP |
| Publish URI | `rtsp://192.168.0.9:8554/pinky_1` |
| Server | RTX 4060, MediaMTX v1.19.3, TCP listener `:8554` |
| 인수 테스트 관측 | 599.93초에 8,997 프레임, 15 FPS, 종료 코드 0 |
| Pinky 부하 | `rpicam-vid` CPU 24.6% / MEM 1.2%, FFmpeg CPU 0.8% / MEM 0.6% |
| Pinky 온도 | 48분 이상 게시 후 48.5 C |
| Wi-Fi 확인 | `wlan0` power save가 on이며, 운영 시 off 필요 |

명목상 9,000 프레임과의 3프레임 차이는 수신기가 live-stream timestamp에서
시작하므로 패킷 손실로 단정하지 않는다. 명목 프레임 수의 0.033%로, 인수
기준인 1% 미만이다.

## 4. 아키텍처 결정

ROS 노드는 하드웨어 spike를 통과한 `rpicam-vid -> FFmpeg -> MediaMTX` 경로를
그대로 감독한다.

```text
Pinky-Pro [구현]
  OV5647
    -> rpicam-vid (libav/libx264, MPEG-TS on stdout)
    -> FFmpeg (demux/copy, RTSP/TCP publisher)
    -> 저장 서버 PC의 MediaMTX /pinky_1

  FFmpeg progress + process status + encoded-byte samples
    -> StreamHealth state machine
    -> /trihouse/vision/stream_health at 1 Hz

저장 서버 PC [후속 구현, 별도 배포]
  MediaMTX /pinky_1
    -> 녹화 worker -> 분할 영상 저장
    -> 녹화/저장 상태 -> 관제/FMS
    -> RTSP fan-out -> YOLO 추론 서버 PC

YOLO 추론 서버 PC [후속 구현, 별도 배포]
  MediaMTX RTSP subscription
    -> 최신 프레임 decoder(오래된 프레임 폐기)
    -> YOLO worker
    -> 검출 결과 + 추론 상태 -> 관제/FMS
```

이는 검증 경로를 새 GStreamer 카메라 파이프라인으로 교체하는 것보다 우선한다.
GStreamer는 후속 구현의 선택지로 남기되, 첫 배포 패키지는 측정된 하드웨어
경로에서의 변경을 최소화해야 한다.

노드는 인자 배열을 사용하는 `subprocess.Popen`을 써야 한다. shell 명령을 만들거나
`shell=True`를 사용하지 않는다. `rpicam-vid` stdout은 OS pipe로 FFmpeg stdin에
직접 연결하며, 어느 명령에도 파일 sink를 넣지 않는다.

## 5. 패키지·파일 경계

구현 범위는 `trihouse_pinky/trihouse_pinky_vision`과
`trihouse_interfaces/msg/StreamHealth.msg`까지다. 아래 서버 디렉터리는 필요한
후속 배치 위치를 설명하며, `trihouse_pinky`에 포함하지 않고 이 설계에서
구현하지 않는다.

```text
vision_perception/
├── recording_server/                  # [후속 구현] 저장 서버 PC 전용
│   ├── rtsp_recorder.py                # RTSP 녹화와 세그먼트 교체
│   ├── storage_health.py               # 디스크·쓰기·녹화 상태
│   └── docker-compose.yml              # MediaMTX·녹화기 배포
├── yolo_inference_server/              # [후속 구현] YOLO 서버 PC 전용
│   ├── rtsp_reader.py                  # 독립 MediaMTX 구독
│   ├── yolo_worker.py                  # 최신 프레임 객체 검출
│   ├── detection_publisher.py          # 검출 결과를 관제/FMS에 전달
│   ├── inference_health.py             # GPU·FPS·지연·모델 상태
│   └── docker-compose.yml              # CUDA/YOLO 배포
├── augmentation/                       # 기존 오프라인 데이터 도구
├── data_collection/                    # 기존 데이터 수집 도구
└── segmentation/                       # 기존 세그멘테이션 실험

trihouse_interfaces/
├── msg/StreamHealth.msg                # [구현] Pinky 엣지 상태
├── msg/Detection.msg                   # [후속 구현] YOLO 결과 계약
├── msg/RecordingHealth.msg             # [후속 구현] 저장 서버 상태
└── msg/InferenceHealth.msg             # [후속 구현] YOLO 서버 상태
```

```text
trihouse_interfaces/
├── CMakeLists.txt
├── package.xml
├── msg/
│   └── StreamHealth.msg
└── test/
    └── test_stream_health_interface.py

trihouse_pinky/trihouse_pinky_vision/
├── package.xml
├── setup.py
├── setup.cfg
├── resource/
│   └── trihouse_pinky_vision
├── launch/
│   └── vision.launch.py
├── config/
│   └── pinky_1.yaml
├── scripts/
│   └── verify_rtsp.sh
├── trihouse_pinky_vision/
│   ├── __init__.py
│   ├── camera_streamer_node.py
│   ├── command_builder.py
│   ├── process_supervisor.py
│   ├── process_metrics.py
│   └── stream_health.py
└── test/
    ├── fixtures/
    │   ├── fake_camera.py
    │   └── fake_publisher.py
    ├── test_command_builder.py
    ├── test_process_supervisor.py
    ├── test_stream_health.py
    └── test_vision_launch.py
```

책임:

- `command_builder.py`는 타입이 있는 설정을 검증하고 두 argv 배열을 반환한다.
  `rpicam-vid`와 FFmpeg flag를 아는 유일한 모듈이다.
- `process_supervisor.py`는 프로세스 쌍을 시작·관측·정지·재시작한다. ROS
  개념을 소유하지 않으며 테스트를 위해 process factory를 받는다.
- `process_metrics.py`는 FFmpeg progress record를 파싱하고 Linux에서
  `rpicam-vid`가 쓴 인코딩 바이트를 샘플링한다. 상태를 판정하지 않고 측정값을
  반환한다.
- `stream_health.py`는 측정값과 주입받은 monotonic clock으로 동작하는 결정론적
  상태 머신이다.
- `camera_streamer_node.py`는 ROS parameter를 선언하고 모듈을 연결하며,
  1 Hz 상태를 게시하고 종료 시 정리를 보장한다.
- `vision.launch.py`는 로봇 profile 하나를 불러 streamer node 하나를 시작한다.
- `verify_rtsp.sh`는 URI에 `ffprobe`와 제한 시간 FFmpeg decode를 수행하며,
  미디어를 녹화하지 않는다.

## 6. `StreamHealth` 계약

`trihouse_interfaces/msg/StreamHealth.msg`는 다음을 포함한다.

```text
uint8 STATE_UNKNOWN=0
uint8 STATE_HEALTHY=1
uint8 STATE_DEGRADED=2
uint8 STATE_DISCONNECTED=3
uint8 STATE_RECOVERING=4

string camera_id
uint8 state
float32 fps
float32 bitrate_kbps
builtin_interfaces/Time last_frame_stamp
string detail
builtin_interfaces/Time stamp
```

의미:

- `last_frame_stamp`는 FFmpeg가 마지막으로 엄격히 증가한 출력 frame count를
  보고한 ROS 시간이다. 카메라 센서 timestamp가 아니다.
- `stamp`는 메시지 게시 시각이다.
- `fps`는 FFmpeg가 출력한 누적 평균이 아니라 rolling window의 frame-count
  delta로 계산한다.
- `bitrate_kbps`는 byte counter delta로 계산한 관측 인코딩 스트림 추정값이다.
  값이 `0.0`이면 측정 불가를 뜻하며 `detail`에 이유를 넣어야 한다.
- `detail`에는 `no_progress`, `publisher_exit`, `healthy`와 같은 안정된 reason
  token 뒤에 선택적 진단 문자열을 넣는다.

토픽은 reliable, volatile, keep-last-10 QoS의
`/trihouse/vision/stream_health`다. ROS 토픽에는 영상 payload, 인코딩 fragment,
이미지를 넣지 않는다.

## 7. 설정 계약

`pinky_1.yaml` profile은 검증된 기본값을 고정하되, launch에서 로봇 ID와 서버
주소를 덮어쓸 수 있게 한다.

| parameter | 기본값 |
|---|---|
| `camera_id` | `pinky_1` |
| `camera_index` | `0` |
| `publish_uri` | `rtsp://192.168.0.9:8554/pinky_1` |
| `width` / `height` | `1280` / `720` |
| `fps` | `15.0` |
| `bitrate_kbps` | `2000` |
| `keyframe_interval` | `15` |
| `hflip` / `vflip` | `true` / `true` |
| `encoder` | `libx264` |
| `encoder_preset` | `veryfast` |
| `encoder_profile` | `baseline` |
| `transport` | `tcp` |
| `health_publish_hz` | `1.0` |
| `degraded_after_sec` | `1.0` |
| `disconnected_after_sec` | `3.0` |
| `healthy_after_sec` | `5.0` |
| `restart_backoff_sec` | `[1, 2, 4, 8, 16, 30]` |
| `rpicam_executable` | `/usr/local/bin/rpicam-vid` |
| `ffmpeg_executable` | `/usr/bin/ffmpeg` |

검증은 0 이하의 해상도·FPS·bitrate·keyframe 값, `/`가 든 카메라 ID, `rtsp`
scheme이 없는 게시 URI, 마지막 경로 요소가 `camera_id`와 다른 URI를 거부한다.

노드는 잘못된 profile을 시작 오류로 보고하며 자식 프로세스를 시작하지 않는다.

## 8. 상태·복구 상태 머신

상태 머신은 구간 계산에 monotonic time을 사용하고, 게시 timestamp에만 ROS time을
사용한다.

- 시작 시 프로세스를 실행하기 전에 `RECOVERING`으로 진입한다.
- `HEALTHY`는 두 자식 프로세스가 살아 있고 frame count가 단조 증가하며, 5초
  연속 목표 FPS의 90% 이상일 때만 진입한다.
- `DEGRADED`는 새 frame이 1초 이상 없거나, rolling FPS가 목표의 50% 미만이거나,
  FPS가 목표의 50~90% 사이에서 10초 동안 정상에 도달하지 않을 때 진입한다.
- `DISCONNECTED`는 새 frame이 3초 동안 없거나, 자식 프로세스 중 하나가
  종료되거나, 프로세스 간 pipe가 끊기거나, RTSP 게시가 실패할 때 진입한다.
- 재시작하면 `RECOVERING`으로 바뀐다. frame이 재개되어도 즉시 정상은 아니며
  5초 healthy gate를 다시 통과해야 한다.

재시작 지연은 1, 2, 4, 8, 16, 30초이며 최대 30초로 제한한다. 30초 연속 정상
상태면 지연 순서를 다시 1초로 초기화한다.

ROS node 정지는 실패가 아니다. 종료 시 supervisor는 SIGINT를 보내 3초 기다리고,
SIGTERM을 보내 2초 기다린 뒤 남아 있는 자식에만 SIGKILL을 보낸다. 항상 두
프로세스를 회수한다.

vision 패키지는 상태만 보고하며 로봇 작업을 재개하지 않는다. fleet과 bringup은
후속 구현에서 `StreamHealth`를 준비 상태 입력으로 사용하고, 영상 의존 작업을
재개하기 전에 새 marker/authorization 검사를 요구한다.

## 9. Wi-Fi 정책

운영 profile은 로봇이 영상을 연속 게시하고 idle radio 절전보다 지연과 안정성을
우선하므로 `wlan0` power save를 off로 요구한다. ROS node는 `iw`를 호출하거나,
NetworkManager를 변경하거나, sudo를 요구해서는 안 된다. 이 설정은 하드웨어
인수 테스트 중 운영자가 확인·기록한다.

배포 체크리스트에는 되돌릴 수 있는 명령을 두되, 실제 적용은 별도 운영자 작업이다.

```bash
sudo iw dev wlan0 set power_save off
sudo nmcli connection modify trihouse 802-11-wireless.powersave 2
```

현재 로봇에는 이 영구 설정을 아직 적용하지 않았다. power save off 상태의 배터리
지속 시간은 후속 운영 시험에서 측정해야 한다.

## 10. 하드웨어 없는 테스트 설계

로컬 개발은 Pinky, OV5647, MediaMTX, RTX 4060을 요구해서는 안 된다.

단위 테스트는 주입한 clock과 process factory를 사용한다. fixture 프로그램은 두
자식 프로세스를 모사한다. camera fixture는 제한된 byte chunk를 내보내고,
publisher fixture는 stdin을 소비해 FFmpeg 형식의 progress record를 낸다.

자동 테스트는 다음을 포함해야 한다.

1. 양쪽 flip과 파일 출력 부재를 포함한 정확한 검증 argv 생성
2. 잘못된 profile 값과 불일치 URI/카메라 ID 거부
3. 시작 후 5초 정상 진행을 거친 `RECOVERING`에서 `HEALTHY` 전이
4. 진행 없이 1초가 지나면 `DEGRADED` 전이
5. 3초 뒤 또는 자식 프로세스 종료 시 `DISCONNECTED` 전이
6. 재시작 지연과 30초 정상 뒤 초기화
7. 같은 frame count를 새 frame으로 허용하지 않음
8. 자식 정리 escalation과 프로세스 회수
9. 관측 bitrate 계산과 측정 불가 fallback
10. fixture 프로세스에서 1 Hz `StreamHealth`를 관측하는 ROS launch 테스트
11. 두 fixture 자식이 모두 종료됨을 보이는 shutdown 테스트
12. 운영 명령에 파일 출력 경로가 없음을 보이는 source scan

현장 방문 전에 ROS 2 Jazzy에서 `colcon test`를 통과해야 한다.

## 11. 하드웨어 인수 테스트

다음 현장 세션은 아래 순서로 수행한다.

1. `192.168.0.9`의 저장 서버 PC에서 RTSP TCP를 활성화한 MediaMTX v1.19.3을 시작한다.
2. Pinky에서 `trihouse_interfaces`, `trihouse_pinky_vision`을 빌드·source한다.
3. `pinky_1.yaml` profile을 launch하고 `RECOVERING -> HEALTHY`를 확인한다.
4. `ffprobe`로 H.264 baseline, 1280x720, 15 FPS를 확인한다.
5. FFmpeg `-xerror`로 600초 decode한다. 종료 코드 0, 약 9,000 프레임,
   손상 frame·decode 오류 없음을 요구한다.
6. Nav2를 함께 실행하며 Pinky CPU, 메모리, 온도를 기록한다.
7. publisher 프로세스를 종료해 `DISCONNECTED`, 제한된 재시작,
   `RECOVERING`을 거친 `HEALTHY` 복귀를 확인한다.
8. MediaMTX를 3초 이상 정지한 뒤 다시 시작하고 같은 복구 경로를 확인한다.
9. Pinky에 영상·이미지 파일이 생성되지 않았음을 확인한다.
10. Wi-Fi power save를 일시적으로 off로 설정해 안정성 테스트를 반복한 후,
    운영자 승인 뒤에만 영구 설정으로 바꾼다.

전원이 켜진 Raspberry Pi에서 CSI 리본 케이블을 분리하지 않는다. 물리 단절 시험을
위해 로봇을 완전히 끄는 경우가 아니라면, camera 프로세스를 종료해 카메라 실패를
모사한다.

## 12. 인수 기준

첫 구현은 다음을 모두 만족할 때 인수한다.

- 두 ROS 2 패키지가 Jazzy에서 빌드되고 모든 하드웨어 없는 테스트가 통과한다.
- 단일 launch 명령으로 로컬 미디어 파일 없이 `pinky_1`을 게시한다.
- 지정한 상태 의미로 `StreamHealth`를 1 Hz로 게시한다.
- 자식 종료와 서버 장애가 제한된 자동 복구를 유발한다.
- live stream이 10분 동안 1280x720, 10~15 FPS를 유지한다.
- 수신 decode가 종료 코드 0으로 끝나고 frame-count 부족이 안정성 대리 지표로서
  1% 미만이며 decoder log에 오류가 없다. 이 지표는 직접적인 packet-loss
  측정값으로 보고하지 않는다.
- Nav2가 활성화된 상태에서도 Pinky에 충분한 CPU·온도 여유가 있다.
- 구현이 `pinky_pro`를 수정하거나 ROS 2로 영상을 게시하지 않는다.
