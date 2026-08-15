# project1-ver2 · Nav2 지도

`rmf_control_ui` 가 **도면에서 만들었습니다.** 손으로 고쳐도 다음 내보내기 때
덮어써집니다.

## 무엇에 쓰나

RMF 는 nav graph 만으로 길을 찾으므로 이 지도가 필요 없습니다. 이 지도가 필요한
것은 **로봇 쪽**입니다 — AMCL 이 라이다로 제 위치를 잡고 Nav2 가 장애물을 피할 때
씁니다.

## 왜 SLAM 을 안 돌렸나

시뮬레이터에서는 돌 이유가 없습니다. 정확한 도면이 이미 있고, 그 도면이 Gazebo
월드를 만든 바로 그 원본이기 때문입니다. 도면에서 바로 만들면

- **원점이 RMF 월드에 계산으로 정확히 맞습니다.** 맞추는 작업 자체가 없습니다
- 표류가 없습니다
- 맵을 고치면 다시 만들어집니다

벽은 RMF 가 쓰는 두께 **0.1m** 로 그렸습니다(`building_map/wall.py` 의
`wall_thickness`). 그래서 Gazebo 에서 라이다가 보는 벽과 이 지도의 벽이 같습니다.
다르면 AMCL 이 못 붙습니다.

## 이 지도

| | |
|---|---|
| 크기 | 800 × 615 칸 |
| 한 칸 | 0.0059941919419155675 m |
| 덮는 범위 | x -1.239 ~ 3.557 m · y -3.241 ~ 0.445 m |
| 원점 | -1.238644, -3.241447 |
| 바닥 | 123586 칸 |
| 벽 | 34474 칸 |
| 모름 | 333940 칸 |

좌표는 **RMF 월드**입니다 — 원점은 도면 그림의 왼쪽 위, y 는 위로 갈수록 커져서
건물 안은 음수입니다. 자세한 것은 `rmf_control_ui/docs/COORDINATE_FRAMES.md`.

## 보기

```bash
# 그림으로 바로 보기
eog project1-ver2.pgm

# map_server 로 띄워서 RViz 에서 보기
ros2 run nav2_map_server map_server --ros-args \
  -p yaml_filename:=$PWD/project1-ver2.yaml
ros2 lifecycle set /map_server configure
ros2 lifecycle set /map_server activate
```

## 실물 건물에서 SLAM 으로 뜬 지도와 비교하기

진짜 핑키로 넘어가면 건물을 SLAM 으로 떠서 여기에 나란히 둡니다.

```bash
# 1. SLAM 으로 뜬다
ros2 launch pinky_navigation map_building.launch.xml

# 2. 이 디렉터리에 다른 이름으로 저장한다
ros2 run nav2_map_server map_saver_cli -f project1-ver2_slam
```

그 다음 **원점을 맞춰야 합니다.** SLAM 지도의 원점은 로봇이 SLAM 을 시작한
자리이고, RMF 의 원점은 도면 그림의 왼쪽 위입니다. `project1-ver2_slam.yaml` 의
`origin:` 세 숫자를 고쳐서 이 파일(`project1-ver2.yaml`)과 같은 자리를 가리키게
합니다.

맞았는지는 두 그림을 겹쳐 보면 압니다. 벽이 어긋나면 아직 안 맞은 것입니다.
