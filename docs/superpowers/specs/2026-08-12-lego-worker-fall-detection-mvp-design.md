# LEGO Worker Fall Detection Pipeline Design

## 1. 목표와 단계

POC의 대상은 LEGO 작업자다. 기존 YOLO segmentation 데이터셋에서 LEGO는 `person` 클래스로 polygon 라벨링되어 있다. 최종 시스템은 실시간 카메라 영상에서 LEGO를 segmentation·추적하고, 비정상 수평 자세와 장시간 무움직임이 함께 확인되면 관제 시스템에 관리자 확인 요청 후보를 보낸다.

전체 파이프라인은 다음 네 단계로 나눈다.

```text
1. YOLOE LEGO person segmentation 학습·평가
2. mask 기반 standing/fallen 자세 판정
3. ByteTrack + 시간-window 무움직임 판정
4. EMERGENCY_CANDIDATE 관제 확인 요청
```

이번 구현 사이클의 필수 범위는 **1단계 학습·평가 파이프라인**이다. 2~4단계는 학습 산출물과 인터페이스를 소비하는 후속 구현으로 설계 계약을 남긴다.

## 2. 선택한 접근

YOLOE는 LEGO의 자세 상태를 직접 분류하지 않고 `person` segmentation mask를 생성한다. standing/fallen은 mask의 aspect ratio, PCA orientation과 바닥 기준 centroid를 조합해 별도 규칙 모듈이 판단한다. 무움직임은 동일 track의 centroid displacement와 mask IoU를 시간 window로 평가한다.

이 경계는 다음 장점이 있다.

- 기존 `person` polygon 라벨과 `train.py`를 재사용한다.
- 자세 클래스로 전체 데이터셋을 다시 라벨링하지 않는다.
- 한 worker가 넘어져도 class가 바뀌지 않아 tracking ID 유지에 유리하다.
- 자세·시간 threshold를 모델 재학습 없이 현장 영상으로 보정할 수 있다.

## 3. 현재 데이터셋과 발견된 제약

데이터셋 루트는 `/home/syw/Trihouse/dataset/raw_examples`이며 구조는 다음과 같다.

```text
dataset/raw_examples/
├── data.yaml
├── train/{images,labels}
├── valid/{images,labels}
└── test/{images,labels}
```

`data.yaml`은 `obstacle=0`, `person=1`의 두 클래스를 정의한다. 현재 감사 결과는 다음과 같다.

| Split | 이미지 | person instance | bbox aspect ratio ≥ 1.2 |
|---|---:|---:|---:|
| train | 233 | 129 | 17 |
| valid | 51 | 28 | 0 |
| test | 50 | 26 | 0 |

aspect ratio만으로 자세를 확정할 수는 없지만, valid/test에 명백히 수평인 mask가 없다는 것은 누운 LEGO segmentation 성능을 독립적으로 검증할 표본이 부족하다는 강한 신호다. 학습 파이프라인은 이 문제를 숨기지 않고 보고해야 한다.

원본 split과 파일은 자동으로 이동하거나 덮어쓰지 않는다. 자세 메타데이터가 없으므로 파일명이나 aspect ratio만 사용해 정답 posture를 자동 확정하지도 않는다. 대신 dataset audit에서 자세 후보를 추출한 contact sheet와 CSV를 만들고, 사용자가 `standing`, `fallen`, `unknown`을 확인한 manifest를 입력으로 받는다.

## 4. 학습 파이프라인 구성

### 4.1 Dataset Preflight

학습 전에 다음을 검사한다.

- `data.yaml`에 train, val, test 경로와 `person` class가 존재한다.
- 각 split 이미지가 읽히며 대응 label 파일이 존재한다.
- polygon 행은 class ID 뒤에 최소 3개 좌표쌍이 있고 모든 좌표가 0~1 범위다.
- label class ID가 `names` 범위를 벗어나지 않는다.
- 동일 파일 또는 동일 이미지 content hash가 split 사이에 중복되지 않는다.
- 빈 label 이미지는 허용하되 개수와 비율을 보고한다.
- split별 이미지, instance, class, mask bbox aspect ratio 분포를 계산한다.
- posture manifest가 있으면 경로·중복·허용값과 split별 standing/fallen 분포를 검사한다.

preflight는 `dataset_report.json`, `instances.csv`, `posture_candidates.csv`, contact sheet를 결과 디렉터리에 저장한다. 구조나 polygon이 잘못된 경우 학습을 중단한다. posture 표본 부족은 기본적으로 명확한 `NOT_EVALUABLE` gate가 되며 `--allow-posture-gap`을 명시한 detection-only 실험에서만 학습을 허용한다.

