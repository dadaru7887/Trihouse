#!/bin/bash
# environment.yml 로 conda 환경 만든 뒤, 이 스크립트 한 번 실행하세요.
# conda activate unified_env 먼저 하고 실행!

set -e

echo ">> [1/2] pywsd/nltk 데이터 다운로드"
python -c "
import nltk
for pkg in ['averaged_perceptron_tagger_eng','averaged_perceptron_tagger','wordnet','omw-1.4','punkt','punkt_tab']:
    nltk.download(pkg)
"

echo ">> [2/2] spconv/cumm JIT 재컴파일 방지용 환경변수를 conda activate 스크립트에 등록"
ACTIVATE_DIR="$CONDA_PREFIX/etc/conda/activate.d"
mkdir -p "$ACTIVATE_DIR"
cat > "$ACTIVATE_DIR/pointcept_env.sh" << 'EOF'
export CUMM_DISABLE_JIT=1
export SPCONV_DISABLE_JIT=1
EOF

echo "완료! 다음부터 'conda activate unified_env' 할 때마다 위 환경변수가 자동으로 설정됩니다."
