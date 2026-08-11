# Open-RMF 에너지 Bridge 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Open-RMF office 시뮬레이션의 `/fleet_states`, navigation graph, 공식 motion·ambient 배터리 모델을 Trihouse `EstimateTaskEnergy` 서비스와 Control Tower에 연결한다.

**Architecture:** 새 C++ ROS 2 패키지 `trihouse_rmf_bridge`가 fleet 상태 저장, 순수 에너지 계산, ROS 서비스 변환을 분리한다. 기존 Python `RmfEnergyEstimator` 앞에는 동기 호출 규약을 구현하는 ROS client adapter를 추가하고, 실제 office graph를 사용하는 통합 테스트와 수동 검증 CLI로 끝단 연결을 검증한다.

**Tech Stack:** Ubuntu 24.04, ROS 2 Jazzy, C++17, `rclcpp`, `rmf_fleet_msgs`, `rmf_traffic 3.3.3`, `rmf_battery 0.3.1`, `rmf_fleet_adapter`, `ament_cmake_gtest`, Python 3, `rclpy`, `pytest`

## Global Constraints

- `/home/syw/Trihouse/pinky_pro`, `/home/syw/Trihouse/control_system`, `/home/syw/rmf_ws`는 읽기만 하고 수정하지 않는다.
- 서비스 이름은 `/trihouse/rmf/estimate_task_energy`, 형식은 `trihouse_interfaces/srv/EstimateTaskEnergy`로 고정한다.
- office 기본 대상은 fleet `tinyRobot`, robot `tinyRobot1`, fleet-state freshness timeout은 `3.0 s`이다.
- `RobotState.battery_percent`의 `0..100`을 내부 SOC `0.0..1.0`으로 변환한다.
- 이동 소비는 itinerary의 모든 trajectory에 `SimpleMotionPowerSink`를 적용해 합산한다.
- ambient 소비는 이동·적재·인계·buffer를 합친 전체 작업시간에 `SimpleDevicePowerSink`를 적용한다.
- Pinky 배터리를 사용하지 않는 OMX tool power는 계산하지 않는다.
- 마지막 정상 예측값이나 부분 경로 결과를 오류 시 재사용하지 않는다.
- Control Tower service timeout은 `2.0 s`, timeout 재시도는 1회다.
- 구현은 테스트를 먼저 실패시키고 최소 구현으로 통과시키는 TDD 순서를 지킨다.

---

### Task 1: C++ 패키지 골격과 fleet 상태 저장소

**Files:**
- Create: `trihouse_rmf_bridge/package.xml`
- Create: `trihouse_rmf_bridge/CMakeLists.txt`
- Create: `trihouse_rmf_bridge/include/trihouse_rmf_bridge/fleet_state_store.hpp`
- Create: `trihouse_rmf_bridge/src/fleet_state_store.cpp`
- Create: `trihouse_rmf_bridge/test/test_fleet_state_store.cpp`

**Interfaces:**
- Consumes: `rmf_fleet_msgs::msg::FleetState`, `std::chrono::steady_clock::time_point`
- Produces: `RobotSnapshot`, `SnapshotResult`, `FleetStateStore::update(const FleetState&, TimePoint)`, `FleetStateStore::snapshot(TimePoint) const`

- [ ] **Step 1: 저장소 계약을 검증하는 실패 테스트 작성**

```cpp
TEST(FleetStateStore, WaitsForFirstMatchingSampleAndRejectsStaleData)
{
  FleetStateStore store("tinyRobot", "tinyRobot1", 3s);
  const auto t0 = FleetStateStore::Clock::time_point{};
  EXPECT_EQ(store.snapshot(t0).reason_code,
    "WAITING_FOR_FIRST_RMF_FLEET_STATE");

  store.update(make_fleet_state("tinyRobot", "tinyRobot1", 18.0), t0);
  const auto fresh = store.snapshot(t0 + 2s);
  ASSERT_TRUE(fresh.snapshot.has_value());
  EXPECT_DOUBLE_EQ(fresh.snapshot->state_of_charge, 0.18);
  EXPECT_EQ(store.snapshot(t0 + 4s).reason_code, "RMF_FLEET_STATE_STALE");
}

TEST(FleetStateStore, IgnoresOtherFleetAndRobotAndRejectsInvalidBattery)
{
  FleetStateStore store("tinyRobot", "tinyRobot1", 3s);
  const auto now = FleetStateStore::Clock::time_point{};
  store.update(make_fleet_state("other", "tinyRobot1", 50.0), now);
  EXPECT_EQ(store.snapshot(now).reason_code,
    "WAITING_FOR_FIRST_RMF_FLEET_STATE");
  store.update(make_fleet_state("tinyRobot", "tinyRobot1",
    std::numeric_limits<float>::quiet_NaN()), now);
  EXPECT_EQ(store.snapshot(now).reason_code,
    "RMF_BATTERY_PERCENT_INVALID");
}
```

