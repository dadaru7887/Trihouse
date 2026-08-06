# Pinky Vision RTSP Streaming ROS 2 Design

## 1. Goal

Turn the camera path verified on 2026-08-06 into a ROS 2 package that can be
built and tested without robot hardware, then deployed to Pinky for hardware
acceptance testing. The package owns camera capture, H.264 publication,
process recovery, and `StreamHealth`; it does not carry video in ROS 2.

## 2. Scope

This design adds two buildable ROS 2 packages:

- `trihouse_interfaces`: the first concrete shared interface,
  `StreamHealth.msg`.
- `trihouse_pinky/trihouse_pinky_vision`: a Python ROS 2 package that manages
  the verified camera publisher pipeline and reports its health.

It also adds a server-side verification script and written hardware acceptance
procedure. MediaMTX remains a standalone service on the RTX 4060 server; it is
not embedded in the robot ROS graph.

The following are explicitly deferred:

- camera intrinsic/extrinsic calibration and TF publication;
- `MarkerObservation` and `PersonDetection` coordinate transforms;
- server inference and recording workers;
- systemd and the final `trihouse_pinky_bringup` integration;
- automatic changes to Wi-Fi, NetworkManager, firewall, or OS configuration.

## 3. Verified Baseline

The implementation must preserve the values measured in the successful
2026-08-06 spike.

| Item | Verified value |
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
| Acceptance observation | 8,997 frames in 599.93 seconds, 15 FPS, exit 0 |
| Pinky load | `rpicam-vid` 24.6% CPU / 1.2% MEM; FFmpeg 0.8% CPU / 0.6% MEM |
| Pinky temperature | 48.5 C after more than 48 minutes of publication |
| Wi-Fi finding | `wlan0` power save was on; operations plan requires off |

The three-frame difference from the nominal 9,000-frame count is not treated
as proven packet loss because the receiver starts on live-stream timestamps.
It is 0.033% of the nominal count and is below the one-percent acceptance
threshold.

## 4. Architecture Decision

The ROS node will supervise the exact `rpicam-vid -> FFmpeg -> MediaMTX` path
that passed the hardware spike.

```text
OV5647
  -> rpicam-vid (libav/libx264, MPEG-TS on stdout)
  -> FFmpeg (demux/copy, RTSP/TCP publisher)
  -> MediaMTX /pinky_1
  -> server readers and inference

FFmpeg progress + process status + encoded-byte samples
  -> StreamHealth state machine
  -> /trihouse/vision/stream_health at 1 Hz
```

This is preferred over replacing the verified path with a new GStreamer
camera pipeline. GStreamer remains an allowed future implementation detail,
but the first deployed package must minimize changes from the measured
hardware path.

The node must use `subprocess.Popen` with argument arrays. It must not build a
shell command or use `shell=True`. `rpicam-vid` stdout is connected directly
to FFmpeg stdin through an OS pipe. Neither command may contain a file sink.

## 5. Package and File Boundaries

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

Responsibilities:

- `command_builder.py` validates typed configuration and returns the two argv
  arrays. It is the only module that knows `rpicam-vid` and FFmpeg flags.
- `process_supervisor.py` starts, observes, stops, and restarts the process
  pair. It owns no ROS concepts and accepts a process factory for tests.
- `process_metrics.py` parses FFmpeg progress records and samples encoded
  bytes written by `rpicam-vid` on Linux. It returns measurements rather than
  assigning health states.
- `stream_health.py` is a deterministic state machine driven by measurements
  and an injected monotonic clock.
- `camera_streamer_node.py` declares ROS parameters, connects the modules,
  publishes health at 1 Hz, and guarantees cleanup during shutdown.
- `vision.launch.py` loads one robot profile and starts one streamer node.
- `verify_rtsp.sh` runs `ffprobe` and a bounded FFmpeg decode against the URI;
  it never records media.

## 6. `StreamHealth` Contract

`trihouse_interfaces/msg/StreamHealth.msg` will contain:

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

Semantics:

- `last_frame_stamp` is the ROS time when FFmpeg last reported a strictly
  increasing output frame count. It is not the camera sensor timestamp.
- `stamp` is message publication time.
- `fps` is calculated from frame-count deltas over a rolling window, not from
  the lifetime average printed by FFmpeg.
- `bitrate_kbps` is an observed encoded-stream estimate calculated from byte
  counter deltas. A value of `0.0` means measurement is unavailable and
  `detail` must say why.
- `detail` contains a stable reason token followed by optional diagnostic
  text, for example `no_progress`, `publisher_exit`, or `healthy`.

The topic is `/trihouse/vision/stream_health` with reliable, volatile,
keep-last-10 QoS. Video payloads, encoded fragments, and images are forbidden
on ROS topics.

## 7. Configuration Contract

The `pinky_1.yaml` profile fixes the verified defaults while leaving robot
identity and server address overrideable from launch:

| Parameter | Default |
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

Validation rejects non-positive geometry, FPS, bitrate, and keyframe values;
a camera ID containing `/`; a publish URI without the `rtsp` scheme; and a URI
whose final path component does not equal `camera_id`.

