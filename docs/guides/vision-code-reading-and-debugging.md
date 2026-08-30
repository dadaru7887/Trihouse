# 사람·낙상 코드 읽는 순서와 디버깅

> 대상: segmentation + 낙상 감지 코드를 처음 통째로 확인하려는 사람.
> 짝 문서: 판정 기준과 임계값은 [obj_seg_n_person_fallen_detection_architecture.md](../obj_seg_n_person_fallen_detection_architecture.md) §11.

## 0. 먼저 알아야 할 구조 차이

일반적인 ML 저장소는 `main.py` 하나에 `--mode train|eval`이 있다. 여기는 **진입점이 둘로 갈라져 있고, 그게 의도다.**

| | 진입점 | 무엇을 하는가 |
| --- | --- | --- |
| 학습 | `vision_ai.models.perception.trainer.pipeline` | preflight → 학습 → val → gate → test |
| 학습 | `vision_ai.models.perception.trainer.fall_trainer` | 낙상 분류기 학습 |
| 추론 | `vision_ai.robot.perception.worker` | 영상 한 줄기를 받아 사람·낙상 판정 |
| 추론 | `vision_ai.robot.recovery.runtime` | 위 + VLM/RL 복구까지 (5080 운영) |

나눈 이유는 **로봇에 올라가는 프로세스가 학습 코드를 import하지 않게** 하기 위해서다.
`vision_ai/models/recovery/trainer/__init__.py`에 "never imported by physical runtime"이라고 적혀 있고,
[test_inference_boundary.py](../../vision_ai/tests/recovery/test_inference_boundary.py)가 그 경계를 테스트로 지킨다.
`--mode eval`을 만들면 이 경계가 사라진다.

**"eval 모드 = inference"라는 등식도 여기서는 갈라진다.** 둘은 다른 일이다.

- `training.train evaluate` — 학습된 weight를 **고정 데이터셋**에 재는 것 (지표를 낸다)
- `worker` / `runtime` — **들어오는 영상**을 처리하는 것 (지표를 안 낸다, 상태를 낸다)

로봇에 내장됐을 때 도는 것은 후자다.

---

## 1. 읽는 순서 — 학습 경로

각 단계마다 **읽을 파일 → 확인할 것 → 직접 돌려볼 명령** 순이다.
데이터셋 경로는 전부 인자이므로 아래 `$DATA`를 자기 경로로 바꾸면 된다.

```bash
export DATA=/path/to/your/dataset/data.yaml     # YOLO 형식 data.yaml
export RUNS=$PWD/runs/reading                   # 아무 데나
```

### 1-1. 진입점부터 — 전체 지도를 먼저 본다

**읽기**: [training/train.py](../../vision_ai/models/perception/trainer/pipeline.py)

서브커맨드 여섯 개가 곧 파이프라인 단계다. `build_parser()` 하나만 읽으면 전체 그림이 나온다.

```
labels → preflight → run → train → evaluate → analyze
```

**돌려보기** (학습 안 함, 도움말만):
```bash
python -m vision_ai.models.perception.trainer.pipeline --help
python -m vision_ai.models.perception.trainer.pipeline run --help
```

### 1-2. 설정이 어떻게 값이 되는가

**읽기**: [cli.py](../../vision_ai/models/perception/trainer/cli.py) → [run_config.py](../../vision_ai/utils/run_config.py) → [config_loader.py](../../vision_ai/utils/config_loader.py)

- `TrainingConfig`가 하이퍼파라미터 전부다. `__post_init__`에서 검증한다.
- 우선순위는 **CLI 인자 > config yaml**. `--data`가 `dataset.data_yaml`을 이긴다.
- 상대 경로 기준은 **저장소 루트**다(`REPOSITORY_ROOT`). config를 다른 깊이로 옮겨도 안 깨지게 한 것.
- `configs/config.yaml`의 `data_yaml`은 **PLACEHOLDER**다. 실재하는 경로가 아니다.

**확인할 것**: 절대 경로가 코드에 박힌 곳이 있는가 → 없어야 한다.

### 1-3. dataloader — 학습 전에 데이터를 의심한다

**읽기**: [dataloader/audit.py](../../vision_ai/data_loader/perception/audit.py)

`audit_dataset()`이 하는 검사가 이 파이프라인에서 가장 값어치 있는 부분이다.

