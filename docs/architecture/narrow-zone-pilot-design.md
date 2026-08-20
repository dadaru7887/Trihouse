# 협로 규칙 주행 통합 설계

Nav2 가 통과하지 못하는 도크 앞 좁은 통로를, `dev_driving` 의 규칙 기반 시퀀스를
가져와 P0 안에서 돌리기 위한 설계다. **아직 구현하지 않았다.**

## 왜 필요한가

숫자가 정한다.

| | 값 |
|---|---|
| 냉동 통로 폭 (`trihouse_map_01`) | 0.20 m |
| 로봇 필요 폭 (지역 costmap, padding 포함) | 0.14 m |
| 남는 여유 | 편측 **0.03 m** |
| AMCL 위치추정 오차 (실측 stddev) | **0.08 ~ 0.11 m** |

**위치추정 오차가 통과 여유의 세 배다.** Nav2 는 절대 좌표로 계획하므로 구조적으로
불가능하다. 2026-08-19 실측:

```
[planner_server]  [compute_path_to_pose] Aborting handle.
[behavior_server] Running spin  →  Initial checks failed for spin
[behavior_server] Initial checks failed for backup
```

경로 계획 실패 → 복구 → 실패 → 재시도. 로봇이 "나왔다 들어갔다" 를 반복하고, 결국
냉동창고에서 빠져나오지 못했다.

규칙 주행은 **진입점에서의 상대 이동**(회전 몇 rad, 후진 몇 m)이라 AMCL 오차가
누적되지 않는다.

## 무엇을 가져오고 무엇을 버리는가

원본: `~/vlm_rl_backup/Trihouse_segmentation/Trihouse/driving_fms/narrow3_rule_based_docking.py`

| | 가져온다 | 버린다 |
|---|---|---|
| `in_oriented_zone()` | 통로 방향으로 정렬한 직사각형 판정 | |
| `rotate_to_yaw()` · `drive_straight()` | 제자리 회전, 거리 기반 직진·후진 | |
| `ZONES` 시퀀스 형식 | 존마다 `[회전, 후진]` 명시 목록 | |
| **`cmd_vel` 직접 발행** | | **버린다.** 충돌 감지를 통째로 건너뛴다 |
| 사람이 지켜보는 전제 | | 버린다 |

## 핵심 — 안전 사슬 안으로 들어간다

지금 Nav2 의 속도 명령은 이 사슬을 지난다.

```
controller_server ─→ cmd_vel_nav ─→ velocity_smoother ─→ cmd_vel_smoothed
                                                            │
                                                     collision_monitor ─→ cmd_vel ─→ 로봇
                                                     LiDAR · FootprintApproach
                                                     time_before_collision 1.2 s
```

`narrow3` 은 맨 끝 `cmd_vel` 에 직접 쐈다. 그래서 파일 상단에 *"LiDAR 충돌 감지가 없음.
반드시 사람이 옆에서 지켜보다가 Ctrl+C"* 라고 적혀 있다.

**규칙 주행은 `cmd_vel_nav` 로 넣는다.** 가속 제한(velocity_smoother)과 충돌 감시
(collision_monitor)가 그대로 적용된다. 사람이 지켜봐야 하는 전제가 사라진다.

전제 조건: **Nav2 컨트롤러가 그 순간 같은 토픽에 쓰고 있으면 안 된다.** 규칙 주행에
들어가기 전에 진행 중인 `NavigateToPose` 를 반드시 취소한다.

## 어디에 끼워 넣는가

`fleet_node` 가 `ExecuteTransport` 를 처리하는 한가운데다. 원장과 RMF 는 아무것도
바뀌지 않는다 — 여전히 "도크에 도착했다" 는 결과만 받는다.

```
지금
  ExecuteTransport 수신 → NavigateToPose(도크 좌표) → 도착 판정 → arrived 발행

바뀐 뒤
  ExecuteTransport 수신
    └ 목적지에 협로 존이 등록돼 있나?
        아니오 → 지금과 같다
        예    → NavigateToPose(**존 진입점**)        ← Nav2 가 여기까지
                 → 진입 시퀀스 실행 (회전·후진)      ← 규칙 주행
                 → 도착 판정 → arrived 발행
```

