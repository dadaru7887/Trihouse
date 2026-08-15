# Trihouse Control Tower Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Copy the current `control_system` into `control_ui` and integrate canonical MySQL, product-only order planning, two-Pinky Nav2/Open-RMF simulation, two OMX handover adapters, six camera feeds, and operator completion into one runnable control stack.

**Architecture:** Flutter calls only public FMS Gateway APIs. The Gateway remains the only MySQL writer and uses Control Tower domain policies for FEFO allocation, temperature-zone bundling, priority, partial fulfillment, ETA preparation, and Step advancement. Nav2 owns the driven path; Open-RMF receives an automatically generated scheduling trajectory, and no Lane editor is exposed.

**Tech Stack:** Flutter/Dart, Python 3.12, FastAPI/Pydantic, MySQL 8.4, ROS 2 Jazzy, Nav2, Open-RMF, Gazebo, MediaMTX, pytest, flutter_test, Docker Compose.

## Global Constraints

- Copy `control_system` commit `5b4cafe65e257fd070fec925a1c8251315b005de` into `control_ui/`; exclude nested Git metadata and build caches.
- `db/schema_mysql.sql` is the only operational schema; only FMS Gateway writes MySQL.
- SLAM `map` frame is the only runtime coordinate system; Floor plans are measurement aids only.
- No user-authored Lane or transit graph. Nav2 computes every actual navigate path.
- Visit one mobile Loading Dock per non-empty zone in ambient, chilled, frozen, packing order.
- UI `긴급` maps to DB `critical`; never interrupt active transport mid-Step.
- Partial fulfillment requires `allow_partial_fulfillment=true`.
- Pinky may enter the Dock first, but load starts only after same-revision `PINKY_READY` and `OMX_READY`.
- Inventory finalizes only after the UI `작업 완료` request succeeds idempotently.
- Every attempt stores criteria, observations, metrics, evidence, outcome, policy, and model lineage in `job_step_attempts`.
- Camera inventory is fixed at two fixed, two OMX wrist, and two Pinky streams.
- QR/ArUco OpenCV runs on the 4060 PC; VLM remains on the remote 5080 server.
- Throughput and retention stay `UNMEASURED` until hardware outputs and a six-stream soak artifact exist.
- 2026-08-16 required gate: two Pinky order simulation; two OMX simulation adapters are included.
- 2026-08-17 gate: UI, Control Tower, Gateway, MySQL, Open-RMF, Nav2/Gazebo, and MediaMTX run together.

---

### Task 1: Copy A into the Product `control_ui` Directory

**Files:**
- Create: `control_ui/**`
- Create: `control_ui/UPSTREAM_CONTROL_SYSTEM_COMMIT`
- Test: `tools/test_control_ui_copy.py`

**Interfaces:**
- Consumes: clean `control_system/` source at the recorded commit.
- Produces: root-owned `control_ui/` source with no nested repository or cache ownership.

- [ ] **Step 1: Write the failing provenance test**

```python
from pathlib import Path


def test_control_ui_copy_has_provenance_and_no_nested_repository():
    copied = Path(__file__).resolve().parents[1] / "control_ui"
    assert (copied / "UPSTREAM_CONTROL_SYSTEM_COMMIT").read_text().strip() == (
        "5b4cafe65e257fd070fec925a1c8251315b005de"
    )
    assert not (copied / ".git").exists()
    assert (copied / "rmf_control_ui" / "pubspec.yaml").is_file()
```

- [ ] **Step 2: Verify RED**

Run: `pytest -q tools/test_control_ui_copy.py`

Expected: FAIL because `control_ui` does not exist.

- [ ] **Step 3: Copy only source state**

Run:

```bash
rsync -a --exclude '.git/' --exclude '.dart_tool/' --exclude 'build/' \
  --exclude '__pycache__/' control_system/ control_ui/
```

Create `control_ui/UPSTREAM_CONTROL_SYSTEM_COMMIT` containing the exact 40-character commit above. Keep internal Flutter package names unchanged for upstream comparison.

- [ ] **Step 4: Verify GREEN and A regression**

Run:

```bash
pytest -q tools/test_control_ui_copy.py
cd control_ui/rmf_control_ui && flutter test
```

Expected: PASS with the copied A test result unchanged.

- [ ] **Step 5: Commit**

```bash
git add control_ui tools/test_control_ui_copy.py
git commit -m "chore: copy control system into control ui"
```

### Task 2: Add Immutable Map Sources, Polygon Types, Docks, Cameras, and Orders

**Files:**
- Modify: `db/schema_mysql.sql`
- Modify: `db/seed_dev.sql`
- Create: `db/tests/test_control_tower_schema.py`
- Modify: `fms_gateway/tests/integration/test_schema.py`
- Create: `tests/fixtures/simulation_map_publish.json`
- Create: `tests/fixtures/demo_orders.json`

