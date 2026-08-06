# Pinky Vision RTSP Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build ROS 2 Jazzy packages that publish the verified Pinky OV5647 camera stream to MediaMTX over H.264/RTSP/TCP and report deterministic `StreamHealth` with bounded recovery.

**Architecture:** `trihouse_interfaces` defines the shared health message. A Python `trihouse_pinky_vision` node validates a typed profile, supervises the verified `rpicam-vid | ffmpeg` process pair, converts progress samples into a pure state machine, and publishes health at 1 Hz. Hardware-free tests inject fixture executables; on-site tests use the real Pinky and RTX 4060.

**Tech Stack:** ROS 2 Jazzy, `ament_cmake`, `rosidl`, `ament_python`, Python 3.12, `rclpy`, `pytest`, `launch_testing`, `rpicam-vid`, FFmpeg, MediaMTX.

## Global Constraints

- Do not modify `pinky_pro`.
- Do not publish video, images, H.264 fragments, or base64 payloads through ROS 2.
- Do not create local video/image files on Pinky, including during failure handling.
- Preserve the verified profile: camera 0, 1280x720, 15 FPS, 2,000 kbps, IDR 15, `libx264`, `veryfast`, `baseline`, zero latency, `hflip=true`, `vflip=true`.
- Publish to `rtsp://192.168.0.9:8554/pinky_1` over TCP by default.
- Do not alter Wi-Fi, NetworkManager, firewall, or sudo-managed settings from the ROS node.
- Use argument arrays with `subprocess.Popen`; never use `shell=True`.
- Use test-first development and verify every failing test before implementation.

---

### Task 1: Build the shared `StreamHealth` interface

**Files:**
- Create: `trihouse_interfaces/package.xml`
- Create: `trihouse_interfaces/CMakeLists.txt`
- Create: `trihouse_interfaces/msg/StreamHealth.msg`
- Create: `trihouse_interfaces/test/test_stream_health_interface.py`
- Modify: `trihouse_interfaces/README.md`

**Interfaces:**
- Produces: `trihouse_interfaces/msg/StreamHealth` with state constants, camera identity, FPS, bitrate, last-frame time, detail, and publication time.

- [ ] Write a failing interface test that imports `StreamHealth`, verifies all five constants, assigns every field, and round-trips values through the generated Python type.
- [ ] Run `colcon build --packages-select trihouse_interfaces` and the test before files exist; record the expected package/import failure.
- [ ] Add the exact message contract from the design:

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

- [ ] Add `rosidl_generate_interfaces`, `builtin_interfaces`, runtime export, and interface package group metadata.
- [ ] Build, source `install/setup.bash`, and run the interface test; require PASS.
- [ ] Update the README status from documentation-only to partial implementation with only `StreamHealth` implemented.
- [ ] Commit as `feat: add stream health ROS interface`.

### Task 2: Implement typed profile validation and exact command generation

**Files:**
- Create: `trihouse_pinky/trihouse_pinky_vision/trihouse_pinky_vision/__init__.py`
- Create: `trihouse_pinky/trihouse_pinky_vision/trihouse_pinky_vision/command_builder.py`
- Create: `trihouse_pinky/trihouse_pinky_vision/test/test_command_builder.py`

**Interfaces:**
- Produces: immutable `StreamConfig`, `build_rpicam_command(config) -> list[str]`, `build_ffmpeg_command(config) -> list[str]`.
- Consumes later: node parameters and process supervisor argv arrays.

- [ ] Write failing tests for the verified defaults and literal argv values, including `--hflip`, `--vflip`, MPEG-TS stdout, FFmpeg stdin, `-c:v copy`, RTSP TCP, and `/pinky_1`.
- [ ] Write failing parameterized tests for zero/negative dimensions, FPS, bitrate, keyframe interval, slash-containing camera ID, non-RTSP URI, and URI path mismatch.
- [ ] Run `pytest -q .../test_command_builder.py`; verify collection fails because `command_builder` is absent.
- [ ] Implement frozen `StreamConfig` validation and the two pure command builders without shell syntax or file paths.
- [ ] Run the focused tests and require PASS.
- [ ] Commit as `feat: build verified Pinky streaming commands`.

### Task 3: Implement metrics and deterministic health state transitions

**Files:**
- Create: `trihouse_pinky/trihouse_pinky_vision/trihouse_pinky_vision/process_metrics.py`
- Create: `trihouse_pinky/trihouse_pinky_vision/trihouse_pinky_vision/stream_health.py`
- Create: `trihouse_pinky/trihouse_pinky_vision/test/test_process_metrics.py`
- Create: `trihouse_pinky/trihouse_pinky_vision/test/test_stream_health.py`

**Interfaces:**
- Produces: `ProgressSample`, `FfmpegProgressParser.feed(line)`, `EncodedBitrateSampler.sample(total_bytes, now)`, `HealthStateMachine.update(sample, processes_alive, now)`.
- Health result fields: state enum, FPS, bitrate, last-frame monotonic time, reason token.

- [ ] Write failing parser tests using literal FFmpeg progress records and malformed/log lines.
- [ ] Write failing bitrate tests for byte deltas, zero elapsed time, and unavailable samples.
- [ ] Write failing state tests for startup recovering, healthy after five good seconds, degraded after one second, disconnected after three seconds/child exit, repeated frame rejection, and recovery gating.
- [ ] Run both focused test files; verify missing-module failures.
- [ ] Implement the parser, bitrate sampler, and state machine with an injected monotonic time and no ROS dependency.
- [ ] Run the focused tests and require PASS.
- [ ] Commit as `feat: monitor Pinky stream health`.

