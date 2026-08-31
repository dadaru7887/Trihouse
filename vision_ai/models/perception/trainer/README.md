# 인지 모델 학습 파이프라인 (YOLOE segmentation)

> 설계 **근거**(왜 에피소드 단위로 나눴는지, 왜 S1~S5 증강인지)는
> [설계 근거 문서](../../../../docs/vision_ai_design_rationale.md) §3 에 있다.
> 이 문서는 실행 절차만 다룬다.

사람/장애물 2-class segmentation 모델(`obstacle=0`, `person=1`)을 학습·평가한다.
S1~S5 다온도 환경 증강은 `scenarios.py` 를 그대로 쓴다.

**데이터셋 경로는 인자다.** 저장소에 딸린 `configs/config.yaml` 의 `data_yaml` 은
`PLACEHOLDER/...` 이므로 반드시 `--data` 로 넘기거나 config 를 자기 경로로 바꾼다.

낙상 성능 검증은 이 파이프라인의 범위가 아니다. 평가 split 에 fallen 인스턴스가
부족하면 `--allow-posture-gap` 이 필요하고, 그때의 결과는 **검출·segmentation 학습**
이지 낙상 성능 검증이 아니다.

## 코드 흐름

```text
vision_ai/models/perception/trainer/pipeline.py          ← 학습 단일 진입점
  → training/dataloader/   dataset 로딩, 계약 검증, label 품질·분포 분석
  → training/trainer/      YOLOE adapter와 multi-seed experiment 실행
  → vision_ai/utils/metrics.py/  box instance 및 mask pixel 지표 계산
  → training/analysis/     seed 비교, 학습 정체 진단, 표와 PNG 대시보드
  → training/{config_loader,orchestrator,multi_seed,environment,reproducibility}.py
  → vision_ai/utils/device.py   (학습·추론 공통)

seed 하나는 별도 프로세스다 — `python -m vision_ai.models.perception.trainer.seed_runner`.
재현성 때문이다: `PYTHONHASHSEED` 는 인터프리터가 뜬 뒤 못 바꾸고 CUDA 전역
상태도 프로세스에 남아, 같은 프로세스에서 seed 를 바꾸면 앞 seed 가 새어 든다.
```

`pipeline/dataset_audit.py`와 `pipeline/yoloe_backend.py`는 이전 import 사용자를 위한 호환 shim이다. 실제 구현은 각각 `dataloader/audit.py`, `trainer/yoloe_trainer.py`에 있다.

라벨 분석:

```bash
venv/yolo_segmentation/bin/python -m vision_ai.models.perception.trainer.pipeline labels \
  --config vision_ai/models/perception/trainer/configs/config.yaml
```

학습 완료 결과 분석:

```bash
venv/yolo_segmentation/bin/python -m vision_ai.models.perception.trainer.pipeline analyze \
  --experiment-dir runs/lego_worker/lego_yoloe_multiseed/<실험시각>
```

`analysis/`에는 `seed_performance.csv`, `performance_report.json/md`, `seed_dashboard.png`, `training_curves.png`가 생성된다. 새 multi-seed 학습은 종료 시 이 분석을 자동 실행한다.

Segmentation의 핵심 지표는 person mask mAP50-95, mAP50, recall, precision과 F1이다. box confusion matrix에서는 person TP/FP/FN, precision/recall/F1을 계산한다. mask IoU와 Dice/F1은 pixel overlap 품질을 나타낸다. Pixel accuracy는 넓은 배경 때문에 높게 보일 수 있으므로 보조 지표로만 사용한다.

현재 raw dataset의 person instance는 train/valid/test 각각 129/28/26개이며, bbox 면적이 전체 이미지의 1% 미만인 small person이 69/18/19개다. 이 small-object 비율과 작은 validation 표본은 seed별 변동 및 성능 정체의 주요 점검 대상이다.

## 1. Python 3.12 / CUDA 12.8 환경

Docker는 아직 만들지 않는다. 아래 스크립트가 저장소의 `venv/yolo_segmentation`에 Python 3.12 venv와 PyTorch cu128, Ultralytics를 설치한다.

