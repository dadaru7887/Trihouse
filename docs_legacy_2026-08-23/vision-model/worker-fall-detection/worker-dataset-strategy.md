# LEGO 작업자 검출·낙상 데이터셋 구축 전략

## 1. 목적과 범위

이 문서는 LEGO 작업자를 `person` 클래스로 검출·segmentation하고, 후속 단계에서 낙상 자세와 무움직임을 판정하기 위한 데이터셋 구축 기준을 정의한다. POC는 LEGO 전용이며 실제 사람의 산업 안전 성능을 주장하지 않는다.

데이터셋은 다음 세 문제를 각각 검증할 수 있어야 한다.

1. 정지 이미지에서 `person`과 `obstacle` 검출 및 mask segmentation
2. 검출된 LEGO의 `standing`, `fallen`, `transition` 자세 판정
3. 연속 영상에서 낙상 이후 무움직임과 관제 확인 요청 이벤트 판정

정지 이미지 polygon만으로 시간 기반 무움직임 성능을 검증하지 않는다.

## 2. 클래스 정책

`person`과 `obstacle` 두 클래스를 모두 유지한다.

```yaml
nc: 2
names:
  0: obstacle
  1: person
```

- `person`: 작업자로 취급하는 LEGO 전체의 segmentation polygon
- `obstacle`: LEGO와 혼동할 수 있거나 접촉·가림·낙상 환경을 형성하는 장애물 polygon
- 어느 클래스에도 해당하지 않는 영역은 background

`obstacle`을 유지하면 장애물을 작업자로 오검출하는 문제와 작업자가 장애물에 기대거나 가려진 상황을 클래스별 confusion matrix로 분석할 수 있다. 대표 모델 선택과 안전 관련 gate는 macro 평균이 아니라 `person` 지표를 우선 사용한다.

## 3. 데이터 관리 단위와 디렉터리

원본 관리 단위는 개별 frame이 아니라 recording session 또는 video clip이다.

```text
dataset/lego_worker_v1/
├── data.yaml
├── dataset_manifest.json
├── frame_manifest.csv
├── posture_manifest.csv
├── event_intervals.csv
├── train/{images,labels}/
├── valid/{images,labels}/
└── test/{images,labels}/
```

계층은 다음과 같다.

```text
scenario → camera → recording_session → clip → frame → instance
```

`frame_manifest.csv` 권장 열:

```csv
image,session_id,clip_id,frame_index,camera_id,track_id,posture,motion_state,environment,occlusion,object_size,synthetic,recipe_id
```

자세 값:

- `standing`
- `fallen`
- `transition`
- `unknown`

움직임 값:

- `moving`
- `immobile`
- `unknown`

`transition`을 standing 또는 fallen으로 억지로 합치지 않는다. 무움직임은 단일 frame 속성이 아니라 동일 track의 시간 구간이므로 `event_intervals.csv`에 시작·종료 frame과 지속시간을 별도로 기록한다.

## 4. 실제 촬영 전략

### 4.1 재현 가능한 실제 열화

현재 장비와 공간에서 안전하게 재현 가능한 열화는 실제 촬영 데이터로 확보한다.

- 조명 끄기 또는 단계적으로 낮추기: low light
- 손전등·휴대전화 플래시·직사 조명: glare, highlight saturation
- 카메라 또는 LEGO 이동 중 촬영: motion blur
- 상자·기둥·장애물로 일부 가리기: partial occlusion
- 카메라 거리·높이·각도 변경
- 배경, 바닥 재질과 LEGO 색상 변경
- 화면 중앙·모서리·경계 배치
- 자동 노출 및 white balance 변화
- 정상 정지, 장시간 정지, 일시적 검출 누락 같은 hard negative

각 환경은 정상 자세와 낙상 자세를 모두 포함해야 한다. 단일 장면의 연속 frame을 다량 추출해 수량만 늘리지 않고, 독립적인 배치·촬영 session·각도를 우선 늘린다.

### 4.2 낙상 방향과 시나리오

Positive 시나리오:

- 전방, 후방, 좌측, 우측, 대각선 낙상
- 장애물 위 또는 옆으로 쓰러짐
- 부분 가림 중 낙상
- low-light 및 glare 중 낙상
- 화면 가장자리에서 낙상
- 낙상 직후 조금 움직이다가 멈춤

Hard-negative 시나리오:

- standing 상태로 장시간 정지
- 정상적으로 이동하다 잠시 멈춤
- 장애물에 기대었지만 쓰러지지 않음
- 장애물만 움직임
- 카메라 흔들림과 조명 변화
- 가려졌다 다시 나타남
- 일시적인 mask 누락 또는 track ID 변경

