-- Replace table and column comments with English metadata in an existing v4 database.
-- This migration changes metadata only and does not delete application data.

ALTER TABLE `trihouse_fms`.`locations`
  COMMENT = 'Manages warehouse racks, slots, docks, chargers, workstations, safety nodes, and RMF waypoints.';

ALTER TABLE `trihouse_fms`.`locations`
  MODIFY COLUMN location_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related location.',
  MODIFY COLUMN parent_location_id BIGINT UNSIGNED NULL COMMENT 'Identifier of the related parent location.',
  MODIFY COLUMN location_code      VARCHAR(96) NOT NULL COMMENT 'Business code for location.',
  MODIFY COLUMN name               VARCHAR(160) NULL COMMENT 'Location name displayed in operator interfaces.',
  MODIFY COLUMN location_type      VARCHAR(32) NOT NULL COMMENT 'Code identifying the location type.',
  MODIFY COLUMN zone_code          VARCHAR(64) NULL COMMENT 'Business code for zone.',
  MODIFY COLUMN temperature_zone   VARCHAR(16) NULL COMMENT 'Temperature zone for this record.',
  MODIFY COLUMN map_name           VARCHAR(96) NULL COMMENT 'Name of the map.',
  MODIFY COLUMN rmf_waypoint_name  VARCHAR(128) NULL COMMENT 'Name of the rmf waypoint.',
  MODIFY COLUMN pose_x             DOUBLE NULL COMMENT 'X coordinate in the map frame, in meters.',
  MODIFY COLUMN pose_y             DOUBLE NULL COMMENT 'Y coordinate in the map frame, in meters.',
  MODIFY COLUMN pose_yaw           DOUBLE NULL COMMENT 'Heading in the map frame, in radians.',
  MODIFY COLUMN state              VARCHAR(24) NOT NULL DEFAULT 'available' COMMENT 'Current location status: available, reserved, occupied, blocked, or maintenance.',
  MODIFY COLUMN metadata           JSON NULL COMMENT 'JSON object containing location-specific attributes and external integration values.';

ALTER TABLE `trihouse_fms`.`map_features`
  COMMENT = 'Manages spatial data for markers, static obstacles, bottlenecks, doors, and restricted areas by map revision.';

ALTER TABLE `trihouse_fms`.`map_features`
  MODIFY COLUMN feature_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related feature.',
  MODIFY COLUMN map_name            VARCHAR(96) NOT NULL COMMENT 'Name of the map.',
  MODIFY COLUMN map_revision        VARCHAR(128) NOT NULL COMMENT 'Map revision for this record.',
  MODIFY COLUMN feature_code        VARCHAR(128) NOT NULL COMMENT 'Business code for feature.',
  MODIFY COLUMN feature_type        VARCHAR(24) NOT NULL COMMENT 'Code identifying the feature type.',
  MODIFY COLUMN location_id         BIGINT UNSIGNED NULL COMMENT 'Identifier of the related location.',
  MODIFY COLUMN marker_code         INT UNSIGNED NULL COMMENT 'Business code for marker.',
  MODIFY COLUMN geometry            JSON NOT NULL COMMENT 'JSON geometry describing a point, line, or polygon in map coordinates.',
  MODIFY COLUMN properties          JSON NULL COMMENT 'JSON object containing additional properties data.',
  MODIFY COLUMN active              TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'Indicates whether this feature is used by operating rules for the map revision.';

ALTER TABLE `trihouse_fms`.`workers`
  COMMENT = 'Manages worker accounts and permission scopes for control requests, manual recovery, and safety release actions.';

ALTER TABLE `trihouse_fms`.`workers`
  MODIFY COLUMN worker_id          VARCHAR(64) NOT NULL COMMENT 'Identifier of the related worker.',
  MODIFY COLUMN worker_code        VARCHAR(64) NOT NULL COMMENT 'Business code for worker.',
  MODIFY COLUMN name               VARCHAR(128) NOT NULL COMMENT 'Worker name displayed in operator interfaces and audit records.',
  MODIFY COLUMN role               VARCHAR(32) NOT NULL COMMENT 'Role for this record.',
  MODIFY COLUMN external_auth_id   VARCHAR(128) NULL COMMENT 'Identifier of the related external auth.',
  MODIFY COLUMN allowed_zones      JSON NULL COMMENT 'JSON array of zone codes the worker may access or operate.',
  MODIFY COLUMN active             TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'Indicates whether this worker account may participate in job requests and approvals.',
  MODIFY COLUMN registered_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the registered event occurred.',
  MODIFY COLUMN retired_at         DATETIME(6) NULL COMMENT 'Timestamp when the retired event occurred.';

