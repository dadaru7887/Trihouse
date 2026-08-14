"""USB 카메라를 PC1 MediaMTX의 표준 RTSP 경로로 발행하는 명령 계약."""

from dataclasses import dataclass
from enum import StrEnum
import re
from urllib.parse import urlparse


_IDENTIFIER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')


class UsbVideoFormat(StrEnum):
    H264 = 'h264'
    MJPEG = 'mjpeg'
    YUYV422 = 'yuyv422'


class VideoEncoder(StrEnum):
    COPY = 'copy'
    NVENC = 'h264_nvenc'
    LIBX264 = 'libx264'


@dataclass(frozen=True)
class StreamIdentity:
    robot_id: str
    camera_id: str

    def __post_init__(self) -> None:
        for name, value in (('robot_id', self.robot_id), ('camera_id', self.camera_id)):
            if not _IDENTIFIER.fullmatch(value):
                raise ValueError(f'{name} must be a safe stream identifier')

    @property
    def path(self) -> str:
        return f'pinky/{self.robot_id}/{self.camera_id}'

    def publish_url(self, mediamtx_base_url: str) -> str:
        parsed = urlparse(mediamtx_base_url)
        if parsed.scheme != 'rtsp' or not parsed.hostname or parsed.path not in ('', '/'):
            raise ValueError('mediamtx_base_url must be an RTSP origin without a path')
        return f'{mediamtx_base_url.rstrip("/")}/{self.path}'


@dataclass(frozen=True)
class UsbIngressConfig:
    identity: StreamIdentity
    device: str
    mediamtx_base_url: str
    input_format: UsbVideoFormat = UsbVideoFormat.MJPEG
    encoder: VideoEncoder = VideoEncoder.NVENC
    width: int = 1280
    height: int = 720
    fps: int = 15
    bitrate_kbps: int = 3000
    ffmpeg_executable: str = 'ffmpeg'

    def __post_init__(self) -> None:
        if not self.device.startswith('/dev/video') or not self.device[10:].isdigit():
            raise ValueError('device must be a /dev/videoN path')
        self.identity.publish_url(self.mediamtx_base_url)
        if self.encoder is VideoEncoder.COPY and self.input_format is not UsbVideoFormat.H264:
            raise ValueError('stream copy requires an H.264 camera input')
        if self.width <= 0 or self.height <= 0 or self.fps <= 0 or self.bitrate_kbps <= 0:
            raise ValueError('video dimensions, fps, and bitrate must be positive')
        if not self.ffmpeg_executable:
            raise ValueError('ffmpeg_executable is required')


def build_usb_ingress_command(config: UsbIngressConfig) -> list[str]:
    """검증된 USB 입력을 MediaMTX로 발행하는 shell-free FFmpeg argv를 만든다."""
    command = [
        config.ffmpeg_executable,
        '-nostdin',
        '-hide_banner',
        '-loglevel', 'warning',
        '-f', 'v4l2',
        '-input_format', config.input_format.value,
        '-video_size', f'{config.width}x{config.height}',
        '-framerate', str(config.fps),
        '-i', config.device,
        '-map', '0:v:0',
        '-an',
        '-c:v', config.encoder.value,
    ]
    if config.encoder is not VideoEncoder.COPY:
        command.extend([
            '-pix_fmt', 'yuv420p',
            '-r', str(config.fps),
            '-g', str(config.fps),
            '-bf', '0',
            '-b:v', f'{config.bitrate_kbps}k',
        ])
        if config.encoder is VideoEncoder.NVENC:
            command.extend(['-preset', 'p1', '-tune', 'ull'])
        else:
            command.extend(['-preset', 'veryfast', '-tune', 'zerolatency'])
    command.extend([
        '-f', 'rtsp',
        '-rtsp_transport', 'tcp',
        config.identity.publish_url(config.mediamtx_base_url),
    ])
    return command
