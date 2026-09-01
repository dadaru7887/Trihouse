#!/bin/bash
# Train the perception model on the HPC server: a multi-seed YOLOE segmentation
# experiment, then the fall classifier when a feature JSONL is given.
#
#   sbatch --time=2-12:00:00 --gres=gpu:1 \
#     scripts/vision_ai/perception_model.sh <data.yaml> [fall_features.jsonl]
#
# This script only submits the experiment. What it runs is described by
#
#     vision_ai/models/perception/trainer/configs/config.yaml
#
# which owns the seed list, epochs, batch, the validation gate and the
# model-selection metric. Change the experiment there, not here. The dataset
# stays an argument: the shipped config carries a placeholder on purpose, so a
# path that happens to exist on another machine cannot be trained on by
# accident. The posture manifest is derived from data.yaml and passed with it,
# because it describes that dataset.
#
# `pipeline train` runs every seed as its own process, keeps going when one
# fails (experiment.continue_on_failure), scores the test split even for a seed
# under the gate (evaluation.test_all_seeds), then aggregates the seeds, picks
# one model on validation metrics and writes the plots.
#
# Not supported here: leave-one-out holdout runs. The multi-seed config has no
# holdout key, so a corruption-holdout experiment still needs
# `pipeline run --holdout <mechanism>` for a single seed.

echo "### START DATE=$(date)"
echo "### HOSTNAME=$(hostname)"
echo "### CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"

DATA=$1
FALL_FEATURES=$2

BASE_ROOT="/home/jyseo9506/wsy_ws/Trihouse"
CONFIG="vision_ai/models/perception/trainer/configs/config.yaml"

if [ -z "$DATA" ]; then
    echo "ERROR: missing data.yaml."
    echo ""
    echo "Usage:"
    echo "  sh $0 <data.yaml> [fall_features.jsonl]"
    echo ""
    echo "Example:"
    echo "  sh $0 data/pinky_camera/merged/data.yaml"
    exit 1
fi

# The seed list moved into the config. Catch the old call shape rather than
# letting a seed argument land in $FALL_FEATURES and fail much later.
case "$FALL_FEATURES" in
    all | *[0-9],[0-9]* | [0-9] | [0-9][0-9] | [0-9][0-9][0-9] | [0-9][0-9][0-9][0-9])
        echo "ERROR: seeds are no longer an argument."
        echo ""
        echo "They come from experiment.seeds in ${CONFIG}."
        echo "Edit that list to change which seeds run."
        echo ""
        echo "Usage:"
        echo "  sh $0 <data.yaml> [fall_features.jsonl]"
        exit 1
        ;;
esac

# The manifest sits beside data.yaml in a merged dataset. Preflight counts the
# fallen samples per eval split from it; without it that check is skipped.
DATA_DIR=$(dirname "$DATA")
POSTURE_MANIFEST="${DATA_DIR}/posture_manifest.csv"

# MultiSeedExperiment creates this directory itself and refuses one that
# already exists, so do not mkdir it here.
EXPERIMENT_DIR="${BASE_ROOT}/experiments/$(date +%Y%m%d_%H%M%S)"

echo "### [Input Parameters]"
echo "### config           = ${CONFIG}"
echo "### data             = ${DATA}"
echo "### posture_manifest = ${POSTURE_MANIFEST}"
echo "### fall_features    = ${FALL_FEATURES:-none}"
echo "### experiment_dir   = ${EXPERIMENT_DIR}"
echo "###"

cd "$BASE_ROOT" || exit 1

source ~/.bashrc
conda activate trihouse-vision
ml purge

# ---------------------------------------------------------------------------
# 1. Multi-seed YOLOE segmentation: train, validate, test and select.
# ---------------------------------------------------------------------------
CMD="python -m vision_ai.models.perception.trainer.pipeline train \
  --config ${CONFIG} \
  --data ${DATA} \
  --posture-manifest ${POSTURE_MANIFEST} \
  --experiment-dir ${EXPERIMENT_DIR} \
"

echo "### RUN COMMAND (multi-seed segmentation):"
echo "### $CMD"
echo "###"

eval $CMD
STATUS=$?

if [ $STATUS -ne 0 ]; then
    echo "### segmentation experiment failed with status ${STATUS}; skipping the fall classifier"
    echo "### END DATE=$(date)"
    exit $STATUS
fi

# ---------------------------------------------------------------------------
# 2. Fall classifier, only when a feature JSONL was given. It is a separate
#    model with its own inputs, seeded with the seed that won selection so the
#    two models that ship together were built under the same draw.
# ---------------------------------------------------------------------------
if [ -n "$FALL_FEATURES" ]; then
    SELECTED="${EXPERIMENT_DIR}/selected_model.json"
    SEED=$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['selected_seed'])" \
           "$SELECTED" 2>/dev/null)

    if [ -z "$SEED" ]; then
        echo "### no selected seed in ${SELECTED}; skipping the fall classifier"
    else
        FALL_CMD="PYTHONHASHSEED=${SEED} NO_ALBUMENTATIONS_UPDATE=1 \
          python -m vision_ai.models.perception.trainer.fall_trainer \
          --dataset ${FALL_FEATURES} \
          --out ${EXPERIMENT_DIR}/fall \
          --seed ${SEED} \
          --min-recall 0.85 \
          --wandb \
          --wandb-project trihouse-vision \
        "
        echo "### RUN COMMAND (fall classifier, seed ${SEED}):"
        echo "### $FALL_CMD"
        echo "###"
        eval $FALL_CMD
        STATUS=$?
    fi
fi

echo "###"
echo "### RESULTS in ${EXPERIMENT_DIR}"
echo "###   selected_model.json    chosen weights and why"
echo "###   aggregate.json         per-seed and mean/std across seeds"
echo "###   seed_results.csv       one row per seed"
echo "###   seed_<n>/              each seed's run, log, weights and metrics"
echo "###   analysis/              plots across seeds"
echo "### END DATE=$(date)"
exit $STATUS
