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
            scikit-learn pandas pyyaml joblib roboflow wandb
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

Skip it if you do not want tracking, and drop `--wandb` below. Metrics are
written to `metrics.jsonl` in the run directory either way.

## 3. Download and merge the dataset

Both Roboflow projects are pulled and merged by one command. It needs the
Roboflow API key.

```bash
python -m vision_ai.data_loader.perception.roboflow_merge \
    --api-key <ROBOFLOW_API_KEY> \
    --out data/pinky_camera \
    --seed 42
```

What it does:

| | |
|---|---|
| downloads | `trihouse` v7 (obstacle/person) and `trihouse_detect_fallen` v2 (Fallen/Obstacle/Standing) |
| remaps | Fallen and Standing both become `person`; segmentation only needs obstacle vs person |
| splits | by **episode**, never by frame -- adjacent frames of one video are near identical, so a frame split measures memorisation |
| writes | `data/pinky_camera/merged/` with `data.yaml`, train/valid/test, `posture_manifest.csv`, `merge_report.json` |

The posture manifest carries fallen/standing per frame. Preflight counts the
fallen samples in each eval split from it, and the fall classifier needs it.

Expected result with seed 42: 672 images, train 440 / valid 109 / test 123,
163 fallen frames, two episodes in each of valid and test.

Re-running with the same seed reproduces the same split. A different seed
gives a different one, so record which seed produced the weights.

## 4. Check the dataset before spending GPU hours

```bash
python -m vision_ai.models.perception.trainer.pipeline preflight \
    --data data/pinky_camera/merged/data.yaml \
    --posture-manifest data/pinky_camera/merged/posture_manifest.csv \
    --output runs/preflight_check
```

This refuses a dataset that cannot be scored: missing labels, orphan labels,
polygons outside 0..1, duplicate images across splits, or fewer than 10
confirmed fallen frames in valid or test. It prints a fingerprint that
identifies the exact dataset a run trained on.

## 5. Look at the augmentation you are about to train with

```bash
python -m vision_ai.tooling.augmentation_preview.preview \
    --dataset data/pinky_camera/merged --out runs/augmentation_preview --all-groups

python -m vision_ai.tooling.augmentation_preview.preview \
    --dataset data/pinky_camera/merged --out runs/augmentation_preview --severity
```

Training draws uniformly from 16 single-mechanism recipes; the eval tiers are
never drawn during training. See
`vision_ai/tooling/augmentation_preview/README.md` for what to look for.

## 6. Train

```bash
sh scripts/vision_ai/perception_model.sh data/pinky_camera/merged/data.yaml 42
```

Or directly, which is what the script runs:

```bash
python -m vision_ai.models.perception.trainer.pipeline run \
    --data data/pinky_camera/merged/data.yaml \
    --posture-manifest data/pinky_camera/merged/posture_manifest.csv \
    --run-root runs/perception \
    --seed 42 --epochs 200 --device auto \
    --augmentation --wandb --wandb-project trihouse-vision
```

Stages, in order: preflight -> train -> validation -> **validation gate** ->
test. The gate stops the run before test when person mask recall or mAP50 is
below the floor, so test stays unopened on a model that was not going to be
used. Defaults are recall 0.90 and mAP50 0.80; lower them with
`--min-mask-recall` / `--min-mask-map50` if the run should proceed anyway.

Watch it with:

```bash
tail -f runs/perception/*/run.log
```

## 7. Score the trained model under degradation

```bash
# every group plus clean
python -m vision_ai.models.perception.trainer.corruption_eval \
    --run-dir runs/perception/<run> --split test --all

# every recipe, for severity curves
python -m vision_ai.models.perception.trainer.corruption_eval \
    --run-dir runs/perception/<run> --split test --per-recipe
```

Read the tiers weakest first: S1-S4 are in-distribution, `seen_compound` is
trained effects in a new combination, `unseen` and `unseen_compound` are
implementations training never ran. Report clean alongside all of them.

## 8. Leave-one-out, to show a mechanism is doing work

```bash
sh scripts/vision_ai/perception_model.sh data/pinky_camera/merged/data.yaml 42 200 frost
```

Trains with every recipe that can produce frost removed, compounds included,
then scores on group S4. One run per mechanism you want to report on.

## 9. Fall classifier

**Not runnable yet**: it needs a feature JSONL, and no adapter turns the
merged dataset's polygons into one. Once that exists:

```bash
python -m vision_ai.models.perception.trainer.fall_trainer \
    --dataset runs/fall/features.jsonl --out runs/fall \
    --seed 42 --min-recall 0.85 --wandb
```

## What a finished run leaves behind

```
runs/perception/<timestamp>_<model>_aug/
    run.log                          every stage, the device, the gate decision
    metrics.jsonl                    all metrics, with or without wandb
    status.json                      RUNNING / COMPLETED / FAILED and where
    config/resolved.json             the exact config, device already resolved
    environment.json                 torch, CUDA, GPU, dataset fingerprint
    preflight/dataset_report.json    label counts and split composition
    train/weights/best.pt            <- the weights
    evaluation/validation_metrics.json
    evaluation/test_metrics.json
    artifact_manifest.json           weights + fingerprint + gate result
```

Keep `best.pt`, `artifact_manifest.json` and `merge_report.json` together: the
first is useless later without knowing which dataset split produced it.
