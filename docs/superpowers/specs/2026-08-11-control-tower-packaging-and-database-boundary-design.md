# Control Tower Packaging and Database Boundary Design

## Goal

Make `control_tower` a buildable and installable ROS 2 `ament_python` library without adding a runtime server entry point, while preserving one authoritative MySQL schema location and preparing an evidence-based SR implementation audit.

## Scope

This change will:

- package the existing `control_tower.*` Python modules as one ROS 2 library;
- preserve the current source paths to avoid broad documentation and import churn;
- keep `db/schema_mysql.sql`, migrations, seeds, tools, and schema tests under the repository-level `db/` directory;
- remove the empty duplicate `control_tower/database/migrations/` directory;
- verify source-tree tests, colcon build, installed imports, and installed-package tests;
- audit SR requirements separately after packaging.

This change will not:

- add a `ros2 run` or production server entry point;
- move or copy the canonical MySQL schema into the Python package;
- claim that the current SQLite repository is a production MySQL implementation;
- implement multiple missing SR capabilities as part of packaging.

## Packaging Design

`control_tower` remains a single library package. The existing folders `database`, `fleet_manager`, `gateway`, `rmf_adapter`, and `task_manager` remain in place and are installed under the `control_tower` Python namespace through an explicit setuptools package mapping. UI assets remain repository/deployment assets and are not implicitly bundled until a runtime server contract requires them.

The package will add:

- `control_tower/package.xml` with accurate runtime and test dependencies;
- `control_tower/setup.py` with explicit `control_tower.*` package discovery;
- `control_tower/setup.cfg` for ROS executable installation conventions;
- `control_tower/resource/control_tower` as the ament index marker;
- `control_tower/__init__.py` as the root Python package marker.

No `console_scripts` entry point will be declared in this phase.

## Database Ownership

The repository-level `db/` directory is the sole owner of database lifecycle assets:

- `db/schema_mysql.sql`: canonical MySQL 8 schema;
- `db/migrations/`: non-destructive upgrades for existing databases;
- `db/seed_dev.sql`: development seed data;
- `db/tools/` and `db/tests/`: schema maintenance and validation.

`control_tower/database/` owns application persistence code only. Its tracked structure is:

```text
control_tower/database/
├── connections/     # connection configuration and factories
└── repositories/    # repository interfaces and concrete adapters
```

The `connections/` Python package will be created now as the designated boundary, but production connection behavior will not be invented during packaging. This directory must not contain a second schema copy or independently maintained migration chain. Therefore the empty `control_tower/database/migrations/` directory will be removed and the README responsibility description will be corrected.

The current `AuditRepository` is SQLite-backed and creates its own test tables. It will be treated as a test/local adapter until a MySQL repository using the canonical schema is designed and integration-tested. Packaging must not imply production MySQL completion.

## Verification

Packaging is accepted only when all of the following are demonstrated:

1. Existing Control Tower unit tests pass before packaging changes.
2. `colcon list` identifies `control_tower` as `ros.ament_python`.
3. `rosdep check` resolves declared dependencies.
4. `colcon build` succeeds with `control_tower`, Trihouse interfaces, OMX adapter, and Pinky packages in the selected base paths.
5. After sourcing `install/setup.bash`, representative imports from every installed Control Tower subpackage succeed outside the repository source directory.
6. Control Tower tests pass against the installed package.

## Follow-up Sequence

After packaging, SR work proceeds as separate, reviewable steps:

1. Build an SR evidence matrix from `system_requirements.md`, code, tests, and deployment artifacts, classifying each requirement as implemented, partial, missing, or hardware/integration validation required.
2. Separate the SQLite repository into an explicitly named local/test adapter without changing behavior.
3. Design and implement a MySQL repository against `db/schema_mysql.sql` with integration tests.
4. Address missing SR capabilities one bounded requirement group at a time, using the evidence matrix to set priority.

Each follow-up receives its own design and implementation plan when its scope is selected. This prevents packaging, persistence migration, and unrelated SR behavior changes from being combined into one unverifiable change.