**나올 때도 같다.** 다음 이동 명령을 받았는데 로봇이 협로 존 안이면, 먼저
`sequence_exit` 로 빠져나온 뒤 Nav2 에 넘긴다. 지금 냉동창고에 갇힌 것이 이 경로가
없어서다.

## 상태 기계

```
IDLE ─(협로 목적지 명령)→ APPROACH   Nav2 로 진입점까지
                              │
                              ↓ 진입점 도착 + 존 안 판정
                          ENTERING   시퀀스 실행 (회전 → 후진)
                              │
                              ↓ 시퀀스 완료
                           DOCKED    arrived 발행. 인계 대기
                              │
                              ↓ 다음 이동 명령
                          EXITING    sequence_exit 실행
                              │
                              ↓ 존 밖
                            IDLE     Nav2 에 넘김
```

각 전이에서 실패하면 **그 자리에 정지하고 실패를 보고한다.** 규칙 주행은 재시도하지
않는다 — 같은 값으로 다시 해도 같은 결과이고, 두 번째 시도가 첫 번째보다 위험하다.

## 중단 조건

시퀀스 실행 중 아래 중 하나라도 걸리면 즉시 멈추고 실패를 낸다.

| 조건 | 왜 |
|---|---|
| `collision_monitor` 가 정지 상태를 보고 | 앞에 무언가 있다 |
| 스텝별 시간 상한 초과 | 바퀴가 헛돌거나 끼었다 |
| 존 직사각형을 벗어남 | 예상 밖으로 밀렸다 |
| 안전 정지(`SafetyState.EMERGENCY`) | 사람 개입 |
| 명령 취소 | RMF 나 관제가 거둬들였다 |

## 존 정보를 어디에 두는가

**결정 필요.** 두 가지다.

| | 방식 | 장점 | 단점 |
|---|---|---|---|
| **가** | 로봇 쪽 설정 파일 (`config/narrow_zones.<map>.yaml`) | 작다. `narrow3` 형식 그대로 | 로봇이 지도별 지식을 갖는다 |
| **나** | 원장이 명령에 실어 보냄 (`handover_expected` 처럼) | 로봇이 추측하지 않는다. 설계 원칙과 일치 | 인터페이스 확장 필요 |

**결정: 우선 가(YAML)로 검증하고, 값이 맞는 것을 확인한 뒤 DB 로 옮긴다.**

지금 YAML 로 시작하는 이유는 셋이다.

1. **값이 아직 검증되지 않았다.** `dev_driving` 의 2026-08-15 실측을 옮겨 왔을 뿐, 이
   지도에서 돌려 본 적이 없다. 틀린 값을 어디에 두든 소용없다.
2. **한 존의 값은 한 곳에 있어야 한다.** 지금 스키마에서 진입점만 담을 수 있는 자리
   (`departure_pose`)가 있는데, 존은 진입점·직사각형·진입 시퀀스·탈출 시퀀스 넷이다.
   나눠 담으면 한 존의 값이 두 곳에 흩어진다.
3. **지도 결합이 드러난다.** 파일 이름 `narrow_zones.<지도>.yaml` 이 어느 지도의 값인지
   말해 준다.

### 검증 뒤 옮길 자리

`departure_pose` 는 지금 **이름만 있다** — 허용 필드 목록과 "null 이어야 한다" 는 검사
두 줄이 전부이고, 값을 받아 어디로도 보내지 않는다(`WaypointFeature`·
`map_project_waypoints`·`locations` 모두 컬럼이 없다).

자세 하나로는 존을 담지 못하므로, 옮길 때는 `map_project_waypoints` 에
**`narrow_zone JSON NULL`** 컬럼 하나를 더하는 형태가 자연스럽다. 흩어지지 않고
마이그레이션도 한 번이다. 그러면 경로가 이렇게 된다.

