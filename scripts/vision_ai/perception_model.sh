#!/bin/bash
# Train the perception model on the HPC server: YOLOE segmentation, then the
# fall classifier when a feature JSONL is given.
#
#   sh scripts/vision_ai/perception_model.sh <data.yaml> <seed> [epochs] [holdout] [fall_features]
#
# Examples:
#   sh scripts/vision_ai/perception_model.sh data/pinky_camera/merged/data.yaml 42
#   sh scripts/vision_ai/perception_model.sh data/pinky_camera/merged/data.yaml 42 200 frost
#
# holdout keeps one degradation mechanism out of training so the run can be
# scored on a corruption it never saw. One of:
#   gamma motion_blur color_jitter condensation glare frost

echo "### START DATE=$(date)"
echo "### HOSTNAME=$(hostname)"
echo "### CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"

DATA=$1
SEED=$2
EPOCHS=$3
HOLDOUT=$4
FALL_FEATURES=$5

DEFAULT_EPOCHS=200

if [ -z "$DATA" ] || [ -z "$SEED" ]; then
    echo "ERROR: missing arguments."
    echo ""
    echo "Usage:"
    echo "  sh $0 <data.yaml> <seed> [epochs] [holdout] [fall_features.jsonl]"
    echo ""
    echo "Example:"
    echo "  sh $0 data/pinky_camera/merged/data.yaml 42 200 frost"
    exit 1
fi

if [ -z "$EPOCHS" ]; then
    EPOCHS=$DEFAULT_EPOCHS
    echo "### epochs not provided -> use default = ${EPOCHS}"
fi

# The manifest sits beside data.yaml in a merged dataset. Preflight counts the
# fallen samples per eval split from it; without it the run stops there.
DATA_DIR=$(dirname "$DATA")
POSTURE_MANIFEST="${DATA_DIR}/posture_manifest.csv"

echo "### [Input Parameters]"
echo "### data              = ${DATA}"
echo "### posture_manifest  = ${POSTURE_MANIFEST}"
echo "### seed              = ${SEED}"
echo "### epochs            = ${EPOCHS}"
echo "### holdout           = ${HOLDOUT:-none}"
echo "### fall_features     = ${FALL_FEATURES:-none}"
echo "###"

BASE_ROOT="/scratch/sywon_ys/trihouse"
EXP_NAME="perception_e${EPOCHS}${HOLDOUT:+_holdout-${HOLDOUT}}"
OUTDIR="${BASE_ROOT}/s${SEED}/${EXP_NAME}"

echo "### [Output Directory]"
echo "### OUTDIR = ${OUTDIR}"
mkdir -p "$OUTDIR"

source ~/.bashrc
conda activate trihouse-vision-aug
ml purge

# ---------------------------------------------------------------------------
# 1. YOLOE segmentation. --device auto picks cuda here and mps on a Mac.
# ---------------------------------------------------------------------------
CMD="python -m vision_ai.models.perception.trainer.pipeline run \
  --data ${DATA} \
  --posture-manifest ${POSTURE_MANIFEST} \
  --run-root ${OUTDIR} \
  --seed ${SEED} \
  --epochs ${EPOCHS} \
  --device auto \
  --augmentation \
  --wandb \
  --wandb-project trihouse-vision \
"

if [ -n "$HOLDOUT" ]; then
    CMD="${CMD} --holdout ${HOLDOUT}"
fi

echo "### RUN COMMAND (segmentation):"
echo "### $CMD"
echo "###"

eval $CMD
STATUS=$?

if [ $STATUS -ne 0 ]; then
    echo "### segmentation failed with status ${STATUS}; skipping the fall classifier"
    echo "### END DATE=$(date)"
    exit $STATUS
fi

# ---------------------------------------------------------------------------
# 2. Fall classifier, only when a feature JSONL was given. It is a separate
#    model with its own inputs, so the segmentation run stands on its own.
# ---------------------------------------------------------------------------
if [ -n "$FALL_FEATURES" ]; then
    FALL_CMD="python -m vision_ai.models.perception.trainer.fall_trainer \
      --dataset ${FALL_FEATURES} \
      --out ${OUTDIR}/fall \
      --seed ${SEED} \
      --min-recall 0.85 \
      --wandb \
      --wandb-project trihouse-vision \
    "
    echo "### RUN COMMAND (fall classifier):"
    echo "### $FALL_CMD"
    echo "###"
    eval $FALL_CMD
    STATUS=$?
fi

echo "###"
echo "### RESULTS in ${OUTDIR}"
echo "###   run.log                       stage-by-stage log"
echo "###   metrics.jsonl                 every metric, also without wandb"
echo "###   */train/weights/best.pt       segmentation weights"
echo "###   */evaluation/*_metrics.json   val and test scores"
echo "### END DATE=$(date)"
exit $STATUS
