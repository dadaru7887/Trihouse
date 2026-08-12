# LEGO Worker Fall Detection MVP Design

## 목적과 범위

최종 목표는 카메라 영상을 실시간으로 받아 LEGO 작업자의 비정상 수평 자세와 무움직임을 감지하는 것이다. LEGO 작업자는 기존 YOLOE-Seg 모델에서 `person`으로 인식하도록 이미 학습됐으며, 학습에는 저조도, motion blur, 색 변화, 결로, glare, 성에와 그 복합 환경을 생성하는 augmentation이 적용됐다.

이번 단계에서는 실시간 기능을 바로 붙이기 전에 **기존 데이터셋의 고정된 test split으로 해당 학습 모델의 성능을 재현 가능하게 평가**한다. 이 결과로 다음 실시간 구현 단계에서 사용할 confidence 기준, 자세 feature 분포와 초기 threshold를 정한다. 시스템은 모든 단계에서 사고를 확정하지 않고 향후 `EMERGENCY_CANDIDATE` 후보 이벤트만 생성한다.

이번 단계의 성공 조건은 다음과 같다.

- `--model`, `--data`, `--split test`를 받는 평가 CLI로 기존 YOLOE 체크포인트를 평가한다.
- Ultralytics의 detection/segmentation 지표인 box·mask Precision, Recall, mAP50, mAP50-95를 JSON과 CSV로 저장한다.
- test split 전체 결과뿐 아니라 데이터셋에 정의된 환경 그룹별 결과를 분리해 저장한다.
- 정답 mask와 예측 mask를 비교하는 표본 overlay를 저장해 수치와 실제 품질을 함께 검토할 수 있다.
- 자세 메타데이터가 제공된 경우 standing/fallen 그룹별 aspect ratio, PCA orientation, centroid feature 분포와 후보 threshold를 계산한다.
- 잘못 검출된 사례와 미검출 사례를 confidence 순으로 저장하여 다음 개선 대상을 확인할 수 있다.
- 평가 명령, 모델·데이터 경로, 실행 시각, Ultralytics 버전과 결과 경로가 실행 기록에 남는다.

웹캠, MP4, ByteTrack, 무움직임 상태 머신과 JSONL 후보 이벤트는 **다음 실시간 구현 단계**의 범위다. 정지 이미지 test split만으로 tracking과 시간 기반 무움직임 성능을 입증했다고 주장하지 않는다.

## 선택한 접근

평가는 기존 학습 코드와 동일한 Ultralytics YOLOE 런타임에서 `model.val(data=..., split="test")`을 호출한다. Ultralytics가 계산한 표준 box·mask 지표를 원본 결과로 보존하고, 별도 evaluator가 이미지별 예측 결과와 데이터셋 메타데이터를 결합해 환경 그룹 및 자세 그룹 지표를 만든다.

평가 코드는 이후 실시간 판정에서도 재사용할 `person` mask feature 추출기를 함께 만든다. 이 단계에서는 정답/예측 mask에서 정적인 자세 feature만 계산하고, tracking 또는 immobility를 흉내 내지 않는다. OpenCV 색상/윤곽 검출기나 새 학습 파이프라인도 추가하지 않는다.

## 구성 요소와 책임

### 평가 입력 계약

필수 입력은 학습된 `best.pt`와 기존 데이터셋의 `data.yaml`이다. `data.yaml`에는 평가에 사용할 `test` split과 LEGO 작업자에 대응하는 `person` class가 있어야 한다. test split이 없으면 validation split으로 묵시적으로 대체하지 않고 명확히 실패한다. 학습에 사용한 train/val 이미지를 test 결과에 섞지 않는다.

환경별 평가를 위해 선택적인 manifest CSV를 받는다.

```csv
image,environment,posture
images/test/ambient_001.jpg,normal_light,standing
images/test/dark_001.jpg,low_light,standing
images/test/frost_001.jpg,frost,fallen
```

- `image`: data.yaml 기준 이미지 상대 경로
- `environment`: `normal_light`, `low_light`, `motion_blur`, `color_shift`, `condensation`, `glare`, `frost`, `combined` 중 하나
- `posture`: `standing`, `fallen`, `unknown` 중 하나

manifest가 없으면 표준 YOLO 지표만 산출한다. 파일명에서 환경이나 자세를 추측하지 않는다. manifest에 test split 밖의 이미지, 중복 이미지, 알 수 없는 그룹값이 있으면 평가 전에 실패한다.

### 정적 자세 Feature 추출

한 worker mask에서 다음 값을 계산한다.

- bbox 폭/높이 비율
- mask pixel PCA 주축의 수평 기준 각도(0~90도)
- mask 중심점의 정규화 좌표
- 영상 하단에서 중심점까지의 정규화 거리
- mask area와 이미지 대비 면적 비율

mask가 비어 있거나 최소 면적보다 작으면 feature 계산 대상에서 제외하고 그 사유를 기록한다. 바닥선 calibration이 없는 정적 데이터셋 평가에서는 centroid-height를 낙상 판정 점수에 바로 사용하지 않고 분포만 기록한다.

