-- Make scheduling measurable: keep the prediction a step was dispatched with,
-- keep the decomposed time it actually took, and keep the calibration derived
-- from those samples behind an explicit human approval.
--
-- Error cannot be computed after the fact. Nothing in the schema stored what a
-- step was expected to take, so the difference between plan and reality was
-- unrecoverable no matter how much history accumulated. That is what this adds.
--
-- Requires migration 011_unify_loading_dock_and_waiting_point.sql first.

USE `trihouse_fms`;

-- 1. The prediction a step carried when it was dispatched ---------------------
--
-- Stored on the step rather than the attempt because a prediction is made once,
-- at dispatch, for the work itself. A retry that predicts differently records
-- that in its own attempt metrics.
ALTER TABLE job_steps
  ADD COLUMN predicted_duration_ms BIGINT UNSIGNED NULL
    COMMENT 'Expected duration in milliseconds recorded when the step was dispatched.'
    AFTER assignment_revision,
  ADD COLUMN prediction_source VARCHAR(24) NULL
    COMMENT 'Origin of the prediction: rmf, baseline, seed, or none.'
    AFTER predicted_duration_ms,
  ADD COLUMN predicted_at DATETIME(6) NULL
    COMMENT 'Timestamp when the prediction was recorded.'
    AFTER prediction_source,
  ADD CONSTRAINT chk_job_steps_prediction CHECK
    ((predicted_duration_ms IS NULL AND prediction_source IS NULL
      AND predicted_at IS NULL)
     OR (predicted_duration_ms IS NOT NULL AND prediction_source IS NOT NULL
         AND predicted_at IS NOT NULL));

-- 2. Queryable projections of the decomposed duration sample ------------------
--
-- The decomposition itself stays in `metrics` JSON, because the segments differ
-- per action type: a navigate splits into travel and traffic wait, a pick into
-- approach and grasp. Only the few values every sample shares are lifted into
-- generated columns, so aggregation can use an index instead of scanning JSON.
ALTER TABLE job_step_attempts
  ADD COLUMN metric_total_ms BIGINT UNSIGNED
    GENERATED ALWAYS AS
      (JSON_VALUE(metrics, '$.duration.total_ms' RETURNING UNSIGNED)) STORED
    COMMENT 'Measured total duration in milliseconds, projected from metrics.',
  ADD COLUMN metric_environment VARCHAR(16)
    GENERATED ALWAYS AS
      (JSON_VALUE(metrics, '$.duration.environment' RETURNING CHAR(16))) STORED
    COMMENT 'Environment that produced this sample: simulation or hardware.',
  ADD COLUMN metric_scope_key VARCHAR(128)
    GENERATED ALWAYS AS
      (JSON_VALUE(metrics, '$.duration.scope_key' RETURNING CHAR(128))) STORED
    COMMENT 'Aggregation scope this sample belongs to, projected from metrics.',
  ADD KEY idx_attempts_calibration
    (metric_environment, metric_scope_key, completed_at);

-- 3. Calibration derived from those samples -----------------------------------
--
-- Scheduling reads only this table, and only rows an operator approved. An
-- aggregate that rewrote the schedule the moment it was computed would let the
-- warehouse silently re-time itself; the same gate that governs a published map
-- governs a published duration.
CREATE TABLE IF NOT EXISTS duration_baselines (
  baseline_id     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Surrogate identifier for this baseline revision.',
  scope_kind      VARCHAR(24) NOT NULL COMMENT 'What this baseline times: an action type or a navigation lane.',
  scope_key       VARCHAR(128) NOT NULL COMMENT 'Aggregation scope, such as zone=frozen. Refinable without discarding history.',
  environment     VARCHAR(16) NOT NULL COMMENT 'Environment the samples came from: simulation or hardware.',
  origin          VARCHAR(16) NOT NULL DEFAULT 'aggregated' COMMENT 'How the values were produced: seed for an operator measurement, aggregated for computed statistics.',
  sample_count    INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Number of samples behind these percentiles. Zero only for an operator seed.',
  p50_ms          BIGINT UNSIGNED NOT NULL COMMENT 'Median duration in milliseconds, used for planning.',
  p90_ms          BIGINT UNSIGNED NOT NULL COMMENT 'Ninetieth percentile duration in milliseconds, used for slack.',
  observed_from   DATETIME(6) NULL COMMENT 'Start of the sample window. Null for an operator seed.',
  observed_to     DATETIME(6) NULL COMMENT 'End of the sample window. Null for an operator seed.',
  revision        BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT 'Increases every time this scope is recalibrated.',
  state           VARCHAR(16) NOT NULL DEFAULT 'proposed' COMMENT 'Approval status: proposed, approved, or superseded.',
  approved_by     VARCHAR(64) NULL COMMENT 'Operator who approved this revision.',
  approved_at     DATETIME(6) NULL COMMENT 'Timestamp when the approval was recorded.',
  note            VARCHAR(512) NULL COMMENT 'Operator-readable explanation of how the values were obtained.',
  created_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the created event occurred.',
  PRIMARY KEY (baseline_id),
  UNIQUE KEY uq_baseline_revision (scope_kind, scope_key, environment, revision),
  KEY idx_baseline_lookup (scope_kind, scope_key, environment, state),
  CONSTRAINT chk_baseline_scope_kind CHECK (scope_kind IN
    ('pick','load','handover','wait','dock','navigate_lane','return_home')),
  CONSTRAINT chk_baseline_environment CHECK (environment IN
    ('simulation','hardware')),
  CONSTRAINT chk_baseline_origin CHECK (origin IN ('seed','aggregated')),
  CONSTRAINT chk_baseline_state CHECK (state IN
    ('proposed','approved','superseded')),
  CONSTRAINT chk_baseline_percentiles CHECK (p90_ms >= p50_ms),
  CONSTRAINT chk_baseline_window CHECK
    ((observed_from IS NULL AND observed_to IS NULL)
     OR (observed_from IS NOT NULL AND observed_to IS NOT NULL
         AND observed_to >= observed_from)),
  -- An aggregated baseline without samples would be a fabricated number.
  CONSTRAINT chk_baseline_samples CHECK
    (origin = 'seed' OR sample_count > 0),
  -- Approval is what scheduling trusts, so it must name someone.
  CONSTRAINT chk_baseline_approval CHECK
    (state <> 'approved'
     OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
) ENGINE=InnoDB COMMENT='Holds approved duration percentiles per scope and environment, seeded by operators and refined from measured samples.';
