"""2단계 — 사람 mask 에서 자세와 움직임을 **잰다**.

여기서 하는 것은 측정이지 판정이 아니다. "넘어졌다" 는 결론은 시간축을 보는
`fall_monitor.py` 가 내린다. 둘을 나눈 이유는 갈아 끼우기 위해서다 — 지금 자세는
mask bbox 의 가로/세로 비라는 **규칙**이지만, 언젠가 사람 crop 위의 자세 모델로
바뀐다. 그때 바뀌는 것은 이 파일뿐이어야 한다.

## 규칙의 한계 (2026-08-18~19 실측)

- `fall_aspect_ratio` 를 0.7 까지 내리면 `re_2` 에서 오탐이 났다. **0.9 밑으로
  내리지 않는다.**
- 비율이 임계값 밑이면 애초에 의심 단계에 들어가지도 못한다. 이 recall gap 은
  시간축 로직으로 못 고친다 — 2차 신호가 있어야 한다.
- 배경 물체를 사람으로 잡으면 이 측정은 그대로 속는다. `re_3` t=74 s 에서 벽에
  달린 금속 체인이 비율 3.54 로 잡혔고 confidence 로는 걸러지지 않았다
  (conf >= 0.25 였다).

그래서 이 값들은 **사람이 재확인할 근거**이지 최종 판정이 아니다.
"""

from dataclasses import dataclass
from math import hypot
from typing import Any


@dataclass(frozen=True)
class PostureConfig:
    """`configs/realtime.yaml` 의 `monitor` 절에서 온다."""

    # 이 비율 이상이면 누운 자세로 본다. 0.9 는 무낙상 영상 두 편에서 오탐 0 을
    # 확인한 하한이다. 낮출수록 recall 은 오르지만 0.7 에서 오탐이 확인됐다.
    fall_aspect_ratio: float = 0.9
    # 프레임 대각선으로 정규화한 centroid 이동량. 이 값 이하면 정지로 본다.
    # **아직 sweep 검증되지 않은 값이다** — `FALLEN` 상태에 들어가 본 영상이
    # 없어서 한 번도 실전에서 확인되지 않았다.
    motion_threshold: float = 0.015

    def __post_init__(self) -> None:
        if self.fall_aspect_ratio <= 0 or self.motion_threshold < 0:
            raise ValueError("fall_aspect_ratio must be positive and motion_threshold 0 or more")


@dataclass(frozen=True)
class PostureMeasurement:
    aspect_ratio: float
    centroid: tuple[float, float]
    motion: float
    low_posture: bool
    moving: bool


def mask_geometry(mask: Any) -> tuple[float, tuple[float, float]] | None:
    """mask 에서 (가로/세로 비, centroid). 빈 mask 면 `None`.

    비율은 bbox 로 재고 centroid 는 픽셀 평균으로 낸다. bbox 는 자세에, centroid
    는 움직임에 쓰인다 — bbox 중심을 쓰면 팔다리 하나가 튀어나올 때 중심이 크게
    흔들려 정지를 움직임으로 잘못 읽는다.
    """
    import numpy as np

    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    width = int(xs.max() - xs.min() + 1)
    height = int(ys.max() - ys.min() + 1)
    return width / max(height, 1), (float(xs.mean()), float(ys.mean()))


class PostureEstimator:
    """연속 프레임에서 자세와 움직임을 잰다. centroid 하나를 기억한다."""

    def __init__(self, config: PostureConfig) -> None:
        self.config = config
        self._last_centroid: tuple[float, float] | None = None

    def measure(self, mask: Any, frame_diagonal: float) -> PostureMeasurement | None:
        geometry = mask_geometry(mask)
        if geometry is None:
            # 사람이 안 잡힌 프레임은 "정지" 가 아니다. 다음에 다시 잡혔을 때
            # 그 사이를 이동으로 세지 않도록 기준을 버린다.
            self._last_centroid = None
            return None
        aspect_ratio, centroid = geometry
        if self._last_centroid is None:
            motion = 0.0
        else:
            moved = hypot(centroid[0] - self._last_centroid[0], centroid[1] - self._last_centroid[1])
            motion = moved / max(frame_diagonal, 1.0)
        self._last_centroid = centroid
        return PostureMeasurement(
            aspect_ratio=aspect_ratio,
            centroid=centroid,
            motion=motion,
            low_posture=aspect_ratio >= self.config.fall_aspect_ratio,
            moving=motion > self.config.motion_threshold,
        )

    def reset(self) -> None:
        self._last_centroid = None


class TrackedPostureEstimator:
    """track 마다 `PostureEstimator` 를 따로 둔다.

    `PostureEstimator` 는 centroid 를 하나만 기억한다. 한 화면에 두 사람이
    있으면 그 하나를 번갈아 덮어써서, 걸어가는 사람의 위치가 가만히 있는
    사람의 이동량으로 읽힌다 — 증상은 "가만히 누워 있는 사람이 계속 움직이는
    것으로 잡혀 `IMMOBILE` 에 못 간다" 로 나타난다.
    """

    def __init__(self, config: PostureConfig) -> None:
        self.config = config
        self._by_track: dict[str, PostureEstimator] = {}

    def measure(self, track_id: str, mask: Any, frame_diagonal: float) -> PostureMeasurement | None:
        estimator = self._by_track.get(track_id)
        if estimator is None:
            estimator = PostureEstimator(self.config)
            self._by_track[track_id] = estimator
        return estimator.measure(mask, frame_diagonal)

    def forget_missing(self, seen_track_ids: set[str]) -> None:
        """이번 프레임에 안 잡힌 track 의 기준을 버린다.

        `PostureEstimator.reset` 과 같은 이유다 — 사라진 동안 사람이 움직였다면
        다시 잡혔을 때의 위치 차이는 이동이 아니라 관측 공백이다.
        """
        for track_id in list(self._by_track):
            if track_id not in seen_track_ids:
                del self._by_track[track_id]
