import pytest

from trihouse_pinky_vision.command_builder import (
    build_ffmpeg_command,
    build_rpicam_command,
    StreamConfig,
)


def test_builds_verified_cam_pk_01_commands_without_file_outputs():
    config = StreamConfig()

    assert build_rpicam_command(config) == [
        '/usr/local/bin/rpicam-vid',
        '--camera', '0',
        '--hflip', '--vflip',
        '-n', '-t', '0',
        '--width', '1280', '--height', '720', '--framerate', '15',
        '--codec', 'libav',
        '--libav-video-codec', 'libx264',
        '--libav-video-codec-opts',
        'preset=veryfast;profile=baseline;tune=zerolatency',
        '--libav-format', 'mpegts',
        '--bitrate', '2000000', '--intra', '15',
        '--inline', '--flush', '-o', '-',
    ]
    assert build_ffmpeg_command(config) == [
        '/usr/bin/ffmpeg', '-hide_banner', '-loglevel', 'info',
        '-progress', 'pipe:2', '-stats_period', '1',
        '-f', 'mpegts', '-i', 'pipe:0', '-map', '0:v:0',
        '-c:v', 'copy', '-f', 'rtsp', '-rtsp_transport', 'tcp',
        '-rw_timeout', '5000000',
        'rtsp://192.168.0.9:8554/pinky/CAM-PK-01',
    ]


def test_publisher_carries_a_socket_timeout_above_the_disconnect_threshold():
    """소켓 쓰기에 5초 backstop 을 둔다.

    타임아웃이 없으면 FFmpeg 는 반쯤 닫힌 TCP 연결에 쓰다가 무한히 멈출 수
    있다. 건강 상태 기계가 3.0초에 이미 disconnected 를 감지하므로 값은 그보다
    위여야 한다 — 아래로 내리면 FFmpeg 가 먼저 죽어서 감지 순서가 뒤집히고,
    Wi-Fi 절전이 아직 켜져 있는 상태에서 재시작이 과격해진다. 이 값의 역할은
    감지가 아니라, 멈춘 발행자가 SIGINT→SIGTERM→SIGKILL 단계를 기다리지 않고
    스스로 빠져나오게 하는 것이다.
    """
    config = StreamConfig()

    command = build_ffmpeg_command(config)

    assert command[command.index('-rw_timeout') + 1] == '5000000'
    # 출력 옵션이므로 출력 URL 앞에 와야 한다. 뒤에 오면 무시된다.
    assert command.index('-rw_timeout') < command.index(config.publish_uri)
    # 5초는 disconnected_after_sec(3.0)보다 위여야 한다.
    assert int(command[command.index('-rw_timeout') + 1]) / 1_000_000 > 3.0


@pytest.mark.parametrize(
    ('changes', 'message'),
    [
        ({'width': 0}, 'width'),
        ({'height': -1}, 'height'),
        ({'fps': 0.0}, 'fps'),
        ({'bitrate_kbps': -1}, 'bitrate_kbps'),
        ({'keyframe_interval': 0}, 'keyframe_interval'),
        ({'camera_id': 'pinky/CAM-PK-01'}, 'camera_id'),
        ({'publish_uri': 'http://192.168.0.9/pinky/CAM-PK-01'}, 'rtsp'),
        ({'publish_uri': 'rtsp:///pinky/CAM-PK-01'}, 'host'),
        # 역할 접두사만 맞고 마지막 segment 가 다른 경우. 두 segment 규약에서
        # 가장 저지르기 쉬운 오타이므로 명시적으로 막는다.
        ({'publish_uri': 'rtsp://192.168.0.9:8554/pinky/CAM-PK-02'}, 'camera_id'),
    ],
)
def test_rejects_invalid_stream_configuration(changes, message):
    with pytest.raises(ValueError, match=message):
        StreamConfig(**changes)


def test_omits_flip_flags_when_camera_is_upright():
    config = StreamConfig(hflip=False, vflip=False)

    command = build_rpicam_command(config)

    assert '--hflip' not in command
    assert '--vflip' not in command