```bash
cd "$REPO_ROOT"   # 저장소 루트
./vision_ai/setup_venv.sh
```

현재 검증된 설치값은 Python 3.12.3, PyTorch 2.11.0+cu128, CUDA runtime 12.8이다. 실제 학습 시작 시 `environment.json`에 GPU 모델, driver, CUDA runtime, PyTorch/Ultralytics, dataset fingerprint, Git SHA/dirty 여부가 기록된다. RTX 5080에서는 `sm_120` 미지원 또는 CUDA runtime 12.8 미만이면 학습 전에 실패한다.

## 2. 로컬에서 preflight만 실행

Ultralytics나 GPU 없이 실행할 수 있다.

```bash
cd "$REPO_ROOT"   # 저장소 루트
venv/yolo_segmentation/bin/python -m vision_ai.models.perception.trainer.pipeline preflight \
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
cd "$REPO_ROOT"   # 저장소 루트

# 1) Dataset 검사와 resolved config 생성
preflight 단계 \
  --data dataset/raw_examples/data.yaml \
  --output runs/lego_worker/manual-01 \
  --model 26s --epochs 200 --patience 20 \
  --augmentation yes --device 0 --allow-posture-gap

# 2) YOLOE 학습
train 단계 \
  --run-dir runs/lego_worker/manual-01

# 3) Validation 평가
evaluate 단계 \
  --run-dir runs/lego_worker/manual-01 --split val

# 4) Validation 결과 확인 후 Test 평가
evaluate 단계 \
  --run-dir runs/lego_worker/manual-01 --split test
```

수동 단계는 디버깅용이다. validation gate와 최종 artifact manifest까지 자동 적용하려면 일괄 실행을 사용한다.

## 4. config 기반 multi-seed 전체 실행 (권장)

학습 파라미터와 seed는 `configs/config.yaml` 한 곳에서 관리한다. 각 seed는 별도 subprocess와 `PYTHONHASHSEED`로 격리된다. `training.augmentation_seed: 42`는 저조도·성에·결로 등 온라인 증강 난수열에만 적용되고, `experiment.seeds`는 모델 초기화·데이터 shuffle·PyTorch 학습 난수를 제어한다. 따라서 결과는 "고정 augmentation seed 아래 학습 seed 민감도" 실험이다.

`training.device`는 다음 정책을 지원한다.

- `auto`: CUDA GPU가 있으면 GPU 0, 없으면 CPU
- `cpu`: GPU가 있어도 CPU 강제
- `gpu` 또는 `cuda`: GPU 0 필수, CUDA가 없으면 즉시 실패
- `"0"`, `"1"`, `"cuda:1"`: 해당 GPU 필수, index가 없으면 즉시 실패

```bash
cd "$REPO_ROOT"   # 저장소 루트
venv/yolo_segmentation/bin/python -m vision_ai.models.perception.trainer.pipeline train \
  --config vision_ai/models/perception/trainer/configs/config.yaml
```

모든 성공 seed의 test 결과는 `test_summary.md/csv`에 평균 ± 표본표준편차와 min/max로 기록한다. 대표 모델은 validation `mask_map50_95`, validation `mask_recall`, 낮은 seed 순으로만 고르며 validation gate 실패 모델은 제외한다. test 지표는 선택에 쓰지 않고 근거와 weight 경로를 `selected_model.json`에 남긴다.

## 5. 단일 seed 전체 실행

### Python 직접 실행

venv에서:

```bash
venv/yolo_segmentation/bin/python -m vision_ai.models.perception.trainer.pipeline run \
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
cd "$REPO_ROOT"   # 저장소 루트
venv/yolo_segmentation/bin/python -m vision_ai.models.perception.trainer.pipeline run \
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
cd "$REPO_ROOT"   # 저장소 루트
venv/yolo_segmentation/bin/python \
  -m vision_ai.robot.perception.worker \
  --weights runs/lego_worker/lego_yoloe_multiseed/<실험시각>/selected_model.json \
  --source 0
```