### Task 4: Implement bounded subprocess supervision

**Files:**
- Create: `trihouse_pinky/trihouse_pinky_vision/trihouse_pinky_vision/process_supervisor.py`
- Create: `trihouse_pinky/trihouse_pinky_vision/test/fixtures/fake_camera.py`
- Create: `trihouse_pinky/trihouse_pinky_vision/test/fixtures/fake_publisher.py`
- Create: `trihouse_pinky/trihouse_pinky_vision/test/test_process_supervisor.py`

**Interfaces:**
- Produces: `ProcessSupervisor.start()`, `poll()`, `restart_due(now)`, `restart(now)`, and `stop()`; `SupervisorSnapshot` exposes liveness, latest progress, byte count, exit reason, and restart delay.
- Consumes: argv arrays from Task 2 and progress parser from Task 3.

- [ ] Write failing integration tests with real fixture subprocesses for data forwarding, progress collection, child exit detection, and no orphan after shutdown.
- [ ] Write failing fake-clock tests for delays `1,2,4,8,16,30,30` and reset after 30 healthy seconds.
- [ ] Run the focused test; verify the supervisor import fails.
- [ ] Implement direct OS-pipe connection, reader threads with bounded diagnostic queues, bounded backoff, and SIGINT → SIGTERM → SIGKILL cleanup.
- [ ] Run the supervisor and all pure-Python tests; require PASS and no remaining fixture processes.
- [ ] Commit as `feat: supervise Pinky camera publisher`.

### Task 5: Package the ROS node, launch profile, and launch test

**Files:**
- Create: `trihouse_pinky/trihouse_pinky_vision/package.xml`
- Create: `trihouse_pinky/trihouse_pinky_vision/setup.py`
- Create: `trihouse_pinky/trihouse_pinky_vision/setup.cfg`
- Create: `trihouse_pinky/trihouse_pinky_vision/resource/trihouse_pinky_vision`
- Create: `trihouse_pinky/trihouse_pinky_vision/trihouse_pinky_vision/camera_streamer_node.py`
- Create: `trihouse_pinky/trihouse_pinky_vision/launch/vision.launch.py`
- Create: `trihouse_pinky/trihouse_pinky_vision/config/pinky_1.yaml`
- Create: `trihouse_pinky/trihouse_pinky_vision/test/test_camera_streamer_node.py`
- Create: `trihouse_pinky/trihouse_pinky_vision/test/test_vision_launch.py`

**Interfaces:**
- Produces: executable `camera_streamer`, launch file `vision.launch.py`, topic `/trihouse/vision/stream_health` with reliable/volatile/keep-last-10 QoS.
- Consumes: `StreamHealth`, `StreamConfig`, supervisor snapshots, and state results.

- [ ] Write failing node tests with an injected supervisor factory, checking 1 Hz message values, invalid-profile startup refusal, and shutdown cleanup.
- [ ] Write a failing launch test that substitutes fixture executables and observes `RECOVERING -> HEALTHY` without camera hardware.
- [ ] Run focused tests; verify missing node/package failures.
- [ ] Implement package metadata, parameter declarations, timer-driven supervision, ROS time conversion, QoS, signal-safe destruction, YAML defaults, and launch arguments.
- [ ] Build both packages and run all package tests; require PASS.
- [ ] Commit as `feat: add Pinky vision ROS streaming node`.

### Task 6: Add operator verification and synchronize documentation

**Files:**
- Create: `trihouse_pinky/trihouse_pinky_vision/scripts/verify_rtsp.sh`
- Modify: `trihouse_pinky/trihouse_pinky_vision/README.md`
- Modify: `trihouse_pinky/doc/implementation-order.md`
- Modify: `docs/setup/2026-08-06-pinky-vision-streaming-design.md`

**Interfaces:**
- Produces: executable verification script accepting URI and duration, with ffprobe inspection and FFmpeg `-xerror` decode to the null muxer.

- [ ] Write a failing shell behavior test using fixture `ffprobe`/`ffmpeg` executables to prove URI/duration forwarding, nonzero propagation, and absence of media files.
- [ ] Run the shell test and verify failure because the script is absent.
- [ ] Implement `verify_rtsp.sh` with strict shell options, URI validation, bounded duration, and no file output.
- [ ] Update docs to replace the speculative GStreamer-only path with the verified Pi 5 `rpicam-vid + libx264 + FFmpeg` path, measured values, home tests, and on-site acceptance commands.
- [ ] Run shell tests, Python tests, `colcon build`, `colcon test`, `colcon test-result --verbose`, and `git diff --check`.
- [ ] Commit as `docs: add Pinky vision deployment verification`.

### Task 7: Final review and GitHub publication

**Files:**
- Review all files changed since `4c644a21`.

- [ ] Run fresh complete build and test verification from a clean `build/`, `install/`, and `log/` output location under `/tmp`.
- [ ] Request independent code review against the design and this plan; fix all Critical and Important findings with regression tests.
- [ ] Re-run the complete verification and inspect `git status`, staged diff, and commit history.
- [ ] Push `feat/pinky-edge-agent` to `origin` without force and confirm the remote SHA equals local HEAD.

