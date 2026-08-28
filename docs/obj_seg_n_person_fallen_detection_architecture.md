# 사람·장애물 Segmentation + 낙상 감지 아키텍처 코드 읽기 노트

> 목적: Trihouse의 segmentation → 낙상 감지 흐름을 코드 근거로 이해하고, 이후 포트폴리오·LinkedIn·면접에서 **구현된 내용 / 검증된 내용 / 설계·계획**을 구분해 설명하기 위한 조사 노트다.
>
> 작성 규칙: 모든 사실에 `파일 경로:함수/클래스`를 남긴다. 실행하지 않고 코드만 읽은 내용은 `코드상 확인`, 실제 실행·측정한 내용은 `실행 검증`, 아이디어만 있는 내용은 `설계/계획`으로 표시한다. 이 노트는 2026-08-28 기준 코드를 읽고 채웠고, 남은 `[확인 필요]`는 GPU·가중치·영상이 있어야 확인 가능한 항목이다.
>
> 짝 문서: VLM+RL 복구 흐름은 [trihouse_vlm_rl_architecture.md](trihouse_vlm_rl_architecture.md).

---

## 0. 한 문장 요약

카메라 프레임에서 YOLOE-seg가 사람/장애물 mask를 내고(`nc=2`), 사람 mask의 **기하 특징(bbox 종횡비, PCA 주축 각도, centroid 높이)과 접촉 특징(사람-사람/사람-장애물 IoU)** 으로 "지금 쓰러진 자세인가"를 판정한 뒤, **시간축 상태머신**이 그 판정을 누적해 `NORMAL → FALL_SUSPECTED → FALLEN → IMMOBILE → EMERGENCY_CANDIDATE`로 전이시킨다. 최종 산출물은 로봇 제어가 아니라 **관제 확인 요청**이다.

**중요한 구분**: 위 문장에서 PCA·접촉 피처·분류기는 `dev_vision` 배달본(2026-08-24)에만 있고, **운영 코드에는 아직 없다.** 운영 코드는 종횡비 규칙 하나만 쓴다. 자세한 경계는 §6.

---

## 1. 저장소에서의 위치

| 역할 | 실제 파일·모듈 | 진입 함수/클래스 | 상태 |
| --- | --- | --- | --- |
| 세그멘테이션 추론 | [model/perception/segmentation/runtime/detector.py](../model/perception/segmentation/runtime/detector.py) | `Detector.detect` / `detect_person` | 코드상 확인 |
| 세그멘테이션 학습 | [model/perception/segmentation/training/](../model/perception/segmentation/training/) | `orchestrator.py`, `seed_runner.py` | 코드상 확인 |
| 자세 **측정** | [model/worker/person/posture.py](../model/worker/person/posture.py) | `PostureEstimator.measure` | 코드상 확인 |
| 시간축 **판정** | [model/worker/person/fall_monitor.py](../model/worker/person/fall_monitor.py) | `FallMonitor.advance` | 코드상 확인 |
| 다중 인원 정책 | [model/worker/person/policy.py](../model/worker/person/policy.py) | `PersonPolicy` | 코드상 확인 |
| 프레임 평가(사람별) | [model/worker/person/frame.py](../model/worker/person/frame.py) | `PersonFrameEvaluator.evaluate` | 코드상 확인 |
| 보고 스로틀 | [model/worker/person/reporting.py](../model/worker/person/reporting.py) | `ReportThrottle.should_report` | 코드상 확인 |
| 독립 실행 worker | [model/worker/person/worker.py](../model/worker/person/worker.py) | `main` | 코드상 확인 |
| VLM+RL 런타임 내 보고 | [model/vlm_rl/inference/live_runtime.py](../model/vlm_rl/inference/live_runtime.py) | `PersonSafetyReporter` | 코드상 확인 |
| 원본 배달본(보관) | [vision_system/person_worker/upstream_dev_vision/](../vision_system/person_worker/upstream_dev_vision/) | — | 보관만, import 안 됨 |

원본은 `dev_vision:fallen_detection_delivery`, 기준 커밋 `3f0ce0a`(2026-08-24). 23MB 가중치 `segmentation_finetuned_seed2026_best.pt`는 저장소 관례(가중치는 `/models` 마운트로 전달, LFS 미사용)에 따라 보관본에서 제외했다 — sha256 `07d5ecc31910185166506be180dd322c43f5d1eb4ad66a9cb9d44756a17a1224`.

---

## 2. End-to-End 흐름

```text
카메라 프레임 (RTSP 또는 mp4)
  → YOLOE-seg 추론 + tracking   detector.py:Detector.detect  (tracking=True → track(persist=True))
  → 사람 전원, track_id 별로     frame.py:PersonFrameEvaluator.evaluate
       ├ 자세·움직임 측정        posture.py:TrackedPostureEstimator.measure
       └ 시간축 상태 전이        policy.py:PersonPolicy.observe → fall_monitor.py:FallMonitor.advance
  → 프레임 결론 = 가장 나쁜 상태 frame.py:FrameVerdict
  → 스로틀링 후 보고            reporting.py:ReportThrottle.should_report
  → Gateway POST               /internal/v1/vision/person-detections
```

