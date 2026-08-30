"""낙상 분류기 학습 데이터셋을 읽고, 학습을 시작하기 전에 의심한다.

세그멘테이션 쪽 `training/dataloader/audit.py` 와 같은 자리다. 형식만 맞으면
통과시키는 것이 아니라, 지표를 낼 수 없는 데이터셋이면 학습 자체를 거절한다 —
조용히 이상한 모델을 만드는 것보다 뜨지 않는 편이 낫다.

한 줄에 한 인스턴스인 JSONL 이다.

    {"features": [aspect_ratio, pca_angle, centroid_y,
                  contact_person_iou, contact_obstacle_iou],
     "fallen": true, "split": "train"}

`split` 은 `train` / `valid` / `test` 셋뿐이다.
"""

from __future__ import annotations

import json
from pathlib import Path

from vision_ai.models.perception.features import FEATURE_NAMES

SPLITS = ("train", "valid", "test")


class DatasetError(ValueError):
    """학습을 시작할 수 없는 데이터셋. 조용히 이상한 모델을 만드는 대신 터진다."""


def load_dataset(path: Path) -> dict[str, tuple[list[list[float]], list[int]]]:
    rows: dict[str, tuple[list[list[float]], list[int]]] = {s: ([], []) for s in SPLITS}
    text = Path(path).read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise DatasetError(f"{path}:{number} JSON 이 아닙니다 — {error}") from error
        split = record.get("split")
        if split not in rows:
            raise DatasetError(f"{path}:{number} split 은 train/valid/test 중 하나여야 합니다: {split!r}")
        features = record.get("features")
        if not isinstance(features, list) or len(features) != len(FEATURE_NAMES):
            raise DatasetError(
                f"{path}:{number} features 는 계약된 다섯 값(five)이어야 합니다: {FEATURE_NAMES}"
            )
        rows[split][0].append([float(value) for value in features])
        rows[split][1].append(1 if record.get("fallen") else 0)

    for split in SPLITS:
        features, labels = rows[split]
        if not features:
            raise DatasetError(f"{split} split 이 비어 있습니다 (valid/test 도 필요합니다)")
        if sum(labels) == 0:
            raise DatasetError(f"{split} split 에 fallen 예시가 없습니다 — 지표를 낼 수 없습니다")
        if sum(labels) == len(labels):
            raise DatasetError(f"{split} split 에 정상 예시가 없습니다 — 지표를 낼 수 없습니다")
    return rows
