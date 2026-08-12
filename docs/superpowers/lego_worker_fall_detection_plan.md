# Vision-based Worker Abnormal Posture & Immobility Detection

> 구현 시작점: [`vision_perception/test/worker-fall-detection/README.md`](../../vision_perception/test/worker-fall-detection/README.md)
>
> POC는 LEGO를 `person` polygon으로 학습한 YOLOE segmentation 모델을 사용한다. 현재 구현 순서는 dataset preflight → YOLOE 학습 → validation gate → test 평가이며, 생성된 `artifact_manifest.json`을 후속 ByteTrack·자세·무움직임·관제 확인 요청 단계가 소비한다.

## 1. 프로젝트 개요

### 프로젝트 배경
3온도(상온/냉장/냉동) 물류센터 로봇 자동화 시스템에서 작업자의 안전을 위해, 카메라 영상으로 작업자의 비정상 자세와 장시간 무움직임을 감지하고 관제센터에 비상 후보 이벤트를 전달하는 기능을 구현한다.

실제 사람 대신 LEGO 인형을 작업자로 가정하여 데모 환경을 구성한다.

### 핵심 목표
본 기능의 목표는 AI가 곧바로 "낙상 사고"를 확정하는 것이 아니라 아래 절차로 **Human-in-the-loop 방식의 안전 관제 시스템**을 구현하는 것이다.

1. 작업자(LEGO worker) 인식
2. 동일 작업자 지속 추적
3. 수평/비정상 자세 감지
4. 일정 시간 동안 움직임이 없는지 판단
5. `EMERGENCY_CANDIDATE` 이벤트 생성
6. 관제센터에 영상/상태 정보 전달
7. 관리자가 최종 확인
8. 비상상황으로 확인되면 로봇 안전 프로세스 수행

---

# 2. 권장 시스템 아키텍처

```text
RGB / RealSense Camera
        ↓
Open-vocabulary Segmentation
(YOLOE-Seg)
        ↓
LEGO Worker Mask
        ↓
Multi Object Tracking
(ByteTrack 또는 BoT-SORT)
        ↓
Worker별 상태 Feature 추출
        │
        ├─ Bounding Box Aspect Ratio
        ├─ Segmentation Mask Orientation
        ├─ Mask Centroid Height
        ├─ Centroid Displacement
        ├─ Consecutive Mask IoU
        └─ Optical Flow
        ↓
Fall / Immobility State Machine
        ↓
NORMAL
        ↓
FALL_SUSPECTED
        ↓
FALLEN
        ↓
IMMOBILE
        ↓
EMERGENCY_CANDIDATE
        ↓
ROS2 Event
/emergency/fall_candidate
        ↓
관제센터 UI
        ↓
관리자 판단
     ↙       ↘
  오탐       비상 확인
               ↓
        Emergency Manager
               ↓
        해당 구역 안전 제어
```

---

# 3. 기술 선정

## 3.1 Worker Detection / Segmentation

### 1순위
- YOLOE Segmentation
- Open-vocabulary 기반 객체 탐지/세그멘테이션
- 초기 프롬프트 예시:
  - `worker`
  - `person`
  - `lego worker`
  - `human figure`

### 중요한 주의사항
실제 사람과 LEGO 인형 사이에는 큰 domain gap이 있으므로 zero-shot 성능만 신뢰하지 않는다.

권장 방식:

```text
YOLOE Zero-shot 테스트
        ↓
실제 프로젝트 카메라 영상 수집
        ↓
LEGO Worker Dataset 구축
        ↓
Fine-tuning 또는 별도 segmentation 모델 학습
```

최종 데모 성능이 우선이라면 LEGO worker segmentation dataset을 직접 구축하는 것이 가장 안정적이다.

---

# 4. Tracking

Segmentation 이후 각 LEGO worker에게 ID를 유지해야 한다.

권장 알고리즘:

- ByteTrack
- BoT-SORT

예:

```text
worker_01
worker_02
worker_03
```

추적 ID가 필요한 이유:

- 사람별 무움직임 시간을 독립적으로 계산
- 프레임 간 자세 변화를 비교
- 여러 작업자가 동시에 존재해도 각각 상태 관리
- 관제센터에 특정 작업자 이벤트 전달

---

# 5. Fall Detection Feature

한 개 프레임만 보고 낙상을 확정하지 않는다.

여러 시각적 Feature를 조합해 `FALL_SUSPECTED` 여부를 계산한다.

---

## 5.1 Bounding Box Aspect Ratio

Bounding box의 폭과 높이를 이용한다.

```text
aspect_ratio = width / height
```

정상적으로 서 있는 LEGO 인형:

```text
width < height
```

쓰러진 LEGO 인형:

```text
width > height
```

예:

```text
Standing
aspect_ratio ≈ 0.3 ~ 0.7

Fallen
aspect_ratio ≈ 1.5 이상
```

주의:
- 위 threshold는 예시이며 실제 LEGO 크기, 카메라 높이, 촬영 각도에 따라 calibration 필요

---

# 6. Segmentation Mask Orientation

가장 중요한 자세 특징 중 하나로 사용한다.

Segmentation mask 내부 pixel 좌표에 PCA를 적용한다.

```text
Mask pixels
(x1, y1)
(x2, y2)
...
(xn, yn)
        ↓
PCA
        ↓
Principal Axis
```

정상:

```text
    ↑
    │
    │
```

쓰러짐:

```text
────────→
```

Feature:

```text
orientation_angle
```

예시:

```text
70° ~ 110°
→ vertical / standing

0° ~ 30°
150° ~ 180°
→ horizontal / fallen candidate
```

실제 threshold는 데이터 기반으로 결정한다.

---

# 7. Mask Centroid Height

Segmentation mask의 중심 좌표를 계산한다.

```text
Cx = mean(mask_x)
Cy = mean(mask_y)
```

고정형 카메라 환경에서는 작업자가 쓰러지면 중심점이 바닥에 가까워지는 경향이 있다.

따라서 다음 feature를 사용한다.

```text
normalized_centroid_height
```

예:

```text
distance_from_floor =
floor_y - centroid_y
```

카메라가 고정되어 있으므로 floor line 또는 관심 영역(ROI)을 미리 calibration할 수 있다.

---

# 8. Fall Score

초기에는 머신러닝 classifier를 추가하지 않고 rule 기반 score로 구현한다.

예:

```text
fall_score =
    w1 * aspect_ratio_score
  + w2 * orientation_score
  + w3 * centroid_height_score
```

초기 weight 예시:

```text
w1 = 0.3
w2 = 0.5
w3 = 0.2
```

예:

```text
if fall_score > FALL_THRESHOLD:
    state = FALL_SUSPECTED
```

주의:
- weight/threshold는 반드시 실험 데이터로 조정
- 처음부터 hard coding하기보다 config YAML로 분리

---

# 9. 움직임 감지

본 프로젝트에서 낙상 여부보다 더 중요한 조건이다.

목표:

```text
비정상 자세
+
일정 시간 동안 움직임 없음
=
Emergency Candidate
```

---

## 9.1 Centroid Displacement

Tracking된 worker의 중심점 이동량을 계산한다.

```text
motion_t =
sqrt(
    (cx_t - cx_t-1)^2
    +
    (cy_t - cy_t-1)^2
)
```

예:

```text
motion_t < MOTION_EPSILON
```

상태가 일정 시간 유지되면 무움직임 후보로 판단한다.

---

# 10. Segmentation Mask IoU 기반 움직임

Centroid만 보면 작은 팔/몸 움직임을 놓칠 수 있다.

따라서 연속 프레임의 segmentation mask를 비교한다.

```text
mask_iou =
IoU(mask_t, mask_t-1)
```

거의 움직이지 않는 경우:

```text
mask_iou → 1.0
```

예:

```text
mask_iou > 0.95
AND
centroid_motion < epsilon
```

이면 `low_motion`으로 판단한다.

실제 threshold는 실험을 통해 결정한다.

