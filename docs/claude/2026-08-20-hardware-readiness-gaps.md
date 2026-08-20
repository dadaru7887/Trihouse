# 실물 출고 테스트 — 메워야 하는 공백과 결정 기록

작성: 2026-08-20 · 브랜치 `feat/pinky-edge-agent`
목표: **4060 서버에서 주문을 넣어 로봇이 출고 완주 3회.** 그 뒤 로봇 2대 · 주문 2건.
UI 는 쓰지 않는다. Open-RMF 는 그대로 쓴다.

실행 절차는 [p0-hardware-quick-run.md](../runbooks/p0-hardware-quick-run.md) 다.
**이 문서는 코드를 읽어 확인한 사실만 적는다.** 로봇 위에서 확인해야 하는 것은
"로봇에서 확인" 이라고 밝혔다.

---

## 0. 결정된 것 (2026-08-20 인터뷰)

| 항목 | 결정 |
|---|---|
| 로봇팔 | **이번엔 뺀다.** 실물 테스트를 돌리면서 팔을 붙여 통합 테스트로 간다 |
| 지도 | **`new_map_2`** (`control_ui/rmf_control_ui/data/rmf_maps/new_map_2.yaml`). 좌표 재측정은 필요하면 한다 |
| 대수 | **1대 완주 3회 → 그다음 2대.** 2대는 Open-RMF 기능으로 되는지 먼저 정리 |
| 안전 gate | 상황·현재 주행 경로·최적안을 정리해 보고 (→ §1) |

---

## 1. 안전 gate — 지금 코드는 실제로 어떻게 주행하는가

> 사용자 질문: *"어떤 상황이고, 현재 코드는 어떻게 주행하게 되어 있고 최적안은 어떤 것인지."*

### 1.1 설계가 말하는 것

`safety_supervisor` 는 스스로를 이렇게 선언한다.

```python
# trihouse_pinky_safety/safety_supervisor_node.py:51
"""The only operational publisher for the motor `/cmd_vel` topic."""
# :91-92   구독
self.create_subscription(Twist, 'cmd_vel_nav', ...)
self.create_subscription(Twist, 'cmd_vel_dock', ...)
# :101     발행
self.cmd_pub = self.create_publisher(Twist, 'cmd_vel', 10)
```

의도한 사슬은 하나다.

```
Nav2 ──cmd_vel_nav──▶ safety_supervisor ──cmd_vel──▶ 모터
                          │
                          └── 비상래치 · 사람감지 · 초음파근접 · 센서신선도
```

**`cmd_vel` 발행자가 1개이고 그것이 safety 일 때만** 이 gate 가 뜻을 갖는다.
하드웨어 스모크 문서 §1·§6.5 가 그것을 통과 조건으로 적어 두었다.

### 1.2 실기에서 실제로 벌어지는 일

