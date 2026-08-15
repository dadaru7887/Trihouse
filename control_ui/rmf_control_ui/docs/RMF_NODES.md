# Roles of RMF Control Nodes (관제 노드별 하는 일)

## 1. 이 문서가 답하는 것

`백엔드 띄우기`를 누르면 ROS 노드 여럿이 한꺼번에 올라옵니다. 어느 것이 무엇을
맡는지, 무엇이 안 뜨면 무엇이 안 되는지 정리합니다.

여기 적힌 노드 목록은 **이 프로젝트의 launch 를 실제로 띄워 `ros2 node list` 로
받아 적은 것**입니다. 문서를 위해 지어낸 이름이 아닙니다.

관련 문서: [Pinky 가상 로봇 · Fleet Adapter 연동](PINKY_FLEET_INTEGRATION.md) ·
[로봇 등록과 디렉터리 구조](ROBOT_REGISTRATION.md) ·
[한 월드에 로봇 여러 대](MULTI_ROBOT_NAMESPACES.md) ·
[값이 오는 곳 셋](THREE_SOURCES.md) · [좌표계](COORDINATE_FRAMES.md) ·
[Nav2 길](NAV2_PATH.md) · [시뮬레이션 시간 (RTF)](SIMULATION_TIME.md)

## 2. 무엇이 무엇을 띄우나

```
run_<맵이름>.sh
├── <맵이름>_bringup.launch.xml        Gazebo · 로봇 · 토픽 다리
└── <맵이름>.launch.xml                (12초 뒤)
    ├── rmf_demos/common.launch.xml    ← RMF core. 6개 노드 + 시각화
    └── rmf_demos_fleet_adapter/…      ← 이 프로젝트의 플릿. 2개 노드
```

**core 가 먼저 떠야 fleet adapter 가 붙습니다.** 순서가 뒤집히면 fleet adapter 가
schedule node 를 못 찾고 조용히 멈춰 있습니다.

## 3. 실제로 뜨는 노드

`gwanghee` 프로젝트로 띄워 받아 적은 목록입니다.

| 노드 | 묶음 | 하는 일 |
|---|---|---|
| `rmf_traffic_schedule_primary` | core | **모든 로봇의 예정 경로를 한자리에 모아 충돌을 막음** |
| `rmf_traffic_blockade_node` | core | 좁은 길에서 서로 마주 보고 멈춘 것을 풀어 줌 |
| `building_map_server` | core | `building.yaml` 을 읽어 맵을 뿌림 |
| `rmf_dispatcher_node` | core | 작업을 어느 로봇에 줄지 **입찰**로 정함 |
| `door_supervisor` | core | 자동문 요청을 한 곳으로 모아 중재 |
| `rmf_lift_supervisor` | core | 승강기 요청을 중재 |
| `schedule_data_node` | 시각화 | 경로 데이터를 시각화용으로 풀어 줌 |
| `schedule_visualizer_node` | 시각화 | RViz 에 경로를 그림 |
| `fleet_states_visualizer` | 시각화 | 로봇 상태를 그림 |
| `navgraph_visualizer` | 시각화 | 주행 그래프를 그림 |
| `floorplan_visualizer` | 시각화 | 도면을 그림 |
| `building_systems_visualizer` | 시각화 | 문·승강기를 그림 |
| `rmf_obstacle_visualizer` | 시각화 | 장애물을 그림 |
| `<플릿이름>_fleet_adapter` | 플릿 | 이 프로젝트의 로봇을 RMF 에 이어 줌 |
| `<플릿이름>_fleet_manager` | 플릿 | 로봇과 직접 주고받는 REST 층 |

시각화 노드 7개는 `headless:=true` 로 띄워도 함께 올라옵니다. RViz 창만 뜨지
않을 뿐입니다.

## 4. core 노드 하나씩

### 4.1 `rmf_traffic_schedule_primary` — 교통 일정

**RMF 의 심장입니다.** 모든 로봇이 "나는 이 시각에 이 길을 지나겠다"고 제출한
예정 경로(itinerary)를 한자리에 모아 둡니다. 새 경로가 기존 것과 겹치면 그
사실을 알려 로봇이 다른 길이나 다른 시각을 고르게 합니다.

받는 것:

```
/rmf_traffic/itinerary_set        경로를 새로 낸다
/rmf_traffic/itinerary_extend     가던 길을 늘린다
/rmf_traffic/itinerary_delay      늦어진다고 알린다
/rmf_traffic/itinerary_reached    어디까지 갔는지 알린다
/rmf_traffic/itinerary_clear      경로를 거둔다
```

여는 서비스:

```
/rmf_traffic/register_participant   로봇 한 대를 교통 참가자로 등록
/rmf_traffic/register_query         관심 있는 구역의 변화만 받아 보기
/rmf_traffic/request_changes        놓친 변화를 다시 달라고 요청
```