**Interfaces:**
- Consumes: existing `map_revisions`, `map_features`, `locations`, and inventory seed.
- Produces: `map_revision_sources`; unified operational Polygon types; five destination poses; six camera features; six independent seed-order examples.

- [ ] **Step 1: Write failing schema tests**

```python
def test_revision_sources_are_keyed_by_revision_and_type(mysql_db):
    key_rows = mysql_db.all(
        "SELECT column_name FROM information_schema.key_column_usage "
        "WHERE table_schema='trihouse_fms' AND table_name='map_revision_sources' "
        "AND constraint_name='PRIMARY' ORDER BY ordinal_position"
    )
    columns = mysql_db.all(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='trihouse_fms' AND table_name='map_revision_sources'"
    )
    assert [row["column_name"] for row in key_rows] == ["map_revision", "source_type"]
    assert {"content_bytes", "sha256", "byte_size", "metadata"} <= {
        row["column_name"] for row in columns
    }


def test_feature_check_supports_uniform_geometry_and_cameras(mysql_db):
    clause = mysql_db.one(
        "SELECT check_clause FROM information_schema.check_constraints "
        "WHERE constraint_schema='trihouse_fms' AND constraint_name='chk_map_features_type'"
    )["check_clause"]
    assert all(f"'{value}'" in clause for value in (
        "facility_footprint", "safety_zone", "speed_zone", "camera"
    ))


def test_seed_has_all_mobile_destinations(mysql_db):
    codes = {
        row["location_code"] for row in mysql_db.all(
            "SELECT location_code FROM locations "
            "WHERE location_code LIKE '%-DOCK-01' OR location_code='PROJECT1-WAIT-01'"
        )
    }
    assert {"WH-AMB-01-DOCK-01", "WH-CHL-01-DOCK-01", "WH-FRZ-01-DOCK-01", "PACKING-01-DOCK-01", "PROJECT1-WAIT-01"} <= codes
```

- [ ] **Step 2: Verify RED**

Run: `pytest -q db/tests/test_control_tower_schema.py`

Expected: FAIL because the source table and new types do not exist.

- [ ] **Step 3: Add the one minimal source table**

```sql
CREATE TABLE IF NOT EXISTS map_revision_sources (
  map_revision VARCHAR(160) NOT NULL,
  source_type VARCHAR(24) NOT NULL,
  file_name VARCHAR(255) NOT NULL,
  mime_type VARCHAR(128) NOT NULL,
  content_bytes LONGBLOB NOT NULL,
  sha256 CHAR(64) NOT NULL,
  byte_size BIGINT UNSIGNED NOT NULL,
  metadata JSON NULL,
  PRIMARY KEY (map_revision, source_type),
  CONSTRAINT fk_map_revision_sources_revision FOREIGN KEY (map_revision)
    REFERENCES map_revisions (map_revision) ON DELETE CASCADE,
  CONSTRAINT chk_map_revision_sources_type CHECK (source_type IN
    ('slam_yaml','slam_image','floor_plan','facility_import')),
  CONSTRAINT chk_map_revision_sources_hash CHECK
    (sha256 REGEXP '^[0-9a-f]{64}$' AND byte_size > 0)
) ENGINE=InnoDB;
```

Extend `chk_map_features_type` with `facility_footprint`, `safety_zone`, `speed_zone`, and `camera`. Leave `map_project_lanes` unused in this first DDL change.
Add `map_revision_sources` to `FMS_TABLES` in the schema integration test so unexpected missing or extra tables still fail.

- [ ] **Step 4: Add deterministic runtime fixtures**

Add idempotent SLAM pose/yaw rows for the five destination codes. Put camera features `CAM-FIXED-01/02`, `CAM-OMX-01/02`, and `CAM-PK-01/02` into the published-map fixture with roles and MediaMTX paths. Put design Orders A-F into `demo_orders.json`, including critical D, opt-in partial E, and one-Dock ambient bundle F. Each order is run from a fresh seed.

- [ ] **Step 5: Verify GREEN**

Run: `pytest -q db/tests fms_gateway/tests/integration/test_schema.py`

Expected: PASS for a fresh schema and twice-applied seed.

- [ ] **Step 6: Commit**

```bash
git add db tests/fixtures
git commit -m "feat: add canonical map and demo fixtures"
```

### Task 3: Plan and Persist Product-Only Outbound Orders

**Files:**
- Modify: `control_tower/fleet_manager/order_intake.py`
- Create: `control_tower/task_manager/outbound_planner.py`
- Modify: `control_tower/task_manager/outbound_sequence.py`
- Modify: `control_tower/tests/test_order_intake.py`
- Create: `control_tower/tests/test_outbound_planner.py`
- Modify: `fms_gateway/app/models.py`
- Modify: `fms_gateway/app/main.py`
- Modify: `fms_gateway/app/repositories.py`
- Create: `fms_gateway/tests/unit/test_outbound_order_api.py`
- Create: `fms_gateway/tests/integration/test_outbound_order_repository.py`

