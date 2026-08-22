USE `trihouse_recovery`;

CREATE TABLE recovery_proposals (
  proposal_id CHAR(36) NOT NULL,
  recovery_episode_uuid CHAR(36) NOT NULL,
  step_no SMALLINT UNSIGNED NOT NULL,
  device_id VARCHAR(64) NOT NULL,
  map_name VARCHAR(96) NOT NULL,
  map_revision VARCHAR(128) NOT NULL,
  trigger_type VARCHAR(24) NOT NULL,
  state_schema_id VARCHAR(64) NOT NULL,
  named_state JSON NOT NULL,
  perception_evidence JSON NOT NULL,
  vlm_lineage JSON NOT NULL,
  policy_lineage JSON NOT NULL,
  candidate_evidence JSON NOT NULL,
  selected_skill_id TINYINT UNSIGNED NOT NULL,
  selected_skill_name VARCHAR(24) NOT NULL,
  action_family VARCHAR(16) NOT NULL,
  selected_coord JSON NOT NULL,
  canonical_action JSON NOT NULL,
  safety_gate_enabled TINYINT(1) NOT NULL,
  request_sha256 CHAR(64) NOT NULL,
  proposal_sha256 CHAR(64) NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'pending',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  decided_at DATETIME(6) NULL,
  PRIMARY KEY (proposal_id),
  UNIQUE KEY uq_recovery_proposal_step (recovery_episode_uuid, step_no),
  KEY idx_recovery_proposal_status (status, created_at),
  CONSTRAINT chk_recovery_proposal_state_schema CHECK
    (state_schema_id = 'trihouse.recovery-state.v1'),
  CONSTRAINT chk_recovery_proposal_json CHECK
    (JSON_TYPE(named_state) = 'OBJECT'
     AND JSON_TYPE(perception_evidence) = 'ARRAY'
     AND JSON_LENGTH(perception_evidence) > 0
     AND JSON_TYPE(vlm_lineage) = 'OBJECT'
     AND JSON_TYPE(policy_lineage) = 'OBJECT'
     AND JSON_TYPE(candidate_evidence) = 'ARRAY'
     AND JSON_TYPE(selected_coord) = 'ARRAY' AND JSON_LENGTH(selected_coord) = 3
     AND JSON_TYPE(canonical_action) = 'OBJECT'),
  CONSTRAINT chk_recovery_proposal_skill CHECK
    ((selected_skill_id = 0 AND selected_skill_name = 'BACKUP' AND action_family = 'retreat') OR
     (selected_skill_id = 1 AND selected_skill_name = 'REROUTE_LEFT' AND action_family = 'detour') OR
     (selected_skill_id = 2 AND selected_skill_name = 'REROUTE_RIGHT' AND action_family = 'detour') OR
     (selected_skill_id = 3 AND selected_skill_name = 'WAIT_REOBSERVE' AND action_family = 'wait') OR
     (selected_skill_id = 4 AND selected_skill_name = 'REJOIN' AND action_family = 'rejoin')),
  CONSTRAINT chk_recovery_proposal_safety CHECK (safety_gate_enabled IN (0, 1)),
  CONSTRAINT chk_recovery_proposal_status CHECK (status IN ('pending','approved','rejected','expired')),
  CONSTRAINT chk_recovery_proposal_hashes CHECK
    (request_sha256 REGEXP '^[0-9a-f]{64}$' AND proposal_sha256 REGEXP '^[0-9a-f]{64}$')
) ENGINE=InnoDB COMMENT='Stores bounded recovery proposals and complete inference evidence before human approval.';

CREATE TABLE recovery_approval_decisions (
  approval_id CHAR(36) NOT NULL,
  proposal_id CHAR(36) NOT NULL,
  worker_id VARCHAR(64) NOT NULL,
  decision VARCHAR(16) NOT NULL,
  reason VARCHAR(1024) NOT NULL,
  proposal_sha256 CHAR(64) NOT NULL,
  decided_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (approval_id),
  UNIQUE KEY uq_recovery_approval_proposal (proposal_id),
  CONSTRAINT fk_recovery_approval_proposal FOREIGN KEY (proposal_id)
    REFERENCES recovery_proposals (proposal_id) ON DELETE CASCADE,
  CONSTRAINT chk_recovery_approval_decision CHECK (decision IN ('approved','rejected')),
  CONSTRAINT chk_recovery_approval_reason CHECK (CHAR_LENGTH(TRIM(reason)) > 0),
  CONSTRAINT chk_recovery_approval_hash CHECK (proposal_sha256 REGEXP '^[0-9a-f]{64}$')
) ENGINE=InnoDB COMMENT='Records the accountable operator decision bound to an immutable recovery proposal hash.';

CREATE TABLE recovery_command_outbox (
  command_id CHAR(36) NOT NULL,
  proposal_id CHAR(36) NOT NULL,
  approval_id CHAR(36) NOT NULL,
  device_id VARCHAR(64) NOT NULL,
  payload JSON NOT NULL,
  payload_sha256 CHAR(64) NOT NULL,
  delivery_status VARCHAR(16) NOT NULL DEFAULT 'pending',
  attempt_count INT UNSIGNED NOT NULL DEFAULT 0,
  next_attempt_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  delivered_at DATETIME(6) NULL,
  acknowledged_at DATETIME(6) NULL,
  last_error VARCHAR(1024) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (command_id),
  UNIQUE KEY uq_recovery_command_proposal (proposal_id),
  KEY idx_recovery_command_delivery (delivery_status, next_attempt_at),
  CONSTRAINT fk_recovery_command_proposal FOREIGN KEY (proposal_id)
    REFERENCES recovery_proposals (proposal_id) ON DELETE CASCADE,
  CONSTRAINT fk_recovery_command_approval FOREIGN KEY (approval_id)
    REFERENCES recovery_approval_decisions (approval_id) ON DELETE CASCADE,
  CONSTRAINT chk_recovery_command_payload CHECK (JSON_TYPE(payload) = 'OBJECT'),
  CONSTRAINT chk_recovery_command_hash CHECK (payload_sha256 REGEXP '^[0-9a-f]{64}$'),
  CONSTRAINT chk_recovery_command_delivery CHECK
    (delivery_status IN ('pending','sent','acknowledged','failed'))
) ENGINE=InnoDB COMMENT='Queues approved recovery commands for application-acknowledged delivery by device_id.';

CREATE TABLE recovery_execution_results (
  command_id CHAR(36) NOT NULL,
  device_id VARCHAR(64) NOT NULL,
  proposal_sha256 CHAR(64) NOT NULL,
  execution_status VARCHAR(16) NOT NULL,
  success TINYINT(1) NOT NULL,
  result_payload JSON NOT NULL,
  result_sha256 CHAR(64) NOT NULL,
  received_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (command_id),
  CONSTRAINT fk_recovery_execution_command FOREIGN KEY (command_id)
    REFERENCES recovery_command_outbox (command_id) ON DELETE CASCADE,
  CONSTRAINT chk_recovery_execution_status CHECK
    (execution_status IN ('succeeded','failed','cancelled')),
  CONSTRAINT chk_recovery_execution_success CHECK (success IN (0, 1)),
  CONSTRAINT chk_recovery_execution_payload CHECK (JSON_TYPE(result_payload) = 'OBJECT'),
  CONSTRAINT chk_recovery_execution_hashes CHECK
    (proposal_sha256 REGEXP '^[0-9a-f]{64}$' AND result_sha256 REGEXP '^[0-9a-f]{64}$')
) ENGINE=InnoDB COMMENT='Stores one idempotent ExecuteRecovery result returned by the authenticated Pinky session.';