**이것이 없으면 fleet adapter 가 아예 시작하지 못합니다.** 로봇을 참가자로
등록할 곳이 없기 때문입니다. 그래서 `common.launch.xml` 이 먼저 떠야 합니다.

이름 끝의 `_primary` 는 이중화 구성에서 주 노드를 뜻합니다. 예비 노드를 함께
띄우면 주 노드가 죽었을 때 이어받습니다. 지금은 주 노드만 띄웁니다.

### 4.2 `rmf_traffic_blockade_node` — 교착 중재

일정은 "언제 어디를 지날지"를 다루지만, 실제로는 **한 칸 통로에서 두 로봇이
마주 보고 둘 다 멈추는** 일이 생깁니다. 서로 상대가 비켜 주기를 기다리며 영원히
멈춰 있는 상태입니다.

이 노드가 그 구간의 통행권을 한 대에게 몰아 줘서 교착을 풉니다.

```
/rmf_traffic/blockade_set        이 구간을 쓰겠다
/rmf_traffic/blockade_ready      들어갈 준비가 됐다
/rmf_traffic/blockade_reached    어디까지 갔다
/rmf_traffic/blockade_release    다 썼다, 놓아준다
/rmf_traffic/blockade_cancel     안 가기로 했다
```

로봇이 한 대면 할 일이 없습니다. 좁은 통로에 여러 대가 다닐 때 의미가 있습니다.

### 4.3 `building_map_server` — 건물 맵

`building.yaml` 을 읽어 벽·바닥·Waypoint·Lane 을 ROS 로 뿌립니다. 이 프로젝트는
`rmf_maps/<맵이름>/<맵이름>.building.yaml` 을 가리킵니다.

```
/map              BuildingMap 을 계속 발행
/get_building_map 맵을 한 번에 달라는 서비스
```

**시각화와 rmf-web 이 이것을 봅니다.** 안 뜨면 화면에 도면이 안 나옵니다. 로봇
주행 자체는 fleet adapter 가 `nav_graphs/0.yaml` 을 직접 읽으므로 계속 됩니다.

### 4.4 `rmf_dispatcher_node` — 작업 배차

작업이 들어오면 **어느 로봇이 맡을지 입찰로 정합니다.** 각 플릿에 "이 일 할 수
있나, 얼마나 걸리나"를 물어 답을 모으고, 가장 나은 곳에 맡깁니다.

```
/task_api_requests    작업 요청이 들어오는 곳 (rmf-web 이 여기로 넣는다)
/rmf_task/bid_response  플릿들이 낸 응찰
/rmf_task/dispatch_ack  맡겠다는 확인
/dispatch_states        지금 어느 작업이 어디에 있는지
```

서비스: `/submit_task` `/cancel_task` `/get_dispatches`

입찰에 주는 시간은 기본 **2초**입니다(`bidding_time_window`). 짧으면 느린 플릿이
응찰을 못 하고, 길면 작업 시작이 늦어집니다.

**이것이 없으면 작업을 넣어도 아무 로봇도 움직이지 않습니다.**

### 4.5 `door_supervisor` — 자동문 중재

여러 로봇이 같은 문을 두고 "열어라 / 닫아라"를 동시에 보내면 문이 열리다 닫히다
합니다. 이 노드가 요청을 한 곳으로 모아 **아직 지나가는 로봇이 있으면 닫지
않도록** 합니다.

```
/adapter_door_requests  로봇들이 보내는 요청
       ↓ (중재)
/door_requests          문에 실제로 나가는 명령
/door_states            문의 현재 상태
```

이 맵에 자동문이 없으면 할 일이 없습니다. 그래도 떠 있는 것이 정상입니다.

### 4.6 `rmf_lift_supervisor` — 승강기 중재

문과 같은 얼개입니다. 여러 로봇이 같은 승강기를 부를 때 층을 중재합니다.

```
/adapter_lift_requests → /lift_requests
/lift_states
/fire_alarm_trigger     화재 경보. 승강기를 전부 놓아준다
```

단층 창고에서는 할 일이 없습니다.

## 5. 플릿 노드

### 5.1 `<플릿이름>_fleet_adapter`

**RMF 와 우리 로봇 사이의 통역입니다.** 프로젝트마다 하나씩 뜹니다.

읽는 것:

| 파일 | 무엇 |
|---|---|
| `<플릿이름>_config.yaml` | 로봇 목록, 속도·회전 한계, 프로필 반경, 배터리 |
| `nav_graphs/0.yaml` | 어느 Waypoint 가 어느 Lane 으로 이어지는지 |

하는 일:

- 등록된 로봇을 교통 일정에 **참가자로 등록**
- 배차 요청에 **응찰** — 이 로봇이 그 일을 얼마 만에 할 수 있는지 계산
- 맡은 작업을 Waypoint 순서로 풀어 로봇에 전달
- 로봇 위치를 받아 교통 일정에 계속 갱신

**등록에서 출처가 `앱 Mock` 인 로봇은 여기 들어가지 않습니다.** 앱이 제 안에서
굴리는 것이라 실제로는 없기 때문입니다. 넣으면 오지 않을 로봇의 상태를 계속
기다립니다.

`-sim` 인자를 주면 시뮬레이션 시간(`/clock`)을 씁니다. 이 프로젝트는 Gazebo 와
함께 띄우므로 그렇게 갑니다.

### 5.2 `<플릿이름>_fleet_manager`

fleet adapter 가 로봇과 직접 주고받는 층입니다. REST 로 열려 있고, 주소는 등록
설정의 `fleet_manager` 에서 옵니다.

```yaml
fleet_manager:
  ip: "127.0.0.1"
  port: 22011
```

Gazebo 로 돌릴 때는 시뮬레이터의 토픽을 이 REST 뒤에 붙입니다. 실물을 쓸 때는
로봇 제조사의 API 를 여기에 맞춰 넣습니다.

## 6. 시각화 노드

7개가 함께 뜹니다. RViz 에 그리는 일만 합니다.

| 노드 | 그리는 것 |
|---|---|
| `schedule_data_node` | 경로 데이터를 시각화용으로 풀어 줌 (그리지는 않음) |
| `schedule_visualizer_node` | 로봇들의 예정 경로 |
| `fleet_states_visualizer` | 로봇 위치·상태 |
| `navgraph_visualizer` | Waypoint 와 Lane |
| `floorplan_visualizer` | 도면 이미지 |
| `building_systems_visualizer` | 문·승강기 |
| `rmf_obstacle_visualizer` | 감지된 장애물 |

**`headless:=true` 로 띄워도 이 노드들은 올라옵니다.** RViz 창만 안 뜹니다.
관제를 앱에서 보므로 창은 필요 없지만, 노드가 도는 비용은 그대로 듭니다.

### 시각화 노드는 스스로 아는 것이 없습니다

이 7개는 **받아서 그리기만** 합니다. 먹이를 주는 것은 fleet adapter 입니다.

| 그리는 것 | 그리는 노드 | 먹이 토픽 | 그 토픽을 내는 것 |
|---|---|---|---|
| 경로 (Lane·Waypoint) | `navgraph_visualizer` | `/nav_graphs` | fleet adapter |
| 로봇 | `fleet_states_visualizer` | `/fleet_states` | fleet adapter |
| 도면 | `floorplan_visualizer` | `/floorplan` | `building_map_server` |

RMF 안에서 `/nav_graphs` 와 `/fleet_states` 를 내는 것은 fleet adapter
(`FleetUpdateHandle`) **하나뿐**입니다. 그래서 어댑터가 죽으면 RViz 는 도면만
남고 **경로와 로봇이 통째로 사라집니다.** 시각화 노드는 멀쩡히 떠 있고 오류도
안 납니다 — 줄 것이 없어서 안 그릴 뿐입니다.

확인은 발행자 수로 합니다. 0 이면 어댑터가 죽은 것입니다.

```bash
ros2 topic info /nav_graphs      # Publisher count: 1 이라야 합니다
ros2 topic info /fleet_states
```

어댑터는 Nav2 20여 개 노드와 같이 뜨는 중에 `add_easy_fleet` 안에서
SIGSEGV(-11) 로 죽은 적이 있습니다. 그 부하의 뿌리는 시뮬레이션이 느린 것이라
[SIMULATION_TIME.md](SIMULATION_TIME.md) 도 함께 보세요 — RTF 가 낮으면
`map_server` 가 lifecycle 응답 시간 초과로 `inactive` 에 멈춰, 어댑터가 멀쩡해도
로봇이 RMF 에 안 붙습니다. 한가할 때 같은 명령을 손으로 돌리면 멀쩡히
뜹니다. 부하가 걸린 순간에만 나는 rmf_adapter 쪽 경합이라 고칠 수 없어서,
`<맵>_nav2.launch.xml` 에서 `respawn="true"` (5초 간격, 최대 5회)로 다시
띄웁니다.

## 7. 무엇이 없으면 무엇이 안 되나