**Interfaces:**
- Consumes: product/quantity, priority, partial flag, inventory lots, parent zones, and one Dock per zone.
- Produces: `POST /api/v1/orders`; FEFO reservations; confirmed/outstanding lines; one `ZoneBundle` per non-empty temperature zone; canonical Job/Items/Steps.

- [ ] **Step 1: Write failing policy and API tests**

```python
def test_two_items_in_one_zone_make_one_mobile_visit(planner, inventory, docks):
    plan = planner.plan(order("SKU-ORANGE", "SKU-MANDARIN"), inventory, docks)
    assert len(plan.bundles) == 1
    assert plan.bundles[0].dock_code == "WH-AMB-01-DOCK-01"
    assert [item.product_code for item in plan.bundles[0].items] == ["SKU-ORANGE", "SKU-MANDARIN"]


def test_partial_order_keeps_literal_outstanding_quantity(planner, inventory, docks):
    plan = planner.plan(partial_order("SKU-SANDWICH", 3), inventory, docks)
    assert plan.confirmed[0].quantity == 2
    assert plan.outstanding[0].quantity == 1


def test_order_api_does_not_accept_waypoint_or_robot_fields(client):
    response = client.post("/api/v1/orders", headers={"Idempotency-Key": "demo-a"}, json=order_a())
    assert response.status_code == 201
    assert [row["temperature_zone"] for row in response.json()["bundles"]] == ["ambient", "chilled", "frozen"]
```

- [ ] **Step 2: Verify RED**

Run: `pytest -q control_tower/tests/test_order_intake.py control_tower/tests/test_outbound_planner.py fms_gateway/tests/unit/test_outbound_order_api.py`

Expected: FAIL because outstanding quantities, bundles, and the public route are missing.

- [ ] **Step 3: Implement pure planning types**

```python
@dataclass(frozen=True)
class PlannedItem:
    product_code: str
    lot_id: int
    slot_location_id: int
    quantity: int

@dataclass(frozen=True)
class ZoneBundle:
    temperature_zone: str
    dock_location_id: int
    dock_code: str
    items: tuple[PlannedItem, ...]

@dataclass(frozen=True)
class OutboundPlan:
    order_id: str
    priority: str
    confirmed: tuple[RequestedItem, ...]
    outstanding: tuple[RequestedItem, ...]
    bundles: tuple[ZoneBundle, ...]
    packing_location_id: int
```

Select lots FEFO, group with `ambient=0, chilled=1, frozen=2`, and never use Nav2 cost to reorder shelves inside one bundle.

- [ ] **Step 4: Generate and persist the ordered Steps**

For each bundle emit OMX `prepare/pick`, Pinky `navigate` to the bundle Dock, and dual-role `load`; append packing `navigate`, `unload/handover`, operator `wait`, and `return_home`. The Gateway transaction locks lots, inserts Job/Items/Steps, increments reservations, and writes an operation event. A non-opt-in shortage rolls back all work. A critical request writes `jobs.priority='critical'` and `context.urgent=true`; existing `reorder_unsubmitted()` keeps in-use work fixed.

- [ ] **Step 5: Add strict request models and errors**

`OutboundOrderRequest` contains only external reference, canonical priority, `allow_partial_fulfillment`, requester, and at least one `{product_code, quantity>=1}`. Map no stock to `409 OUT_OF_STOCK`, full-only shortage to `409 INSUFFICIENT_STOCK`, and mismatched repeated idempotency keys to `409 IDEMPOTENCY_CONFLICT`.

- [ ] **Step 6: Verify GREEN**

Run: `pytest -q control_tower/tests fms_gateway/tests/unit/test_outbound_order_api.py fms_gateway/tests/integration/test_outbound_order_repository.py`

Expected: PASS for Orders A-F and two concurrent queued orders.

- [ ] **Step 7: Commit**

```bash
git add control_tower fms_gateway
git commit -m "feat: plan canonical outbound orders"
```

### Task 4: Coordinate ETA, Both-Robot Readiness, Step Attempts, and Worker Completion

