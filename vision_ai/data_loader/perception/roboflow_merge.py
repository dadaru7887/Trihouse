"""Download the two Roboflow exports and merge them into one training dataset.

Both projects are instance segmentation. `trihouse` labels obstacle/person;
`trihouse_detect_fallen` labels Fallen/Obstacle/Standing. Segmentation only
needs obstacle vs person, so Fallen and Standing both map to person, and the
posture distinction is carried in a side manifest for the fall classifier.

    python -m vision_ai.data_loader.perception.roboflow_merge \
        --api-key <key> --out data/pinky_camera --seed 42

Flow: download each export -> remap classes to [obstacle, person] -> group
frames by episode -> assign whole episodes to train/valid/test -> write the
merged dataset plus posture_manifest.csv.

Splits are by episode, never by frame: adjacent frames of one video are near
identical, so a frame-level split measures memorisation.
"""

import argparse
import csv
import json
import random
import re
import shutil
from pathlib import Path
from typing import Iterable

import yaml


# Class order the runtime depends on: robot/configs/realtime.yaml sets
# person_class_id: 1. Swapping these swaps people and obstacles.
MERGED_CLASSES = ["obstacle", "person"]

# Source class name (lowercased) -> merged class index.
NAME_TO_MERGED = {
    "obstacle": 0,
    "person": 1,
    "fallen": 1,     # a fallen person is still a person to the detector
    "standing": 1,
}

# Source class name (lowercased) -> posture recorded in the manifest.
NAME_TO_POSTURE = {"fallen": "fallen", "standing": "standing", "person": "unknown"}

# Frames whose filename carries no video id; kept in train so an unknown
# source cannot leak into valid or test.
LEGACY_EPISODE = "legacy_frames"

# How far past its frame target an evaluation split may go when taking one more
# episode. Above this the episode goes to train instead.
OVERSHOOT_LIMIT = 1.15

_EPISODE = re.compile(r"dataset_video_(\d{8}_\d{6})")


def episode_of(filename: str) -> str:
    """Return the video id embedded in a Roboflow filename, or LEGACY_EPISODE."""
    match = _EPISODE.search(filename)
    return match.group(1) if match else LEGACY_EPISODE


def remap_label_text(text: str, mapping: dict[int, int]) -> str:
    """Rewrite the class id on every polygon line; coordinates pass through."""
    lines = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()          # "<class> x1 y1 x2 y2 ..."
        source = int(parts[0])
        if source not in mapping:
            # Skipping an unmapped class would drop the instance silently.
            raise ValueError(f"line {number}: class {source} is outside the mapping")
        # Only the class id changes; polygon coordinates are untouched.
        lines.append(" ".join([str(mapping[source]), *parts[1:]]))
    return "\n".join(lines) + ("\n" if lines else "")