영상 clip은 정상 상태 3초 이상, 자세 전환, 낙상 직후 움직임, 5~15초 무움직임, 회복 또는 종료를 포함하도록 촬영한다.

## 5. 실제 재현이 어려운 환경의 대안

실제 frost 또는 condensation 환경을 만들 수 없으므로 이를 실제 데이터 필수 조건으로 두지 않는다. 환경 slice를 세 등급으로 분리한다.

### Tier A: 실제 촬영 검증 환경

low-light, glare, motion blur, occlusion, 거리·각도·배경 변화처럼 실제로 재현 가능한 환경이다. 모델의 실제 환경 대응 성능 주장은 Tier A test 결과로만 뒷받침한다.

### Tier B: Synthetic-only 강건성 환경

frost, condensation, sensor noise와 복합 열화처럼 실제 촬영이 어려운 환경이다. 이 결과는 synthetic stress test로만 보고하며 실제 frost 대응 검증 완료로 표현하지 않는다.

### Tier C: 향후 external validation

실제 냉장·냉동 환경이나 공개 라이선스 데이터가 확보되면 기존 train/valid와 섞지 않고 외부 test set으로 평가한다. 모델이나 threshold 선택에 사용하지 않는다.

### Synthetic augmentation 규칙

- train에만 online augmentation 적용
- validation/test 원본에는 train augmentation 미적용
- 별도의 synthetic stress validation/test set을 구성할 수 있음
- stress test recipe는 train recipe와 강도·조합을 달리해 단순 recipe 암기를 방지
- augmentation seed, recipe ID, 파라미터와 코드 Git SHA 기록
- 원본 mask 좌표를 변경하지 않는 photometric/environment augmentation 우선
- synthetic 결과와 실제 촬영 결과를 합쳐 하나의 성능 숫자로 보고하지 않음
- frost/condensation은 procedural texture를 사용하며 학습 중 외부 URL 다운로드 금지

실제 frost가 없는 경우의 권장 보고 예:

```text
실제 low-light/glare test: 검증 완료
synthetic frost stress test: 강건성 참고 결과
실제 frost external test: 미수행
```

## 6. 객체 크기와 목표 수량

bbox 면적을 전체 이미지 면적으로 나눈 비율로 slice를 구분한다.

| Slice | Bbox area ratio |
|---|---:|
| Tiny | `< 0.5%` |
| Small | `0.5–2%` |
| Medium | `2–10%` |
| Large | `≥ 10%` |

현재 raw dataset은 person instance가 train/valid/test 129/28/26개이며, 이미지 면적 1% 미만 person이 69/18/19개다. 따라서 첫 보강은 medium 객체와 독립적인 positive scene을 우선한다.

1차 POC 목표:

| 항목 | Train | Valid | Test |
|---|---:|---:|---:|
| Person standing | 800 | 150 | 150 |
| Person fallen | 600 | 150 | 150 |
| Person transition | 300 | 75 | 75 |
| Negative/person 없음 | 500 | 100 | 100 |

각 valid/test 주요 slice는 최소 50 instance를 목표로 한다. fallen과 standing은 각각 최소 100 instance를 권장한다. 표본이 20개면 instance 한 개가 지표를 5%p 변화시키므로 안전 관련 성능 판단에 부족하다.

## 7. Split 전략

동일 clip의 frame을 서로 다른 split에 배정하지 않는다.

```text
recording_session 또는 clip 전체 → train, valid, test 중 하나
```

기본 비율은 train/valid/test 70/15/15이며 다음 항목을 group-stratify한다.

- posture
- person/obstacle 분포
- object size
- 환경
- camera
- fall direction
- occlusion

test에는 가능하면 보지 않은 session, 배경 또는 카메라를 포함한다. 동일 파일 hash, perceptual near-duplicate, 동일 clip/session의 교차 split 중복은 0이어야 한다. multi-seed 실험에서는 split과 dataset fingerprint를 고정한다.

## 8. 라벨링 및 QA

기존 모델 예측은 polygon 초안으로만 사용하고 사람이 수정한다. 자동 라벨을 검수 없이 정답으로 사용하지 않는다.

검수 우선순위:

1. negative 이미지 안의 미라벨 person
2. tiny/small person
3. polygon 꼭짓점이 적거나 면적이 극단적인 instance
4. 이미지 경계와 접촉한 instance
5. person/obstacle 혼동
6. fallen 및 transition 자세

