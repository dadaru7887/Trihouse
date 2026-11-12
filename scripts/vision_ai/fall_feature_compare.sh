#!/bin/bash
# Fall-feature comparison A/B/C on the HPC server, end to end:
#   merge (export session split) -> preflight -> YOLOE multi-seed (augmented)
#   -> compare on ground-truth masks -> compare on the selected YOLOE's masks
#
#   sbatch --time=2-12:00:00 --gres=gpu:1 scripts/vision_ai/fall_feature_compare.sh
#   sbatch --time=02:00:00  --gres=gpu:1 scripts/vision_ai/fall_feature_compare.sh \
#       experiments/<stamp>/selected_model.json      # reuse trained YOLOE weights
#
# Needs data/pinky_camera/{segmentation,fallen} (scripts/vision_ai/README.md
# step 3). The YOLOE run itself is configured by
# vision_ai/models/perception/trainer/configs/config.yaml (seeds, epochs,
# augmentation: true, validation gate).

echo "### START DATE=$(date)"
echo "### HOSTNAME=$(hostname)"
echo "### CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"

WEIGHTS=$1                                     # optional selected_model.json or best.pt

BASE_ROOT="/home/jyseo9506/wsy_ws/Trihouse"
CONFIG="vision_ai/models/perception/trainer/configs/config.yaml"
EXPORT="data/pinky_camera/fallen"              # Fallen/Obstacle/Standing labels
MERGED="data/pinky_camera/merged_export_split" # person/obstacle, export session split
STAMP=$(date +%Y%m%d_%H%M%S)
OUT="runs/fall_compare/${STAMP}"               # comparison reports land here

cd "$BASE_ROOT" || exit 1
source ~/.bashrc
conda activate trihouse-vision
ml purge
export NO_ALBUMENTATIONS_UPDATE=1

# ---------------------------------------------------------------------------
# 1. Merged dataset whose sessions sit where the fallen export put them, so
#    YOLOE and the fall classifier share one split.
# ---------------------------------------------------------------------------
if [ ! -f "${MERGED}/data.yaml" ]; then
    python -m vision_ai.data_loader.perception.roboflow_merge \
        --out data/pinky_camera --split-from-export fallen \
        --merged-name "$(basename ${MERGED})" || exit 1
fi
python -m vision_ai.models.perception.trainer.pipeline preflight \
    --data "${MERGED}/data.yaml" \
    --posture-manifest "${MERGED}/posture_manifest.csv" \
    --output "${OUT}/preflight" || exit 1

# ---------------------------------------------------------------------------
# 2. YOLOE person/obstacle segmentation, multi-seed with augmentation, unless
#    weights were given.
# ---------------------------------------------------------------------------
if [ -z "$WEIGHTS" ]; then
    EXPERIMENT_DIR="${BASE_ROOT}/experiments/${STAMP}"
    echo "### YOLOE experiment -> ${EXPERIMENT_DIR}"
    python -m vision_ai.models.perception.trainer.pipeline train \
        --config "${CONFIG}" \
        --data "${MERGED}/data.yaml" \
        --posture-manifest "${MERGED}/posture_manifest.csv" \
        --experiment-dir "${EXPERIMENT_DIR}"
    WEIGHTS="${EXPERIMENT_DIR}/selected_model.json"
fi

# ---------------------------------------------------------------------------
# 3. Ground-truth masks: needs no weights, so it runs even if YOLOE failed.
# ---------------------------------------------------------------------------
python -m vision_ai.models.perception.trainer.fall_compare \
    --export "${EXPORT}" --merged "${MERGED}" \
    --masks gt --out "${OUT}/gt" || exit 1

# ---------------------------------------------------------------------------
# 4. Predicted masks from the selected YOLOE. No seed passing the validation
#    gate means no selected_model.json; that comparison is then not run.
# ---------------------------------------------------------------------------
if [ ! -f "$WEIGHTS" ]; then
    echo "### no weights at ${WEIGHTS}; predicted-mask comparison skipped"
    echo "### END DATE=$(date)"
    exit 3
fi
python -m vision_ai.models.perception.trainer.fall_compare \
    --export "${EXPORT}" --merged "${MERGED}" \
    --masks predicted --weights "${WEIGHTS}" --device auto \
    --out "${OUT}/predicted"
STATUS=$?

echo "### RESULTS in ${BASE_ROOT}/${OUT}"
echo "###   gt/report.md, predicted/report.md   tables"
echo "###   */report.json, */rows.jsonl         every number and every row"
echo "###   */cases/*.png                       representative cases"
echo "### END DATE=$(date)"
exit $STATUS
