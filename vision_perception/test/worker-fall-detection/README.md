# LEGO Worker YOLOE 학습 파이프라인

LEGO를 `person`으로 segmentation하는 YOLOE 모델을 학습·평가하는 POC 파이프라인이다. 기존 `/home/syw/Trihouse/vision_perception/segmentation/train.py`의 S1~S5 환경 augmentation을 그대로 사용한다.

현재 데이터셋은 `/home/syw/Trihouse/dataset/raw_examples/data.yaml`이며 `obstacle=0`, `person=1`이다. 감사 결과 train에는 수평 mask 후보가 있지만 valid/test에는 명백한 fallen 후보가 없다. 따라서 지금 실행은 `--allow-posture-gap`을 붙인 **LEGO 검출·segmentation 학습**이고, 낙상 성능 검증 완료를 의미하지 않는다.

## 1. 로컬에서 preflight만 실행

Ultralytics나 GPU 없이 실행할 수 있다.

```bash
cd /home/syw/Trihouse
python3 vision_perception/test/worker-fall-detection/preflight.py \
  --data dataset/raw_examples/data.yaml \
  --output runs/lego_worker/manual-preflight \
  --model 26s \
  --allow-posture-gap
```

확인할 파일:

- `preflight/dataset_report.json`: split별 이미지·instance와 fingerprint
- `preflight/instances.csv`: polygon instance별 통계
- `preflight/posture_candidates.csv`: 자세 검토 후보
- `preflight/contact_sheets/posture_candidates.jpg`: aspect ratio가 큰 순서의 육안 검토표
- `config/resolved.json`: 이후 수동 단계가 그대로 사용하는 설정

`--allow-posture-gap`을 빼면 valid/test fallen 정답 부족으로 종료 코드 2를 반환한다. fallen manifest가 준비되면 다음 CSV 형식으로 `--posture-manifest`를 전달한다.

```csv
image,posture,environment
valid/images/example.jpg,fallen,low_light
test/images/example.jpg,fallen,normal_light
```

## 2. 단계별 수동 실행

호스트에서 `trihouse_train` 컨테이너를 실행한 뒤 사용한다. 컨테이너의 저장소 위치가 기본값과 다르면 `TRIHOUSE_CONTAINER_ROOT`를 지정한다.

```bash
cd /home/syw/Trihouse

# 1) Dataset 검사와 resolved config 생성
vision_perception/test/worker-fall-detection/run_stage.sh preflight \
  --data dataset/raw_examples/data.yaml \
  --output runs/lego_worker/manual-01 \
  --model 26s --epochs 200 --patience 20 \
  --augmentation yes --device 0 --allow-posture-gap

# 2) YOLOE 학습
vision_perception/test/worker-fall-detection/run_stage.sh train \
  --run-dir runs/lego_worker/manual-01

# 3) Validation 평가
vision_perception/test/worker-fall-detection/run_stage.sh evaluate \
  --run-dir runs/lego_worker/manual-01 --split val

# 4) Validation 결과 확인 후 Test 평가
vision_perception/test/worker-fall-detection/run_stage.sh evaluate \
  --run-dir runs/lego_worker/manual-01 --split test
```

수동 단계는 디버깅용이다. validation gate와 최종 artifact manifest까지 자동 적용하려면 일괄 실행을 사용한다.

## 3. 한 번에 전체 실행

### Python 직접 실행

컨테이너의 `unified_env_ver2` 환경에서:

```bash
python3 vision_perception/test/worker-fall-detection/run_pipeline.py \
  --data dataset/raw_examples/data.yaml \
  --run-root runs/lego_worker \
  --name lego-26s-poc \
  --model 26s --augmentation yes \
  --epochs 200 --patience 20 --batch -1 \
  --device 0 --workers 8 \
  --allow-posture-gap
```

### 호스트에서 Shell 실행

```bash
cd /home/syw/Trihouse
vision_perception/test/worker-fall-detection/run_pipeline.sh \
  --data dataset/raw_examples/data.yaml \
  --run-root runs/lego_worker \
  --name lego-26s-poc \
  --model 26s --augmentation yes \
  --epochs 200 --patience 20 --batch -1 \
  --device 0 --workers 8 \
  --allow-posture-gap
```

1 epoch orchestration smoke test는 `--epochs 1 --patience 0 --batch 2 --workers 1`로 실행한다. 성능 gate 때문에 중단될 수 있으며, 이는 smoke run이 성능을 만족하지 못했다는 정상적인 gate 동작이다.

## 4. 결과와 판정

일괄 run에는 다음 핵심 파일이 생긴다.

- `status.json`: `RUNNING`, `FAILED`, `PREFLIGHT_COMPLETED`, `COMPLETED`
- `train/weights/best.pt`: 후속 실시간 추론 입력
- `evaluation/validation_metrics.json`
- `evaluation/test_metrics.json`
- `artifact_manifest.json`: 모델, class, dataset fingerprint, 지표 연결 계약

Validation gate 기본값은 person mask Recall 0.90, mask mAP50 0.80이다. gate를 통과해야 test 평가와 `artifact_manifest.json`이 생성된다.

## 5. 자동 테스트

```bash
cd /home/syw/Trihouse
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q \
  vision_perception/test/worker-fall-detection/tests
```

다음 단계에서는 `artifact_manifest.json`의 `best.pt`를 기존 실시간 입력에 연결하고 ByteTrack, mask 자세 feature, 시간-window 무움직임과 `EMERGENCY_CANDIDATE` 관제 확인 요청을 구현한다.