벤더 Nav2 는 두 줄로 자기 출력을 정한다
([pinky_navigation/launch/navigation_launch.xml:85-86](../../pinky_pro/pinky_navigation/launch/navigation_launch.xml#L85-L86)).

```xml
<remap from="cmd_vel"          to="cmd_vel_nav"/>   <!-- velocity_smoother 의 입력 -->
<remap from="cmd_vel_smoothed" to="cmd_vel"/>       <!-- velocity_smoother 의 출력 = 모터 -->
```

그리고 우리 실기 launch 는 `SetRemap(src='cmd_vel', dst='cmd_vel_nav')` 를
**온보드 그룹 안**에 두었다([trihouse_pinky.launch.py:69](../../trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_pinky.launch.py#L69)).
그 그룹에 Nav2 는 없다 — Nav2 include 는 103행, 그룹 **바깥**이다.

그래서 remap 이 **Nav2 가 아니라 safety 에** 걸린다.

```
현재 (실기)

  controller_server ──cmd_vel(remap)──▶ cmd_vel_nav ─┐
                                                     ├─▶ velocity_smoother ──cmd_vel──▶ 모터
  safety_supervisor ──cmd_vel(remap)──▶ cmd_vel_nav ─┘          ▲
          ▲                                                     │
          └── 자기가 구독하는 토픽에 자기가 발행한다 (되먹임)      LiDAR 충돌감시 없음
```

**세 가지가 동시에 깨진다.**

| # | 무엇 | 왜 |
|---|---|---|
| 1 | **safety 의 STOP 이 로봇을 못 세운다** | `velocity_smoother` 의 입력에 발행자가 둘. safety 가 0 을 보내는 사이에도 `controller_server` 의 0 이 아닌 값이 계속 도착한다. 최신 메시지가 이기므로 로봇은 **끊기며 계속 간다** |
| 2 | **safety 가 자기 출력을 다시 읽는다** | 발행 `cmd_vel`→`cmd_vel_nav`, 구독도 `cmd_vel_nav`. gate 를 통과한 값이 다시 입력으로 들어온다 |
| 3 | **LiDAR 충돌 감시가 아예 없다** | 벤더 `lifecycle_nodes_nav` 는 6개뿐이고 `collision_monitor` 가 없다([bringup_launch.xml:15-20](../../pinky_pro/pinky_navigation/launch/bringup_launch.xml#L15-L20)). 시뮬에는 우리가 넣어 준다 |

**즉 실기에서 비상정지·사람감지·근접정지 중 어느 것도 주행을 멈추지 못한다.**

### 1.3 시뮬은 왜 굴러가는가 — 시뮬도 완전하지는 않다

시뮬은 `nav2_bringup` 을 쓰고, 그쪽은 `controller_server`·`behavior_server`·
`velocity_smoother`·`docking_server` 의 `cmd_vel` 만 `cmd_vel_nav` 로 remap 하고
**`collision_monitor` 에는 remap 을 걸지 않는다**
([navigation_launch.py:137,181,214](/opt/ros/jazzy/share/nav2_bringup/launch/navigation_launch.py)).
우리 파생 params 는 `collision_monitor` 의 출력을 `cmd_vel` 로 둔다
([p0_runtime_assets.py:97-98](../../control_tower/bringup/p0_runtime_assets.py#L97-L98)).

**2026-08-20 실측** — 도는 시뮬에서 직접 셌다.

```bash
ros2 topic info /pinky_01/cmd_vel --verbose
```
```text
Publisher count: 3
  collision_monitor            /pinky_01
  docking_server               /pinky_01
  trihouse_safety_supervisor   /pinky_01     ← gate
Subscription count: 1
  trihouse_bridge_pinky_01     /            ← gz bridge → 모터
```

```
시뮬 (실측)

  controller ──cmd_vel_nav──▶ velocity_smoother ──cmd_vel_smoothed──▶ collision_monitor ──┐
  trihouse_fleet(협로) ──────▶       (LiDAR 충돌감시 O)                                    │
                    │                                        docking_server ──────────────┤──cmd_vel──▶ gz bridge ─▶ 모터
                    └──────────────────────────▶ safety_supervisor ───────────────────────┘
```

**시뮬의 `cmd_vel` 발행자는 셋이다** — `collision_monitor` · `docking_server` ·
`safety_supervisor`. **그중 gate 는 하나뿐이다.** safety 가 STOP 으로 0 을 보내도
나머지 둘이 계속 자기 값을 내보내므로, **시뮬에서도 safety 는 로봇을 세우지 못한다.**
시뮬이 굴러간 이유는 세 발행자가 평소 같은 방향의 값을 내기 때문이다.

다만 시뮬에는 LiDAR 충돌 감시(`collision_monitor`)가 사슬 안에 있어 물리적 안전망이
하나 더 있다. **실기에는 그것조차 없다**(벤더 lifecycle 목록에 없다).

`cmd_vel_nav` 쪽도 함께 쟀다 — 발행자 7(controller_server 1 + behavior_server 5 +
**`trihouse_fleet`**), 구독자 2(`velocity_smoother`, `safety_supervisor`).
`trihouse_fleet` 이 협로 규칙 주행을 여기로 넣는 것이 설계대로 확인됐다.

### 1.4 최적안

**목표: `cmd_vel` 발행자를 safety 하나로 만들되, 가속 제한(velocity_smoother)은 유지한다.**
`pinky_pro` 는 보호 경로라 벤더 파일은 고치지 않는다.

```
목표 사슬 (실기)

  controller_server ──cmd_vel_nav──▶ velocity_smoother ──cmd_vel──▶ safety_supervisor ──cmd_vel_motor──▶ 모터 드라이버
  narrow_zone_pilot ──cmd_vel_nav──┘                                    (발행자 1)
```

**방법: 우리 launch 에서 두 자리만 고친다.**

| 자리 | 지금 | 바꿀 것 |
|---|---|---|
| 온보드 그룹의 `SetRemap` | `cmd_vel → cmd_vel_nav` (safety 에 잘못 걸림) | **제거** |
| `safety_supervisor` 노드 | 구독 `cmd_vel_nav`, 발행 `cmd_vel` | `remappings=[('cmd_vel_nav','cmd_vel'), ('cmd_vel','cmd_vel_motor')]` — smoother 출력을 받아 모터 토픽에 낸다 |
| 벤더 `bringup_robot` include | 모터 드라이버가 `cmd_vel` 구독 | 그 그룹에 `SetRemap('cmd_vel','cmd_vel_motor')` |

이렇게 하면 **`cmd_vel` 은 Nav2 → safety 구간의 내부 토픽**이 되고, 모터가 듣는
`cmd_vel_motor` 의 발행자는 safety 하나가 된다. 가속 제한도 그대로 지난다.
협로 규칙 주행(`narrow_zone_pilot` 이 `cmd_vel_nav` 로 발행)도 사슬 안에 남는다.

**대안 두 가지와 비교.**

| | 방법 | 판정 |
|---|---|---|
| B | 벤더 `velocity_smoother` 를 lifecycle 목록에서 빼고 safety 가 가속 제한까지 | 발행자 충돌은 사라지나 **safety 의 가속 제한 값이 실측되지 않았다.** 안 권함 |
| C | 코드 그대로 두고 사람이 물리 E-stop 으로 커버 | 로봇이 사람과 같은 공간에서 도는데 소프트 정지가 없다. **권하지 않음** |

**추가 판단이 필요한 것:** 실기에는 `collision_monitor` 가 없다. safety 의 초음파
근접 정지가 유일한 자동 정지다. `require_ultrasonic` 이 실기에서 켜져 있는지,
초음파 한 개(전방)로 충분한지는 **실물에서 정지거리를 재고 정해야 한다.**

**이 변경은 실기 launch 의 구조 변경이다. 승인 뒤 착수한다.**

---

## 2. 로봇 2대 — Open-RMF 로 되는가

> 사용자 질문: *"2대 할 때 open-rmf 기능을 활용할 수 있는 방향이 있는지 정리해줘."*

### 2.1 결론 — 된다. 그리고 이미 절반 이상 배선돼 있다

Open-RMF Jazzy 의 `rmf_fleet_adapter` 는 **mutex group** 을 완전히 구현하고 있다.

```
librmf_fleet_adapter.so 심볼 (실측)
  RobotContext::request_mutex_groups(set<string>, deadline)
  RobotContext::retain_mutex_groups / _release_mutex_group
  RobotContext::_check_mutex_groups(MutexGroupStates)
  RobotContext::_handle_mutex_group_manual_release(...)
  rmf_traffic::agv::Graph::Waypoint::set_in_mutex_group(...)
  rmf_traffic::agv::Graph::Lane::Properties::set_in_mutex_group(...)
```

`rmf_fleet_msgs` 에 `MutexGroupRequest` · `MutexGroupStates` · `MutexGroupAssignment`
· `MutexGroupManualRelease` 가 다 있다.

**중요:** `request_mutex_groups` 가 **집합(`unordered_set`)을 한 번에** 받는다.
필요한 그룹을 **전부 얻은 뒤에야** 진입한다는 뜻이고, 그것이 2-phase locking 이다.
**"A 가 병목1 을 쥔 채 병목2 를 기다리고 B 가 그 반대" 라는 교착이 구조적으로 안 생긴다.**
그래서 `path_schedule.py`·`traffic_reservation.py`·`bottleneck.py` 를 런타임에
연결할 필요가 **없다.** 그 셋은 RMF 가 이미 하는 일을 우리 층에서 다시 하는 것이다.

### 2.2 그런데 지금은 꺼져 있다 — 키 이름 하나 때문에

우리 nav_graph 생성기는 병목 정점에 이렇게 쓴다
([p0_runtime_assets.py:272](../../control_tower/bringup/p0_runtime_assets.py#L272)).

```yaml
# .trihouse/p0/nav_graph.yaml (실제 산출물)
- - 0.841
  - -0.111
  - mutex_group: bottleneck_01          # ← 우리가 쓰는 키
    name: TRIHOUSE-TEST-01-BOTTLENECK-01
```

그런데 RMF 의 graph 파서가 읽는 정점 속성 키는 이것들이다 (`librmf_fleet_adapter.so`
문자열, parse_graph 순서 그대로).

```
is_parking_spot   is_holding_point   is_passthrough_point   is_charger
mutex             merge_radius       orientation_constraint
door_name         dock_name          speed_limit
```

**`mutex` 다. `mutex_group` 이 아니다.** RMF 의 파서는 모르는 키를 조용히 버린다.
**즉 지금 발행되는 graph 에는 상호배제가 하나도 없다.** 오류도 경고도 나지 않는다.

> **고칠 자리: `p0_runtime_assets.py:272` 의 `"mutex_group"` → `"mutex"` 한 단어.**
> JSONL 의 필드 이름(`mutex_group`)은 우리 정본이니 그대로 두고, **YAML 로 내보낼 때의
> 키만** 바꾼다.

### 2.3 그것만으로 2대가 되는가 — 아니다, §3 이 먼저다

mutex 를 켜면 **통로 경합**은 RMF 가 맡는다. 남는 것은 두 가지다.

| 남는 것 | 왜 |
|---|---|
| **namespace (H1)** | 두 로봇이 `/scan`·`/odom`·`/cmd_vel` 을 공유하면 mutex 와 무관하게 섞인다. §3 |
| 부하 | 실기는 Nav2 가 로봇 위에서 도므로 관제 PC 부하는 시뮬보다 훨씬 낮다. 시뮬의 12코어 문제는 실기에 없다 |

그리고 **RMF 의 lane 교통(traffic schedule / negotiation)은 이미 켜져 있다** —
`rmf_core.launch.py` 가 schedule 노드를 띄우고 두 adapter 가 같은 schedule 에 붙는다.
lane 이 좁아 서로 비켜야 하는 상황은 RMF 가 협상으로 푼다.

**정리: 2대 운용에 새 스케줄러를 만들 필요는 없다. `mutex` 키 한 단어 + namespace 배선이면
Open-RMF 가 통로 경합과 교통을 모두 맡는다.**

---

## 3. 실물 테스트를 구조적으로 막는 것

### H0. 협로 규칙 주행이 RMF 작업을 취소시킨다 — **2026-08-20 실측, 재현됨**

**깨끗한 상태에서 주문을 넣어 두 번 연속 같은 자리에서 죽었다.** 지금 완주를 막는 것은
이것 하나다.

```text
job 2  step 10 arm/pick        succeeded
       step 20 mobile/navigate cancelled   RMF_TASK_CANCELLED
       step 30~70              pending      ← 러너가 여기서 영원히 멈춘다
```

`/tmp/sim.log` 의 그 순간 (시각 순서 그대로).

```text
[fleet_node]      협로 exit 2/3 — straight 0.315                     ← 규칙 주행 중
[fleet_adapter]   RMF 상태 갱신 중단: PINKY_NOT_READY
[fleet_adapter]   상태 복구 확인 후 RMF에 recommission했습니다
[project1_pinky_fleet_adapter]
     Requesting replan for [project1_pinky/PK_01]
     because its command handle seems to be unresponsive      ← ★ 근본 원인
[fleet_adapter]   RMF stop을 Pinky action cancel로 전달했습니다
[bt_navigator]    Failed to get result for follow_path in node halt!
[bt_navigator]    Goal canceled
[fleet_adapter]   navigation canceled
[job_runner]      job runner blocked: job 2: step 3 is cancelled     ← 이후 무한 반복
```

**연쇄.**

1. 로봇이 협로에 들어가면 `fleet_node` 가 Nav2 대신 **규칙 주행**을 잡는다
   (`cmd_vel_nav` 로 직접 발행. `narrow_zone_pilot`).
2. 그동안 `navigate_to_pose` 는 진행하지 않으므로 RMF EasyFullControl 의
   **command handle 감시기가 "응답 없음" 으로 판정**한다.
3. RMF 가 replan 을 걸고 **stop → Nav2 goal cancel** 을 내린다.
4. `navigation canceled` → step 20 이 `RMF_TASK_CANCELLED` 로 닫힌다.
5. **러너에 취소된 step 의 회복 경로가 없다.** `job runner blocked: step N is cancelled`
   를 매 주기 반복하며 job 이 로봇을 쥔 채 영구히 멈춘다. 그 사이 fleet adapter 는
   `FMS command claim 실패: 409` 를 초당 수백 번 낸다 (앞 세대에서 `/tmp/sim.log`
   201 MB).

**즉 협로 규칙 주행과 RMF 작업 수명주기가 서로를 모른다.** 규칙 주행이 도는 동안
RMF 에 "나 살아 있고 진행 중" 이라고 말해 줄 사람이 없다.

**고칠 방향 (선택 필요).**

| | 방법 | 판정 |
|---|---|---|
| **A** | 규칙 주행 중에도 RMF command handle 을 살아 있게 유지한다 — 진행 보고(`updater`)를 규칙 주행 루프에서도 계속 낸다 | 사슬을 안 바꾼다. **가장 작다** |
| B | 협로 구간을 RMF `dock_name` 으로 만들어 RMF 가 "도킹 중" 으로 알게 한다 | RMF 가 원래 그 용도로 가진 기능. nav_graph 에 `dock_name` 을 넣는다. 구조적으로 옳지만 graph·adapter 양쪽 변경 |
| C | 감시기 타임아웃을 늘린다 | 증상만 늦춘다. 협로가 길면 다시 터진다 |

**그리고 4번(러너가 취소된 step 에서 영구히 멈춤)은 어느 쪽을 골라도 따로 고쳐야 한다** —
실기에서는 취소가 더 자주 일어난다.

**실기 영향:** 협로 규칙 주행은 실기에 **반드시 필요하다**(H4 의 숫자). 그러니 이것을
고치지 않으면 실기 출고는 step 20 에서 죽는다. **H3(안전 gate)과 함께 착수 전 필수다.**


### H1. 벤더 로봇 bringup 이 namespace 를 지원하지 않는다 — **2대 운용의 실제 벽**

`sim-to-hardware` 계획서 Task 3 이 *"로봇 위에서 확인하라"* 고 남긴 분기점을
**소스로 확정했다.**

```xml
<!-- pinky_pro/pinky_bringup/launch/bringup_robot.launch.xml — 전문 -->
<launch>
  <arg name="use_sim_time" .../>  <arg name="wheel_radius" .../>  <arg name="wheel_separation" .../>
  <include file=".../upload_robot.launch.py"> ... </include>
  <include file=".../sllidar_c1_launch.py">   ... frame_id=rplidar_link ... </include>
  <node pkg="pinky_bringup" exec="bringup"/>            <!-- 모터 · odom -->
  <node pkg="pinky_bringup" exec="battery_publisher"/>
</launch>
```

**`<arg name="namespace">` 도 `<push-ros-namespace>` 도 없다.** 우리 launch 는
`launch_arguments={'namespace': namespace}` 로 넘기지만, launch 는 선언되지 않은
인자를 **오류로 만들지 않는다**([include_launch_description.py:215-235](/opt/ros/jazzy/lib/python3.12/site-packages/launch/actions/include_launch_description.py)) —
조용히 무시된다.

**결과:**

| 노드 | 지금 뜨는 자리 |
|---|---|
| sllidar → `scan` | **루트** `/scan` |
| `pinky_bringup/bringup` → `cmd_vel`·`odom`·TF | **루트** |
| `battery_publisher` → `batt_state` | **루트** |
| Nav2 (벤더 `bringup_launch.xml` 은 push 함) | `/pinky_01/...` |
| 우리 온보드 노드 (PushRosNamespace) | `/pinky_01/...` |

**Nav2 와 우리 노드는 `/pinky_01/scan` 을 듣는데 라이다는 `/scan` 에 쏜다.** AMCL 이
스캔을 하나도 못 받아 `map -> odom` 이 안 나오고, `status` 의 `frame_id` 가 `map` 이
되지 못해 **RMF adapter 가 로봇을 거절한다.**

> 예외 하나 — `upload_robot.launch.py` 는 자기 `namespace` 인자를 갖고 rsp 를 그 아래
> 둔다. 그리고 launch configuration 이 상위에서 이미 `pinky_01` 로 설정돼 있으므로
> **rsp 만 namespace 를 문다.** 그래서 프레임은 `pinky_01/` 접두사가 붙는데 센서 노드는
> 루트에 있는 어긋난 상태가 된다.

**고칠 자리 (실기 launch, 우리 저장소).**

```python
GroupAction([
    PushRosNamespace(namespace),          # ← 없다. 이것을 넣는다
    SetRemap('/tf', 'tf'), SetRemap('/tf_static', 'tf_static'),
    IncludeLaunchDescription(vendor_bringup),
])
```

주석 *"벤더 bringup 이 자기 인자로 스스로 push 하므로 두 번 감싸면
`/pinky_01/pinky_01/...` 이 된다"* 는 **사실과 다르다.** 벤더 XML 에 push 가 없다.
다만 `upload_robot.launch.py` 의 rsp 만 이중이 되므로 그 하나를 함께 처리해야 한다
(그 그룹에서 `namespace` 설정을 비우고 프레임 접두사는 PushRosNamespace 쪽으로 통일).

**프레임 접두사 정책이 따라온다.** `derive_hardware_nav2_params.py` 는 params 의 프레임
이름에 namespace 를 붙인다. 벤더 rsp 가 접두사를 안 붙이면 그 둘이 어긋난다.
**둘 중 하나로 통일해야 하고, 그 선택이 곧 분기 A 의 내용이다.**

**로봇에서 5분이면 확인된다** — 런북 0단계에 넣었다.

| 확인 | 결과 → 분기 |
|---|---|
| `ros2 topic list \| grep -c '^/pinky_01/scan'` 이 **1** | 분기 A 가 이미 됨 |
| `/scan` 만 있고 `/pinky_01/scan` 이 없음 | **분기 B 강제** — 1대만 가능. 2대는 위 수정 필요 |

---

### H2. 관제 호스트용 실기 bringup 이 없다

관제 층을 띄우는 것은 `p0_simulation_bringup.sh` 하나이고, 2)절이
`two_pinky_order_demo.launch.py` 를 부른다. 그 launch 의 **로봇 그룹**은 아래를
**조건 없이** 띄운다([two_pinky_order_demo.launch.py:253-495](../../trihouse_rmf_bridge/launch/two_pinky_order_demo.launch.py#L253-L495)).

```
robot_state_publisher   ros_gz_sim create(spawn)   status_node
sim_hardware            battery_condition          battery_policy
readiness_checker       safety_supervisor          fleet_node
fleet_gateway           ros_gz_bridge ×2
```

**`start_gazebo:=false start_nav2:=false` 로도 그대로 뜬다.** 조건이 걸린 것은 Nav2
include(364행)와 Gazebo 프로세스(535행)뿐이다.

실기에서 이걸 띄우면:

| 무엇 | 결과 |
|---|---|
| `sim_hardware` | **가짜 배터리·근접 센서**가 실물과 같은 토픽에 발행된다 |
| `safety_supervisor` 2벌 | 모터 토픽 발행자가 늘어난다. 안전 판정이 갈라진다 |
| `fleet_gateway` 2벌 | 같은 robot_id 로 8788 에 두 세션 → 시퀀스·세션 충돌 |
| `ros_gz_sim create` | Gazebo 가 없어 영원히 대기 |
| `verify_robot_status.py` | `publishers` 가 2 → **문서 규칙상 이후 측정값 전부 무효** |

**필요한 것:** 관제 PC 에서 아래 여섯만 띄우는 실기 bringup. **부품은 전부 있다.
조합해 주는 파일만 없다.**

```
rmf_core.launch.py
pinky_easy_fleet_adapter.launch.py × 로봇 수
trihouse_omx_adapter (hardware_omx_adapter) × 필요 수
job_runner_node    executor_worker_node    rmf_gateway_worker_node
```

---

### H3. 안전 gate — §1 참조. **최우선**

---

### H4. 협로 규칙 주행이 실기 launch 에 연결되지 않았다

`fleet_node` 는 `narrow_zones_file` · `narrow_map_name` 으로 켜진다
([fleet_node.py:145-147](../../trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py#L145-L147)).
시뮬 launch 는 넘기지만 **실기 launch 는 넘기지 않는다** — 실기 `fleet_node` 파라미터는
`robot_id` 와 `map_revision` 둘뿐이다. 파일이 없으면 노드는 **조용히** 규칙 주행을 끈다.

숫자가 Nav2 로는 안 된다고 말한다.

| | 값 |
|---|---|
| 도크 앞 통로 폭 | 0.20 m |
| 로봇 필요 폭 (padding 포함) | 0.14 m |
| 편측 여유 | **0.03 m** |
| AMCL 오차 (실측 stddev) | **0.08 ~ 0.11 m** |

**오차가 여유의 세 배다.** 실기에서 이대로 두면 step 20(navigate) 이 도크 앞에서
막히고 로봇이 "나왔다 들어갔다" 를 반복한다.

---

### H5. `new_map_2` 로 옮기면 따라오는 일

두 지도는 **같은 방을 두 번 SLAM 한 것**이지만 프레임이 다르다.

| | `trihouse_map_01` | `new_map_2` |
|---|---|---|
| 크기 | 44 × 54 px @ 0.05 → 2.20 × 2.70 m | 73 × 89 px @ 0.03 → 2.19 × 2.67 m |
| origin | `[-0.277, -1.452]` | `[-0.220, -1.473]` |
| 차이 | — | **Δ (+0.057, −0.021) m** |

**origin 이 5.7 cm 다르다.** 협로 편측 여유가 3 cm 이므로, 좌표를 그대로 옮기면
**여유보다 큰 오차를 처음부터 안고 시작한다.**

따라오는 일 넷.

| # | 무엇 | 없으면 |
|---|---|---|
| 1 | **좌표 정본 재측정** — `trihouse_test_01_physical_features.jsonl` 의 waypoint 8 + 병목 2 | 로봇이 "도착했다"는 자리와 원장이 아는 자리가 어긋나 도착 판정이 구조적으로 실패 |
| 2 | **`config/narrow_zones.new_map_2.yaml`** — 지금 없다 | 규칙 주행이 **조용히 꺼진다**. `p0_reset.sh` 가 경고는 해 준다 |
| 3 | `map_revision` 재발행 | bringup 이 revision 불일치로 거절 |
| 4 | 로봇으로 지도 파일 배포 | 관제가 발행한 지도와 로봇이 도는 지도가 갈라진다 |

**2026-08-20 실측 — 지금 좌표를 그대로 `new_map_2` 에 얹으면 냉동 도크에 못 간다.**

```bash
python3 scripts/p0_show_map.py new_map_2
```

병목 01 에서 각 도크까지의 최선 통로 폭. 로봇에 필요한 폭은 **0.14 m**(지역 costmap).

| 도크 | `trihouse_map_01` | `new_map_2` | 판정 |
|---|---|---|---|
| ambient | 0.30 m | 0.18 m | 통과 가능 |
| chilled | 0.40 m | 0.36 m | 통과 가능 |
| **frozen** | 0.20 m | **0.06 m** | **통과 불가** |
| packing ×2 | 0.50 m | 0.66 m | 통과 가능 |

10 개 지점 전부 통행 가능한 격자 위에 있기는 하다. **문제는 지점이 아니라 가는 길이다.**
해상도가 0.05 → 0.03 으로 올라가 벽이 더 얇고 자세히 잡힌 것과, origin 이 5.7 cm
밀린 것이 겹쳤다. **냉동 도크 좌표는 반드시 다시 재야 한다.**

절차는 이미 있다 — [p0-narrow-zone-measurement.md](../runbooks/p0-narrow-zone-measurement.md),
`notebooks/narrow_zone_measurement.ipynb`, [p0-glb-world-alignment.md](../runbooks/p0-glb-world-alignment.md).

`new_map_2.pgm` 은 **확장자만 `.pgm` 이고 내용은 PNG** 다. `p0_publish_map.py` 가
magic bytes 로 판별해 처리하므로 저장소 파일은 건드리지 않는다.

---

### H6. 로봇팔 — 이번엔 뺀다 (결정됨)

- `config/act.simulation.yaml` — `mode: deterministic_fake`, repo/revision/profile 전부
  `UNCONFIGURED`. **`act.hardware.yaml` 은 없다.**
- [executor_worker_node.py:78-86](../../control_tower/task_manager/executor_worker_node.py#L78-L86) 이
  실제 OMX motion 을 여는 정책이 실리면 **기동을 거부**한다.

**이번 테스트에서의 처리:** step 10 `arm/pick` 은 원장에 그대로 두고 프로토콜 왕복만
시킨다(= 물리 동작 없음). 그 사이 **사람이 물건을 로봇에 올린다.** 7단계 구조가
유지되므로 시뮬 기록과 비교할 수 있고, 나중에 팔이 준비되면 그 단계만 실물로 바꾸면 된다.

---

### H7. 실기용 초기화·기동·정리 스크립트가 없다

| 스크립트 | 지금 | 실기에 필요한 것 |
|---|---|---|
| `scripts/p0_up.sh` | `TRIHOUSE_ROBOTS=PK_01`·`ROS_DOMAIN_ID=0`·`p0_simulation_bringup.sh` **하드코딩** | 도메인 52, 실기 bringup |
| `scripts/p0_reset.sh` | DB 초기화 + 지도 발행 + **시뮬 teardown** 호출 | teardown 이 실기용이어야 함 |
| `scripts/sim_teardown.sh` | Gazebo·nav2 패턴 | 실기는 관제 프로세스만 |
| `scripts/control_stack` | `--mode` 가 `choices=("simulation",)` (286행) | hardware 모드 |

---

### H8. 도메인·바인딩·주소가 실기 값으로 정리되지 않았다

**전부 "오류 없이 조용히 안 되는" 종류다.**

| 항목 | 지금 | 실기 값 | 안 맞으면 |
|---|---|---|---|
| `ROS_DOMAIN_ID` | 시뮬 0 강제 / `.env.example` 52 / compose 기본 52 | **전부 52** | 같은 이름의 노드가 서로를 못 본다. 오류 없음 |
| `FMS_TCP_BIND` | `127.0.0.1` | 4060 **Ethernet** 주소 | 로봇이 8788 에 못 붙어 `control_link_offline` 이 안 풀리고 `dispatchable=false` → RMF 가 작업을 안 준다 |
| `FMS_API_HOST` | `127.0.0.1` | 로봇/타 PC 가 8080 을 쓰면 LAN 주소 | 상동 |
| `ROS_AUTOMATIC_DISCOVERY_RANGE` | `SUBNET` | `SUBNET` | 서버는 인터페이스가 둘(Wi-Fi + ROS 전용 Ethernet). 한 층만 좁히면 그 층이 상대를 못 본다 |
| `PINKY_PK_0N_IP` 등 | 자리표시자 | **DHCP 예약 주소** | MediaMTX publish 가 IP 허용목록이라 그 로봇만 조용히 거절된다 |
| `compose.simulation.yaml` 의 `rmf_api` | `ROS_DOMAIN_ID` 기본 52 | 호스트와 같은 값 | 한쪽만 바뀌면 침묵으로 갈라진다 |

---

### H9. 배정이 first-fit — "시간 효율" 은 없다

설계 8절 5~10(ETA 추정기 → `available_at` → ETA 최소화 배정 → 전방 예약 → `in_use`
전이 → 경로 기반 ETA)이 전부 미구현. 빈 로봇을 먼저 잡을 뿐이다.

**이번 테스트("2 주문이 두 로봇에 나뉘어 돈다")에는 문제가 없다.** 목표와의 거리를
기록해 둔다.

---

## 4. 회차 3회 반복을 막는 것

| # | 무엇 | 실기에서의 뜻 |
|---|---|---|
| **O1** | **D2 — 취소가 재고 예약을 안 돌려준다** | `p0_reset.sh` 가 DB 를 되돌리며 **지도도 재발행**한다. 그러면 로봇이 든 `map_revision` 이 낡아 거절되므로 **로봇까지 재기동**해야 한다. → 런북은 **회차마다 다른 SKU** 로 돌아 초기화를 피한다 (seed 에 SKU 11 종 × 1 lot) |
| **O2** | **D15 — 순간 안전정지가 로봇을 fleet 에서 빼낸다** (미수정, 근본) | 실기에는 사람·장애물이 실제로 있어 시뮬보다 훨씬 자주 터진다. 3회 중 재현 가능성 높음 |
| **O3** | D18 — bringup 셸을 닫으면 SIGHUP 으로 전체 사망 | 시뮬은 `p0_up.sh` 가 `setsid` 로 우회. 실기 스크립트가 없어 그대로 노출 |
| **O4** | `DISPATCH_ATTEMPTS_EXHAUSTED` 가 개별 거절 사유를 덮어씀 (D22) | 실패 시 DB 만으로는 원인을 못 찾는다. **로그를 반드시 파일로 남긴다** |
| **O5** | 실기 teardown 이 없다 | `sim_teardown.sh` 를 실기에서 돌리지 않는다 |

---

## 5. 우선순위 — 이 순서

```
0. 협로 주행 ↔ RMF 수명주기          ← H0. 지금 완주를 막는 것. 시뮬에서 재현됨
   + 러너의 취소 step 회복 경로
1. new_map_2 좌표·협로 실측          ← H5. 냉동 도크 통로 0.06 m — 재측정 없이는 못 간다
2. 안전 gate 배선                    ← §1.4. 로봇이 사람 옆에서 돌기 전에
3. 벤더 namespace 배선 확인/수정      ← H1. 로봇에서 5분. 분기 A/B 가 여기서 갈린다
4. 관제 호스트 실기 bringup           ← H2
5. 협로 파라미터를 실기 launch 에     ← H4
6. 1대 완주 3회                       ← 목표 1
7. mutex 키 한 단어 + 2대 기동        ← §2. 목표 2
```

**0 이 먼저인 이유:** 시뮬에서 이미 두 번 연속 같은 자리에서 죽었다. 실기로 옮겨도
그대로 죽으므로, 실기 준비를 아무리 해도 이것을 지나갈 수 없다.

**1 이 2·3 보다 먼저인 이유:** 좌표가 틀리면 그 뒤의 모든 실패가 코드 결함인지 좌표
오차인지 구분되지 않는다. 2와 3은 순서를 바꿔도 된다.

---

## 6. 이번 범위 밖

| 축 | 상태 |
|---|---|
| 입고 (UR_01) | 주문 API 가 `Literal["outbound"]` 고정. `planned_inbound_steps()` 없음 |
| 비상 · 작업자 쓰러짐 (UR_10) | `EmergencyWorkflow` 236줄을 **런타임에서 부르는 곳 0**. Gateway 에 incident 엔드포인트 없음 |
| 팔 ∥ 주행 병렬 (UR_13) | `dependencies`/`gate` 를 **읽는 곳 0**. 보상(place_back) 단계도 없다 |
| 카메라 · QR · 5080 AI | 출고 완주 경로에 없다. `stream_health` 실패는 `dispatchable` 에 안 들어간다 |

---

관련 문서
- 실행 절차: [p0-hardware-quick-run.md](../runbooks/p0-hardware-quick-run.md)
- 시뮬 절차: [p0-simulation-quick-run.md](../runbooks/p0-simulation-quick-run.md)
- 결함 정본 D1~D22: [p0-stack-reference.md](p0-stack-reference.md)
- 로봇 단독 점검: [2026-08-18-pinky-hardware-nav2-smoke.md](../validation/2026-08-18-pinky-hardware-nav2-smoke.md)
- 협로 실측: [p0-narrow-zone-measurement.md](../runbooks/p0-narrow-zone-measurement.md)
