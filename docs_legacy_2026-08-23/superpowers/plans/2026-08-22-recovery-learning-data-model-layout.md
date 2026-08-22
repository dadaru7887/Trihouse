# Recovery Learning Data and Model Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every completed VLM+RL recovery action exportable as the unchanged TGRPO+SAC training tuple `(state, skill, coord, reward, next_state, done)`, while reorganizing model code into separate training and inference packages and shipping inference only in the physical 5080 runtime.

**Architecture:** `002_recovery_learning_transitions.sql` adds a one-to-one learning transition for each finalized recovery step and an ingestion receipt for ACK idempotency. Gateway validates and atomically persists the transition, and a JSONL exporter emits the exact dictionary shape consumed by the existing offline trainer. The neural-network structure and training mathematics from `origin/dev_driving` are preserved; package movement, I/O adapters, checkpoint verification, and runtime packaging are the only changes.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, MySQL 8.4 JSON/CHECK constraints, NumPy, PyTorch, pytest, Docker Compose

**Spec:** `docs/superpowers/specs/2026-08-22-vision-vlm-rl-recovery-integration-design.md`

## Global Constraints

- Do not modify `db/migrations/001_physical_v1_baseline.sql`; add `002_recovery_learning_transitions.sql`.
- Preserve `STATE_DIM=9`, `COORD_DIM=3`, `N_SKILLS=5`, skill order, network layers, activations, sampling equations, reward equations, optimizer behavior, and training hyperparameters from `origin/dev_driving`.
- Use `PK_01` and `PK_02` for DB/FMS device IDs and `pinky_01`, `pinky_02` only for ROS namespaces.
- 5080 never receives MySQL host, user, or password and never writes MySQL directly.
- Production uses `model.vlm_rl.inference` only. Training entrypoints run only in an explicit offline training profile and are excluded from the physical runtime image.
- Only an actually attempted recovery action may have a `recovery_learning_transitions` row; rejected candidates remain operation events/artifacts.
- A finalized learning row must reconstruct `state`, `skill`, `coord`, `reward`, `next_state`, and `done` without reading an undocumented pickle.
- Preserve the existing dirty `001_physical_v1_baseline.sql` change and all unrelated user changes.
- Follow test-first RED/GREEN for every production behavior and commit only the files named by each task.

---

## Plan Boundary

This is the first independently testable implementation slice of the approved architecture. It delivers the clean model layout, immutable model contract, trainable recovery storage, Gateway ingestion, JSONL training export, durable ACK sender, and inference-only Compose boundary. Operator approval UI, Pinky recovery-command execution, and physical Nav2 cancellation are a separate follow-up plan because they can be reviewed and tested independently from whether recovery data is learnable.

## Target File Map

```text
model/
├── perception/                         moved and normalized current perception code
├── worker/                             moved current media/person/object/marker workers
└── vlm_rl/
    ├── shared/
    │   ├── contracts.py                state/action/skill constants and transition dataclass
    │   └── policy_architecture.py      unchanged network definitions required by both modes
    ├── inference/
    │   ├── checkpoint.py               approved checkpoint checksum/load
    │   └── candidate_generator.py      no-grad KxM candidate generation
    ├── training/
    │   ├── dataset.py                  JSONL transition loader
    │   ├── replay_sampler.py           selected existing replay sampler
    │   ├── offline_train.py            selected existing trainer with JSONL I/O adapter
    │   └── algorithms.py               unchanged SAC/TGRPO update mathematics
    ├── recovery_memory/
    │   ├── queue.py                    fsync-backed pending messages
    │   └── sender.py                   Gateway retry/ACK client
    └── tests/
db/migrations/002_recovery_learning_transitions.sql
fms_gateway/app/recovery_models.py
fms_gateway/app/recovery_repository.py
fms_gateway/app/recovery_routes.py
fms_gateway/tests/unit/test_recovery_learning_api.py
fms_gateway/tests/integration/test_recovery_learning_repository.py
docker/ai/Dockerfile.inference
docker/ai/Dockerfile.training
compose.ai_5080.yaml
compose.ai_training.yaml
tests/model/test_model_layout.py
tests/model/test_inference_image_contract.py
```

### Stable shared interfaces

