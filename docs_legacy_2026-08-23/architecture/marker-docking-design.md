# 마커 기반 도킹 설계 (보류 중)

로봇이 적재 도크에 정밀하게 들어가는 마지막 0.2~0.5 m 를 어떻게 처리할지 정한 것이다.
**아직 구현하지 않았다.** 한 사이클 완주가 먼저이고, 이 문서는 그 뒤에 착수할 때
다시 읽으려고 남긴다.

## 왜 필요한가

Nav2 의 RPP 컨트롤러로는 좁은 도크에 들어가지 못한다. 이유는 셋이다.

| `nav2_params.yaml` | 값 | 문제 |
|---|---|---|
| `allow_reversing` | `false` | 도크 진입은 후진이다. Pure Pursuit 은 후진을 못 한다 |
| `min_lookahead_dist` | `0.3` | 폭 0.20 m 통로에서 0.3 m 앞을 보면 carrot 이 벽 너머에 놓인다 |
| `use_collision_detection` + `max_allowed_time_to_collision_up_to_carrot` | `true` / `1.0` | 그 원호를 검사해 `collision ahead` 로 거절한다 |

`dev_driving/driving_fms/narrow3_rule_based_docking.py` 의 docstring 이 같은 결론을
먼저 적어 두었다 — *"inflation / lookahead / rotate_to_heading / allow_reversing 을 다
시도해도 RPP 가 계속 collision ahead 로 막혀서"*. **파라미터 조정은 이미 실패한 접근이다.**

## 결정 사항

- 마커는 **확인 신호가 아니라 제어 입력**으로 쓴다. 마커 상대 좌표로 정렬하므로 지도를
  다시 그려도 마지막 구간은 영향을 받지 않는다.
- 도킹 엔진은 **`opennav_docking` 을 쓴다.** 자체 구현하지 않는다.
- 우리 `Dock.action` 은 원장과 맞물리는 **얇은 래퍼**로 남긴다.

## 왜 섞는가

`opennav_docking` 은 대기 지점 이동·정밀 제어·재시도·타임아웃·**충돌 감시**를 이미 갖고
있다. 마지막 항목이 특히 중요하다 — `narrow3` 은 `cmd_vel` 을 직접 쏘면서 충돌 감지가
없어 "사람이 옆에서 지켜보다가 Ctrl+C" 를 전제했다. 그것을 제도화하지 않는다.

반대로 `nav2_msgs/DockRobot` 에는 `job_id`·`job_step_id` 가 없어 원장에 결과를 적을 수
없다. 우리 `Dock.action` 이 그 자리를 채운다.

## 책임 분담

```
FMS Gateway                도킹 결과를 step 결과로 기록
    ▲ Dock.action (우리 계약: job_id·job_step_id·marker_id)
fleet_node 의 Dock 서버     ← 새로 만든다 (얇음). 상태·오류를 매핑한다
    ▲ nav2_msgs/DockRobot
opennav_docking            ← 설정만. SimpleNonChargingDock 플러그인
+ SimpleNonChargingDock       대기 지점 · 정밀 제어 · 재시도 · 충돌 감시
    ▲ PoseStamped (검출된 마커, 카메라 광학 프레임)
ArUco 검출 노드             ← 새로 만든다. RTSP → detectMarkers → solvePnP
```

`SimpleNonChargingDock` 을 쓰는 이유는 적재 도크가 충전기가 아니기 때문이다
(`isCharging()` 이 의미가 없다). 이 플러그인은 `use_external_detection_pose` 로 외부
검출 pose 를 토픽으로 받도록 이미 설계돼 있다 — 헤더 주석이 *"image_proc::TrackMarkerNode
같은 외부 참조로 도크를 검출할 수 있다"* 고 적고 있다.

## 상태·오류 매핑

| `DockRobot` 피드백 | 우리 `Dock.action` |
|---|---|
| `NAV_TO_STAGING_POSE` | `STATE_SEARCHING` |
| `INITIAL_PERCEPTION` | `STATE_ALIGNING` |
| `CONTROLLING` | `STATE_APPROACHING` |
| `RETRY` | `STATE_ALIGNING` |
| 성공 후 자체 확인 | `STATE_VERIFYING` |

| `DockRobot` 오류 | 우리 코드 | `outcomes.py` 도메인 |
|---|---|---|
| `FAILED_TO_DETECT_DOCK` | `CODE_MARKER_LOST` | `perception` — **코드 신규 추가 필요** |
| `FAILED_TO_CONTROL` · `FAILED_TO_STAGE` | `CODE_TOLERANCE_NOT_REACHED` | 기존 `GOAL_TOLERANCE_NOT_MET` |