- `train`/`valid`/`test` split이 data.yaml에 다 있는가
- 라벨 파일이 클래스 개수 범위를 벗어나지 않는가
- **split 사이에 이미지 content hash가 겹치지 않는가** ← 데이터 누수 검사
- 평가 split마다 `fallen` 인스턴스가 최소 개수 이상인가
- 데이터셋 fingerprint(해시)를 남겨 나중에 "무엇으로 학습했나"를 되짚게 한다

**돌려보기** — 학습 없이 데이터만 검사한다. **가장 먼저 이걸 돌려라.**
```bash
python -m vision_ai.models.perception.trainer.pipeline preflight \
    --data "$DATA" --output "$RUNS/preflight_only"
```
성공하면 `[PREFLIGHT 완료] <fingerprint>`, 실패하면 exit 2와 이유가 나온다.

### 1-4. 한 번 학습 — 단일 run의 전 과정

**읽기**: [orchestrator.py](../../vision_ai/models/perception/trainer/orchestrator.py)의 `run_pipeline()`

단계가 코드에 문자열로 박혀 있고 `status.json`에 매 단계 기록된다:

```
PREFLIGHT → TRAIN → VALIDATION → VALIDATION_GATE → TEST → COMPLETE
```

여기서 확인할 것 세 가지:
1. **validation gate** — `min_mask_recall`/`min_mask_map50`을 못 넘기면 기본적으로 거기서 멈춘다.
2. **test는 gate 통과 뒤에 한 번만** 잰다.
3. `artifact_manifest.json`이 weight·fingerprint·지표 경로·gate 통과 여부를 한 파일에 묶는다.

**돌려보기**:
```bash
python -m vision_ai.models.perception.trainer.pipeline run \
    --data "$DATA" --run-root "$RUNS" --name first_try \
    --epochs 1 --batch 2 --workers 0 --device cpu
```
`--epochs 1`로 먼저 **끝까지 흐르는지**만 본다. 성능은 나중이다.

### 1-5. multi-seed — 대표 모델 고르기

**읽기**: [trainer/experiment.py](../../vision_ai/models/perception/trainer/experiment.py) → [multi_seed.py](../../vision_ai/models/perception/trainer/multi_seed.py)

- seed마다 **자식 프로세스**로 `seed_runner`를 띄운다(`PYTHONHASHSEED`까지 고정).
- `select_deployment_model()`은 **`validation_metrics.json`만 읽는다.** test는 선택에 관여하지 않는다.
- 결과가 `selected_model.json`이고, 배포 쪽 `resolve_weights()`가 이 파일을 가리킬 수 있다.

**돌려보기**:
```bash
python -m vision_ai.models.perception.trainer.pipeline train \
    --config vision_ai/models/perception/trainer/configs/config.yaml \
    --data "$DATA" --experiment-dir "$RUNS/multiseed"
```

### 1-6. 낙상 분류기 학습

**읽기**: [person/training/train.py](../../vision_ai/models/perception/trainer/fall_trainer.py)

세그멘테이션과 같은 규율을 훨씬 작은 코드로 반복한다: train으로 맞추고, valid로 임계값 고르고, test는 마지막 한 번.

입력은 피처가 이미 뽑힌 JSONL이다:
```json
{"features": [aspect_ratio, pca_angle, centroid_y, contact_person_iou, contact_obstacle_iou],
 "fallen": true, "split": "train"}
```

피처를 뽑는 쪽은 [features.py](../../vision_ai/models/perception/features.py)다. **좌표계를 반드시 확인하라** — 정규화(0..1) 좌표다.

```bash
python -m vision_ai.models.perception.trainer.fall_trainer \
    --dataset /path/to/features.jsonl --out "$RUNS/fallen" --seed 42 --min-recall 0.85
```

---

## 2. 읽는 순서 — 추론 경로 (로봇에 내장됐을 때)

들어오는 영상 프레임 한 장이 어떻게 상태가 되는지를 순서대로 따라간다.

