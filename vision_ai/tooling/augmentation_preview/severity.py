"""Measure how hard each recipe hits a real frame, so nothing ships unreadable.

Two failures this catches, both of which happened:
a recipe that changes nothing scores like a free win, and a recipe that erases
the subject teaches nothing and cannot be annotated either.

    python -m vision_ai.tooling.augmentation_preview.severity \
        --dataset data/pinky_camera/merged --out runs/augmentation_preview

    # sweep one effect's strength instead, to pick a setting
    python -m vision_ai.tooling.augmentation_preview.severity \
        --dataset data/pinky_camera/merged --out runs/augmentation_preview --sweep blur

Flow: load a handful of valid frames -> apply every recipe -> report the mean
pixel shift and the share of the frame that moved by more than JND. Sweeps
render a strength ladder as a PNG instead, for judging by eye.

Reading it: share is the useful column. Under ~5% the effect barely exists;
the subject staying recognisable is a judgement call the sheet supports, not
a number this prints.
"""

from __future__ import annotations

import argparse
from pathlib import Path

# A change smaller than this is below what matters visually, so it is not
# counted as "the frame moved here".
JND = 12
SAMPLE_FRAMES = 8


def _load(dataset: Path, images: Path | None, count: int):
    """Load frames to measure on, from a merged dataset or a plain directory."""
    import cv2

    from vision_ai.tooling.augmentation_preview.preview import frames_from_dataset

    if images is not None:
        paths = [p for p in sorted(Path(images).iterdir())
                 if p.suffix.lower() in (".jpg", ".jpeg", ".png")][:count]
    else:
        paths = frames_from_dataset(dataset, limit=count, posture="fallen")
    frames = [cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB) for p in paths]
    if not frames:
        raise ValueError("no frames to measure")
    return frames


def measure(frames, recipe_id: str) -> tuple[float, float]:
    """Return (mean pixel shift, share of the frame changed) for one recipe."""
    import numpy as np

    from vision_ai.utils.augmentation import scenarios

    shifts, shares = [], []
    for index, frame in enumerate(frames):
        # A fixed seed per frame keeps the table comparable between runs.
        scenarios.configure_augmentation_seed(200 + index)
        out = scenarios.apply_recipe(frame.copy(), recipe_id)
        delta = np.abs(out.astype(np.int16) - frame.astype(np.int16))
        shifts.append(delta.mean())
        shares.append((delta.max(axis=2) > JND).mean() * 100)
    return float(np.mean(shifts)), float(np.mean(shares))


def report(frames) -> str:
    """Build the per-recipe severity table, grouped the way the tiers are."""
    from vision_ai.utils.augmentation import scenarios

    lines = [f"{'recipe':34}{'mean shift':>12}{'frame changed':>15}"]
    group = None
    for recipe in scenarios.RECIPES:
        if recipe.group != group:
            group = recipe.group
            lines.append(f"\n-- {group} ({len(scenarios.recipes_in(group))}) --")
        shift, share = measure(frames, recipe.id)
        note = "   <- barely changes the frame" if share < 5 else ""
        lines.append(f"{recipe.id:34}{shift:12.1f}{share:14.1f}%{note}")
    return "\n".join(lines)


# Strength ladders for the two effects whose settings needed judging by eye.
SWEEPS = {
    "blur": ("motion_blur {}px", "add_motion_blur",
             [dict(ksize=k, angle=18) for k in (9, 15, 21, 25, 31, 45, 70)]),
    "dark": ("gamma_brightness f={factor} g={gamma}", "gamma_brightness",
             [dict(factor=f, gamma=g) for f, g in
              ((0.8, 1.0), (0.6, 1.1), (0.5, 1.2), (0.4, 1.3), (0.3, 1.4))]),
    "frost": ("frost cov={coverage_ratio} t={temperature_delta}",
              "generate_frost_overlay_chunky",
              [dict(coverage_ratio=c, temperature_delta=t, seed=7, n_anchors=4)
               for c, t in ((0.15, 0.30), (0.30, 0.40), (0.45, 0.55), (0.60, 0.70))]),
}


def sweep(frame, name: str, out_dir: Path) -> Path:
    """Render one effect at rising strength, for picking a setting by eye."""
    import cv2

    from vision_ai.tooling.augmentation_preview import preview
    from vision_ai.utils.augmentation import primitives

    label, function, settings = SWEEPS[name]
    effect = getattr(primitives, function)
    panels = [("original", frame)]
    for kwargs in settings:
        caption = label.format(*kwargs.values(), **kwargs)
        panels.append((caption, effect(frame.copy(), **kwargs)))
    panels = [(caption, cv2.cvtColor(image, cv2.COLOR_RGB2BGR)) for caption, image in panels]

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"_sweep_{name}.png"
    cv2.imwrite(str(target), preview._tile(panels, columns=4))
    return target


def build_parser() -> argparse.ArgumentParser:
    """Define the command line: which frames, and table or sweep."""
    parser = argparse.ArgumentParser(
        description="Measure augmentation severity on real frames")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--dataset", type=Path, help="Merged dataset root")
    source.add_argument("--images", type=Path, help="Directory of source frames")
    parser.add_argument("--out", type=Path, help="Where to write the table and sweeps")
    parser.add_argument("--sweep", choices=sorted(SWEEPS),
                        help="Render a strength ladder for one effect instead of the table")
    parser.add_argument("--frames", type=int, default=SAMPLE_FRAMES,
                        help="How many frames to average the table over")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Print the severity table, or render the requested sweep."""
    args = build_parser().parse_args(argv)
    frames = _load(args.dataset, args.images, args.frames)

    if args.sweep:
        print(sweep(frames[0], args.sweep, args.out or Path(".")))
        return 0

    text = report(frames)
    print(text)
    if args.out:
        target = Path(args.out) / "severity.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
        print(f"\nwritten to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