The node reports an invalid profile as a startup error and does not spawn a
child process.

## 8. Health and Recovery State Machine

The state machine uses monotonic time for intervals and ROS time only for
published timestamps.

- Startup enters `RECOVERING` before processes are launched.
- `HEALTHY` requires both children alive, monotonically increasing frame
  count, and at least 90% of target FPS for five consecutive seconds.
- `DEGRADED` is entered when no new frame is observed for at least one second,
  rolling FPS is below 50% of target, or FPS stays between 50% and 90% for ten
  seconds without reaching healthy.
- `DISCONNECTED` is entered when no new frame is observed for three seconds,
  either child exits, the inter-process pipe breaks, or RTSP publication
  fails.
- Restart changes the state to `RECOVERING`. Resumed frames do not immediately
  make the stream healthy; the five-second healthy gate applies again.

The restart delays are 1, 2, 4, 8, 16, then 30 seconds, capped at 30 seconds.
Thirty continuous healthy seconds reset the sequence to one second.

Stopping the ROS node is not a failure. On shutdown the supervisor sends
SIGINT, waits three seconds, sends SIGTERM, waits two seconds, and uses SIGKILL
only for a remaining child. It always reaps both processes.

The vision package reports health but does not resume a robot task. Fleet and
bringup will later use `StreamHealth` as a readiness input and require fresh
marker/authorization checks before resuming vision-dependent work.

## 9. Wi-Fi Policy

The operating profile requires `wlan0` power save to be off because the robot
continuously publishes video and values latency and stability over idle-radio
power savings. The ROS node must not call `iw`, modify NetworkManager, or
require sudo. The setting is checked and recorded by the operator during
hardware acceptance.

The deployment checklist contains the reversible commands, but applying them
is a separate operator action:

```bash
sudo iw dev wlan0 set power_save off
sudo nmcli connection modify trihouse 802-11-wireless.powersave 2
```

The current robot has not yet had this persistent setting applied. Battery
runtime with power save off must be measured in a later operational test.

## 10. Hardware-Free Test Design

Home development must not require Pinky, the OV5647, MediaMTX, or the RTX 4060.

Unit tests use an injected clock and process factory. Fixture programs mimic
the two child processes: the camera fixture emits bounded byte chunks; the
publisher fixture consumes stdin and emits FFmpeg-style progress records.

Automated coverage must include:

1. exact verified argv generation, including both flips and absence of file
   output;
2. rejection of invalid profile values and mismatched URI/camera ID;
3. startup to recovering to healthy after five good seconds;
4. degraded at one second without progress;
5. disconnected at three seconds or on either child exit;
6. restart delays and reset after 30 healthy seconds;
7. no repeated frame count accepted as a fresh frame;
8. child cleanup escalation and process reaping;
9. observed bitrate calculation and unavailable-measurement fallback;
10. ROS launch test that observes 1 Hz `StreamHealth` from fixture processes;
11. shutdown test proving that both fixture children exit;
12. source scan proving production commands contain no file output path.

`colcon test` must pass on ROS 2 Jazzy before the hardware visit.

## 11. Hardware Acceptance Test

The next on-site session follows this order:

1. Start MediaMTX v1.19.3 on `192.168.0.9` with RTSP TCP enabled.
2. Build and source `trihouse_interfaces` and `trihouse_pinky_vision` on Pinky.
3. Launch the `pinky_1.yaml` profile and confirm `RECOVERING -> HEALTHY`.
4. Confirm H.264 baseline, 1280x720, and 15 FPS with `ffprobe`.
5. Decode for 600 seconds with FFmpeg `-xerror`; require exit code zero,
   approximately 9,000 frames, and no corrupt-frame or decode errors.
6. Record Pinky CPU, memory, and temperature while Nav2 is also running.
7. Kill the publisher process and verify `DISCONNECTED`, bounded restart, and
   return through `RECOVERING` to `HEALTHY`.
8. Stop MediaMTX for more than three seconds, restart it, and verify the same
   recovery path.
9. Confirm no video or image files were created on Pinky.
10. Temporarily set Wi-Fi power save off, repeat the stability test, then make
    the setting persistent only after operator approval.

Do not unplug a CSI ribbon cable from a powered Raspberry Pi. Camera failure
is simulated by terminating the camera process unless the robot is fully
powered down for a physical disconnect test.

## 12. Acceptance Criteria

The first implementation is accepted when:

- both ROS 2 packages build on Jazzy and all hardware-free tests pass;
- one launch command publishes `pinky_1` without local media files;
- `StreamHealth` is published at 1 Hz with the specified state semantics;
- child exit and server outage cause bounded automatic recovery;
- the live stream maintains 1280x720 at 10-15 FPS for ten minutes;
- receiver decode exits zero with a frame-count shortfall below one percent as
  a stability proxy, while decoder logs contain no errors; this proxy is not
  reported as a direct packet-loss measurement;
- Pinky retains enough CPU and temperature margin while Nav2 is active;
- the implementation does not modify `pinky_pro` or publish video through
  ROS 2.