- [ ] **Step 2: 테스트를 실행해 패키지 부재로 실패 확인**

Run: `source /opt/ros/jazzy/setup.bash && colcon test --packages-select trihouse_rmf_bridge --event-handlers console_direct+`

Expected: FAIL 또는 package not found. 아직 `FleetStateStore` 구현이 없다.

- [ ] **Step 3: 메시지와 monotonic 수신시각만 보존하는 최소 구현 작성**

```cpp
struct RobotSnapshot
{
  std::string map_name;
  double x;
  double y;
  double yaw;
  uint32_t mode;
  std::string task_id;
  double state_of_charge;
};

struct SnapshotResult
{
  std::optional<RobotSnapshot> snapshot;
  std::string reason_code;
  std::string detail;
};

class FleetStateStore
{
public:
  using Clock = std::chrono::steady_clock;
  using TimePoint = Clock::time_point;
  FleetStateStore(std::string fleet_name, std::string robot_name,
    Clock::duration timeout);
  void update(const rmf_fleet_msgs::msg::FleetState& message, TimePoint received_at);
  SnapshotResult snapshot(TimePoint now) const;
};
```

`update()`는 fleet 이름 불일치 시 무시하고, 대상 robot이 없으면 `RMF_ROBOT_NOT_FOUND`, 배터리가 유한수가 아니거나 `0..100` 밖이면 `RMF_BATTERY_PERCENT_INVALID`를 저장한다. 정상 데이터만 `battery_percent / 100.0`으로 변환하며, `snapshot()`은 첫 정상 수신 전 오류와 `now-received_at > timeout`을 구분한다.

- [ ] **Step 4: 저장소 테스트 통과 확인**

Run: `source /opt/ros/jazzy/setup.bash && colcon build --packages-select trihouse_rmf_bridge && colcon test --packages-select trihouse_rmf_bridge --ctest-args -R test_fleet_state_store --output-on-failure`

Expected: PASS, battery `18.0`이 SOC `0.18`로 변환되고 3초 초과 데이터가 거절된다.

- [ ] **Step 5: 저장소 단위 커밋**

```bash
git add trihouse_rmf_bridge
git commit -m "feat: add RMF fleet state store"
```

### Task 2: 순수 RMF 경로·배터리 계산기

**Files:**
- Create: `trihouse_rmf_bridge/include/trihouse_rmf_bridge/energy_estimator.hpp`
- Create: `trihouse_rmf_bridge/src/energy_estimator.cpp`
- Create: `trihouse_rmf_bridge/test/fixtures/test_graph.yaml`
- Create: `trihouse_rmf_bridge/test/test_energy_estimator.cpp`
- Modify: `trihouse_rmf_bridge/CMakeLists.txt`
- Modify: `trihouse_rmf_bridge/package.xml`

**Interfaces:**
- Consumes: `RobotSnapshot`, waypoint 이름 배열, 세 작업 단계 시간, RMF graph/vehicle/battery 파라미터
- Produces: `EstimateInput`, `EstimateOutput`, `EstimateError`, `EnergyEstimator::estimate(const EstimateInput&) const`

- [ ] **Step 1: 연결·다중 구간·입력 오류에 대한 실패 테스트 작성**

