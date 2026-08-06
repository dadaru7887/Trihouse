# trihouse_pinky_vision

> 상태: 구현 계획. 현재는 README만 존재하며 ROS 2 노드, launch, YAML 또는 스크립트는 없다.

## 1. 목적과 책임

Pinky 내장 카메라를 안정적인 장치 경로로 열어 H.264/RTSP로 MediaMTX에 게시하고 스트림 상태를 보고한다. 카메라 intrinsic/extrinsic과 `camera_optical_frame`을 소유하며 서버 관측을 `base_link`로 변환한다.

영상 본체의 방향은 Pinky가 RTX 4060으로 **송신**하고 RTX 4060이 해당 RTSP 경로를 **수신**하는 구조다.

## 2. 넣지 않을 기능

- 연속 `sensor_msgs/Image`, JPEG/PNG, H.264 조각 또는 base64 영상을 ROS 2로 배포하지 않는다.
- Pinky 로컬에 영상/이미지를 저장하거나 네트워크 단절 시 로컬 녹화로 전환하지 않는다.
- 사람·ArUco 모델 추론, safety 정지 판단, docking 제어를 넣지 않는다.

## 3. 계획된 노드와 작업

- `camera_streamer_node`: GStreamer pipeline과 bus의 EOS/ERROR/reconnect 관리
- `stream_health_monitor`: frame timestamp/FPS/bitrate/freeze 상태를 1 Hz로 보고
- `camera_geometry_node`: calibration 로드, TF 게시, 관측 좌표 변환
- 안정적인 `/dev/v4l/by-id/` 식별과 제한된 exponential backoff
- 오래된 frame을 버리는 bounded RAM queue

초기 확인은 `gst-launch-1.0`으로 수행하고, 측정값이 확정된 뒤 Python GStreamer binding 기반 ROS 2 노드로 감싼다.

## 4. 발행·구독 토픽

- 발행 계획: `/trihouse/vision/stream_health` (`StreamHealth`), base-frame `MarkerObservation`, base-frame `PersonDetection`, camera TF
- 구독 계획: 서버 추론 브리지의 camera-frame `MarkerObservation`, `PersonDetection`
- 비대상: 실물 운영 영상의 ROS 2 image topic

## 5. 제공·호출 서비스

초기 계획에는 없다. 향후 진단용 restart 요청을 추가하더라도 lifecycle/권한 경계를 별도로 설계한다.

## 6. 제공·호출 액션

없음.

## 7. 사용하는 공용 인터페이스

`StreamHealth`, `MarkerObservation`, `PersonDetection`.

## 8. pinky_pro 참조

`pinky_description`의 카메라 link를 include/확장하고 `pinky_gz_sim` image bridge는 시뮬레이션 인지 검증에만 사용한다. Gazebo image bridge를 실물 RTSP 구현 완료로 간주하지 않는다.

## 9. 설정 파일 후보

| 항목 | 초기값/규칙 |
|---|---|
| `camera_id` | 1호기 `pinky_1`, 2호기 `pinky_2` |
| `device` | 실측한 `/dev/v4l/by-id/...-video-index0` |
| `publish_uri` | `rtsp://192.168.0.9:8554/<camera_id>` |
| profile | `1280x720`, 10~15 FPS, 1.5~3 Mbps |
| keyframe | 1초 |
| transport | 초기 RTSP/TCP, 반복 손실 시 같은 ID로 SRT 검토 |
| queue | 오래된 frame 폐기, RAM 최대 3 frame 후보 |
| calibration | `calibration/<camera_id>/{intrinsics.yaml,extrinsics.yaml}` 후보 |

## 10. 구현 순서와 완료 조건

1. 하드웨어와 카메라 포맷을 실측한다.
2. 가장 비용이 낮은 H.264 pipeline을 선택해 수동 송수신한다.
3. CPU, FPS, frame drop과 재접속을 측정한다.
4. GStreamer pipeline manager와 상태 머신을 테스트 주도로 구현한다.
5. `StreamHealth`와 자동 재접속을 추가한다.
6. 최종 RTSP decode frame으로 calibration하고 TF/좌표 변환을 추가한다.

완료 조건은 10분 연속 720p 10~15 FPS, frame drop 1% 이하, timestamp 단조 증가, USB/네트워크 단절 탐지와 복구, 로컬 저장 없음, Nav2와 함께 실행할 CPU 여유가 입증되는 것이다.

## 오늘 할 일: 카메라 영상 송수신 spike

### Step 0 — Pinky에서 사실 확인

```bash
cat /proc/device-tree/model
v4l2-ctl --list-devices
ls -l /dev/v4l/by-id/
v4l2-ctl -d /dev/video0 --list-formats-ext
v4l2-ctl -d /dev/video0 --list-ctrls | grep -i -E 'bitrate|i_frame|h264'
gst-inspect-1.0 | grep -i 264
```

