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
    """`<role>/<camera_id>` 두 segment 경로. 세 segment 규약을 대체한다.

    `robot_id` 를 중간 segment 로 두던 규약을 버린 이유는 `StreamHealth.msg` 가
    `camera_id` 만 싣고 `robot_id` 는 싣지 않기 때문이다. 세 segment 아래에서는
    노드의 `camera_id` 가 `front` 같은 역할 이름이 되어 PK_01 과 PK_02 의 건강
    메시지를 구분할 수 없게 된다. `camera_id` 를 마지막 segment 로 두면 그 값이
    전역 유일해서 구분이 공짜로 따라온다.

    `role` 은 `config/cameras.yaml` 의 역할에 대응하는 경로 접두사(`pinky`,
    `omx`, `fixed`)다. MediaMTX 는 이 접두사 단위로 publish 권한을 나눈다.
    """

    role: str
    camera_id: str

    def __post_init__(self) -> None:
        for name, value in (('role', self.role), ('camera_id', self.camera_id)):
            if not _IDENTIFIER.fullmatch(value):
                raise ValueError(f'{name} must be a safe stream identifier')

    @property
    def path(self) -> str:
        return f'{self.role}/{self.camera_id}'

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