**Files:**
- Modify: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/eta.py`
- Modify: `control_tower/task_manager/handover_gate.py`
- Create: `control_tower/task_manager/zone_handover.py`
- Modify: `control_tower/task_manager/task_orchestrator.py`
- Create: `control_tower/database/repositories/mysql_execution_repository.py`
- Modify: `fms_gateway/app/models.py`
- Modify: `fms_gateway/app/main.py`
- Modify: `fms_gateway/app/repositories.py`
- Create: `control_tower/tests/test_zone_handover.py`
- Create: `control_tower/tests/test_mysql_execution_repository.py`
- Create: `fms_gateway/tests/unit/test_step_attempt_api.py`
- Create: `fms_gateway/tests/unit/test_worker_completion_api.py`

**Interfaces:**
- Consumes: Nav2 path length/ETA, grasp duration, matching readiness facts, structured execution facts, and operator completion.
- Produces: `prepare_at`, one `START_LOAD`, append-only attempt rows, and idempotent final inventory transaction.

- [ ] **Step 1: Write failing readiness and persistence tests**

```python
def test_pinky_can_arrive_first_but_load_waits_for_omx(handover):
    assert handover.record(pinky_ready(revision=3)).command is None
    assert handover.record(omx_ready(revision=3)).command.command_kind == "START_LOAD"


def test_stale_omx_ready_does_not_release_current_pinky(handover):
    assert handover.record(omx_ready(revision=2)).reason_code == "STALE_ASSIGNMENT"
    assert handover.record(pinky_ready(revision=3)).command is None


def test_attempt_persists_learning_evidence(repository, successful_fact):
    repository.record_execution(successful_fact.event, successful_fact.fact, successful_fact.outcome)
    row = repository.attempt(successful_fact.fact.command_uuid)
    assert row["criteria"][0]["code"] == "NAV2_GOAL_REACHED"
    assert row["metrics"]["path_length_m"] == 8.25
    assert row["evidence_refs"] == ["artifact://nav/segment-1"]
    assert row["policy_source"] == "nav2"
```

- [ ] **Step 2: Verify RED**

Run: `pytest -q control_tower/tests/test_zone_handover.py control_tower/tests/test_mysql_execution_repository.py fms_gateway/tests/unit/test_worker_completion_api.py`

Expected: FAIL because the orchestration wrapper, MySQL execution adapter, and completion route do not exist.

- [ ] **Step 3: Implement ETA and dual readiness**

Use existing `EtaEstimator.omx_command_at(arrival_at_s, grasp_s, prep_margin_s, now_s)` to dispatch OMX preparation. Wrap existing `HandoverGate` in `ZoneHandover.schedule()` and `ZoneHandover.record()`. Pinky readiness requires Dock arrival, stationary velocity, correct Job/Step, and basket load-safe. OMX readiness requires expected items held, handover pose, and safety clear. Generate `START_LOAD` once only when the existing Gate releases.

- [ ] **Step 4: Persist every attempt through Gateway**

Implement `POST /internal/v1/job-steps/{id}/attempts`. Store all `ExecutionFact` fields in `job_step_attempts`, link verified artifact URIs, and update the Step terminal projection in the same transaction. Missing required criteria produces `UNCLASSIFIED_RESULT`, never success. Repeated event/command UUIDs are idempotent replays.

- [ ] **Step 5: Implement UI-facing worker completion API**

Implement `POST /api/v1/jobs/{id}/worker-completion` with required `Idempotency-Key`. Lock the Job, Step, Items, and lots; require the packing wait Step; decrement available/reserved quantities once; succeed the wait Step; append the operator event. Replays return the first result. Premature requests return `409 JOB_NOT_READY_FOR_COMPLETION`.

- [ ] **Step 6: Verify GREEN**

Run: `pytest -q control_tower/tests fms_gateway/tests/unit/test_worker_completion_api.py fms_gateway/tests/unit/test_step_attempt_api.py fms_gateway/tests/integration/test_outbound_order_repository.py`

Expected: PASS, including Pinky-first, OMX-first, stale revision, incomplete observations, and duplicate completion.

- [ ] **Step 7: Commit**

```bash
git add control_tower trihouse_pinky/trihouse_pinky_fleet fms_gateway
git commit -m "feat: coordinate and record outbound execution"
```

### Task 5: Run Two Pinky and Two OMX Adapters on Nav2 Paths

**Files:**
- Create: `trihouse_rmf_bridge/launch/two_pinky_order_demo.launch.py`
- Modify: `trihouse_rmf_bridge/launch/control_system_rmf.launch.py`
- Modify: `trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_pinky_sim.launch.py`
- Modify: `trihouse_omx_adapter/trihouse_omx_adapter/gazebo_adapter_node.py`
- Create: `trihouse_rmf_bridge/test/test_two_pinky_order_demo_launch.py`
- Modify: `trihouse_omx_adapter/tests/test_gazebo_adapter_state.py`
- Create: `control_tower/tests/test_two_robot_demo_scenario.py`

**Interfaces:**
- Consumes: one Gazebo world/RMF schedule, `PK_01/PK_02`, `OMX_01/OMX_02`, and published pose/yaw destinations.
- Produces: namespaced Nav2 motion for two Pinky, one RMF scheduling owner, two readiness OMX adapters, and concurrent assignments.

- [ ] **Step 1: Write failing multi-robot tests**

```python
def test_launch_has_two_namespaces_and_one_rmf_core(launch_contract):
    assert launch_contract.robot_ids == ("PK_01", "PK_02")
    assert launch_contract.namespaces == ("pinky_01", "pinky_02")
    assert launch_contract.rmf_schedule_count == 1
    assert launch_contract.omx_ids == ("OMX_01", "OMX_02")


