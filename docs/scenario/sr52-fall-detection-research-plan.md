# SR52 사람 쓰러짐 감지 기술 조사·구현 계획

상태: **조사·계획 단계 — 구현 코드와 자동 테스트를 추가하거나 변경하지 않음**

이 문서는 `System Requirements.md`의 SR_52를 구현하기 전에 합의해야 할 데이터, 시간적 판정,
오경보 대응, 운영자 승인과 평가 방법을 정리한다. 기존
`vision_system/person_worker/policy.py`의 `observe_fall()`은 단순 정책 초안으로 남아 있으며,
이 문서의 완료 근거나 배포 가능한 쓰러짐 감지기로 사용하지 않는다.

## 조사 결론

1. **사람 box 한 프레임 또는 낮은 자세만으로 비상을 만들지 않는다.** 바닥 작업, 쪼그림,
   선반 아래 물품 확인, 가림은 쓰러짐과 유사하다. 연구도 pose를 시계열로 처리해 자세와 동작을
   함께 보며, 다중 사람 가림은 keypoint 오류와 오경보를 높이는 문제로 지적한다.
2. **1차 배포 후보는 `person detector/tracker → pose → temporal verifier`다.** 기존 사람 검출과
   추적 ID를 재사용하고, pose keypoint에서 몸통 각도·머리/골반의 바닥 방향 높이·수직 낙하 속도를
   계산한 뒤, 동일 track ID의 시간 창으로 검증한다. 별도 RGB video action model은 이 baseline이
   검증된 뒤 비교한다.
3. **비상은 모델의 최종 판정이 아니다.** Vision은 `FALL_SUSPECTED` 증거 묶음만 만들고,
   Control Tower가 incident·keep-out을 열며, Pinky Safety Supervisor는 FMS의 승인된
   emergency request 또는 자신의 거리 센서 위험만으로 정지한다.
4. **평가 기준은 accuracy 하나가 아니다.** 이벤트 단위 recall/precision, 시간당 false alarm,
   감지 지연 p50/p95, camera·구역·조도·가림별 오류를 모두 본다. NIST의 영상 분석 평가도
   activity/event detection에서 시간 기반 false alarm을 별도 지표로 다룬다.

## 제안 파이프라인 (승인 전 설계)

```text
RTSP frame
  → person detector + tracker (camera_id, track_id)
  → pose quality gate (필요 keypoint confidence, visible joints)
  → per-track temporal features
       [몸통 수평도, head/hip 바닥 상대 위치, 수직 속도, bbox 종횡비,
        centroid 이동량, occlusion/track continuity]
  → 후보: FALL_CANDIDATE
  → 정지 시간·추적 안정성·재기립 부재 검증
  → FALL_SUSPECTED evidence bundle
  → Control Tower incident 생성 및 운영자 확인
  → 승인된 emergency request / keep-out → Pinky Safety Supervisor
```

### 상태와 전이

| 상태 | 진입 조건 | 이탈 조건 | 외부 효과 |
| --- | --- | --- | --- |
| `MONITORING` | 추적 가능한 사람 또는 프레임 대기 | 유효한 낙하 후보 | 없음 |
| `FALL_CANDIDATE` | 동일 track에서 급격한 수직 변화와 낮은 자세가 시간 창 안에 관측됨 | 정상 보행/기립, track 품질 부족, 시간 초과 | evidence buffer pin 시작 |
| `POSTURE_STATIC_VERIFY` | 낮은 자세가 유지되고 필요한 keypoint 품질을 만족 | 움직임/기립 감지 시 `MONITORING`; 정지 기준 충족 시 suspected | pre/post 영상 구간 보존 |
| `FALL_SUSPECTED` | track·pose·정지 조건을 모두 만족 | 운영자 확인/해제는 Vision 상태가 아닌 incident workflow의 책임 | Control Tower에 구조화된 evidence 전송 |
| `UNOBSERVABLE` | 가림, keypoint 품질 저하, track switch 의심 | 새로 안정 추적됨 | 안전 정지나 비상 생성 금지, 품질 metric만 기록 |

`FALL_CANDIDATE`와 `FALL_SUSPECTED`의 시간·confidence threshold는 이 문서에서 숫자로 고정하지
않는다. 카메라별 시야, FPS, 작업자 행동, 허용 오경보율이 측정되기 전의 임계값은 안전 계약이
아니기 때문이다.

## 데이터 계획

### 학습·사전검증 데이터

- 공개 benchmark는 단독 배포 근거가 아니라 모델 후보 비교용이다. UR Fall은 소규모 실내
  fall/일상행동 데이터이며, FallVision은 침대·의자·서 있는 상태의 fall/no-fall과 landmark
  영상을 제공한다.
- 공개 데이터의 참여자·배경·카메라와 창고 작업자는 다르므로, **train/test를 사람 ID와 카메라
  기준으로 분리**한다. 같은 원본 영상의 이웃 frame을 train과 test에 섞지 않는다.
- Trihouse 현장 데이터는 동의·접근 권한·보존 기간을 먼저 정하고 수집한다. 필수 negative는
  쪼그림, 바닥 청소, 상자 들기/내리기, 선반 확인, 휴식/앉기, 카메라 가림, 지게차·Pinky 통과,
  냉동·냉장 저조도와 반사다.