| 순서 | 파일 | 확인할 것 |
| --- | --- | --- |
| 1 | [runtime/detector.py](../../vision_ai/models/perception/detector.py) | `Detector.detect` — `tracking`이면 `track(persist=True)`. `detections_from_result`가 mask/track_id를 뽑는다 |
| 2 | [person/frame.py](../../vision_ai/robot/perception/frame.py) | `PersonFrameEvaluator.evaluate` — **여기가 허브다.** 사람 선별 → 자세 → 시간축 → 프레임 결론 |
| 3 | [person/posture.py](../../vision_ai/robot/perception/posture.py) | 자세·움직임을 **잰다**. 판정 안 함. `TrackedPostureEstimator`가 track별로 나눔 |
| 4 | [person/features.py](../../vision_ai/models/perception/features.py) | 분류기용 다섯 피처. 정규화 좌표 |
| 5 | [person/classifier.py](../../vision_ai/models/perception/fall_classifier.py) | 번들 적재 + 승인/SHA-256 검증 |
| 6 | [person/fall_monitor.py](../../vision_ai/robot/perception/fall_monitor.py) | 시간축 상태 전이. `advance()` 하나만 읽으면 된다 |
| 7 | [person/policy.py](../../vision_ai/robot/perception/policy.py) | track별 monitor 관리, 소멸 처리 |
| 8 | [person/reporting.py](../../vision_ai/robot/perception/reporting.py) | 무엇을 언제 올릴지 |
| 9 | [person/worker.py](../../vision_ai/robot/perception/worker.py) | 실제 루프. 위를 잇기만 한다 |

**2번을 먼저 읽고 나머지를 거기서 뻗어 나가는 게 빠르다.** `evaluate()` 하나가 3~7을 다 부른다.

**돌려보기** — 영상 파일로 (GPU·로봇 없이):
```bash
python -m vision_ai.robot.perception.worker \
    --weights /path/to/best.pt --source /path/to/video.mp4 --headless
```
`--report-url`을 안 주면 Gateway로 아무것도 안 보내고 stdout JSON만 나온다.

---

## 3. 디버깅

### 3-1. 어디가 문제인지부터 좁힌다

이 파이프라인의 증상은 대부분 **원인에서 멀다.** 순서대로 잘라 본다.

| 증상 | 먼저 확인할 단계 | 확인 방법 |
| --- | --- | --- |
| 학습이 시작조차 안 됨 | dataloader | `train preflight` |
| 학습은 되는데 지표가 이상 | 데이터 누수 / 라벨 | `train labels`, preflight의 split 중복 검사 |
| 낙상을 아예 못 잡음 | 검출 or 자세 | 아래 3-2 |
| 낙상은 잡는데 알람이 안 뜸 | 시간축 | 아래 3-3 |
| 알람이 잘못 뜸 | 자세 판정 | 3-2, 특히 배경 오검출 |

### 3-2. 검출·자세 단계 끊어보기

**GPU도 카메라도 없이 확인 가능한 것들이다.** 이게 이 구조의 요점이다 — 각 단계가 무거운 의존 없이 시험된다.

```python
# 프레임 한 장에서 무엇이 잡혔는가
from vision_ai.models.perception.detector import Detector, DetectorConfig
d = Detector("/path/to/best.pt", DetectorConfig(tracking=True))
for det in d.detect(frame):
    print(det.class_id, round(det.confidence, 3), det.track_id, det.mask.sum())
```

`mask.sum()`이 0이면 mask가 안 왔거나 이진화 임계값 문제다.

```python
# 그 mask 가 "쓰러진 자세"로 읽히는가
from vision_ai.robot.perception.posture import PostureEstimator, PostureConfig
import math
p = PostureEstimator(PostureConfig())
m = p.measure(det.mask, math.hypot(*frame.shape[:2][::-1]))
print(m.aspect_ratio, m.low_posture, m.motion, m.moving)
```

- `low_posture`가 False인데 실제로 누워 있다 → **종횡비 규칙의 recall 구멍**이다. 임계값을 내리지 마라(0.7에서 오탐 확인됨). 분류기를 켜는 게 답이다.
- `moving`이 계속 True → centroid가 흔들리는 것. mask가 프레임마다 크게 달라지는지 본다.

```python
# 분류기가 무엇을 보고 있는가
from vision_ai.models.perception.features import fallen_features, FEATURE_NAMES
f = fallen_features(det, all_detections, frame.shape, person_class_id=1)
print(dict(zip(FEATURE_NAMES, [round(v, 4) for v in f])))
```

**여기서 가장 흔한 함정**: `aspect_ratio`가 `posture.py`의 값과 다르게 나온다. 정상이다 — 하나는 픽셀, 하나는 정규화 좌표다. 프레임이 정사각형이 아니면 `frame_h/frame_w`만큼 차이 난다.

### 3-3. 시간축 끊어보기

