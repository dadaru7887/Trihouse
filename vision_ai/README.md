# vision_ai — Trihouse vision AI 두 모델과 로봇 프로세스

Vision AI 모델이 **둘**이고, 각자 가중치를 낸다. 그 가중치를 읽어 실시간으로
도는 **로봇 프로세스**는 별도다.

| | 모델 | 학습 산출물 | 로봇이 읽는 자리 |
| --- | --- | --- | --- |
| ① | **인지** — YOLOE-seg(사람/장애물) + 낙상 분류기(기하 피처 + logreg) | `best.pt` · `fallen_classifier.joblib` | `robot/perception/` |
| ② | **복구** — VLM + RL (Tuned-TGRPO + SAC), distilled skill selector | `policy.pt` · `high_level_distilled_ensemble.pt` | `robot/recovery/` |

## 구조

```
main.py              학습·검증 진입점 (모델 2개 공용)
data_loader/
    perception/      YOLO data.yaml 적재 · split 누수 검사 · 라벨 분석
    fall/            낙상 피처 JSONL
    recovery/        복구 전이 · risk-stratified replay buffer
models/
    perception/      detector · 기하 피처 · 낙상 분류기 · yoloe_backend
        trainer/     preflight → 학습 → val → gate → test · multi-seed · 증강 recipe
    recovery/        TGRPO/SAC 망 · distilled selector · VLM interpreter · checkpoint
        trainer/     off-policy TGRPO 근사 + SAC 오프라인 업데이트
utils/               device · environment · reproducibility · config · contracts · metrics
visualization/       seed 대시보드 · 학습 곡선 · 성능 리포트

robot/               ★ 로봇에 올라가는 프로세스 — 가중치만 읽는다
    main.py          로봇 진입점
    perception/      검출 → 사람별 자세·움직임 → 시간축 상태머신 → Gateway 보고
    recovery/        트리거 → VLM 해석 → RL 후보 → 안전 경계 → 승인 제안
    safety/          실행 전 안전 gate 설정
    marker/ media/ object/   그 밖의 로봇 측 vision worker

upstream/            원본 저장소 보관본 (dev_driving · dev_vision). 아무도 import 하지 않는다
tests/               worker/ · recovery/
```

## 왜 학습과 로봇을 나눴는가

로봇에 올라가는 프로세스가 ultralytics 학습 스택과 scikit-learn 을 끌고 들어가면
안 된다. 그 경계는 세 곳에서 지켜진다.

1. `robot/main.py` 의 import 는 전부 함수 안에 있다.
2. `tests/test_main_entrypoint.py` 가 **실제 프로세스를 띄워** `sys.modules` 를 읽고
   trainer·data_loader·무거운 서드파티가 한 줄도 안 올라오는지 잰다. 정적 검사로는
   간접 import 를 못 잡는다.
3. `docker/ai/Dockerfile.inference` 의 COPY 목록이 이미지에 실제로 안 들어간다는 것을
   정한다.

## 명령

```bash
# ① 인지 — segmentation
python -m vision_ai.main train --model perception --stage segmentation --data /path/to/data.yaml
python -m vision_ai.main train --model perception --stage segmentation --data ... --multi-seed

# ① 인지 — 낙상 분류기
python -m vision_ai.main train --model perception --stage fall \
    --dataset /path/to/features.jsonl --out runs/fall

# ② 복구
python -m vision_ai.main train --model recovery \
    --dataset dataset/vlm_rl/recovery_transitions.jsonl --checkpoint runs/recovery/policy.pt

# 검증 — 고정 데이터셋 지표
python -m vision_ai.main eval --model perception --run-dir runs/... --split test

# 로봇 실시간
python -m vision_ai.robot.main --source rtsp://<pc1>:8554/pinky/CAM-PK-01 \
    --weights /models/best.pt --report-url http://<gateway>:8000
```

데이터셋 경로는 코드에도 기본값에도 없다. 전부 인자로 들어온다.

## 더 읽을 것

- 판정 기준과 시간축 전체: [obj_seg_n_person_fallen_detection_architecture.md](../docs/obj_seg_n_person_fallen_detection_architecture.md)
- 코드 읽는 순서와 디버깅: [vision-code-reading-and-debugging.md](../docs/guides/vision-code-reading-and-debugging.md)
- VLM+RL 복구 흐름: [trihouse_vlm_rl_architecture.md](../docs/trihouse_vlm_rl_architecture.md)
