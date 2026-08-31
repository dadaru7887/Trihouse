"""Render what each augmentation recipe does to a real frame, for eyeballing.

Calls `vision_ai/utils/augmentation`, the same code training uses, so the
reviewed image is the trained image.

    # one sheet per source frame, original plus one draw from every group
    python -m vision_ai.tooling.augmentation_preview.preview \
        --images data/pinky_camera/merged/valid/images --out runs/preview --limit 4

    # every recipe in one group, side by side
    python -m vision_ai.tooling.augmentation_preview.preview \
        --images ... --out runs/preview --group S2

Flow: read source images -> apply the chosen recipes -> write one PNG per
source image with the original and its variants tiled side by side.

Output is a review artefact, not a dataset. Nothing reads it back.
"""

from __future__ import annotations

import argparse
from pathlib import Path

# Grid geometry: one column for the original, the rest for variants.
COLUMN_WIDTH = 320


def _read_images(images_dir: Path, limit: int) -> list[tuple[str, "object"]]:
    """Load up to `limit` images from a directory, sorted by name."""
    import cv2

    found = []
    for path in sorted(Path(images_dir).iterdir()):
        if path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        image = cv2.imread(str(path))
        if image is not None:
            found.append((path.stem, image))
        if len(found) >= limit:
            break
    if not found:
        raise ValueError(f"no readable images under {images_dir}")
    return found


def _label(image, text: str):
    """Burn a caption into the top-left corner so tiles stay identifiable."""
    import cv2

    out = image.copy()
    # Dark strip behind the text; the frames are often bright enough to hide it.
    cv2.rectangle(out, (0, 0), (out.shape[1], 26), (0, 0, 0), -1)
    cv2.putText(out, text, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1,
                cv2.LINE_AA)
    return out


def _tile(panels: list[tuple[str, "object"]]):
    """Scale every panel to a common width and lay them out in one row."""
    import cv2
    import numpy as np

    scaled = []
    for caption, image in panels:
        height = int(image.shape[0] * COLUMN_WIDTH / image.shape[1])
        scaled.append(_label(cv2.resize(image, (COLUMN_WIDTH, height)), caption))
    tallest = max(panel.shape[0] for panel in scaled)
    # Pad shorter panels so hstack gets a uniform height.
    padded = [np.pad(p, ((0, tallest - p.shape[0]), (0, 0), (0, 0))) for p in scaled]
    return np.hstack(padded)


def render(images_dir: Path, out_dir: Path, group: str | None = None,
           limit: int = 4, seed: int = 42) -> list[Path]:
    """Write one comparison PNG per source image and return the paths.

    With `group` set, the row shows every recipe in that group. Without it,
    it shows one draw from each group, training and evaluation alike.
    """
    import cv2

    from vision_ai.utils.augmentation import scenarios

    if group is not None and group not in scenarios.GROUPS:
        raise ValueError(f"unknown group: {group}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for name, image in _read_images(Path(images_dir), limit):
        # Reseed per image so the same source always yields the same sheet.
        scenarios.configure_augmentation_seed(seed)
        panels = [("original", image)]
        if group is None:
            panels += [(g, scenarios.apply_group(image, g)) for g in scenarios.GROUPS]
        else:
            panels += [(recipe.id, scenarios.apply_recipe(image, recipe.id))
                       for recipe in scenarios.recipes_in(group)]
        target = out_dir / f"{name}__{group or 'all'}.png"
        cv2.imwrite(str(target), _tile(panels))
        written.append(target)
    return written


def build_parser() -> argparse.ArgumentParser:
    """Define the command line: source frames, output directory, which group."""
    parser = argparse.ArgumentParser(
        description="Render augmentation recipes over real frames for review")
    parser.add_argument("--images", type=Path, required=True, help="Directory of source frames")
    parser.add_argument("--out", type=Path, required=True, help="Where to write the sheets")
    parser.add_argument("--group", help="S1..S4, seen_compound, unseen, unseen_compound; "
                                        "omit to show one draw from each")
    parser.add_argument("--limit", type=int, default=4, help="How many source frames to render")
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Render the sheets and print where each was written."""
    args = build_parser().parse_args(argv)
    written = render(args.images, args.out, group=args.group,
                     limit=args.limit, seed=args.seed)
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
