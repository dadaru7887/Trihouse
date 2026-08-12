# LEGO Worker YOLOE Training Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible, manually runnable and one-command YOLOE segmentation training pipeline for the LEGO `person` dataset, with dataset gates and artifacts suitable for the later fall/immobility monitor.

**Architecture:** Keep the existing augmentation implementation and YOLOE trainer, but put deterministic dataset auditing and run orchestration in a focused package under `vision_perception/test/worker-fall-detection`. Manual stage scripts call the same Python APIs as the all-in-one runner, so staged debugging and full runs cannot drift.

**Tech Stack:** Python 3.10+, PyYAML, OpenCV, NumPy, pytest, Ultralytics YOLOE, Bash, Docker/conda wrapper already used by `vision_perception/segmentation/train.sh`.

> Extension approved 2026-08-12: use Python 3.12 and PyTorch cu128 in `venv/yolo_segmentation`; add strict YAML config, environment snapshot, subprocess-isolated multi-seed aggregation/selection, and selected-weight realtime webcam/MP4 monitoring. Do not create Docker/Compose in this cycle.

## Global Constraints

- POC detects LEGO only; dataset class `person` is class ID 1.
- Dataset source is `/home/syw/Trihouse/dataset/raw_examples` and must not be modified.
- Existing S1-S5 augmentation behavior in `vision_perception/segmentation/train.py` remains available.
- Test split is never used for training, early stopping, or threshold selection.
- Missing confirmed fallen examples in validation/test is reported as `NOT_EVALUABLE`; training requires explicit `--allow-posture-gap` until a posture manifest satisfies the gate.
- The pipeline must support stage-by-stage manual execution and one-command execution.

---

### Task 1: Dataset audit and posture candidate artifacts

**Files:**
- Create: `vision_perception/test/worker-fall-detection/pipeline/__init__.py`
- Create: `vision_perception/test/worker-fall-detection/pipeline/dataset_audit.py`
- Create: `vision_perception/test/worker-fall-detection/tests/test_dataset_audit.py`

**Interfaces:**
- Produces: `audit_dataset(data_yaml: Path, output_dir: Path, posture_manifest: Path | None, allow_posture_gap: bool) -> DatasetReport`
- Produces: JSON-serializable `DatasetReport` and `DatasetAuditError`.

- [ ] Write failing tests using temporary YOLO polygon datasets for valid input, invalid coordinates/class IDs, missing pairs, cross-split duplicate content, empty labels and missing posture coverage.
- [ ] Run `python3 -m pytest -q vision_perception/test/worker-fall-detection/tests/test_dataset_audit.py` and confirm failures are caused by the missing module.
- [ ] Implement YAML resolution, polygon validation, SHA-256 split leak detection, instance statistics, posture manifest validation and deterministic JSON/CSV artifacts.
- [ ] Run the focused tests and confirm they pass.
- [ ] Run preflight against `dataset/raw_examples/data.yaml`; confirm the dataset structure passes while posture coverage reports `NOT_EVALUABLE`.

### Task 2: Reproducible training run configuration and lifecycle

**Files:**
- Create: `vision_perception/test/worker-fall-detection/pipeline/run_config.py`
- Create: `vision_perception/test/worker-fall-detection/pipeline/orchestrator.py`
- Create: `vision_perception/test/worker-fall-detection/tests/test_orchestrator.py`

**Interfaces:**
- Produces: immutable `TrainingConfig` with model/data/augmentation/epochs/imgsz/patience/batch/device/workers/seed/run_root/name/preflight flags.
- Produces: `run_pipeline(config: TrainingConfig, backend: TrainingBackend) -> Path`.
- Consumes: `audit_dataset(...)` from Task 1.

- [ ] Write failing tests showing deterministic resolved config, dataset fingerprint, `RUNNING`→`COMPLETED` status, `FAILED` stage recording, validation-before-test ordering, and artifact manifest content.
- [ ] Run focused tests and confirm the missing implementation causes the failure.
- [ ] Implement run directory creation, metadata capture, status lifecycle, backend protocol, validation gate and artifact manifest.
- [ ] Run focused tests and confirm they pass.

### Task 3: YOLOE backend adapter and existing training compatibility

**Files:**
- Create: `vision_perception/test/worker-fall-detection/pipeline/yoloe_backend.py`
- Modify: `vision_perception/segmentation/train.py`
- Create: `vision_perception/test/worker-fall-detection/tests/test_yoloe_backend.py`

**Interfaces:**
- Produces: `YOLOEBackend.train(config, run_dir) -> Path` and `YOLOEBackend.evaluate(weights, split, config, run_dir) -> dict[str, float]`.
- Reuses: `resolve_model`, `mixed_augmentation`, and `YOLOEPESegTrainer` behavior from the existing training path.

- [ ] Write failing adapter tests with a narrow fake model factory, asserting concrete train/val arguments and normalized box/mask metrics.
- [ ] Run focused tests and verify the failure.
- [ ] Refactor only the callable training helpers needed by the adapter while keeping the old `train.py` CLI operational.
- [ ] Implement lazy Ultralytics imports, validation and test metric normalization, and checkpoint existence checks.
- [ ] Run focused tests and the existing `train.py --help` smoke check.

