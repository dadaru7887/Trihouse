# robo_pinky — Gazebo Pinky ↔ 관제센터 가상 실험

3온도 물류센터 관제센터([`robo_control`](../robo_control/))에 **Gazebo 안의 Pinky
로봇**을 실장비처럼 물려 주는 ROS 2 워크스페이스입니다.

관제센터의 시뮬레이션 로봇(`RS-xx`)과 달리, 이 로봇들(`PK-xx`)은 관제가 위치를
계산하지 않습니다. **관제는 경로·정지·속도 상한만 내려보내고, 위치·방위·배터리는
로봇이 물리 엔진 위에서 실제로 움직인 결과를 보고합니다.** 배차·FEFO·안전·재고
로직은 두 경우 모두 완전히 동일하게 돌아갑니다.

구획마다 **OpenMANIPULATOR-X 적재 로봇팔**이 한 대씩 서 있습니다. 로봇이 랙에서
집품한 뒤 구획 적재 스테이션에 정차하면, 관제가 팔에 적재를 지시하고 팔이 화물을
로봇 위에 실어 준 다음 로봇이 출고 도크로 떠납니다.

```
 robo_control (Flutter)                    robo_pinky (ROS 2 + Gazebo)
┌───────────────────────┐   TCP 8788    ┌──────────────────────────────┐
│ FleetEngine           │  NDJSON       │ pinky_agent × 3   (주행 로봇)│
│  · 배차/FEFO/안전     │ ────────────▶ │  · 웨이포인트 추종 → cmd_vel │
│  · RobotLinkServer    │  path/hold    │  · 라이다 전방 감시          │
│                       │  speed/charge │  · 배터리 모델               │
│                       │ ◀──────────── │                              │
│                       │  telemetry    ├──────────────────────────────┤
│                       │               │ pinky_arm_agent × 3  (팔)    │
│                       │ ────────────▶ │  · 역기구학 → 집기·적재 궤적 │
│                       │  load/abort   │                              │
│                       │ ◀──────────── │                              │
│                       │ loaded/failed │ Gazebo Harmonic (물리·센서)  │
└───────────────────────┘  hello/log    └──────────────────────────────┘
```

## 문서

| 문서 | 내용 |
|---|---|
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | **실행·조작·문제 해결.** 무엇을 보게 되는지, 해 볼 만한 실험, 플릿·평면도 바꾸는 법 |
| [docs/PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md) | **설계 문서.** 좌표계·월드·로봇 모델·프로토콜 명세·제어 루프·설계 판단 기록·검증 |

## 요구 환경

| | |
|---|---|
| ROS 2 | Jazzy |
| Gazebo | Harmonic (gz-sim 8) |
| 그 외 | `ros_gz_sim`, `ros_gz_bridge`, `robot_state_publisher`, `xacro` |

## 빠른 시작

관제센터와 시뮬레이터는 **어느 쪽을 먼저 켜도 됩니다.** 에이전트는 관제가 열릴
때까지 재접속을 반복합니다.

```bash
# 터미널 1 — 관제센터
cd robo_control && flutter run -d linux

# 터미널 2 — Gazebo + Pinky 3대
cd robo_pinky && ./run.sh
```

`run.sh`는 빌드 후 런치까지 한 번에 합니다. 이미 빌드했다면:

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch robo_pinky_sim warehouse.launch.py
```

종료는 런치 터미널에서 `Ctrl+C`. Gazebo GUI 창을 닫는 것만으로는 종료되지
않습니다(의도된 동작 — [설계 문서 §11.3](docs/PROJECT_SUMMARY.md#113-gazebo-gui는-필수-프로세스가-아니다)).

### 자주 쓰는 인자

```bash
ros2 launch robo_pinky_sim warehouse.launch.py gui:=false        # 헤드리스
ros2 launch robo_pinky_sim warehouse.launch.py camera:=true      # 전방 카메라
ros2 launch robo_pinky_sim warehouse.launch.py agents:=false     # 관제 없이 수동 조종
ros2 launch robo_pinky_sim warehouse.launch.py arms:=none        # 로봇팔 없이
ros2 launch robo_pinky_sim warehouse.launch.py control_host:=192.168.0.10
```

전체 목록은 [사용 설명서 §5](docs/USER_GUIDE.md#5-런치-인자).

## 확인

```bash
ros2 topic echo /pinky_01/link_status
#   PK-01 연결 | (62.5, 42.0) unit | 배터리 93.1% | 잔여 WP 3 | 정상

ros2 topic echo /omx_c/arm_status
#   OMX-C@LOAD-C 연결 | loading | 누적 2건 | 진행 TSK-0042
```

관제센터 화면에서는

- 좌측 사이드바 하단 **현장 링크** — 접속 대수
- [로봇 관제] 상태 브로드캐스트 표의 🗼 아이콘 — 링크로 제어되는 로봇
- 상단 배속 선택기가 **1×로 잠김** — 실장비는 실시간으로 움직이므로 관제 시계도
  실시간으로 맞춘다

## 패키지

| 패키지 | 내용 |
|---|---|
| `robo_pinky_description` | Pinky · OpenMANIPULATOR-X URDF(xacro). 실기 치수를 따르되 메시 대신 기본 도형으로 재구성해 다중 스폰이 가볍다. 이름마다 링크·토픽이 분리된다 |
| `robo_pinky_sim` | 관제 평면도를 그대로 옮긴 창고 월드 + 생성 스크립트 + 플릿·로봇팔 런치 |
| `robo_pinky_agent` | 주행 로봇 에이전트(경로 추종·라이다 감시·배터리)와 로봇팔 에이전트(역기구학·적재 궤적) |

## 좌표계 요약

관제 `WarehouseLayout`는 120 × 72 unit의 화면 좌표계(좌상단 원점, y가 아래로
증가), Gazebo는 창고 중심이 원점인 미터 좌표계입니다.

```
x_m = (x_u - 60) * 0.1          y_m = (36 - y_u) * 0.1          yaw = -heading_u
```

1 unit = 0.1 m이므로 창고는 **12 m × 7.2 m**, 관제 기본 주행 속도 3.4 unit/s는
**0.34 m/s** — Pinky 정격(0.5 m/s) 안에 들어옵니다.
자세한 근거는 [설계 문서 §4](docs/PROJECT_SUMMARY.md#4-좌표계).

## 알려진 제약

- 로봇에 **지역 경로 재계획이 없습니다.** 통로 한복판의 예상 못 한 장애물 앞에서는
  정지하고 관제 이력에 사유를 올릴 뿐 스스로 우회하지 않습니다.
- 카메라는 기본 비활성입니다. 통합 GPU에서 로봇 대수만큼 렌더 패스가 늘면
  다른 GL 응용(관제센터 창 포함)까지 영향을 받습니다.

전체 목록은 [설계 문서 §13](docs/PROJECT_SUMMARY.md#13-한계와-향후-과제).
