# trihouse_pinky_docking

> 상태: **규칙 기반 후진 도킹 구현됨** (2026-08-20). 마커 기반은 아직 계획이다.

## 지금 있는 것 — 규칙 기반 후진 도킹

Nav2 로는 못 들어간다. RPP 는 후진을 못 하고(`allow_reversing` 은 전역 경로에 이미
방향 전환점이 있을 때만 쓸모가 있는데 NavFn 은 그런 경로를 만들지 않는다), 더
근본적으로 **냉동 도크 통로 0.20 m 안에서는 회전 지름 0.34 m 인 로봇이 돌 수 없다.**

풀이는 회전과 후진을 나누는 것이다 — 넓은 곳에서 돌고, 좁은 통로는 곧게 후진으로
들어간다. 후진에는 회전 원이 아니라 로봇 폭만 필요하다.

| 파일 | 무엇 |
|---|---|
| `sequence.py` | 단계 실행 로직. ROS 없이 시험한다 |
| `zones.py` | 실측 구역 설정 읽기 |
| `config/zones.yaml` | 2026-08-15 실물 실측값. **손으로 지어내지 않는다** |
| `dock_node.py` | TF 로 pose 를 읽고 `cmd_vel_dock` 으로 낸다 |

원본(`dev_driving` 의 `narrow3_rule_based_docking.py`)은 `/cmd_vel` 을 직접 쐈고
충돌 감지가 없어 *"사람이 옆에서 지켜보다가 Ctrl+C"* 를 전제했다. 여기서는
`cmd_vel_dock` 으로 내보내 `safety_supervisor` 아래로 들어간다 — 사람이 지켜보던
자리를 안전 gate 가 대신하고, 그 gate 는 후진할 때 보호 필드를 뒤로 뒤집는다.

거리는 시간이 아니라 **실제 이동량**으로 잰다. gate 가 감속하거나 멈추면 시간
기준으로는 덜 가서 도크에 못 닿는다.

**냉장(`chilled`)은 `verified: false` 다.** 2026-08-15 에 상온 값을 그대로
재사용했고 실물 검증되지 않았다. 지도 계산으로도 그 지점의 벽까지 여유가
0.05 m 라 회전이 안 될 가능성이 높다. `allow_unverified_zones` 로 명시하지 않으면
실행되지 않는다.

## 아래는 마커 기반 계획 (아직)

## 1. 목적과 책임

Nav2가 도킹 전 위치에 도착한 뒤 ArUco 상대 pose를 이용해 마지막 정밀 정차를 수행한다.

## 2. 넣지 않을 기능

장거리 경로 계획, 마커 영상 검출, camera-to-base 변환, 모터용 `/cmd_vel` 직접 발행을 넣지 않는다.

## 3. 계획된 노드와 작업

- `dock_action_server`: goal lifecycle, timeout, 취소, 결과 관리
- freshness/신뢰도/marker ID 검증
- 선형·각 P 제어, tolerance와 최대 속도 제한
- 마커 소실 즉시 0 출력, 제한된 탐색/재시도, 마지막 open-loop 구간

## 4. 발행·구독 토픽

`/trihouse/vision/marker_observation/base` (`MarkerObservation`)와
`/trihouse/vision/readiness` (`Readiness`)를 구독하고 `/cmd_vel_dock`
(`geometry_msgs/msg/Twist`)을 safety에 발행한다. vision readiness가 READY가
아니면 도킹을 시작하지 않으며, 동작 중 내려가면 정지한다.

## 5. 제공·호출 서비스

없음.

## 6. 제공·호출 액션

`/trihouse/dock` (`trihouse_interfaces/action/Dock`)을 제공하며 fleet만 호출한다.
action feedback은 상대 오차, 상태와 재시도 횟수를 포함한다.

## 7. 사용하는 공용 인터페이스

`MarkerObservation`, `Readiness`, `Dock`.

## 8. pinky_pro 참조

Nav2 action 결과와 URDF base/camera frame을 참조한다. 제어 출력은 벤더 모터가 아니라 safety 입력에 연결한다.

## 9. 설정 파일 후보

marker ID/크기, 목표 offset, 선형·각 gain, 속도 상한, pose/capture timeout, tolerance, 최대 3회 재시도, 마커 최소 관측 거리와 open-loop 시간.

## 10. 구현 순서와 완료 조건

1. 기록된 marker pose로 controller 단위 테스트를 만든다.
2. 취소/timeout/소실 정지를 구현한다.
3. simulation에서 safety 경유 토픽을 검증한다.
4. 실물에서 저속으로 오차와 재시도를 조정한다.

완료 조건은 마커 소실 시 즉시 정지하고, 최대 재시도 후 명확한 `DOCK_FAILED`를 반환하며, 허용 오차 안에서 반복 정차하는 것이다.