ALTER TABLE `trihouse_fms`.`devices`
  COMMENT = 'Manages models, fleets, locations, control modes, and capabilities for Pinky mobile robots and OMX robot arms.';

ALTER TABLE `trihouse_fms`.`devices`
  MODIFY COLUMN device_id            VARCHAR(64) NOT NULL COMMENT 'Identifier of the related device.',
  MODIFY COLUMN device_type          VARCHAR(16) NOT NULL COMMENT 'Code identifying the device type.',
  MODIFY COLUMN name                 VARCHAR(128) NOT NULL COMMENT 'Device name displayed in operator interfaces.',
  MODIFY COLUMN model                VARCHAR(96) NOT NULL COMMENT 'Model for this record.',
  MODIFY COLUMN fleet_name           VARCHAR(96) NULL COMMENT 'Name of the fleet.',
  MODIFY COLUMN home_location_id     BIGINT UNSIGNED NULL COMMENT 'Identifier of the related home location.',
  MODIFY COLUMN current_location_id  BIGINT UNSIGNED NULL COMMENT 'Identifier of the related current location.',
  MODIFY COLUMN control_mode         VARCHAR(24) NOT NULL DEFAULT 'automatic' COMMENT 'Device control mode, such as automatic, manual, offline, maintenance, or safety stop.',
  MODIFY COLUMN active               TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'Indicates whether this device is eligible for dispatch and job assignment.',
  MODIFY COLUMN capabilities         JSON NULL COMMENT 'JSON object describing actions and features supported by the device.',
  MODIFY COLUMN registered_at        DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the registered event occurred.',
  MODIFY COLUMN retired_at           DATETIME(6) NULL COMMENT 'Timestamp when the retired event occurred.';

ALTER TABLE `trihouse_fms`.`inventory_lots`
  COMMENT = 'Manages storage location, expiration date, available quantity, reserved quantity, and status for each inventory lot.';

ALTER TABLE `trihouse_fms`.`inventory_lots`
  MODIFY COLUMN lot_id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related lot.',
  MODIFY COLUMN product_code       VARCHAR(96) NOT NULL COMMENT 'Business code for product.',
  MODIFY COLUMN lot_code           VARCHAR(128) NOT NULL COMMENT 'Business code for lot.',
  MODIFY COLUMN item_name          VARCHAR(160) NULL COMMENT 'Name of the item.',
  MODIFY COLUMN temperature_zone   VARCHAR(16) NOT NULL COMMENT 'Temperature zone for this record.',
  MODIFY COLUMN location_id        BIGINT UNSIGNED NULL COMMENT 'Identifier of the related location.',
  MODIFY COLUMN expiry_date        DATE NOT NULL COMMENT 'Expiry date for this record.',
  MODIFY COLUMN unit_weight_kg     DECIMAL(10,3) NULL COMMENT 'Weight of one product unit in kilograms.',
  MODIFY COLUMN available_qty      INT NOT NULL DEFAULT 0 COMMENT 'Total physical quantity currently held in the inventory lot.',
  MODIFY COLUMN reserved_qty       INT NOT NULL DEFAULT 0 COMMENT 'Quantity for reserved.',
  MODIFY COLUMN state              VARCHAR(24) NOT NULL DEFAULT 'stored' COMMENT 'Inventory-lot status, such as pending receipt, stored, held, depleted, expired, or damaged.',
  MODIFY COLUMN received_at        DATETIME(6) NULL COMMENT 'Timestamp when the received event occurred.',
  MODIFY COLUMN updated_at         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                         ON UPDATE CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the updated event occurred.';

ALTER TABLE `trihouse_fms`.`jobs`
  COMMENT = 'Manages the full lifecycle of inbound, outbound, transfer, replenishment, disposal, recovery, and emergency jobs.';