`FallMonitor`는 **의존이 하나도 없다.** 영상 없이 그냥 돌려볼 수 있다 — 시간축 문제는 전부 여기서 재현된다.

```python
from vision_ai.robot.perception.fall_monitor import FallMonitor, MonitorConfig
m = FallMonitor(MonitorConfig())
prev = None
for i in range(120):
    t = i / 15.0
    r = m.advance(t, fallen=True, low_motion=True)   # 여기에 의심되는 패턴을 넣는다
    if r["state"] != prev:
        print(f"frame {i:>4} t={t:6.3f}s -> {r['state']}", "EVENT" if r["event"] else "")
        prev = r["state"]
```

실제 영상에서 낙상을 못 잡았다면, 그 구간의 `(fallen, low_motion)` 시퀀스를 여기에 그대로 넣어 재현한다. 재현되면 시간축 문제, 안 되면 앞 단계(3-2) 문제다.

**시간축에서 실제로 겪은 함정 두 가지**:
- `EMERGENCY_CANDIDATE`가 영영 안 뜬다 → 미세 움직임으로 `FALLEN↔IMMOBILE`이 뒤집히는 중. 정지 시계는 `immobile_since`이고 플립으로 리셋되지 않아야 한다.
- 낙상 후 화면 밖에 나갔다 오면 즉시 `NORMAL` → `note_no_detection()`이 안 불리고 있다.

### 3-4. 상태 확인용 파일들

학습 run 디렉터리에 남는 것들. 실패했을 때 여기부터 본다.

| 파일 | 무엇을 알려주는가 |
| --- | --- |
| `status.json` | 어느 단계에서 멈췄는가 (`stage`, `error`) |
| `preflight/` | 데이터셋 검사 결과, fingerprint |
| `environment.json` | GPU/드라이버/패키지 버전 — "어제는 됐는데" 류에 |
| `config/resolved.json` | **실제로 쓰인** 하이퍼파라미터 전부 |
| `config/run.json` | git commit + dirty 여부 |
| `evaluation/validation_metrics.json` | gate 판단 근거 |
| `evaluation/test_metrics.json` | 최종 수치 |
| `artifact_manifest.json` | 배포 후보로서의 요약 |

`config/resolved.json`을 먼저 보는 습관이 좋다 — "내가 준 값이 실제로 들어갔나"가 가장 흔한 착각이다.

### 3-5. 테스트로 좁히기

```bash
# 추론 3단계가 각자 자기 몫만 하는지
pytest vision_ai/tests/worker/test_person_inference_stages.py -v

# 시간축만
pytest vision_ai/tests/worker/test_fall_monitor.py -v

# 다중 인원
pytest vision_ai/tests/worker/test_person_frame_evaluator.py vision_ai/tests/worker/test_person_policy.py -v

# 분류기 적재/학습
pytest vision_ai/tests/worker/test_fallen_classifier.py vision_ai/tests/worker/test_fallen_classifier_training.py -v
```

동작을 바꿨는데 이 테스트들이 그대로 통과한다면, **테스트가 그 동작을 안 잡고 있는 것**이다.
고치기 전에 먼저 실패하는 테스트를 쓴다.

---

## 4. 알려진 함정 모음

| 함정 | 증상 | 실제 원인 |
| --- | --- | --- |
| 좌표계 | 분류기 성능이 학습 때보다 훨씬 나쁨 | 픽셀 좌표를 정규화 자리에 넣음. `aspect_ratio` 계수가 +5.273이라 이것만으로 무너진다 |
| `--data` 미반영 | 엉뚱한 데이터셋으로 학습됨 | config의 PLACEHOLDER를 그대로 씀. `config/resolved.json`으로 확인 |
| tracking 꺼짐 | 다중 인원에서 한 사람만 추적됨 | `track_id`가 비면 최고 confidence 1명만 본다 |
| 환경변수 반쪽 | 런타임이 기동 거부 | `*_BUNDLE`/`*_SHA256`은 **둘 다** 필요. 하나만 주면 일부러 죽는다 |
| 배경 오검출 | 아무도 없는데 낙상 | 금속 체인이 종횡비 3.54로 잡힌 사례 있음. confidence로 안 걸러짐 |
| `contact_obstacle_iou` | 접촉 피처가 효과 없음 | 현재 번들에서 이 계수는 정확히 0이다 (학습 데이터에 해당 사례 없음) |
