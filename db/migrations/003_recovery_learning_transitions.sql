USE `trihouse_recovery`;

CREATE TABLE recovery_learning_transitions (
  recovery_step_id BIGINT UNSIGNED NOT NULL COMMENT 'Identifier of the executed recovery step represented by this learning transition.',
  schema_version SMALLINT UNSIGNED NOT NULL DEFAULT 1 COMMENT 'Version of the frozen learning-transition contract.',
  state_vector JSON NOT NULL COMMENT 'Nine-element policy state before the executed action.',
  skill_id TINYINT UNSIGNED NOT NULL COMMENT 'Numeric identifier in the frozen five-skill ontology.',
  skill_name VARCHAR(24) NOT NULL COMMENT 'Name paired with the numeric skill identifier.',
  action_vector JSON NOT NULL COMMENT 'Three-element relative action vector containing dx, dy, and dyaw.',
  reward_total DOUBLE NOT NULL COMMENT 'Scalar reward observed after the executed action.',
  next_state_vector JSON NOT NULL COMMENT 'Nine-element policy state observed after the executed action.',
  done TINYINT(1) NOT NULL COMMENT 'Whether the policy episode terminates after this transition.',
  metadata JSON NOT NULL COMMENT 'Lineage and execution facts needed to audit exported training data.',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the learning transition was recorded.',
  PRIMARY KEY (recovery_step_id),
  CONSTRAINT fk_learning_transition_step FOREIGN KEY (recovery_step_id)
    REFERENCES recovery_steps (recovery_step_id) ON DELETE CASCADE,
  CONSTRAINT chk_learning_schema_version CHECK (schema_version = 1),
  CONSTRAINT chk_learning_state_shape CHECK
    (JSON_TYPE(state_vector) = 'ARRAY' AND JSON_LENGTH(state_vector) = 9),
  CONSTRAINT chk_learning_action_shape CHECK
    (JSON_TYPE(action_vector) = 'ARRAY' AND JSON_LENGTH(action_vector) = 3),
  CONSTRAINT chk_learning_next_state_shape CHECK
    (JSON_TYPE(next_state_vector) = 'ARRAY' AND JSON_LENGTH(next_state_vector) = 9),
  CONSTRAINT chk_learning_skill CHECK
    ((skill_id = 0 AND skill_name = 'BACKUP') OR
     (skill_id = 1 AND skill_name = 'REROUTE_LEFT') OR
     (skill_id = 2 AND skill_name = 'REROUTE_RIGHT') OR
     (skill_id = 3 AND skill_name = 'WAIT_REOBSERVE') OR
     (skill_id = 4 AND skill_name = 'REJOIN')),
  CONSTRAINT chk_learning_done CHECK (done IN (0, 1)),
  CONSTRAINT chk_learning_metadata CHECK (JSON_TYPE(metadata) = 'OBJECT')
) ENGINE=InnoDB COMMENT='Stores finalized executed recovery transitions in the exact tuple consumed by offline reinforcement learning.';

CREATE TABLE recovery_ingestion_receipts (
  message_id CHAR(36) NOT NULL COMMENT 'Idempotency UUID supplied by the inference sender.',
  payload_sha256 CHAR(64) NOT NULL COMMENT 'SHA-256 digest of the canonical request payload.',
  message_type VARCHAR(64) NOT NULL COMMENT 'Type of recovery message acknowledged by the Gateway.',
  resource_key VARCHAR(160) NOT NULL COMMENT 'Stable domain resource addressed by the message.',
  response_payload JSON NOT NULL COMMENT 'Original acknowledgement returned for an identical retry.',
  processed_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the message transaction committed.',
  PRIMARY KEY (message_id),
  CONSTRAINT chk_recovery_receipt_message_id CHECK
    (message_id REGEXP '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'),
  CONSTRAINT chk_recovery_receipt_sha256 CHECK
    (payload_sha256 REGEXP '^[0-9a-f]{64}$'),
  CONSTRAINT chk_recovery_receipt_response CHECK
    (JSON_TYPE(response_payload) = 'OBJECT')
) ENGINE=InnoDB COMMENT='Stores durable application acknowledgements for idempotent recovery-message ingestion.';