- 실제 낙상 재현은 안전 담당자의 승인, 매트, 스팟터, 중지 절차가 있는 통제 환경에서만 한다.
  위험한 현장 재현을 요구하지 않는다.

### 라벨 계약

한 clip 또는 event에는 다음을 남긴다.

| 필드 | 용도 |
| --- | --- |
| `camera_id`, `zone_id`, `recording_segment_uri` | 재현성과 녹화 evidence 조회 |
| `track_id`와 track continuity | 사람 단위 시간 판정·ID switch 분석 |
| `candidate_at`, `suspected_at`, `recovery_at` | 감지 지연과 정상 복귀 측정 |
| `event_class` | fall, near-fall, crouch, sit/lie-down, floor-work, occluded, unknown |
| pose/tracking quality | `UNOBSERVABLE`을 false negative와 구분 |
| human-review outcome | suspected, dismissed, confirmed 및 사유 |

## 배포 전 평가 게이트

다음 값은 운영자·안전 책임자와 합의해 설정한다. 합의 전에는 model을 비상 자동화에 연결하지
않는다.

| 게이트 | 측정 방법 | 통과 기준의 성격 |
| --- | --- | --- |
| Event recall | 실제 fall event 중 `FALL_SUSPECTED` 비율 | 놓침 위험 상한 |
| Precision / false alarm per camera-hour | 정상 작업 중 suspected 수 | 운영자 경보 피로 상한 |
| Detection delay p50/p95 | fall onset → suspected 시간 | 구조 대응 시간 예산 |
| Camera/zone robustness | 상온·냉장·냉동, 각 camera, 조도/반사/가림 slice | 특정 구역 성능 은폐 방지 |
| Track/pose quality coverage | 관찰 가능한 frame·event의 비율 | `UNOBSERVABLE` 비율 감시 |
| End-to-end evidence | event → recording segment → UI → approval trace | 사고 검토 가능성 |

offline benchmark 통과 후에는 **shadow mode**로 전환한다. shadow mode는 이벤트와 evidence를
기록하지만 로봇 정지·keep-out·경보 자동 확대를 만들지 않는다. 운영자 검토로 false alarm과
miss를 확인한 뒤에야 `FALL_SUSPECTED`를 관제 경고로 표시한다. 자동 emergency 확대는 그 다음의
별도 안전 승인 단계다.

## 구현이 허가될 때의 최소 계약

아래는 향후 코드 작성 시의 계약 초안이며, 이 문서에서 구현하지 않는다.

```json
{
  "type": "fall_suspected",
  "event_id": "uuid",
  "camera_id": "cam-fixed-01",
  "zone_id": "frozen-a",
  "track_id": "tracker-42",
  "candidate_at": "RFC3339 timestamp",
  "suspected_at": "RFC3339 timestamp",
  "model_version": "registry version",
  "evidence": {
    "pre_segment_uri": "recording URI",
    "post_segment_uri": "recording URI",
    "pose_quality": 0.0,
    "track_continuity": 0.0
  }
}
```

금지 사항:

- Vision 또는 VLM이 `/cmd_vel`을 발행하거나 safety latch를 해제하지 않는다.
- `FALL_SUSPECTED` 하나만으로 기존 작업을 자동 재개하지 않는다.
- 재생 중인/기록 중인 evidence segment를 retention이 삭제하지 않도록 SR_04 catalog 정책을 사용한다.
- 화면의 경보 확인과 emergency 해제 승인은 `authorization.py`의 관리자 권한 및 audit 기록을
  통과해야 한다.

## 승인 후 구현 순서

1. 카메라 배치, FPS/해상도, zone polygon, privacy·보존 정책, 운영자 escalation 시간을 합의한다.
2. 데이터 수집·라벨링 계약과 subject/camera-disjoint split을 확정한다.
3. 공개 데이터로 pose-temporal baseline과 RGB temporal baseline을 비교한다.
4. 현장 shadow mode에서 slice별 false alarm과 delay를 수집한다.
5. evidence schema·recording lookup·UI 경고를 **읽기 전용**으로 연결한다.
6. 운영자 confirmation과 keep-out 정책을 end-to-end drill로 검증한다.
7. 자동 emergency 확대 여부는 안전 책임자 승인과 rollback 기준이 있을 때만 결정한다.

## 참고 자료

- [Chen et al., Video Based Fall Detection Using Human Poses (2021)](https://arxiv.org/abs/2107.14633): pose를 시간
  입력으로 사용한 fall detection 접근과 실시간성 비교의 출발점.
- [FallVision benchmark dataset (2025)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11950752/): 다양한 낙상 자세와
  landmark 영상, 공개 benchmark의 데이터 다양성 한계 검토.
- [Person Fall Detection Using Weakly Supervised Methods (WACV 2024)](https://openaccess.thecvf.com/content/WACV2024W/RWS/papers/Madsen_Person_Fall_Detection_Using_Weakly_Supervised_Methods_WACVW_2024_paper.pdf):
  fall detection을 시간적 video anomaly 문제로 다루는 비교 근거.
- [NIST ActEV evaluation plan](https://actev.nist.gov/pub/TRECVID_ActEV_2021_EvaluationPlan.pdf): 시간 기반 false alarm을
  포함하는 영상 이벤트 평가 설계 참고.