| 단계 | 실제 입력 | 실제 출력 | 파일:함수 |
| --- | --- | --- | --- |
| 1. 검출 | BGR 프레임 | `Detection(class_id, confidence, mask)` 목록 | `detector.py:detections_from_result` |
| 2. 사람 선택 | `Detection` 목록 | 최고 confidence 사람 1건 or `None` | `detector.py:select_best` |
| 3. 자세 측정 | bool mask, 프레임 대각선 | `PostureMeasurement(aspect_ratio, centroid, motion, low_posture, moving)` | `posture.py:mask_geometry` |
| 4. 시간축 판정 | `(timestamp, fallen, low_motion)` | `{state, previous_state, event}` | `fall_monitor.py:advance` |
| 5. 보고 | 상태 + confidence | JSON payload | `worker.py:main` / `live_runtime.py:PersonSafetyReporter.observe` |

---

## 3. Segmentation: 무엇을 보고, 무엇을 내는가

### 3-1. 클래스 정의

`nc=2`, `names: ['obstacle', 'person']` → `person_class_id: 1`. 클래스 순서가 바뀌면 설정만 바꾸면 되도록 코드에 숫자를 박지 않았다 ([detector.py:DetectorConfig](../model/perception/segmentation/runtime/detector.py)). 이 정의는 원본 배달본의 파인튜닝 모델과도 동일해서 **drop-in 교체가 가능**하다(원본 README 주장, 미검증).

### 3-2. 추론 설정

[model/worker/configs/realtime.yaml](../model/worker/configs/realtime.yaml) 기준: `confidence: 0.25`, `image_size: 640`, `device: auto`.

무거운 import(`ultralytics`, `torch`)는 `Detector.load()` 안에서만 한다 — GPU 없는 곳에서도 모듈을 읽고 시험할 수 있게 하려는 의도적 설계다.

### 3-3. 학습

multi-seed 실험: seeds `[17, 42, 101, 2026, 3407]`, YOLOE `26s`, epochs 200, patience 20. 대표 모델 선정 기준은 `person_mask_map50_95`(동점 시 `person_mask_recall`), validation gate는 `min_mask_recall: 0.70` / `min_mask_map50: 0.60` ([configs/config.yaml](../model/perception/segmentation/training/configs/config.yaml)).

대표 모델은 `selected_model.json`으로 남고 배포 쪽이 그 파일을 가리킬 수 있다 — seed를 바꿔 학습해도 배포 명령이 안 바뀌게 하려는 설계 ([detector.py:resolve_weights](../model/perception/segmentation/runtime/detector.py)).

---

## 4. 낙상 판정: 두 층으로 나눈 이유

### 4-1. 측정과 판정의 분리

`posture.py`는 **재기만** 하고, `fall_monitor.py`가 **결론**을 낸다. 코드 주석이 이유를 명시한다: 자세 판정이 언젠가 규칙에서 모델로 바뀌기 때문에, 그때 바뀌는 파일이 `posture.py` 하나여야 한다. — 그리고 이 예측은 실제로 맞았다. 배달본의 분류기가 정확히 그 교체다(§6).

### 4-2. 운영 코드의 자세 판정 (규칙)

bbox 가로/세로 비 ≥ `fall_aspect_ratio`(0.9)면 누운 자세. centroid 이동량 / 프레임 대각선 ≤ `motion_threshold`(0.015)면 정지.

종횡비는 bbox로, centroid는 **픽셀 평균**으로 잰다 — bbox 중심을 쓰면 팔다리 하나가 튀어나올 때 중심이 크게 흔들려 정지를 움직임으로 오독한다는 게 코드에 적힌 근거다.

**실행 검증된 한계** (`posture.py` 문서화, 2026-08-18~19 실측):
- `fall_aspect_ratio`를 0.7까지 내리면 `re_2`에서 오탐 발생 → **0.9 밑으로 내리지 않는다.**
- 비율이 임계값 밑이면 애초에 의심 단계에 못 들어간다. 이 recall gap은 시간축 로직으로 못 고친다 — **2차 신호가 필요하다.** (배달본의 분류기가 이 2차 신호다.)
- `re_3` t=74s에서 벽의 금속 체인이 비율 3.54로 잡혔고 confidence로 안 걸러졌다(conf ≥ 0.25).

### 4-3. 시간축 상태머신

```text
NORMAL ──fallen──> FALL_SUSPECTED ──1.0s 유지──> FALLEN ──low_motion──> IMMOBILE
                                                    ↑                      │
                                                    └──not low_motion──────┘
                                                                           │ 5.0s 유지
                                                                           ↓
                                                              EMERGENCY_CANDIDATE
```

- `NORMAL`/`FALL_SUSPECTED`에서 "안 넘어짐"이 나오면 **즉시** 리셋 (안전 증거가 아직 없음).
- `FALLEN`/`IMMOBILE`/`EMERGENCY_CANDIDATE`에서는 `recovery_confirm_seconds`(1.0s) **연속** "안 넘어짐"이어야 `NORMAL`로 복귀. 노이즈 한 프레임에 안전 증거가 지워지지 않게 하려는 디바운스다.
- `EMERGENCY_CANDIDATE` 이벤트는 `event_sent` 플래그로 **한 번만** 발행.

### 4-4. 보고 스로틀

상태가 그대로면 TTL 절반 주기로만 올린다. 코드 주석의 근거: 15 Hz를 그대로 흘리면 **TCP 8788이 관측으로 차서 주행 명령이 뒤로 밀린다** ([worker.py:main](../model/worker/person/worker.py)). 단, `EMERGENCY_CANDIDATE` 이벤트는 스로틀을 우회해 항상 올린다.

---

