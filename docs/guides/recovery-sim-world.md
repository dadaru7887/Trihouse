# 복구(VLM+RL) 시뮬레이션 월드 만들기 — new_map_2 를 Gazebo 로

이 문서는 실물에서 만든 SLAM 지도(`new_map_2`)로 Gazebo 월드를 만들어 Pinky 를
띄우고, 그 월드가 지도와 같은 자리에 있는지 검사하는 순서를 적는다. 복구 학습
데이터(버퍼)를 시뮬레이션에서 모으기 위한 첫 단계다.

환경: Ubuntu 24.04, ROS 2 Jazzy, Gazebo Harmonic, `pinky_pro` 워크스페이스 빌드 완료.
1단계(월드 파일 생성)는 Python 만 있으면 어느 PC 에서도 된다. Pillow 와 PyYAML 이
필요하다 (Ubuntu: `sudo apt install python3-pil python3-yaml`).

## 원리: 지도 한 장이 어떻게 벽이 되나

SLAM 지도는 **그림 한 장 + 설명서(yaml)** 다.

```yaml
# pinky_pro_alpha/pinky_navigation/map/new_map_2.yaml
image: new_map_2.pgm        # 73 x 89 픽셀 (확장자만 pgm, 내용은 PNG)
resolution: 0.030           # 픽셀 한 칸 = 3 cm
origin: [-0.220, -1.473, 0] # 그림 왼쪽 아래 모서리의 map 좌표 (m)
occupied_thresh: 0.65       # 이보다 어두우면 벽
```

| 픽셀 색 | 뜻 | 월드에서 |
|---|---|---|
| 검정 (0) | 점유 = 벽 | 3 cm × 3 cm × 높이 0.30 m 상자 |
| 흰색 (254) | 비어 있음 | 바닥 |
| 회색 (205) | 미확인 (방 밖) | 아무것도 없음. 벽으로 세우면 없는 벽이 생긴다 |

1. 검정 픽셀마다 상자를 하나씩 세우면 764 개가 된다. 이웃한 픽셀을 직사각형으로
   뭉쳐 95 개로 줄인다. 상자가 적어야 물리 계산이 가볍다.
2. 상자 위치 = `origin + (열, 행) × resolution` 이다. 그림의 행은 위에서부터
   세므로 y 는 뒤집는다.
3. 벽 모델을 pose 0 에 두므로 **Gazebo 의 world 좌표 = 지도의 map 좌표** 다. 실측
   waypoint (예: `charging_station_01` = (0.057, 0.195)) 를 Gazebo 에 그대로 쓰면 된다.
4. 벽 높이 0.30 m 는 라이다 평면 높이 0.125 m 보다 높아야 해서 정한 값이다. 낮으면
   라이다 빔이 벽을 지나가 버린다.

벽을 손으로 그리지 않고 Nav2 가 쓰는 것과 **같은 yaml** 에서 만드는 이유:
지도(Nav2), 물리(Gazebo), 원장(DB)이 서로 다른 벽을 가지면, 로봇이 "도착했다"고 하는
자리와 실제로 선 자리가 어긋난다.

## 관련 파일

| 파일 | 역할 |
|---|---|
| `scripts/recovery_sim/build_world.py` | 이 문서의 1단계. 월드 두 벌 + 미리보기 + 보고서 |
| `control_tower/bringup/p0_runtime_assets.py` | 벽 세우는 함수 `build_world_with_walls` (bringup 과 공용) |
| `control_tower/bringup/p0_world.sdf` | 원본 월드: 바닥면과 물리 설정. 읽기만 한다 |
| `scripts/p0_check_world_alignment.py` | 4단계. 라이다로 월드와 지도의 정합을 잰다 |
| `tests/test_recovery_sim_world.py` | 벽 = 지도, 조명 1 개, 원본 불변을 검사 |

## 1단계 — 월드 파일 만들기