---

# 11. Optical Flow

추가적인 움직임 감지 방법.

MVP 이후 안정성을 높이고 싶으면 segmentation ROI 내부의 optical flow를 계산한다.

우선순위:

1. OpenCV Farneback
2. Lucas-Kanade
3. 필요 시 Deep Optical Flow 모델

LEGO 데모 환경에서는 Farneback 수준으로 충분할 가능성이 높다.

계산:

```text
worker ROI
    ↓
Optical Flow
    ↓
mean_flow_magnitude
```

예:

```text
mean_flow_magnitude < FLOW_THRESHOLD
```

가 일정 시간 지속될 경우 `IMMOBILE` 판단에 반영한다.

---

# 12. 최종 Motion Score

다음 세 정보를 결합한다.

```text
1. centroid displacement
2. mask IoU
3. optical flow
```

예:

```text
is_low_motion =
    centroid_motion < centroid_threshold
AND
    mask_iou > mask_iou_threshold
AND
    mean_flow < flow_threshold
```

MVP에서는 다음 두 개만 먼저 구현해도 된다.

```text
centroid displacement
+
mask IoU
```

Optical Flow는 2차 확장 기능으로 추가한다.

---

# 13. State Machine

필수 구현 요소.

단일 if 문으로 구현하지 않고 명시적인 상태 머신으로 관리한다.

## 상태 정의

```text
NORMAL
FALL_SUSPECTED
FALLEN
IMMOBILE
EMERGENCY_CANDIDATE
```

## 상태 전이

```text
NORMAL
  │
  │ fall_score > threshold
  ↓
FALL_SUSPECTED
  │
  │ 자세가 일정 시간 유지
  ↓
FALLEN
  │
  │ 움직임 없음
  ↓
IMMOBILE
  │
  │ immobile_time > threshold
  ↓
EMERGENCY_CANDIDATE
```

복귀 조건도 정의한다.

```text
FALL_SUSPECTED
    ↓
자세 정상화
    ↓
NORMAL
```

```text
IMMOBILE
    ↓
움직임 다시 발생
    ↓
FALLEN 또는 NORMAL
```

---

# 14. 권장 Timer

실제 값은 테스트 후 조정한다.

초기 테스트값 예시:

```yaml
fall_suspected_duration: 1.0
fallen_duration: 2.0
immobile_duration: 5.0
```

즉:

```text
수평 자세 약 1초 이상
        ↓
FALLEN 후보

그 상태에서 약 5초 이상 움직임 없음
        ↓
EMERGENCY_CANDIDATE
```

테스트 환경에서는 3~5초로 짧게 설정하고, 실제 시스템 요구사항에서는 별도 값으로 관리한다.

---

# 15. ROS2 시스템 구성

권장 패키지 구조:

```text
warehouse_safety/
├── perception/
│   ├── worker_segmentation_node.py
│   ├── worker_tracking_node.py
│   └── motion_estimator_node.py
│
├── safety_monitor/
│   ├── fall_feature_node.py
│   ├── fall_state_machine.py
│   └── emergency_event_node.py
│
├── interfaces/
│   ├── msg/
│   │   ├── WorkerState.msg
│   │   └── FallEvent.msg
│   │
│   └── srv/
│       └── ConfirmEmergency.srv
│
└── config/
    └── fall_detection.yaml
```

실제 ROS2 workspace에서는 각각 package로 분리할 수도 있다.

예:

```text
warehouse_perception
warehouse_safety_monitor
warehouse_interfaces
warehouse_dashboard
```

---

# 16. 권장 ROS2 Node 구조

```text
Camera Node
   ↓
/camera/image_raw

worker_segmentation_node
   ↓
/workers/segmentation

worker_tracking_node
   ↓
/workers/tracks

fall_feature_node
   ↓
/workers/state_features

fall_state_machine_node
   ↓
/workers/safety_state

emergency_event_node
   ↓
/emergency/fall_candidate
```

---

# 17. WorkerState Message 예시