### Task 4: Manual stage commands and all-in-one runners

**Files:**
- Create: `vision_perception/test/worker-fall-detection/preflight.py`
- Create: `vision_perception/test/worker-fall-detection/train_stage.py`
- Create: `vision_perception/test/worker-fall-detection/evaluate_stage.py`
- Create: `vision_perception/test/worker-fall-detection/run_pipeline.py`
- Create: `vision_perception/test/worker-fall-detection/run_pipeline.sh`
- Create: `vision_perception/test/worker-fall-detection/tests/test_cli.py`

**Interfaces:**
- Manual commands operate on an explicit run directory and exchange resolved JSON artifacts.
- All-in-one Python CLI calls the same `run_pipeline` API.
- Shell wrapper mirrors the existing container/conda delegation pattern.

- [ ] Write failing subprocess tests for `--help`, preflight-only success, posture-gap refusal and explicit override.
- [ ] Run CLI tests and confirm the expected failures.
- [ ] Implement shared argument parsing and manual stage entry points.
- [ ] Implement one-command Python runner and executable shell wrapper.
- [ ] Run CLI tests, syntax checks and preflight-only command on the real dataset.

### Task 5: Operator guide and complete verification

**Files:**
- Create: `vision_perception/test/worker-fall-detection/README.md`
- Modify: `vision_perception/segmentation/PINKY_SEGMENTATION_PIPELINE.md`
- Modify: `docs/superpowers/lego_worker_fall_detection_plan.md`

**Interfaces:**
- Documents exact manual stage commands, all-in-one commands, output interpretation, posture gap remediation, GPU smoke run and full training run.

- [ ] Document dataset status, stage-by-stage workflow and one-command workflow with exact paths.
- [ ] Document `--allow-posture-gap` as detection-only evidence, not fall validation.
- [ ] Run the complete focused pytest suite.
- [ ] Run `bash -n` on all shell files and `python3 -m compileall` on new Python code.
- [ ] Run real-dataset preflight and inspect its JSON/CSV outputs.
- [ ] Review all diffs for unrelated changes and verify the original dataset is unchanged.

### Task 6: Strict YAML configuration and environment snapshot

**Files:** `configs/config.yaml`, `pipeline/config_loader.py`, `pipeline/environment.py`, corresponding tests.

- [ ] Test unknown-key/type rejection, path resolution and resolved config.
- [ ] Implement Python/GPU/driver/CUDA/package/dataset/Git capture and RTX 5080 `sm_120` gate.

### Task 7: Python 3.12 cu128 venv workflow

**Files:** `requirements/*.txt`, `setup_venv.sh`, updated shell runners.

- [ ] Make `venv/yolo_segmentation/bin/python` the only shell-runner interpreter.
- [ ] Install PyTorch from the cu128 index before origin/env-compatible YOLO dependencies.

### Task 8: Multi-seed aggregation and deployment selection

**Files:** `train_seed.py`, `train_multi_seed.py`, `pipeline/multi_seed.py`, tests.

- [ ] Spawn each seed with `PYTHONHASHSEED`.
- [ ] Report every successful seed test metric as mean±sample-std/min/max.
- [ ] Select deployment weights using validation only and write `selected_model.json`.

### Task 9: Existing-weight realtime webcam/MP4 monitor

**Files:** `realtime.py`, `runtime/*.py`, `configs/realtime.yaml`, tests.

- [ ] Load selected/artifact/direct weights and track `person` masks.
- [ ] Compute posture/motion features and explicit state transitions.
- [ ] Emit one JSONL candidate per episode and support webcam/MP4 source semantics.

### Task 10: Automatic CUDA/CPU device resolution

**Files:**
- Create: `vision_perception/test/worker-fall-detection/pipeline/device.py`
- Modify: `pipeline/config_loader.py`, `pipeline/orchestrator.py`, `pipeline/yoloe_backend.py`
- Modify: `configs/config.yaml`, `configs/realtime.yaml`, `realtime.py`, `README.md`
- Test: `tests/test_device.py`, `tests/test_config_environment.py`, `tests/test_yoloe_backend.py`

**Interfaces:**
- Produces: `resolve_device(requested: str, torch_module=None) -> DeviceSelection`.
- `DeviceSelection.resolved` is `"0"` for auto-selected CUDA and `"cpu"` otherwise. `gpu`/`cuda` require GPU 0; numeric and `cuda:N` values require that exact GPU and never fall back.
- Environment validation consumes the resolved selection and gates CUDA 12.8/`sm_120` only when the selected GPU is RTX 5080.

- [ ] Write failing tests for auto CUDA, auto CPU, explicit device preservation and CPU environment acceptance.
- [ ] Run focused tests and confirm failure due to the missing resolver/old CUDA requirement.
- [ ] Implement the resolver and pass its resolved value to training/evaluation/realtime inference.
- [ ] Record requested/resolved device and reason in `environment.json` and run metadata.
- [ ] Change both YAML defaults to `auto` and document CPU smoke commands.
- [ ] Run the complete suite in `venv/yolo_segmentation`, shell syntax checks and CPU preflight/config smoke checks.
