# Battery Measurement Logging and Final Local Job Design

## Goal

Refine the POC battery policy so a LOCAL_ONLY robot can use its remaining safe energy for one final frozen-storage-to-packing task, and automatically capture structured measurement data that can calibrate Open-RMF energy estimates.

`pinky_pro` and `control_system` remain read-only and are not changed.

## LOCAL_ONLY Decision Bands

The existing hard-stop threshold of 5% is the safety boundary for accepting one final local job.

| Predicted task-finish SOC | Decision |
|---|---|
| Greater than 10% | `ALLOW_LOCAL_JOB`; normal frozen-storage-to-packing cycling may continue |
| Greater than 5% and at most 10% | `COMPLETE_THEN_RETURN`; accept this final local task and return to charge afterward |
| At most 5% | `RETURN_TO_CHARGE`; reject the task and return immediately |
| RMF estimate unavailable | `WAIT_AT_SAFE_NODE`; do not guess |

The predicted SOC is the task-finish value returned by the RMF estimate boundary. `COMPLETE_THEN_RETURN` remains a decision snapshot rather than a direct motor command. Existing `ExecuteTransport`/Nav2 execution performs the job and subsequent charge return.

## Structured Measurement Logs

Measurement logging is enabled by default and separated from mixed ROS console logs. Files use append-only JSON Lines so incomplete shutdowns preserve earlier records and analysis tools can stream them.

```text
~/.ros/trihouse/measurements/<run_id>/
├── run_metadata.json
├── battery_telemetry_<robot_id>.jsonl
├── rmf_energy_estimates.jsonl
└── battery_policy_decisions.jsonl
```

`run_id` may be supplied through configuration or `TRIHOUSE_MEASUREMENT_RUN_ID`. If absent, the process generates a UTC timestamp identifier. The root may be supplied through configuration or `TRIHOUSE_MEASUREMENT_LOG_ROOT`; otherwise it defaults to `~/.ros/trihouse/measurements`.

Every record contains `schema_version`, `recorded_at`, `run_id`, and `record_type`. Domain-specific fields include robot ID, task/job ID, current SOC, predicted SOC, duration, policy state/action/reason, waypoint sequence, cargo context, estimator source, and errors where applicable.

Writers create directories lazily, serialize one record per line, flush each record, and never allow a logging failure to change a safety or dispatch decision. The owning ROS/process logger reports a warning if measurement persistence fails.

## Recording Boundaries

### Pinky Gateway

Each outgoing `RobotStatus` sample records robot/job identity, actual percentage, power supply status, validity/freshness, policy state, ready flag, and reason. These records provide the actual time series used to compare RMF predictions with observed finish SOC.

### RMF Energy Estimator

Each estimate attempt records the request waypoint sequence, current SOC, fixed phase durations, timeout/retry result, RMF travel and total durations, charge change, predicted finish SOC, and estimator source. Failed attempts record a stable error code.

### Dispatch Workflow

Each assignment evaluation records robot ID, task ID, current state/percentage, predicted SOC, chosen action, reason code, and assignment outcome. It must use the same pure policy result that drives dispatch, not recompute policy for logging.

## Open-RMF Environment Findings

The protected `control_system` documentation targets:

- ROS 2 Jazzy
- `rmf_demos` 2.3
- rmf-web dashboard 0.3.0 at commit `7aa265337936a5bd9a920b3fa2360a43244a015c`
- `ghcr.io/open-rmf/rmf-web/api-server:jazzy`

The present machine does not expose `/home/syw/rmf_ws/install/setup.bash` or importable RMF Python modules, and Docker daemon access is unavailable to the current user. Therefore runtime RMF core and API image digests cannot be asserted from this environment.

The existing rmf-web `/fleets` client consumes fleet/name, robot status, current battery, task ID, map/x/y/yaw, issues, and mutex groups. The current battery is not predicted finish SOC. The custom `EstimateTaskEnergy.srv` server still needs to be implemented in the future RMF adapter; this change records and consumes its response through the existing port without modifying `control_system`.

## POC Parameter Documentation

Create `docs/guideline/parameters_for_rmf.md` with only the minimum POC inputs:

- navigation graph waypoint coordinates and approach yaw;
- RMF-to-robot coordinate references;
- linear/angular velocity and acceleration;
- footprint/vicinity;
- nominal voltage, usable capacity, and charging current;
- mass, inertia estimate, rolling resistance/friction estimate, and Pinky ambient power;
- loading, handover, and task-buffer durations.

The same document includes a measurement-method column, required battery experiments, RMF-produced estimates, rmf-web-observable states and meanings, version limitations, relevant source/test file checklist, terminal test procedure, and JSONL inspection commands.

OMX arm power is not included because OMX does not draw from the Pinky battery. Tool power remains zero for this POC unless Pinky-powered equipment is added.

## Testing

- Red/green policy boundary tests at predicted 10%, 5%, and either side.
- JSONL writer tests for directory layout, metadata, append behavior, and serialization.
- RMF estimator tests for success, retry, failure, and fallback measurement records.
- Dispatch tests asserting logged action matches the action used for eligibility.
- Gateway source/unit tests for battery telemetry records.
- Documentation contract checks for required parameters, experiments, states, commands, and protected-path statement.
- Existing ROS interface, Pinky, and Control Tower suites remain green.