```text
string worker_id

float32 bbox_aspect_ratio
float32 orientation_angle
float32 centroid_x
float32 centroid_y

float32 centroid_motion
float32 mask_iou
float32 optical_flow

float32 fall_score

string state
```

---

# 18. FallEvent Message 예시

```text
string worker_id
string zone
string event_type

float32 fall_score
float32 immobile_duration

builtin_interfaces/Time detected_at
```

예:

```text
worker_id: worker_02
zone: freezer
event_type: fall_candidate
fall_score: 0.91
immobile_duration: 8.4
```

---

# 19. 관제센터 Alert

`EMERGENCY_CANDIDATE` 상태가 발생하면 관제센터에 전달한다.

예:

```text
⚠ 작업자 이상 상태 감지

Zone:
냉동 창고

Worker:
worker_02

상태:
쓰러짐 의심 + 무움직임

Fall score:
0.91

Immobile duration:
8.4 sec

[ CCTV 확인 ]

[ 비상상황 확인 ]
[ 오탐 ]
```

AI는 다음과 같이 표현한다.

```text
"작업자 쓰러짐 의심"
```

또는

```text
"작업자 이상 자세 및 장시간 무움직임 감지"
```

다음 표현은 피한다.

```text
"작업자가 쓰러졌습니다."
```

AI가 최종 비상상황을 단정하지 않도록 한다.

---

# 20. 관리자 확인 이후 Emergency Process

관리자가 비상상황으로 확인한 후에만 자동 대응을 수행한다.

```text
EMERGENCY_CANDIDATE
        ↓
관리자 확인
        ↓
EMERGENCY_CONFIRMED
        ↓
Emergency Manager
        ↓
1. 해당 구역 신규 작업 배정 중지
2. AMR 해당 구역 진입 제한
3. 해당 구역 주행 로봇 Safe Stop
4. 로봇팔 안전 정지
5. 관제센터 비상 UI 표시
6. 필요 시 경광등 / 부저 활성화
```

Safety Layer와 Scheduler / Task Manager를 분리하여 구현한다.

---

# 21. Skeleton / Pose Estimation

## 현재 권장
초기 MVP에서는 사용하지 않는다.

이유:
- 일반 pose model은 실제 사람 체형에 최적화
- LEGO 인형은 비율과 관절 구조가 다름
- COCO human keypoint 모델을 그대로 적용하면 keypoint 오탐 가능성이 높음
- segmentation mask만으로도 LEGO의 서 있음/누워 있음 판단이 쉽다

---

# 22. Skeleton 확장 계획

후속 단계에서는 LEGO용 custom keypoint model을 만든다.

추천 keypoints:

```text
0 head
1 left_shoulder
2 right_shoulder
3 pelvis
4 left_foot
5 right_foot
```

구조:

```text
           head
             ●
             │
left_shoulder ─ right_shoulder
             │
           pelvis
           /    \
    left_foot  right_foot
```

이후 YOLO Pose custom training을 수행한다.

---

# 23. Skeleton Feature

custom pose model을 만든 이후에는 다음 feature를 추가한다.

## Spine Orientation

```text
spine_vector =
head - pelvis
```

정상:

```text
     head
       ●
       │
       │
       ● pelvis
```

쓰러짐:

```text
head ●────────● pelvis
```

Feature:

```text
spine_angle
```

이 값을 segmentation mask orientation과 fusion한다.

---

# 24. 최종 Feature Fusion

향후 확장:

```text
Segmentation Features
        +
Pose / Skeleton Features
        +
Motion Features
        ↓
Fall Classification
```

입력 feature 예:

```text
aspect_ratio
orientation_angle
centroid_height
spine_angle
centroid_motion
mask_iou
optical_flow
```

---

# 25. 향후 Advanced Model

LEGO MVP 이후 실제 사람 데이터 또는 충분한 시계열 데이터가 확보되면 다음 모델 검토 가능:

- ST-GCN
- PoseC3D
- Temporal CNN
- LSTM
- Transformer 기반 skeleton action recognition

