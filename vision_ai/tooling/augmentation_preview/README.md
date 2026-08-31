# augmentation_preview

Reproduces the augmentation review set. Both commands call
`vision_ai/utils/augmentation`, the same code training uses, so what you look
at here is what the model actually sees.

```bash
# every sheet: an overview plus one per group, on a valid frame with a fallen person
python -m vision_ai.tooling.augmentation_preview.preview \
    --dataset data/pinky_camera/merged --out runs/augmentation_preview --all-groups

# how hard each recipe hits, averaged over 8 valid frames
python -m vision_ai.tooling.augmentation_preview.severity \
    --dataset data/pinky_camera/merged --out runs/augmentation_preview

# strength ladders, for picking a setting by eye
python -m vision_ai.tooling.augmentation_preview.severity \
    --dataset data/pinky_camera/merged --out runs/augmentation_preview --sweep blur
#   --sweep dark | frost
```

`runs/` is gitignored: these are review artefacts, and nothing reads them back.

## What to look for

- **Is the subject still there?** A condition nobody could annotate teaches
  the model nothing and measures nothing. This is why motion blur is capped at
  25px: at 45px on a 640px frame the figures smear into streaks.
- **Does the effect exist at all?** `severity` flags anything moving under 5%
  of the frame. A scoring recipe that changes nothing reports as a free win.
- **Does it look like the warehouse?** The number cannot tell you this. An
  earlier eval effect matched the target severity exactly and rendered blowing
  sand; it was removed.