## 5. 지금 코드에서 확인된 갭

읽으면서 발견한, 문서에 안 적혀 있던 사실들이다.

### 5-1. 다중 인원 — 해결 (2026-08-29)

**이전 상태**: [policy.py:PersonPolicy](../model/worker/person/policy.py)는 `(camera_id, track_id)`별 독립 `FallMonitor`를 두는 다중 인원 설계를 이미 갖고 있었는데, import하는 곳이 자기 단위 테스트뿐이었다. 운영 경로 둘 다 `FallMonitor` 하나를 공유하고 `select_best`로 1명만 봐서, **두 사람이 있으면 한 사람의 회복이 다른 사람의 증거를 지웠다.**

이식하면서 드러난 것은 단일 인물 가정이 세 겹이었다는 점이다.

1. `Detection`에 `track_id`가 없었다 → `Detector`에 `tracking` 옵션 추가. 켜면 `predict` 대신 `track(persist=True)`로 돌린다. `persist=True`가 없으면 tracker가 프레임마다 번호를 다시 매겨 신원이 아니게 된다.
2. `PostureEstimator`가 `_last_centroid`를 **하나만** 들고 있었다 → `TrackedPostureEstimator`. 걸어가는 사람의 위치가 가만히 누운 사람의 이동량으로 읽히던 문제다.
3. `PersonPolicy`에 track 소멸 처리가 없었다 → `note_present_tracks()`. 잠깐 안 보이면 회복 시계만 멈추고(§6-2의 `note_no_detection`), `track_timeout_seconds`(3.0s)를 넘기면 그 사람 몫 상태를 버린다.

이 셋을 잇는 것이 [frame.py:PersonFrameEvaluator](../model/worker/person/frame.py)이고, 호출부 둘이 이제 이것만 쓴다. 프레임 하나의 결론은 **그 화면에서 가장 나쁜 상태**다 — 서 있는 행인이 바닥에 누운 사람을 가려서는 안 된다.

tracking이 꺼져 있으면 `track_id`가 비고, 전원을 빈 id 하나에 몰면 고치려던 버그가 그대로 재현된다. 그래서 그때는 예전처럼 `select_best`로 한 명만 본다 — 다중 인원 상태는 tracking이 켜져 있어야만 성립한다.

**남은 한계**: ReID가 없어 카메라가 `track_timeout_seconds` 넘게 끊기면 같은 사람이 새 track_id를 받아 상태머신이 새로 시작한다. 원본도 구조적 한계로 인정한 부분이다.

### 5-2. `MonitorConfig.fall_aspect_ratio`는 운영에서 죽은 값 — 코드상 확인

`fall_monitor.py`의 기본값은 `1.2`, `posture.py`의 기본값은 `0.9`로 서로 다르다. 그런데 `MonitorConfig.fall_aspect_ratio`는 `FallMonitor.update()`에서만 쓰이고, 운영 경로 둘은 모두 `advance()`를 직접 호출하며 `fallen` 판정을 `posture.py`에서 받아온다. **따라서 1.2는 실행되지 않는다.** 값이 둘로 갈라져 있는 것 자체가 혼동 위험이다.

### 5-3. 낙상 이벤트는 기록되지 않고 중계만 된다 — 코드상 확인