현재 POC는 가장 confidence가 높은 `person=1` segmentation mask의 가로/세로 비율과 centroid 이동량을 사용한다. 낙상 지속 후 무움직임이 임계시간을 넘으면 stdout에 `WORKER_FALL_CONFIRMATION_REQUEST` JSON 후보 이벤트를 한 번 출력한다. 관제 API 전송은 다음 통합 단계에서 이 이벤트에 연결하면 된다.

`configs/realtime.yaml`의 `inference.device`도 동일한 `auto/cpu/gpu/index` 규칙을 사용한다.

CPU에서 orchestration 코드 경로만 점검하려면 config 사본에서 `device: cpu`, `epochs: 1`, `batch: 2`, `workers: 1`, seed 하나만 사용한다. CPU smoke 결과는 성능 비교나 대표 모델 선정 자료로 사용하지 않는다.

GPU PC에서는 먼저 1-epoch smoke config로 train→validation→test→selected model 경로를 확인한다.

```bash
venv/yolo_segmentation/bin/python -m vision_ai.models.perception.trainer.pipeline train \
  --config vision_ai/models/perception/trainer/configs/smoke_gpu.yaml
```

완료 후 본 학습은 `configs/config.yaml`의 `device`를 `gpu`로 지정하고 실행한다.

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
cd "$REPO_ROOT"   # 저장소 루트
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q \
  vision_ai/tests/worker
```

현재 실시간 코드는 LEGO 한 개 POC이다. 다중 LEGO tracking, 카메라별 calibration, 관제 API의 인증·재시도·중복 제거는 후속 범위다.

## 9. 알려진 한계 — 낙상 recall gap

낙상 판정은 person mask 의 **bbox aspect ratio 가 `fall_aspect_ratio` 를 넘는 것**에서
시작한다. 넘지 못하면 `FALL_SUSPECTED` 에 진입조차 못 하므로, 그 뒤의 상태머신
(`fall_confirm_seconds` · `immobile_seconds` · `motion_threshold`)이 아무리 정확해도
그 낙상은 보이지 않는다. **상태머신 로직으로는 이 gap 을 메울 수 없다** — 2차 신호
(자세 추정, 깊이, 시간축 모션 특징) 없이는 구조적으로 못 고친다.

임계값을 낮추는 것으로 메우려 하면 오탐이 늘어난다. 2026-08-18 sweep 실측:

| `fall_aspect_ratio` | `re_1` 오탐 | `re_2` 오탐 |
|---|---|---|
| 1.2 (이전 기본값) | 0 | 0 |
| 0.9 (현재) | 0 | 0 |
| 0.7 | 0 | **1회** |

**0.9 밑으로 내리지 않는다.** 다만 두 영상 모두 실제 낙상이 없어, 0.9 가 "안전하다"
까지만 확인됐고 "recall 이 실제로 좋아진다" 는 직접 증거는 아직 없다.

지금은 이 gap 을 **다운스트림 절차**가 흡수하는 것을 전제로 한다 —
`WORKER_FALL_CONFIRMATION_REQUEST` 이벤트를 관제센터의 사람이 재확인한다. 즉 이
모델은 최종 판정자가 아니라 **사람에게 볼 곳을 알려 주는 장치**다.

### 아직 검증되지 않은 것

- `motion_threshold`(기본 0.015)와 `immobile_seconds`(기본 5.0) 는 sweep 검증을
  거치지 않았다. `re_1`·`re_2` 에 낙상이 없어 `FALLEN` 상태에 한 번도 들어가 본 적이
  없기 때문이다.
- 배경 하드웨어를 person 으로 잡는 오검출이 있다 (`re_3` t=74 s, ratio 3.54 는 벽에
  달린 금속 체인이었다). confidence 로는 걸러지지 않는다 — 전부 conf ≥ 0.25 였다.
  aspect ratio 만으로 자동 판정하면 안 된다.
- CPU 추론이 약 0.21 s/frame 이다. 원본 20 fps(0.05 s/frame) 대비 1/4 속도라
  **CPU 단독 실시간 처리는 불가능**하다. GPU · 프레임 스킵 · 입력 해상도 축소 중
  하나가 필요하다.