다만 현재 LEGO 기반 물류센터 프로젝트에서는 과도한 구조가 될 가능성이 높으므로 1차 구현 범위에서는 제외한다.

---

# 26. 개발 우선순위

## Phase 1 — Perception MVP

목표:
LEGO 작업자를 안정적으로 segmentation 및 tracking

구현:

- Camera input
- YOLOE segmentation
- LEGO worker detection
- ByteTrack
- worker ID 유지
- 결과 영상 overlay

완료 조건:

```text
여러 LEGO 인형이 존재해도 worker별 ID 유지
```

---

## Phase 2 — Fall Posture Detection

목표:
서 있는 상태와 쓰러진 상태 구분

구현:

- bbox aspect ratio
- mask PCA orientation
- mask centroid
- floor-relative centroid height
- fall score 계산

완료 조건:

```text
standing → NORMAL

fallen → FALL_SUSPECTED
```

---

## Phase 3 — Motion Detection

목표:
쓰러진 이후 장시간 움직임 없음 감지

구현:

- centroid displacement
- mask IoU
- timer
- optional optical flow

완료 조건:

```text
FALL_SUSPECTED
+
N sec motion 없음
→ IMMOBILE
```

---

## Phase 4 — State Machine

구현:

```text
NORMAL
FALL_SUSPECTED
FALLEN
IMMOBILE
EMERGENCY_CANDIDATE
```

각 상태에 timeout과 recovery condition 추가.

---

## Phase 5 — ROS2 Integration

구현:

```text
/workers/state
/emergency/fall_candidate
```

관제센터와 통신.

---

## Phase 6 — Dashboard

표시:

- 카메라 영상
- worker ID
- segmentation mask
- worker state
- fall score
- immobile timer
- zone

관리자 버튼:

```text
[ 비상상황 확인 ]
[ 오탐 ]
```

---

## Phase 7 — Robot Safety Integration

관리자가 비상상황을 확인했을 때:

```text
Safety Manager
      ↓
Task Manager
      ↓
AMR / Robot Arm
```

동작:

- 해당 zone task scheduling 정지
- AMR 진입 제한
- 로봇 안전 정지
- 관제 로그 저장

---

# 27. 권장 디렉터리 구조

```text
warehouse_ws/
└── src/
    ├── warehouse_perception/
    │   ├── warehouse_perception/
    │   │   ├── worker_segmentation.py
    │   │   ├── worker_tracker.py
    │   │   ├── mask_feature_extractor.py
    │   │   └── motion_estimator.py
    │   ├── config/
    │   │   └── perception.yaml
    │   ├── launch/
    │   │   └── perception.launch.py
    │   ├── package.xml
    │   └── setup.py
    │
    ├── warehouse_safety/
    │   ├── warehouse_safety/
    │   │   ├── fall_detector.py
    │   │   ├── fall_state_machine.py
    │   │   └── emergency_manager.py
    │   ├── config/
    │   │   └── fall_detection.yaml
    │   ├── launch/
    │   │   └── safety.launch.py
    │   ├── package.xml
    │   └── setup.py
    │
    ├── warehouse_interfaces/
    │   ├── msg/
    │   │   ├── WorkerState.msg
    │   │   └── FallEvent.msg
    │   ├── srv/
    │   │   └── ConfirmEmergency.srv
    │   ├── CMakeLists.txt
    │   └── package.xml
    │
    └── warehouse_bringup/
        ├── launch/
        │   └── safety_system.launch.py
        └── config/
```

---

# 28. Configuration 예시

`fall_detection.yaml`

```yaml
fall_detection:
  aspect_ratio_threshold: 1.5

  orientation:
    horizontal_angle_min: 0.0
    horizontal_angle_max: 30.0

  centroid:
    floor_distance_threshold: 0.20

  motion:
    centroid_displacement_threshold: 3.0
    mask_iou_threshold: 0.95
    optical_flow_threshold: 0.5

  timer:
    fall_suspected_duration: 1.0
    fallen_duration: 2.0
    immobile_duration: 5.0

  score:
    aspect_ratio_weight: 0.30
    orientation_weight: 0.50
    centroid_height_weight: 0.20
    fall_threshold: 0.70
```

