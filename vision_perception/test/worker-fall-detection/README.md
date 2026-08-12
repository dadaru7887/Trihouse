# LEGO Worker YOLOE 학습 파이프라인

LEGO를 `person`으로 segmentation하는 YOLOE 모델을 학습·평가하는 POC 파이프라인이다. 기존 `/home/syw/Trihouse/vision_perception/segmentation/train.py`의 S1~S5 환경 augmentation을 그대로 사용한다.

현재 데이터셋은 `/home/syw/Trihouse/dataset/raw_examples/data.yaml`이며 `obstacle=0`, `person=1`이다. 감사 결과 train에는 수평 mask 후보가 있지만 valid/test에는 명백한 fallen 후보가 없다. 따라서 지금 실행은 `--allow-posture-gap`을 붙인 **LEGO 검출·segmentation 학습**이고, 낙상 성능 검증 완료를 의미하지 않는다.

## 1. Python 3.12 / CUDA 12.8 환경

Docker는 아직 만들지 않는다. 아래 스크립트가 저장소의 `venv/yolo_segmentation`에 Python 3.12 venv와 PyTorch cu128, Ultralytics를 설치한다.

```bash
cd /home/syw/Trihouse/vision_perception/test/worker-fall-detection
./setup_venv.sh
```

현재 검증된 설치값은 Python 3.12.3, PyTorch 2.11.0+cu128, CUDA runtime 12.8이다. 실제 학습 시작 시 `environment.json`에 GPU 모델, driver, CUDA runtime, PyTorch/Ultralytics, dataset fingerprint, Git SHA/dirty 여부가 기록된다. RTX 5080에서는 `sm_120` 미지원 또는 CUDA runtime 12.8 미만이면 학습 전에 실패한다.

## 2. 로컬에서 preflight만 실행

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

## 3. 단계별 수동 실행

모든 shell wrapper는 `venv/yolo_segmentation`을 사용한다.

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

## 4. config 기반 multi-seed 전체 실행 (권장)

학습 파라미터와 seed는 `configs/config.yaml` 한 곳에서 관리한다. 각 seed는 별도 subprocess와 `PYTHONHASHSEED`로 격리된다.

`training.device`는 다음 정책을 지원한다.

- `auto`: CUDA GPU가 있으면 GPU 0, 없으면 CPU
- `cpu`: GPU가 있어도 CPU 강제
- `gpu` 또는 `cuda`: GPU 0 필수, CUDA가 없으면 즉시 실패
- `"0"`, `"1"`, `"cuda:1"`: 해당 GPU 필수, index가 없으면 즉시 실패

```bash
cd /home/syw/Trihouse
vision_perception/test/worker-fall-detection/train_multi_seed.sh \
  --config vision_perception/test/worker-fall-detection/configs/config.yaml
```

모든 성공 seed의 test 결과는 `test_summary.md/csv`에 평균 ± 표본표준편차와 min/max로 기록한다. 대표 모델은 validation `mask_map50_95`, validation `mask_recall`, 낮은 seed 순으로만 고르며 validation gate 실패 모델은 제외한다. test 지표는 선택에 쓰지 않고 근거와 weight 경로를 `selected_model.json`에 남긴다.

## 5. 단일 seed 전체 실행

### Python 직접 실행

venv에서:

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

## 6. 기존 weight 실시간 영상 테스트

카메라 `0`, MP4 경로, RTSP URL을 `--source`로 받을 수 있다. `--weights`에는 `best.pt` 또는 multi-seed 결과의 `selected_model.json`을 준다.

```bash
cd /home/syw/Trihouse
venv/yolo_segmentation/bin/python \
  vision_perception/test/worker-fall-detection/realtime.py \
  --weights runs/lego_worker/lego_yoloe_multiseed/<실험시각>/selected_model.json \
  --source 0
```

현재 POC는 가장 confidence가 높은 `person=1` segmentation mask의 가로/세로 비율과 centroid 이동량을 사용한다. 낙상 지속 후 무움직임이 임계시간을 넘으면 stdout에 `WORKER_FALL_CONFIRMATION_REQUEST` JSON 후보 이벤트를 한 번 출력한다. 관제 API 전송은 다음 통합 단계에서 이 이벤트에 연결하면 된다.

`configs/realtime.yaml`의 `inference.device`도 동일한 `auto/cpu/gpu/index` 규칙을 사용한다.

CPU에서 orchestration 코드 경로만 점검하려면 config 사본에서 `device: cpu`, `epochs: 1`, `batch: 2`, `workers: 1`, seed 하나만 사용한다. CPU smoke 결과는 성능 비교나 대표 모델 선정 자료로 사용하지 않는다.

## 7. 결과와 판정

일괄 run에는 다음 핵심 파일이 생긴다.

- `status.json`: `RUNNING`, `FAILED`, `PREFLIGHT_COMPLETED`, `COMPLETED`
- `train/weights/best.pt`: 후속 실시간 추론 입력
- `evaluation/validation_metrics.json`
- `evaluation/test_metrics.json`
- `artifact_manifest.json`: 모델, class, dataset fingerprint, 지표 연결 계약

Validation gate 기본값은 person mask Recall 0.90, mask mAP50 0.80이다. multi-seed 설정은 통계 보고를 위해 gate 실패 seed도 test하지만 대표 모델 후보에서는 제외한다.

## 8. 자동 테스트

```bash
cd /home/syw/Trihouse
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q \
  vision_perception/test/worker-fall-detection/tests
```

현재 실시간 코드는 LEGO 한 개 POC이다. 다중 LEGO tracking, 카메라별 calibration, 관제 API의 인증·재시도·중복 제거는 후속 범위다.
