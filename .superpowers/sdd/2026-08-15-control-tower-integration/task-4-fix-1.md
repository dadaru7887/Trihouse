# Task 4 review-fix report

## Outcome and scope

- Resolved every finding in `task-4-review.md`: C1-C3, I1-I5, and the required `If-Match` contract.
- Implementation commit: `4c60a2399c9d4f24328d4d52833726a26bbb9c53` (`fix: harden map draft publication workflow`).
- The implementation is a focused follow-up to `db117b74b3fbee4952a4baffd3e36c44da9c7273`; it was not amended. The original Task base remains `6c3ffbbb8112a07aca93da23497d59606560c48f`.
- Exactly 13 implementation/test paths were committed: 5 Control UI paths, 4 Gateway runtime paths, and 4 Gateway test paths. Pre-existing Task 3/user edits in overlapping `main.py`, `repositories.py`, the repository integration test, and the map-project API test were kept out of the index, as were all unrelated tracked, untracked, and nested-repository changes.

## TDD evidence

### RED

- C1 adversarial deployment tests showed that a stage could retain a trusted manifest hash while its embedded Draft snapshot, source binding, SLAM metadata/image, or generated artifact entries were changed. The new tests failed before validation was made content-addressed end to end.
- C2 tests renamed the project and embedded physical map name while changing bottleneck dimensions. Both invalid imports passed before the target-name gate was removed. A separate fixture made two fiducials share a recognition pose and exposed the missing uniqueness check.
- C3 controlled post-validation Save tests for InMemory and MySQL showed activation could proceed from a stale validation result because the repository publish transaction was not comparing the locked Draft/source/profile expectations.
- I1 repeated-Publish coverage exposed revision identity being coupled to ephemeral deployment UUID/time, producing a different revision/conflict instead of returning the existing immutable publication.
- I2 the widget drag regression showed that an imported handle moved visually before the page later ignored the callback.
- I3 project switching silently replaced dirty state, while browser pop did not provide a reusable Cancel/Discard decision with correct stay/pop behavior.
- I4 an ordered filesystem-spy test showed Active JSON writes lacked file and directory durability barriers.
- I5 concurrent claims allowed the losing pending-to-claimed rename to surface `FileNotFoundError`, yielding a generic server failure.
- Minor-contract compilation coverage showed `expectedRevision` remained optional and the client could omit `If-Match`.

### GREEN

- Shared working overlay, full Gateway suite against live MySQL 8.4: `199 passed`, one existing Starlette/httpx deprecation warning.
- Shared working overlay, full Flutter suite: `191 passed`; `flutter analyze --no-fatal-infos`: no issues; `flutter build web`: succeeded.
- Exact committed-index snapshot, full Gateway suite against MySQL 8.4 at `127.0.0.1:3307` with explicit `fms_gateway` and test-admin credentials: `179 passed`, one existing Starlette/httpx deprecation warning.
- Exact committed-index snapshot, focused Gateway unit suite: `127 passed`; focused live-MySQL map repository suite: `16 passed`.
- Exact committed-index snapshot, full Flutter suite: `191 passed`; analyzer: no issues; web build and Wasm dry run: succeeded.
- Python compilation of the exact snapshot's deployment, repository, and public-route modules succeeded.
- `git diff --cached --check` was clean immediately before the implementation commit.
- One verification invocation used a nonexistent disposable credential pair and failed at MySQL authentication only. It was replaced by the explicit repository test credentials above; the corrected full exact-snapshot run is the reported `179 passed` result.

## C1: complete staged-manifest integrity

Validation now distrusts every mutable stage field and recomputes the binding from canonical or persisted bytes:

- Canonicalizes `manifest.draft_snapshot`, recomputes SHA-256, and compares it to `snapshot_sha256`.
- Requires the snapshot's map name, Draft revision, runtime-profile hash, and source UUID mapping to match the staged manifest and current Draft.
- Loads every persisted source selected by the Draft and rehashes/resizes `content_bytes`; stored SHA/size columns are not trusted. UUID, type, filename, MIME, hash, and size must all match the immutable source manifest.
- Validates required map-server YAML fields and types: `image`, positive finite `resolution`, three finite `origin` numbers, integer `negate` in `{0,1}`, and finite ordered free/occupied thresholds. The image is a plain filename and must exactly name the selected image source.
- Preflights supported PGM P2/P5 data and PNG signature/IHDR/chunks/CRC/IDAT/decompressed scanline shape. Unsupported or malformed images fail closed.
- Requires exactly the generated artifact keys `building_yaml`, `nav_graph_yaml`, and `world_sdf`. Each entry's shape/hash is checked and its content is compared to a fresh deterministic generation before activation; missing keys return validation errors rather than late indexing crashes.