위 값은 placeholder이며 실제 데이터 기반 calibration이 필요하다.

---

# 29. 데이터 수집 시나리오

LEGO 데이터는 최소 다음 상태를 포함한다.

## Normal

```text
서 있음
걷는 중
방향 전환
잠시 정지
```

## Normal but difficult

```text
몸을 숙임
물건 줍기
앉기
작업대 가까이 접근
로봇 옆에 서 있음
```

## Fall

```text
앞으로 쓰러짐
뒤로 쓰러짐
좌측으로 쓰러짐
우측으로 쓰러짐
비스듬하게 쓰러짐
```

## Fall + Motion

```text
쓰러진 뒤 다시 움직임
쓰러진 뒤 일어남
```

## Emergency Candidate

```text
쓰러진 뒤 장시간 움직이지 않음
```

---

# 30. 카메라 환경 variation

3온도 물류센터를 고려하여 데이터 수집 시 아래 variation을 포함한다.

```text
밝은 조명
어두운 조명
냉동창고 저조도
조명 색 변화
부분 가림
로봇이 앞을 지나가는 상황
다른 작업자와 겹치는 상황
카메라 노이즈
```

---

# 31. Evaluation Metrics

단순 segmentation mAP만 보지 않는다.

서비스 기준 metric을 별도로 정의한다.

## Perception

```text
Segmentation Precision
Segmentation Recall
Tracking ID Switch
```

## Fall Detection

```text
Fall Precision
Fall Recall
False Alarm Rate
```

## Safety Event

```text
Emergency Candidate Recall
False Emergency Candidate Rate
Detection Latency
```

특히 안전 시스템에서는:

```text
False Negative
=
실제로 쓰러져 있는데 감지 실패
```

를 중요하게 본다.

---

# 32. 테스트 케이스

## TC-01 정상 작업자

```text
LEGO worker 서 있음
→ NORMAL 유지
```

## TC-02 걸어가는 작업자

```text
LEGO worker 이동
→ NORMAL
```

## TC-03 물건 줍기

```text
잠시 몸을 숙임
→ FALL_SUSPECTED가 발생하더라도 NORMAL 복귀
→ Alert 발생하면 안 됨
```

## TC-04 낙상 후 바로 일어남

```text
horizontal pose
→ FALL_SUSPECTED
→ movement 발생
→ NORMAL
```

## TC-05 낙상 후 장시간 정지

```text
horizontal pose
+
N초 이상 움직임 없음
→ EMERGENCY_CANDIDATE
```

## TC-06 다중 작업자

```text
worker_01 정상
worker_02 쓰러짐
worker_03 이동

→ worker_02만 alert
```

## TC-07 Tracking loss

```text
작업자가 로봇에 잠시 가려짐

→ 짧은 tracking loss는 ID 유지
→ 바로 비상 이벤트를 생성하지 않음
```

---

# 33. 로그

모든 safety event를 DB 또는 파일에 기록한다.

추천:

```text
timestamp
worker_id
zone
state_before
state_after
fall_score
immobile_duration
alert_sent
operator_decision
```

관리자 판단:

```text
confirmed
false_positive
```

추후 threshold calibration 및 모델 개선 데이터로 활용한다.

---

# 34. MVP 범위

반드시 구현:

```text
YOLOE Segmentation
ByteTrack
Mask PCA Orientation
BBox Aspect Ratio
Centroid Height
Centroid Motion
Mask IoU
State Machine
ROS2 Alert
관제센터 관리자 확인
```

선택:

```text
Optical Flow
Custom YOLO Pose
ST-GCN
PoseC3D
```

---

# 35. 최종 권장 기술 스택

