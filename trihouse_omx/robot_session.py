"""OMX follower 팔·카메라를 프로세스 수명 동안 한 번만 connect/disconnect한다.

deliver.py/store.py는 이 모듈로 로봇을 한 번 연결한 뒤, 물품이 바뀔 때마다
policy_runtime의 정책만 교체해서 재사용한다. 재연결 비용(포트 오픈, 캘리브레이션
로드, 카메라 워밍업)을 주문마다 반복하지 않는 것이 1단계 벤치마크의 대조군이다.

실행 전 준비:
    source ~/venv/il/bin/activate
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
from lerobot.robots.omx_follower import OmxFollower, OmxFollowerConfig

# 이 PC에 이미 있는 calibration 파일(~/.cache/huggingface/lerobot/calibration/
# robots/omx_follower/omx_follower_arm.json)의 id와 일치해야 factory 기본값
# 대신 그 캘리브레이션을 그대로 불러온다.
DEFAULT_ROBOT_ID = "omx_follower_arm"


@dataclass(frozen=True)
class CameraSpec:
    """카메라 하나의 연결 정보. index_or_path는 실행 시점에 v4l2-ctl로 재확인한 값을 넣는다.

    기본 해상도 640x480·fps 30은 카메라 최대 스펙(1280x720)이 아니라, 지금
    학습된 체크포인트들의 실제 녹화 설정에 맞춘 값이다 — 추론 입력이 학습
    시점 설정과 다르면 카메라가 그 값을 거부할 수도 있고(실측: 1280 요청 시
    RuntimeError, fps=15 요청 시 실제 22.0으로 밀려 RuntimeError), 설령 열려도
    정책이 기대하는 입력과 어긋날 수 있다. lerobot의 OpenCVCamera._validate_fps는
    요청값과 실측값이 정확히 일치해야 통과한다(tolerance 없음) — 카메라가 지원하는
    고정 fps만 넣을 수 있다.
    """

    name: str
    index_or_path: str | int
    width: int = 640
    height: int = 480
    fps: int = 30
    fourcc: str | None = "MJPG"


def _normalize_index_or_path(value: str | int) -> int | Path:
    """CLI에서 오는 문자열을 OpenCVCameraConfig가 기대하는 int/Path로 바꾼다.

    OpenCVCameraConfig.index_or_path는 int | Path다. 순수 문자열("4")을 그대로
    넘기면 cv2.VideoCapture가 그걸 정수 인덱스가 아니라 현재 폴더의 "4"라는
    파일 경로로 해석해 ConnectionError가 난다. 숫자만 있으면 int로, 아니면
    (예: "/dev/video4") Path로 변환한다.

    Ubuntu에서는 OpenCV 정수 인덱스가 /dev/videoN과 항상 1:1로 대응하지
    않을 수 있다(camera_opencv.py 주석 참고) — 이 PC에서 확인된 값은
    /dev/video4(front)·/dev/video6(wrist) 전체 경로이므로, 숫자만 주는 것보다
    "/dev/videoN" 전체 경로를 쓰는 쪽을 권장한다.
    """
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return Path(text)


def build_robot(
    *,
    port: str,
    cameras: tuple[CameraSpec, ...],
    robot_id: str = DEFAULT_ROBOT_ID,
) -> OmxFollower:
    """OmxFollower 인스턴스를 만든다. 아직 connect()는 하지 않는다."""
    camera_configs = {
        cam.name: OpenCVCameraConfig(
            index_or_path=_normalize_index_or_path(cam.index_or_path),
            width=cam.width,
            height=cam.height,
            fps=cam.fps,
            fourcc=cam.fourcc,
        )
        for cam in cameras
    }
    config = OmxFollowerConfig(port=port, id=robot_id, cameras=camera_configs)
    return OmxFollower(config)


@dataclass
class RobotSession:
    """이 프로세스가 소유하는 단 한 번의 connect()/disconnect() 쌍.

    with 블록을 벗어나면 무조건 disconnect를 시도한다 — 예외로 중간에 빠져나가도
    토크가 걸린 채로 프로세스가 죽는 것보다 낫다(OmxFollowerConfig의
    disable_torque_on_disconnect 기본값이 이를 보장).
    """

    robot: OmxFollower
    calibrate: bool = True
    _connected: bool = field(default=False, init=False, repr=False)

    def __enter__(self) -> OmxFollower:
        self.robot.connect(calibrate=self.calibrate)
        self._connected = True
        return self.robot

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._connected and self.robot.is_connected:
            self.robot.disconnect()
        self._connected = False
