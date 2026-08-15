# Trihouse Control Tower P0 Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a P0 simulation stack in which `control_ui`, copied from the current `control_system`, accepts product-only orders, persists every operational datum in the canonical MySQL schema, and visibly drives two Pinky robots over Nav2-computed paths coordinated by Open-RMF, with two contract-level OMX simulators and event-driven camera/emergency fixtures.

**Architecture:** `control_ui` is a browser-only presentation layer and talks only to public FMS Gateway REST/WebSocket endpoints. Control Tower owns FEFO planning and the final Pinky/OMX/Packing Dock assignment; Nav2 computes the actual path, Open-RMF coordinates the assigned Pinky trajectories, and the local safety layer may always stop motion. `db/schema_mysql.sql` is the only operational schema, while binary map sources are stored in `map_project_sources` and video/model binaries remain external artifacts referenced from MySQL.

**Tech Stack:** Flutter/Dart, Python 3.12, FastAPI/Pydantic, MySQL 8.4, ROS 2 Jazzy, Nav2, Open-RMF EasyFullControl, Gazebo, OpenCV, MediaMTX, pytest, flutter_test, Docker Compose.

## Global Constraints

- The approved design is `docs/superpowers/specs/2026-08-15-control-system-trihouse-integration-design.md` at commit `8b2466b6`.
- Copy `control_system` commit `5b4cafe65e257fd070fec925a1c8251315b005de` in full to `control_ui/`; exclude only nested `.git` and build/cache artifacts.
- The copy and removal of UI-owned DB/migration/ROS/process/filesystem access are one inseparable P0 boundary change.
- `db/schema_mysql.sql` is the only operational schema, and only FMS Gateway writes MySQL.
- The P0 canonical project/map name is `trihouse_test_01`.
- `control_system_test/rmf_control_ui/data/import/trihouse_test_01_physical_features.jsonl` is the only P0 pose source. Do not invent or duplicate coordinates in fixtures, seed files, launch files, or tests.
- Dock stop poses and ArUco recognition poses are distinct records. Marker 0's frozen recognition pose must not replace the frozen Dock stop pose.
- Both bottlenecks have diameter `0.2m` and execution radius `0.1m`.
- Do not expose or persist user-authored Lane, Transit Waypoint, or manual bottleneck waiting points.
- Control Tower makes the final Pinky, OMX, and Packing Dock assignment. RMF must not substitute another Pinky.
- Nav2 `ComputePathToPose` runs before motion; the approved path is registered with RMF and executed with Nav2 `FollowPath`.
- `critical` changes queued Job ordering only; it does not interrupt active transport or alter bottleneck passage priority.
- Pinky may arrive before OMX, but loading starts only after same-assignment `PINKY_READY` and `OMX_READY`.
- `allow_partial_fulfillment` affects intake stock shortage only. Pick failure choices remain `재시도` and `포장대에서 처리`.
- Worker completion is an idempotent UI action and is the only point that finalizes inventory.
- P0 registers six camera fixtures but does not connect six physical cameras.
- `ACT_MODEL_REPO_ID`, revision, and profile default to `UNCONFIGURED`; P0 uses a deterministic fake policy and never emits actual OMX motion.
- 4060/5080 concurrency, storage mode, and retention remain `UNMEASURED` until the required commands and 30-minute six-stream soak run on the actual hosts.
- P1-only work—physical Pinky/OMX/camera connection, real ACT checkpoint motion, camera calibration, Floor measurement tools, Polygon authoring, generic facility CSV/JSON, and editable Nav2/costmap/robot forms—must not be pulled into P0.

## File and Boundary Map

- `control_ui/rmf_control_ui/lib/trihouse/api/`: public Gateway REST/WebSocket client only.
- `control_ui/rmf_control_ui/lib/trihouse/features/maps/`: P0 SLAM/source import, Draft save/delete/publish, and read-only feature display.
- `control_ui/rmf_control_ui/lib/trihouse/features/orders/`: product-only order and worker-completion screens.
- `control_ui/rmf_control_ui/lib/trihouse/features/operations/`: actual path, robot, reservation, camera, and incident presentation.
- `fms_gateway/app/`: public HTTP contracts, idempotency, MySQL transactions, and WebSocket projection.
- `control_tower/task_manager/`: pure order/assignment/readiness/emergency policies.
- `control_tower/rmf_adapter/`: assigned-robot path scheduling and RMF traffic contracts.
- `trihouse_rmf_bridge/`: ROS 2 adapter from assigned path contracts to Nav2/Open-RMF.
- `trihouse_omx_adapter/`: P0 OMX command simulator, OpenCV fixture perception, and fake ACT policy.
- `db/schema_mysql.sql`: complete fresh-deployment schema; migrations are not the deployment source.
- `scripts/control_stack`: one lifecycle command for the whole P0 stack.

---

### Task 1: Freeze the A Baseline and Copy It to `control_ui`

**Files:**
- Create: `tools/test_control_ui_copy.py`
- Create: `control_ui/UPSTREAM_CONTROL_SYSTEM_COMMIT`
- Create: `control_ui/**` by copying `control_system/**`
- Create: `docs/validation/2026-08-16-control-system-baseline.md`

**Interfaces:**
- Consumes: `control_system` at commit `5b4cafe65e257fd070fec925a1c8251315b005de` and its current Flutter tests.
- Produces: a provenance-locked `control_ui` tree whose test baseline is recorded before any boundary refactor.

- [ ] **Step 1: Write the failing copy/provenance test**

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_control_ui_is_full_source_copy_without_nested_git():
    target = ROOT / "control_ui"
    assert (target / "UPSTREAM_CONTROL_SYSTEM_COMMIT").read_text().strip() == (
        "5b4cafe65e257fd070fec925a1c8251315b005de"
    )
    assert not (target / ".git").exists()
    assert (target / "rmf_control_ui" / "lib" / "main.dart").is_file()
    assert (target / "rmf_control_ui" / "pubspec.yaml").is_file()
```

- [ ] **Step 2: Verify RED and capture A's baseline**

Run:

```bash
pytest -q tools/test_control_ui_copy.py
cd control_system/rmf_control_ui && flutter test
```

Expected: copy test FAIL because `control_ui` is absent; record the exact Flutter pass/fail count and existing failures in `docs/validation/2026-08-16-control-system-baseline.md`.

- [ ] **Step 3: Copy all source state**

Run:

```bash
rsync -a --exclude '.git/' --exclude '.dart_tool/' --exclude 'build/' \
  --exclude '__pycache__/' --exclude '.pytest_cache/' control_system/ control_ui/