ALTER TABLE `trihouse_fms`.`jobs`
  MODIFY COLUMN job_id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related job.',
  MODIFY COLUMN parent_job_id        BIGINT UNSIGNED NULL COMMENT 'Identifier of the related parent job.',
  MODIFY COLUMN job_code             VARCHAR(64) NOT NULL COMMENT 'Business code for job.',
  MODIFY COLUMN operation_type       VARCHAR(24) NOT NULL COMMENT 'Code identifying the operation type.',
  MODIFY COLUMN priority             VARCHAR(16) NOT NULL DEFAULT 'normal' COMMENT 'Job priority code: critical, high, normal, or low.',
  MODIFY COLUMN priority_rank        TINYINT UNSIGNED GENERATED ALWAYS AS (
      CASE priority
        WHEN 'critical' THEN 1
        WHEN 'high' THEN 2
        WHEN 'normal' THEN 3
        WHEN 'low' THEN 4
      END
    ) STORED COMMENT 'Automatically calculated numeric value used to sort priorities.',
  MODIFY COLUMN state                VARCHAR(24) NOT NULL DEFAULT 'pending' COMMENT 'Job lifecycle status from pending and planning through execution, completion, failure, cancellation, or safety hold.',
  MODIFY COLUMN revision             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Optimistic-lock version used to detect concurrent updates.',
  MODIFY COLUMN requested_by         VARCHAR(64) NULL COMMENT 'Requested by for this record.',
  MODIFY COLUMN external_reference   VARCHAR(128) NULL COMMENT 'External reference for this record.',
  MODIFY COLUMN source_location_id   BIGINT UNSIGNED NULL COMMENT 'Identifier of the related source location.',
  MODIFY COLUMN destination_location_id BIGINT UNSIGNED NULL COMMENT 'Identifier of the related destination location.',
  MODIFY COLUMN due_at               DATETIME(6) NULL COMMENT 'Timestamp when the due event occurred.',
  MODIFY COLUMN assigned_mobile_id   VARCHAR(64) NULL COMMENT 'Identifier of the related assigned mobile.',
  MODIFY COLUMN failure_reason       VARCHAR(512) NULL COMMENT 'Specific reason the job or execution step failed.',
  MODIFY COLUMN context              JSON NULL COMMENT 'JSON object containing the job origin and extended context from external requests.',
  MODIFY COLUMN created_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the created event occurred.',
  MODIFY COLUMN started_at           DATETIME(6) NULL COMMENT 'Timestamp when the started event occurred.',
  MODIFY COLUMN completed_at         DATETIME(6) NULL COMMENT 'Timestamp when the completed event occurred.';

ALTER TABLE `trihouse_fms`.`job_items`
  COMMENT = 'Manages products, requested and completed quantities, assigned lots, and verification status for each job.';

ALTER TABLE `trihouse_fms`.`job_items`
  MODIFY COLUMN job_item_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related job item.',
  MODIFY COLUMN job_id              BIGINT UNSIGNED NOT NULL COMMENT 'Identifier of the related job.',
  MODIFY COLUMN product_code        VARCHAR(96) NOT NULL COMMENT 'Business code for product.',
  MODIFY COLUMN requested_qty       INT NOT NULL COMMENT 'Quantity for requested.',
  MODIFY COLUMN completed_qty       INT NOT NULL DEFAULT 0 COMMENT 'Quantity for completed.',
  MODIFY COLUMN lot_id              BIGINT UNSIGNED NULL COMMENT 'Identifier of the related lot.',
  MODIFY COLUMN handling_unit_code  VARCHAR(128) NULL COMMENT 'Business code for handling unit.',
  MODIFY COLUMN verification_state  VARCHAR(24) NOT NULL DEFAULT 'pending' COMMENT 'Verification state for this record.',
  MODIFY COLUMN metadata            JSON NULL COMMENT 'JSON object containing item-specific verification and external-order values.';

ALTER TABLE `trihouse_fms`.`job_steps`
  COMMENT = 'Manages ordered execution steps for Pinky movement, OMX manipulation, verification, and handoff operations.';

ALTER TABLE `trihouse_fms`.`job_steps`
  MODIFY COLUMN job_step_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related job step.',
  MODIFY COLUMN job_id               BIGINT UNSIGNED NOT NULL COMMENT 'Identifier of the related job.',
  MODIFY COLUMN step_no              SMALLINT UNSIGNED NOT NULL COMMENT 'Execution order within the same job or recovery episode.',
  MODIFY COLUMN executor_type        VARCHAR(16) NOT NULL COMMENT 'Code identifying the executor type.',
  MODIFY COLUMN assigned_device_id   VARCHAR(64) NULL COMMENT 'Identifier of the related assigned device.',
  MODIFY COLUMN action_type          VARCHAR(32) NOT NULL COMMENT 'Code identifying the action type.',
  MODIFY COLUMN target_location_id   BIGINT UNSIGNED NULL COMMENT 'Identifier of the related target location.',
  MODIFY COLUMN state                VARCHAR(24) NOT NULL DEFAULT 'pending' COMMENT 'Job-step status: pending, queued, running, succeeded, failed, held, or cancelled.',
  MODIFY COLUMN rmf_task_id          VARCHAR(128) NULL COMMENT 'Identifier of the related rmf task.',
  MODIFY COLUMN policy_name          VARCHAR(128) NULL COMMENT 'Name of the policy.',
  MODIFY COLUMN policy_version       VARCHAR(128) NULL COMMENT 'Policy version for this record.',
  MODIFY COLUMN retry_count          SMALLINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Total number of retries for this job step.',
  MODIFY COLUMN failure_reason       VARCHAR(512) NULL COMMENT 'Specific reason the job or execution step failed.',
  MODIFY COLUMN input                JSON NULL COMMENT 'JSON object containing additional input data.',
  MODIFY COLUMN result               JSON NULL COMMENT 'JSON object containing additional result data.',
  MODIFY COLUMN started_at           DATETIME(6) NULL COMMENT 'Timestamp when the started event occurred.',
  MODIFY COLUMN completed_at         DATETIME(6) NULL COMMENT 'Timestamp when the completed event occurred.';