| 안 뜬 노드 | 겉으로 보이는 증상 |
|---|---|
| `rmf_traffic_schedule_primary` | fleet adapter 가 시작하다 멈춤. 로봇이 아예 안 움직임 |
| `rmf_dispatcher_node` | 작업을 넣어도 아무 로봇도 맡지 않음 |
| `building_map_server` | 화면에 도면이 안 나옴. 주행은 됨 |
| `<플릿>_fleet_adapter` | 로봇이 RMF 에 안 보임. 배차 대상에서 빠짐 |
| `<플릿>_fleet_manager` | fleet adapter 가 로봇에 명령을 못 보냄 |
| `rmf_traffic_blockade_node` | 좁은 통로에서 두 대가 마주 보고 영영 멈춤 |
| `door_supervisor` · `lift_supervisor` | 문·승강기가 있는 맵에서만 문제 |
| 시각화 노드들 | RViz 만 비어 있음. 관제는 정상 |

## 8. 확인하는 법

```bash
source /opt/ros/jazzy/setup.bash
source ~/robosapiens/rmf_ws/install/setup.bash

# 무엇이 떠 있나
ros2 node list

# 이 노드가 무엇을 주고받나
ros2 node info /rmf_traffic_schedule_primary

# 교통 일정에 로봇이 등록됐나
ros2 service call /rmf_traffic/request_changes \
  rmf_traffic_msgs/srv/RequestChanges "{query_id: 0}"

# 배차가 도는가
ros2 topic echo /dispatch_states --once

# 맵이 나가는가
ros2 topic echo /map --once --field name
```

앱에서는 **로봇 메뉴의 `Open-RMF 백엔드` 카드**가 같은 것을 봅니다. `다시 확인`
을 누르면 `ros2 node list` 를 다시 읽습니다.

## 9. 왜 노드가 이렇게 많은가

한 덩어리로 만들면 하나가 죽을 때 전부 죽습니다. RMF 는 **관심사마다 노드를
나눠** 두었습니다.

- 교통(일정·교착)은 로봇 종류와 무관합니다 → 플릿이 몇이든 하나면 됩니다
- 배차는 플릿을 몰라도 됩니다 → 입찰로 물어보면 되니까
- 로봇의 사정은 플릿마다 다릅니다 → fleet adapter 를 플릿마다 따로 둡니다

그래서 **Pinky 플릿과 OMX 워크셀을 함께 쓰더라도 core 는 하나**이고, 플릿이
늘면 fleet adapter 만 늘어납니다.

---

## ROS2 확인 화면

왼쪽 메뉴 `ROS2 확인` 에서 지금 떠 있는 것을 직접 들여다볼 수 있습니다. 탭 넷은
각각 `ros2 <종류> list` 를 그대로 부릅니다.

| 탭 | 목록 | 눌렀을 때 |
|---|---|---|
| 노드 | `ros2 node list` | `ros2 node info` |
| 토픽 | `ros2 topic list -t` | `ros2 topic info --verbose` + **값 한 건 읽기** |
| 서비스 | `ros2 service list -t` | `ros2 service info` |
| 액션 | `ros2 action list -t` | `ros2 action info -t` |

**탭마다 목록만 보여 주고, 하나를 누르면 움직일 수 있는 팝업에 자세한 내용이
뜹니다.** 목록에 상세를 함께 늘어놓으면 서른 개가 넘는 노드에서 정작 찾는 것이
안 보입니다.

### 수신값

토픽 팝업의 `값 한 건 읽기` 는 `ros2 topic echo --once --timeout N` 입니다. 한 건만
받고 끊습니다. **목록에 있어도 발행자가 없는 토픽이 흔합니다** — 그때는 시간이
지나 "값이 오지 않았습니다" 로 알립니다. 실패한 것과 안 온 것을 갈라 보여 주므로,
값이 오는지가 원인을 짚는 첫 갈림길이 됩니다.

전체 토픽의 값을 한꺼번에 읽지는 않습니다. 발행자 없는 토픽마다 기다려 화면이
멎습니다.

### 조회 방식 — 데몬 / 직접 탐색

`ros2` 는 보통 백그라운드 데몬에 대신 물어봅니다. 그 데몬과 직접 탐색
(`--no-daemon`)의 결과가 **서로 다르게 나오는 일을 겪었습니다.** 그래서 화면에서
골라 견줄 수 있게 두었고, 직접 탐색일 때는 탐색 시간(`--spin-time`)도 고릅니다 —
짧으면 오히려 덜 보입니다.

> **`ros2 action` 은 `--no-daemon` 도 `--spin-time` 도 받지 않습니다.** 붙이면
> usage 오류로 죽습니다. 그래서 액션 탭에서는 그 선택을 감춥니다. 숨은 것 보기
> 옵션 이름도 종류마다 달라서(노드는 `-a`, 토픽·서비스는 `--include-hidden-…`,
> 액션은 없음) 각자 실제 이름을 씁니다.

돌린 명령은 `명령 복사` 로 가져가 터미널에서 그대로 재현할 수 있습니다.