낙상 파이프라인 진입을 위한 권장 최소 조건은 valid와 test 각각 확인된 `fallen` person instance 10개 이상이다. 이 수치는 안전 인증 기준이 아니라 POC 평가가 완전히 비어 있지 않게 하는 개발 gate다.

### 4.2 Augmentation

기존 `train.py`의 S1~S5 augmentation을 유지한다.

- S1: 저조도 gamma, motion blur, color jitter
- S2: 결로
- S3: glare
- S4: 성에 및 야간 성에
- S5: 저조도·결로·glare·성에·motion blur 복합 조건

단, augmentation 선택 로직과 학습 orchestration을 분리한다. `augmentations.py`는 순수 이미지 변환과 registry만 담당하고, `train.py`는 CLI·검증·YOLOE 호출을 담당한다. seed를 한 곳에서 설정하고 실행 기록에 남긴다.

validation과 test에는 온라인 augmentation을 적용하지 않는다. 원본 test split은 최종 평가에만 사용하고 threshold 선택에 사용하지 않는다.

### 4.3 학습 실행

기존 호출 방식은 유지한다.

```bash
vision_perception/segmentation/train.sh \
  --model 26s \
  --data /home/syw/Trihouse/dataset/raw_examples/data.yaml \
  --augmentation yes \
  --epochs 200 \
  --patience 20 \
  --device 0
```

`train.sh`는 호스트에서 `trihouse_train` 컨테이너로 위임하고 컨테이너 안에서는 `unified_env_ver2`를 활성화한다. 기존 GPU 환경과 호환성을 유지하면서 `--preflight-only`, `--allow-posture-gap`, `--posture-manifest`, `--run-root`, `--resume`을 지원한다.

학습 실행 순서는 고정한다.

1. 입력 경로와 실행 환경 검증
2. dataset preflight 및 fingerprint 생성
3. run 디렉터리 생성과 resolved config 저장
4. YOLOE fine-tuning
5. `best.pt`로 validation 평가
6. 모든 gate가 통과한 경우 test 평가
7. 산출물 manifest 및 최종 상태 기록

중간 실패 시 `status.json`은 `FAILED`와 실패 단계를 기록한다. 성공한 것처럼 보이는 완료 marker는 만들지 않는다.

### 4.4 재현성과 Resume

run ID는 KST timestamp, 모델, augmentation 상태를 포함한다. 각 run은 다음을 기록한다.

- 원본 CLI와 resolved 설정
- Git commit 및 dirty 여부
- Python, PyTorch, CUDA, Ultralytics, Albumentations 버전
- GPU 이름
- dataset `data.yaml`과 image/label 목록 fingerprint
- seed, model, imgsz, batch, epochs, patience, workers
- 시작·종료 시각과 최종 상태

`--resume <last.pt>`는 같은 dataset fingerprint와 호환 설정일 때만 허용한다. 다른 dataset 또는 class mapping으로 조용히 재개하지 않는다.

## 5. 평가와 학습 산출물

Ultralytics 표준 지표를 보존한다.

- box Precision, Recall, mAP50, mAP50-95
- mask Precision, Recall, mAP50, mAP50-95
- class별 결과
- confusion matrix와 validation prediction 이미지

초기 POC training gate는 validation의 `person` mask Recall 0.90 이상과 mask mAP50 0.80 이상이다. test 결과는 gate 조정에 사용하지 않고 최종 보고만 한다. posture manifest가 충분한 경우 standing/fallen 그룹의 `person` mask Recall도 별도로 보고한다. 이 기준은 실시간 낙상 안전 인증이 아닌 다음 개발 단계 진입 기준이다.

산출물 구조는 다음과 같다.

```text
runs/lego_worker/<run_id>/
├── preflight/
│   ├── dataset_report.json
│   ├── instances.csv
│   ├── posture_candidates.csv
│   └── contact_sheets/
├── config/
│   ├── run.json
│   └── resolved.yaml
├── train/
│   └── weights/{best.pt,last.pt}
├── evaluation/
│   ├── validation_metrics.json
│   └── test_metrics.json
├── artifact_manifest.json
└── status.json
```

`artifact_manifest.json`은 후속 실시간 모듈이 사용할 `best.pt`, class ID/name, imgsz, confidence 후보값, dataset fingerprint와 지표 경로를 제공한다.

## 6. 자동 테스트와 Smoke Test

실제 GPU 없이 실행하는 자동 테스트는 다음을 검증한다.

- 정상 dataset 계약 통과
- 누락 image/label, 범위 밖 좌표, 잘못된 class ID 거부
- train/valid/test content hash 중복 탐지
- 빈 label 통계
- posture manifest 검증과 부족 gate
- 모델 축약명 해석
- resolved config와 dataset fingerprint의 결정성
- run status가 성공·실패를 정확히 나타냄
- 학습 backend를 대체한 fake 결과로 validation/test orchestration과 artifact manifest 생성