권장 검수 정책:

- test split 100% 검수
- fallen/transition 100% 검수
- 전체 mask 최소 20% 이중 검수
- label 수정자는 가능하면 test 평가 담당자와 분리

## 9. 데이터셋 품질 평가 기준

### 9.1 Hard gate

다음 항목은 모두 0이어야 한다.

- 손상되거나 읽을 수 없는 이미지
- image 없는 label 또는 label 없는 image
- 범위 밖 polygon 좌표
- 잘못된 class ID
- 면적 0 polygon
- split 간 동일 파일·동일 clip·동일 session 중복
- video track ID와 event interval 필수값 누락

하나라도 실패하면 본 학습을 막는다.

### 9.2 라벨 완전성과 정확성

| 지표 | POC 권장 기준 |
|---|---:|
| 미라벨 person | `< 1%` |
| person/obstacle 오분류 라벨 | `< 1%` |
| mask 누락·과도한 잘림 | `< 2%` |
| posture 누락 | `< 1%` |
| 심각한 polygon 오류 | `< 1%` |

### 9.3 이중 annotation 일치도

| 지표 | 권장 기준 |
|---|---:|
| Mask IoU | `≥ 0.90` |
| Dice | `≥ 0.95` |
| Boundary IoU | `≥ 0.80` |
| Posture Cohen's kappa | `≥ 0.80` |
| Standing/fallen agreement | `≥ 95%` |

tiny 객체는 boundary 몇 pixel 차이에도 IoU가 크게 변하므로 size slice별로 별도 보고한다.

### 9.4 Coverage와 분포

다음을 split별 표와 그래프로 기록한다.

- 이미지, empty label, class instance 수
- positive/negative 이미지 비율
- posture, environment, occlusion 분포
- 객체 크기 분포
- polygon vertex와 면적 분포
- camera/session 수
- 실제 촬영과 synthetic 비율

train/valid/test 분포 차이는 오류가 아닐 수 있지만 의도와 함께 문서화해야 한다. 보지 않은 환경 test는 분포가 다른 것이 목적이다.

### 9.5 Dataset Quality Score

운영 편의를 위한 참고 점수:

```text
25% integrity
+ 25% label completeness
+ 20% annotation agreement
+ 15% split independence
+ 15% slice coverage
```

| 점수 | 사용 가능 범위 |
|---|---|
| 90–100 | 본 학습 가능 |
| 80–89 | POC 학습 가능, 부족 slice 명시 |
| 70–79 | smoke 및 탐색 실험만 가능 |
| `< 70` | 데이터 정비 우선 |

Hard gate 실패는 종합 점수와 무관하게 학습을 차단한다.

## 10. Detection 및 분류 성능 평가

Accuracy, Precision, Recall, F1은 person/obstacle detection confusion matrix로 계산한다. 먼저 confidence threshold와 IoU threshold를 고정해 prediction과 GT를 one-to-one matching한다.

- 같은 class로 match: TP
- prediction만 존재하거나 background에서 검출: FP
- GT가 match되지 않음: FN
- 다른 class로 match: 실제 class FN이자 예측 class FP

클래스별 정의:

```text
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
F1        = 2 × Precision × Recall / (Precision + Recall)
```

Detection에는 이미지 전체의 true negative 개수가 자연스럽게 정의되지 않는다. 따라서 분류 accuracy는 matched object에 한정해 다음처럼 표시한다.

```text
Matched classification accuracy
= correctly classified matched objects / all matched objects
```

미검출과 background false positive가 빠진다는 한계가 있으므로 accuracy 단독 사용을 금지하고 Precision, Recall, F1, false positives/image, mAP와 함께 보고한다.

보고 항목:

- person/obstacle confusion matrix
- 클래스별 Precision, Recall, F1
- macro average: 두 클래스를 동일 가중치로 평균
- weighted average: GT instance 수로 가중
- micro average: 모든 클래스 TP/FP/FN 합산
- false positives/image
- missed instances/image
- Box mAP50 및 mAP50-95

안전 기능의 validation gate와 대표 모델 선택은 person Recall과 person mask mAP50-95를 우선한다. obstacle 성능과 macro 평균은 보조 지표다.

## 11. Segmentation 성능 평가

핵심 우선순위:

1. Person mask mAP50-95
2. Person mask Recall
3. Person mask F1
4. Person mask mAP50
5. Size/environment별 person Recall 및 AP
6. Mask IoU, Dice와 Boundary IoU
7. Pixel accuracy