ALTER TABLE `trihouse_fms`.`reservations`
  COMMENT = 'Manages access to bottlenecks and exclusive or time-based reservations for docks, workstations, and devices.';

ALTER TABLE `trihouse_fms`.`reservations`
  MODIFY COLUMN reservation_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related reservation.',
  MODIFY COLUMN job_id               BIGINT UNSIGNED NOT NULL COMMENT 'Identifier of the related job.',
  MODIFY COLUMN job_step_id          BIGINT UNSIGNED NULL COMMENT 'Identifier of the related job step.',
  MODIFY COLUMN location_id          BIGINT UNSIGNED NULL COMMENT 'Identifier of the related location.',
  MODIFY COLUMN device_id            VARCHAR(64) NULL COMMENT 'Identifier of the related device.',
  MODIFY COLUMN map_feature_id       BIGINT UNSIGNED NULL COMMENT 'Identifier of the related map feature.',
  MODIFY COLUMN reservation_mode     VARCHAR(24) NOT NULL DEFAULT 'exclusive_lock' COMMENT 'Reservation mode for this record.',
  MODIFY COLUMN state                VARCHAR(16) NOT NULL DEFAULT 'reserved' COMMENT 'Reservation status: reserved, in use, released, expired, or cancelled.',
  MODIFY COLUMN planned_start_at     DATETIME(6) NULL COMMENT 'Timestamp when the planned start event occurred.',
  MODIFY COLUMN planned_end_at       DATETIME(6) NULL COMMENT 'Timestamp when the planned end event occurred.',
  MODIFY COLUMN entered_at           DATETIME(6) NULL COMMENT 'Timestamp when the entered event occurred.',
  MODIFY COLUMN exited_at            DATETIME(6) NULL COMMENT 'Timestamp when the exited event occurred.',
  MODIFY COLUMN expires_at           DATETIME(6) NOT NULL COMMENT 'Timestamp when the expires event occurred.',
  MODIFY COLUMN created_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the created event occurred.',
  MODIFY COLUMN released_at          DATETIME(6) NULL COMMENT 'Timestamp when the released event occurred.',
  MODIFY COLUMN active_resource_key  VARCHAR(160) GENERATED ALWAYS AS (
      CASE
        WHEN reservation_mode = 'bottleneck_lock'
         AND state IN ('reserved','in_use')
          THEN CONCAT('feature:', map_feature_id)
        WHEN reservation_mode = 'exclusive_lock'
         AND state IN ('reserved','in_use')
          THEN CASE WHEN location_id IS NOT NULL THEN CONCAT('location:', location_id)
                    ELSE CONCAT('device:', device_id) END
        WHEN reservation_mode = 'time_slot'
         AND state = 'in_use'
          THEN CASE WHEN location_id IS NOT NULL THEN CONCAT('location:', location_id)
                    ELSE CONCAT('device:', device_id) END
        ELSE NULL
      END
    ) STORED COMMENT 'Calculated unique key that prevents conflicting active resource reservations.';

ALTER TABLE `trihouse_fms`.`inventory_moves`
  COMMENT = 'Records immutable inventory and reservation quantity changes, resulting balances, reasons, and responsible actors.';