def test_concurrent_orders_receive_distinct_robots(demo_scheduler):
    first, second = demo_scheduler.submit_concurrently(order_a(), order_b())
    assert {first.mobile_id, second.mobile_id} == {"PK_01", "PK_02"}
```

- [ ] **Step 2: Verify RED**

Run: `pytest -q trihouse_rmf_bridge/test/test_two_pinky_order_demo_launch.py control_tower/tests/test_two_robot_demo_scenario.py`

Expected: FAIL because the wrapper is absent.

- [ ] **Step 3: Implement one-core, two-namespace launch**

Start Gazebo, map, RMF schedule, and dispatcher once. Start two Nav2/Pinky/Fleet Adapter groups with unique Gazebo names and `/pinky_01` or `/pinky_02` scan, odom, pose, navigate, path, costmap, status, and transport topics. Start OMX adapters with unique IDs, node names, `assignment_revision`, expected items, and configurable readiness delays.

- [ ] **Step 4: Use Nav2 actual path and non-editable RMF trajectory**

Call Nav2 `ComputePathToPose` for each navigate Step and execute via Nav2. Simplify returned poses only for RMF expected-trajectory updates. Store runtime JSON under `runtime/<map_revision>/<job_step_id>/rmf_trajectory.json`; never create `map_project_lanes` rows or an editable graph.

- [ ] **Step 5: Verify GREEN and smoke launch**

Run:

```bash
pytest -q trihouse_rmf_bridge/test trihouse_omx_adapter/tests control_tower/tests/test_two_robot_demo_scenario.py
ros2 launch trihouse_rmf_bridge two_pinky_order_demo.launch.py headless:=true
```

Expected: tests PASS and the launch exposes four unique device IDs without duplicate RMF ownership.

- [ ] **Step 6: Commit**

```bash
git add trihouse_rmf_bridge trihouse_pinky/trihouse_pinky_bringup trihouse_omx_adapter control_tower/tests/test_two_robot_demo_scenario.py
git commit -m "feat: launch two Pinky order simulation"
```

### Task 6: Expose Pinky Pro Nav2 Profiles and Order Controls in Control UI

**Files:**
- Create: `fms_gateway/app/nav2_profiles.py`
- Modify: `fms_gateway/app/models.py`
- Modify: `fms_gateway/app/main.py`
- Modify: `fms_gateway/app/repositories.py`
- Create: `fms_gateway/tests/unit/test_nav2_profile_api.py`
- Modify: `control_ui/rmf_control_ui/pubspec.yaml`
- Create: `control_ui/rmf_control_ui/lib/trihouse/api/fms_api_client.dart`
- Create: `control_ui/rmf_control_ui/lib/trihouse/features/orders/order_page.dart`
- Create: `control_ui/rmf_control_ui/lib/trihouse/features/orders/job_detail_page.dart`
- Create: `control_ui/rmf_control_ui/lib/trihouse/features/settings/nav2_profile_page.dart`
- Modify: `control_ui/rmf_control_ui/lib/main.dart`
- Create: `control_ui/rmf_control_ui/test/order_page_test.dart`
- Create: `control_ui/rmf_control_ui/test/worker_completion_test.dart`
- Create: `control_ui/rmf_control_ui/test/nav2_profile_page_test.dart`

**Interfaces:**
- Consumes: Pinky defaults from `pinky_pro/pinky_navigation/params/nav2_params.yaml` and `pinky_pro/pinky_bringup/config/pinky_params.yaml`; public order/Job/profile APIs.
- Produces: validated simulation/real profiles, product-only order form, partial/critical controls, timeline, and operator completion.

- [ ] **Step 1: Write failing API and Flutter tests**

```python
def test_nav2_profile_rejects_impossibly_small_footprint(client):
    response = client.put("/api/v1/maps/project1/nav2-profiles/simulation", json={
        "footprint": [[0.01,0.01],[0.01,-0.01],[-0.01,-0.01],[-0.01,0.01]],
        "wheel_radius_m": 0.027, "wheel_separation_m": 0.0961,
        "inflation_radius_m": 0.15
    })
    assert response.status_code == 422
```

```dart
testWidgets('order form never asks for waypoint or robot', (tester) async {
  final api = RecordingFmsApi();
  await tester.pumpWidget(MaterialApp(home: OrderPage(api: api)));
  expect(find.textContaining('Waypoint'), findsNothing);
  expect(find.textContaining('로봇 선택'), findsNothing);
  expect(find.text('부분 출고 허용'), findsOneWidget);
  expect(find.text('긴급'), findsOneWidget);
});

