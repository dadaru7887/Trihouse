#!/bin/bash
# trihouse 이미지 컨테이너 접속용 launcher
# conda 환경(unified_env_ver2)까지 자동 활성화된 상태로 쉘 진입

IMAGE="trihouse:ver2"

docker run --rm -it --gpus all "$IMAGE" bash -c '
source /opt/conda/etc/profile.d/conda.sh
conda activate unified_env_ver2
exec bash
'
