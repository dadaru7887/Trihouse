# Training the perception model on the server

Steps 0-5 are one-time setup, 6 onwards is the run. Every command is run from
the repo root.

## 0. Get the code

```bash
git clone <repo-url> Trihouse
cd Trihouse
git checkout dev
```

## 1. Environment

```bash
conda create -n trihouse-vision python=3.10 -y
conda activate trihouse-vision

# Install the same CUDA 12.8 PyTorch wheels as the inference Docker image.
# The NVIDIA driver must support CUDA 12.8; confirm it with `nvidia-smi` first.
python -m pip install --upgrade pip
python -m pip install \
    torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 \
    --index-url https://download.pytorch.org/whl/cu128

pip install ultralytics albumentations opencv-python pillow \
            scikit-learn pandas pyyaml joblib roboflow wandb lap
```

Verify the GPU is visible before going further:

```bash
python - <<'PY'
import torch
import torchvision

print("torch      :", torch.__version__)
print("torchvision:", torchvision.__version__)
print("CUDA build :", torch.version.cuda)
print("CUDA ready :", torch.cuda.is_available())
print("GPU        :", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "NOT DETECTED")
PY
```

`--device auto` picks CUDA when it is there, then MPS, then CPU. If this
prints `False`, training will silently fall back to CPU.

## 2. Weights & Biases

```bash
wandb login          # paste the key from wandb.ai/authorize
```

Skip it if you do not want tracking. Metrics are written to `metrics.jsonl`
in the run directory either way.

## 3. Download and merge the dataset

Both Roboflow projects are pulled and merged by one command. It needs the
Roboflow API key the first time; drop `--api-key` to re-merge an existing
download.

```bash
python -m vision_ai.data_loader.perception.roboflow_merge \
    --api-key <ROBOFLOW_API_KEY> \
    --out data/pinky_camera \
    --split-from-export fallen --merged-name merged_export_split
```

What it does:

| | |
|---|---|
| downloads | `trihouse` v7 (obstacle/person) and `trihouse_detect_fallen` v2 (Fallen/Obstacle/Standing) into `data/pinky_camera/{segmentation,fallen}` |
| remaps | Fallen and Standing both become `person`; segmentation only needs obstacle vs person |
| splits | by **episode**, copied from the fallen export, so YOLOE and the fall classifier share one split (test: 162744, 171506) |
| writes | `data/pinky_camera/merged_export_split/` with `data.yaml`, train/valid/test, `posture_manifest.csv`, `merge_report.json` |

Expected result: 672 images, train 462 / valid 92 / test 118.

Without `--split-from-export` the episodes are drawn with `--seed` into
`merged/`. That split puts 162744 in train, so weights trained on it must not
be scored on the fallen export's test.

## 4. Check the dataset before spending GPU hours

```bash
python -m vision_ai.models.perception.trainer.pipeline preflight \
    --data data/pinky_camera/merged_export_split/data.yaml \
    --posture-manifest data/pinky_camera/merged_export_split/posture_manifest.csv \
    --output runs/preflight_check
```

This refuses a dataset that cannot be scored: missing labels, orphan labels,
polygons outside 0..1, duplicate images across splits, or fewer than 10
confirmed fallen frames in valid or test. It prints a fingerprint that
identifies the exact dataset a run trained on.

## 5. Base weights (login node, once)

Compute nodes may have no internet. Training loads `yoloe-26s-seg.pt` and the
text encoder `mobileclip2_b.ts` from the repo root, so fetch both there first:

```bash
python - <<'PY'
from ultralytics import YOLOE
model = YOLOE("yoloe-26s-seg.pt")
model.set_classes(["obstacle", "person"], model.get_text_pe(["obstacle", "person"]))
PY
ls yoloe-26s-seg.pt mobileclip2_b.ts
```

Optional: look at the augmentation you are about to train with.

```bash
python -m vision_ai.tooling.augmentation_preview.preview \
    --dataset data/pinky_camera/merged_export_split --out runs/augmentation_preview --all-groups
```

## 6. Train YOLOE and compare fall features A/B/C (one job)

```bash
# merge if missing -> preflight -> YOLOE multi-seed (augmented) -> compare gt -> compare predicted
sbatch --time=2-12:00:00 --gres=gpu:1 scripts/vision_ai/fall_feature_compare.sh

# YOLOE already trained: compare only
sbatch --time=02:00:00 --gres=gpu:1 scripts/vision_ai/fall_feature_compare.sh \
    experiments/<stamp>/selected_model.json

squeue -u $USER                      # job state
tail -f slurm-<jobid>.out            # live log
```