posture manifest가 있는 경우 standing과 fallen의 feature 분포를 비교한다. 단일 고정 threshold는 test split을 보고 최적화하지 않는다. 가능하면 별도 calibration/validation split에서 후보 threshold를 구하고 test split에는 고정 적용한다. 별도 split이 없다면 test에서 계산한 값은 `exploratory_threshold`로 명시하며 최종 성능으로 보고하지 않는다.

### 평가 지표와 결과물

표준 결과는 다음을 포함한다.

- box: Precision, Recall, mAP50, mAP50-95
- mask: Precision, Recall, mAP50, mAP50-95
- 이미지 수, 정답 instance 수, 예측 instance 수
- confidence threshold와 IoU threshold
- 전체 및 환경 그룹별 지표
- posture metadata가 있을 때 standing/fallen feature 요약 통계와 exploratory threshold

출력 디렉터리 구조는 다음과 같다.

```text
artifacts/fall_detection_eval/<run_id>/
├── run.json
├── metrics.json
├── metrics_by_environment.csv
├── posture_features.csv
├── errors.csv
└── overlays/
```

`run.json`에는 모델 경로와 SHA-256, data.yaml 경로, split, device, imgsz, batch, confidence/IoU 설정, 패키지 버전과 시작·종료 시각을 기록한다. `errors.csv`는 false negative, false positive, 낮은 mask IoU 사례를 이미지 단위로 정렬한다. overlay는 전체를 무제한 저장하지 않고 그룹별 최악 사례와 고정 seed 표본을 저장한다.

### 평가 CLI

```bash
python -m vision_perception.fall_detection.evaluate \
  --model /path/to/best.pt \
  --data /path/to/data.yaml \
  --split test \
  --manifest /path/to/test_manifest.csv \
  --device 0 \
  --output artifacts/fall_detection_eval
```

`--manifest`는 선택 사항이다. 실행기는 입력 존재 여부와 dataset 계약을 먼저 검사하고, 평가 중간 실패 시 완료된 결과처럼 보이는 `metrics.json`을 만들지 않는다. 성공 시 생성된 run 디렉터리와 핵심 전체 지표를 콘솔에 출력한다.

## 테스트 전략

단위 테스트는 실제 GPU 모델을 요구하지 않는다.

- 세로/가로 합성 직사각형 mask로 aspect ratio와 PCA orientation을 검증한다.
- 빈 mask와 너무 작은 mask가 제외 사유와 함께 처리되는지 검증한다.
- data.yaml의 test split 및 `person` class 계약을 검증한다.
- manifest의 경로, 중복, 허용 환경·자세 값을 검증한다.
- 환경 그룹 집계가 전체 집계와 일관되는지 검증한다.
- 실행 metadata와 metrics JSON/CSV 스키마를 검증한다.
- 고정 seed overlay 표본과 최악 오류 선택이 재현되는지 검증한다.

GPU 통합 smoke test는 실제 기존 체크포인트와 데이터셋으로 최소 이미지 수 제한을 걸어 CLI 전체 경로를 확인한 다음 전체 test split 평가를 실행한다. 최종 검증 증거는 명령, 종료 코드, run ID와 생성된 결과 파일이다.

초기 POC 통과 기준은 `person` mask Recall 0.90 이상, mask mAP50 0.80 이상, manifest에 20개 이상의 정답 instance가 있는 각 환경 그룹의 mask Recall 0.80 이상이다. 표본 수가 20개 미만인 그룹은 `INSUFFICIENT_SAMPLE`로 표시하며 통과로 계산하지 않는다. 이 값은 실시간 안전 성능의 인증 기준이 아니라, 다음 단계의 영상 수집·tracking 실험으로 넘어가기 위한 개발 gate다.

## 실패 처리와 안전 경계

- 모델, data.yaml 또는 test split을 열 수 없으면 구체적인 경로와 함께 평가 전에 실패한다.
- test split 누락을 validation split으로 자동 대체하지 않는다.
- 정답 mask가 없는 데이터로 segmentation 성능을 평가했다고 보고하지 않는다.
- posture manifest가 없으면 낙상 자세 정확도를 계산했다고 보고하지 않는다.
- 정지 이미지 평가로 tracking·무움직임·실시간 FPS가 검증됐다고 보고하지 않는다.
- test split으로 선택한 threshold는 탐색값으로 표시하고 독립 test 성능처럼 표현하지 않는다.

## 후속 통합

데이터셋 평가가 기준을 충족하면 다음 단계에서 기존 `inference_stream.py`의 capture·stream health 정책을 재사용하고 YOLOE `track(..., persist=True, tracker="bytetrack.yaml")`를 연결한다. 이때 웹캠과 MP4 입력, worker별 상태 머신, centroid displacement와 시간-window mask IoU, 화면 overlay와 JSONL 후보 이벤트를 구현한다.

그 다음 `WorkerState.msg`, `FallEvent.msg`를 `trihouse_interfaces`에 추가하고 같은 event interface를 ROS2 publisher로 구현한다. 관제 UI의 관리자 확인 service와 Emergency Manager 연결은 후보 이벤트 검증 후 진행한다. Optical flow, 다중 카메라 re-identification과 custom keypoint 모델은 측정 결과가 필요성을 입증한 경우에만 추가한다.