기록할 값은 보드 모델, 고정 device 경로, 지원 해상도/FPS별 `H264/MJPG/YUYV`, bitrate/I-frame control, 사용 가능한 encoder다. `/dev/video0` 번호는 재부팅 때 바뀔 수 있으므로 운영 설정에 직접 쓰지 않는다.

필요 도구가 없다면 Pinky에서 설치한다.

```bash
sudo apt install -y v4l-utils gstreamer1.0-tools \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly
```

### Step 1 — encoder 선택

1. 카메라가 H.264를 직접 출력하면 재인코딩하지 않는다.
2. MJPG/YUYV이고 Pi 4의 `v4l2h264enc`가 있으면 hardware encoding을 쓴다.
3. Pi 5이거나 hardware encoder가 없으면 `x264enc`를 쓰고 CPU를 반드시 측정한다.

### Step 2-A — UVC H.264 직접 송신

`DEVICE_PATH`와 `pinky_1`을 실측값/로봇 ID로 바꾼다.

```bash
gst-launch-1.0 -v \
  v4l2src device=DEVICE_PATH \
  ! video/x-h264,width=1280,height=720,framerate=15/1 \
  ! h264parse config-interval=1 \
  ! rtspclientsink location=rtsp://192.168.0.9:8554/pinky_1 protocols=tcp
```

카메라 control이 지원될 때만 다음과 같이 적용한다.

```bash
v4l2-ctl -d DEVICE_PATH -c video_bitrate=2000000 -c h264_i_frame_period=15
```

### Step 2-B — Pi 4 hardware H.264 송신

```bash
gst-launch-1.0 -v \
  v4l2src device=DEVICE_PATH \
  ! image/jpeg,width=1280,height=720,framerate=15/1 \
  ! jpegdec ! videoconvert ! video/x-raw,format=I420 \
  ! v4l2h264enc extra-controls="controls,video_bitrate=2000000,h264_i_frame_period=15,repeat_sequence_header=1" \
  ! video/x-h264,level=4 \
  ! h264parse config-interval=1 \
  ! rtspclientsink location=rtsp://192.168.0.9:8554/pinky_1 protocols=tcp
```

### Step 2-C — software H.264 송신

```bash
gst-launch-1.0 -v \
  v4l2src device=DEVICE_PATH \
  ! image/jpeg,width=1280,height=720,framerate=15/1 \
  ! jpegdec ! videoconvert ! video/x-raw,format=I420 \
  ! queue leaky=downstream max-size-buffers=3 \
  ! x264enc tune=zerolatency speed-preset=veryfast bitrate=2000 key-int-max=15 bframes=0 \
  ! video/x-h264,profile=baseline \
  ! h264parse config-interval=1 \
  ! rtspclientsink location=rtsp://192.168.0.9:8554/pinky_1 protocols=tcp
```

MJPG가 없고 YUYV만 있으면 source caps와 변환 구간을 실제 `--list-formats-ext` 결과에 맞춘다. 추측으로 pipeline을 고정하지 않는다.

### Step 3 — RTX 4060에서 수신 검증

MediaMTX가 먼저 실행 중이어야 한다. 1호기 예시는 다음과 같다.

```bash
ffprobe -rtsp_transport tcp rtsp://192.168.0.9:8554/pinky_1
ffmpeg -rtsp_transport tcp -i rtsp://192.168.0.9:8554/pinky_1 -t 60 -f null -
```

화면 확인이 필요하면 `ffplay -rtsp_transport tcp ...`를 사용하되 검증 근거는 `ffprobe/ffmpeg`의 codec, resolution, FPS, decode error와 timestamp로 남긴다.

### Step 4 — Pinky 부하와 Wi-Fi 확인

```bash
pgrep -af gst-launch-1.0
pidstat -p PID 1 30
iw dev wlan0 get power_save
nmcli -g 802-11-wireless.powersave connection show trihouse
```

software encoding 부하가 높으면 FPS 15→10, 해상도 1280x720→960x540 순으로 내린다. 주행 제어 주기와 Nav2 안정성이 화질보다 우선이다. Wi-Fi power save는 운영 연결에서 비활성화한다.

### Step 5 — 결과 기록 양식

```text
robot_id:
board_model:
device_by_id:
input_format/resolution/fps:
encoder:
RTSP URI:
observed fps/bitrate:
Pinky CPU usage:
60-second decode errors:
10-minute disconnects/frame drop:
selected profile:
```

이 결과를 확보하기 전에는 systemd나 ROS 2 node의 pipeline 문자열을 확정하지 않는다.

## 계획된 StreamHealth 판정

- `DEGRADED`: 1초 이상 새 frame 없음 또는 FPS가 목표의 50% 미만
- `DISCONNECTED`: 3초 이상 새 frame 없음, publish session 종료 또는 USB 제거
- `RECOVERING`: 제한된 backoff로 재접속 중
- `HEALTHY`: 5초 연속 목표 FPS의 90% 이상이며 timestamp가 단조 증가

재연결만으로 영상 의존 작업을 자동 재개하지 않는다. 새 frame/marker와 새 authorization을 확인한 뒤 fleet이 재개를 결정한다.