```python
STATE_DIM = 9
COORD_DIM = 3
SKILL_NAMES = (
    "BACKUP", "REROUTE_LEFT", "REROUTE_RIGHT", "WAIT_REOBSERVE", "REJOIN"
)
SKILL_TO_ACTION_TYPE = {
    0: "retreat", 1: "detour", 2: "detour", 3: "wait", 4: "rejoin"
}

@dataclass(frozen=True)
class LearningTransition:
    state: tuple[float, ...]
    skill: int
    coord: tuple[float, float, float]
    reward: float
    next_state: tuple[float, ...]
    done: bool
    meta: dict[str, object]

@dataclass(frozen=True)
class RecoveryMessage:
    message_id: str
    message_type: str
    endpoint: str
    payload: dict[str, object]

@dataclass(frozen=True)
class SendReport:
    acknowledged: tuple[str, ...]
    pending: tuple[str, ...]
    dead_letter: tuple[str, ...]
```

The exact callable interfaces are `load_training_jsonl(path: Path) ->
list[LearningTransition]`, `enqueue(queue_dir: Path, message: RecoveryMessage) -> Path`,
and `send_pending(queue_dir: Path, gateway_url: str) -> SendReport`.

---

### Task 1: Move Vision Code Under `model/` Without Behavior Changes

**Files:**
- Create/move: `model/perception/**`
- Create/move: `model/worker/**`
- Delete after successful move: `vision_perception/**`, `vision_system/**`, `vision_edge/**`
- Modify: `control_tower/task_manager/pick_failure_report.py`
- Modify: `trihouse_omx_hardware/stream_wrist_camera.py`
- Modify: `trihouse_omx_hardware/job_loop.py`
- Modify: `trihouse_omx_hardware/run_all.py`
- Modify: `pytest.ini`
- Modify: relevant Markdown links and Python module commands returned by `rg -n 'vision_(edge|perception|system)'`
- Test: `tests/model/test_model_layout.py`
- Move/update: current `vision_system/tests/**`, `vision_edge/tests/**`, and `vision_perception/data_collection/test/**`

**Interfaces:**
- Consumes: current vision packages and tests without changing their public behavior.
- Produces: importable `model.perception` and `model.worker`; no old top-level vision directories.

- [ ] **Step 1: Write the failing layout contract**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_model_tree_is_the_only_vision_source_tree() -> None:
    assert (ROOT / "model/perception").is_dir()
    assert (ROOT / "model/worker/person/posture.py").is_file()
    assert not (ROOT / "vision_perception").exists()
    assert not (ROOT / "vision_system").exists()
    assert not (ROOT / "vision_edge").exists()
```

- [ ] **Step 2: Run the layout test and verify RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/model/test_model_layout.py`

Expected: FAIL because `model/perception` and `model/worker` do not exist and old directories still exist.

- [ ] **Step 3: Move files with `git mv` and update imports mechanically**

Use these ownership rules:

```text
vision_perception/augmentation        -> model/perception/dataset/augmentation
vision_perception/calibration         -> model/perception/dataset/calibration
vision_perception/data_collection     -> model/perception/dataset/collection
vision_perception/segmentation/train* -> model/perception/segmentation/training
vision_system/training                -> model/perception/segmentation/training/pipeline
vision_system/evaluation              -> model/perception/segmentation/evaluation
vision_system/yolo_inference_server   -> model/perception/segmentation/runtime
vision_system/inference_common        -> model/worker/common
vision_system/person_worker           -> model/worker/person
vision_system/object_worker           -> model/worker/object
vision_system/marker_worker           -> model/worker/marker
vision_system/stream_hub              -> model/worker/media/stream_hub
vision_system/recording_server        -> model/worker/media/recording
vision_edge/perception.py             -> model/worker/marker/edge_perception.py
vision_edge/worker.py                 -> model/worker/marker/edge_worker.py
```

Update imports to `model.perception...` and `model.worker...`. Do not leave compatibility packages at the old paths.

- [ ] **Step 4: Run moved vision tests and layout test**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/model/test_model_layout.py \
  model/perception/tests \
  model/worker/tests
