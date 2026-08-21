"""PC2 추론용 RTSP 입력을 최신 raw frame 흐름으로 변환하는 계약."""

from dataclasses import dataclass
import os
import re
from typing import Mapping
from urllib.parse import urlparse


_CAMERA_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')


@dataclass(frozen=True)
class InferenceStreamConfig:
    """PC2 는 스트림 하나만 소비하고, 그 정체는 URL 에서 파생한다.

    `camera_id` 를 별도 환경변수로 받지 않는 이유는 그것이 중복 정보이기
    때문이다. 경로 규약이 `<역할>/<camera_id>` 로 정해진 뒤로 URL 은 이미
    논리 ID 를 싣고 있고, 같은 사실을 두 곳에서 받으면 둘이 어긋날 수 있다.
    `front` 와 `pinky_1` 이 갈라졌던 방식이 정확히 그것이었다.

    필드가 아니라 property 로 파생하는 것도 의도다. 필드로 두면 `from_env`
    바깥에서 만든 객체가 여전히 어긋난 값을 들 수 있다. 파생하면 어긋난 값을
    표현할 방법 자체가 없어진다. 이 규칙은 발행자 쪽 규칙(`publish_uri` 의
    마지막 segment 가 곧 `camera_id`)과 같은 규칙이다.
    """

    input_uri: str
    width: int = 1280
    height: int = 720
    inference_fps: int = 15
    ffmpeg_executable: str = 'ffmpeg'

    def __post_init__(self) -> None:
        parsed = urlparse(self.input_uri)
        if parsed.scheme != 'rtsp' or not parsed.hostname or not parsed.path.strip('/'):
            raise ValueError('input_uri must be an RTSP stream URI')
        if not _CAMERA_ID.fullmatch(_final_path_segment(self.input_uri)):
            raise ValueError(
                'input_uri path must end with a safe camera identifier, '
                'as in rtsp://<host>:8554/pinky/CAM-PK-01'
            )
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
            width=_positive_int(values.get('VISION_FRAME_WIDTH', '1280'), 'VISION_FRAME_WIDTH'),
            height=_positive_int(values.get('VISION_FRAME_HEIGHT', '720'), 'VISION_FRAME_HEIGHT'),
            inference_fps=_positive_int(values.get('VISION_INFERENCE_FPS', '15'), 'VISION_INFERENCE_FPS'),
            ffmpeg_executable=values.get('VISION_FFMPEG_EXECUTABLE', 'ffmpeg').strip(),
        )

    @property
    def camera_id(self) -> str:
        """스트림 경로의 마지막 segment. 발행자가 쓰는 논리 ID 와 같은 값이다."""
        return _final_path_segment(self.input_uri)

    @property
    def frame_size_bytes(self) -> int:
        return self.width * self.height * 3


def _final_path_segment(uri: str) -> str:
    # `urlparse` 를 거치므로 `viewer:pass@host` 형태의 자격 증명은 netloc 에
    # 남고 경로에는 섞이지 않는다. read 가 계정으로 막힌 뒤로 PC2 의 URL 은
    # 실제로 자격 증명을 달고 온다.
    return urlparse(uri).path.rstrip('/').rsplit('/', 1)[-1]


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