```

Write the exact 40-character upstream commit to `control_ui/UPSTREAM_CONTROL_SYSTEM_COMMIT`. Do not rename the internal Flutter package in this task.

- [ ] **Step 4: Verify GREEN and copied baseline equivalence**

Run:

```bash
pytest -q tools/test_control_ui_copy.py
cd control_ui/rmf_control_ui && flutter test
```

Expected: copy test PASS; Flutter result matches the recorded A baseline exactly.

- [ ] **Step 5: Commit**

```bash
git add control_ui tools/test_control_ui_copy.py docs/validation/2026-08-16-control-system-baseline.md
git commit -m "chore: copy control system into control ui"
```

### Task 2: Enforce the Browser/Gateway Boundary Across the Copied UI

**Files:**
- Delete: `control_ui/db/**`
- Delete: `control_ui/rmf_control_ui/lib/*_io.dart` (all copied platform-backend implementations; pure model/parser files remain)
- Modify: `control_ui/rmf_control_ui/lib/main.dart`
- Create: `control_ui/rmf_control_ui/lib/trihouse/api/fms_api.dart`
- Create: `control_ui/rmf_control_ui/lib/trihouse/api/fms_api_client.dart`
- Create: `control_ui/rmf_control_ui/lib/trihouse/api/fms_models.dart`
- Create: `control_ui/rmf_control_ui/test/fms_api_client_test.dart`
- Create: `tools/test_control_ui_architecture.py`

**Interfaces:**
- Consumes: copied A presentation widgets and Gateway public `/api/v1/*` contracts.
- Produces: `FmsApi` as the only runtime backend abstraction used by Flutter pages.

- [ ] **Step 1: Write failing repository-wide architecture tests**

```python
from pathlib import Path


FORBIDDEN = ("dart:io", "package:mysql", "Process.run", "Process.start", "ServerSocket")


def test_control_ui_has_no_private_backend_or_direct_system_access():
    root = Path("control_ui/rmf_control_ui/lib")
    violations = []
    for path in root.rglob("*.dart"):
        text = path.read_text()
        for token in FORBIDDEN:
            if token in text:
                violations.append(f"{path}:{token}")
        if "/internal/v1/" in text:
            violations.append(f"{path}:/internal/v1/")
    assert violations == []
    assert not Path("control_ui/db").exists()
```

Add a Dart client test that asserts `FmsApiClient.listInventory()` calls `/api/v1/inventory/lots` and never an internal route.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest -q tools/test_control_ui_architecture.py
cd control_ui/rmf_control_ui && flutter test test/fms_api_client_test.dart
```

Expected: FAIL on copied IO/migration/process implementations and missing client.

- [ ] **Step 3: Define the public UI interface**

```dart
abstract interface class FmsApi {
  Future<List<InventoryLotDto>> listInventory();
  Future<List<MapProjectSummaryDto>> listMapProjects();
  Future<MapProjectOpenDto> openMapProject(String mapName);
  Future<StagedMapSourceDto> stageMapSource(String mapName, MapSourceUploadDto source);
  Future<MapProjectDraftDto> saveMapDraft(MapProjectDraftDto draft, {int? expectedRevision});
  Future<void> deleteMapDraft(String mapName);
  Future<MapValidationDto> validateMapDraft(String mapName);
  Future<PublishedMapDto> publishMapDraft(String mapName, PublishMapDto request);
  Future<OutboundOrderDto> createOutboundOrder(OutboundOrderRequestDto request, {required String idempotencyKey});
  Future<JobDetailDto> getJob(int jobId);
  Future<JobDetailDto> completeJob(int jobId, WorkerCompletionDto request, {required String idempotencyKey});
  Stream<OperationsEventDto> operationsEvents();
  Future<void> decideEmergency(int incidentId, EmergencyDecisionDto request, {required String idempotencyKey});
}
```

Define the DTOs in `fms_models.dart` with these stable fields:

- `MapProjectOpenDto`: `draft`, `openExisting`, `activeRevision`.
- `MapSourceUploadDto`: `sourceType`, `fileName`, `mimeType`, `Uint8List bytes`.
- `StagedMapSourceDto`: `uploadToken`, `sourceType`, `sha256`, `byteSize`; it is not a DB row.
- `MapSourceDto`: saved `sourceUuid`, `projectId`, `sourceType`, `sha256`, `byteSize`.
- `MapProjectDraftDto`: `mapName`, `formatVersion`, `draftRevision`, source UUID map,
  waypoint list, feature list, and runtime profile hash.
- `MapValidationDto`: `valid` and immutable error-code list.
- `PublishMapDto`: `expectedDraftRevision` and `publishedBy`; the server generates
  artifacts and hashes.
- `PublishedMapDto`: `mapName`, `mapRevision`, `draftRevision`, `manifest`.
- `OutboundOrderRequestDto`: external reference, requester, priority, partial flag,
  and product-code/quantity lines only.
- `WorkerCompletionDto`: worker ID, completion note, and acknowledged manual-item IDs.
- `EmergencyDecisionDto`: worker ID, `RAISE_ALARM|CONTINUE_WORK`, and reason.

`InventoryLotDto`, `OutboundOrderDto`, `JobDetailDto`, and `OperationsEventDto`
mirror the public Gateway response fields without embedding domain decisions in Flutter.

Implement `FmsApiClient` with browser-safe HTTP/WebSocket dependencies. Inject `FmsApi` into the app shell; remove `migrateDatabaseSchema()`, direct ROS/process launch, direct file persistence, telemetry sockets, and MySQL-backed store construction from `main.dart`.

- [ ] **Step 4: Remove obsolete backend implementations and convert tests**

Delete `control_ui/db`. Remove or replace IO-specific tests such as `database_migration_test.dart`, `map_project_store_test.dart`, `operations_log_test.dart`, and `task_store_test.dart` with Gateway-client/widget contract tests. Preserve pure geometry, styling, parsing, and presentation tests.

- [ ] **Step 5: Verify GREEN**

Run:

```bash
pytest -q tools/test_control_ui_architecture.py
cd control_ui/rmf_control_ui && flutter test && flutter analyze
```

Expected: architecture test PASS; the adjusted Flutter baseline has no direct backend dependency.

- [ ] **Step 6: Commit**

```bash
git add control_ui tools/test_control_ui_architecture.py
git commit -m "refactor: route control ui through fms gateway"
```

### Task 3: Add Immutable Project Sources and the Authoritative Physical-Feature Import

**Files:**
- Modify: `db/schema_mysql.sql`
- Modify: `db/seed_dev.sql`
- Modify: `control_system_test/rmf_control_ui/data/import/trihouse_test_01_physical_features.jsonl`
- Create: `fms_gateway/app/physical_features.py`
- Modify: `fms_gateway/app/models.py`
- Modify: `fms_gateway/app/repositories.py`
- Create: `db/tests/test_map_project_sources_schema.py`
- Create: `fms_gateway/tests/unit/test_physical_features.py`
- Modify: `fms_gateway/tests/integration/test_schema.py`

**Interfaces:**
- Consumes: the 13-line JSONL source.
- Produces: immutable `map_project_sources` rows and `PhysicalFeatureImport` with 8 waypoints, 2 bottlenecks, and 3 fiducial bindings.

- [ ] **Step 1: Write failing schema and importer tests**

```python
def test_physical_fixture_is_the_only_pose_source(importer, physical_jsonl):
    result = importer.parse(physical_jsonl)
    assert result.map_name == "trihouse_test_01"
    assert len(result.waypoints) == 8
    assert len(result.bottlenecks) == 2
    assert len(result.fiducials) == 3
    assert result.bottlenecks[0].radius_m == 0.1
    assert result.bottlenecks[0].source_diameter_m == 0.2
    assert result.waypoint("WH-FRZ-01-DOCK-01").pose != result.marker(0).recognition_pose


def test_source_table_is_project_scoped_and_immutable(mysql_db):
    columns = mysql_db.column_names("map_project_sources")
    assert {"source_uuid", "project_id", "source_type", "content_bytes", "sha256"} <= columns
    assert mysql_db.primary_key("map_project_sources") == ["source_uuid"]
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest -q db/tests/test_map_project_sources_schema.py fms_gateway/tests/unit/test_physical_features.py
```

Expected: FAIL because the table/importer and corrected diameter field do not exist.

- [ ] **Step 3: Add the single source table and constrained feature types**

Add this shape to `db/schema_mysql.sql`:

```sql
CREATE TABLE IF NOT EXISTS map_project_sources (
  source_uuid CHAR(36) NOT NULL,
  project_id BIGINT UNSIGNED NOT NULL,
  source_type VARCHAR(32) NOT NULL,
  file_name VARCHAR(255) NOT NULL,
  mime_type VARCHAR(128) NOT NULL,
  content_bytes LONGBLOB NOT NULL,
  sha256 CHAR(64) NOT NULL,
  byte_size BIGINT UNSIGNED NOT NULL,
  metadata JSON NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (source_uuid),
  KEY idx_map_project_sources_project (project_id, source_type, created_at),
  CONSTRAINT fk_map_project_sources_project FOREIGN KEY (project_id)
    REFERENCES map_projects(project_id) ON DELETE CASCADE,
  CONSTRAINT chk_map_project_sources_type CHECK (source_type IN
    ('slam_yaml','slam_image','floor_plan','physical_features_import')),
  CONSTRAINT chk_map_project_sources_hash CHECK
    (sha256 REGEXP '^[0-9a-f]{64}$' AND byte_size > 0)
) ENGINE=InnoDB;
```

Extend `map_features.feature_type` with `facility_footprint`, `safety_zone`, `speed_zone`, and `camera`; align `map_features.map_revision` to `VARCHAR(160)`. Keep `map_project_lanes` deprecated and unused. Do not add global SHA uniqueness. Do not create P0 camera Point rows because no camera map poses were measured.

- [ ] **Step 4: Correct diameter provenance without changing any pose**

In JSONL records 9 and 10, rename top-level and measurement provenance `source_radius_m: 0.2`/`radius_m: 0.2` to `source_diameter_m: 0.2`, and correct the Korean notes from “반경 20cm” to “지름 20cm, 반지름 10cm”. Leave top-level execution `radius_m: 0.1` and all coordinates unchanged. In `seed_dev.sql`, do not use `(2.0,2.0)` or `(2.5,2.0)` as `trihouse_test_01` runtime poses; initialize P0 robot poses from imported charger records at deployment/launch time.

- [ ] **Step 5: Implement strict JSONL parsing**

Define immutable `MapPose`, `WaypointFeature`, `BottleneckFeature`, `FiducialBinding`, and `PhysicalFeatureImport`. Reject duplicate business codes, non-finite values, unsupported records, a bottleneck where `radius_m != source_diameter_m / 2`, and any fixture count other than 8/2/3 for the canonical P0 file. Do not compare source/target/file names to the open project name.

- [ ] **Step 6: Verify GREEN**

Run:

```bash
jq -e -s 'length == 13' control_system_test/rmf_control_ui/data/import/trihouse_test_01_physical_features.jsonl
pytest -q db/tests/test_map_project_sources_schema.py fms_gateway/tests/unit/test_physical_features.py fms_gateway/tests/integration/test_schema.py
```

Expected: PASS; importer output is derived from the file and contains no fallback pose.

- [ ] **Step 7: Commit**

```bash
git add db fms_gateway control_system_test/rmf_control_ui/data/import/trihouse_test_01_physical_features.jsonl
git commit -m "feat: persist authoritative map project sources"
```

### Task 4: Implement Explicit Draft Save/Delete and Atomic Publish

**Files:**
- Create: `fms_gateway/app/map_deployment.py`
- Create: `fms_gateway/app/runtime_profiles.py`
- Modify: `fms_gateway/app/models.py`
- Modify: `fms_gateway/app/main.py`
- Modify: `fms_gateway/app/repositories.py`
- Modify: `fms_gateway/tests/unit/test_map_project_api.py`
- Modify: `fms_gateway/tests/integration/test_map_project_repository.py`
- Create: `fms_gateway/tests/unit/test_map_deployment.py`
- Create: `control_ui/rmf_control_ui/lib/trihouse/features/maps/map_project_page.dart`
- Create: `control_ui/rmf_control_ui/lib/trihouse/features/maps/physical_feature_layer.dart`
- Create: `control_ui/rmf_control_ui/lib/trihouse/features/settings/runtime_profile_panel.dart`
- Create: `control_ui/rmf_control_ui/test/map_project_page_test.dart`

**Interfaces:**
- Consumes: `FmsApi`, immutable source UUIDs, and `PhysicalFeatureImport`.
- Produces: public `/api/v1/map-projects/*` Draft APIs, staged publish, and a P0 read/edit surface with explicit Save/Delete/Publish.

- [ ] **Step 1: Write failing API and widget tests**

```python
def test_saved_draft_reopens_and_unsaved_edit_does_not_persist(client):
    saved = client.put("/api/v1/map-projects/trihouse_test_01", json=draft(), headers={"If-Match": "0"})
    assert saved.status_code == 200
    assert client.get("/api/v1/map-projects/trihouse_test_01").json()["draft_revision"] == 1


def test_same_name_active_opens_new_draft_revision(client, published_project):
    response = client.post("/api/v1/map-projects", json={"map_name": "trihouse_test_01"})
    assert response.status_code == 200
    assert response.json()["open_existing"] is True
    assert response.json()["active_revision"] == published_project.map_revision


def test_publish_failure_preserves_active_and_creates_no_failure_audit(client, active_map, repository):
    response = client.post("/api/v1/map-projects/trihouse_test_01/publish", json=invalid_publication())
    assert response.status_code == 422
    assert repository.active_revision("trihouse_test_01") == active_map.map_revision
    assert repository.deployment_failure_events("trihouse_test_01") == []


def test_same_jsonl_can_be_stored_by_two_projects(client, physical_jsonl):
    first = stage_and_save_source(client, "trihouse_test_01", physical_jsonl)
    second = stage_and_save_source(client, "another_project", physical_jsonl)
    assert first["source_uuid"] != second["source_uuid"]
    assert first["sha256"] == second["sha256"]
```

```dart
testWidgets('P0 map page has save delete publish and no lane tools', (tester) async {
  await tester.pumpWidget(testMapProjectPage());
  expect(find.text('저장'), findsOneWidget);
  expect(find.text('삭제'), findsOneWidget);
  expect(find.text('배포'), findsOneWidget);
  expect(find.textContaining('Lane'), findsNothing);
  expect(find.text('Polygon 추가'), findsNothing);
});

testWidgets('configuration tab is read-only in P0', (tester) async {
  await tester.pumpWidget(testMapProjectPage());
  await tester.tap(find.text('설정 파일'));
  await tester.pump();
  expect(find.text('pinky_pro simulation profile'), findsOneWidget);
  expect(find.byType(TextField), findsNothing);
});
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest -q fms_gateway/tests/unit/test_map_project_api.py fms_gateway/tests/unit/test_map_deployment.py
cd control_ui/rmf_control_ui && flutter test test/map_project_page_test.dart
```

Expected: FAIL because public APIs, source persistence, and the focused page are missing.

- [ ] **Step 3: Add public Draft/source contracts**

Add `POST /api/v1/map-projects`, `GET/PUT /api/v1/map-projects/{map_name}`, `POST /api/v1/map-projects/{map_name}/sources/stage`, `DELETE /api/v1/map-projects/{map_name}/draft`, `POST /api/v1/map-projects/{map_name}/validate`, and `POST /api/v1/map-projects/{map_name}/publish`. Keep `/internal/v1/*` for service workers only. Source staging returns an expiring upload token and writes only under runtime staging; it does not insert MySQL rows.

`PUT` uses `If-Match` and atomically promotes staged upload tokens to immutable `map_project_sources` rows, then saves payload/source UUID references/waypoints/features. Repeated Save with the same selected source reuses its UUID. If no Active revision exists, Delete removes the Draft and unreferenced source rows. If an Active revision exists, Delete restores a Draft view from the Active manifest and keeps the Active revision and referenced sources. Unsaved exit discards local edits and the startup/expiry reconciler removes unused staged uploads, so upload alone leaves no canonical DB record.

- [ ] **Step 4: Implement staged publish and crash reconciliation**

Define immutable `StagedDeployment(deployment_uuid, map_name, draft_revision,
staging_dir, manifest_path)`. `MapDeploymentCoordinator.stage(map_name,
draft_revision)` returns that value; `validate(staged)` returns an immutable
sequence of concrete validation error codes; `activate(staged, published_by)`
returns `PublishedMap`; `reconcile_startup()` returns the deployment UUIDs it
removed or restored.

Stage a manifest under `runtime/staging/<deployment_uuid>/manifest.json`; validate source hashes, exact P0 record set, generated runtime artifacts, and runtime preflight. Only `activate()` writes the immutable revision, canonical snapshot/hash, revision features, `locations` projection, and source UUID/hash manifest, retires the previous revision, and swaps the runtime active pointer. Validation failure returns 422 and logs server detail without inserting a permanent failure audit row.

- [ ] **Step 5: Build the P0 map page**

Support SLAM YAML/image and physical-feature JSONL upload, show the 8 waypoints/yaws, 2 radius-0.1 bottlenecks, and 3 marker recognition poses. Permit manual Waypoint point/yaw addition, but no Lane, Transit, Polygon, Floor measurement, or editable Nav2 settings. The `설정 파일` tab reads controller/planner, costmap, footprint, speed, tolerance, and wheel values from `pinky_pro/pinky_navigation/params/nav2_params.yaml` and `pinky_pro/pinky_bringup/config/pinky_params.yaml`, displays them read-only, and pins the canonical profile hash in the publish manifest. Warn on unsaved exit; only Save writes. File/project/source names never gate import compatibility.

- [ ] **Step 6: Verify GREEN**

Run:

```bash
pytest -q fms_gateway/tests/unit/test_map_project_api.py fms_gateway/tests/unit/test_map_deployment.py fms_gateway/tests/integration/test_map_project_repository.py
cd control_ui/rmf_control_ui && flutter test test/map_project_page_test.dart && flutter analyze
```

Expected: PASS for save/reopen/delete/same-name/publish-failure/active-preservation cases.

- [ ] **Step 7: Commit**

```bash
git add fms_gateway control_ui/rmf_control_ui
git commit -m "feat: add explicit map draft and publish workflow"
```

### Task 5: Add Product-Only Order Intake and FEFO Zone Planning

**Files:**
- Modify: `control_tower/fleet_manager/order_intake.py`
- Create: `control_tower/task_manager/outbound_planner.py`
- Modify: `control_tower/task_manager/outbound_sequence.py`
- Modify: `control_tower/task_manager/sequence_orchestrator.py`
- Modify: `fms_gateway/app/models.py`
- Modify: `fms_gateway/app/main.py`
- Modify: `fms_gateway/app/repositories.py`
- Create: `control_tower/tests/test_outbound_planner.py`
- Create: `fms_gateway/tests/unit/test_outbound_order_api.py`
- Create: `fms_gateway/tests/integration/test_outbound_order_repository.py`
- Create: `tests/fixtures/demo_orders.json`
- Create: `control_ui/rmf_control_ui/lib/trihouse/features/orders/order_page.dart`
- Create: `control_ui/rmf_control_ui/test/order_page_test.dart`

**Interfaces:**
- Consumes: product code/name, quantity, priority, `allow_partial_fulfillment`, inventory lots, and Active map locations.
- Produces: `POST /api/v1/orders`, FEFO lot reservations, zone bundles, and parallel OMX/Pinky branches converging at a handover gate.

- [ ] **Step 1: Write failing domain/API/UI tests**

```python
def test_full_only_shortage_creates_nothing(planner, repository):
    result = planner.plan(order("SKU-ORANGE", 2, allow_partial=False), repository.snapshot())
    assert result.reason_code == "INSUFFICIENT_STOCK"
    assert repository.jobs() == []
    assert repository.reservations() == []


def test_zone_order_and_single_visit(planner, inventory):
    plan = planner.plan(order_items("SKU-ORANGE", "SKU-MANDARIN", "SKU-MILK", "SKU-ICEBAR"), inventory)
    assert [bundle.temperature_zone for bundle in plan.bundles] == ["ambient", "chilled", "frozen"]
    assert [item.product_code for item in plan.bundles[0].items] == ["SKU-ORANGE", "SKU-MANDARIN"]
```

```dart
testWidgets('order page asks for products but not destinations or robots', (tester) async {
  await tester.pumpWidget(testOrderPage());
  expect(find.text('상품 추가'), findsOneWidget);
  expect(find.text('긴급'), findsOneWidget);
  expect(find.text('부분 출고 허용'), findsOneWidget);
  expect(find.textContaining('Waypoint 선택'), findsNothing);
  expect(find.textContaining('로봇 선택'), findsNothing);
});
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest -q control_tower/tests/test_outbound_planner.py fms_gateway/tests/unit/test_outbound_order_api.py
cd control_ui/rmf_control_ui && flutter test test/order_page_test.dart
```

Expected: FAIL on missing planner/public route/page.

- [ ] **Step 3: Define stable planning types**

```python
@dataclass(frozen=True)
class PlannedItem:
    product_code: str
    lot_id: int
    slot_location_id: int
    requested_qty: int
    reserved_qty: int


@dataclass(frozen=True)
class ZoneBundle:
    handover_group_id: str
    temperature_zone: str
    dock_location_id: int
    items: tuple[PlannedItem, ...]
```

Use FEFO lot ordering and fixed zone ordering `ambient`, `chilled`, `frozen`. A zone produces one Pinky Dock visit regardless of shelf count. Empty zones disappear.

- [ ] **Step 4: Persist order and parallel branch dependencies atomically**

`OutboundOrderRequest` accepts only external reference, requester, priority, partial flag, and item lines. For each bundle create OMX `prepare/pick` and Pinky `navigate` steps with the same `handover_group_id` and dependency JSON, then a readiness `load` convergence step. Append packing navigate/handover, worker wait, and return-home steps after Dock assignment. Lock FEFO lots and write Job/Items/Steps/reservations/idempotency event in one transaction.

- [ ] **Step 5: Add all six fresh-seed examples**

Put design Orders A-F in `tests/fixtures/demo_orders.json`: all zones, chilled/frozen with ambient skipped, full-order stock rejection, critical, opt-in partial, and two ambient products/one Dock. Every test resets schema and seed before submitting one example.

- [ ] **Step 6: Verify GREEN**

Run:

```bash
pytest -q control_tower/tests/test_order_intake.py control_tower/tests/test_outbound_planner.py fms_gateway/tests/unit/test_outbound_order_api.py fms_gateway/tests/integration/test_outbound_order_repository.py
cd control_ui/rmf_control_ui && flutter test test/order_page_test.dart
```

Expected: PASS; false+shortage creates no Job/Step/reservation and true+shortage records literal outstanding quantity.

- [ ] **Step 7: Commit**

```bash
git add control_tower fms_gateway control_ui/rmf_control_ui tests/fixtures/demo_orders.json
git commit -m "feat: plan product-only outbound orders"
```

### Task 6: Own Assignment, Readiness, Pick Recovery, Packing, and Completion

**Files:**
- Modify: `control_tower/fleet_manager/packing_station.py`
- Modify: `control_tower/task_manager/handover_gate.py`
- Modify: `control_tower/task_manager/omx_workflow.py`
- Modify: `control_tower/task_manager/pick_failure_report.py`
- Create: `control_tower/task_manager/assignment.py`
- Create: `control_tower/task_manager/zone_handover.py`
- Modify: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/eta.py`
- Modify: `fms_gateway/app/models.py`
- Modify: `fms_gateway/app/main.py`
- Modify: `fms_gateway/app/repositories.py`
- Create: `control_tower/tests/test_assignment.py`
- Create: `control_tower/tests/test_zone_handover.py`
- Create: `control_tower/tests/test_pick_recovery.py`
- Create: `fms_gateway/tests/unit/test_worker_completion_api.py`
- Create: `control_ui/rmf_control_ui/lib/trihouse/features/orders/job_detail_page.dart`
- Create: `control_ui/rmf_control_ui/test/worker_completion_test.dart`

**Interfaces:**
- Consumes: queued plan, device availability, Nav2 travel estimate, RMF delay, reservation availability, readiness facts, and operator decisions.
- Produces: immutable `AssignmentRevision`, `prepare_at`, one load release, item-level attempt outcomes, selected Packing Dock, and idempotent completion/charger return.

- [ ] **Step 1: Write failing assignment/readiness/recovery tests**

```python
def test_control_tower_assigns_every_resource_once(assigner):
    assignment = assigner.assign(job(), mobiles(), arms(), packing_docks())
    assert assignment.mobile_id in {"PK_01", "PK_02"}
    assert assignment.omx_id in {"OMX_01", "OMX_02"}
    assert assignment.packing_dock_code in {"PACKING-01-DOCK-01", "PACKING-01-DOCK-02"}


def test_loading_waits_for_both_same_revision(handover):
    assert handover.record(pinky_ready(revision=4)).released is False
    assert handover.record(omx_ready(revision=3)).reason_code == "STALE_ASSIGNMENT"
    assert handover.record(omx_ready(revision=4)).released is True


def test_drop_blocks_retry_and_pinky_departure(recovery):
    state = recovery.record(load_result("DROP_DETECTED"))
    assert state.pinky_departure_allowed is False
    assert state.retry_allowed is False
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest -q control_tower/tests/test_assignment.py control_tower/tests/test_zone_handover.py control_tower/tests/test_pick_recovery.py fms_gateway/tests/unit/test_worker_completion_api.py
```

Expected: FAIL on missing assignment and completion contracts.

- [ ] **Step 3: Implement assignment and ETA preparation**

`AssignmentRevision` contains `revision`, `mobile_id`, `omx_id`, `packing_dock_code`, and `charger_code`. Choose the Packing Dock with the smallest `reservation_available_at + rmf_wait_s + nav2_travel_s`. Pin `PK_01 → TRIHOUSE-TEST-01-CHG-01` and `PK_02 → TRIHOUSE-TEST-01-CHG-02`. Compute `prepare_at = eta_at - grasp_duration - prep_margin`; refresh it on path/delay changes without resetting an already `OMX_READY` pick.

- [ ] **Step 4: Implement readiness and item-level load states**

Require Dock arrival/stationary/current assignment for `PINKY_READY` and expected item/safe handover pose for `OMX_READY`. Release exactly one `START_LOAD`. Persist each attempt with criteria, observations, metrics, evidence refs, policy/model lineage, and one of `LOAD_CONFIRMED`, `DROP_DETECTED`, `LOAD_UNCERTAIN`, `GRASP_RETAINED`. Only `LOAD_CONFIRMED` permits Pinky departure.

- [ ] **Step 5: Implement the two pick-failure choices**

`재시도` re-observes QR/ArUco and resets the ACT episode; permit at most two operator-selected retries. `포장대에서 처리` marks the item `MANUAL_FULFILLMENT_REQUIRED` without removing it from the order. A drop holds OMX/work area/Pinky and disables retry until a worker records object recovery and area clear. After two failed retries, expose only packing handling.

- [ ] **Step 6: Implement worker completion**

Add `POST /api/v1/jobs/{job_id}/worker-completion` with required `Idempotency-Key`. Lock Job, packing Step, Items, lots, and reservations; require manual-required items to be acknowledged; finalize inventory once; release Packing Dock; succeed the wait Step; enqueue return-home to the fixed charger. Replays return the first response.

- [ ] **Step 7: Verify GREEN**

Run:

```bash
pytest -q control_tower/tests/test_assignment.py control_tower/tests/test_zone_handover.py control_tower/tests/test_pick_recovery.py fms_gateway/tests/unit/test_worker_completion_api.py
cd control_ui/rmf_control_ui && flutter test test/worker_completion_test.dart
```

Expected: PASS for Pinky-first, OMX-first, stale readiness, retry/manual handling, drop recovery, duplicate completion, two Dock choices, and charger return.

- [ ] **Step 8: Commit**

```bash
git add control_tower trihouse_pinky fms_gateway control_ui/rmf_control_ui
git commit -m "feat: coordinate outbound handover and completion"
```

### Task 7: Execute Assigned Nav2 Paths Under RMF and Bottleneck Control

**Files:**
- Modify: `control_tower/rmf_adapter/task_api.py`
- Modify: `control_tower/rmf_adapter/rmf_gateway_worker.py`
- Modify: `control_tower/task_manager/sequence_orchestrator.py`
- Modify: `control_tower/rmf_adapter/traffic_reservation.py`
- Create: `control_tower/rmf_adapter/path_schedule.py`
- Create: `control_tower/rmf_adapter/bottleneck.py`
- Create: `trihouse_rmf_bridge/trihouse_rmf_bridge/nav2_path_executor.py`
- Modify: `trihouse_rmf_bridge/trihouse_rmf_bridge/pinky_adapter_node.py`
- Modify: `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py`
- Modify: `trihouse_rmf_bridge/launch/control_system_rmf.launch.py`
- Create: `trihouse_rmf_bridge/launch/two_pinky_order_demo.launch.py`
- Create: `control_tower/tests/test_path_schedule.py`
- Create: `control_tower/tests/test_bottleneck.py`
- Create: `trihouse_rmf_bridge/test/test_nav2_path_executor.py`
- Create: `trihouse_rmf_bridge/test/test_two_pinky_order_demo_launch.py`

**Interfaces:**
- Consumes: assigned `robot_name`, target pose/yaw, Active map revision, Nav2 candidate path, footprint, stopping distance, and RMF participant state.
- Produces: `AssignedPathRequest`, timed RMF itinerary, `FollowPath` execution, and atomic bottleneck leases.

- [ ] **Step 1: Write failing fixed-robot/path/bottleneck tests**

```python
def test_dispatch_contract_requires_assigned_robot():
    request = GoToPlaceRequest(
        request_id="r1", job_step_id=7, waypoint="ambient_storage_loading_dock_01",
        fleet_name="trihouse_pinky", robot_name="PK_01", request_time_ms=1,
    )
    assert request.robot_name == "PK_01"


def test_first_arrival_wins_bottleneck_without_priority_override(coordinator):
    assert coordinator.request("PK_02", "bottleneck_01", at_s=1, priority="normal").acquired
    denied = coordinator.request("PK_01", "bottleneck_01", at_s=2, priority="critical")
    assert denied.acquired is False
    assert denied.holder == "PK_02"
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest -q control_tower/tests/test_path_schedule.py control_tower/tests/test_bottleneck.py trihouse_rmf_bridge/test/test_nav2_path_executor.py
```

Expected: FAIL because `robot_name`, candidate-path execution, and bottleneck coordinator are incomplete.

- [ ] **Step 3: Make selected robot identity mandatory end-to-end**

Add `robot_name: str` to `GoToPlaceRequest`, outbox payload, claim, acceptance, and update validation. A worker/adapter whose name differs rejects the command as `ASSIGNMENT_MISMATCH`; RMF assignment observation may never overwrite `jobs.assigned_mobile_id`. Keep dispatcher/task records for status, but only the Control Tower-selected adapter claims and executes the movement.

- [ ] **Step 4: Replace `NavigateToPose` execution with candidate-path flow**

```python
@dataclass(frozen=True)
class AssignedPathRequest:
    job_step_id: int
    assignment_revision: int
    robot_name: str
    map_revision: str
    goal_pose: tuple[float, float, float]


@dataclass(frozen=True)
class PlannedNavPath:
    request: AssignedPathRequest
    poses: tuple[tuple[float, float, float], ...]
    travel_time_s: float
    path_hash: str


@dataclass(frozen=True)
class PathExecutionResult:
    reached: bool
    reason_code: str
    path_hash: str
```

`Nav2PathExecutor.compute(request)` returns `PlannedNavPath`; its
`follow(path)` method returns `PathExecutionResult`.

Call Nav2 `ComputePathToPose` without moving, convert every pose/time to the assigned RMF participant itinerary, wait for conflict resolution/clearance, then call `FollowPath`. On Nav2 replan need or schedule mismatch, cancel/hold, release the prior override handle, recompute, re-register, and resume. Never hold stubborn override handles for both robots simultaneously.

- [ ] **Step 5: Implement automatic bottleneck approach leases**

Compute approach distance from footprint extent, configured safety margin, and stopping distance. Check/acquire before the footprint crosses the radius-0.1 zone; no manual waiting Waypoint. After 15 seconds, ask Nav2 for a path excluding the occupied region. Use it if valid; otherwise keep waiting. Release only when the full footprint plus margin exits. Stop/emergency inside retains the lease.

- [ ] **Step 6: Launch two isolated Pinky namespaces**

Start one RMF core and two groups for `PK_01`/`pinky_01` and `PK_02`/`pinky_02`. Spawn them at their imported charger poses. Namespace scan, odom, pose, compute path, follow path, local/global path, costmap, and status topics. Internal bootstrap graph is generated only for registered robots/chargers/waypoints and is not an operator layer.

- [ ] **Step 7: Verify GREEN**

Run:

```bash
pytest -q control_tower/tests/test_path_schedule.py control_tower/tests/test_bottleneck.py trihouse_rmf_bridge/test/test_nav2_path_executor.py trihouse_rmf_bridge/test/test_two_pinky_order_demo_launch.py
```

Expected: PASS for fixed assignment, no motion before schedule clearance, replan hold/re-register, first-arrival mutex, 15-second detour, no-detour wait, and lease retention during emergency.

- [ ] **Step 8: Commit**

```bash
git add control_tower trihouse_rmf_bridge trihouse_pinky
git commit -m "feat: coordinate assigned Nav2 paths with RMF"
```

### Task 8: Simulate OMX Contracts and Prebuild OpenCV/ACT Integration

**Files:**
- Modify: `control_tower/gateway/omx_protocol.py`
- Modify: `trihouse_omx_adapter/trihouse_omx_adapter/gazebo_adapter_node.py`
- Create: `trihouse_omx_adapter/trihouse_omx_adapter/protocol_simulator.py`
- Create: `trihouse_omx_adapter/trihouse_omx_adapter/act_policy.py`
- Modify: `trihouse_omx_adapter/setup.py`
- Create: `trihouse_omx_adapter/tests/test_protocol_simulator.py`
- Create: `trihouse_omx_adapter/tests/test_act_policy.py`
- Create: `vision_edge/__init__.py`
- Create: `vision_edge/perception.py`
- Create: `vision_edge/worker.py`
- Create: `vision_edge/tests/test_perception.py`
- Create: `vision_edge/tests/test_worker_contract.py`
- Create: `config/act.simulation.yaml`
- Create: `config/cameras.simulation.yaml`

**Interfaces:**
- Consumes: Gateway OMX command, marker IDs 0/1/2, QR fixture observations, deterministic fake ACT observations, and assignment revision.
- Produces: two simulator processes with real command/state/result contracts and structured load evidence.

- [ ] **Step 1: Write failing simulator/perception/policy tests**

```python
def test_simulator_emits_real_readiness_sequence(simulator):
    events = simulator.execute(prepare_command(omx_id="OMX_01", revision=5))
    assert [event.state for event in events] == ["PREPARING", "PICKING", "OMX_READY"]
    assert all(event.assignment_revision == 5 for event in events)


def test_marker_and_qr_are_both_required(perception):
    result = perception.verify(qr="SKU-MILK", marker_id=1, expected_qr="SKU-MILK", expected_marker=1)
    assert result.accepted is True
    assert perception.verify(qr="SKU-MILK", marker_id=0, expected_qr="SKU-MILK", expected_marker=1).accepted is False


def test_unconfigured_act_never_enables_real_motion(loader):
    policy = loader.load(repo_id="UNCONFIGURED", mode="simulation")
    assert policy.is_fake is True
    assert policy.real_motion_enabled is False
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest -q trihouse_omx_adapter/tests/test_protocol_simulator.py trihouse_omx_adapter/tests/test_act_policy.py vision_edge/tests
```

Expected: FAIL because the simulator, OpenCV evidence types, and ACT loader do not exist.

- [ ] **Step 3: Implement the simulator using the production message contract**

Consume prepare/load/hold/reset commands from Gateway, validate `command_uuid`, `job_step_id`, `assignment_revision`, `omx_id`, expected items, and marker ID, and emit deterministic state transitions. Run two instances as `OMX_01` and `OMX_02`; do not emulate physical ROS endpoints in P0.

- [ ] **Step 4: Implement reusable OpenCV QR/ArUco processing**

Implement OpenCV in the standalone `vision_edge` worker intended for the 4060 server, not inside OMX device ROS. Use `cv2.QRCodeDetector` and `cv2.aruco.DICT_5X5_50`. Return QR value/bounding box and marker ID/corners/rvec/tvec with timestamp, camera ID, assignment revision, and command UUID through the Gateway protocol. Pinky fixtures use marker recognition pose for final corridor/Dock alignment; OMX fixtures use the same real marker IDs to correct pick pose. Do not create synthetic marker IDs.

- [ ] **Step 5: Implement ACT configuration and fake episode**

`config/act.simulation.yaml` sets repo ID/revision/profile to `UNCONFIGURED` and `mode: deterministic_fake`. The loader accepts only a fully specified real repo/revision/profile for hardware mode. The fake episode emits stages `OBSERVE`, `POLICY`, `GRASP`, `VERIFY`, `HANDOVER` and records model lineage as `fake-act/p0-v1`. Publish the six camera IDs, roles, attached Pinky/OMX where applicable, and fixture MediaMTX paths in `map_revisions.manifest.cameras`; omit map pose until P1 calibration instead of inventing coordinates.

- [ ] **Step 6: Implement visual load evidence states**

Combine wrist pre/post grasp tracking and fixed-camera basket ROI observations. Confirm only when the gripper opens over the ROI, the item remains inside, and the empty gripper retreats. Emit exactly `LOAD_CONFIRMED`, `DROP_DETECTED`, `LOAD_UNCERTAIN`, or `GRASP_RETAINED` with evidence refs.

- [ ] **Step 7: Verify GREEN**

Run:

```bash
pytest -q trihouse_omx_adapter/tests vision_edge/tests
```

Expected: PASS for two namespaces, stale revision rejection, QR/marker mismatch, fake ACT, all four load outcomes, and no real motion when unconfigured.

- [ ] **Step 8: Commit**

```bash
git add control_tower/gateway/omx_protocol.py trihouse_omx_adapter vision_edge config/act.simulation.yaml config/cameras.simulation.yaml
git commit -m "feat: add OMX contract simulation and vision adapters"
```

### Task 9: Show Actual Paths, Event Cameras, and Emergency Decisions

**Files:**
- Modify: `control_tower/gateway/operations_feed.py`
- Modify: `control_tower/task_manager/emergency_workflow.py`
- Modify: `fms_gateway/app/models.py`
- Modify: `fms_gateway/app/main.py`
- Modify: `fms_gateway/app/repositories.py`
- Create: `fms_gateway/app/operations_ws.py`
- Create: `media/event_catalog/catalog.py`
- Create: `media/event_catalog/test_catalog.py`
- Create: `control_ui/rmf_control_ui/lib/trihouse/features/operations/operations_page.dart`
- Create: `control_ui/rmf_control_ui/lib/trihouse/features/operations/map_layers.dart`
- Create: `control_ui/rmf_control_ui/lib/trihouse/features/operations/camera_wall.dart`
- Create: `control_ui/rmf_control_ui/test/operations_page_test.dart`
- Create: `control_ui/rmf_control_ui/test/emergency_workflow_test.dart`
- Create: `control_tower/tests/test_emergency_camera_selection.py`

**Interfaces:**
- Consumes: WebSocket robot/path/costmap/RMF/reservation events, six camera fixture statuses, inference overlays, and emergency candidate events.
- Produces: actual-path-first map UI, diagnostic RMF toggle, event camera wall, hold/alarm/continue commands, and auditable resume replan.

- [ ] **Step 1: Write failing layer/camera/emergency tests**

```dart
testWidgets('actual Nav2 path is primary and bootstrap graph is absent', (tester) async {
  await tester.pumpWidget(testOperationsPage());
  expect(find.byKey(const Key('nav2-global-path')), findsOneWidget);
  expect(find.byKey(const Key('actual-trail')), findsOneWidget);
  expect(find.byKey(const Key('bootstrap-graph')), findsNothing);
  expect(find.text('RMF 진단'), findsOneWidget);
});

testWidgets('fall source selects the correct event camera', (tester) async {
  final feed = fakeSixCameraFeed();
  await tester.pumpWidget(testOperationsPage(feed: feed));
  feed.emitPinkyFall('PK_01');
  await tester.pump();
  expect(find.byKey(const Key('CAM-PK-01-live')), findsOneWidget);
});
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest -q control_tower/tests/test_emergency_camera_selection.py
cd control_ui/rmf_control_ui && flutter test test/operations_page_test.dart test/emergency_workflow_test.dart
```

Expected: FAIL on missing WebSocket/UI selection and resume workflow.

- [ ] **Step 3: Publish the operational projection**

Stream SLAM revision, robot pose/yaw/footprint/battery/current Job, Nav2 global/local paths, actual trail, costmaps, goal/yaw, bottleneck lease/wait, RMF conflict/delay, optional RMF timed trajectory, camera status, and incident state. If Nav2/RMF path mismatch exceeds the configured tolerance, emit `PATH_SCHEDULE_MISMATCH` and keep the robot held.

- [ ] **Step 4: Build event-driven camera UI**

Register six status cards. Open OMX wrist + relevant fixed camera for QR/pick/load; relevant Pinky camera for a Pinky-travel fall; relevant fixed camera for a warehouse fall; Pinky camera on manual normal-travel request. Never use Pinky video as OMX load evidence. Overlay QR, ArUco, ACT stage/version/attempt, gripper, safety gate, and load outcome. Auto-close on success; remain open for retry/drop/uncertain/emergency. P0 stores only fixture event clips; the catalog hashes each completed clip and inserts its URI/time range/camera/Job/Step/incident relation in `artifacts`. Do not enable or imply continuous six-stream recording.

- [ ] **Step 5: Implement the two P0 emergency fixtures**

Fixture 1 emits a Pinky-travel fall and selects that Pinky camera. Fixture 2 emits a warehouse fall and selects the fixed camera. Both hold affected work immediately. `비상경보 발령` confirms the incident and preserves hold; `작업 계속 진행` records worker/reason, releases hold, recomputes Nav2 path, re-registers RMF itinerary, and resumes the same Job. Closing the dialog does nothing.

- [ ] **Step 6: Verify GREEN**

Run:

```bash
pytest -q control_tower/tests/test_emergency_camera_selection.py fms_gateway/tests/unit media/event_catalog/test_catalog.py
cd control_ui/rmf_control_ui && flutter test test/operations_page_test.dart test/emergency_workflow_test.dart && flutter analyze
```

Expected: PASS for actual-path rendering, hidden bootstrap graph, six statuses/selective decoding, both camera rules, both operator decisions, and resume replan.

- [ ] **Step 7: Commit**

```bash
git add control_tower fms_gateway control_ui/rmf_control_ui media/event_catalog
git commit -m "feat: add live operations and emergency review"
```

### Task 10: Deliver the One-Command Stack and P0 Acceptance Gate

**Files:**
- Create: `scripts/control_stack`
- Create: `scripts/measure_control_hosts.sh`
- Create: `scripts/camera_soak_test.py`
- Modify: `compose.yaml`
- Modify: `compose.control.yaml`
- Modify: `compose.simulation.yaml`
- Modify: `compose.edge_4060.yaml`
- Create: `tests/test_control_stack_cli.py`
- Create: `tests/test_measurement_gate.py`
- Create: `tools/measurement_gate.py`
- Create: `tests/e2e/test_trihouse_test_01_orders.py`
- Create: `tests/e2e/test_two_pinky_traffic.py`
- Create: `tests/e2e/test_emergency_fixtures.py`
- Create: `docs/validation/2026-08-16-p0-simulation.md`

**Interfaces:**
- Consumes: Tasks 1–9.
- Produces: `up/status/logs/down/doctor`, fresh-seed A–F evidence, two-Pinky traffic evidence, OMX/emergency evidence, and P1 measurement tools that remain gated until run on actual hosts.

In `tests/test_control_stack_cli.py`, define `run_control_stack` as a pytest
fixture that executes `scripts/control_stack` with
`subprocess.run(["scripts/control_stack", *args], text=True,
capture_output=True, check=False)` and returns
the `CompletedProcess`. In `tools/measurement_gate.py`, define
`evaluate_measurements(path: Path) -> MeasurementReport`, where
`MeasurementReport` has `status: Literal["UNMEASURED", "MEASURED"]` and
`missing: tuple[str, ...]`. Import that function in
`tests/test_measurement_gate.py`.

- [ ] **Step 1: Write failing lifecycle and measurement-gate tests**

```python
import json


def test_simulation_doctor_lists_every_required_service(run_control_stack):
    completed = run_control_stack("doctor", "--mode", "simulation")
    checks = json.loads(completed.stdout)["checks"]
    assert set(checks) >= {
        "mysql", "fms_gateway", "control_tower", "mediamtx", "rmf_schedule",
        "gazebo", "nav2:PK_01", "nav2:PK_02", "omx:OMX_01", "omx:OMX_02", "control_ui",
    }


def test_missing_real_host_outputs_are_unmeasured(tmp_path):
    report = evaluate_measurements(tmp_path)
    assert report.status == "UNMEASURED"
    assert set(report.missing) == {"nvidia_smi.txt", "free.txt", "lsblk.txt", "df.txt", "camera_soak.json"}
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest -q tests/test_control_stack_cli.py tests/test_measurement_gate.py
```

Expected: FAIL because lifecycle/measurement scripts are absent.

- [ ] **Step 3: Implement exact lifecycle commands**

```bash
./scripts/control_stack up --mode simulation --project trihouse_test_01
./scripts/control_stack status
./scripts/control_stack logs
./scripts/control_stack doctor --mode simulation
./scripts/control_stack down
```

Use one Compose project. Start MySQL → Gateway → Control Tower workers → MediaMTX → RMF core → Fleet Adapters → Gazebo → two Nav2/Pinky stacks + two OMX protocol simulators → `control_ui`. Default Gazebo to headless; enable GUI/RViz only with flags. Do not start `compose.ai_5080.yaml`; simulation checks only the fake model contract.

- [ ] **Step 4: Prebuild but do not claim physical-host measurement**

`measure_control_hosts.sh <output_dir>` captures the exact `nvidia-smi`, `free -h`, `lsblk -o NAME,MODEL,TRAN,SIZE,FSTYPE,MOUNTPOINTS`, and `df -h` outputs. `camera_soak_test.py` records six-stream codec/resolution/source FPS/decoded FPS/bitrate/drop/QR-ArUco latency/CPU/GPU/RAM/bytes for at least 1800 seconds. Short fixture runs may test the script but must never change production status from `UNMEASURED`.

- [ ] **Step 5: Run six fresh-seed order tests**

For A–F, recreate `db/schema_mysql.sql` + `db/seed_dev.sql`, publish `trihouse_test_01` from the authoritative JSONL, submit through the same public order API used by UI, and assert exact zone sequence, shortage/partial/critical behavior, one-Dock bundle, item attempts, worker completion, selected Packing Dock, and fixed charger return.

- [ ] **Step 6: Run two-Pinky/RMF/OMX/emergency tests**

Submit two compatible orders concurrently. Assert distinct Control Tower assignments, actual Nav2 paths, RMF registration before motion, no collision, bottleneck first-arrival lease and 15-second detour/wait behavior, two OMX READY/load sequences, and both emergency fixture hold/continue replans.

- [ ] **Step 7: Run the full P0 gate**

```bash
./scripts/control_stack up --mode simulation --project trihouse_test_01
pytest -q db/tests fms_gateway/tests control_tower/tests trihouse_rmf_bridge/test trihouse_omx_adapter/tests trihouse_pinky/test tests
cd control_ui/rmf_control_ui && flutter test && flutter analyze
cd /home/syw/Trihouse && ./scripts/control_stack doctor --mode simulation
./scripts/control_stack down
```

Expected: all suites PASS. Record exact commit, commands, pass counts, A–F results, both Pinky path/RMF evidence, both OMX event sequences, emergency screenshots, and artifact/log URIs in `docs/validation/2026-08-16-p0-simulation.md`.

- [ ] **Step 8: Commit**

```bash
git add scripts compose.yaml compose.control.yaml compose.simulation.yaml compose.edge_4060.yaml tests docs/validation/2026-08-16-p0-simulation.md
git commit -m "feat: deliver Trihouse P0 control stack"
```

## P1 Entry Gate After the 2026-08-17 Integration Test

Do not execute physical integration as part of this P0 plan. After P0 passes, collect these inputs on the actual systems before writing/executing the P1 hardware plan:

1. 4060 and OMEN 5080 outputs from `nvidia-smi`, `free -h`, `lsblk`, and `df -h`.
2. A 30-minute six-stream soak artifact produced by `scripts/camera_soak_test.py`.
3. ACT Hugging Face repo ID, immutable revision, input/output features, normalization statistics, and LeRobot version.
4. Actual OMX_01/OMX_02 normal-PC Gateway endpoint and local ROS 2/ROBOTIS driver contracts.
5. Actual Pinky camera/marker calibration and fixed/wrist camera stream/calibration records.
6. P0 regression evidence from `docs/validation/2026-08-16-p0-simulation.md`.

The P1 implementation plan must then cover physical adapters and acceptance, real ACT motion safety, actual stream/storage sizing, camera calibration, and the deferred Floor/Polygon/generic-import/Nav2-settings UI. Until all six inputs exist, physical profiles stay blocked and throughput/retention remain `UNMEASURED`.
