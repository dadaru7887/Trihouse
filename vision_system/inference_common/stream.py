"""PC2 추론용 RTSP 입력을 최신 raw frame 흐름으로 변환하는 계약."""

from dataclasses import dataclass
import os
import re
from typing import Mapping
from urllib.parse import urlparse


_CAMERA_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')


@dataclass(frozen=True)
class InferenceStreamConfig:
    input_uri: str
    camera_id: str
    width: int = 1280
    height: int = 720
    inference_fps: int = 15
    ffmpeg_executable: str = 'ffmpeg'

    def __post_init__(self) -> None:
        parsed = urlparse(self.input_uri)
        if parsed.scheme != 'rtsp' or not parsed.hostname or not parsed.path.strip('/'):
            raise ValueError('input_uri must be an RTSP stream URI')
        if not _CAMERA_ID.fullmatch(self.camera_id):
            raise ValueError('camera_id must be a safe identifier')
        if self.width <= 0 or self.height <= 0 or self.inference_fps <= 0:
            raise ValueError('frame dimensions and inference_fps must be positive')
        if not self.ffmpeg_executable:
            raise ValueError('ffmpeg_executable is required')

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> 'InferenceStreamConfig':
        values = os.environ if env is None else env
        input_uri = values.get('VISION_RTSP_URL', '').strip()
        if not input_uri:
            raise ValueError('VISION_RTSP_URL is required')
        return cls(
            input_uri=input_uri,
            camera_id=values.get('VISION_CAMERA_ID', 'front').strip(),
            width=_positive_int(values.get('VISION_FRAME_WIDTH', '1280'), 'VISION_FRAME_WIDTH'),
            height=_positive_int(values.get('VISION_FRAME_HEIGHT', '720'), 'VISION_FRAME_HEIGHT'),
            inference_fps=_positive_int(values.get('VISION_INFERENCE_FPS', '15'), 'VISION_INFERENCE_FPS'),
            ffmpeg_executable=values.get('VISION_FFMPEG_EXECUTABLE', 'ffmpeg').strip(),
        )

    @property
    def frame_size_bytes(self) -> int:
        return self.width * self.height * 3


def _positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f'{name} must be a positive integer') from error
    if parsed <= 0:
        raise ValueError(f'{name} must be a positive integer')
    return parsed


def build_ffmpeg_frame_command(config: InferenceStreamConfig) -> list[str]:
    """RTSP를 낮은 버퍼의 고정 크기 BGR frame stdout으로 변환한다.

    소비자는 반드시 ``frame_size_bytes`` 단위로 읽고, 모델이 느리면 과거 frame을
    처리하기보다 decoder를 재동기화하거나 별도 latest-frame slot을 사용해야 한다.
    """
    return [
        config.ffmpeg_executable,
        '-nostdin',
        '-hide_banner',
        '-loglevel', 'warning',
        '-rtsp_transport', 'tcp',
        '-fflags', 'nobuffer',
        '-flags', 'low_delay',
        '-probesize', '32',
        '-analyzeduration', '0',
        '-i', config.input_uri,
        '-map', '0:v:0',
        '-an',
        '-vf', f'fps={config.inference_fps},scale={config.width}:{config.height}',
        '-pix_fmt', 'bgr24',
        '-f', 'rawvideo',
        'pipe:1',
    ]
