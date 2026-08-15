# Control System Flutter Baseline

Captured on 2026-08-16 before the `control_ui` boundary copy.

## Source

- Source: `control_system` at Git commit
  `5b4cafe65e257fd070fec925a1c8251315b005de`.
- The source worktree was already dirty when this validation began. It was
  treated as read-only, so this records the current checkout's test behavior
  without attempting to change or repair it.

## Command and result

```bash
cd control_system/rmf_control_ui && flutter test --reporter compact
```

The command exited with status 1 after reporting `+701 ~15 -82`:

- 701 passed
- 15 skipped
- 82 failed

The failing cases are distributed across these existing test files:

| Failing cases | Test file |
| ---: | --- |
| 1 | `test/fleet_adapter_respawn_test.dart` |
| 3 | `test/grid_map_menu_test.dart` |
| 4 | `test/grid_save_button_test.dart` |
| 4 | `test/manual_profile_test.dart` |
| 2 | `test/map_project_naming_test.dart` |
| 5 | `test/readiness_panel_test.dart` |
| 4 | `test/rmf_project_config_test.dart` |
| 6 | `test/robot_detail_test.dart` |
| 4 | `test/robot_map_size_test.dart` |
| 19 | `test/robot_registration_test.dart` |
| 4 | `test/robot_safety_settings_test.dart` |
| 3 | `test/robot_send_button_test.dart` |
| 8 | `test/ros2_inspect_page_test.dart` |
| 3 | `test/ros_domain_test.dart` |
| 1 | `test/simulation_backend_test.dart` |
| 6 | `test/speed_settings_place_test.dart` |
| 4 | `test/wall_height_test.dart` |
| 1 | `test/widget_test.dart` |

This baseline is intentionally failing. Task 1 requires the copied UI to
reproduce this result exactly; it does not alter the Flutter package or repair
the existing tests.

## Copied-tree equivalence

After copying the source tree and writing its provenance marker, the following
command was run without renaming or otherwise refactoring the Flutter package:

```bash
cd control_ui/rmf_control_ui && flutter test --reporter compact
```

It also exited with status 1 and reported `+701 ~15 -82`. The passed, skipped,
and failed totals therefore match the source baseline exactly.