ALTER TABLE `trihouse_fms`.`inventory_moves`
  MODIFY COLUMN inventory_move_id    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related inventory move.',
  MODIFY COLUMN lot_id               BIGINT UNSIGNED NOT NULL COMMENT 'Identifier of the related lot.',
  MODIFY COLUMN job_id               BIGINT UNSIGNED NULL COMMENT 'Identifier of the related job.',
  MODIFY COLUMN job_step_id          BIGINT UNSIGNED NULL COMMENT 'Identifier of the related job step.',
  MODIFY COLUMN move_type            VARCHAR(24) NOT NULL COMMENT 'Code identifying the move type.',
  MODIFY COLUMN quantity_delta       INT NOT NULL COMMENT 'Amount added to or removed from the available quantity.',
  MODIFY COLUMN quantity_after       INT NOT NULL COMMENT 'Available quantity after applying the inventory movement.',
  MODIFY COLUMN reserved_delta       INT NOT NULL DEFAULT 0 COMMENT 'Amount added to or removed from the reserved quantity.',
  MODIFY COLUMN reserved_after       INT NOT NULL DEFAULT 0 COMMENT 'Reserved quantity after applying the inventory movement.',
  MODIFY COLUMN recorded_by          VARCHAR(96) NOT NULL COMMENT 'Recorded by for this record.',
  MODIFY COLUMN recorded_at          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the recorded event occurred.',
  MODIFY COLUMN note                 VARCHAR(512) NULL COMMENT 'Additional explanation for the inventory movement.';

ALTER TABLE `trihouse_fms`.`device_states`
  COMMENT = 'Stores the latest heartbeat, location, battery level, progress, health, and active step for each device.';

ALTER TABLE `trihouse_fms`.`device_states`
  MODIFY COLUMN device_id            VARCHAR(64) NOT NULL COMMENT 'Identifier of the related device.',
  MODIFY COLUMN observed_at          DATETIME(6) NOT NULL COMMENT 'Timestamp when the observed event occurred.',
  MODIFY COLUMN state                VARCHAR(24) NOT NULL COMMENT 'Current operating-state code reported by the device.',
  MODIFY COLUMN health               VARCHAR(16) NOT NULL DEFAULT 'ok' COMMENT 'Device health code, such as healthy, warning, error, or unreachable.',
  MODIFY COLUMN current_job_step_id  BIGINT UNSIGNED NULL COMMENT 'Identifier of the related current job step.',
  MODIFY COLUMN pose_x               DOUBLE NULL COMMENT 'X coordinate in the map frame, in meters.',
  MODIFY COLUMN pose_y               DOUBLE NULL COMMENT 'Y coordinate in the map frame, in meters.',
  MODIFY COLUMN pose_yaw             DOUBLE NULL COMMENT 'Heading in the map frame, in radians.',
  MODIFY COLUMN battery_pct          DECIMAL(5,2) NULL COMMENT 'Remaining battery percentage reported by the device.',
  MODIFY COLUMN progress             DECIMAL(5,4) NULL COMMENT 'Progress of the current job step, from 0 through 1.',
  MODIFY COLUMN details              JSON NULL COMMENT 'JSON object containing additional details data.';

ALTER TABLE `trihouse_fms`.`integration_messages`
  COMMENT = 'Manages idempotency, retries, and delivery status for commands and responses exchanged with RMF, Pinky, and OMX.';

ALTER TABLE `trihouse_fms`.`integration_messages`
  MODIFY COLUMN message_id           CHAR(36) NOT NULL COMMENT 'Identifier of the related message.',
  MODIFY COLUMN direction            VARCHAR(8) NOT NULL COMMENT 'Message direction: inbound or outbound.',
  MODIFY COLUMN channel              VARCHAR(16) NOT NULL COMMENT 'Channel for this record.',
  MODIFY COLUMN device_id            VARCHAR(64) NULL COMMENT 'Identifier of the related device.',
  MODIFY COLUMN job_step_id          BIGINT UNSIGNED NULL COMMENT 'Identifier of the related job step.',
  MODIFY COLUMN message_type         VARCHAR(64) NOT NULL COMMENT 'Code identifying the message type.',
  MODIFY COLUMN idempotency_key      VARCHAR(160) NOT NULL COMMENT 'Business key that prevents duplicate execution of the same request.',
  MODIFY COLUMN external_reference   VARCHAR(160) NULL COMMENT 'External reference for this record.',
  MODIFY COLUMN state                VARCHAR(16) NOT NULL DEFAULT 'pending' COMMENT 'Message status: pending, sent, acknowledged, failed, or dead.',
  MODIFY COLUMN attempts             SMALLINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Total number of message delivery attempts.',
  MODIFY COLUMN next_attempt_at      DATETIME(6) NULL COMMENT 'Timestamp when the next attempt event occurred.',
  MODIFY COLUMN payload              JSON NOT NULL COMMENT 'JSON object containing additional payload data.',
  MODIFY COLUMN last_error           VARCHAR(512) NULL COMMENT 'Last error for this record.',
  MODIFY COLUMN created_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the created event occurred.',
  MODIFY COLUMN sent_at              DATETIME(6) NULL COMMENT 'Timestamp when the sent event occurred.',
  MODIFY COLUMN acknowledged_at      DATETIME(6) NULL COMMENT 'Timestamp when the acknowledged event occurred.';