## 만들 것 · 고칠 것

| | 파일 | 내용 |
|---|---|---|
| 신규 | `trihouse_pinky_vision/aruco_dock_detector_node.py` | RTSP → `detectMarkers` → `solvePnP` → `PoseStamped` + `MarkerObservation` |
| 신규 | `trihouse_pinky_fleet/dock_node.py` | `Dock.action` 서버 ↔ `DockRobot` 클라이언트 |
| 신규 | 도크 데이터베이스 | 도크 3건. **손으로 적지 말고 `p0_runtime_assets.py` 가 발행된 지도에서 생성한다** |
| 신규 | 카메라 내부 파라미터 | 캘리브레이션 결과 |
| 수정 | 카메라 **광학 프레임** | URDF 에 `front_camera_link` 는 있으나 광학 프레임이 없다. `pinky_pro` 는 읽기 전용이므로 우리 launch 에서 `static_transform_publisher` 로 얹는다 |
| 수정 | nav2 파생본 | `docking_server` 절이 지금 **없다** |
| 수정 | `trihouse_pinky.launch.py` | `docking_enabled` 인자는 있으나 **아무것도 띄우지 않는다** |
| 수정 | `fleet_node.py` | `requires_precise_stop` 인 도착에서 `Dock.action` 호출 |

## dev_driving 에서 가져올 곳

경로: `~/vlm_rl_backup/Trihouse_segmentation/Trihouse/driving_fms/`

| 파일 | 줄 | 무엇을 |
|---|---|---|
| `check_aruco_detection.py` | 62–66 | `build_detector()` — OpenCV 5.0 신 API. 그대로 재사용 |
| | 69–74 | `marker_pixel_size()` — 거리 대리지표 |
| | 76–82 | `estimate_distance_m()` — **캘리브레이션 없으면 오차 큼**이라고 저자가 명시 |
| | 232–266 | 검출 루프. `STATE_SEARCHING` 의 본체 |
| | 206–207 | CSV 헤더 — 도킹 피드백에 필요한 값이 이미 다 정의돼 있다 |
| `mission_goal_state_machine.py` | 111–120 | `ARUCO_ARRIVAL_MIN_PIXEL_SIZE = 24.6` — 실측 근거(직선거리 약 68 cm) |
| | 259–296 | `confirm_arrival_by_aruco()` — pixel_size + 연속 프레임 이중 게이트 |
| | 276–279 | AMCL 거리 게이트를 **뺀 이유**. 같은 함정을 반복하지 않기 위해 |
| `narrow3_rule_based_docking.py` | 225–246 | `rotate_to_yaw()` |
| | 247–277 | `drive_straight()` |
| | 204–214 | `in_oriented_zone()` — 원형이 아닌 **정렬된 직사각형** |
| | 41–120 | 세 구역의 실측 시퀀스와 stddev. 폴백 또는 초기값 |
| `aruco_recognition_distance_tests.jsonl` | 전체 | 마커 id 확정 근거. **검출 횟수 + 최대 픽셀 크기** 두 지표로 판별했다 |

`narrow3` 의 `cmd_vel` 직접 발행은 **가져오지 않는다.** 충돌 감시 아래로 들어가야 한다.

## 아직 정하지 않은 것

- **마커를 어디에 붙이나** — 도크 정면 벽인지 바닥인지. `external_detection_translation_x/y`
  값이 여기서 나온다. 실측 기록의 `recognition_pose` 는 *로봇이 마커를 확실히 인식한
  지점*이지 마커 자체 위치가 아니다.
- **전진 진입인가 후진 진입인가** — `narrow3` 은 셋 다 후진이었다. 후진이면 도크에
  다가갈수록 앞 카메라가 마커를 잃는다. 뒤 카메라가 없다면 "마커로 정렬 → 돌아서 후진"
  이 되고, 후진 구간은 마커 없이 간다. 도킹 서버의 `CONTROLLING` 이 마커를 계속
  요구하는지 확인이 필요하다.
- **`pixel_size` 인가 미터인가** — `Dock.action` 이 `linear_tolerance_m` 을 요구하므로
  계약대로 가려면 캘리브레이션이 선행된다.

## 시뮬레이션의 한계

Gazebo world 는 바닥면뿐이라 **마커가 없다.** 도킹은 실물에서만 검증되거나, world 에
마커 판을 세워야 한다. 카메라 자체는 2026-08-19 의 센서 수정으로 살아났다.

관련 문서: [waypoint-operational-roles.md](waypoint-operational-roles.md) ·
[p0-simulation-quick-run.md](../runbooks/p0-simulation-quick-run.md)
