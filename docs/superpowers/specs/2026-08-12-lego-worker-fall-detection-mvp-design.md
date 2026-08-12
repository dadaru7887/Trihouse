# LEGO Worker Fall Detection MVP Design

## 목적과 범위

오늘 웹캠 또는 MP4 영상으로 LEGO 작업자의 비정상 수평 자세와 무움직임을 확인할 수 있는 로컬 MVP를 만든다. 시스템은 사고를 확정하지 않고 `EMERGENCY_CANDIDATE` 후보 이벤트만 생성한다. 관리자의 확인, 로봇 정지, 관제 UI, ROS2 토픽 발행은 이 MVP의 후속 통합 범위다.

당일 성공 조건은 다음과 같다.

- 동일한 CLI가 `--source 0` 웹캠과 `--source sample.mp4` 영상 파일을 모두 연다.
- segmentation mask로 자세와 움직임 feature를 계산한다.
- 정상 LEGO는 `NORMAL`, 누운 자세가 유지되면 단계적으로 상태가 전이된다.
- 누운 채 설정 시간 동안 움직이지 않으면 `EMERGENCY_CANDIDATE`가 화면과 JSONL 이벤트에 한 번 기록된다.
- 자세가 정상화되거나 의미 있는 움직임이 재개되면 후보 누적이 해제된다.
- 실제 모델 없이도 합성 mask 기반 자동 테스트로 feature와 시간 전이를 검증한다.

## 선택한 접근

기존 `vision_perception/segmentation/inference_stream.py`의 Ultralytics YOLOE 입력 경로를 재사용하되, 낙상 판정 코어를 모델과 OpenCV UI에서 분리한다. 모델 결과를 직접 처리하는 얇은 실행기가 mask와 tracking ID를 판정 코어에 전달한다. 이 구조는 오늘 실제 영상을 시험하면서도 검출 모델의 품질과 낙상 규칙의 정확성을 독립적으로 진단할 수 있게 한다.

OpenCV 색상/윤곽 검출기를 별도로 만들지 않는다. 모델 없는 현장 데모를 위한 중복 구현보다 합성 mask 자동 테스트와 기존 YOLOE 체크포인트 활용에 집중한다.

## 구성 요소와 책임

### 설정

YAML 파일은 fall score 가중치와 임계값, 움직임 임계값, 상태 유지 시간을 보관한다. 코드에는 데모 기본값을 넣지 않고 설정 로더가 누락 필드와 잘못된 범위를 시작 시 검증한다.

초기 데모값은 다음과 같다.

- `aspect_ratio_threshold`: 1.2
- `horizontal_angle_max_deg`: 30.0
- `centroid_floor_threshold`: 0.35
- `fall_score_threshold`: 0.65
- `aspect_ratio_weight`: 0.3
- `orientation_weight`: 0.5
- `centroid_height_weight`: 0.2
- `centroid_motion_threshold`: 0.02 (영상 대각선 기준 정규화 값)
- `mask_iou_threshold`: 0.95
- `fall_suspected_duration_sec`: 1.0
- `fallen_duration_sec`: 2.0
- `immobile_duration_sec`: 5.0
- `track_lost_timeout_sec`: 2.0

### Feature 추출

한 worker mask에서 다음 값을 계산한다.

- bbox 폭/높이 비율
- mask pixel PCA 주축의 수평 기준 각도(0~90도)
- mask 중심점의 정규화 좌표
- 영상 하단에서 중심점까지의 정규화 거리
- 이전 mask 중심점과의 영상 대각선 기준 변위
- 이전 mask와 현재 mask의 IoU

mask가 비어 있거나 면적이 너무 작으면 해당 관측을 유효하지 않은 것으로 처리하고 상태 전이에 사용하지 않는다. 첫 관측은 이전 mask가 없으므로 motion과 IoU를 `None`으로 두며, 무움직임 시간을 누적하지 않는다.

Fall score의 세 부분은 0~1 범위다. aspect ratio는 임계값 이상, orientation은 수평에 가까울수록, centroid는 설정된 바닥 영역에 가까울수록 점수가 높다. 총점은 설정 가중합이며 0~1로 제한한다.

### Worker 추적과 상태 머신

Ultralytics `track(..., persist=True, tracker="bytetrack.yaml")`의 track ID를 `worker_<id>`로 사용한다. 단일 LEGO 데모에서 모델이 ID를 제공하지 않으면 그 프레임의 가장 큰 mask만 `worker_01`로 처리한다. 다중 mask인데 ID가 없다면 잘못된 worker 결합을 피하기 위해 fallback하지 않고 경고한다.

worker별 독립 상태는 다음 순서로 전이한다.