```
JSONL → physical_features → map_project_waypoints.narrow_zone
      → 지도 발행 projection → claim_command 응답 → ExecuteTransport.Goal → fleet_node
```

`handover_expected` 를 실어 보낸 것과 같은 길이고, **지도 revision 과 함께 발행**되므로
지도와 존 값이 갈라질 수 없다는 이점이 생긴다. 지금 YAML 이 파일 이름으로만 지키는
것을 원장이 구조적으로 지켜 준다.

키는 `destination_code` 다 — `ExecuteTransport.Goal` 에 이미 들어 있다.

```yaml
# config/narrow_zones.trihouse_map_01.yaml
frozen_storage_loading_dock_01:
  entry:    { x: 0.920, y: -1.189, yaw: -0.032 }   # 2026-08-15 실측
  zone:     { length: 0.10, width: 0.20 }
  enter:    [ [straight, 0.10], [rotate, -1.525], [straight, -0.315] ]
  exit:     [ [straight, 0.315], [rotate, -2.999], [exit_zone, null] ]
  measured: { date: 2026-08-15, stddev_x: 0.158, stddev_y: 0.043, stddev_yaw: 0.305 }
```

## 만들 것 · 고칠 것

| | 파일 | 내용 |
|---|---|---|
| 신규 | `trihouse_pinky_fleet/narrow_zone_pilot.py` | 존 판정 · 시퀀스 실행 · 중단 조건. `cmd_vel_nav` 로 발행 |
| 신규 | `config/narrow_zones.trihouse_map_01.yaml` | 존 표 |
| 수정 | `fleet_node.py` | 목적지에 존이 있으면 진입점으로 Nav2 → 시퀀스. 다음 명령 시 탈출 시퀀스 |
| 수정 | `trihouse_pinky.launch.py` | 존 파일 경로 인자 |
| 신규 | 테스트 | 존 판정, 시퀀스 순서, 중단 조건. **`cmd_vel` 을 직접 쏘지 않는지** |

## 검증 순서

```
1. 존 판정만          로봇을 진입점에 두고 "존 안" 판정이 나오는지
2. 회전만             시퀀스의 첫 스텝만 실행. 바구니가 선반을 향하는지
3. 진입 전체          회전 + 후진. 벽에 닿지 않는지
4. 탈출 전체          되돌아 나오는지
5. 사이클             주문 → 도착 → 적재 → 탈출 → 포장대
```

**1~4 는 주문 없이 한다.** 원장을 끌어들이면 실패했을 때 원인이 둘로 늘어난다.

## 남는 문제

- **`cmd_vel_nav` 경합** — Nav2 컨트롤러가 활성인 채로 규칙 주행이 들어가면 두 발행자가
  싸운다. 진입 전 `NavigateToPose` 취소가 확실히 되는지 확인이 필요하다.
- **오도메트리 드리프트** — 후진 0.315 m 를 오도메트리로 잰다. 바퀴가 미끄러지면 그만큼
  어긋나고, 규칙 주행에는 되먹임이 없다.
- **지도 결합** — 지도를 다시 그리면 존 값을 전부 다시 재야 한다.
  [p0-narrow-zone-measurement.md](../runbooks/p0-narrow-zone-measurement.md) 참고.

## 이것이 임시라는 것

최종형은 [marker-docking-design.md](marker-docking-design.md) 의 마커 기반 도킹이다.
마커 상대 좌표로 정렬하므로 지도가 바뀌어도 마지막 구간이 그대로 동작하고, 되먹임이
있어 드리프트에도 강하다. **도킹이 붙으면 이 층은 걷어내는 것이 맞다.**

그럼에도 지금 만드는 이유는, 도킹이 카메라 캘리브레이션·마커 부착·인식 검증을 거쳐야
하는데 그 사이에도 사이클을 돌려 원장 쪽 로직을 검증해야 하기 때문이다.

관련: [p0-narrow-zone-measurement.md](../runbooks/p0-narrow-zone-measurement.md) ·
[marker-docking-design.md](marker-docking-design.md)