def plan_splits(episode_stats: dict[str, dict[str, int]], seed: int = 42,
                min_fallen: int = 10, eval_ratio: float = 0.2) -> dict[str, list[str]]:
    """Assign whole episodes to train/valid/test, keeping evaluation usable.

    valid and test must each hold at least `min_fallen` fallen frames, or the
    fall metrics cannot be read. Episodes richest in fallen frames are seeded
    into the evaluation splits first, then the rest fill toward the frame
    ratio. LEGACY_EPISODE is pinned to train.
    """
    stats = {e: s for e, s in episode_stats.items() if e != LEGACY_EPISODE}
    has_legacy = LEGACY_EPISODE in episode_stats
    if len(stats) < 3:
        raise ValueError(f"need at least 3 episodes to split, got {len(stats)}")

    total_fallen = sum(s["fallen"] for s in stats.values())
    if total_fallen < 2 * min_fallen:
        raise ValueError(
            f"only {total_fallen} fallen frames; valid and test each need {min_fallen}")

    # Phase 1 -- balance frames. Largest episodes first, each going to the
    # split furthest below its frame target.
    total_frames = sum(s["frames"] for s in stats.values())
    target = {"valid": total_frames * eval_ratio, "test": total_frames * eval_ratio,
              "train": total_frames * (1 - 2 * eval_ratio)}
    # Largest episodes first; a big one placed last swings the ratios.
    order = sorted(stats, key=lambda e: (-stats[e]["frames"], e))
    random.Random(seed).shuffle(order[len(order) // 2:])   # shuffle the small half by seed

    plan: dict[str, list[str]] = {"train": [], "valid": [], "test": []}
    frames = {"train": 0, "valid": 0, "test": 0}
    fallen = {"train": 0, "valid": 0, "test": 0}
    for episode in order:
        size = stats[episode]["frames"]
        # An eval split that one episode would fill on its own cannot tell that
        # episode's quirks from real generalisation, so oversized episodes go to
        # train and the eval splits collect several smaller ones.
        # train always qualifies; an eval split qualifies only while taking
        # this episode keeps it within OVERSHOOT_LIMIT x its frame target.
        candidates = [s for s in ("train", "valid", "test")
                      if s == "train" or (frames[s] + size) / target[s] <= OVERSHOOT_LIMIT]
        # Send it to whichever split would stay least full relative to target.
        split = min(candidates, key=lambda s: (frames[s] + size) / target[s])
        plan[split].append(episode)
        frames[split] += stats[episode]["frames"]
        fallen[split] += stats[episode]["fallen"]

    # Phase 2 -- repair. While an eval split is short of fallen frames, pull in
    # the fallen-richest episode still sitting in train.
    for split in ("valid", "test"):
        while fallen[split] < min_fallen:
            # Fallen-richest first; episodes with no fallen frames cannot help.
            donors = sorted(plan["train"], key=lambda e: (-stats[e]["fallen"], e))
            donors = [e for e in donors if stats[e]["fallen"] > 0]
            if not donors:
                raise ValueError(
                    f"cannot reach {min_fallen} fallen frames in {split} "
                    f"(have {fallen[split]}); no fallen episodes left in train")
            episode = donors[0]
            plan["train"].remove(episode)
            plan[split].append(episode)
            for bucket, delta in ((frames, "frames"), (fallen, "fallen")):
                bucket["train"] -= stats[episode][delta]
                bucket[split] += stats[episode][delta]

    if not plan["train"]:
        raise ValueError("no episodes left for train; supply more episodes")
    if has_legacy:
        plan["train"] = [LEGACY_EPISODE, *plan["train"]]
    return {split: sorted(episodes) for split, episodes in plan.items()}


def _class_names(export_root: Path) -> list[str]:
    """Read the class list from an export's data.yaml."""
    meta = yaml.safe_load((export_root / "data.yaml").read_text(encoding="utf-8"))
    names = meta["names"]
    return list(names) if isinstance(names, list) else list(names.values())


def _collect(export_root: Path) -> list[tuple[Path, Path, list[str]]]:
    """List (image, label, class_names) for every annotated frame in an export."""
    names = _class_names(export_root)
    found = []
    for split in ("train", "valid", "test"):
        images = export_root / split / "images"
        labels = export_root / split / "labels"
        if not images.is_dir():
            continue
        for image in sorted(images.iterdir()):
            if image.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                continue
            label = labels / f"{image.stem}.txt"
            if label.is_file():
                found.append((image, label, names))
    return found


def _posture_of(label_text: str, names: list[str]) -> str:
    """Image-level posture: fallen wins, then standing, else unknown."""
    # One image may hold several people, but the manifest has one row per
    # image, so the most severe posture becomes the representative value.
    seen = {names[int(line.split()[0])].strip().lower()
            for line in label_text.splitlines() if line.strip()}
    if "fallen" in seen:
        return "fallen"
    if "standing" in seen:
        return "standing"
    return "unknown"


def merge_exports(exports: dict[str, Path], out_dir: Path, seed: int = 42,
                  min_fallen: int = 10) -> dict:
    """Merge exports into one dataset at `out_dir` and return a summary."""
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"output directory is not empty: {out_dir}")

    frames = [item for root in exports.values() for item in _collect(Path(root))]
    if not frames:
        raise ValueError("no annotated frames found in the given exports")

    # Count frames and fallen frames per episode before assigning splits;
    # plan_splits needs both to satisfy the ratio and the fallen floor at once.
    stats: dict[str, dict[str, int]] = {}
    for image, label, names in frames:
        episode = stats.setdefault(episode_of(image.name), {"frames": 0, "fallen": 0})
        episode["frames"] += 1
        if _posture_of(label.read_text(encoding="utf-8"), names) == "fallen":
            episode["fallen"] += 1
    plan = plan_splits(stats, seed=seed, min_fallen=min_fallen)
    split_of = {episode: split for split, episodes in plan.items() for episode in episodes}

    for split in ("train", "valid", "test"):
        (out_dir / split / "images").mkdir(parents=True, exist_ok=True)
        (out_dir / split / "labels").mkdir(parents=True, exist_ok=True)

    manifest_rows, counts = [], {s: 0 for s in ("train", "valid", "test")}
    for image, label, names in frames:
        split = split_of[episode_of(image.name)]
        # Class order differs per export, so rebuild the export-index ->
        # merged-index table for each frame. (fallen: 0,1,2 / segmentation: 0,1)
        mapping = {i: NAME_TO_MERGED[n.strip().lower()] for i, n in enumerate(names)
                   if n.strip().lower() in NAME_TO_MERGED}
        text = label.read_text(encoding="utf-8")
        # Images are copied as-is; augmentation happens at training time.
        (out_dir / split / "images" / image.name).write_bytes(image.read_bytes())
        (out_dir / split / "labels" / label.name).write_text(
            remap_label_text(text, mapping), encoding="utf-8")
        manifest_rows.append({
            "image": f"{split}/images/{image.name}",
            "posture": _posture_of(text, names),
            "environment": "unknown",   # source frames are un-augmented
        })
        counts[split] += 1

    (out_dir / "data.yaml").write_text(
        "names:\n" + "".join(f"- {n}\n" for n in MERGED_CLASSES)
        + f"nc: {len(MERGED_CLASSES)}\n"
        + "train: train/images\nval: valid/images\ntest: test/images\n",
        encoding="utf-8")

    with (out_dir / "posture_manifest.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["image", "posture", "environment"])
        writer.writeheader()
        writer.writerows(manifest_rows)

    report = {
        "images": len(frames), "per_split": counts, "episodes": plan, "seed": seed,
        "sources": {name: str(Path(root).resolve()) for name, root in exports.items()},
        "classes": MERGED_CLASSES,
        "postures": {p: sum(r["posture"] == p for r in manifest_rows)
                     for p in ("fallen", "standing", "unknown")},
    }
    (out_dir / "merge_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def download_exports(api_key: str, out_dir: Path) -> dict[str, Path]:
    """Download both Roboflow projects as YOLOv8 segmentation exports."""
    from roboflow import Roboflow

    workspace = Roboflow(api_key=api_key).workspace("dahyuns-workspace-o0qqk")
    out_dir = Path(out_dir)
    roots = {}
    for name, project, version in (("segmentation", "trihouse", 7),
                                   ("fallen", "trihouse_detect_fallen", 2)):
        target = out_dir / name
        if target.exists():
            shutil.rmtree(target)
        workspace.project(project).version(version).download(
            "yolov8", location=str(target), overwrite=True)
        roots[name] = target
    return roots


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download and merge the Roboflow exports into one training dataset")
    parser.add_argument("--api-key", help="Roboflow API key; omit to reuse an existing download")
    parser.add_argument("--out", type=Path, required=True,
                        help="Directory holding the downloads and the merged/ output")
    parser.add_argument("--seed", type=int, default=42, help="Seed for the episode split")
    parser.add_argument("--min-fallen", type=int, default=10,
                        help="Fallen frames each of valid and test must hold")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out = Path(args.out)
    if args.api_key:
        roots = download_exports(args.api_key, out)
    else:
        roots = {name: out / name for name in ("segmentation", "fallen")
                 if (out / name / "data.yaml").is_file()}
        if not roots:
            print(f"no existing export under {out}; pass --api-key to download", flush=True)
            return 2
    report = merge_exports(roots, out / "merged", seed=args.seed,
                           min_fallen=args.min_fallen)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