1. `NORMAL`: fall score가 임계값을 넘으면 `FALL_SUSPECTED`로 이동하고 비정상 자세 시작 시간을 기록한다.
2. `FALL_SUSPECTED`: 자세가 계속 비정상이고 1초가 지나면 `FALLEN`으로 이동한다. 정상 자세가 되면 즉시 `NORMAL`로 복귀한다.
3. `FALLEN`: 비정상 자세와 low-motion이 유지되면 무움직임 시작 시간을 기록한다. 비정상 자세가 풀리면 `NORMAL`로, 움직임이 있으면 `FALLEN`에 머물며 무움직임 타이머만 초기화한다. `fallen_duration_sec` 이상 비정상 자세가 유지되고 low-motion이 확인되면 `IMMOBILE`로 이동한다.
4. `IMMOBILE`: low-motion 누적이 `immobile_duration_sec`에 도달하면 `EMERGENCY_CANDIDATE`로 이동한다. 움직임이 재개되면 `FALLEN`, 자세가 정상화되면 `NORMAL`로 복귀한다.
5. `EMERGENCY_CANDIDATE`: 동일 episode에서는 이벤트를 다시 만들지 않는다. 움직임 재개 시 `FALLEN`, 정상화 시 `NORMAL`로 복귀하며 이후 새 episode에서 새 이벤트를 만들 수 있다.

`low_motion`은 이전 관측이 있고, centroid 변위가 임계값 미만이며 mask IoU가 임계값을 초과할 때 참이다. 프레임이 잠시 사라져도 `track_lost_timeout_sec` 전에는 상태를 보존하고, 그 시간을 넘으면 worker 상태를 제거한다. 영상의 presentation timestamp가 유효하면 이를 상태 시간으로 사용하여 MP4 처리 속도에 관계없이 결과가 같게 하고, 웹캠은 monotonic 시간을 사용한다.

### 실행기와 출력

CLI는 model, source, config, output-event path, target FPS, display 여부를 받는다. 숫자로만 된 source는 카메라 인덱스로 변환하고 그 외는 파일 또는 URL로 OpenCV에 전달한다.

매 프레임에서 YOLOE tracking 결과를 adapter가 mask 관측으로 변환하고 worker별 판정 결과를 얻는다. 화면에는 mask/bbox, worker ID, 상태, fall score, motion/IoU를 표시한다. `q` 또는 ESC로 정상 종료한다. MP4가 끝나면 재접속하지 않고 종료하며, 웹캠/네트워크 입력 단절은 기존 스트림 정책에 맞춰 안전하게 중단한다.

후보 이벤트는 append-only JSONL로 기록한다. 필드는 `event_id`, `worker_id`, `event_type`, `state`, `fall_score`, `immobile_duration_sec`, `source`, `detected_at`이다. `event_type`은 `fall_candidate`이고 문구는 확정 표현을 사용하지 않는다. 파일 쓰기 실패는 화면/콘솔에 오류를 알리되 추론 루프 전체를 비정상 종료하지 않는다.

## 테스트 전략

단위 테스트는 실제 YOLOE 모델이나 카메라를 요구하지 않는다.

- 세로/가로 합성 직사각형 mask로 aspect ratio와 PCA 방향을 검증한다.
- 이동한 mask와 동일 mask로 centroid motion과 IoU를 검증한다.
- 명시적 timestamp를 주입해 전체 상태 전이와 정상 복귀를 검증한다.
- 움직임 재개가 무움직임 타이머를 초기화하는지 검증한다.
- 같은 episode에서 후보 이벤트가 한 번만 생성되고 정상 복귀 뒤에는 다시 생성되는지 검증한다.
- 잘못된 YAML 값과 빈 mask를 명확한 오류/무효 관측으로 처리하는지 검증한다.
- source 문자열 변환과 MP4 timestamp 선택을 검증한다.

수동 smoke test는 두 경로를 제공한다.

```bash
python -m vision_perception.fall_detection.cli --source 0 --model <weights.pt>
python -m vision_perception.fall_detection.cli --source demo.mp4 --model <weights.pt>
```

테스트자는 LEGO를 세운 상태, 쓰러뜨리는 동작, 쓰러진 채 5초 정지, 다시 세우는 동작을 차례로 보여준다. 화면 상태와 JSONL 이벤트가 성공 조건과 일치하는지 확인하고, 필요하면 YAML만 수정해 임계값을 보정한다.

## 실패 처리와 안전 경계

- 모델 또는 source를 열 수 없으면 실행 전에 구체적인 경로와 함께 실패한다.
- mask 또는 tracking ID가 불충분하면 사고를 추정하지 않고 해당 관측을 건너뛴다.
- 입력 단절 동안 마지막 frame을 반복 사용하거나 무움직임 시간을 누적하지 않는다.
- 후보 이벤트는 로봇 제어를 직접 호출하지 않는다.
- 화면과 이벤트 문구는 항상 “이상 자세 및 무움직임 후보”로 표현한다.

## 후속 통합

MVP 검증 후 `WorkerState.msg`, `FallEvent.msg`를 `trihouse_interfaces`에 추가하고 JSONL writer와 동일한 event interface를 ROS2 publisher로 구현한다. 이어 관제 UI의 관리자 확인 service와 Emergency Manager를 연결한다. Optical flow, 다중 카메라 re-identification, LEGO 전용 fine-tuning, custom keypoint 모델은 측정 결과가 필요성을 입증한 경우에만 추가한다.
