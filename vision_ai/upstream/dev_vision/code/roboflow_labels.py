"""Roboflow YOLOv8-seg export(images/ + labels/*.txt + data.yaml)를 읽어서
fallen 분류기 학습용 (이미지 경로, polygon, fallen 여부) 레코드로 변환.

Roboflow export 표준 레이아웃 가정:
    <export_root>/
        data.yaml          # names: [person, fallen_person, ...]
        train/images/*.jpg, train/labels/*.txt
        valid/images/*.jpg, valid/labels/*.txt
        test/images/*.jpg,  test/labels/*.txt
    라벨 한 줄 = "class_id x1 y1 x2 y2 ... xn yn" (0~1 정규화 polygon, YOLO-seg 포맷).

fallen으로 취급하는 클래스 이름은 FALLEN_CLASS_NAMES에서 매칭(대소문자 무시,
'fallen'이 이름에 포함되면 fallen으로 간주) -- 정확한 클래스명은 라벨링할 때
data.yaml에서 확인 후 필요하면 이 목록에 추가.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

FALLEN_CLASS_NAMES = {"fallen_person", "fallen person", "fallen", "person_fallen"}
NOT_FALLEN_CLASS_NAMES = {"non_fallen", "non-fallen", "not_fallen", "person", "standing"}


@dataclass(frozen=True)
class LabelRecord:
    image_path: Path
    split: str  # "train" / "valid" / "test"
    class_name: str
    is_fallen: bool
    polygon: list[tuple[float, float]]  # 0..1 정규화 좌표


def _is_fallen_class(name: str) -> bool:
    lowered = name.strip().lower()
    if lowered in NOT_FALLEN_CLASS_NAMES:
        return False
    return lowered in FALLEN_CLASS_NAMES or "fallen" in lowered


def _parse_label_file(label_path: Path, class_names: list[str]) -> list[tuple[str, list[tuple[float, float]]]]:
    if not label_path.is_file():
        return []
    records = []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 7 or len(parts) % 2 == 0:
            continue  # class_id + 짝수개 좌표(x,y 쌍)라 홀수 길이여야 정상
        class_id = int(parts[0])
        if class_id >= len(class_names):
            continue
        coords = [float(v) for v in parts[1:]]
        polygon = list(zip(coords[0::2], coords[1::2]))
        records.append((class_names[class_id], polygon))
    return records


def load_roboflow_export(export_root: Path) -> list[LabelRecord]:
    export_root = Path(export_root).expanduser().resolve()
    data_yaml = export_root / "data.yaml"
    if not data_yaml.is_file():
        raise FileNotFoundError(f"data.yaml을 찾을 수 없습니다: {data_yaml}")
    meta = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
    class_names = meta["names"] if isinstance(meta["names"], list) else list(meta["names"].values())

    records: list[LabelRecord] = []
    for split in ("train", "valid", "test"):
        images_dir = export_root / split / "images"
        labels_dir = export_root / split / "labels"
        if not images_dir.is_dir():
            continue
        for image_path in sorted(images_dir.glob("*.*")):
            if image_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                continue
            label_path = labels_dir / f"{image_path.stem}.txt"
            for class_name, polygon in _parse_label_file(label_path, class_names):
                lowered = class_name.strip().lower()
                if lowered not in NOT_FALLEN_CLASS_NAMES and lowered not in FALLEN_CLASS_NAMES \
                        and "fallen" not in lowered:
                    continue  # obstacle 등 person이 아닌 클래스는 분류기 데이터에서 제외
                records.append(LabelRecord(
                    image_path=image_path, split=split, class_name=class_name,
                    is_fallen=_is_fallen_class(class_name), polygon=polygon,
                ))
    return records


def load_all_instances_by_image(
    export_root: Path,
) -> dict[Path, list[tuple[str, list[tuple[float, float]]]]]:
    """이미지별 **모든 클래스**(person/fallen/standing/obstacle 다 포함) (class_name, polygon)
    목록. class_name을 유지하는 이유는 "사람-사람 접촉"과 "사람-장애물 접촉"을 서로 다른
    피처로 분리하기 위함(사람-사람이 더 신뢰도 높은 신호로 판단됨, 2026-08-24).
    `load_roboflow_export`는 obstacle을 걸러내지만 여기서는 안 거름."""
    export_root = Path(export_root).expanduser().resolve()
    data_yaml = export_root / "data.yaml"
    meta = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
    class_names = meta["names"] if isinstance(meta["names"], list) else list(meta["names"].values())

    by_image: dict[Path, list[tuple[str, list[tuple[float, float]]]]] = {}
    for split in ("train", "valid", "test"):
        images_dir = export_root / split / "images"
        labels_dir = export_root / split / "labels"
        if not images_dir.is_dir():
            continue
        for image_path in sorted(images_dir.glob("*.*")):
            if image_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                continue
            label_path = labels_dir / f"{image_path.stem}.txt"
            by_image[image_path] = _parse_label_file(label_path, class_names)
    return by_image


def summarize(records: list[LabelRecord]) -> dict[str, dict[str, int]]:
    """split별 fallen/not-fallen 개수 -- posture_manifest용 min_fallen_per_eval_split
    확인이나 데이터 점검용."""
    summary: dict[str, dict[str, int]] = {}
    for r in records:
        bucket = summary.setdefault(r.split, {"fallen": 0, "not_fallen": 0})
        bucket["fallen" if r.is_fallen else "not_fallen"] += 1
    return summary
