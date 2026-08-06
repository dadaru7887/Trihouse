"""Validated configuration and argv construction for the camera pipeline."""

from dataclasses import dataclass
import re
from urllib.parse import urlparse


_CAMERA_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]+$')


@dataclass(frozen=True)
class StreamConfig:
    camera_id: str = 'pinky_1'
    camera_index: int = 0
    publish_uri: str = 'rtsp://192.168.0.9:8554/pinky_1'
    width: int = 1280
    height: int = 720
    fps: float = 15.0
    bitrate_kbps: int = 2000
    keyframe_interval: int = 15
    hflip: bool = True
    vflip: bool = True
    encoder: str = 'libx264'
    encoder_preset: str = 'veryfast'
    encoder_profile: str = 'baseline'
    transport: str = 'tcp'
    rpicam_executable: str = '/usr/local/bin/rpicam-vid'
    ffmpeg_executable: str = '/usr/bin/ffmpeg'

    def __post_init__(self) -> None:
        for name in ('width', 'height', 'fps', 'bitrate_kbps', 'keyframe_interval'):
            if getattr(self, name) <= 0:
                raise ValueError(f'{name} must be positive')
        if self.camera_index < 0:
            raise ValueError('camera_index must not be negative')
        if not _CAMERA_ID_PATTERN.fullmatch(self.camera_id):
            raise ValueError('camera_id must contain only letters, numbers, underscore, or dash')
        parsed = urlparse(self.publish_uri)
        if parsed.scheme != 'rtsp':
            raise ValueError('publish_uri must use the rtsp scheme')
        if not parsed.hostname:
            raise ValueError('publish_uri must contain a host')
        if parsed.path.rstrip('/').rsplit('/', 1)[-1] != self.camera_id:
            raise ValueError('publish_uri path must end with camera_id')
        if self.transport != 'tcp':
            raise ValueError('transport must be tcp')


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def build_rpicam_command(config: StreamConfig) -> list[str]:
    command = [
        config.rpicam_executable,
        '--camera', str(config.camera_index),
    ]
    if config.hflip:
        command.append('--hflip')
    if config.vflip:
        command.append('--vflip')
    command.extend([
        '-n', '-t', '0',
        '--width', str(config.width),
        '--height', str(config.height),
        '--framerate', _number(config.fps),
        '--codec', 'libav',
        '--libav-video-codec', config.encoder,
        '--libav-video-codec-opts',
        f'preset={config.encoder_preset};profile={config.encoder_profile};tune=zerolatency',
        '--libav-format', 'mpegts',
        '--bitrate', str(config.bitrate_kbps * 1000),
        '--intra', str(config.keyframe_interval),
        '--inline', '--flush', '-o', '-',
    ])
    return command


def build_ffmpeg_command(config: StreamConfig) -> list[str]:
    return [
        config.ffmpeg_executable,
        '-hide_banner', '-loglevel', 'info',
        '-progress', 'pipe:2', '-stats_period', '1',
        '-f', 'mpegts', '-i', 'pipe:0',
        '-map', '0:v:0', '-c:v', 'copy',
        '-f', 'rtsp', '-rtsp_transport', config.transport,
        config.publish_uri,
    ]