```cpp
TEST(EnergyEstimator, AddsAllSegmentsAndNonTravelDurations)
{
  auto estimator = make_test_estimator("test/fixtures/test_graph.yaml");
  EstimateInput input{make_snapshot(1.0), {"pickup", "dropoff"}, 30.0, 20.0, 10.0};
  const auto result = estimator.estimate(input);
  ASSERT_TRUE(result.has_value());
  EXPECT_GT(result->travel_duration_s, 0.0);
  EXPECT_DOUBLE_EQ(result->total_duration_s,
    result->travel_duration_s + 60.0);
  EXPECT_GT(result->motion_change_in_charge, 0.0);
  EXPECT_GT(result->ambient_change_in_charge, 0.0);
  EXPECT_DOUBLE_EQ(result->change_in_charge,
    result->motion_change_in_charge + result->ambient_change_in_charge);
}

TEST(EnergyEstimator, RejectsUnknownWaypointAndNegativeStageTime)
{
  auto estimator = make_test_estimator("test/fixtures/test_graph.yaml");
  EXPECT_EQ(error_code(estimator.estimate(
    {make_snapshot(1.0), {"missing"}, 0.0, 0.0, 0.0})),
    "RMF_WAYPOINT_NOT_FOUND");
  EXPECT_EQ(error_code(estimator.estimate(
    {make_snapshot(1.0), {"pickup"}, -1.0, 0.0, 0.0})),
    "RMF_TASK_DURATION_INVALID");
}
```

- [ ] **Step 2: 계산기 테스트를 실행해 링크/타입 부재 실패 확인**

Run: `source /opt/ros/jazzy/setup.bash && source /home/syw/rmf_ws/install/setup.bash && colcon build --packages-select trihouse_rmf_bridge --cmake-args -DBUILD_TESTING=ON`

Expected: FAIL. `EnergyEstimator`, test graph, RMF 링크 설정이 아직 없다.

- [ ] **Step 3: 공개 계산 계약과 모델 설정 타입 구현**

```cpp
struct EstimateInput
{
  RobotSnapshot robot;
  std::vector<std::string> waypoint_ids;
  double loading_duration_s;
  double handover_duration_s;
  double buffer_duration_s;
};

struct EstimateOutput
{
  double travel_duration_s;
  double total_duration_s;
  double motion_change_in_charge;
  double ambient_change_in_charge;
  double change_in_charge;
  double finish_state_of_charge;
};

struct EstimateError { std::string reason_code; std::string detail; };
using EstimateResult = std::variant<EstimateOutput, EstimateError>;
```

생성자는 graph 경로, `VehicleTraits`, `BatterySystem`, `MechanicalSystem`, ambient `PowerSystem`을 받는다. 모델 factory가 실패하면 예외를 밖으로 내보내지 않고 `RMF_ENERGY_MODEL_INVALID`로 변환할 수 있도록 생성 factory `EnergyEstimator::make(...) -> std::variant<EnergyEstimator, EstimateError>`를 둔다.

- [ ] **Step 4: 공식 RMF API를 이용한 최소 계산 구현**

```cpp
auto starts = rmf_traffic::agv::compute_plan_starts(
  graph, input.robot.map_name,
  Eigen::Vector3d{input.robot.x, input.robot.y, input.robot.yaw}, now);
if (starts.empty())
  return EstimateError{"RMF_START_NOT_ON_GRAPH", "robot pose cannot join graph"};

double travel_s = 0.0;
double motion_soc = 0.0;
for (const auto& waypoint_id : input.waypoint_ids)
{
  const auto* waypoint = graph.find_waypoint(waypoint_id);
  if (!waypoint)
    return EstimateError{"RMF_WAYPOINT_NOT_FOUND", waypoint_id};
  const auto plan = planner.plan(starts, rmf_traffic::agv::Plan::Goal(waypoint->index()));
  if (!plan)
    return EstimateError{"RMF_ROUTE_UNAVAILABLE", waypoint_id};
  for (const auto& route : plan->get_itinerary())
  {
    const auto* begin = route.trajectory().start_time();
    const auto* finish = route.trajectory().finish_time();
    if (begin && finish)
      travel_s += std::chrono::duration<double>(*finish - *begin).count();
    motion_soc += motion_sink.compute_change_in_charge(route.trajectory());
  }
  starts = {plan->get_waypoints().back()};
}
const double total_s = travel_s + input.loading_duration_s
  + input.handover_duration_s + input.buffer_duration_s;
const double ambient_soc = ambient_sink.compute_change_in_charge(total_s);
```

빈 waypoint는 `RMF_WAYPOINTS_REQUIRED`, 음수 단계시간은 `RMF_TASK_DURATION_INVALID`로 먼저 거절한다. 계산된 시간·SOC가 유한수가 아니거나 감소량이 음수이면 `RMF_ENERGY_MODEL_INVALID`; 종료 SOC는 `std::max(0.0, current_soc-change)`다.

- [ ] **Step 5: 계산기 단위 테스트 통과 확인**