GPU smoke test는 실제 컨테이너에서 `--epochs 1`, 작은 batch, 제한된 workers로 전체 orchestration을 확인한다. 이것은 성능 판정이 아니라 코드 경로 검증이다. 실제 성능 평가는 전체 설정으로 별도 실행한다.

## 7. 후속 실시간 파이프라인 계약

학습 gate를 통과한 `artifact_manifest.json`을 입력으로 다음 단계를 구현한다.

```text
Camera / MP4
  → YOLOE person mask
  → ByteTrack worker ID
  → aspect ratio + PCA orientation + calibrated centroid
  → FALL_SUSPECTED / FALLEN
  → centroid displacement + time-window mask IoU
  → IMMOBILE
  → EMERGENCY_CANDIDATE
  → 관제 시스템 관리자 확인 요청
```

AI는 비상을 확정하지 않는다. 관제 요청 payload는 worker ID, zone, fall score, immobile duration, timestamp와 근거 frame/clip reference를 포함한다. 관리자가 확인한 뒤에만 Emergency Manager가 로봇 안전 제어를 수행한다.

정지 이미지 학습 데이터만으로 tracking, 낙상 동작 시점, 무움직임 지속 시간이나 실시간 FPS를 검증했다고 주장하지 않는다. 이 항목은 학습 완료 후 별도 영상 시나리오로 검증한다.

## 8. 안전 경계와 비범위

- POC 모델은 LEGO 전용이며 실제 사람 안전 성능을 주장하지 않는다.
- 기존 dataset 원본을 자동 재배치하거나 덮어쓰지 않는다.
- test split을 학습, early stopping 또는 threshold 선택에 사용하지 않는다.
- 누운 LEGO가 없는 test 결과로 낙상 성능이 검증됐다고 보고하지 않는다.
- 이번 사이클에서는 ROS2 메시지, 관제 UI와 로봇 정지 동작을 구현하지 않는다.
- pose estimation, optical flow와 별도 시계열 신경망은 초기 POC 범위에서 제외한다.

## 9. Python 3.12 / RTX 5080 실행 환경

`origin/env:backend/Dockerfile`의 최종 유효 상태를 기준으로 한다. 해당 Dockerfile은 처음에 CUDA 12.4/PyTorch 2.5를 설치하지만 RTX 5080 `sm_120` 미지원 때문에 마지막에 cu128 PyTorch로 교체한다. 따라서 로컬 전용 환경은 `/home/syw/Trihouse/venv/yolo_segmentation`, Python 3.12, PyTorch cu128로 구성한다. Docker/Compose는 이번 단계에서 만들지 않는다.

학습 시작 전 `torch.cuda.is_available()`, GPU 이름, compute capability, `torch.version.cuda`, `torch.cuda.get_arch_list()`를 확인한다. RTX 5080인데 `sm_120`이 없거나 PyTorch CUDA runtime이 12.8 미만이면 학습을 시작하지 않는다.

## 10. Config와 Multi-seed

`configs/config.yaml`을 단일 사용자 진입점으로 사용한다. strict loader는 알 수 없는 key와 잘못된 타입을 거부하고 최종 설정을 각 run에 저장한다. CLI는 config 경로와 제한된 `--set key=value` override만 받는다.

각 seed는 `PYTHONHASHSEED`가 적용된 별도 subprocess로 실행한다. 모든 학습 성공 seed의 test 지표를 mean, sample standard deviation, min, max로 보고한다. 대표 배포 모델은 validation `mask_map50_95`, validation `mask_recall`, 낮은 seed 순으로만 선택한다. test 지표는 선택에 사용하지 않으며 `selected_model.json`에 이 사실과 선택 근거를 기록한다.

실험 시작 시 `environment.json`에 GPU 모델, driver, driver CUDA capability, PyTorch CUDA runtime, PyTorch/Ultralytics 버전, dataset fingerprint와 Git SHA/dirty 상태를 기록한다.

## 11. 기존 Weight 실시간 검증

실시간 runner는 `selected_model.json`, 단일 run의 `artifact_manifest.json` 또는 직접 지정한 `best.pt`를 읽는다. 웹캠과 MP4를 동일한 source interface로 처리하고 YOLOE `track(..., persist=True, tracker="bytetrack.yaml")` 결과에서 person mask만 취한다. mask 자세 feature와 시간-window 움직임으로 상태를 관리하고 `EMERGENCY_CANDIDATE`를 JSONL로 남긴다. 이 이벤트는 관제 확인 요청 후보이며 로봇 제어를 직접 실행하지 않는다.