```bash
cd ~/Trihouse                       # 저장소 루트
python3 scripts/recovery_sim/build_world.py
```

출력 예 (2026-11-14, new_map_2):

```
지도 new_map_2.yaml: 2.19 m x 2.67 m, 셀 0.03 m
벽: 점유 셀 764 개 -> 상자 95 개, 높이 0.3 m
지도와 일치: 예 (벽 빠진 셀 0, 지도에 없는 벽 0)
  charging_station_01   (+0.057, +0.195)  not_wall  벽까지 0.177 m
  ...
```

만들어지는 파일 (`.trihouse/recovery_sim/`, git 에 올라가지 않음):

| 파일 | 언제 쓰나 |
|---|---|
| `world.sdf` | 벽 + 조명. 2·3·4단계처럼 **혼자** 띄울 때 |
| `world_base.sdf` | 조명만. 5단계 전체 스택에 줄 때 (bringup 이 벽을 직접 세우므로 두 겹 방지) |
| `preview.png` | 위에서 본 그림. 빨간 테두리 = 생성된 벽 상자, 초록 점 = waypoint, 빨강/초록 축 = 원점의 +x/+y |
| `report.json` | 위 숫자 전부 |

확인할 것:
- "지도와 일치: 예" 가 나와야 한다. 아니면 종료 코드 1 로 끝난다.
- `preview.png` 에서 빨간 상자가 검정 픽셀을 정확히 덮고, 초록 점이 모두 흰 바닥 위에
  있어야 한다.

조명을 넣는 이유: 원본 `p0_world.sdf` 에는 `<light>` 가 없다. 그러면 카메라 화면이
기본 주변광만 받는다. VLM 과 검출기가 볼 화면이라 위에서 비스듬히 비추는 빛 하나와
주변광 0.5 를 넣는다.

다른 지도를 쓰려면 `--map <지도.yaml>`, 출력 위치를 바꾸려면 `--out <폴더>` 를 준다.

## 2단계 — 월드만 띄워 보기 (로봇 없음)

```bash
source /opt/ros/jazzy/setup.bash
gz sim -r .trihouse/recovery_sim/world.sdf
```

회색 벽이 `preview.png` 와 같은 모양이면 된다. 마우스 휠로 확대, 드래그로 회전한다.

## 3단계 — Pinky 한 대 띄우기

터미널 1:

```bash
source /opt/ros/jazzy/setup.bash
source pinky_pro/install/setup.bash
ros2 launch pinky_gz_sim launch_sim.launch.xml \
    world:=$PWD/.trihouse/recovery_sim/world.sdf
```

로봇은 (0, 0), yaw 0 에 생긴다. `preview.png` 의 축 원점이고, `charging_station_02`
바로 옆 빈 바닥이다. namespace 는 없다. 토픽은 `/scan` 처럼 앞에 이름이 붙지 않는다.

터미널 2 (센서 확인):

```bash
source /opt/ros/jazzy/setup.bash
ros2 topic hz /scan                 # 라이다 약 10 Hz
ros2 topic hz /camera/image_raw     # 카메라 30 Hz 설정 (PC 성능에 따라 낮을 수 있음)
ros2 run rqt_image_view rqt_image_view /camera/image_raw   # 화면 보기
ros2 run teleop_twist_keyboard teleop_twist_keyboard        # 키보드로 움직이기
```

| 센서 | 토픽 | 사양 (`pinky_gz.urdf.xacro`) | 복구에서 쓰는 곳 |
|---|---|---|---|
| 라이다 | `/scan` | 10 Hz, 640 빔 | 주행(Nav2·AMCL), 보상의 벽 여유 거리 |
| 카메라 | `/camera/image_raw` | 1280×720, 수평 화각 66°, 30 Hz, 0.1 m 보다 가까우면 안 보임 | VLM 입력, 위험 객체 박스 |
| 오도메트리 | `/odom`, `/tf` | 30 Hz | 로봇 위치 |
| IMU | `imu_raw` | 100 Hz | 주행 |

