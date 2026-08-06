import pytest

from trihouse_pinky_vision.command_builder import (
    StreamConfig,
    build_ffmpeg_command,
    build_rpicam_command,
)


def test_builds_verified_pinky_1_commands_without_file_outputs():
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
        'rtsp://192.168.0.9:8554/pinky_1',
    ]


@pytest.mark.parametrize(
    ('changes', 'message'),
    [
        ({'width': 0}, 'width'),
        ({'height': -1}, 'height'),
        ({'fps': 0.0}, 'fps'),
        ({'bitrate_kbps': -1}, 'bitrate_kbps'),
        ({'keyframe_interval': 0}, 'keyframe_interval'),
        ({'camera_id': 'pinky/1'}, 'camera_id'),
        ({'publish_uri': 'http://192.168.0.9/pinky_1'}, 'rtsp'),
        ({'publish_uri': 'rtsp:///pinky_1'}, 'host'),
        ({'publish_uri': 'rtsp://192.168.0.9:8554/pinky_2'}, 'camera_id'),
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