testWidgets('completion enables only at packing wait', (tester) async {
  await tester.pumpWidget(MaterialApp(home: JobDetailPage(api: readyApi(), jobId: 7)));
  await tester.pumpAndSettle();
  expect(tester.widget<ElevatedButton>(find.widgetWithText(ElevatedButton, '작업 완료')).onPressed, isNotNull);
});
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest -q fms_gateway/tests/unit/test_nav2_profile_api.py
cd control_ui/rmf_control_ui && flutter test test/order_page_test.dart test/worker_completion_test.dart test/nav2_profile_page_test.dart
```

Expected: missing routes/pages fail.

- [ ] **Step 3: Implement profile validation and generation**

Cover current footprint/padding, resolution, inflation, obstacle/raytrace range, velocities/accelerations, tolerances, planner/controller, topics, timeouts, wheel radius `0.027`, and separation `0.0961`. Store under `map_project_fleets.settings.nav2_profiles`, hash canonical JSON into the map revision manifest, generate revision YAML, and pass it as Nav2 `params_file`. Never overwrite Pinky source YAML.

- [ ] **Step 4: Implement a web-safe Gateway client and focused pages**

Add `http` to Flutter dependencies. No new Trihouse UI file may import `dart:io`, MySQL, ROS, or `/internal/v1`. Order UI lists DB inventory and sends only product/quantity, priority, partial flag, requester, and external reference. Show confirmed/outstanding quantities. Job detail renders Steps/attempts; `작업 완료` generates one UUID key, disables in flight, and displays success only after HTTP 200.

- [ ] **Step 5: Wire pages minimally into A's shell**

Keep A theme/navigation and change only selected tab routing in `main.dart`. Put new behavior in focused `lib/trihouse/` files instead of expanding the existing large file.

- [ ] **Step 6: Verify GREEN**

Run:

```bash
pytest -q fms_gateway/tests/unit/test_nav2_profile_api.py
cd control_ui/rmf_control_ui && flutter test && flutter analyze
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add fms_gateway control_ui/rmf_control_ui trihouse_rmf_bridge
git commit -m "feat: add orders and Nav2 profiles to control ui"
```

### Task 7: Implement SLAM/Polygon Editing and Live Six-Camera Operations

**Files:**
- Create: `control_ui/rmf_control_ui/lib/trihouse/features/maps/slam_editor_page.dart`
- Create: `control_ui/rmf_control_ui/lib/trihouse/features/maps/polygon_editor.dart`
- Create: `control_ui/rmf_control_ui/lib/trihouse/features/operations/operations_page.dart`
- Create: `control_ui/rmf_control_ui/lib/trihouse/features/operations/camera_player.dart`
- Modify: `control_ui/rmf_control_ui/lib/main.dart`
- Create: `control_ui/rmf_control_ui/test/slam_editor_page_test.dart`
- Create: `control_ui/rmf_control_ui/test/operations_page_test.dart`
- Modify: `fms_gateway/app/models.py`
- Modify: `fms_gateway/app/main.py`
- Modify: `fms_gateway/app/repositories.py`
- Create: `fms_gateway/tests/unit/test_atomic_map_deployment_api.py`

**Interfaces:**
- Consumes: SLAM YAML/image, optional measurement/import sources, session edits, operation WebSocket, and MediaMTX playback URLs.
- Produces: Point/Polygon/measurement editor with no Lane; atomic publish; live robot/path/costmap/RMF layers; six camera status cards with selective decoding.

- [ ] **Step 1: Write failing UI and deployment tests**

```dart
testWidgets('SLAM editor exposes no lane authoring', (tester) async {
  await tester.pumpWidget(const MaterialApp(home: SlamEditorPage()));
  expect(find.text('Lane 추가'), findsNothing);
  expect(find.text('Waypoint'), findsOneWidget);
  expect(find.text('Polygon'), findsOneWidget);
  expect(find.text('길이 측정'), findsOneWidget);
});

testWidgets('only selected and incident cameras decode', (tester) async {
  final feed = FakeOperationsFeed.withSixCameras();
  await tester.pumpWidget(MaterialApp(home: OperationsPage(feed: feed)));
  await tester.tap(find.text('CAM-PK-01'));
  feed.emitPersonDown(cameraId: 'CAM-FIXED-02');
  await tester.pump();
  expect(feed.openedStreams, ['pinky_01', 'fixed_02']);
});
```

```python
def test_failed_first_publish_leaves_no_project_or_revision(client, repository):
    response = client.post("/api/v1/map-deployments", files=invalid_slam_bundle())
    assert response.status_code == 422
    assert repository.project_named("warehouse_01") is None