Run: `source /opt/ros/jazzy/setup.bash && source /home/syw/rmf_ws/install/setup.bash && colcon test --packages-select trihouse_rmf_bridge --ctest-args -R test_energy_estimator --output-on-failure`

Expected: PASS. 다중 waypoint의 ETA와 motion 소비가 합산되고 ambient 소비에는 전체 시간이 반영된다.

- [ ] **Step 6: 계산기 단위 커밋**

```bash
git add trihouse_rmf_bridge
git commit -m "feat: estimate RMF route energy"
```

### Task 3: ROS 서비스 node, office 설정과 launch

**Files:**
- Create: `trihouse_rmf_bridge/src/energy_estimator_node.cpp`
- Create: `trihouse_rmf_bridge/config/office_bridge.yaml`
- Create: `trihouse_rmf_bridge/launch/office_energy_bridge.launch.py`
- Create: `trihouse_rmf_bridge/test/test_office_service.py`
- Modify: `trihouse_rmf_bridge/CMakeLists.txt`
- Modify: `trihouse_rmf_bridge/package.xml`

**Interfaces:**
- Consumes: `/fleet_states` (`rmf_fleet_msgs/msg/FleetState`), `EstimateTaskEnergy` request, `FleetStateStore`, `EnergyEstimator`
- Produces: `/trihouse/rmf/estimate_task_energy` service와 `trihouse_rmf_bridge_node` executable

- [ ] **Step 1: 가짜 fleet state와 실제 office graph를 사용하는 실패 통합 테스트 작성**

```python
def test_office_service_estimates_pantry_to_hardware_2(bridge_process, ros_node):
    publish_robot_state(ros_node, fleet="tinyRobot", robot="tinyRobot1",
                        level="L1", x=8.0, y=-10.0, yaw=0.0,
                        battery_percent=80.0)
    response = call_estimate(ros_node, ["pantry", "hardware_2"],
                             loading=30.0, handover=30.0, buffer=15.0)
    assert response.success
    assert response.travel_duration_s > 0.0
    assert response.total_duration_s == pytest.approx(
        response.travel_duration_s + 75.0)
    assert 0.0 < response.change_in_charge < 0.8
    assert response.finish_state_of_charge == pytest.approx(
        0.8 - response.change_in_charge)
```

같은 파일에 첫 메시지 전 `WAITING_FOR_FIRST_RMF_FLEET_STATE`, 3초 초과 `RMF_FLEET_STATE_STALE`, 빈 waypoint `RMF_WAYPOINTS_REQUIRED`, 없는 waypoint `RMF_WAYPOINT_NOT_FOUND`를 각각 검증한다.

- [ ] **Step 2: 통합 테스트를 실행해 node executable 부재 실패 확인**

Run: `source /opt/ros/jazzy/setup.bash && source /home/syw/rmf_ws/install/setup.bash && colcon test --packages-select trihouse_rmf_bridge --ctest-args -R test_office_service --output-on-failure`

Expected: FAIL. node와 launch/config가 아직 설치되지 않았다.

- [ ] **Step 3: office 파라미터 파일 작성**

```yaml
trihouse_rmf_bridge:
  ros__parameters:
    fleet_name: tinyRobot
    robot_name: tinyRobot1
    fleet_state_topic: /fleet_states
    service_name: /trihouse/rmf/estimate_task_energy
    fleet_state_timeout_s: 3.0
    linear_velocity: 0.5
    linear_acceleration: 0.75
    angular_velocity: 0.6
    angular_acceleration: 2.0
    footprint_radius: 0.3
    vicinity_radius: 0.5
    reversible: true
    nominal_voltage: 12.0
    capacity: 24.0
    charging_current: 5.0
    mass: 20.0
    moment_of_inertia: 10.0
    friction_coefficient: 0.22
    ambient_power: 20.0
```

- [ ] **Step 4: node의 구독·서비스 변환 구현**

node는 sensor-data QoS인 `rclcpp::SensorDataQoS()`로 `/fleet_states`를 구독하고 callback 수신 시 `steady_clock::now()`를 저장한다. 서비스 callback은 snapshot 오류를 그대로 응답하고, 성공 시 아래 필드를 모두 채운다.

```cpp
response->success = true;
response->travel_duration_s = output.travel_duration_s;
response->total_duration_s = output.total_duration_s;
response->change_in_charge = output.change_in_charge;
response->finish_state_of_charge = output.finish_state_of_charge;
response->reason_code = "OK";
response->detail = "RMF route and energy estimate completed";
```

