-- Upgrade an existing Trihouse development volume to the runtime state and
-- execution-lineage contract defined by db/migrations/001_physical_v1_baseline.sql.
--
-- This migration preserves rows. DDL in MySQL commits implicitly, so take a
-- backup before applying it and run the file exactly once.

USE `trihouse_fms`;

ALTER TABLE jobs
  ADD COLUMN state_reason_code VARCHAR(96) NULL
    COMMENT 'Stable reason code explaining the current job state.' AFTER state,
  ADD COLUMN state_detail VARCHAR(1024) NULL
    COMMENT 'Operator-readable detail for the current job state.' AFTER state_reason_code,
  ADD COLUMN result_code VARCHAR(96) NULL
    COMMENT 'Stable final result code for a terminal job.' AFTER state_detail,
  ADD COLUMN updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6)
    COMMENT 'Timestamp when the updated event occurred.' AFTER completed_at;

ALTER TABLE jobs DROP CHECK chk_jobs_state;

UPDATE jobs
SET state = CASE state
  WHEN 'pending' THEN 'queued'
  WHEN 'planned' THEN 'queued'
  WHEN 'waiting' THEN 'held'
  WHEN 'blocked' THEN 'held'
  WHEN 'safety_hold' THEN 'held'
  ELSE state
END;

ALTER TABLE jobs
  MODIFY COLUMN state VARCHAR(24) NOT NULL DEFAULT 'queued'
    COMMENT 'Job lifecycle status: queued, assigned, running, held, completed, failed, or cancelled.',
  ADD CONSTRAINT chk_jobs_state CHECK (state IN
    ('queued','assigned','running','held','completed','failed','cancelled'));

UPDATE job_steps
SET state = 'pending'
WHERE state IN ('queued', 'on_hold');

ALTER TABLE job_steps DROP CHECK chk_job_steps_state;

ALTER TABLE job_steps
  ADD COLUMN assignment_revision BIGINT UNSIGNED NOT NULL DEFAULT 0
    COMMENT 'Assignment revision used to reject stale execution results.' AFTER assigned_device_id,
  ADD COLUMN rmf_phase_id VARCHAR(128) NULL
    COMMENT 'Open-RMF phase identifier associated with this job step.' AFTER rmf_task_id,
  ADD COLUMN rmf_event_id VARCHAR(128) NULL
    COMMENT 'Open-RMF event identifier associated with this job step.' AFTER rmf_phase_id,
  ADD COLUMN rmf_status VARCHAR(32) NULL
    COMMENT 'Latest Open-RMF task status observed for this job step.' AFTER rmf_event_id,
  ADD COLUMN rmf_status_observed_at DATETIME(6) NULL
    COMMENT 'Timestamp when the latest Open-RMF status was observed.' AFTER rmf_status,
  ADD COLUMN final_outcome_reason_code VARCHAR(96) NULL
    COMMENT 'Stable reason code for the final step outcome.' AFTER failure_reason,
  ADD COLUMN final_method_code VARCHAR(96) NULL
    COMMENT 'Method code used by the final execution attempt.' AFTER final_outcome_reason_code,
  MODIFY COLUMN state VARCHAR(24) NOT NULL DEFAULT 'pending'
    COMMENT 'Job-step status: pending, running, succeeded, failed, or cancelled.',
  ADD CONSTRAINT chk_job_steps_state CHECK (state IN
    ('pending','running','succeeded','failed','cancelled'));

ALTER TABLE operation_events
  ADD COLUMN correlation_uuid CHAR(36) NULL
    COMMENT 'UUID that groups events belonging to the same distributed operation.' AFTER event_uuid,
  ADD COLUMN causation_event_uuid CHAR(36) NULL
    COMMENT 'UUID of the event that directly caused this event.' AFTER correlation_uuid,
  ADD COLUMN attempt_uuid CHAR(36) NULL
    COMMENT 'UUID that identifies one execution attempt across systems.' AFTER causation_event_uuid,
  ADD KEY idx_events_correlation (correlation_uuid, occurred_at),
  ADD KEY idx_events_attempt (attempt_uuid, occurred_at),
  ADD CONSTRAINT fk_events_attempt FOREIGN KEY (attempt_uuid)
    REFERENCES job_step_attempts (attempt_uuid);
