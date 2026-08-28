# 낙상 감지(fallen detection) 결과물 — 2026-08-24

세그멘테이션 재학습(Track A) + fallen 분류기(Track B) + 시간축 상태머신을 낙상 데이터로
검증/개선한 결과물. 자세한 과정과 근거는 로컬 메모리
`project_fallen_detection_options_and_progress.md`, `reference_fallen_detection_github.md`
참고(다음 세션에서 Claude가 자동으로 불러옴).

## 폴더 구성

```
weights/
  segmentation_finetuned_seed2026_best.pt   -- Track A 대표 모델(YOLOE-26s-seg, person/obstacle nc=2)
classifier/
  fallen_classifier_contact_seed42.joblib   -- Track B 최종 분류기(기하+접촉 피처, logreg)
code/
  fall_monitor.py            -- 시간축 상태머신(track_id별 독립 지원)
  video_monitor.py           -- 세그멘테이션+분류기+상태머신 연결, 다중인원 추적 파이프라인
  classifier_trainer.py      -- 분류기 피처 정의(기하/프롬프트/접촉) + 학습 로직
  roboflow_labels.py         -- Roboflow 라벨 로더
  run_config.py / cli.py / reproducibility.py -- 분류기 학습 CLI
  eval_end_to_end.py         -- 진짜 recall 평가(탐지 실패 포함, 가려짐/안가려짐 분리)
  retrain_on_predicted_masks.py -- 예측 mask 기준 threshold 재선택
configs/
  final_metrics.json         -- 오늘 나온 최종 수치 요약
  event_intervals.csv        -- 실제 영상 GT(사람이 육안 확인한 낙상 시각)
  single_phrase.json / descriptive.json -- 프롬프트 문구 실험용(현재 미사용, 참고용)
```

## 어떻게 다시 병합해야 하는지

### 1. 세그멘테이션 (Track A)
`weights/segmentation_finetuned_seed2026_best.pt`는 팀 저장소의 `aug_best.pt`를
**대체**하는 게 아니라 **병행 검증용**으로 먼저 두는 걸 추천. 병합 데이터셋(원본
video_re_1~5 + fallen 영상 리매핑, 총 929장)으로 파인튜닝한 결과라, 원본 데이터셋만
쓰던 모델과 클래스 정의(nc=2, person/obstacle)는 동일하게 호환됨 -- 바로 교체 가능한
drop-in weight.

### 2. 분류기 + 상태머신 (Track B)
- `code/fall_monitor.py`가 팀 저장소의 `vision_system/person_worker/fall_monitor.py`
  (또는 `model/worker/person/fall_monitor.py`)를 **대체**해야 함 -- `note_no_detection()`
  메서드와 `fallen_since` 필드가 추가됨(오늘 발견한 버그 수정, 원본엔 없음).
- `code/video_monitor.py`는 팀 저장소에 없던 **신규 연결 파이프라인**. 원본의
  `policy.py`(`PersonPolicy`) 설계(track_id별 독립 모니터)를 최대한 반영해서 새로
  짠 것 -- 원본 `policy.py`를 그대로 쓸 수 있다면 `video_monitor.py`의
  `VideoFallPipeline` 로직을 그 인터페이스에 맞게 재배선하는 걸 권장(지금은 독립
  실행 스크립트라 팀 저장소의 `PersonObservation`/`PersonPolicy` 클래스 계약과
  완전히 맞춰져 있진 않음).
- `code/classifier_trainer.py`의 피처 정의(`polygon_to_geometric_features`,
  `contact_features`/`contact_from_predictions`)는 팀 저장소의 `posture.py`가 맡던
  역할을 확장한 것 -- `posture.py`를 이 피처 정의로 업데이트하거나, 이 파일을
  그대로 `posture.py` 옆에 두고 import해서 쓰는 두 가지 방법 중 택1.

### 3. 데이터/설정
- `configs/event_intervals.csv`는 계속 채워나가야 할 GT 파일 -- 아직 8개 영상 중
  일부만 채워짐(162744/170622/171307/162137 일부).
- `configs/final_metrics.json`은 발표/보고용 스냅샷, 코드에서 안 읽음.

## 알려진 미해결 문제 (병합 전에 인지할 것)

1. **회복 인식 지연** -- 일어난 뒤에도 몇 초간 "쓰러짐"으로 오판하는 경우 있음.
   162744에서 실제 오탐 1건 확인(t=9.15s), 원인 미해결(mask 자체가 자세 변화를
   못 따라가는 것으로 추정). `posture_change_threshold` 시도했으나 이 케이스는
   해결 안 됨 -- 코드엔 남겨뒀지만(기본값 0.15) 완전한 해결책 아님.
2. **track_id 재식별 불가** -- 카메라가 길게(10초+) 끊긴 뒤 같은 사람이 돌아오면
   새 track_id를 받아서 그 사람 몫 상태머신이 새로 시작됨. ReID 없이는 구조적
   한계로 인정하고 감.
3. **시간 임계값 재보정 미착수** -- `fall_confirm_seconds`(1.0)/`immobile_seconds`(5.0)/
   `motion_threshold`(0.015)는 원본 repo 기본값 그대로. `event_intervals.csv`가
   더 채워지면 재보정 필요.
4. **가려짐(occlusion) 상황은 구조적으로 못 풂** -- 단일 프레임 분류기 특성상
   당연한 한계, depth나 시간축 정보 없이는 해결 불가로 판단하고 범위에서 제외함.

## 재현 명령어 예시

```bash
# 분류기 재학습 (예측 mask 기준 threshold 재선택)
python -m code.retrain_on_predicted_masks \
  --seg-weights weights/segmentation_finetuned_seed2026_best.pt \
  --roboflow-export <fallen roboflow export 경로> \
  --out classifier/fallen_classifier_contact_seed42.joblib

# end-to-end 평가 (가려짐/안가려짐 분리)
python -m code.eval_end_to_end \
  --seg-weights weights/segmentation_finetuned_seed2026_best.pt \
  --classifier classifier/fallen_classifier_contact_seed42.joblib \
  --roboflow-export <fallen roboflow export 경로> --split test

# 실제 영상에 프레임 단위로 돌리기
python -m code.video_monitor \
  --seg-weights weights/segmentation_finetuned_seed2026_best.pt \
  --classifier classifier/fallen_classifier_contact_seed42.joblib \
  --video <영상.mp4> --out <결과.jsonl>
```
