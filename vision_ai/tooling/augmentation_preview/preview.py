"""Render what each augmentation recipe does to a real frame, for eyeballing.

Calls `vision_ai/utils/augmentation`, the same code training uses, so the
reviewed image is the trained image.

    # the whole review set: an overview plus one sheet per group, on a frame
    # the merged dataset says holds a fallen person
    python -m vision_ai.tooling.augmentation_preview.preview \
        --dataset data/pinky_camera/merged --out runs/augmentation_preview --all-groups

    # one group from a plain directory of frames
    python -m vision_ai.tooling.augmentation_preview.preview \
        --images data/pinky_camera/merged/valid/images --out runs/preview --group S2

Flow: pick source frames -> apply the chosen recipes -> write one PNG per
source image with the original and its variants tiled side by side.

Output is a review artefact, not a dataset. Nothing reads it back.
"""

from __future__ import annotations

import argparse
from pathlib import Path

# Grid geometry: panel width in pixels, and how many before wrapping to a new row.
COLUMN_WIDTH = 320
COLUMNS = 5


def frames_from_dataset(root: Path, limit: int = 1, posture: str = "fallen"):
    """Pick source frames from a merged dataset, preferring the given posture.

    Reads posture_manifest.csv so the review frame actually contains what the
    model has to keep finding; a frame of empty floor hides what an effect
    does to a person. Falls back to any valid frame when none match.
    """
    import csv

    root = Path(root)
    manifest = root / "posture_manifest.csv"
    rows = list(csv.DictReader(manifest.open(encoding="utf-8")))
    valid = [r for r in rows if r["image"].startswith("valid")]
    wanted = [r for r in valid if r.get("posture") == posture] or valid
    if not wanted:
        raise ValueError(f"no valid-split frames listed in {manifest}")
    return [root / row["image"] for row in wanted[:limit]]


def _read_images(source, limit: int) -> list[tuple[str, "object"]]:
    """Load up to `limit` frames from a directory, or from a list of paths."""
    import cv2

    if isinstance(source, (str, Path)):
        paths = [p for p in sorted(Path(source).iterdir())
                 if p.suffix.lower() in (".jpg", ".jpeg", ".png")]
    else:
        paths = list(source)

    found = []
    for path in paths:
        image = cv2.imread(str(path))
        if image is not None:
            found.append((path.stem, image))
        if len(found) >= limit:
            break
    if not found:
        raise ValueError(f"no readable images in {source}")
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


def _tile(panels: list[tuple[str, "object"]], columns: int = COLUMNS):
    """Scale every panel to a common size and lay them out in a grid.

    A single row would be thousands of pixels wide once a group has more than
    a handful of recipes, so panels wrap after `columns`.
    """
    import cv2
    import numpy as np

    scaled = []
    for caption, image in panels:
        height = int(image.shape[0] * COLUMN_WIDTH / image.shape[1])
        scaled.append(_label(cv2.resize(image, (COLUMN_WIDTH, height)), caption))
    cell_h = max(panel.shape[0] for panel in scaled)
    # Pad every panel to one cell size so the rows stack cleanly.
    cells = [np.pad(p, ((0, cell_h - p.shape[0]), (0, 0), (0, 0))) for p in scaled]
    blank = np.zeros((cell_h, COLUMN_WIDTH, 3), dtype=cells[0].dtype)
    rows = []
    for start in range(0, len(cells), columns):
        row = cells[start:start + columns]
        row += [blank] * (columns - len(row))       # pad the last row
        rows.append(np.hstack(row))
    return np.vstack(rows)


def render_all_groups(source, out_dir: Path, seed: int = 42) -> list[Path]:
    """Write the whole review set: an overview sheet plus one sheet per group.

    Sheets are named by group so the directory reads in order, which is what
    a reviewer wants when checking whether any condition went too far.
    """
    from vision_ai.utils.augmentation import scenarios

    written = render(source, out_dir, seed=seed, limit=1)
    for path in written:                       # the mixed sheet leads the set
        path.rename(path.with_name("00_overview.png"))
    result = [Path(out_dir) / "00_overview.png"]
    for group in scenarios.GROUPS:
        for path in render(source, out_dir, group=group, seed=seed, limit=1):
            target = path.with_name(f"{group}.png")
            path.rename(target)
            result.append(target)
    return result


def render(source, out_dir: Path, group: str | None = None,
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
    for name, image in _read_images(source, limit):
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
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--images", type=Path, help="Directory of source frames")
    source.add_argument("--dataset", type=Path,
                        help="Merged dataset root; picks a valid frame with a fallen person")
    parser.add_argument("--out", type=Path, required=True, help="Where to write the sheets")
    parser.add_argument("--group", help="S1..S4, seen_compound, unseen, unseen_compound; "
                                        "omit to show one draw from each")
    parser.add_argument("--all-groups", action="store_true",
                        help="Write the overview and every group sheet in one run")
    parser.add_argument("--posture", default="fallen",
                        help="Posture to prefer when picking from --dataset")
    parser.add_argument("--limit", type=int, default=4, help="How many source frames to render")
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Render the sheets and print where each was written."""
    args = build_parser().parse_args(argv)
    source = (args.images if args.images
              else frames_from_dataset(args.dataset, limit=args.limit, posture=args.posture))
    if args.all_groups:
        written = render_all_groups(source, args.out, seed=args.seed)
    else:
        written = render(source, args.out, group=args.group,
                         limit=args.limit, seed=args.seed)
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