실패 응답은 모든 수치 필드를 `0.0`, `success=false`로 초기화하고 해당 `reason_code`와 진단 `detail`을 기록한다. `robot_id`가 설정된 대상 robot과 다르면 `RMF_ROBOT_NOT_FOUND`를 반환한다.

- [ ] **Step 5: launch에서 package share 기반 office graph 경로 해석**

```python
office_graph = Path(get_package_share_directory("rmf_demos_maps")) / \
    "maps/office/nav_graphs/0.yaml"
Node(package="trihouse_rmf_bridge", executable="trihouse_rmf_bridge_node",
     name="trihouse_rmf_bridge",
     parameters=[config_path, {"nav_graph_file": str(office_graph)}],
     output="screen")
```

절대 홈 경로는 설정에 저장하지 않는다. `CMakeLists.txt`는 executable, `config`, `launch`를 install하고 pytest를 등록한다.

- [ ] **Step 6: ROS 통합 테스트 통과 확인**

Run: `source /opt/ros/jazzy/setup.bash && source /home/syw/rmf_ws/install/setup.bash && colcon build --packages-select trihouse_interfaces trihouse_rmf_bridge && source install/setup.bash && colcon test --packages-select trihouse_rmf_bridge --event-handlers console_direct+`

Expected: PASS. 실제 office graph와 RMF library로 정상·오류 응답이 모두 검증된다.

- [ ] **Step 7: ROS server 단위 커밋**

```bash
git add trihouse_rmf_bridge
git commit -m "feat: serve office RMF energy estimates"
```

### Task 4: Control Tower ROS client adapter와 오류 전달

**Files:**
- Modify: `control_tower/rmf_adapter/energy_estimator.py`
- Create: `control_tower/rmf_adapter/ros_energy_client.py`
- Modify: `control_tower/rmf_adapter/__init__.py`
- Modify: `control_tower/tests/test_energy_estimator.py`
- Create: `control_tower/tests/test_ros_energy_client.py`

**Interfaces:**
- Consumes: `EstimateRequest`, generated `EstimateTaskEnergy.Request/Response`, 2초 timeout
- Produces: `RmfEstimateResponse(..., reason_code, detail)`, callable `RosEstimateService.__call__(request, timeout_s)`

- [ ] **Step 1: server reason 보존과 client 변환 실패 테스트 작성**

```python
def test_server_failure_preserves_reason_code():
    estimator = RmfEnergyEstimator(lambda request, timeout: RmfEstimateResponse(
        False, 0.0, 0.0, 0.0, 0.0,
        "RMF_FLEET_STATE_STALE", "last state is older than 3 seconds"))
    with pytest.raises(EnergyEstimateError) as caught:
        estimator.estimate(make_request())
    assert caught.value.reason_code == "RMF_FLEET_STATE_STALE"

def test_ros_client_maps_request_and_response(fake_node):
    service = RosEstimateService(fake_node,
        "/trihouse/rmf/estimate_task_energy")
    response = service(make_request(), 2.0)
    assert fake_node.last_request.waypoint_ids == ["pantry", "hardware_2"]
    assert response.reason_code == "OK"
```

- [ ] **Step 2: Python 테스트를 실행해 새 타입/adapter 부재 실패 확인**

Run: `python3 -m pytest control_tower/tests/test_energy_estimator.py control_tower/tests/test_ros_energy_client.py -q`

Expected: FAIL. `reason_code`, `detail`, `RosEstimateService`가 없다.

- [ ] **Step 3: 구조화된 오류와 응답 확장 구현**

```python
class EnergyEstimateError(RuntimeError):
    def __init__(self, message: str, *, reason_code: str):
        super().__init__(message)
        self.reason_code = reason_code

@dataclass(frozen=True)
class RmfEstimateResponse:
    success: bool
    travel_duration_s: float
    total_duration_s: float
    change_in_charge: float
    finish_state_of_charge: float
    reason_code: str = ""
    detail: str = ""
```

`_validated_result()`는 `success=false`일 때 server의 `reason_code`와 `detail`을 `EnergyEstimateError`에 보존하고, `_record()`도 문자열 추론 대신 `error.reason_code`를 기록한다. 기존 테스트 호출은 default 필드 덕분에 호환되어야 한다.