ALTER TABLE `trihouse_fms`.`incidents`
  COMMENT = 'Manages safety incidents from detection through resolution, including people, fall risks, collision risks, and emergency stops.';

ALTER TABLE `trihouse_fms`.`incidents`
  MODIFY COLUMN incident_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related incident.',
  MODIFY COLUMN incident_code        VARCHAR(64) NOT NULL COMMENT 'Business code for incident.',
  MODIFY COLUMN incident_type        VARCHAR(32) NOT NULL COMMENT 'Code identifying the incident type.',
  MODIFY COLUMN severity             VARCHAR(16) NOT NULL COMMENT 'Severity for this record.',
  MODIFY COLUMN state                VARCHAR(24) NOT NULL DEFAULT 'active' COMMENT 'Safety-incident status: open, acknowledged, mitigating, resolved, or closed.',
  MODIFY COLUMN location_id          BIGINT UNSIGNED NULL COMMENT 'Identifier of the related location.',
  MODIFY COLUMN geometry             JSON NULL COMMENT 'JSON geometry describing the point or area affected by the safety incident.',
  MODIFY COLUMN description          VARCHAR(512) NOT NULL COMMENT 'Operator-readable description of the cause and circumstances of the safety incident.',
  MODIFY COLUMN raised_by_worker_id  VARCHAR(64) NULL COMMENT 'Identifier of the related raised by worker.',
  MODIFY COLUMN acknowledged_by_worker_id VARCHAR(64) NULL COMMENT 'Identifier of the related acknowledged by worker.',
  MODIFY COLUMN resolved_by_worker_id VARCHAR(64) NULL COMMENT 'Identifier of the related resolved by worker.',
  MODIFY COLUMN raised_at            DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the raised event occurred.',
  MODIFY COLUMN acknowledged_at      DATETIME(6) NULL COMMENT 'Timestamp when the acknowledged event occurred.',
  MODIFY COLUMN resolved_at          DATETIME(6) NULL COMMENT 'Timestamp when the resolved event occurred.',
  MODIFY COLUMN context              JSON NULL COMMENT 'JSON object containing sensor observations, response procedures, and other incident details.';

ALTER TABLE `trihouse_fms`.`operation_events`
  COMMENT = 'Records chronological audit events for jobs, devices, safety decisions, model decisions, and operator actions.';

ALTER TABLE `trihouse_fms`.`operation_events`
  MODIFY COLUMN event_id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related event.',
  MODIFY COLUMN event_uuid           CHAR(36) NOT NULL COMMENT 'UUID of the related event.',
  MODIFY COLUMN occurred_at          DATETIME(6) NOT NULL COMMENT 'Timestamp when the occurred event occurred.',
  MODIFY COLUMN actor_worker_id      VARCHAR(64) NULL COMMENT 'Identifier of the related actor worker.',
  MODIFY COLUMN device_id            VARCHAR(64) NULL COMMENT 'Identifier of the related device.',
  MODIFY COLUMN job_id               BIGINT UNSIGNED NULL COMMENT 'Identifier of the related job.',
  MODIFY COLUMN job_step_id          BIGINT UNSIGNED NULL COMMENT 'Identifier of the related job step.',
  MODIFY COLUMN incident_id          BIGINT UNSIGNED NULL COMMENT 'Identifier of the related incident.',
  MODIFY COLUMN severity             VARCHAR(16) NOT NULL DEFAULT 'info' COMMENT 'Severity for this record.',
  MODIFY COLUMN category             VARCHAR(24) NOT NULL COMMENT 'Category for this record.',
  MODIFY COLUMN event_type           VARCHAR(96) NOT NULL COMMENT 'Code identifying the event type.',
  MODIFY COLUMN message              VARCHAR(512) NULL COMMENT 'Operator-readable summary of the operation event.',
  MODIFY COLUMN model_name           VARCHAR(128) NULL COMMENT 'Name of the model.',
  MODIFY COLUMN model_version        VARCHAR(128) NULL COMMENT 'Model version for this record.',
  MODIFY COLUMN confidence           DECIMAL(6,5) NULL COMMENT 'Model confidence value from 0 through 1.',
  MODIFY COLUMN safety_decision      VARCHAR(16) NULL COMMENT 'Safety decision for this record.',
  MODIFY COLUMN payload              JSON NULL COMMENT 'JSON object containing detailed observations and decision evidence for the event type.';

