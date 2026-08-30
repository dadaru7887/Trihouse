"""낙상 분류기가 읽는 다섯 피처. `dev_vision` 배달본의 정의를 그대로 옮겼다.

**좌표계가 계약의 일부다.** 배달본은 학습·추론 모두 ultralytics 의
`masks.xyn`/`boxes.xyxyn`, 즉 프레임 크기로 나눈 0..1 좌표 위에서 쟀다. 우리
`posture.py` 는 픽셀 좌표로 잰다. 두 기준은 프레임이 정사각형이 아닌 한 다르다 —
640x480 에서 200x100 mask 의 종횡비는 픽셀로 2.0, 정규화로 1.5 다.

`aspect_ratio` 는 번들에서 계수가 +5.273 으로 압도적이라, 픽셀 비율을 그대로
넣으면 가장 강한 신호가 조용히 틀어진다. 그래서 여기서는 정규화 좌표로 잰다.
규칙 경로(`posture.py`)는 픽셀 기준 그대로 둔다 — 그쪽의 0.9 는 픽셀 비율 위에서
실측된 값이고, 기준을 바꾸면 그 측정이 무효가 된다.

피처 순서는 학습 때 `np.concatenate([geometric, contact])` 순서와 같아야 한다:
    (aspect_ratio, pca_angle_deg, centroid_y, contact_person_iou, contact_obstacle_iou)
"""

from __future__ import annotations

from typing import Any, Sequence

# 배달본과 같은 값. 이보다 크게 겹치면 대상 자신으로 본다.
SELF_OVERLAP_IOU = 0.95

FEATURE_NAMES = (
    "aspect_ratio",
    "pca_angle",
    "centroid_y",
    "contact_person_iou",
    "contact_obstacle_iou",
)


def geometric_features(mask: Any, frame_shape: tuple[int, ...]) -> tuple[float, float, float] | None:
    """(종횡비, PCA 주축 각도[0,180), centroid 세로 위치) — 전부 정규화 좌표.

    빈 mask 면 `None`. 각도는 mask 화소의 공분산 행렬에서 가장 큰 고유값의
    고유벡터 방향이다 — 사람이 누운 방향을 읽는다.
    """
    import numpy as np

    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    height, width = float(frame_shape[0]), float(frame_shape[1])
    nx = xs / max(width, 1.0)
    ny = ys / max(height, 1.0)

    # `mask_geometry` 와 같이 화소 개수로 센다(+1). 배달본은 polygon 정점을 써서
    # +1 이 없는데, 200 화소짜리 mask 에서 차이는 0.5% 로 mask 자체의 흔들림보다
    # 훨씬 작다. 저장소 안에서 종횡비 정의가 갈리지 않는 쪽을 택했다.
    span_x = float(xs.max() - xs.min() + 1) / max(width, 1.0)
    span_y = float(ys.max() - ys.min() + 1) / max(height, 1.0)
    aspect_ratio = span_x / max(span_y, 1e-6)
    centroid_y = float(ny.mean())

    points = np.stack([nx, ny])
    centered = points - points.mean(axis=1, keepdims=True)
    covariance = np.cov(centered)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    principal = eigenvectors[:, int(np.argmax(eigenvalues))]
    angle_deg = float(np.degrees(np.arctan2(principal[1], principal[0])) % 180.0)

    return aspect_ratio, angle_deg, centroid_y


def _normalized_box(mask: Any, frame_shape: tuple[int, ...]) -> tuple[float, float, float, float] | None:
    import numpy as np

    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    height, width = float(frame_shape[0]), float(frame_shape[1])
    return (
        float(xs.min()) / width, float(ys.min()) / height,
        float(xs.max()) / width, float(ys.max()) / height,
    )


def _box_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def contact_features(target: Any, detections: Sequence[Any], *,
                     person_class_id: int) -> tuple[float, float]:
    """(사람-사람 최대 접촉 IoU, 사람-장애물 최대 접촉 IoU).

    종횡비가 거의 안 변하는 "기대는 낙상" 을 잡기 위한 2차 신호다. 배달본 실측
    (171307)에서 기대기 전 0.000 이던 값이 기댄 뒤 0.05~0.13 으로 올라 GT 타임
    라인과 일치했고, 같은 구간에서 종횡비는 거의 무신호였다.

    IoU 는 축마다 다른 배율로 늘려도 변하지 않으므로 픽셀이든 정규화든 같은
    값이 나온다. 그래도 정규화로 재서 나머지 피처와 기준을 맞춘다.
    """
    frame_shape = target.mask.shape
    target_box = _normalized_box(target.mask, frame_shape)
    if target_box is None:
        return 0.0, 0.0
    person_max, obstacle_max = 0.0, 0.0
    for other in detections:
        if other is target:
            continue
        other_box = _normalized_box(other.mask, frame_shape)
        if other_box is None:
            continue
        iou = _box_iou(target_box, other_box)
        if iou >= SELF_OVERLAP_IOU:
            # 대상 자신이 중복 검출된 것으로 본다. 배달본과 같은 규칙이다.
            continue
        if other.class_id == person_class_id:
            person_max = max(person_max, iou)
        else:
            obstacle_max = max(obstacle_max, iou)
    return person_max, obstacle_max


def fallen_features(target: Any, detections: Sequence[Any], frame_shape: tuple[int, ...], *,
                    person_class_id: int) -> tuple[float, ...] | None:
    """학습 때와 같은 순서의 다섯 값. 빈 mask 면 `None`."""
    geometry = geometric_features(target.mask, frame_shape)
    if geometry is None:
        return None
    contact = contact_features(target, detections, person_class_id=person_class_id)
    return (*geometry, *contact)