- [ ] **Step 4: ROS future를 제한시간 동안 구동하는 adapter 구현**

```python
class RosEstimateService:
    def __init__(self, node, service_name="/trihouse/rmf/estimate_task_energy"):
        self._node = node
        self._client = node.create_client(EstimateTaskEnergy, service_name)

    def __call__(self, request: EstimateRequest, timeout_s: float) -> RmfEstimateResponse:
        ros_request = EstimateTaskEnergy.Request()
        ros_request.robot_id = request.robot_id
        ros_request.task_id = request.task_id
        ros_request.map_revision = request.map_revision
        ros_request.waypoint_ids = list(request.waypoint_ids)
        ros_request.expected_loading_duration_s = request.expected_loading_duration_s
        ros_request.expected_handover_duration_s = request.expected_handover_duration_s
        ros_request.task_time_buffer_s = request.task_time_buffer_s
        future = self._client.call_async(ros_request)
        rclpy.spin_until_future_complete(self._node, future, timeout_sec=timeout_s)
        if not future.done():
            future.cancel()
            raise TimeoutError("RMF energy service timed out")
        result = future.result()
        return RmfEstimateResponse(result.success, result.travel_duration_s,
            result.total_duration_s, result.change_in_charge,
            result.finish_state_of_charge, result.reason_code, result.detail)
```

- [ ] **Step 5: adapter 및 기존 estimator 테스트 통과 확인**

Run: `python3 -m pytest control_tower/tests/test_energy_estimator.py control_tower/tests/test_ros_energy_client.py -q`

Expected: PASS. server reason이 JSONL 기록까지 보존되고 timeout은 기존 estimator에서 한 번 재시도된다.

- [ ] **Step 6: Control Tower 연결 단위 커밋**

```bash
git add control_tower/rmf_adapter control_tower/tests/test_energy_estimator.py control_tower/tests/test_ros_energy_client.py
git commit -m "feat: connect control tower to RMF energy service"
```

### Task 5: 수동 검증 CLI와 office 운영 가이드

**Files:**
- Create: `control_tower/rmf_adapter/estimate_energy_cli.py`
- Create: `docs/guideline/open_rmf_energy_bridge_test.md`
- Modify: `trihouse_rmf_bridge/CMakeLists.txt`
- Create: `control_tower/tests/test_estimate_energy_cli.py`

**Interfaces:**
- Consumes: bridge service, office demo `/fleet_states`, waypoint/단계시간 CLI 인자
- Produces: 종료코드 0/1과 JSON 형식의 service 결과, 자동·수동 검증 명령 문서

- [ ] **Step 1: CLI 출력과 실패 종료코드 테스트 작성**

```python
def test_cli_prints_machine_readable_success(capsys):
    code = main(["--robot-id", "tinyRobot1", "--waypoint", "pantry",
                 "--waypoint", "hardware_2"], service=successful_service)
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["success"] is True
    assert payload["finish_state_of_charge"] < 1.0

def test_cli_returns_one_for_server_failure():
    assert main(["--waypoint", "missing"], service=failing_service) == 1
```

- [ ] **Step 2: CLI 테스트를 실행해 파일 부재 실패 확인**

Run: `python3 -m pytest control_tower/tests/test_estimate_energy_cli.py -q`

Expected: FAIL. CLI 모듈이 없다.

- [ ] **Step 3: 인자를 service request로 변환하는 CLI 구현**

CLI 기본값은 `robot_id=tinyRobot1`, `loading=30`, `handover=30`, `buffer=15`, timeout `2.0`; `--waypoint`는 1회 이상 필수다. 출력 키는 `success`, `travel_duration_s`, `total_duration_s`, `change_in_charge`, `finish_state_of_charge`, `reason_code`, `detail`로 고정한다.

```python
print(json.dumps(asdict(response), ensure_ascii=False, sort_keys=True))
return 0 if response.success else 1
```

- [ ] **Step 4: 한국어 수동 검증 절차 문서 작성**

문서에는 아래 네 터미널을 그대로 분리해 기록한다.

