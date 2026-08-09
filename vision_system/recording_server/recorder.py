"""H.264 60초 분할 녹화의 설정과 프로세스 생명주기.

배포 프로세스는 :func:`build_ffmpeg_segment_command`가 만든 argv만 실행한다.
이 모듈은 파일을 직접 삭제하지 않는다. 보존 정책이 안전하다고 판정한 segment ID만
반환하고, 저장소 worker가 그 ID에 해당하는 파일을 삭제한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
import subprocess
from typing import Callable, Protocol
from urllib.parse import urlparse

from .catalog import RecordingCatalog, RecordingSegment


_CAMERA_ID = re.compile(r'^[A-Za-z0-9_-]+$')


class RecorderState(StrEnum):
    STOPPED = 'STOPPED'
    RECORDING = 'RECORDING'
    DISCONNECTED = 'DISCONNECTED'


@dataclass(frozen=True)
class RecorderConfig:
    camera_id: str
    input_uri: str
    output_root: str
    ffmpeg_executable: str = 'ffmpeg'
    segment_duration_s: int = RecordingCatalog.SEGMENT_DURATION_S

    def __post_init__(self) -> None:
        if not _CAMERA_ID.fullmatch(self.camera_id):
            raise ValueError('camera_id may contain only letters, numbers, underscore, or dash')
        input_url = urlparse(self.input_uri)
        if input_url.scheme != 'rtsp' or not input_url.hostname:
            raise ValueError('input_uri must be an RTSP URI with a host')
        if not self.output_root or self.segment_duration_s != RecordingCatalog.SEGMENT_DURATION_S:
            raise ValueError('output_root is required and segments must be exactly 60 seconds')
        if not self.ffmpeg_executable:
            raise ValueError('ffmpeg_executable is required')


def build_ffmpeg_segment_command(config: RecorderConfig) -> list[str]:
    """RTSP 영상을 재인코딩하지 않고 60초 H.264 파일로 나누는 FFmpeg argv를 만든다."""
    output_pattern = f'{config.output_root.rstrip("/")}/{config.camera_id}/%Y%m%dT%H%M%S.h264'
    return [
        config.ffmpeg_executable,
        '-nostdin',
        '-rtsp_transport', 'tcp',
        '-i', config.input_uri,
        '-map', '0:v:0',
        '-c:v', 'copy',
        '-f', 'segment',
        '-segment_time', str(config.segment_duration_s),
        '-reset_timestamps', '1',
        '-strftime', '1',
        output_pattern,
    ]


class RecordingSession:
    """녹화 프로세스 callback과 보존 카탈로그를 연결한다.

    ``segment_opened``는 파일 생성 직후, ``segment_finished``는 파일 close 직후 호출한다.
    진행 중 파일은 카탈로그가 절대 삭제 후보로 반환하지 않는다.
    """

    def __init__(self, *, capacity_bytes: int, output_root: str) -> None:
        self.catalog = RecordingCatalog(capacity_bytes=capacity_bytes, recording_root=output_root)
        self.state = RecorderState.STOPPED
        self.last_error = ''

    def process_started(self) -> None:
        self.state = RecorderState.RECORDING
        self.last_error = ''

    def process_exited(self, detail: str) -> None:
        self.state = RecorderState.DISCONNECTED
        self.last_error = detail or 'recorder process exited'

    def segment_opened(self, *, camera_id: str, minute_start_s: int, size_bytes: int) -> RecordingSegment:
        if self.state is not RecorderState.RECORDING:
            raise RuntimeError('recorder process is not running')
        return self.catalog.start_segment(camera_id, minute_start_s, size_bytes)

    def segment_finished(self, segment_id: str) -> tuple[str, ...]:
        self.catalog.complete(segment_id)
        return self.catalog.enforce_retention()


class _RecorderProcess(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def wait(self, timeout: float) -> int: ...


def _spawn_ffmpeg(argv: list[str]) -> _RecorderProcess:
    """shell 없이 FFmpeg를 시작한다. stdout은 녹화 서버 계약에 포함하지 않는다."""
    return subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


class FfmpegRecorderRunner:
    """검증된 녹화 argv를 실제 process로 실행하는 작은 경계다.

    file watcher 또는 FFmpeg segment callback은 파일 생성/종료 시 ``session``의
    ``segment_opened``/``segment_finished``를 호출해야 한다. 이 runner는 녹화 process의
    시작·종료만 담당하며, UI 재생 여부나 파일 삭제를 결정하지 않는다.
    """

    def __init__(
        self,
        config: RecorderConfig,
        *,
        session: RecordingSession,
        popen: Callable[[list[str]], _RecorderProcess] = _spawn_ffmpeg,
    ) -> None:
        self._config = config
        self.session = session
        self._popen = popen
        self._process: _RecorderProcess | None = None

    def start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            raise RuntimeError('recorder is already running')
        self._process = self._popen(build_ffmpeg_segment_command(self._config))
        self.session.process_started()

    def poll(self) -> RecorderState:
        if self._process is None:
            return self.session.state
        returncode = self._process.poll()
        if returncode is not None and self.session.state is RecorderState.RECORDING:
            self.session.process_exited(f'ffmpeg exited with {returncode}')
        return self.session.state

    def stop(self, *, timeout_s: float = 5.0) -> None:
        if timeout_s <= 0:
            raise ValueError('timeout_s must be positive')
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            self._process.wait(timeout=timeout_s)
        self._process = None
        self.session.state = RecorderState.STOPPED
