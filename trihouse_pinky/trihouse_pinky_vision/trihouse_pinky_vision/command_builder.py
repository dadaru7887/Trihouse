"""Validated configuration and argv construction for the camera pipeline."""

from dataclasses import dataclass
import re
from urllib.parse import urlparse


_CAMERA_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]+$')


@dataclass(frozen=True)
class StreamConfig:
    # 기본값은 PK_01 의 등록 값이다. 경로는 `<역할 접두사>/<camera_id>` 이고,
    # 아래 `__post_init__` 이 마지막 segment 와 `camera_id` 의 일치를 강제하므로
    # 둘 중 하나만 고치면 노드가 부팅에 실패한다.
    camera_id: str = 'CAM-PK-01'
    camera_index: int = 0
    publish_uri: str = 'rtsp://192.168.0.9:8554/pinky/CAM-PK-01'
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


# 소켓 읽기/쓰기 타임아웃(마이크로초). 5초.
#
# 타임아웃이 없으면 FFmpeg 는 반쯤 닫힌 TCP 연결에 쓰다가 무한히 멈출 수 있다.
# 건강 상태 기계가 `disconnected_after_sec: 3.0` 에서 이미 그 상태를 감지하므로
# 이 값은 3초보다 위여야 한다. 아래로 내리면 FFmpeg 가 감지보다 먼저 죽어서
# 기존 감지 순서가 뒤집히고, 2026-08-06 spike 에 기록된 대로 Wi-Fi 절전이 아직
# `on` 인 동안에는 재시작이 필요 이상으로 과격해진다.
#
# 즉 이 값의 역할은 고장을 감지하는 것이 아니라, 이미 감지된 뒤에 멈춰 있는
# 발행자가 `ProcessSupervisor.stop()` 의 SIGINT(3초)→SIGTERM(2초)→SIGKILL
# 단계를 기다리지 않고 스스로 빠져나오게 하는 것이다.
_SOCKET_TIMEOUT_MICROSECONDS = '5000000'


def build_ffmpeg_command(config: StreamConfig) -> list[str]:
    return [
        config.ffmpeg_executable,
        '-hide_banner', '-loglevel', 'info',
        '-progress', 'pipe:2', '-stats_period', '1',
        '-f', 'mpegts', '-i', 'pipe:0',
        '-map', '0:v:0', '-c:v', 'copy',
        '-f', 'rtsp', '-rtsp_transport', config.transport,
        # 출력 옵션이므로 출력 URL 앞에 와야 한다. 뒤에 두면 조용히 무시된다.
        '-rw_timeout', _SOCKET_TIMEOUT_MICROSECONDS,
        config.publish_uri,
    ]
