"""Review the augmentation before training on it: render it, and measure it.

Calls `vision_ai/utils/augmentation`, the same code training uses, so what you
review here is what the model actually sees.

    # every sheet: an overview plus one per group
    python -m vision_ai.tooling.augmentation_preview.preview \
        --dataset data/pinky_camera/merged --out runs/augmentation_preview --all-groups

    # how hard each recipe hits, averaged over several frames
    python -m vision_ai.tooling.augmentation_preview.preview \
        --dataset data/pinky_camera/merged --out runs/augmentation_preview --severity

    # one effect at rising strength, for picking a setting by eye
    python -m vision_ai.tooling.augmentation_preview.preview \
        --dataset data/pinky_camera/merged --out runs/augmentation_preview --sweep blur

Flow: pick source frames -> apply the chosen recipes -> write a PNG tiling the
original beside its variants, or print the severity table.

Two failures the severity numbers catch, both of which happened here: a recipe
that changes nothing scores like a free win, and a recipe that erases the
subject teaches nothing and cannot be annotated either. What they cannot catch
is whether the result looks like a warehouse -- that is what the sheets are for.

Output is a review artefact, not a dataset. Nothing reads it back.
"""

from __future__ import annotations

import argparse
from pathlib import Path

# Grid geometry: panel width in pixels, and how many before wrapping to a new row.
COLUMN_WIDTH = 320
COLUMNS = 5

# A change smaller than this is below what matters visually, so it is not
# counted as "the frame moved here".
JND = 12
SAMPLE_FRAMES = 8


# ------------------------------------------------------------------ input --

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
    valid = [row for row in rows if row["image"].startswith("valid")]
    wanted = [row for row in valid if row.get("posture") == posture] or valid
    if not wanted:
        raise ValueError(f"no valid-split frames listed in {manifest}")
    return [root / row["image"] for row in wanted[:limit]]


def _read_images(source, limit: int) -> list[tuple[str, "object"]]:
    """Load up to `limit` frames from a directory, or from a list of paths."""
    import cv2

    if isinstance(source, (str, Path)):
        paths = [path for path in sorted(Path(source).iterdir())
                 if path.suffix.lower() in (".jpg", ".jpeg", ".png")]
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


# ----------------------------------------------------------------- sheets --

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


def render_all_groups(source, out_dir: Path, seed: int = 42) -> list[Path]:
    """Write the whole review set: an overview sheet plus one sheet per group.

    Sheets are named by group so the directory reads in order, which is what
    a reviewer wants when checking whether any condition went too far.
    """
    from vision_ai.utils.augmentation import scenarios

    for path in render(source, out_dir, seed=seed, limit=1):
        path.rename(path.with_name("00_overview.png"))   # the mixed sheet leads
    result = [Path(out_dir) / "00_overview.png"]
    for group in scenarios.GROUPS:
        for path in render(source, out_dir, group=group, seed=seed, limit=1):
            target = path.with_name(f"{group}.png")
            path.rename(target)
            result.append(target)
    return result


# --------------------------------------------------------------- severity --

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


def severity_report(frames) -> str:
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


# Strength ladders for the effects whose settings needed judging by eye.
SWEEPS = {
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


def sweep(frame, name: str, out_dir: Path) -> Path:
    """Render one effect at rising strength, for picking a setting by eye."""
    import cv2

    from vision_ai.utils.augmentation import primitives

    caption, function, settings = SWEEPS[name]
    effect = getattr(primitives, function)
    panels = [("original", frame)]
    for kwargs in settings:
        panels.append((caption.format(**kwargs), effect(frame.copy(), **kwargs)))
    panels = [(text, cv2.cvtColor(image, cv2.COLOR_RGB2BGR)) for text, image in panels]

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"_sweep_{name}.png"
    cv2.imwrite(str(target), _tile(panels, columns=4))
    return target


# -------------------------------------------------------------------- cli --

def build_parser() -> argparse.ArgumentParser:
    """Define the command line: which frames, and sheets or severity or sweep."""
    parser = argparse.ArgumentParser(
        description="Render and measure augmentation recipes on real frames")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--images", type=Path, help="Directory of source frames")
    source.add_argument("--dataset", type=Path,
                        help="Merged dataset root; picks a valid frame with a fallen person")
    parser.add_argument("--out", type=Path, required=True, help="Where to write the output")
    parser.add_argument("--group", help="S1..S4, seen_compound, unseen, unseen_compound; "
                                        "omit to show one draw from each")
    parser.add_argument("--all-groups", action="store_true",
                        help="Write the overview and every group sheet in one run")
    parser.add_argument("--severity", action="store_true",
                        help="Print the per-recipe severity table instead of sheets")
    parser.add_argument("--sweep", choices=sorted(SWEEPS),
                        help="Render a strength ladder for one effect instead of sheets")
    parser.add_argument("--posture", default="fallen",
                        help="Posture to prefer when picking from --dataset")
    parser.add_argument("--limit", type=int, default=4, help="How many source frames to use")
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the requested mode and print what was written."""
    import cv2

    args = build_parser().parse_args(argv)
    # The severity table averages over several frames; the sheets use --limit.
    count = SAMPLE_FRAMES if args.severity else args.limit
    source = (args.images if args.images
              else frames_from_dataset(args.dataset, limit=count, posture=args.posture))

    if args.sweep:
        rgb = cv2.cvtColor(_read_images(source, 1)[0][1], cv2.COLOR_BGR2RGB)
        print(sweep(rgb, args.sweep, args.out))
    elif args.severity:
        rgb = [cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
               for _, image in _read_images(source, count)]
        text = severity_report(rgb)
        target = Path(args.out) / "severity.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
        print(text)
        print(f"\nwritten to {target}")
    elif args.all_groups:
        for path in render_all_groups(source, args.out, seed=args.seed):
            print(path)
    else:
        for path in render(source, args.out, group=args.group,
                           limit=args.limit, seed=args.seed):
            print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