```text
Camera
RealSense D455f 또는 RGB Camera

Vision
OpenCV
Ultralytics
YOLOE-Seg

Tracking
ByteTrack / BoT-SORT

Geometry
NumPy
OpenCV PCA 또는 sklearn PCA

Motion
Centroid displacement
Mask IoU
Optional OpenCV Optical Flow

Middleware
ROS2 Jazzy

Safety Logic
Python State Machine

Visualization
OpenCV Overlay
Web Dashboard 또는 ROS2 기반 관제 UI

Database
PostgreSQL / MySQL
```

---

# 36. Codex 구현 지시사항

Codex는 다음 순서로 구현한다.

## Step 1

`warehouse_perception` ROS2 Python package 생성.

Camera topic을 받아 YOLOE segmentation 수행.

Output:

```text
worker mask
bbox
confidence
```

---

## Step 2

ByteTrack 또는 Ultralytics track mode를 연결하여 worker ID 생성.

Output:

```text
worker_id
mask
bbox
```

---

## Step 3

`MaskFeatureExtractor` class 생성.

method:

```python
get_aspect_ratio()
get_mask_orientation()
get_mask_centroid()
get_normalized_floor_distance()
```

---

## Step 4

`MotionEstimator` class 생성.

method:

```python
get_centroid_displacement()
get_mask_iou()
get_optical_flow()
```

Optical Flow는 optional.

---

## Step 5

`FallDetector` class 생성.

입력:

```text
MaskFeature
MotionFeature
```

출력:

```text
fall_score
```

threshold와 weight는 YAML에서 읽는다.

---

## Step 6

`FallStateMachine` class 구현.

상태:

```python
NORMAL
FALL_SUSPECTED
FALLEN
IMMOBILE
EMERGENCY_CANDIDATE
```

각 worker ID별 state를 독립적으로 관리한다.

---

## Step 7

ROS2 custom msg 작성.

```text
WorkerState.msg
FallEvent.msg
```

---

## Step 8

`EMERGENCY_CANDIDATE` 발생 시 다음 topic publish.

```text
/emergency/fall_candidate
```

중복 경고 방지를 위한 cooldown 또는 event lock을 구현한다.

---

## Step 9

관리자 응답용 service 작성.

```text
/confirm_emergency
```

request 예:

```text
worker_id
confirmed
```

---

## Step 10

confirmed=true이면 Emergency Manager 호출.

초기 MVP에서는 실제 로봇 정지 대신 log 출력으로 구현한다.

```text
STOP TASK SCHEDULING
BLOCK ZONE
SAFE STOP ROBOT
```

이후 실제 Task Manager와 연동한다.

---

# 37. 구현 원칙

1. 모든 threshold는 코드에 hard coding하지 말고 YAML로 분리한다.
2. worker별 상태를 dictionary 형태로 독립 관리한다.
3. 한 프레임 결과만으로 비상 이벤트를 발생시키지 않는다.
4. segmentation confidence와 tracking confidence가 낮으면 상태 전이를 보수적으로 처리한다.
5. tracking이 몇 프레임 끊겼다고 바로 worker를 삭제하지 않는다.
6. Alert는 AI 판단이 아니라 `Emergency Candidate`로 정의한다.
7. 최종 Emergency Confirm은 관리자 입력을 받는다.
8. perception failure와 safety state를 분리한다.
9. 모든 상태 전이는 로그로 저장한다.
10. 향후 custom LEGO pose model을 추가할 수 있도록 interface를 분리한다.

---

# 38. 최종 기능 정의

기능명:

**비전 기반 작업자 이상 자세·무움직임 감지 및 비상상황 관제 시스템**

영문:

**Vision-based Worker Abnormal Posture & Immobility Detection System**

정의:

> 물류센터 내 작업자를 비전 기반으로 지속 추적하고, 비정상적인 수평 자세와 일정 시간 이상의 무움직임이 동시에 감지될 경우 이를 비상 후보 상황으로 관제센터에 전달한다. 관리자는 실시간 영상과 감지 정보를 바탕으로 비상 여부를 최종 판단하며, 비상상황으로 확인된 경우 해당 구역 로봇 작업 중단 및 접근 제한 등 안전 프로세스를 수행한다.
