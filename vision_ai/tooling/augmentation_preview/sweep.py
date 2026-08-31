"""Render one effect at rising strength, to choose a setting before it ships.

One of the two tools here. Run it once per decision, not per training run: the
value picked ends up in `utils/augmentation/scenarios.py` as a fixed recipe
parameter, and preview.py checks it from then on.

    python -m vision_ai.tooling.augmentation_preview.sweep \
        --dataset data/pinky_camera/merged --out runs/augmentation_preview --effect blur

Flow: load one frame -> apply the effect at each strength in the ladder ->
write a PNG tiling them in order.

The question this answers cannot be answered by a number: 45px motion blur
and 25px change a similar share of the frame, but at 45px the figures smear
into streaks and nobody could label them. That is why the ladders are images.

Reasons to run it again: the camera resolution changes (these were chosen on
640px frames), the robot's speed changes, or a strength is being retuned.
"""

import argparse
from pathlib import Path

import cv2

from vision_ai.tooling.augmentation_preview.preview import (
    frames_from_dataset, read_images, tile,
)
from vision_ai.utils.augmentation import primitives

# One ladder per effect: the caption template, the primitive, and the settings
# to walk. Ladders deliberately run past what any recipe uses, so the sheet
# shows where the effect stops being usable.
LADDERS = {
    "blur": ("motion_blur {ksize}px", "add_motion_blur",
             [dict(ksize=k, angle=18) for k in (9, 15, 21, 25, 31, 45, 70)]),
    "dark": ("gamma_brightness f={factor} g={gamma}", "gamma_brightness",
             [dict(factor=f, gamma=g) for f, g in
              ((0.8, 1.0), (0.6, 1.1), (0.5, 1.2), (0.4, 1.3), (0.3, 1.4))]),
    "frost": ("frost cov={coverage_ratio} t={temperature_delta}",
              "generate_frost_overlay_chunky",
              [dict(coverage_ratio=c, temperature_delta=t, seed=7, n_anchors=4)
               for c, t in ((0.15, 0.30), (0.30, 0.40), (0.45, 0.55), (0.60, 0.70))]),
}


def render_ladder(frame, effect_name: str, out_dir: Path) -> Path:
    """Write the strength ladder for one effect and return the path."""
    if effect_name not in LADDERS:
        raise ValueError(f"unknown effect: {effect_name}")
    caption, function, settings = LADDERS[effect_name]
    effect = getattr(primitives, function)

    panels = [("original", frame)]
    for kwargs in settings:
        panels.append((caption.format(**kwargs), effect(frame.copy(), **kwargs)))
    panels = [(text, cv2.cvtColor(image, cv2.COLOR_RGB2BGR)) for text, image in panels]

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"_sweep_{effect_name}.png"
    cv2.imwrite(str(target), tile(panels, columns=4))
    return target


def build_parser() -> argparse.ArgumentParser:
    """Define the command line: which frame, and which effect to walk."""
    parser = argparse.ArgumentParser(
        description="Render an augmentation effect at rising strength")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--images", type=Path, help="Directory of source frames")
    source.add_argument("--dataset", type=Path,
                        help="Merged dataset root; picks a valid frame with a fallen person")
    parser.add_argument("--out", type=Path, required=True, help="Where to write the sheet")
    parser.add_argument("--effect", choices=sorted(LADDERS), required=True)
    parser.add_argument("--posture", default="fallen",
                        help="Posture to prefer when picking from --dataset")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Render the requested ladder and print where it was written."""
    args = build_parser().parse_args(argv)
    source = args.images or frames_from_dataset(args.dataset, limit=1, posture=args.posture)
    frame = cv2.cvtColor(read_images(source, 1)[0][1], cv2.COLOR_BGR2RGB)
    print(render_ladder(frame, args.effect, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