```

Expected: PASS. If NumPy is unavailable in `.venv`, install the repository-declared vision base requirements before interpreting missing dependency as a code failure.

- [ ] **Step 5: Verify no runtime import references old packages**

Run: `rg -n 'from vision_|import vision_|python -m vision_' --glob '*.py' --glob '*.yaml' --glob '*.md' .`

Expected: no live code or runbook command references the old package names; historical design documents may reference them only when explicitly labeled historical.

- [ ] **Step 6: Commit the mechanical move**

```bash
git add model tests/model control_tower trihouse_omx_hardware pytest.ini docs
git commit -m "refactor(model): group perception and runtime workers"
```

---

### Task 2: Freeze the Existing TGRPO+SAC Model Contract and Split Training from Inference

**Files:**
- Create: `model/vlm_rl/__init__.py`
- Create: `model/vlm_rl/shared/__init__.py`
- Create: `model/vlm_rl/shared/contracts.py`
- Create: `model/vlm_rl/shared/policy_architecture.py`
- Create: `model/vlm_rl/training/__init__.py`
- Create: `model/vlm_rl/training/algorithms.py`
- Create: `model/vlm_rl/inference/__init__.py`
- Create: `model/vlm_rl/inference/checkpoint.py`
- Create: `model/vlm_rl/inference/candidate_generator.py`
- Test: `model/vlm_rl/tests/test_policy_compatibility.py`
- Test: `model/vlm_rl/tests/test_inference_boundary.py`

**Interfaces:**
- Consumes: exact constants, network definitions, update equations, and candidate clamps from `origin/dev_driving:driving_vlm_rm/02_pipeline_core`.
- Produces: `LearningTransition`, unchanged checkpoint-compatible policy classes, and inference code that never imports training modules.

- [ ] **Step 1: Write failing compatibility tests**

```python
def test_model_dimensions_and_skill_order_are_frozen() -> None:
    from model.vlm_rl.shared.contracts import COORD_DIM, SKILL_NAMES, STATE_DIM
    assert STATE_DIM == 9
    assert COORD_DIM == 3
    assert SKILL_NAMES == (
        "BACKUP", "REROUTE_LEFT", "REROUTE_RIGHT", "WAIT_REOBSERVE", "REJOIN"
    )

def test_parameter_shapes_match_dev_driving_v2() -> None:
    from model.vlm_rl.shared.policy_architecture import HighLevelPolicy, LowLevelPolicy
    assert [tuple(p.shape) for p in HighLevelPolicy().parameters()] == [
        (64, 9), (64,), (64, 64), (64,), (5, 64), (5,)
    ]
    assert [tuple(p.shape) for p in LowLevelPolicy().parameters()] == [
        (128, 14), (128,), (128, 128), (128,),
        (3, 128), (3,), (3, 128), (3,)
    ]
```

- [ ] **Step 2: Verify RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q model/vlm_rl/tests/test_policy_compatibility.py`

Expected: FAIL with `ModuleNotFoundError: model.vlm_rl`.

- [ ] **Step 3: Port the model without mathematical changes**

Copy the architecture bodies and constants from commit `d305f12b`/current `origin/dev_driving`. Keep exact layer sizes, ReLU placements, log-std clamp, tanh scaling, skill one-hot encoding, SAC equations, TGRPO equations, seeds, and hyperparameters. Only replace relative import paths and separate class definitions from CLI execution.

Define the trainable tuple validator in `shared/contracts.py`:

```python
def validate_transition(item: LearningTransition) -> None:
    if len(item.state) != STATE_DIM or len(item.next_state) != STATE_DIM:
        raise ValueError("state vectors must contain exactly 9 finite numbers")
    if not 0 <= item.skill < len(SKILL_NAMES):
        raise ValueError("skill must be within the frozen five-skill ontology")
    if len(item.coord) != COORD_DIM:
        raise ValueError("coord must contain dx, dy, and dyaw")
    values = (*item.state, *item.coord, item.reward, *item.next_state)
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("transition values must be finite")
```

- [ ] **Step 4: Write and run the inference-boundary test**