```bash
# 터미널 1: office demo
source /opt/ros/jazzy/setup.bash
source /home/syw/rmf_ws/install/setup.bash
ros2 launch rmf_demos_gz office.launch.xml

# 터미널 2: bridge
source /opt/ros/jazzy/setup.bash
source /home/syw/rmf_ws/install/setup.bash
source /home/syw/Trihouse/install/setup.bash
ros2 launch trihouse_rmf_bridge office_energy_bridge.launch.py

# 터미널 3: 상태 확인
source /opt/ros/jazzy/setup.bash
source /home/syw/rmf_ws/install/setup.bash
ros2 topic echo /fleet_states rmf_fleet_msgs/msg/FleetState --once

# 터미널 4: 예측 요청
source /opt/ros/jazzy/setup.bash
source /home/syw/Trihouse/install/setup.bash
python3 -m control_tower.rmf_adapter.estimate_energy_cli \
  --robot-id tinyRobot1 --waypoint pantry --waypoint hardware_2 \
  --loading-duration-s 30 --handover-duration-s 30 --buffer-duration-s 15
```

성공 판정은 `success=true`, ETA/소비 양수, `total=travel+75`, `finish_soc=current_soc-change`; 실패 판정은 demo 미실행 시 first-state/stale code, 잘못된 waypoint 시 waypoint code로 명시한다.

- [ ] **Step 5: CLI 테스트와 문서 명령 정적 검증**

Run: `python3 -m pytest control_tower/tests/test_estimate_energy_cli.py -q && rg -n "office.launch.xml|office_energy_bridge.launch.py|pantry|hardware_2|RMF_FLEET_STATE_STALE" docs/guideline/open_rmf_energy_bridge_test.md`

Expected: CLI tests PASS이고 문서에 필수 실행·판정 문자열이 모두 출력된다.

- [ ] **Step 6: 검증 도구·문서 단위 커밋**

```bash
git add control_tower/rmf_adapter/estimate_energy_cli.py control_tower/tests/test_estimate_energy_cli.py docs/guideline/open_rmf_energy_bridge_test.md trihouse_rmf_bridge/CMakeLists.txt
git commit -m "docs: add RMF energy bridge verification guide"
```

### Task 6: 전체 회귀와 변경 경계 검증

**Files:**
- Modify only if a test exposes an in-scope defect: files created or modified in Tasks 1–5
- Verify read-only: `pinky_pro/`, `control_system/`

**Interfaces:**
- Consumes: 완성된 bridge, Control Tower adapter, 기존 Trihouse test suite
- Produces: 빌드·테스트 결과와 변경 경계 증거

- [ ] **Step 1: ROS 패키지 clean build**

Run: `source /opt/ros/jazzy/setup.bash && source /home/syw/rmf_ws/install/setup.bash && colcon build --packages-select trihouse_interfaces trihouse_rmf_bridge --cmake-clean-cache`

Expected: 두 패키지 모두 성공하고 bridge가 RMF C++ library에 링크된다.

- [ ] **Step 2: bridge 전체 테스트와 결과 조회**

Run: `source /opt/ros/jazzy/setup.bash && source /home/syw/rmf_ws/install/setup.bash && source install/setup.bash && colcon test --packages-select trihouse_rmf_bridge --event-handlers console_direct+ && colcon test-result --verbose`

Expected: C++ unit/state-store/office ROS integration 테스트가 모두 PASS이고 failure 0이다.

- [ ] **Step 3: 기존 Python 회귀 테스트**

Run: `python3 -m pytest control_tower/tests trihouse_interfaces/test trihouse_pinky/trihouse_pinky_fleet/test -q`

Expected: 기존 테스트와 새 Control Tower client/CLI 테스트가 모두 PASS한다.

- [ ] **Step 4: 금지 디렉터리 변경 여부 확인**

Run: `git status --short -- pinky_pro control_system && git diff -- pinky_pro control_system`

Expected: 이번 구현으로 생성된 diff가 없다. 기존 dirty 항목이 표시되면 사전 상태와 대조하고 staging하지 않는다.

- [ ] **Step 5: 구현 변경 최종 확인**

Run: `git status --short && git log --oneline -7`

Expected: 계획된 파일만 변경되었고 Task 1–5의 작은 커밋과 설계 커밋 `38d46c59`가 보인다.

- [ ] **Step 6: 검증 중 필요한 최소 수정이 있었다면 별도 커밋**

```bash
git add trihouse_rmf_bridge control_tower/rmf_adapter control_tower/tests docs/guideline/open_rmf_energy_bridge_test.md
git commit -m "test: verify RMF energy bridge integration"
```

변경이 없으면 빈 커밋을 만들지 않는다.