```

- [ ] **Step 2: Verify RED**

Run: `pytest -q fms_gateway/tests/unit/test_atomic_map_deployment_api.py && cd control_ui/rmf_control_ui && flutter test test/slam_editor_page_test.dart test/operations_page_test.dart`

Expected: missing public deployment/page behavior fails.

- [ ] **Step 3: Implement session-only SLAM editor**

Keep drafts in controller memory. Require Nav2 YAML + PGM/PNG; support optional Floor plan, a line with entered real meters, facility CSV/JSON, robot-current-pose import, Waypoint `(x,y,yaw)`, and GeoJSON Polygon. Rectangle is only a Polygon gesture preset. Leaving the page sends no request.

- [ ] **Step 4: Implement compensating atomic publish**

One multipart request contains all sources, Waypoints, Polygon features, cameras, and profile hash. Stage and validate all runtime output, write canonical rows in one DB transaction, atomically activate runtime, and remove both runtime and new rows on any failure. Same-name retry must succeed after failed first publish.

- [ ] **Step 5: Implement live layers and camera behavior**

Render SLAM, facilities/zones, robot pose/yaw/footprint, Nav2 global/local path, trail, costmaps, goal, bottleneck reservation, RMF expected trajectory/conflict/delay, and camera/incident markers. Register all six camera statuses; decode only selected and incident streams. Emergency actions remain exactly `비상경보 발령` and `작업 계속 진행`.

- [ ] **Step 6: Verify GREEN**

Run: `pytest -q fms_gateway/tests/unit/test_atomic_map_deployment_api.py && cd control_ui/rmf_control_ui && flutter test && flutter analyze`

Expected: PASS with no persisted editor draft or Lane action.

- [ ] **Step 7: Commit**

```bash
git add control_ui/rmf_control_ui fms_gateway
git commit -m "feat: add SLAM authoring and live operations"
```

### Task 8: Add Low-Load Media Fixtures and Mandatory Hardware Measurement

**Files:**
- Modify: `compose.edge_4060.yaml`
- Create: `media/recording_catalog/catalog.py`
- Create: `media/qr_worker/worker.py`
- Create: `config/cameras.simulation.yaml`
- Create: `scripts/measure_control_hosts.sh`
- Create: `scripts/camera_soak_test.py`
- Create: `tests/test_media_profile.py`
- Create: `tests/test_measurement_gate.py`

**Interfaces:**
- Consumes: six MediaMTX paths, 4060 OpenCV, Gateway artifact/event APIs, and 5080 health/model version.
- Produces: six registered fixture feeds, two active 720p/5 FPS local decoders, recording catalog, and an explicit `UNMEASURED|MEASURED` capability report.

- [ ] **Step 1: Write failing media/gate tests**

```python
def test_simulation_profile_registers_six_but_decodes_two():
    cameras = load_camera_profile("config/cameras.simulation.yaml")
    assert [c.id for c in cameras] == ["CAM-FIXED-01", "CAM-FIXED-02", "CAM-OMX-01", "CAM-OMX-02", "CAM-PK-01", "CAM-PK-02"]
    assert sum(c.decode for c in cameras) == 2
    assert all((c.width, c.height, c.analysis_fps) == (1280, 720, 5) for c in cameras if c.decode)


def test_missing_hardware_artifacts_force_unmeasured(tmp_path):
    report = evaluate_measurements(tmp_path)
    assert report.status == "UNMEASURED"
    assert set(report.missing) == {"nvidia_smi.txt", "free.txt", "lsblk.txt", "df.txt", "camera_soak.json"}
```

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/test_media_profile.py tests/test_measurement_gate.py`

Expected: missing profile/evaluator fails.

- [ ] **Step 3: Implement laptop-safe fixtures and edge services**

Register all six fixture IDs, but decode only `CAM-FIXED-01` and `CAM-PK-01` at 1280x720 and 5 analysis FPS on the current Intel laptop. Other feeds expose health and prerecorded incidents. On 4060, QR worker processes configured streams with OpenCV rate limits. Recording catalog hashes completed fMP4 segments and POSTs artifact metadata with camera, codec, dimensions, Job/Step/incident, and time range.

- [ ] **Step 4: Implement mandatory measurement output**

`measure_control_hosts.sh <dir>` captures exact `nvidia-smi --query-gpu=name,memory.total,driver_version,power.limit --format=csv`, `free -h`, `lsblk -o NAME,MODEL,TRAN,SIZE,FSTYPE,MOUNTPOINTS`, and `df -h`. `camera_soak_test.py` measures all six streams for at least 1800 seconds: codec, resolution, source/decoded FPS, bitrate, QR/ArUco latency, drops, CPU, GPU, RAM, and bytes. Calculate retention only from measured aggregate bytes/sec and writable bytes.

- [ ] **Step 5: Verify GREEN with a short fixture smoke**

Run:

```bash
pytest -q tests/test_media_profile.py tests/test_measurement_gate.py
python scripts/camera_soak_test.py --profile config/cameras.simulation.yaml --duration 10 --output /tmp/trihouse-camera-soak.json
```

Expected: tests PASS; production remains `UNMEASURED` because the ten-second local fixture is not the required hardware soak.

- [ ] **Step 6: Commit**

```bash
git add compose.edge_4060.yaml media config scripts/measure_control_hosts.sh scripts/camera_soak_test.py tests/test_media_profile.py tests/test_measurement_gate.py
git commit -m "feat: integrate six camera media profile"
```

### Task 9: Deliver One-Command Startup and August 16/17 Gates

**Files:**
- Create: `scripts/control_stack`
- Modify: `compose.yaml`
- Modify: `compose.control.yaml`
- Modify: `compose.simulation.yaml`
- Modify: `compose.edge_4060.yaml`
- Create: `tests/test_control_stack_cli.py`
- Create: `tests/e2e/test_six_demo_orders.py`
- Create: `docs/validation/2026-08-16-two-pinky-simulation.md`
- Create: `docs/validation/2026-08-17-integrated-control-stack.md`

**Interfaces:**
- Consumes: all previous deliverables.
- Produces: `up/status/logs/down/doctor`, two-Pinky simulation evidence on August 16, and integrated evidence on August 17.

In `tests/test_control_stack_cli.py`, define `run_control_stack` as a fixture that invokes
`scripts/control_stack` with `subprocess.run(..., text=True, capture_output=True, check=False)`.
Define `parse_checks()` to parse the command's JSON `checks` object and `compose_project()` to
return its JSON `project` field; the CLI's machine-readable output is therefore part of the tested contract.

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_doctor_lists_every_required_simulation_service(run_control_stack):
    checks = parse_checks(run_control_stack("doctor", "--mode", "simulation").stdout)
    assert set(checks) >= {"mysql", "fms_gateway", "control_tower", "mediamtx", "rmf_schedule", "gazebo", "nav2:PK_01", "nav2:PK_02", "omx:OMX_01", "omx:OMX_02", "control_ui"}


def test_up_and_down_use_one_compose_project(run_control_stack):
    assert compose_project(run_control_stack("render", "--mode", "simulation").stdout) == "trihouse_control_stack"
    assert compose_project(run_control_stack("render-down", "--mode", "simulation").stdout) == "trihouse_control_stack"
```

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/test_control_stack_cli.py`

Expected: FAIL because `scripts/control_stack` is absent.

- [ ] **Step 3: Implement exact lifecycle commands**

```bash
./scripts/control_stack up --mode simulation --project project1
./scripts/control_stack status
./scripts/control_stack logs
./scripts/control_stack down
./scripts/control_stack doctor --mode simulation
```

Start MySQL, Gateway, Control Tower workers, MediaMTX/catalog, RMF API/schedule/dispatcher, Fleet Adapters, Gazebo headless, two Nav2 stacks, two OMX adapters, and Flutter Web. Do not start `compose.ai_5080.yaml`; check only remote health/model version.

- [ ] **Step 4: Implement six fresh-seed E2E orders**

Recreate schema/seed and publish the simulation map before each A-F example. Assert zone order, skipped empty zones, rejected insufficient stock, critical ordering, partial outstanding quantity, same-zone single Dock, Step attempts, UI-style worker completion, and return home. Submit A and B concurrently and require distinct Pinky assignments plus Nav2 paths and RMF trajectory updates.

- [ ] **Step 5: Execute the 2026-08-16 simulation gate**

```bash
./scripts/control_stack up --mode simulation --project project1
pytest -q tests/e2e/test_six_demo_orders.py
./scripts/control_stack doctor --mode simulation
./scripts/control_stack down
```

Record exact commit, commands, pass/fail counts, PK_01/PK_02 paths, OMX_01/OMX_02 readiness/load events, screenshots, and artifact/log URIs in the August 16 validation document.

- [ ] **Step 6: Execute the 2026-08-17 integration gate**

Run the same stack with the 4060 edge profile. Verify all six statuses, selected/incident playback, Gateway-only writes, remote 5080 health/model version, emergency decisions, and worker completion. If required hardware outputs or 30-minute six-stream soak are absent, record `UNMEASURED` and publish no throughput or retention number.

- [ ] **Step 7: Run full regression**

```bash
pytest -q db/tests fms_gateway/tests control_tower/tests trihouse_rmf_bridge/test trihouse_omx_adapter/tests trihouse_pinky/test tests
cd control_ui/rmf_control_ui && flutter test && flutter analyze
```

Expected: all suites PASS and validation documents contain command evidence.

- [ ] **Step 8: Commit**

```bash
git add scripts/control_stack compose.yaml compose.control.yaml compose.simulation.yaml compose.edge_4060.yaml tests docs/validation
git commit -m "feat: deliver integrated control stack demo"
```