ALTER TABLE `trihouse_fms`.`artifacts`
  COMMENT = 'Manages storage locations and integrity metadata for videos, images, rosbags, episodes, datasets, models, and reports.';

ALTER TABLE `trihouse_fms`.`artifacts`
  MODIFY COLUMN artifact_id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related artifact.',
  MODIFY COLUMN artifact_type         VARCHAR(24) NOT NULL COMMENT 'Code identifying the artifact type.',
  MODIFY COLUMN storage_uri           VARCHAR(1024) NOT NULL COMMENT 'URI of the stored storage data.',
  MODIFY COLUMN storage_uri_hash      BINARY(32) GENERATED ALWAYS AS
                            (UNHEX(SHA2(storage_uri, 256))) STORED COMMENT 'Storage uri hash for this record.',
  MODIFY COLUMN sha256                CHAR(64) NOT NULL COMMENT 'SHA-256 hash used to verify the integrity of the sha256.',
  MODIFY COLUMN mime_type             VARCHAR(128) NULL COMMENT 'Code identifying the mime type.',
  MODIFY COLUMN byte_size             BIGINT UNSIGNED NULL COMMENT 'Byte size for this record.',
  MODIFY COLUMN device_id             VARCHAR(64) NULL COMMENT 'Identifier of the related device.',
  MODIFY COLUMN job_id                BIGINT UNSIGNED NULL COMMENT 'Identifier of the related job.',
  MODIFY COLUMN job_step_id           BIGINT UNSIGNED NULL COMMENT 'Identifier of the related job step.',
  MODIFY COLUMN event_id              BIGINT UNSIGNED NULL COMMENT 'Identifier of the related event.',
  MODIFY COLUMN model_name            VARCHAR(128) NULL COMMENT 'Name of the model.',
  MODIFY COLUMN model_version         VARCHAR(128) NULL COMMENT 'Model version for this record.',
  MODIFY COLUMN metadata              JSON NULL COMMENT 'JSON object containing artifact-specific details such as codec, resolution, and dataset split.',
  MODIFY COLUMN captured_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the captured event occurred.';

ALTER TABLE `trihouse_fms`.`location_recovery_profiles`
  COMMENT = 'Manages recovery roles, availability, and beta-distribution reliability values for each safety node.';

ALTER TABLE `trihouse_fms`.`location_recovery_profiles`
  MODIFY COLUMN reference_node_uuid    CHAR(36) NOT NULL COMMENT 'UUID of the related reference node.',
  MODIFY COLUMN location_id            BIGINT UNSIGNED NOT NULL COMMENT 'Identifier of the related location.',
  MODIFY COLUMN map_revision           VARCHAR(128) NOT NULL COMMENT 'Map revision for this record.',
  MODIFY COLUMN recovery_roles         JSON NOT NULL COMMENT 'Recovery roles for this record.',
  MODIFY COLUMN availability_status    VARCHAR(16) NOT NULL DEFAULT 'active' COMMENT 'Current availability status code.',
  MODIFY COLUMN reliability_alpha      DECIMAL(12,4) NOT NULL DEFAULT 1.0000 COMMENT 'Accumulated beta-distribution alpha value for successful recovery-node outcomes.',
  MODIFY COLUMN reliability_beta       DECIMAL(12,4) NOT NULL DEFAULT 1.0000 COMMENT 'Accumulated beta-distribution beta value for failed recovery-node outcomes.',
  MODIFY COLUMN last_verified_at       DATETIME(6) NULL COMMENT 'Timestamp when the last verified event occurred.',
  MODIFY COLUMN last_outcome_at        DATETIME(6) NULL COMMENT 'Timestamp when the last outcome event occurred.',
  MODIFY COLUMN reviewed_by_worker_id  VARCHAR(64) NULL COMMENT 'Identifier of the related reviewed by worker.',
  MODIFY COLUMN revision               BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Optimistic-lock version used to detect concurrent updates.',
  MODIFY COLUMN notes                  VARCHAR(1024) NULL COMMENT 'Review notes and cautions for the recovery reference node.',
  MODIFY COLUMN created_at             DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the created event occurred.',
  MODIFY COLUMN updated_at             DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                             ON UPDATE CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the updated event occurred.';

ALTER TABLE `trihouse_recovery`.`recovery_episodes`
  COMMENT = 'Records each recovery incident from trigger to completion, including VLM and recovery-policy lineage.';

