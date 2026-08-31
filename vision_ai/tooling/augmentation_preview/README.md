# augmentation_preview

Look at the augmentation before training on it. Both commands call
`vision_ai/utils/augmentation`, the same code training uses, so what you see
here is what the model sees.

## preview.py -- check what is in use

Run whenever the recipes change.

```bash
# every sheet: an overview plus one per group, on a valid frame with a fallen person
python -m vision_ai.tooling.augmentation_preview.preview \
    --dataset data/pinky_camera/merged --out runs/augmentation_preview --all-groups

# how hard each recipe hits, averaged over 8 valid frames -> severity.txt
python -m vision_ai.tooling.augmentation_preview.preview \
    --dataset data/pinky_camera/merged --out runs/augmentation_preview --severity
```

## sweep.py -- choose a setting

Run once per decision. What it settles ends up in `scenarios.py` as a fixed
recipe parameter, and preview.py checks it from then on.

```bash
python -m vision_ai.tooling.augmentation_preview.sweep \
    --dataset data/pinky_camera/merged --out runs/augmentation_preview --effect blur
#   --effect dark | frost
```

Reasons to run it again: the camera resolution changes (the current values were
chosen on 640px frames), the robot's speed changes, or a strength is retuned.

`runs/` is gitignored: these are review artefacts, and nothing reads them back.

## What to look for

- **Is the subject still there?** A condition nobody could annotate teaches the
  model nothing and measures nothing. This is why motion blur is capped at
  25px: at 45px on a 640px frame the figures smear into streaks.
- **Does the effect exist at all?** `--severity` flags anything moving under 5%
  of the frame. A scoring recipe that changes nothing reports as a free win.
- **Does it look like the warehouse?** No number tells you this. An earlier
  eval effect matched the target severity exactly and rendered blowing sand;
  it was removed.