Pixel accuracy는 넓은 background 때문에 person을 놓쳐도 높게 나올 수 있어 보조 지표로만 사용한다.

초기 POC gate 제안:

| 지표 | 기준 |
|---|---:|
| Person mask mAP50-95 | `≥ 0.60` |
| Person mask mAP50 | `≥ 0.85` |
| Person mask Recall | `≥ 0.90` |
| Person mask Precision | `≥ 0.85` |
| Person mask F1 | `≥ 0.87` |
| Small-person Recall | `≥ 0.80` |
| False positives/image | `≤ 0.10` |

초기 기준은 데이터가 충분해진 뒤 bootstrap confidence interval과 실제 오류 비용을 보고 조정한다.

## 12. 자세·무움직임·이벤트 평가

자세:

- fallen/standing/transition confusion matrix
- Fallen Recall, Precision, F1
- 자세 확정 지연
- size/environment별 Fallen Recall

무움직임:

- Immobility Recall, Precision, F1
- 정상 정지 오경보율
- 확인 지연
- track fragmentation

최종 이벤트:

- Event Recall 및 Precision
- false alarms/hour
- missed-event rate
- detection delay
- duplicate event rate
- track loss rate

AI는 비상을 확정하지 않고 `EMERGENCY_CANDIDATE` 관제 확인 요청만 생성한다.

## 13. Multi-seed 보고와 모델 선택

모든 seed는 같은 split, dataset fingerprint와 augmentation seed 42를 사용한다. 모델 초기화·shuffle·PyTorch 학습 seed만 변경한다.

각 test 지표는 다음 형식으로 보고한다.

- mean ± sample standard deviation
- min/max
- 가능하면 95% bootstrap confidence interval

대표 모델은 validation으로만 선택한다.

1. validation person mask mAP50-95
2. validation person mask Recall
3. validation person mask F1
4. 낮은 seed를 결정적 tie-break로 사용

test 결과는 선택에 사용하지 않는다.

## 14. OODA 구축 주기

### Observe

라벨 audit, confusion matrix, false-positive/false-negative gallery와 size/environment slice 지표를 수집한다.

### Orient

실패를 tiny/small, low-light, glare, occlusion, posture, unseen background, class confusion으로 분류한다.

### Decide

가장 낮은 Recall 또는 가장 큰 안전 비용을 가진 실제 재현 가능 slice를 다음 촬영 목표로 선택한다. frost처럼 재현 불가능한 항목은 synthetic stress test 개선 대상으로만 둔다.

### Act

실제 데이터 보강, 라벨 재검수, 고정 split 재학습, slice 재평가를 수행한다. 새로운 test 실패를 보고 threshold를 바꾸지 않고 validation에서만 조정한다.

## 15. 단계별 실행 계획

### Phase 1: 기존 데이터 QA

- 현재 334장 contact sheet와 label audit 생성
- negative 이미지의 미라벨 LEGO 전수 확인
- tiny/small polygon과 class 혼동 검수
- session/near-duplicate 기반 split leakage 검사

### Phase 2: 실제 재현 가능 환경 보강

- medium 크기 standing/fallen 우선 촬영
- low-light, glare, motion blur, occlusion 실제 촬영
- 자세·크기·환경별 최소 valid/test 표본 확보

### Phase 3: 시간 데이터 구축

- 독립 낙상 방향과 hard-negative clip 촬영
- track ID, posture, event interval annotation
- 정상 정지와 낙상 후 무움직임 균형 확보

### Phase 4: Synthetic stress set

- frost, condensation와 복합 열화 recipe 고정
- train recipe와 다른 stress test recipe 구성
- 실제 환경 결과와 분리 보고

### Phase 5: Baseline과 반복 개선

- 동일 split과 augmentation seed로 multi-seed 학습
- person/obstacle detection 및 mask 지표 산출
- size/environment/posture slice와 이벤트 평가
- OODA 기준으로 다음 데이터 보강 결정

## 16. 완료 조건

데이터셋 v1은 다음을 모두 만족할 때 완료로 본다.

- 모든 hard integrity gate 통과
- session/clip 기반 split과 fingerprint 고정
- person/obstacle 라벨 QA 기준 충족
- valid/test standing과 fallen 최소 표본 충족
- 실제 재현 가능한 주요 환경 slice 확보
- synthetic-only 환경이 별도 표시됨
- 시간 기반 event interval과 hard-negative clip 확보
- dataset manifest에 버전, source session, split 정책, synthetic recipe와 Git SHA 기록