Concrete immutable validation codes include `DEPLOYMENT_SNAPSHOT_INVALID`, `DEPLOYMENT_SNAPSHOT_HASH_MISMATCH`, `DEPLOYMENT_SNAPSHOT_IDENTITY_MISMATCH`, `DEPLOYMENT_PROFILE_BINDING_MISMATCH`, `DEPLOYMENT_SOURCE_MANIFEST_INVALID`, `DEPLOYMENT_SOURCE_MANIFEST_MISMATCH`, `SOURCE_HASH_MISMATCH`, `SLAM_YAML_INVALID`, `SLAM_IMAGE_INVALID`, `RUNTIME_ARTIFACT_SET_INVALID`, `RUNTIME_ARTIFACT_INVALID`, `RUNTIME_ARTIFACT_HASH_MISMATCH`, and `RUNTIME_ARTIFACT_CONTENT_MISMATCH`.

## C2: project-independent canonical P0 physical semantics

- P0 validation no longer depends on project, filename, source, target-map, or embedded map names.
- Every selected physical source must contain exactly 8 source waypoints, 2 bottlenecks, and 3 fiducials.
- Each bottleneck must retain source diameter `0.20 m` and derived radius `0.10 m`.
- All three marker-recognition poses must be distinct, and dock targets must match the canonical source set.
- Tests mutate only names to prove the canonical fixture remains reusable for multiple projects while invalid physical content remains rejected. No coordinate or pose is invented.

## C3: transactional activation fence

The deployment coordinator passes an `expected_draft` envelope into repository publication containing:

- staged Draft revision;
- canonical Draft snapshot and snapshot SHA-256;
- complete source UUID/hash/size/type/filename/MIME manifest;
- pinned runtime-profile hash.

The MySQL repository locks the project row and, within the same transaction, compares the current public Draft plus actual locked source bytes to every staged expectation before looking up/reusing a revision, retiring Active, inserting a revision, or replacing projections. The InMemory repository performs the same checks under an `RLock`, with publication/projection snapshots restored on failure. A Save committed after validation therefore yields stable `DRAFT_REVISION_CHANGED`/HTTP 409, leaves Active unchanged, and removes the failed deployment stage. Controlled race tests cover both repositories, including a real MySQL Save between validation and activation.

## I1: idempotent repeated Publish and cleanup

- Revision identity binds canonical Draft snapshot, runtime-profile hash, source manifest hashes, and generated artifact hashes while excluding deployment UUID and timestamps.
- Publishing an unchanged Draft/profile/source/artifact set returns the existing immutable `PublishedMap` with HTTP 200 and creates no new revision.
- A genuinely different payload reusing a revision identity remains a domain conflict.
- Public routes translate Draft/revision/workflow domain conflicts into stable 409 or 422 responses. Validation and publication stages are removed on all handled non-crash failures and on successful/idempotent completion; only the DB-committed/Active-filesystem crash window is retained for startup reconciliation.

## I2-I3: UI immutability and unsaved-navigation decisions

- Waypoint presentation now carries explicit draggability. Imported handles consume drag gestures without changing local visual state; manual point+yaw handles retain drag behavior. A widget regression asserts the imported marker's position remains unchanged.
- One reusable Cancel/Discard confirmation guards both project switching and route/browser pop.
- Cancel keeps the current dirty project and blocks the pop. Discard opens the chosen project or permits the pending pop. Tests cover both decisions for both navigation paths, so unsaved edits are neither silently lost nor able to trap the user.
- Existing P0 controls and presentation remain intact: explicit Save/Delete/Publish, same-name open guidance, exact 8/2/3 imported display, two `0.10 m` radii, three distinct recognition poses, read-only runtime profile, and no route graph/manual dispatch/polygon measurement editor.

