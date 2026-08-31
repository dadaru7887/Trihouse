"""Evaluate one trained model under each degradation scenario, one at a time.

Fix the evaluation set, vary the corruption -- the ImageNet-C shape. Every
scenario is applied to the whole split, so no per-condition cell is thinner
than the split itself.

    # one condition
    python -m vision_ai.models.perception.trainer.corruption_eval \
        --run-dir runs/lego_worker/<run> --split valid --scenario S4

    # every condition, plus clean
    python -m vision_ai.models.perception.trainer.corruption_eval \
        --run-dir runs/lego_worker/<run> --split valid --all

Flow: copy the split -> apply the scenario to each image (labels untouched,
these are photometric effects) -> write a data.yaml pointing at the copy ->
run the usual YOLOE evaluation against it.

Reading the numbers: training on a scenario and evaluating on the same one
measures whether the model learned that simulator, not whether it is robust
to the real phenomenon. Pair this with `--holdout` at training time to get a
model that never saw the scenario it is being scored on.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import yaml

CLEAN = "clean"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _split_dir(dataset_yaml: Path, split: str) -> Path:
    """Resolve the image directory a data.yaml gives for one split."""
    meta = _load_yaml(dataset_yaml)
    key = {"train": "train", "valid": "val", "test": "test"}[split]
    raw = Path(str(meta[key]))
    root = Path(dataset_yaml).resolve().parent
    return (raw if raw.is_absolute() else root / raw).resolve()


def build_corrupted_split(dataset_yaml: Path, split: str, scenario: str,
                          out_dir: Path, seed: int = 42) -> Path:
    """Write a copy of `split` with `scenario` applied, and return its data.yaml.

    `scenario` may be CLEAN, which copies the images untouched so the same
    code path produces the baseline.
    """
    import cv2

    from vision_ai.utils.augmentation import scenarios

    if scenario != CLEAN and scenario not in scenarios.SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")

    images_in = _split_dir(Path(dataset_yaml), split)
    labels_in = images_in.parent / "labels"
    out_dir = Path(out_dir)
    images_out = out_dir / split / "images"
    labels_out = out_dir / split / "labels"
    for directory in (images_out, labels_out):
        directory.mkdir(parents=True, exist_ok=True)

    scenarios.configure_augmentation_seed(seed)
    for image_path in sorted(images_in.iterdir()):
        if image_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        if scenario == CLEAN:
            shutil.copyfile(image_path, images_out / image_path.name)
        else:
            image = cv2.imread(str(image_path))
            cv2.imwrite(str(images_out / image_path.name),
                        scenarios.apply_scenario(image, scenario))
        label = labels_in / f"{image_path.stem}.txt"
        if label.is_file():
            shutil.copyfile(label, labels_out / label.name)

    meta = _load_yaml(Path(dataset_yaml))
    target = out_dir / "data.yaml"
    target.write_text(
        "names:\n" + "".join(f"- {n}\n" for n in
                             (meta["names"] if isinstance(meta["names"], list)
                              else list(meta["names"].values())))
        + f"nc: {meta['nc']}\n"
        + f"train: {split}/images\nval: {split}/images\ntest: {split}/images\n",
        encoding="utf-8")
    return target


def evaluate_scenarios(run_dir: Path, split: str, scenarios_to_run: list[str],
                       weights: Path | None = None, seed: int = 42,
                       work_dir: Path | None = None) -> dict[str, dict]:
    """Evaluate one run against each scenario and return name -> metrics."""
    from vision_ai.models.perception.trainer.yoloe_trainer import YOLOEBackend
    from vision_ai.utils.run_config import TrainingConfig

    run_dir = Path(run_dir)
    config = TrainingConfig.from_dict(
        json.loads((run_dir / "config/resolved.json").read_text(encoding="utf-8")))
    weights = weights or run_dir / "train/weights/best.pt"
    work_dir = Path(work_dir or run_dir / "corruption_eval")

    backend, results = YOLOEBackend(), {}
    for scenario in scenarios_to_run:
        target = work_dir / scenario
        if target.exists():
            shutil.rmtree(target)
        data_yaml = build_corrupted_split(config.data, split, scenario, target, seed=seed)
        scoped = TrainingConfig.from_dict({**config.to_dict(), "data": str(data_yaml)})
        results[scenario] = backend.evaluate(weights, split, scoped, target)
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Score one trained model under each degradation scenario")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--split", choices=("valid", "test"), default="valid")
    parser.add_argument("--scenario", help="One of clean/S1..S5")
    parser.add_argument("--all", action="store_true", help="clean plus every scenario")
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, help="Where to write the metrics JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    from vision_ai.utils.augmentation import scenarios as scenario_module

    args = build_parser().parse_args(argv)
    if args.all:
        wanted = [CLEAN, *scenario_module.SCENARIOS]
    elif args.scenario:
        wanted = [args.scenario]
    else:
        print("pass --scenario or --all", flush=True)
        return 2

    results = evaluate_scenarios(args.run_dir, args.split, wanted,
                                 weights=args.weights, seed=args.seed)
    output = args.out or Path(args.run_dir) / f"evaluation/corruption_{args.split}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
