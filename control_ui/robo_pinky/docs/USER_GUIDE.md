# robo_pinky 사용 설명서

**Gazebo Pinky ↔ 관제센터 가상 실험** · 문서 버전 1.0 (2026-07-29)

설계 배경과 프로토콜 명세는 [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)를 참고하세요.
이 문서는 **어떻게 띄우고, 무엇을 보고, 안 될 때 어떻게 하는지**만 다룹니다.

---

## 목차

1. [준비](#1-준비)
2. [실행](#2-실행)
3. [무엇을 보게 되는가](#3-무엇을-보게-되는가)
4. [해 볼 만한 실험](#4-해-볼-만한-실험)
5. [런치 인자](#5-런치-인자)
6. [로봇 플릿 바꾸기](#6-로봇-플릿-바꾸기)
7. [로봇팔 바꾸기](#7-로봇팔-바꾸기)
8. [평면도 바꾸기](#8-평면도-바꾸기)
9. [문제 해결](#9-문제-해결)

---

## 1. 준비

### 필요한 것

| | 버전 |
|---|---|
| ROS 2 | Jazzy |
| Gazebo | Harmonic (gz-sim 8) |
| Flutter | 관제센터 실행용 |

ROS 2 패키지 `ros_gz_sim` · `ros_gz_bridge` · `robot_state_publisher` · `xacro`가
설치되어 있어야 합니다. `ros-jazzy-desktop`에 모두 포함됩니다.

### 확인

```bash
source /opt/ros/jazzy/setup.bash
gz sim --versions            # 8.x
ros2 pkg list | grep ros_gz  # ros_gz_bridge, ros_gz_sim …
```

---

## 2. 실행

터미널 두 개를 씁니다. **어느 쪽을 먼저 켜도 됩니다.** 로봇은 관제가 열릴 때까지
재접속을 반복합니다.

### 터미널 1 — 관제센터

```bash
cd robo_control
flutter run -d linux
```

좌측 사이드바 하단에 `게이트웨이 대기 :8788`이 뜨면 준비된 것입니다.

### 터미널 2 — Gazebo + Pinky

```bash
cd robo_pinky
./run.sh
```

`run.sh`는 빌드부터 런치까지 한 번에 합니다. 처음 한 번만 오래 걸립니다.
Jazzy가 아닌 배포판이면 `ROS_SETUP=/opt/ros/<배포판>/setup.bash ./run.sh`로 지정하세요.

이미 빌드했다면 직접 실행해도 됩니다.

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch robo_pinky_sim warehouse.launch.py
```

### 종료

런치 터미널에서 **`Ctrl+C`** 를 누릅니다.

Gazebo GUI 창을 닫는 것으로는 종료되지 않습니다 — 물리 시뮬레이션과 관제 링크는
계속 돌아갑니다(의도된 동작). 창만 다시 열려면 `gz sim -g`를 실행하세요.

---

## 3. 무엇을 보게 되는가

### Gazebo 창

12 m × 7.2 m 창고입니다. 바닥 색이 3온도 구획을 나타냅니다.

| 보이는 것 | 의미 |
|---|---|
| 왼쪽 밝은 회갈색 바닥 | 상온 구획 |
| 가운데 옅은 청회색 | 냉장 구획 |
| 오른쪽 밝은 청색 | 냉동 구획 (조명이 가장 어둡습니다) |
| 4열로 늘어선 긴 블록 | 랙. 세로 통로가 지나는 자리는 비어 있습니다 |
| 바닥의 색 원반 | 스테이션 — 초록 입고 · 파랑 출고 · 노랑 충전소 · 분홍 작업대 · 회색 대기 · 빨강 비상 집결지 |
| 노란 작은 기둥 | 충전소 표시 |
| 분홍·하늘·노랑 로봇 | PK-01 · PK-02 · PK-03 |
| 주황 원반 3개 (통로 한가운데) | 적재 스테이션 LOAD-A · LOAD-C · LOAD-F |
| 그 옆 기둥 위 로봇팔 | OMX-A · OMX-C · OMX-F (구획마다 한 대) |
| 팔 뒤쪽 주황 상자 | 팔이 집어 올리는 화물대 |

로봇은 통로를 따라 움직이다가 랙 앞에서 **정면으로 붙어 정지**한 뒤, 집품이
끝나면 구획 적재 스테이션으로 갑니다. 거기 서면 로봇팔이 화물대에서 화물을
집어 **로봇 위에 실어 주고**, 그다음 로봇이 출고 도크로 떠납니다.

### 관제센터 화면

| 위치 | 확인할 것 |
|---|---|
| 사이드바 하단 **현장 링크** | `실장비 3대 접속` (로봇팔은 별도로 세지 않습니다) |
| 상단 바 배속 | **1×로 잠김**(자물쇠). 실장비는 실시간으로 움직이기 때문입니다 |
| [로봇 관제] 상태 브로드캐스트 | `PK-01` 앞 🗼 아이콘이 **초록** |
| [실시간 맵] | PK-xx가 RS-xx와 같은 평면도 위에서 함께 움직입니다 |
| 로봇 클릭 → 상세 패널 **안전 메모** | 로봇이 스스로 멈춘 사유 |
| [운행 이력] | 링크 접속·단절, 장애물 정지 지속, **로봇팔 적재 지시·완료** |
| [태스크·주문] 행 클릭 | 스텝 6개 — 이동·집품·**적재소 이동**·**적재**·이동·하역 |

### 터미널

```bash
ros2 topic echo /pinky_01/link_status
```

```
data: PK-01 연결 | (62.5, 42.0) unit | 배터리 93.1% | 잔여 WP 3 | 정상
```

```bash
ros2 topic echo /omx_c/arm_status
```

```
data: OMX-C@LOAD-C 연결 | loading | 누적 2건 | 진행 TSK-0042
```

| 항목 | 의미 |
|---|---|
| `연결` / `단절` | 관제 링크 상태 |
| `(x, y) unit` | 관제 좌표계 위치 |
| `잔여 WP` | 아직 지나지 않은 웨이포인트 수 |
| 끝 문구 | `정상` 또는 정지 사유 |

그 밖의 토픽:

```bash
ros2 topic list                       # /pinky_0N/{cmd_vel,odom,scan,imu,tf}
ros2 topic echo /pinky_01/scan --once
ros2 run rviz2 rviz2                  # 프레임 이름은 pinky_0N/ 접두어
```

---

## 4. 해 볼 만한 실험

### 4.1 비상정지가 실제 로봇을 멈추는지

1. 관제센터 상단 바 **전체 비상정지**
2. Gazebo에서 세 대 모두 **즉시 정지**
3. `ros2 topic echo /pinky_01/link_status` → `비상정지 스위치 작동`
4. 다시 눌러 해제하면 하던 경로를 이어서 진행

### 4.2 작업자 안전 필드

관제센터 [안전 관리]의 작업자 목록에서 각 작업자의 최근접 로봇 거리를 보면서
Gazebo를 함께 봅니다. 작업자가 로봇에 4 m(관제 좌표 8 unit) 안으로 들어오면
로봇이 눈에 띄게 느려지고, 1.7 m 안이면 멈춥니다.

> 작업자는 물리 월드에 모델이 없습니다. 관제센터가 계산한 안전 필드가
> **속도 상한**으로 로봇에 전달되어 실제 감속으로 나타납니다.

### 4.3 라이다가 관제보다 먼저 멈추는지

Gazebo GUI에서 로봇 앞 통로에 상자를 하나 놓아 봅니다
(상단 툴바 → Shapes → Box를 통로에 배치).

- 로봇이 상자 0.15 m 앞에서 정지
- `link_status` → `라이다 전방 0.14 m 장애물 — 전진 정지`
- 10초 지나면 관제 [운행 이력]에 경고로 기록
- 상자를 치우면 다시 출발

관제는 이 상자의 존재를 모릅니다. **로봇의 자기 안전 장치**가 관제 명령보다
우선한다는 것을 보여 줍니다.

### 4.4 링크 단절 복구

터미널 2에서 에이전트 하나만 죽입니다.

```bash
pkill -f agent_pinky_02
```

관제센터에서:

- PK-02의 🗼 아이콘이 **회색**으로
- 상태가 `예비 대기`, 활동이 `현장 링크 대기`
- 진행 중이던 태스크가 **대기열로 반환**되어 다른 로봇에 재할당
- [운행 이력]에 단절 기록

다시 띄우면 자동 복귀합니다.

```bash
ros2 run robo_pinky_agent pinky_agent --ros-args \
  -r __node:=agent_pinky_02 \
  -p robot_id:=PK-02 -p "robot_name:=핑키 2호" -p robot_model:=PINKY-GZ \
  -p gz_name:=pinky_02 -p home_charger:=CHG-2 \
  -p spawn_x:=35.0 -p spawn_y:=38.0
```

> 스폰 좌표는 **최초 스폰 위치**여야 합니다. 오도메트리가 그 지점을 원점으로
> 하기 때문입니다. 로봇이 이미 이동한 뒤라면 관제가 보는 위치가 어긋나므로,
> 런치를 통째로 다시 올리는 편이 간단합니다.

### 4.5 배터리 사이클

그대로 20~30분 두면 배터리가 20 % 아래로 내려가면서

1. 절전 모드 진입 — 관제가 속도 상한을 낮춰 실제로 느려집니다
2. 10 % 이하 — 홈 충전소로 복귀
3. 도킹 후 충전 — 관제가 `charge` 명령, 로봇이 배터리를 회복해 보고
4. 95 % 도달 시 작업 대기열 복귀

빨리 보려면 `fleet.yaml`에 낮은 초기 배터리를 주는 대신, 관제센터에서 로봇을
선택해 **충전소 회수**를 눌러도 됩니다.

### 4.6 로봇팔 적재 지켜보기

가장 볼 만한 장면입니다. 출고 태스크가 돌면 자동으로 일어납니다.

1. Gazebo에서 주황 원반(적재 스테이션) 근처로 시점을 옮깁니다
2. 로봇이 랙에서 집품한 뒤 그 자리로 와서 정차합니다
3. 팔이 **뒤쪽 화물대로 돌아 화물을 집고**(그리퍼 닫힘), **로봇 위로 180° 선회**해
   내려놓은 뒤(그리퍼 열림) 홈 자세로 돌아갑니다 — 약 10초
4. 로봇이 출고 도크로 떠납니다

같은 시각 관제센터에서:

- 로봇 상태가 **`적재 대기`**, 활동이 `LOAD-C 로봇팔이 … 3개 적재`
- [운행 이력]에 `LOAD-C 로봇팔에 PK-01 적재 지시` → `적재 완료 — PK-01 인수`

터미널에서 팔의 관절을 직접 볼 수도 있습니다.

```bash
ros2 topic echo /omx_c/joint_states --once
ros2 topic echo /omx_c/arm_status
```

> 그리퍼 개폐와 궤적은 실제로 움직이지만 **화물 객체가 손에 붙지는 않습니다.**
> 화물 인수인계는 관제 원장이 관리합니다(로봇 상세 패널의 적재물 표기).

### 4.7 로봇팔을 떼면 어떻게 되는지

```bash
pkill -f arm_omx_c
```

- [운행 이력]에 `OMX-C 적재 스테이션 링크 단절` 경고
- 냉장 구획 적재는 **수동 처리로 전환**되어 스텝이 시간으로 진행됩니다
- 운영은 멈추지 않습니다 — 팔이 없다고 출고가 막히지는 않습니다

### 4.8 카메라 켜기

```bash
ros2 launch robo_pinky_sim warehouse.launch.py camera:=true
ros2 run rqt_image_view rqt_image_view /pinky_01/camera/image_raw
```

> 통합 GPU에서는 로봇 대수만큼 렌더 부하가 늘어, 관제센터 창을 포함한 다른
> GL 응용이 불안정해질 수 있습니다. 필요할 때만 켜세요.

---

## 5. 런치 인자

```bash
ros2 launch robo_pinky_sim warehouse.launch.py <인자>:=<값> …
```

| 인자 | 기본값 | 설명 |
|---|---|---|
| `gui` | `true` | Gazebo GUI 표시. `false`면 헤드리스(가벼움) |
| `agents` | `true` | 관제 링크 에이전트 실행. `false`면 순수 Gazebo |
| `camera` | `false` | 전방 카메라 센서 |
| `control_host` | `127.0.0.1` | 관제센터 주소 |
| `control_port` | `8788` | 관제 링크 포트 |
| `fleet` | `config/fleet.yaml` | 스폰할 로봇 목록 |
| `arms` | `config/arms.yaml` | 적재 로봇팔 목록. `none`이면 띄우지 않는다 |
| `world` | `worlds/warehouse_3temp.sdf` | 월드 SDF |
| `scale` | `0.1` | 관제 1 unit 당 미터 |

자주 쓰는 조합:

```bash
# 사양이 낮은 PC — 헤드리스로 돌리고 관제 화면만 본다
ros2 launch robo_pinky_sim warehouse.launch.py gui:=false

# 관제를 다른 PC에서 돌린다
ros2 launch robo_pinky_sim warehouse.launch.py control_host:=192.168.0.10

# 로봇팔 없이 (관제는 적재 스텝을 자동 진행으로 처리)
ros2 launch robo_pinky_sim warehouse.launch.py arms:=none

# 관제 없이 로봇만 수동 조종
ros2 launch robo_pinky_sim warehouse.launch.py agents:=false
ros2 run teleop_twist_keyboard teleop_twist_keyboard \
  --ros-args -r /cmd_vel:=/pinky_01/cmd_vel
```

---

## 6. 로봇 플릿 바꾸기

[`src/robo_pinky_sim/config/fleet.yaml`](../src/robo_pinky_sim/config/fleet.yaml)을
편집합니다.

```yaml
robots:
  - id: PK-04                       # 관제 플릿 ID (기존과 겹치지 않게)
    name: 핑키 4호
    model: PINKY-GZ-C               # PINKY로 시작해야 관제가 링크 전용으로 취급
    gz_name: pinky_04               # Gazebo 모델명 겸 토픽 네임스페이스
    body_color: "0.55 0.85 0.55 1.0"
    zones: [ambient, chilled]       # 진입 가능 구획
    home_charger: CHG-2
    spawn_x: 65.0                   # 관제 좌표(unit)
    spawn_y: 22.0
    spawn_heading: 0.0              # 관제 좌표계 기준 radian
```

### 주의할 점

| 항목 | 규칙 |
|---|---|
| `id` | 기존 로봇(`RS-01`…, 다른 `PK-xx`)과 겹치면 안 됩니다 |
| `model` | **`PINKY`로 시작**해야 링크가 끊겼을 때 배차에서 제외됩니다 |
| `gz_name` | 영문·숫자·밑줄만. 하이픈은 gz 토픽 이름으로 쓸 수 없습니다 |
| `spawn_x` `spawn_y` | **통로 위**에 놓으세요. 랙 안이면 로봇이 끼입니다 |
| `zones` | `frozen`이 없으면 관제가 냉동 구역 태스크 입찰에서 제외합니다 |

통로 좌표는 아래 격자의 교차점입니다.

```
세로 통로 x = 5, 20, 35, 50, 65, 80, 95, 110
가로 통로 y = 6, 22, 38, 54, 68
랙 열     y = 13, 30, 46, 61   ← 여기는 피하세요
```

편집 후 다시 런치하면 됩니다. 재빌드는 필요 없습니다(`--symlink-install`).

---

## 7. 로봇팔 바꾸기

[`src/robo_pinky_sim/config/arms.yaml`](../src/robo_pinky_sim/config/arms.yaml)을
편집합니다.

```yaml
arms:
  - id: OMX-C                    # 관제에 표시되는 장비 ID
    model: OMX-LOADER
    gz_name: omx_c               # Gazebo 모델명 겸 토픽 네임스페이스
    station: LOAD-C              # 관제 적재 스테이션 ID (layout.dart와 일치)
    zone: chilled
    body_color: "0.80 0.90 0.96 1.0"
    mount_x: 68.3                # 받침대 설치 위치(관제 좌표 unit)
    mount_y: 35.2
    mount_heading: 1.5708        # 스테이션을 바라보는 방향
```

### 받침대 위치를 옮길 때

**받침대는 관제가 모르는 실물 장애물입니다.** 아무 데나 세우면 지나가던 로봇이
막혀 버립니다. 세 조건을 모두 지켜야 합니다.

| 조건 | 이유 |
|---|---|
| 세로 통로 x(5·20·35·50·65·80·95·110)에서 **3 unit 이상** | 통과 교통을 막지 않는다 |
| 랙 로케이션 x(9.5 + 5.6·c)에서 **2.5 unit 이상** | 랙 진입선을 막지 않는다 |
| 스테이션에서 **2.8 unit(0.28 m) 이내** | 팔 사거리 안에 로봇이 들어온다 |

기본값은 이웃한 랙 열 두 개의 정중앙입니다. 스테이션 좌표 자체를 옮기려면
`robo_control/lib/core/layout.dart`의 `LOAD-*` 스테이션과
`generate_world.py`의 `STATIONS`도 같은 값으로 고쳐야 합니다.

### 팔을 아예 쓰지 않으려면

```bash
ros2 launch robo_pinky_sim warehouse.launch.py arms:=none
```

관제는 적재 스텝을 **시간 기반으로 자동 진행**하므로 운영은 그대로 돌아갑니다.

---

## 8. 평면도 바꾸기

관제센터 평면도(`robo_control/lib/core/layout.dart`)를 바꿨다면, 월드도 다시
생성해야 물리 월드와 통로 그래프가 일치합니다.

1. [`generate_world.py`](../src/robo_pinky_sim/scripts/generate_world.py) 상단의
   상수를 `layout.dart`와 맞춥니다 — `CORRIDOR_X` `CORRIDOR_Y` `RACK_ROW_Y`
   `ZONE_BOUNDS` `STATIONS`
2. 생성

```bash
cd robo_pinky
python3 src/robo_pinky_sim/scripts/generate_world.py \
        src/robo_pinky_sim/worlds/warehouse_3temp.sdf
```

```
… 생성 완료 — 랙 32개, 스테이션 14개, 창고 12.0m × 7.2m
```

3. 다시 런치

세로 통로가 지나는 자리는 자동으로 랙에서 비워집니다(`AISLE_HALF_GAP`).

---

## 9. 문제 해결

### 로봇이 관제에 접속하지 않는다

`link_status`가 계속 `단절`이면:

```bash
# 관제센터가 포트를 열었는지
ss -tlnp | grep 8788

# 에이전트 로그
ros2 topic echo /pinky_01/link_status
```

| 증상 | 원인·조치 |
|---|---|
| 관제센터에 `게이트웨이 닫힘` | 8788 포트를 다른 프로그램이 쓰는 중. 그 프로그램을 종료하거나 `control_port`를 양쪽에서 바꾸세요 |
| 포트는 열려 있는데 접속 안 됨 | `control_host` 확인. 다른 PC면 방화벽도 확인 |
| 접속 직후 끊김 반복 | 관제센터가 죽었을 가능성. 관제 터미널 로그 확인 |

### 로봇이 제자리에서 안 움직인다

순서대로 확인하세요.

1. **`link_status` 끝 문구** — 정지 사유가 그대로 적혀 있습니다
   - `관제 링크 단절` → 위 항목
   - `비상정지 …` → 관제센터에서 비상정지 해제
   - `작업자 위급 …` / `구역 전원 차단` → 관제 [안전 관리]에서 상황 해제
   - `충전 중` → 정상. 95 %까지 기다립니다
   - `라이다 전방 … 장애물` → 앞을 막고 있는 물체 제거
2. **`잔여 WP 0`** — 관제가 아직 경로를 주지 않은 상태입니다. 관제센터에서
   그 로봇이 `예비 대기`인지 확인하세요
3. **관제센터 🗼 아이콘이 회색** — 링크 대기 중. 배차 대상이 아닙니다

### 로봇이 랙에 끼었다

스폰 좌표가 랙 안이거나, 통로에 놓인 장애물에 밀렸을 때 생깁니다.

- Gazebo GUI에서 모델을 선택해 통로로 옮깁니다
- 또는 런치를 다시 올립니다(`Ctrl+C` → `./run.sh`)

오도메트리는 스폰 지점 기준이므로, GUI에서 모델을 옮기면 관제가 보는 위치와
어긋납니다. 옮긴 뒤에는 런치를 다시 올리는 편이 안전합니다.

### Gazebo가 무겁다 / 화면이 끊긴다

```bash
ros2 launch robo_pinky_sim warehouse.launch.py gui:=false
```

헤드리스로 돌리고 관제센터 [실시간 맵]으로 관찰하세요. 그래도 무거우면
`fleet.yaml`에서 로봇 수를 줄입니다. 카메라(`camera:=true`)는 가장 무거운
옵션이므로 필요할 때만 켜세요.

### 관제센터 창이 갑자기 닫힌다

통합 GPU에서 Gazebo 렌더러와 GL 자원을 다투는 경우입니다.

1. `camera:=false`(기본값)인지 확인
2. `gui:=false`로 Gazebo GUI를 끄고 실행
3. 다른 GPU 사용 응용을 종료

### 종료했는데 프로세스가 남는다

런치가 비정상 종료되면 `gz sim`·`parameter_bridge`가 남아 CPU를 계속 씁니다.

```bash
ps -eo pid,pcpu,comm --sort=-pcpu | head
kill $(pgrep -f "gz sim" | tr '\n' ' ')
kill $(pgrep -f parameter_bridge | tr '\n' ' ')
kill $(pgrep -f pinky_agent | tr '\n' ' ')
```

### 빌드가 실패한다

```bash
cd robo_pinky
rm -rf build install log
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
```

`robo_pinky_agent`의 `UserWarning: Unbuilt egg for pytest-repeat`는 시스템
setuptools가 내는 경고이며 빌드 결과에는 영향이 없습니다.