## I4: crash-durable Active files

Active state is persisted in this order:

1. Write the immutable revision manifest to a same-directory temporary file.
2. Flush and `fsync` the file.
3. Atomically `os.replace` it into place.
4. `fsync` the containing directory.
5. Repeat the same durable sequence for the Active pointer.

An injected filesystem spy asserts manifest replace/directory sync happens before pointer replacement. Startup reconciliation still recreates missing Active files from a matching DB-committed stage and removes corrupt/orphan staging safely.

## I5: concurrent token claims

- A loser in the pending-to-claimed rename race now receives `MapWorkflowConflict(STAGED_SOURCE_TOKEN_CONSUMED)` instead of an uncaught `FileNotFoundError`.
- The public Save boundary returns HTTP 409. Exactly one concurrent claimant promotes and saves the source; the loser never deletes or restores the winner's claim.
- Concurrent staging-level and public Save tests assert one winner, one stable conflict, no generic 500, and no leaked/replayed token.

## Required `If-Match` contract

- `expectedRevision` is required by `FmsApi.saveMapDraft` and `FmsApiClient.saveMapDraft`.
- The client always emits `If-Match`; all production callers, fakes, and tests provide the expected revision.

## Staging, Active, and Delete invariants retained

- Source upload remains filesystem-only under the configured runtime staging root until explicit Save, with opaque expiring tokens and filename/MIME/size/path validation.
- Save atomically promotes owned claims with the Draft/source references/features/waypoints; replay, expiry, cross-project use, and losing token races fail closed.
- Publish remains stage -> validate -> activate. Only activate writes immutable revision/snapshot/hash/features/locations/source manifest and the Active pointer.
- A 409/422 failure leaves the prior Active revision intact and creates no permanent failure-audit row.
- Delete with no Active removes Draft and unreferenced sources. Delete with Active restores Draft from the immutable Active manifest and preserves Active plus its referenced sources.

## Runtime-profile contract retained

The Control UI continues to use injected `FmsApi` only. `GET /api/v1/runtime-profiles/pinky-pro-simulation` reads these pinned files server-side and exposes their data read-only:

- `pinky_pro/pinky_navigation/params/nav2_params.yaml`
- `pinky_pro/pinky_bringup/config/pinky_params.yaml`

The verified canonical profile hash remains `98e806991c2cdee14125e600025828923c70de0de7c04da84777d6dad6fcadb9`. Missing source values remain explicitly unavailable; no configuration editor or direct Flutter filesystem read was added.

## Committed paths and overlap audit

Implementation commit `4c60a2399c9d4f24328d4d52833726a26bbb9c53` contains:

- `control_ui/rmf_control_ui/lib/trihouse/api/fms_api.dart`
- `control_ui/rmf_control_ui/lib/trihouse/api/fms_api_client.dart`
- `control_ui/rmf_control_ui/lib/trihouse/features/maps/map_project_page.dart`
- `control_ui/rmf_control_ui/lib/trihouse/presentation/map_workspace.dart`
- `control_ui/rmf_control_ui/test/map_project_page_test.dart`
- `fms_gateway/app/main.py`
- `fms_gateway/app/map_deployment.py`
- `fms_gateway/app/physical_features.py`
- `fms_gateway/app/repositories.py`
- `fms_gateway/tests/integration/test_map_project_repository.py`
- `fms_gateway/tests/unit/test_map_deployment.py`
- `fms_gateway/tests/unit/test_map_project_api.py`
- `fms_gateway/tests/unit/test_physical_features.py`

For overlapping files, the index was built from the committed parent plus only Task 4 fix hunks and then checked out into `/tmp/trihouse-task4-fix-verify2.4hb8ay` for independent verification. The shared worktree's unrelated changes remain unstaged after the commit.

## Risks and accepted boundaries

- Existing-volume migration remains the accepted fresh-deployment risk and is intentionally outside Task 4.
- PNG interlacing is not supported by this narrow server preflight and therefore fails closed rather than accepting an image it cannot fully validate.
- If MySQL activation commits and the following durable Active-manifest write crashes, the stage is deliberately retained so startup reconciliation can finish the manifest/pointer sequence.
- The existing Starlette/httpx deprecation and Flutter Cupertino-font warnings remain informational; tests and builds pass.