The YOLOE run is configured by
`vision_ai/models/perception/trainer/configs/config.yaml`: seeds
17/42/101/2026/3407, 200 epochs, augmentation on, validation gate mask recall
0.80 / mAP50 0.60, selection on person mask mAP50-95. Change the experiment
there, not in the script.

Results:

```
experiments/<stamp>/
    selected_model.json              chosen weights and why
    aggregate.json, seed_results.csv per-seed and mean/std
    seed_<n>/                        each seed's run, log, weights, metrics
    seed_<n>/augmented_samples/      10 actual training inputs per recipe,
                                     original | augmented, named by recipe id
    analysis/                        plots across seeds
runs/fall_compare/<stamp>/{gt,predicted}/
    report.md                        tables; E3 (1 s confirm) and E4 (5 s
                                     escalation, gt only) at the end
    report.json, rows.jsonl          every number and every row
    cases/*.png                      representative cases
```

Keep `selected_model.json`, the seed's `best.pt` and `merge_report.json`
together: weights are useless later without knowing which split produced them.

## 7. Score the trained model under degradation

```bash
python -m vision_ai.models.perception.trainer.corruption_eval \
    --run-dir experiments/<stamp>/seed_<n> --split test --all
python -m vision_ai.models.perception.trainer.corruption_eval \
    --run-dir experiments/<stamp>/seed_<n> --split test --per-recipe
```

Read the tiers weakest first: S1-S4 are in-distribution, `seen_compound` is
trained effects in a new combination, `unseen` and `unseen_compound` are
implementations training never ran. Report clean alongside all of them.

## 8. Leave-one-out, to show a mechanism is doing work

One seed, with every recipe that can produce the mechanism removed:

```bash
python -m vision_ai.models.perception.trainer.pipeline run \
    --data data/pinky_camera/merged_export_split/data.yaml \
    --posture-manifest data/pinky_camera/merged_export_split/posture_manifest.csv \
    --seed 42 --augmentation --holdout frost
```

## 9. Fall classifier for deployment

Build the feature JSONL from the selected YOLOE's masks, then train the bundle
the robot loads (`FALLEN_CLASSIFIER_BUNDLE` / `FALLEN_CLASSIFIER_SHA256`).

```bash
python -m vision_ai.data_loader.fall.build_features \
    --export data/pinky_camera/fallen --merged data/pinky_camera/merged_export_split \
    --out runs/fall/features_predicted.jsonl \
    --masks predicted --weights experiments/<stamp>/selected_model.json

python -m vision_ai.models.perception.trainer.fall_trainer \
    --dataset runs/fall/features_predicted.jsonl --out runs/fall \
    --seed 42 --min-recall 0.85
```

## 10. VLM prompt comparison (after step 6)

Runs every prompt version in `vision_ai/robot/configs/vlm_prompts.yaml` on the
same frames, the same YOLOE detections and the same Qwen settings. Needs a GPU
with about 8 GB free and the VLM packages of the inference image:

```bash
pip install transformers==4.53.2 accelerate==1.8.1 bitsandbytes==0.46.1 qwen-vl-utils==0.0.11

python -m vision_ai.tooling.vlm_prompt_compare \
    --dataset data/pinky_camera/merged_export_split --split valid \
    --weights experiments/<stamp>/selected_model.json \
    --out runs/vlm_prompt_compare/valid                 # all versions (current, v1); --versions v1 for one
```

| file | what it is |
|---|---|
| `detections.jsonl` | per frame: YOLOE detections (region_id, ByteTrack track_id, box) and the labelled objects matched to them. Built once, reused |
| `responses.jsonl` | per frame and version: raw answer, parsed answer, truncated, tokens, seconds. A rerun skips what is there |
| `review.csv` | one row per labelled object: every version's risk/evidence and `risk_label` (pre-filled from `--draft-version`, v1 by default) to correct |
| `overlays/` | each frame with labelled objects (green, g1..) and detections (orange, r1 #track) |
| `summary.json` | per version: JSON valid rate, truncated, regions left unanswered |

`risk_label` starts as v1's answer (v1 is the prompt written to the risk
criteria); go through every row against `overlays/` and the image and correct
it. A row left unchecked keeps v1's answer and scores in v1's favour, so write
what you checked in `label_note`.

Tune prompts on valid only. Decide the versions before opening test, then run
test once with `--split test` and review it the same way.

The robot picks the version with `--prompt-version` (or `VLM_PROMPT_VERSION`):

```bash
python -m vision_ai.robot.recovery.runtime --prompt-version current
```