VLM+RL은 `recovery_proposals` 등 전용 테이블이 있는데, 낙상 쪽은 다르다. `/internal/v1/vision/person-detections`([main.py:257](../fms_gateway/app/main.py#L257))는 관측을 받아 `config/cameras.yaml`의 `attached_to`로 해당 **로봇에 밀어 넣는 실시간 중계**다. 5080이 로봇에 직접 꽂히지 못하게 하려는 경계(`VLM/RL → Safety Supervisor 우회` 금지)이기도 하다.

`pose_class`는 [models.py:927](../fms_gateway/app/models.py#L927)의 pydantic 필드로만 존재하고, 이 값을 쓰는 SQL은 저장소에 없다. 즉 **`EMERGENCY_CANDIDATE`는 로봇을 감속시키고 사라진다** — 나중에 "그날 몇 시에 누가 쓰러졌나"를 되짚을 기록이 없다. 이게 의도인지(안전 반응만 필요) 누락인지 [확인 필요].

---

## 6. 원본 배달본이 가진 것 vs 운영 코드

배달본은 [vision_system/person_worker/upstream_dev_vision/](../vision_system/person_worker/upstream_dev_vision/)에 원본 그대로 보관돼 있고, **운영 코드는 이 중 아무것도 쓰지 않는다.**

| 구성 요소 | 배달본 | 운영 코드 |
| --- | --- | --- |
| 자세 신호 | 분류기 5개 피처 | **이식 완료** — 분류기 켜면 5개, 끄면 종횡비 1개 |
| PCA 주축 각도 | 있음 | **이식 완료** |
| centroid 높이 | 있음 | **이식 완료** |
| 접촉 IoU (사람-사람 / 사람-장애물) | 있음 | **이식 완료** |
| 판정기 | logreg (`joblib`) | **이식 완료** (기본 꺼짐, §6-4) |
| 다중 인원 | `track(persist=True)` + track_id별 모니터 | **이식 완료** (2026-08-29, §5-1) |
| `note_no_detection()` | 있음 | **이식 완료** (2026-08-29) |
| 오실레이션 안전장치 | `fallen_since` | **`immobile_since`** (의미 보존, §6-2) |

### 6-1. 분류기가 쓰는 5개 피처

[classifier_trainer.py:polygon_to_geometric_features](../vision_system/person_worker/upstream_dev_vision/code/classifier_trainer.py)

1. `aspect_ratio` — bbox 가로/세로 (운영 코드와 같은 신호)
2. `pca_angle` — polygon 공분산 행렬의 `eigh` → 최대 고유값 고유벡터의 각도(`% 180`). **mask의 주축 방향** = 사람이 누운 방향.
3. `centroid_y` — mask 중심의 세로 위치. 추가 근거가 코드에 있다: "모양이 어떻게 생겼나"인 aspect_ratio/각도와 달리 "화면 어디에 있나"라는 **독립 축**이라 중복 위험이 적다. (elongation은 aspect_ratio와 사실상 같은 정보라 효과가 없었다고 기록됨.)
4. `contact_person_iou` — 다른 **사람** 인스턴스와의 최대 bbox IoU
5. `contact_obstacle_iou` — **장애물** 인스턴스와의 최대 IoU

접촉 피처를 넣은 이유가 실측으로 남아 있다 — **실행 검증**: 171307 "기대는 낙상"에서 기대기 전 IoU=0.000 → 기댄 뒤 0.05~0.13대로 꾸준히 상승했고 GT 타임라인과 일치. 같은 구간에서 aspect_ratio는 거의 무신호였다. 사람-사람과 사람-장애물을 나눈 것은 신뢰도가 다를 것이라는 판단(사람-사람이 더 확실)에서 분류기가 각각 다른 가중치를 배우게 하려는 것이다.

### 6-2. 배달본이 고친 두 버그 — 이식 완료 (2026-08-29)

1. **`note_no_detection()`** — 탐지가 끊긴 프레임에서 `recovery_since`를 리셋한다. 없으면 사람이 화면 밖에 있던 wall-clock 시간이 "정상이었다"는 증거로 잘못 인정된다. 2026-08-24 실측: 낙상 후 사람이 나갔다 4초 뒤 돌아왔는데 그 4초가 통째로 `recovery_confirm_seconds`를 만족시켜 한 프레임 만에 `NORMAL`로 튀었다. **원본과 동일하게 이식**했고, 호출부 두 곳([worker.py:note_person_lost](../model/worker/person/worker.py), [live_runtime.py:PersonSafetyReporter.observe](../model/vlm_rl/inference/live_runtime.py))에 배선했다.

2. **오실레이션 버그** — 숨쉬기 같은 미세 움직임으로 `FALLEN ↔ IMMOBILE`을 오가면 매번 `since`가 리셋돼, 14초 넘게 쓰러져 있었는데도 5초 연속을 한 번도 못 채워 `EMERGENCY_CANDIDATE`가 **영영 안 뜬다**(170622 실측). 원본은 `fallen_since`(첫 `FALLEN` 진입 시각)로 풀었다.

   **여기서는 `immobile_since`(첫 `IMMOBILE` 진입 시각)로 풀었다 — 의도적으로 원본과 다르다.** 원본 방식은 `immobile_seconds`의 의미를 "정지가 지속된 시간"에서 "넘어진 뒤 경과한 시간"으로 바꾼다. [test_person_policy.py](../model/worker/tests/test_person_policy.py)가 전자를 명시적으로 문서화하고 있었고("자세 확정 1초 → 정지 지속 5초 → 확정 후보"), 원본 방식을 그대로 넣자 그 테스트가 깨졌다. 낙상 후 버둥거리는 사람은 아직 "일어나지 못하고 있는" 것이 아니므로 의미를 보존하는 쪽을 택했다.

   `immobile_since`는 `FALLEN ↔ IMMOBILE` 플립으로는 리셋되지 않고 **진짜 회복(`NORMAL` 복귀)에서만** 리셋된다. 오실레이션 버그는 원본과 동일하게 해결되며, 기존 테스트도 그대로 통과한다. 이 선택은 [test_fall_monitor.py](../model/worker/tests/test_fall_monitor.py)의 `test_the_escalation_clock_measures_stillness_not_time_since_falling`으로 고정해 뒀다.

### 6-4. 피처와 분류기 이식 (2026-08-29)

[features.py](../model/worker/person/features.py)가 다섯 피처를, [classifier.py](../model/worker/person/classifier.py)가 번들 적재를 맡는다. 이식하면서 걸린 것 두 가지.

**좌표계가 계약의 일부다.** 배달본은 학습·추론 모두 ultralytics의 `masks.xyn`/`boxes.xyxyn`, 즉 프레임 크기로 나눈 0..1 좌표에서 쟀다. 우리 `posture.py`는 픽셀 좌표에서 잰다. 프레임이 정사각형이 아니면 두 값이 다르다 — 640×480에서 200×100 mask의 종횡비는 픽셀로 2.0, 정규화로 1.5다. `aspect_ratio`는 번들 계수가 **+5.273으로 압도적**이라 픽셀 비율을 그대로 넣으면 가장 강한 신호가 조용히 틀어진다. 그래서 분류기용 피처는 정규화 좌표로 재고, 규칙 경로는 픽셀 기준을 그대로 뒀다 — `posture.py`의 0.9는 픽셀 비율 위에서 실측된 값이라 기준을 바꾸면 그 측정이 무효가 된다.

**`contact_obstacle_iou`는 이 번들에서 죽은 피처다.** 계수가 정확히 `0.000`, scaler 평균도 `0.0000` — 학습 데이터에서 사람이 장애물과 겹친 인스턴스가 하나도 없었다는 뜻이다. 코드는 값을 계산해 넘기지만 이 번들은 그 값을 쓰지 않는다. "선반에 기대어 쓰러진" 경우를 잡는 신호는 실질적으로 `contact_person_iou`(계수 +0.335)뿐이다. 데이터가 더 모이면 재학습이 필요한 지점이다.

적재는 저장소의 다른 승인 산출물과 같은 절차를 밟는다 — 승인 플래그 + SHA-256, 그리고 번들이 프롬프트 피처를 요구하거나 피처 개수가 다르면 거절. 임계값은 0.5로 덮어쓰지 않고 학습 때 k-fold로 고른 `bundle["threshold"]`를 쓴다.

기본은 **꺼짐**이다. `FALLEN_CLASSIFIER_BUNDLE`과 `FALLEN_CLASSIFIER_SHA256`을 둘 다 설정해야 켜지고, 하나만 설정하면 기동을 거부한다. 꺼져 있으면 종횡비 규칙 그대로다.

움직임 판정은 분류기가 켜져도 `posture.py`가 계속 맡는다 — 분류기는 한 프레임만 보므로 시간축 신호를 낼 수 없다.

### 6-3. 규칙 OR를 뺀 이유 — 실행 검증

배달본 `video_monitor.py`는 최종적으로 `fallen = 분류기(proba ≥ threshold)`만 쓴다. 규칙과의 OR를 뺀 근거: 실측 결과 **분류기 판정 영역이 규칙을 완전히 포함**해서 결합이 무의미했다.

임계값은 임의값 0.5가 아니라 학습 시 k-fold로 고른 값을 `joblib` 번들에서 읽는다(`bundle["threshold"]`).

---

## 7. 검증 현황: 주장 가능한 범위

[configs/final_metrics.json](../vision_system/person_worker/upstream_dev_vision/configs/final_metrics.json) 기준. 아래는 **원본이 보고한 수치**이며 이 저장소에서 재현하지 않았다.

### 분류기 (test split 161 instances, fallen 37)

| 구간 | precision | recall |
| --- | --- | --- |
| 전체 | 0.535 | 0.622 |
| **비가려짐** | **0.875** | **0.840** |
| 가려짐 | 0.105 | 0.167 |

가려짐은 단일 프레임 분류기의 **구조적 한계로 인정하고 범위에서 제외**했다(depth나 시간축 정보 필요). 비가려짐 수치가 목표(0.7~0.8)를 넘었다는 게 원본의 결론이다.

### 파인튜닝 전후 (Track A 효과)

| 지표 | 전 | 후 |
| --- | --- | --- |
| segmentation person recall | 0.604 | **0.881** |
| end-to-end recall (37 fallen) | 0.378 | **0.595** |
| 규칙만(분류기 없이) recall | 0.162 | **0.324** |

### 실제 영상 검증 — 실행 검증(원본)

- **170622**: t=17.60s(이론값과 소수점까지 일치), t=69.90s 정확히 감지
- **171307**: leaning형 낙상을 t=29.60s 감지 — 다중인원 추적 + 접촉 피처로 최초 성공
- **162137**: 긴 낙상(16s/31s) 전부 감지, 5초 경계 테스트 통과
- **162744**: 짧은 낙상(각 ~4s)에 `EMERGENCY_CANDIDATE` 미발생 — 설계 의도대로. 단 t=9.15s에 **실제 오탐 1건**

### 말하면 안 되는 것

- 위 수치를 "Trihouse 운영 시스템의 성능"으로 말할 수 없다. 운영 코드는 분류기를 안 쓴다.
- 가려짐 상황 성능(precision 0.105)을 빼고 전체 수치만 인용하면 안 된다.
- 이 저장소에서 재현하지 않았다 — 23MB 가중치와 Roboflow export가 없다.

---

## 8. 알려진 미해결 문제 (원본 기록)

1. **회복 인식 지연** — 일어난 뒤에도 몇 초간 "쓰러짐"으로 오판. 162744 t=9.15s 오탐 1건 확인, **원인 미해결**. `posture_change_threshold`(기본 0.15)를 시도했으나 이 케이스는 해결 안 됨 — 코드에 남아 있지만 완전한 해결책이 아니다.
2. **track_id 재식별 불가** — 카메라가 10초 이상 끊긴 뒤 같은 사람이 돌아오면 새 track_id를 받아 상태머신이 새로 시작된다. ReID 없이는 구조적 한계로 인정.
3. **시간 임계값 재보정 미착수** — `fall_confirm_seconds`(1.0)/`immobile_seconds`(5.0)/`motion_threshold`(0.015)는 원본 repo 기본값 그대로. `event_intervals.csv`가 더 채워져야 재보정 가능(현재 8개 영상 중 일부만 채워짐).
4. **가려짐** — 범위에서 제외 (§7).

---

## 9. 병합하려면 남은 일 — 설계/계획

원본 README의 병합 지침과, 이 저장소 코드를 읽고 확인한 것을 합친 것이다.

### 9-1. 배달본은 그대로 실행되지 않는다 — 코드상 확인

배달본 `code/`는 평평한 디렉터리인데, 그 안의 import는 원래 패키지 레이아웃을 가리킨다:

```
code/video_monitor.py       → from pipeline.fall_monitor import ...
                              from trainer.classifier_trainer import ...
code/classifier_trainer.py  → from dataloader.roboflow_labels import ...
code/eval_end_to_end.py     → from dataloader.roboflow_labels import ...
```

`pipeline/`, `trainer/`, `dataloader/` 패키지가 배달본에 없으므로 README의 `python -m code.video_monitor` 예시는 **그대로는 실패한다.** 이식할 때 import 경로부터 재배선해야 한다.

### 9-2. 작업 순서 (제안)

1. ~~**버그 픽스 먼저**~~ — **완료 (2026-08-29)**. §6-2 참고.
2. ~~**다중 인원 배선**~~ — **완료 (2026-08-29)**. §5-1 참고.
3. ~~**피처 확장**~~ — **완료 (2026-08-29)**. §6-4 참고.
4. ~~**분류기 도입**~~ — **완료 (2026-08-29)**. §6-4 참고.
5. **가중치 배포** — 23MB 파인튜닝 가중치를 `/models` 마운트에 두고 `SEGMENTATION_WEIGHTS_FILE`로 가리킨다. 원본 권고는 기존 `aug_best.pt`를 **대체하지 말고 병행 검증**부터.

### 9-3. 확인 필요

- `EMERGENCY_CANDIDATE`가 관제 화면·DB에 어떻게 남는가 — 전용 테이블이 없다 (§5-3).
- 파인튜닝 가중치가 정말 drop-in 호환인가 — 원본 주장이며 이 저장소에서 미검증.
- 배달본 `event_intervals.csv`의 GT가 몇 개 영상까지 채워졌는가 — 재보정 착수 가능 시점을 정한다.

---

## 10. 읽기 완료 체크

- [x] segmentation 클래스 정의와 추론 설정을 코드에서 확인
- [x] 자세 측정 / 시간축 판정의 분리 이유를 코드 주석 근거로 확인
- [x] 상태머신 전이 조건 5개를 코드에서 확인
- [x] 운영 코드와 배달본의 차이를 표로 정리
- [x] 원본이 보고한 수치와 그 한계 조건을 구분
- [ ] 배달본을 실제로 실행해 수치 재현 (23MB 가중치 + Roboflow export 필요)
- [ ] `EMERGENCY_CANDIDATE`의 관제·DB 경로 확인

---

# 11. 판정 기준 전체 정리 (input → output)

> 2026-08-29 코드 기준. 시간축 숫자는 추론이 아니라 실제 `FallMonitor`를 15 FPS로 돌려서 뽑았다.

## 11-0. 전체 흐름 한 장

```text
INPUT: BGR 프레임 (RTSP / mp4 / 카메라)
   │
   ├─[1] YOLOE-seg 추론 ─────────────────► Detection(class_id, confidence, mask, track_id) 목록
   │        conf≥0.25, imgsz=640, mask prob>0.5, track(persist=True)
   │
   ├─[2] 사람만 선별 ────────────────────► track_id 별 사람 목록
   │        tracking ON  → 전원, track_id 별로 독립 상태
   │        tracking OFF → 최고 confidence 1명 (신원이 없으므로)
   │
   ├─[3] 사람마다 자세·움직임 측정 ──────► (fallen?, low_motion?)
   │        규칙  : 픽셀 종횡비 ≥ 0.9
   │        분류기: P(fallen) ≥ 0.5   ← 켰을 때만
   │        움직임: |Δcentroid|/대각선 ≤ 0.015  (항상 규칙)
   │
   ├─[4] 사람마다 시간축 상태 전이 ──────► NORMAL … EMERGENCY_CANDIDATE
   │        1.0s 유지 → FALLEN, 정지 5.0s → EMERGENCY_CANDIDATE
   │
   └─[5] 프레임 결론 = 가장 나쁜 상태 ───► FrameVerdict(state, confidence, track_id, events)
            │
            ├─ 스로틀(상태 변화 즉시 / 무변화 0.3s 주기)
            │     └─► POST /internal/v1/vision/person-detections  → 로봇 안전 감속
            └─ 낙상 이벤트(스로틀 없음)
                  └─► WORKER_FALL_CONFIRMATION_REQUEST  → 관제 확인 요청
```

## 11-1. [1] 사람·장애물을 무엇으로 가르는가

**가르는 주체는 모델이다.** 저장소 쪽에는 사람/장애물을 나누는 기하 규칙이 없다. YOLOE-seg가 `nc=2`로 학습됐고, 코드가 하는 일은 클래스 번호를 이름에 대응시키는 것뿐이다.

| 항목 | 값 | 근거 |
| --- | --- | --- |
| 클래스 | `0 = obstacle`, `1 = person` | `data.yaml: names: ['obstacle','person']` |
| `person_class_id` | `1` (설정값, 상수 아님) | [detector.py:DetectorConfig](../model/perception/segmentation/runtime/detector.py) |
| confidence 하한 | `0.25` | [realtime.yaml](../model/worker/configs/realtime.yaml) |
| 입력 크기 | `640` | 같음 |
| mask 이진화 | 확률 `> 0.5` | `detections_from_result(mask_threshold=0.5)` |
| tracking | `track(persist=True)` | `persist` 없으면 매 프레임 번호를 다시 매겨 신원이 안 됨 |

**출력 1건**: `Detection(class_id, confidence, mask, track_id)`. `mask`는 프레임 크기의 bool 배열, `track_id`는 tracking이 꺼져 있으면 빈 문자열.

검출 0건과 추론 실패는 다르다 — 앞은 빈 목록, 뒤는 예외다.

**실측된 한계**: 배경 물체가 사람으로 잡히면 이후 단계는 그대로 속는다. `re_3` t=74s에서 벽의 금속 체인이 종횡비 3.54로 잡혔고 confidence(≥0.25)로 걸러지지 않았다.

## 11-2. [3] 사람이 "쓰러진 자세"인지 무엇으로 판단하는가

두 가지 모드가 있고, **기본은 규칙**이다.

### 모드 A — 종횡비 규칙 (기본)

```
fallen ⟺ (bbox 가로 화소수) / (bbox 세로 화소수) ≥ 0.9      ← 픽셀 좌표
```

`0.9`는 무낙상 영상 두 편에서 오탐 0을 확인한 하한이다. **0.7까지 내리면 `re_2`에서 오탐이 났다 — 이 밑으로 내리지 않는다.**

한계가 실측으로 기록돼 있다: 비율이 임계값 밑이면 애초에 의심 단계에 들어가지 못하고, **이 recall 구멍은 시간축 로직으로 못 메운다.** 2차 신호가 있어야 한다 — 그것이 모드 B다.

### 모드 B — 학습된 분류기 (`FALLEN_CLASSIFIER_*` 설정 시)

```
fallen ⟺ P(fallen | 5개 피처) ≥ threshold
```

`threshold`는 0.5로 덮어쓰지 않고 학습 때 k-fold로 고른 값을 번들에서 읽는다(이 번들은 0.5).

구조: `StandardScaler` → `LogisticRegression`. **피처는 전부 정규화(0..1) 좌표**에서 잰다 — 학습이 `masks.xyn` 위에서 됐기 때문이며, 픽셀 좌표를 넣으면 계수가 가장 큰 신호가 조용히 틀어진다(§6-4).

| # | 피처 | 정의 | 계수 | scaler 평균 |
| --- | --- | --- | --- | --- |
| 1 | `aspect_ratio` | 정규화 bbox 가로/세로 | **+5.273** | 0.7195 |
| 2 | `pca_angle` | mask 화소 공분산의 최대 고유벡터 각도 `[0,180)` — 누운 **방향** | −0.894 | 90.01 |
| 3 | `centroid_y` | mask 중심의 세로 위치 (0=위, 1=아래) | +0.543 | 0.4578 |
| 4 | `contact_person_iou` | 다른 **사람**과의 최대 bbox IoU | +0.335 | 0.0200 |
| 5 | `contact_obstacle_iou` | **장애물**과의 최대 bbox IoU | **0.000** | 0.0000 |

- 자기 자신(IoU ≥ 0.95)은 접촉 상대에서 제외한다.
- 접촉 피처는 "기대는 낙상"용이다. 171307 실측에서 기대기 전 0.000 → 기댄 뒤 0.05~0.13으로 올라 GT와 일치했고, 같은 구간에서 종횡비는 거의 무신호였다.
- **⚠ 5번은 이 번들에서 죽어 있다.** 계수가 정확히 0이고 scaler 평균도 0 — 학습 데이터에 사람이 장애물과 겹친 인스턴스가 없었다. 코드는 계산해 넘기지만 이 번들은 쓰지 않는다.

### 움직임 — 어느 모드든 규칙

```
low_motion ⟺ |centroid(t) − centroid(t−1)| / 프레임 대각선 ≤ 0.015
```

- centroid는 bbox 중심이 아니라 **mask 화소 평균**이다. bbox 중심을 쓰면 팔다리 하나가 튀어나올 때 중심이 크게 흔들려 정지를 움직임으로 오독한다.
- 사람이 (다시) 나타난 첫 프레임은 `motion = 0` → `low_motion = True`.
- 분류기를 켜도 움직임은 계속 규칙이 맡는다. 분류기는 한 프레임만 보므로 시간축 신호를 낼 수 없다.
- **`motion_threshold = 0.015`는 sweep 검증되지 않은 값이다.** 재보정이 미착수 상태다(§8).

## 11-3. [4] 비상까지 시간축: 몇 초, 몇 프레임

전이는 **시간 기준**이고 프레임은 표본일 뿐이다. 아래 프레임 번호는 15 FPS로 사람이 끊김 없이 잡히는 경우다. 한 프레임에 전이는 **최대 한 칸**이므로, FPS가 아무리 높아도 비상까지 최소 4프레임이 필요하다.

### 임계값

| 이름 | 값 | 뜻 |
| --- | --- | --- |
| `fall_confirm_seconds` | 1.0 s | 이만큼 쓰러진 자세가 유지돼야 `FALLEN` |
| `immobile_seconds` | 5.0 s | **정지가 시작된 시점**부터 이만큼 지나야 비상 |
| `recovery_confirm_seconds` | 1.0 s | 이만큼 연속 "안 넘어짐"이어야 `NORMAL` 복귀 |
| `track_timeout_seconds` | 3.0 s | 이만큼 안 보이면 그 사람 상태를 버림 |

### 정상 경로 (계속 쓰러져 정지, 15 FPS)

| 프레임 | 시각 | 전이 | 조건 |
| --- | --- | --- | --- |
| 0 | 0.000 s | `NORMAL → FALL_SUSPECTED` | 첫 "쓰러진 자세" 프레임 |
| 15 | 1.000 s | `FALL_SUSPECTED → FALLEN` | 자세가 `fall_confirm_seconds` 유지 |
| 16 | 1.067 s | `FALLEN → IMMOBILE` | `low_motion` 인 첫 프레임 → **정지 시계 시작** |
| 91 | 6.067 s | `IMMOBILE → EMERGENCY_CANDIDATE` | 정지 시작 + `immobile_seconds` |

**→ 첫 낙상 프레임부터 관제 알람까지 6.067초 / 92프레임.**

### 알람이 안 뜨는 경우 (설계 의도)

| 상황 | 결과 |
| --- | --- |
| 쓰러졌지만 계속 움직임(버둥거림) | `FALLEN`에서 멈춤. `IMMOBILE`에 못 가므로 비상 없음 |
| 짧은 낙상 (정지 5초 미만) | `IMMOBILE`까지 갔다가 회복. 비상 없음 |
| 종횡비가 0.9 미만 | `FALL_SUSPECTED`조차 안 됨 (규칙 모드의 recall 구멍) |

### 회복

| 현재 상태 | "안 넘어짐" 판정이 나오면 |
| --- | --- |
| `NORMAL` / `FALL_SUSPECTED` | **즉시** `NORMAL`. 아직 안전 증거가 쌓이지 않았다 |
| `FALLEN` / `IMMOBILE` / `EMERGENCY_CANDIDATE` | `recovery_confirm_seconds`(1.0s) **연속**이어야 `NORMAL`. 노이즈 한 프레임이 증거를 지우지 못하게 하는 디바운스 |

**미세 움직임 처리**: 숨쉬기 때문에 `FALLEN ↔ IMMOBILE`이 계속 뒤집혀도 정지 시계(`immobile_since`)는 리셋되지 않는다. 리셋은 `NORMAL` 복귀에서만 일어난다. 이 장치가 없으면 14초를 쓰러져 있어도 5초 연속을 한 번도 못 채워 알람이 영영 안 뜬다.

**탐지가 끊긴 프레임**: 판정은 유지하고 회복 시계만 멈춘다. 사람이 화면 밖에 있던 시간이 "정상이었다"는 증거가 되면 안 된다. `track_timeout_seconds`(3.0s)를 넘기면 그 사람 몫 상태를 통째로 버린다.

**ReID가 없다**: 3초 넘게 끊긴 뒤 같은 사람이 돌아오면 새 `track_id`를 받아 상태머신이 처음부터 시작한다. 구조적 한계로 인정한 부분이다.

### 이벤트 발행

`EMERGENCY_CANDIDATE` 진입 시 **track마다 한 번만** 발행한다(`event_sent`). `NORMAL`로 완전히 복귀해야 다시 발행될 수 있다.

## 11-4. [5] OUTPUT: 무엇이 어디로 나가는가

프레임 하나의 결론은 **그 화면에서 가장 나쁜 상태**다. 앞에 선 행인이 뒤에 누운 사람을 가려서는 안 된다.

```
심각도: NO_DETECTION < NORMAL < FALL_SUSPECTED < FALLEN < IMMOBILE < EMERGENCY_CANDIDATE
```

### 출력 1 — 사람 관측 (로봇 안전 감속용)

```json
{"camera_id": "CAM-PK-01", "confidence": 0.91, "pose_class": "IMMOBILE",
 "track_id": "7", "ttl_ms": 600, "observed_at_ms": 1756...}
```

- **전송 규칙**: 상태가 바뀌면 즉시. 안 바뀌면 `ttl_ms/2` = **0.3초 주기(≈3.3 Hz)**. 15 Hz를 그대로 흘리면 TCP 8788이 관측으로 차서 주행 명령이 뒤로 밀린다.
- `NO_DETECTION`은 **보내지 않는다.** 안전 gate는 TTL 만료로 잊는 것이 계약이고 confidence 0을 받지 않는다.
- 도착지: `POST /internal/v1/vision/person-detections` → `config/cameras.yaml`의 `attached_to`가 정한 로봇으로 **중계**. 5080은 로봇에 직접 꽂히지 않는다.

### 출력 2 — 낙상 확인 요청 (관제용)

```json
{"type": "WORKER_FALL_CONFIRMATION_REQUEST", "state": "EMERGENCY_CANDIDATE",
 "track_id": "7", "timestamp": 1756...}
```

스로틀을 타지 않고 항상 나간다. 사람마다 따로 나므로 한 프레임에 둘 이상일 수 있다.

**이 이벤트는 "넘어졌다"는 결론이 아니라 사람이 재확인하는 절차의 입구다.**

### ⚠ 기록되지 않는다

`pose_class`는 pydantic 필드로만 존재하고 이 값을 쓰는 SQL이 없다. `EMERGENCY_CANDIDATE`는 로봇을 감속시키고 사라지며, 나중에 "그날 몇 시에 누가 쓰러졌나"를 되짚을 기록이 남지 않는다(§5-3).

## 11-5. 기본값 요약

| 설정 | 기본값 | 켜는 방법 |
| --- | --- | --- |
| tracking | **ON** | `realtime.yaml: inference.tracking` / `live_runtime`은 코드에서 `tracking=True` |
| 낙상 분류기 | **OFF** (종횡비 규칙) | `FALLEN_CLASSIFIER_BUNDLE` + `FALLEN_CLASSIFIER_SHA256` 둘 다 |
| 파인튜닝 seg 가중치 | 미배포 | `SEGMENTATION_WEIGHTS_FILE` (§9-2 5번, 미완) |

환경변수를 **하나만** 채우면 런타임이 조용히 꺼지지 않고 기동을 거부한다.