```python
import ast
from pathlib import Path

def test_inference_never_imports_training_package() -> None:
    for path in Path("model/vlm_rl/inference").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert all(not name.startswith("model.vlm_rl.training") for name in imported)
```

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q model/vlm_rl/tests/test_policy_compatibility.py model/vlm_rl/tests/test_inference_boundary.py`

Expected: PASS.

- [ ] **Step 5: Commit the immutable model split**

```bash
git add model/vlm_rl
git commit -m "refactor(vlm-rl): separate unchanged training and inference paths"
```

---

### Task 3: Add an Explicit Trainable Transition Schema in Migration 002

**Files:**
- Create: `db/migrations/002_recovery_learning_transitions.sql`
- Create: `db/tools/apply_migrations.py`
- Create: `db/init/004_record_recovery_learning.sh`
- Modify: `compose.yaml`
- Modify: `compose.db.yaml`
- Modify: `compose.db_test.yaml`
- Modify: `fms_gateway/tests/conftest.py`
- Test: `db/tests/test_migration_runner.py`
- Modify: `fms_gateway/tests/integration/test_schema.py`
- Test: `fms_gateway/tests/integration/test_recovery_learning_repository.py`

**Interfaces:**
- Consumes: `recovery_steps.recovery_step_id` and the frozen 9D/5-skill/3D contract.
- Produces: `trihouse_recovery.recovery_learning_transitions` and `recovery_ingestion_receipts`.

- [ ] **Step 1: Write failing schema tests**

```python
def test_recovery_transition_requires_exact_model_dimensions(recovery_mysql_db):
    columns = recovery_mysql_db.all("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='trihouse_recovery'
          AND table_name='recovery_learning_transitions'
    """)
    assert {row["column_name"] for row in columns} >= {
        "recovery_step_id", "schema_version", "state_vector", "skill_id",
        "skill_name", "action_vector", "reward_total", "next_state_vector",
        "done", "metadata"
    }
```

Add insert tests that reject state length 8, action length 2, skill ID 5, mismatched skill name, and non-boolean `done`.

- [ ] **Step 2: Run integration schema tests and verify RED**

Run: `pytest -q -m integration fms_gateway/tests/integration/test_schema.py fms_gateway/tests/integration/test_recovery_learning_repository.py`

Expected: FAIL because migration 002 and the two tables do not exist.

- [ ] **Step 3: Create migration 002**

Create one row per executed step:

```sql
CREATE TABLE trihouse_recovery.recovery_learning_transitions (
  recovery_step_id BIGINT UNSIGNED NOT NULL,
  schema_version SMALLINT UNSIGNED NOT NULL DEFAULT 1,
  state_vector JSON NOT NULL,
  skill_id TINYINT UNSIGNED NOT NULL,
  skill_name VARCHAR(24) NOT NULL,
  action_vector JSON NOT NULL,
  reward_total DOUBLE NOT NULL,
  next_state_vector JSON NOT NULL,
  done TINYINT(1) NOT NULL,
  metadata JSON NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (recovery_step_id),
  CONSTRAINT fk_learning_transition_step FOREIGN KEY (recovery_step_id)
    REFERENCES recovery_steps (recovery_step_id) ON DELETE CASCADE,
  CONSTRAINT chk_learning_state_shape CHECK
    (JSON_TYPE(state_vector)='ARRAY' AND JSON_LENGTH(state_vector)=9),
  CONSTRAINT chk_learning_action_shape CHECK
    (JSON_TYPE(action_vector)='ARRAY' AND JSON_LENGTH(action_vector)=3),
  CONSTRAINT chk_learning_next_state_shape CHECK
    (JSON_TYPE(next_state_vector)='ARRAY' AND JSON_LENGTH(next_state_vector)=9),
  CONSTRAINT chk_learning_skill CHECK
    ((skill_id=0 AND skill_name='BACKUP') OR
     (skill_id=1 AND skill_name='REROUTE_LEFT') OR
     (skill_id=2 AND skill_name='REROUTE_RIGHT') OR
     (skill_id=3 AND skill_name='WAIT_REOBSERVE') OR
     (skill_id=4 AND skill_name='REJOIN')),
  CONSTRAINT chk_learning_done CHECK (done IN (0,1)),
  CONSTRAINT chk_learning_metadata CHECK (JSON_TYPE(metadata)='OBJECT')
) ENGINE=InnoDB COMMENT='Stores finalized executed recovery transitions in the exact state-skill-action-reward-next-state form consumed by offline reinforcement learning.';
```

Create `recovery_ingestion_receipts(message_id, payload_sha256, message_type, resource_key, response_payload, processed_at)` with `message_id` primary key and JSON object checks. Use English table/column comments required by existing schema tests.

Gateway validation must also require the referenced `recovery_steps.action_type` to match
`SKILL_TO_ACTION_TYPE`. A policy action cancelled after it started retains its original
`retreat`, `detour`, `wait`, or `rejoin` action type and can be learned when a real next state and
reward exist. A standalone `stop` audit step is not one of the frozen five RL skills and therefore
does not receive a learning-transition row. `done` means the policy episode terminates after this
transition, not merely that the SQL step row has reached a terminal execution status.

- [ ] **Step 4: Write the failing ordered-migration runner test**

The test uses a temporary migration directory containing versions 001 and 002 and a fake
database adapter. It asserts numeric order, SHA-256 recording, already-applied skip, checksum
mismatch refusal, and gap refusal.

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q db/tests/test_migration_runner.py`

Expected: FAIL because `db/tools/apply_migrations.py` does not exist.

- [ ] **Step 5: Implement and wire ordered migration application**

Do not concatenate 002 into 001. `apply_migrations.py` reads `NNN_*.sql` in numeric order,
compares every applied filename and SHA-256 with `schema_migrations`, refuses a gap or changed
file, executes one unapplied migration per transaction, and records its hash only after success.
The test fixture uses the same ordered file list.

For a new Docker volume, mount 002 after the baseline SQL and add
`004_record_recovery_learning.sh` to record version 2 and its source-file SHA-256. For an existing
volume, the deployment command runs `apply_migrations.py`; initdb scripts are not treated as an
upgrade mechanism.

- [ ] **Step 6: Run migration and schema tests GREEN**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q db/tests/test_migration_runner.py
pytest -q -m integration fms_gateway/tests/integration/test_schema.py fms_gateway/tests/integration/test_recovery_learning_repository.py
docker compose -f compose.db_test.yaml config --quiet
```

Expected: PASS with recovery table set containing four tables and Compose mounting migration 002.

- [ ] **Step 7: Commit migration 002 and its runner**

```bash
git add db/migrations/002_recovery_learning_transitions.sql db/tools/apply_migrations.py \
  db/init/004_record_recovery_learning.sh db/tests/test_migration_runner.py \
  compose.yaml compose.db.yaml compose.db_test.yaml fms_gateway/tests/conftest.py \
  fms_gateway/tests/integration
git commit -m "feat(db): store trainable recovery transitions"
```

---

### Task 4: Implement Gateway Validation and Atomic Recovery Ingestion

**Files:**
- Create: `fms_gateway/app/recovery_models.py`
- Create: `fms_gateway/app/recovery_repository.py`
- Create: `fms_gateway/app/recovery_routes.py`
- Modify: `fms_gateway/app/main.py`
- Modify: `fms_gateway/app/repositories.py` only to expose the focused recovery repository through the application composition boundary
- Test: `fms_gateway/tests/unit/test_recovery_learning_api.py`
- Test: `fms_gateway/tests/integration/test_recovery_learning_repository.py`

**Interfaces:**
- Consumes: `Idempotency-Key`, `RecoveryStepCompletion`, migration 002 tables.
- Produces: atomic terminal step plus learning transition and replay-safe duplicate ACK.

- [ ] **Step 1: Write failing API model tests**

```python
def transition_payload() -> dict:
    return {
        "execution_status": "succeeded",
        "outcome_class": "safe",
        "completed_at": "2026-08-22T16:00:01+09:00",
        "is_terminal": True,
        "reward_components": {"progress": 0.2, "clearance_cost": 0.0},
        "transition": {
            "schema_version": 1,
            "state": [0.0] * 9,
            "skill": 4,
            "skill_name": "REJOIN",
            "coord": [0.1, 0.0, 0.0],
            "reward": 0.2,
            "next_state": [0.1] + [0.0] * 8,
            "done": True,
            "meta": {"is_execution": True}
        }
    }
```

Tests must reject NaN/Infinity, wrong dimensions, mismatched skill/name, nonterminal execution statuses, and `meta.is_execution != true`.

- [ ] **Step 2: Verify RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q fms_gateway/tests/unit/test_recovery_learning_api.py`

Expected: FAIL because the recovery models and route do not exist.

- [ ] **Step 3: Implement strict Pydantic models**

Use `ConfigDict(extra="forbid")`, fixed-length tuples, finite number validators, exact skill mapping, and `meta.is_execution is True`. Keep absolute `target_pose` in `recovery_steps`; keep RL-relative `(dx, dy, dyaw)` only in `transition.coord`.

- [ ] **Step 4: Implement receipt-first idempotency semantics in one DB transaction**

The repository method is `complete_recovery_step`. It accepts `episode_uuid: str`,
`step_no: int`, `request: dict[str, object]`, `message_id: str`, and
`payload_sha256: str`, and returns `dict[str, object]`.

Within one transaction: lock existing receipt; return stored response if hash matches; raise `IdempotencyConflict` if it differs; lock running step; update terminal status; insert exactly one learning transition; insert receipt with response; commit. A rollback must leave neither a terminal step nor a transition.

- [ ] **Step 5: Add the route**

```text
POST /internal/v1/recovery/episodes/{episode_uuid}/steps/{step_no}/complete
Headers: Idempotency-Key: UUID
Response: message_id, recovery_step_id, execution_status, acknowledged=true
```

- [ ] **Step 6: Run unit and real-MySQL integration tests**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q fms_gateway/tests/unit/test_recovery_learning_api.py
pytest -q -m integration fms_gateway/tests/integration/test_recovery_learning_repository.py
```

Expected: PASS, including same-message retry and different-payload conflict.

- [ ] **Step 7: Commit Gateway ingestion**

```bash
git add fms_gateway/app fms_gateway/tests/unit/test_recovery_learning_api.py fms_gateway/tests/integration/test_recovery_learning_repository.py
git commit -m "feat(gateway): ingest recovery learning transitions idempotently"
```

---

### Task 5: Export Recovery Rows as the Existing Trainer Tuple

**Files:**
- Create: `model/vlm_rl/training/dataset.py`
- Create: `fms_gateway/app/recovery_export.py`
- Modify: `fms_gateway/app/recovery_routes.py`
- Test: `model/vlm_rl/tests/test_training_dataset.py`
- Test: `fms_gateway/tests/unit/test_recovery_export.py`

**Interfaces:**
- Consumes: completed episode/step/transition joins.
- Produces: line-delimited dictionaries compatible with the original offline buffer shape.

- [ ] **Step 1: Write a failing round-trip test**

```python
def test_export_round_trips_to_the_frozen_training_tuple(tmp_path: Path) -> None:
    path = tmp_path / "recovery.jsonl"
    path.write_text(json.dumps({
        "state": [0.0] * 9,
        "skill": 4,
        "coord": [0.1, 0.0, 0.0],
        "reward": 0.2,
        "next_state": [0.1] + [0.0] * 8,
        "done": True,
        "meta": {"is_execution": True, "episode_uuid": "episode-1", "step_no": 1}
    }) + "\n", encoding="utf-8")
    transitions = load_training_jsonl(path)
    assert transitions[0].skill == 4
    assert transitions[0].coord == (0.1, 0.0, 0.0)
```

- [ ] **Step 2: Verify RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q model/vlm_rl/tests/test_training_dataset.py fms_gateway/tests/unit/test_recovery_export.py`

Expected: FAIL because loader and exporter do not exist.

- [ ] **Step 3: Implement deterministic JSONL export**

Export only rows where the episode is terminal, the step is terminal, and a transition exists. Order by episode start, episode UUID, step number. Include lineage in `meta`: episode UUID, step number, device ID, map name/revision, VLM model/version, recovery policy/version, outcome class, execution status, `is_execution=true`.

- [ ] **Step 4: Implement strict loader without pickle**

`load_training_jsonl()` parses one object per line, rejects unknown top-level fields, calls `validate_transition`, and reports line number on failure. It never silently substitutes missing state values.

- [ ] **Step 5: Run export/loader tests GREEN**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q model/vlm_rl/tests/test_training_dataset.py fms_gateway/tests/unit/test_recovery_export.py`

Expected: PASS.

- [ ] **Step 6: Commit the training data boundary**

```bash
git add model/vlm_rl/training/dataset.py model/vlm_rl/tests/test_training_dataset.py fms_gateway/app/recovery_export.py fms_gateway/app/recovery_routes.py fms_gateway/tests/unit/test_recovery_export.py
git commit -m "feat(vlm-rl): export DB transitions for offline training"
```

---

### Task 6: Port the Existing Offline Trainer Without Changing Its Mathematics

**Files:**
- Create: `model/vlm_rl/training/algorithms.py`
- Create: `model/vlm_rl/training/replay_sampler.py`
- Create: `model/vlm_rl/training/offline_train.py`
- Test: `model/vlm_rl/tests/test_training_compatibility.py`

**Interfaces:**
- Consumes: `list[LearningTransition]` from Task 5 and shared policy classes from Task 2.
- Produces: checkpoint with the same high/low policy state_dict keys expected by inference.

- [ ] **Step 1: Write failing frozen-math tests**

With fixed seeds and tensors, compare logits, sampled coordinate shapes, reward calculation, SAC batch shapes, and checkpoint keys against values captured from `origin/dev_driving`. Store only small numeric fixtures in `model/vlm_rl/tests/fixtures/compatibility.json`.

- [ ] **Step 2: Verify RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q model/vlm_rl/tests/test_training_compatibility.py`

Expected: FAIL because offline training modules do not exist.

- [ ] **Step 3: Port I/O around unchanged algorithms**

Replace `PersistentRecoveryBuffer` pickle loading with `load_training_jsonl()`. Preserve the following defaults exactly: `BATCH_SIZE=32`, minimum transitions `4`, 20 epochs, reward hard clip disabled, soft clip disabled, TGRPO standard deviation normalization enabled by default, clip surrogate enabled, epsilon `0.2`, and existing KL/SAC/CQL behavior.

- [ ] **Step 4: Run compatibility and one-epoch smoke tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q model/vlm_rl/tests/test_policy_compatibility.py model/vlm_rl/tests/test_training_compatibility.py`

Expected: PASS with no model parameter-shape or fixed-seed fixture change.

- [ ] **Step 5: Commit offline training**

```bash
git add model/vlm_rl/training model/vlm_rl/tests
git commit -m "feat(vlm-rl): train unchanged policies from recovery JSONL"
```

---

### Task 7: Add a Crash-Safe 5080 Queue and ACK Sender

**Files:**
- Create: `model/vlm_rl/recovery_memory/__init__.py`
- Create: `model/vlm_rl/recovery_memory/queue.py`
- Create: `model/vlm_rl/recovery_memory/sender.py`
- Test: `model/vlm_rl/tests/test_recovery_queue.py`

**Interfaces:**
- Consumes: recovery episode/step messages with UUID `message_id` and Gateway HTTP endpoint.
- Produces: atomic pending files removed only after matching application ACK.

- [ ] **Step 1: Write failing queue tests**

Tests cover write-to-temp plus `os.replace`, directory fsync, deterministic filename by message ID, restart discovery, matching ACK removal, timeout preservation, 409 payload conflict dead-letter, and bounded exponential backoff.

- [ ] **Step 2: Verify RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q model/vlm_rl/tests/test_recovery_queue.py`

Expected: FAIL because queue modules do not exist.

- [ ] **Step 3: Implement queue and sender**

Persist a canonical compact JSON envelope containing `message_id`, `message_type`, `payload_sha256`, `endpoint`, and `payload`. Never log authenticated URLs or payload images. Remove a pending file only when HTTP 2xx response contains the same message ID and `acknowledged=true`.

- [ ] **Step 4: Run queue tests GREEN**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q model/vlm_rl/tests/test_recovery_queue.py`

Expected: PASS.

- [ ] **Step 5: Commit durable delivery**

```bash
git add model/vlm_rl/recovery_memory model/vlm_rl/tests/test_recovery_queue.py
git commit -m "feat(vlm-rl): deliver recovery records with durable ACK queue"
```

---

### Task 8: Make Physical Runtime Inference-Only

**Files:**
- Create: `docker/ai/Dockerfile.inference`
- Create: `docker/ai/Dockerfile.training`
- Modify: `compose.ai_5080.yaml`
- Create: `compose.ai_training.yaml`
- Test: `tests/model/test_inference_image_contract.py`
- Modify: `.env.example`
- Modify: `docs/deployment/environment_overview.md`

**Interfaces:**
- Consumes: inference package and approved model/checkpoint mounts.
- Produces: physical runtime that cannot invoke offline training and an explicit opt-in training profile.

- [ ] **Step 1: Write failing Compose/image contract tests**

```python
def test_physical_compose_uses_inference_entrypoint_only() -> None:
    source = Path("compose.ai_5080.yaml").read_text(encoding="utf-8")
    assert "model.vlm_rl.inference" in source
    assert "model.vlm_rl.training" not in source

def test_inference_dockerfile_never_copies_training_package() -> None:
    source = Path("docker/ai/Dockerfile.inference").read_text(encoding="utf-8")
    assert "vlm_rl/training" not in source
```

- [ ] **Step 2: Verify RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/model/test_inference_image_contract.py`

Expected: FAIL because the Dockerfiles and explicit inference command do not exist.

- [ ] **Step 3: Create separate images and Compose entrypoints**

`Dockerfile.inference` copies `model/vlm_rl/shared`, `inference`, `safety`, `contracts`, and `recovery_memory`, but not `training` or datasets. `Dockerfile.training` includes shared plus training and is used only by `compose.ai_training.yaml`. Physical Compose sets `VLM_RL_EXECUTION_MODE=operator_approved` and has no MySQL environment variables.

- [ ] **Step 4: Validate Compose and boundary tests**

Run:

```bash
docker compose -f compose.ai_5080.yaml config --quiet
docker compose -f compose.ai_training.yaml config --quiet
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/model/test_inference_image_contract.py
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit runtime packaging**

```bash
git add docker/ai compose.ai_5080.yaml compose.ai_training.yaml .env.example docs/deployment/environment_overview.md tests/model/test_inference_image_contract.py
git commit -m "feat(deploy): separate VLM RL inference and offline training images"
```

---

### Task 9: Integrated Verification and Status Documentation

**Files:**
- Modify: `docs/architecture/recovery_memory.md`
- Create: `tests/physical_readiness/test_13_recovery_learning_contract.py`
- Modify: `docs/superpowers/specs/2026-08-22-vision-vlm-rl-recovery-integration-design.md` only if implementation exposed an already-approved ambiguity; do not silently change behavior.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: evidence that DB rows round-trip to unchanged training tuples and production runs inference only.

- [ ] **Step 1: Add the end-to-end contract test**

The test creates one terminal episode and step in test MySQL, completes it with a 9D/5-skill/3D transition, exports JSONL, loads it with `load_training_jsonl`, and asserts all six learning fields are equal. It retries the same message ID and asserts one step, one transition, and one receipt.

- [ ] **Step 2: Run the focused full suite**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/model \
  model/perception/tests \
  model/worker/tests \
  model/vlm_rl/tests \
  fms_gateway/tests/unit/test_recovery_learning_api.py \
  fms_gateway/tests/unit/test_recovery_export.py \
  tests/physical_readiness/test_13_recovery_learning_contract.py
pytest -q -m integration \
  fms_gateway/tests/integration/test_schema.py \
  fms_gateway/tests/integration/test_recovery_learning_repository.py
docker compose -f compose.ai_5080.yaml config --quiet
```

Expected: exit 0, no failed tests, migration 001 checksum untouched, and physical Compose contains no training entrypoint or MySQL credential.

- [ ] **Step 3: Document the exact operational rule**

State in `recovery_memory.md`:

```text
Physical runtime: inference only.
Offline training: completed DB export -> JSONL -> explicit training Compose.
Checkpoint promotion: checksum and approved=true before inference load.
No online gradient update during robot operation.
```

- [ ] **Step 4: Verify the worktree diff and immutable baseline**

Run:

```bash
git diff --check
git diff -- db/migrations/001_physical_v1_baseline.sql
git status --short
```

Expected: no whitespace errors. The pre-existing 001 diff remains uncommitted and is not altered by this plan's commits.

- [ ] **Step 5: Commit verification and documentation**

```bash
git add docs/architecture/recovery_memory.md tests/physical_readiness/test_13_recovery_learning_contract.py
git commit -m "test(recovery): verify DB to offline learning round trip"
```

---

## Follow-up Plans

After this plan is verified, create two separate plans from the approved spec:

1. **Operator-approved recovery runtime:** Recovery Coordinator state machine, approval API/UI projection, recovery command downlink, Pinky Nav2 executor, Safety STOP/EMERGENCY cancellation.
2. **Physical recovery validation:** camera/person/obstacle trigger scenarios, sole `/cmd_vel` publisher check, E-stop supervision, ACK-loss injection, and measured recovery success/reward evidence.