ALTER TABLE `trihouse_recovery`.`recovery_episodes`
  MODIFY COLUMN recovery_episode_uuid     CHAR(36) NOT NULL COMMENT 'UUID of the related recovery episode.',
  MODIFY COLUMN source_event_uuid         CHAR(36) NULL COMMENT 'UUID of the related source event.',
  MODIFY COLUMN device_id                 VARCHAR(64) NOT NULL COMMENT 'Identifier of the related device.',
  MODIFY COLUMN fms_job_id                BIGINT UNSIGNED NULL COMMENT 'Identifier of the related fms job.',
  MODIFY COLUMN fms_job_step_id           BIGINT UNSIGNED NULL COMMENT 'Identifier of the related fms job step.',
  MODIFY COLUMN map_name                  VARCHAR(96) NOT NULL COMMENT 'Name of the map.',
  MODIFY COLUMN map_revision              VARCHAR(128) NOT NULL COMMENT 'Map revision for this record.',
  MODIFY COLUMN trigger_type              VARCHAR(24) NOT NULL COMMENT 'Code identifying the trigger type.',
  MODIFY COLUMN vlm_model_name            VARCHAR(128) NULL COMMENT 'Name of the vlm model.',
  MODIFY COLUMN vlm_model_version         VARCHAR(128) NULL COMMENT 'Vlm model version for this record.',
  MODIFY COLUMN recovery_policy_name      VARCHAR(128) NOT NULL COMMENT 'Name of the recovery policy.',
  MODIFY COLUMN recovery_policy_version   VARCHAR(128) NOT NULL COMMENT 'Recovery policy version for this record.',
  MODIFY COLUMN started_at                DATETIME(6) NOT NULL COMMENT 'Timestamp when the started event occurred.',
  MODIFY COLUMN ended_at                  DATETIME(6) NULL COMMENT 'Timestamp when the ended event occurred.',
  MODIFY COLUMN final_status              VARCHAR(16) NOT NULL DEFAULT 'running' COMMENT 'Current final status code.',
  MODIFY COLUMN summary                   VARCHAR(1024) NULL COMMENT 'Summary for this record.',
  MODIFY COLUMN created_at                DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the created event occurred.';

ALTER TABLE `trihouse_recovery`.`recovery_steps`
  COMMENT = 'Records executed recovery actions, observations, rewards, outcomes, and completion status in sequence.';

ALTER TABLE `trihouse_recovery`.`recovery_steps`
  MODIFY COLUMN recovery_step_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related recovery step.',
  MODIFY COLUMN recovery_episode_uuid  CHAR(36) NOT NULL COMMENT 'UUID of the related recovery episode.',
  MODIFY COLUMN step_no                SMALLINT UNSIGNED NOT NULL COMMENT 'Execution order within the same job or recovery episode.',
  MODIFY COLUMN reference_node_uuid    CHAR(36) NULL COMMENT 'UUID of the FMS recovery reference node selected as the action target; no physical cross-database foreign key is used.',
  MODIFY COLUMN action_type            VARCHAR(16) NOT NULL COMMENT 'Code identifying the action type.',
  MODIFY COLUMN target_pose            JSON NULL COMMENT 'JSON object containing the target position and orientation for the recovery action.',
  MODIFY COLUMN before_state_uri       VARCHAR(1024) NULL COMMENT 'URI of the stored before state data.',
  MODIFY COLUMN before_state_sha256    CHAR(64) NULL COMMENT 'SHA-256 hash used to verify the integrity of the before state.',
  MODIFY COLUMN after_state_uri        VARCHAR(1024) NULL COMMENT 'URI of the stored after state data.',
  MODIFY COLUMN after_state_sha256     CHAR(64) NULL COMMENT 'SHA-256 hash used to verify the integrity of the after state.',
  MODIFY COLUMN reward_components      JSON NULL COMMENT 'JSON object containing individual reward components for reinforcement learning.',
  MODIFY COLUMN outcome_class          VARCHAR(16) NOT NULL COMMENT 'Outcome class for this record.',
  MODIFY COLUMN execution_status       VARCHAR(16) NOT NULL DEFAULT 'queued' COMMENT 'Current execution status code.',
  MODIFY COLUMN is_terminal            TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Indicates whether this recovery action is the final step of the episode.',
  MODIFY COLUMN started_at             DATETIME(6) NOT NULL COMMENT 'Timestamp when the started event occurred.',
  MODIFY COLUMN completed_at           DATETIME(6) NULL COMMENT 'Timestamp when the completed event occurred.',
  MODIFY COLUMN created_at             DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the created event occurred.';