## 4단계 — 월드가 지도와 같은 자리에 있는지 재기

로봇이 원점에서 생겼으므로 지금은 `odom` 좌표 = `map` 좌표다. AMCL 없이 바로 잴 수 있다.

```bash
source /opt/ros/jazzy/setup.bash
python3 scripts/p0_check_world_alignment.py --robot "" --fixed-frame odom \
    --map pinky_pro_alpha/pinky_navigation/map/new_map_2.yaml
```

무엇을 재나: 로봇 자세에서 지도 그림 위로 광선을 쏴서 "벽까지 이만큼이어야 한다"는
거리를 계산한다. 이 값을 시뮬레이터 라이다가 실제로 잰 거리와 빔마다 비교한다.

| 결과 | 종료 코드 | 뜻 |
|---|---|---|
| 5 cm 안에 든 빔 90 % 이상 | 0 | 정합됨 |
| 60–90 % | 2 | 평행이동이 남았다 |
| 60 % 미만 | 2 | 회전이나 축척부터 의심 |
| 견줄 빔 없음 | 1 | 시뮬레이터, `/scan`, TF 를 확인 |

teleop 으로 **서로 다른 세 자리**로 옮겨 가며 반복한다. 한 자리에서 맞는 것은 우연일
수 있다. 오래 몰면 바퀴 오도메트리가 조금씩 밀리므로, 짧게 움직이고 잰다.

## 5단계 — 전체 스택(Nav2·AMCL·관제)에서 쓰기

실제 복구 수집은 Nav2 가 막혀야 시작되므로 결국 전체 스택 위에서 돈다. 이때는
`world.sdf` 가 아니라 **`world_base.sdf`** 를 준다. bringup 이 같은 지도로 벽을 직접
세우기 때문이다 (`p0_runtime_assets.py`).

```bash
# 평소 P0 순서 (scripts/p0_reset.sh -> scripts/p0_up.sh) 에서 월드만 바꾼다
PINKY_WORLD=$PWD/.trihouse/recovery_sim/world_base.sdf scripts/p0_up.sh

# AMCL 이 map 을 내보내므로 기본값 그대로 잰다 (pinky_01, map 프레임)
python3 scripts/p0_check_world_alignment.py
```

## 자주 겪는 문제

| 증상 | 원인 |
|---|---|
| 라이다가 벽을 못 본다 | 벽이 라이다 평면(0.125 m)보다 낮다. `WALL_HEIGHT_M` 확인 |
| 벽이 엉뚱한 모양 | 지도 그림을 확장자로 읽었다. `new_map_2.pgm` 은 내용이 PNG 다 (코드는 내용으로 판별함) |
| 벽이 두 겹 | 전체 스택에 `world.sdf` 를 줬다. `world_base.sdf` 를 준다 |
| 카메라 화면이 어둡다 | 원본 월드를 그대로 썼다. 1단계 출력 월드를 쓴다 |
| 시뮬레이션이 느리다 (real time factor 낮음) | 카메라 렌더링 부하. `gz sim` 창 오른쪽 아래 RTF 를 본다 |

## 다음 단계 (아직 하지 않음)

이 월드에는 아직 **막힘을 만드는 물체**가 없다. 복구 수집에는 다음이 더 필요하다.

1. 시나리오 생성: 장애물·사람 모델을 시드로 재현 가능하게 경로 위에 배치한다.
   각 모델에 Gazebo `Label` 시스템으로 번호를 붙인다.
2. 정답 박스: 로봇에 bounding box camera 를 달아, 라벨 붙은 물체의 2D 박스를 받는다.
3. 검출 오류 모델: 정답 박스에 YOLOE 의 **valid** 성능만큼 미검출·오검출·위치 흔들림을
   섞는다. test 성능으로 맞추면 test 를 다시 여는 셈이다.
4. 전이 metadata 에 `domain: sim` 과 시나리오 시드를 기록한다.
