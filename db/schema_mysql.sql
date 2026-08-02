-- ============================================================================
-- FMS MySQL 스키마 v3
--
-- 목적
--   Pinky-pro 주행로봇 2대와 OMX-AI 로봇팔 2대를 함께 운영한다.
--   Open-RMF는 주행로봇의 교통을, Cyclo/OMX는 조작을 맡고, 
--   데이터베이스는 입출고·재고·작업·안전·감사 이력 관리를 담당한다.
--
-- 운영 원칙
--   * MySQL 8.0 이상, InnoDB, UTC DATETIME(6)을 사용한다.
--   * 이 파일은 실제 운영 예시 데이터를 넣지 않는다.
--   * UI와 장비 어댑터는 FMS API만 사용하며 MySQL 쓰기 권한을 받지 않는다.
--   * VLM/RL의 관측과 복구 제안은 기록 대상이며, 전역 배차·최종 안전 권한은
--     FMS와 Safety Supervisor에 남긴다.
-- ============================================================================

CREATE DATABASE IF NOT EXISTS `trihouse_fms`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `trihouse_fms`;

-- [공간·작업장] 창고의 모든 운영 위치를 관리한다.
-- 랙·슬롯·도크·충전기·포장대·OMX 작업장·RMF waypoint를 한 기준으로 연결한다.
CREATE TABLE IF NOT EXISTS locations (
  location_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  parent_location_id BIGINT UNSIGNED NULL,
  location_code      VARCHAR(96) NOT NULL,
  name               VARCHAR(160) NULL,
  location_type      VARCHAR(32) NOT NULL,
  zone_code          VARCHAR(64) NULL,
  temperature_zone   VARCHAR(16) NULL,
  map_name           VARCHAR(96) NULL,
  rmf_waypoint_name  VARCHAR(128) NULL,
  pose_x             DOUBLE NULL,
  pose_y             DOUBLE NULL,
  pose_yaw           DOUBLE NULL,
  state              VARCHAR(24) NOT NULL DEFAULT 'available',
  metadata           JSON NULL,
  PRIMARY KEY (location_id),
  UNIQUE KEY uq_locations_code (location_code),
  UNIQUE KEY uq_locations_rmf_waypoint (map_name, rmf_waypoint_name),
  KEY idx_locations_zone_type (zone_code, location_type),
  CONSTRAINT fk_locations_parent
    FOREIGN KEY (parent_location_id) REFERENCES locations (location_id),
  CONSTRAINT chk_locations_type CHECK (location_type IN
    ('rack','slot','waypoint','staging','inbound_dock','outbound_dock',
     'charger','workstation','door','safe_node')),
  CONSTRAINT chk_locations_temperature CHECK (temperature_zone IS NULL OR
    temperature_zone IN ('ambient','chilled','frozen')),
  CONSTRAINT chk_locations_state CHECK (state IN
    ('available','reserved','occupied','blocked','maintenance'))
) ENGINE=InnoDB;

-- [공간·작업장] 지도에서 운영에 의미가 있는 feature를 관리한다.
-- 정적 장애물·ArUco marker·병목 통로·출입문·진입 금지 구역을 표현한다.
-- 실제 Nav2/RMF 지도 파일은 버전 관리 저장소에 두고, 이 테이블은 UI·운영 규칙·
-- marker 조회를 위한 메타데이터만 가진다.
CREATE TABLE IF NOT EXISTS map_features (
  feature_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  map_name            VARCHAR(96) NOT NULL,
  map_revision        VARCHAR(128) NOT NULL,
  feature_code        VARCHAR(128) NOT NULL,
  feature_type        VARCHAR(24) NOT NULL,
  location_id         BIGINT UNSIGNED NULL,
  marker_code         INT UNSIGNED NULL,
  geometry            JSON NOT NULL,
  properties          JSON NULL,
  active              TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (feature_id),
  UNIQUE KEY uq_map_features_code (map_name, map_revision, feature_code),
  UNIQUE KEY uq_map_features_marker (map_name, map_revision, marker_code),
  KEY idx_map_features_location (location_id),
  KEY idx_map_features_type (map_name, feature_type, active),
  CONSTRAINT fk_map_features_location FOREIGN KEY (location_id)
    REFERENCES locations (location_id),
  CONSTRAINT chk_map_features_type CHECK (feature_type IN
    ('fiducial','static_obstacle','bottleneck','door','no_go_zone')),
  CONSTRAINT chk_map_features_marker CHECK
    ((feature_type = 'fiducial' AND marker_code IS NOT NULL) OR
     (feature_type <> 'fiducial' AND marker_code IS NULL))
) ENGINE=InnoDB;

-- [사람·권한] 관제 요청·수동 복구·안전 해제에 책임을 남길 작업자 계정이다.
-- 카메라가 감지한 사람의 실시간 위치를 기록하는 테이블이 아니다.
CREATE TABLE IF NOT EXISTS workers (
  worker_id          VARCHAR(64) NOT NULL,
  worker_code        VARCHAR(64) NOT NULL,
  name               VARCHAR(128) NOT NULL,
  role               VARCHAR(32) NOT NULL,
  external_auth_id   VARCHAR(128) NULL,
  allowed_zones      JSON NULL,
  active             TINYINT(1) NOT NULL DEFAULT 1,
  registered_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  retired_at         DATETIME(6) NULL,
  PRIMARY KEY (worker_id),
  UNIQUE KEY uq_workers_code (worker_code),
  UNIQUE KEY uq_workers_external_auth (external_auth_id),
  KEY idx_workers_role_active (role, active),
  CONSTRAINT chk_workers_role CHECK (role IN
    ('operator','supervisor','safety_manager','administrator'))
) ENGINE=InnoDB;

-- [장비] Pinky와 OMX의 공통 장비 마스터다.
-- 실시간 상태와 작업 실행 내용은 아래 device_states·job_steps에서 관리한다.
CREATE TABLE IF NOT EXISTS devices (
  device_id            VARCHAR(64) NOT NULL,
  device_type          VARCHAR(16) NOT NULL,
  name                 VARCHAR(128) NOT NULL,
  model                VARCHAR(96) NOT NULL,
  fleet_name           VARCHAR(96) NULL,
  home_location_id     BIGINT UNSIGNED NULL,
  current_location_id  BIGINT UNSIGNED NULL,
  control_mode         VARCHAR(24) NOT NULL DEFAULT 'automatic',
  active               TINYINT(1) NOT NULL DEFAULT 1,
  capabilities         JSON NULL,
  registered_at        DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  retired_at           DATETIME(6) NULL,
  PRIMARY KEY (device_id),
  KEY idx_devices_type_active (device_type, active),
  KEY idx_devices_fleet (fleet_name),
  CONSTRAINT fk_devices_home FOREIGN KEY (home_location_id)
    REFERENCES locations (location_id),
  CONSTRAINT fk_devices_current FOREIGN KEY (current_location_id)
    REFERENCES locations (location_id),
  CONSTRAINT chk_devices_type CHECK (device_type IN ('mobile','arm')),
  CONSTRAINT chk_devices_mode CHECK (control_mode IN
    ('automatic','manual','offline','maintenance','safety_hold'))
) ENGINE=InnoDB;

-- [재고] 유통기한과 보관 온도를 가진 재고 lot의 현재 수량을 관리한다.
-- reserved_qty는 일시적인 업무 예약이며, 수량 변동의 증거는 inventory_moves에 남긴다.
CREATE TABLE IF NOT EXISTS inventory_lots (
  lot_id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  product_code       VARCHAR(96) NOT NULL,
  lot_code           VARCHAR(128) NOT NULL,
  item_name          VARCHAR(160) NULL,
  temperature_zone   VARCHAR(16) NOT NULL,
  location_id        BIGINT UNSIGNED NULL,
  expiry_date        DATE NOT NULL,
  unit_weight_kg     DECIMAL(10,3) NULL,
  available_qty      INT NOT NULL DEFAULT 0,
  reserved_qty       INT NOT NULL DEFAULT 0,
  state              VARCHAR(24) NOT NULL DEFAULT 'stored',
  received_at        DATETIME(6) NULL,
  updated_at         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                       ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (lot_id),
  UNIQUE KEY uq_inventory_lots_lot_code (lot_code),
  KEY idx_lots_product_expiry (product_code, expiry_date),
  KEY idx_lots_location (location_id),
  CONSTRAINT fk_lots_location FOREIGN KEY (location_id)
    REFERENCES locations (location_id),
  CONSTRAINT chk_lots_temperature CHECK (temperature_zone IN
    ('ambient','chilled','frozen')),
  CONSTRAINT chk_lots_qty CHECK
    (available_qty >= 0 AND reserved_qty >= 0),
  CONSTRAINT chk_lots_state CHECK (state IN
    ('pending_inbound','stored','on_hold','depleted','expired','damaged'))
) ENGINE=InnoDB;

-- [업무] 입고·출고·이동·보충·폐기·복구·비상 대응을 하나의 업무 단위로 관리한다.
-- 주문과 로봇 미션을 별도 헤더로 나누지 않아 운영자가 한 화면에서 상태를 본다.
CREATE TABLE IF NOT EXISTS jobs (
  job_id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  job_code             VARCHAR(64) NOT NULL,
  operation_type       VARCHAR(24) NOT NULL,
  priority             VARCHAR(16) NOT NULL DEFAULT 'normal',
  state                VARCHAR(24) NOT NULL DEFAULT 'pending',
  requested_by         VARCHAR(64) NULL,
  external_reference   VARCHAR(128) NULL,
  source_location_id   BIGINT UNSIGNED NULL,
  destination_location_id BIGINT UNSIGNED NULL,
  due_at               DATETIME(6) NULL,
  assigned_mobile_id   VARCHAR(64) NULL,
  failure_reason       VARCHAR(512) NULL,
  context              JSON NULL,
  created_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  started_at           DATETIME(6) NULL,
  completed_at         DATETIME(6) NULL,
  PRIMARY KEY (job_id),
  UNIQUE KEY uq_jobs_code (job_code),
  KEY idx_jobs_dispatch (state, priority, due_at),
  KEY idx_jobs_mobile (assigned_mobile_id, state),
  KEY idx_jobs_external_reference (external_reference),
  CONSTRAINT fk_jobs_source FOREIGN KEY (source_location_id)
    REFERENCES locations (location_id),
  CONSTRAINT fk_jobs_destination FOREIGN KEY (destination_location_id)
    REFERENCES locations (location_id),
  CONSTRAINT fk_jobs_mobile FOREIGN KEY (assigned_mobile_id)
    REFERENCES devices (device_id),
  CONSTRAINT fk_jobs_requester FOREIGN KEY (requested_by)
    REFERENCES workers (worker_id),
  CONSTRAINT chk_jobs_type CHECK (operation_type IN
    ('inbound','outbound','relocation','replenishment','disposal','recovery','emergency')),
  CONSTRAINT chk_jobs_priority CHECK (priority IN ('critical','high','normal','low')),
  CONSTRAINT chk_jobs_state CHECK (state IN
    ('pending','planned','running','waiting','blocked','completed','failed',
     'cancelled','safety_hold'))
) ENGINE=InnoDB;

-- [업무] 한 업무에 포함된 상품·lot·수량·검수 상태를 관리한다.
-- 입고 예정 품목, 출고 요청 품목, 실제로 배정된 lot을 같은 구조로 기록한다.
CREATE TABLE IF NOT EXISTS job_items (
  job_item_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  job_id              BIGINT UNSIGNED NOT NULL,
  product_code        VARCHAR(96) NOT NULL,
  requested_qty       INT NOT NULL,
  completed_qty       INT NOT NULL DEFAULT 0,
  lot_id              BIGINT UNSIGNED NULL,
  handling_unit_code  VARCHAR(128) NULL,
  verification_state  VARCHAR(24) NOT NULL DEFAULT 'pending',
  metadata            JSON NULL,
  PRIMARY KEY (job_item_id),
  KEY idx_job_items_job (job_id),
  KEY idx_job_items_lot (lot_id),
  CONSTRAINT fk_job_items_job FOREIGN KEY (job_id)
    REFERENCES jobs (job_id) ON DELETE CASCADE,
  CONSTRAINT fk_job_items_lot FOREIGN KEY (lot_id)
    REFERENCES inventory_lots (lot_id),
  CONSTRAINT chk_job_items_qty CHECK
    (requested_qty > 0 AND completed_qty >= 0 AND completed_qty <= requested_qty),
  CONSTRAINT chk_job_items_verification CHECK (verification_state IN
    ('pending','matched','mismatch','manual_review'))
) ENGINE=InnoDB;

-- [업무] 업무를 Pinky 이동·OMX 조작·검수·인계 순서의 실행 단계로 나눈다.
-- rmf_task_id로 RMF 작업을 직접 연결하고, 모델 이름·버전으로 VLM/RL 판단을
-- 별도 테이블 없이 추적한다.
CREATE TABLE IF NOT EXISTS job_steps (
  job_step_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  job_id               BIGINT UNSIGNED NOT NULL,
  step_no              SMALLINT UNSIGNED NOT NULL,
  executor_type        VARCHAR(16) NOT NULL,
  assigned_device_id   VARCHAR(64) NULL,
  action_type          VARCHAR(32) NOT NULL,
  target_location_id   BIGINT UNSIGNED NULL,
  state                VARCHAR(24) NOT NULL DEFAULT 'pending',
  rmf_task_id          VARCHAR(128) NULL,
  policy_name          VARCHAR(128) NULL,
  policy_version       VARCHAR(128) NULL,
  retry_count          SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  failure_reason       VARCHAR(512) NULL,
  input                JSON NULL,
  result               JSON NULL,
  started_at           DATETIME(6) NULL,
  completed_at         DATETIME(6) NULL,
  PRIMARY KEY (job_step_id),
  UNIQUE KEY uq_job_steps_order (job_id, step_no),
  UNIQUE KEY uq_job_steps_rmf_task (rmf_task_id),
  KEY idx_job_steps_device_state (assigned_device_id, state),
  KEY idx_job_steps_dispatch (state, executor_type),
  CONSTRAINT fk_job_steps_job FOREIGN KEY (job_id)
    REFERENCES jobs (job_id) ON DELETE CASCADE,
  CONSTRAINT fk_job_steps_device FOREIGN KEY (assigned_device_id)
    REFERENCES devices (device_id),
  CONSTRAINT fk_job_steps_target FOREIGN KEY (target_location_id)
    REFERENCES locations (location_id),
  CONSTRAINT chk_job_steps_executor CHECK (executor_type IN ('mobile','arm','fms')),
  CONSTRAINT chk_job_steps_action CHECK (action_type IN
    ('navigate','dock','inspect','pick','load','unload','place','verify',
     'handover','wait','recover','return_home','safety_stop')),
  CONSTRAINT chk_job_steps_state CHECK (state IN
    ('pending','queued','running','succeeded','failed','on_hold','cancelled'))
) ENGINE=InnoDB;

-- [점유] 병목 통로의 진입 권한과 도크·포장대·OMX의 사용 시간을 관리한다.
-- 병목은 map_feature_id를 잠그고, 시간 예약은 예정 사용 구간이 겹치지 않도록
-- FMS가 관리한다. 활성 상태의 실제 점유는 유일 키로 한 장비만 허용한다.
CREATE TABLE IF NOT EXISTS reservations (
  reservation_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  job_id               BIGINT UNSIGNED NOT NULL,
  job_step_id          BIGINT UNSIGNED NULL,
  location_id          BIGINT UNSIGNED NULL,
  device_id            VARCHAR(64) NULL,
  map_feature_id       BIGINT UNSIGNED NULL,
  reservation_mode     VARCHAR(24) NOT NULL DEFAULT 'exclusive_lock',
  state                VARCHAR(16) NOT NULL DEFAULT 'reserved',
  planned_start_at     DATETIME(6) NULL,
  planned_end_at       DATETIME(6) NULL,
  entered_at           DATETIME(6) NULL,
  exited_at            DATETIME(6) NULL,
  expires_at           DATETIME(6) NOT NULL,
  created_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  released_at          DATETIME(6) NULL,
  active_resource_key  VARCHAR(160) GENERATED ALWAYS AS (
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
  ) STORED,
  PRIMARY KEY (reservation_id),
  UNIQUE KEY uq_reservations_active_resource (active_resource_key),
  KEY idx_reservations_expiry (state, expires_at),
  KEY idx_reservations_job (job_id),
  KEY idx_reservations_location_schedule
    (location_id, state, planned_start_at, planned_end_at),
  KEY idx_reservations_device_schedule
    (device_id, state, planned_start_at, planned_end_at),
  KEY idx_reservations_feature_state (map_feature_id, state),
  CONSTRAINT fk_reservations_job FOREIGN KEY (job_id)
    REFERENCES jobs (job_id) ON DELETE CASCADE,
  CONSTRAINT fk_reservations_step FOREIGN KEY (job_step_id)
    REFERENCES job_steps (job_step_id) ON DELETE SET NULL,
  CONSTRAINT fk_reservations_location FOREIGN KEY (location_id)
    REFERENCES locations (location_id),
  CONSTRAINT fk_reservations_device FOREIGN KEY (device_id)
    REFERENCES devices (device_id),
  CONSTRAINT fk_reservations_feature FOREIGN KEY (map_feature_id)
    REFERENCES map_features (feature_id),
  CONSTRAINT chk_reservations_target CHECK
    ((reservation_mode = 'bottleneck_lock' AND map_feature_id IS NOT NULL
      AND location_id IS NULL AND device_id IS NULL) OR
     (reservation_mode IN ('exclusive_lock','time_slot') AND map_feature_id IS NULL
      AND ((location_id IS NOT NULL AND device_id IS NULL) OR
           (location_id IS NULL AND device_id IS NOT NULL)))),
  CONSTRAINT chk_reservations_mode CHECK
    (reservation_mode IN ('exclusive_lock','bottleneck_lock','time_slot')),
  CONSTRAINT chk_reservations_schedule CHECK
    ((reservation_mode = 'time_slot' AND planned_start_at IS NOT NULL
      AND planned_end_at IS NOT NULL AND planned_start_at < planned_end_at) OR
     (reservation_mode <> 'time_slot' AND planned_start_at IS NULL
      AND planned_end_at IS NULL)),
  CONSTRAINT chk_reservations_state CHECK (state IN
    ('reserved','in_use','released','expired','cancelled'))
) ENGINE=InnoDB;

-- [재고] 재고 수량이 변한 모든 근거를 추가만 가능한 원장으로 남긴다.
-- inventory_lots의 현재 수량 갱신과 이 INSERT는 반드시 같은 트랜잭션에서 처리한다.
CREATE TABLE IF NOT EXISTS inventory_moves (
  inventory_move_id    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  lot_id               BIGINT UNSIGNED NOT NULL,
  job_id               BIGINT UNSIGNED NULL,
  job_step_id          BIGINT UNSIGNED NULL,
  move_type            VARCHAR(24) NOT NULL,
  quantity_delta       INT NOT NULL,
  quantity_after       INT NOT NULL,
  recorded_by          VARCHAR(96) NOT NULL,
  recorded_at          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  note                 VARCHAR(512) NULL,
  PRIMARY KEY (inventory_move_id),
  KEY idx_inventory_moves_lot_at (lot_id, recorded_at),
  KEY idx_inventory_moves_job (job_id),
  CONSTRAINT fk_inventory_moves_lot FOREIGN KEY (lot_id)
    REFERENCES inventory_lots (lot_id),
  CONSTRAINT fk_inventory_moves_job FOREIGN KEY (job_id)
    REFERENCES jobs (job_id),
  CONSTRAINT fk_inventory_moves_step FOREIGN KEY (job_step_id)
    REFERENCES job_steps (job_step_id),
  CONSTRAINT chk_inventory_moves_type CHECK (move_type IN
    ('inbound','outbound','reservation','reservation_release','adjustment',
     'disposal','cycle_count'))
) ENGINE=InnoDB;

-- [장비] 장비별 최신 상태를 한 행으로 보관해 관제 화면과 재시작 복구에 사용한다.
-- Pinky는 위치·배터리를, OMX는 관절·카메라·툴 상태를 details에 기록한다.
CREATE TABLE IF NOT EXISTS device_states (
  device_id            VARCHAR(64) NOT NULL,
  observed_at          DATETIME(6) NOT NULL,
  state                VARCHAR(24) NOT NULL,
  health               VARCHAR(16) NOT NULL DEFAULT 'ok',
  current_job_step_id  BIGINT UNSIGNED NULL,
  pose_x               DOUBLE NULL,
  pose_y               DOUBLE NULL,
  pose_yaw             DOUBLE NULL,
  battery_pct          DECIMAL(5,2) NULL,
  progress             DECIMAL(5,4) NULL,
  details              JSON NULL,
  PRIMARY KEY (device_id),
  KEY idx_device_states_step (current_job_step_id),
  CONSTRAINT fk_device_states_device FOREIGN KEY (device_id)
    REFERENCES devices (device_id) ON DELETE CASCADE,
  CONSTRAINT fk_device_states_step FOREIGN KEY (current_job_step_id)
    REFERENCES job_steps (job_step_id) ON DELETE SET NULL,
  CONSTRAINT chk_device_states_state CHECK (state IN
    ('idle','moving','docking','working','waiting','charging','blocked',
     'error','estop','offline','maintenance')),
  CONSTRAINT chk_device_states_health CHECK (health IN
    ('ok','warning','fault','safety_hold')),
  CONSTRAINT chk_device_states_battery CHECK
    (battery_pct IS NULL OR (battery_pct >= 0 AND battery_pct <= 100)),
  CONSTRAINT chk_device_states_progress CHECK
    (progress IS NULL OR (progress >= 0 AND progress <= 1))
) ENGINE=InnoDB;

-- [연동] RMF 배차, Pinky/OMX 명령, 장비 응답을 모두 담는 내구성 있는 메시지 큐다.
-- inbound/outbound와 idempotency_key를 함께 기록해 재전송 시 중복 실행을 막는다.
CREATE TABLE IF NOT EXISTS integration_messages (
  message_id           CHAR(36) NOT NULL,
  direction            VARCHAR(8) NOT NULL,
  channel              VARCHAR(16) NOT NULL,
  device_id            VARCHAR(64) NULL,
  job_step_id          BIGINT UNSIGNED NULL,
  message_type         VARCHAR(64) NOT NULL,
  idempotency_key      VARCHAR(160) NOT NULL,
  external_reference   VARCHAR(160) NULL,
  state                VARCHAR(16) NOT NULL DEFAULT 'pending',
  attempts             SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  payload              JSON NOT NULL,
  last_error           VARCHAR(512) NULL,
  created_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  sent_at              DATETIME(6) NULL,
  acknowledged_at      DATETIME(6) NULL,
  PRIMARY KEY (message_id),
  UNIQUE KEY uq_messages_dedupe (direction, channel, idempotency_key),
  KEY idx_messages_delivery (direction, state, created_at),
  KEY idx_messages_step (job_step_id),
  CONSTRAINT fk_messages_device FOREIGN KEY (device_id)
    REFERENCES devices (device_id),
  CONSTRAINT fk_messages_step FOREIGN KEY (job_step_id)
    REFERENCES job_steps (job_step_id) ON DELETE SET NULL,
  CONSTRAINT chk_messages_direction CHECK (direction IN ('inbound','outbound')),
  CONSTRAINT chk_messages_channel CHECK (channel IN ('rmf','pinky','omx')),
  CONSTRAINT chk_messages_state CHECK (state IN
    ('pending','sent','acknowledged','completed','failed','dead_letter'))
) ENGINE=InnoDB;

-- [운영·AI·안전] 현재 진행 중인 안전 사고를 관리한다.
-- 단순 로그와 달리 active 상태·영향 위치·해제 승인자를 가지며, FMS가 해당 구역을
-- 차단하고 RMF 재계획 또는 정지를 요청하는 기준이 된다.
CREATE TABLE IF NOT EXISTS incidents (
  incident_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  incident_code        VARCHAR(64) NOT NULL,
  incident_type        VARCHAR(32) NOT NULL,
  severity             VARCHAR(16) NOT NULL,
  state                VARCHAR(24) NOT NULL DEFAULT 'active',
  location_id          BIGINT UNSIGNED NULL,
  geometry             JSON NULL,
  description          VARCHAR(512) NOT NULL,
  raised_by_worker_id  VARCHAR(64) NULL,
  resolved_by_worker_id VARCHAR(64) NULL,
  raised_at            DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  resolved_at          DATETIME(6) NULL,
  context              JSON NULL,
  PRIMARY KEY (incident_id),
  UNIQUE KEY uq_incidents_code (incident_code),
  KEY idx_incidents_active (state, severity, raised_at),
  KEY idx_incidents_location (location_id, state),
  CONSTRAINT fk_incidents_location FOREIGN KEY (location_id)
    REFERENCES locations (location_id),
  CONSTRAINT fk_incidents_raised_by FOREIGN KEY (raised_by_worker_id)
    REFERENCES workers (worker_id),
  CONSTRAINT fk_incidents_resolved_by FOREIGN KEY (resolved_by_worker_id)
    REFERENCES workers (worker_id),
  CONSTRAINT chk_incidents_type CHECK (incident_type IN
    ('worker_intrusion','worker_emergency','estop','spill','blocked_path',
     'fire','power_cut','device_fault')),
  CONSTRAINT chk_incidents_severity CHECK (severity IN
    ('info','warning','serious','critical')),
  CONSTRAINT chk_incidents_state CHECK (state IN
    ('active','acknowledged','resolved','cancelled'))
) ENGINE=InnoDB;

-- [운영·AI·안전] 작업·안전·VLM·RL 판단을 시간 순서대로 추가만 가능한 로그로 남긴다.
-- VLM/RL 제안은 여기 기록한 뒤 Safety Supervisor가 승인한 허용된 복구 행동만 실행한다.
CREATE TABLE IF NOT EXISTS operation_events (
  event_id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  event_uuid           CHAR(36) NOT NULL,
  occurred_at          DATETIME(6) NOT NULL,
  device_id            VARCHAR(64) NULL,
  job_id               BIGINT UNSIGNED NULL,
  job_step_id          BIGINT UNSIGNED NULL,
  incident_id          BIGINT UNSIGNED NULL,
  severity             VARCHAR(16) NOT NULL DEFAULT 'info',
  category             VARCHAR(24) NOT NULL,
  event_type           VARCHAR(96) NOT NULL,
  message              VARCHAR(512) NULL,
  model_name           VARCHAR(128) NULL,
  model_version        VARCHAR(128) NULL,
  confidence           DECIMAL(6,5) NULL,
  safety_decision      VARCHAR(16) NULL,
  payload              JSON NULL,
  PRIMARY KEY (event_id),
  UNIQUE KEY uq_operation_events_uuid (event_uuid),
  KEY idx_events_device_at (device_id, occurred_at),
  KEY idx_events_job_at (job_id, occurred_at),
  KEY idx_events_incident_at (incident_id, occurred_at),
  KEY idx_events_category_at (category, occurred_at),
  CONSTRAINT fk_events_device FOREIGN KEY (device_id)
    REFERENCES devices (device_id),
  CONSTRAINT fk_events_job FOREIGN KEY (job_id)
    REFERENCES jobs (job_id),
  CONSTRAINT fk_events_step FOREIGN KEY (job_step_id)
    REFERENCES job_steps (job_step_id),
  CONSTRAINT fk_events_incident FOREIGN KEY (incident_id)
    REFERENCES incidents (incident_id),
  CONSTRAINT chk_events_severity CHECK (severity IN
    ('debug','info','warning','serious','critical')),
  CONSTRAINT chk_events_category CHECK (category IN
    ('operation','inventory','rmf','omx','vision','policy','safety','system')),
  CONSTRAINT chk_events_safety_decision CHECK (safety_decision IS NULL OR
    safety_decision IN ('approved','denied','stopped','manual_review')),
  CONSTRAINT chk_events_confidence CHECK
    (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
) ENGINE=InnoDB;

-- [학습 원본] 이미지·영상·point cloud·ROS bag·Cyclo episode·데이터셋·모델의
-- 파일 자체가 아니라 위치와 무결성 정보를 관리한다. 원본은 NAS/MinIO/S3에 저장한다.
CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  artifact_type         VARCHAR(24) NOT NULL,
  storage_uri           VARCHAR(1024) NOT NULL,
  sha256                CHAR(64) NOT NULL,
  mime_type             VARCHAR(128) NULL,
  byte_size             BIGINT UNSIGNED NULL,
  device_id             VARCHAR(64) NULL,
  job_id                BIGINT UNSIGNED NULL,
  job_step_id           BIGINT UNSIGNED NULL,
  event_id              BIGINT UNSIGNED NULL,
  model_name            VARCHAR(128) NULL,
  model_version         VARCHAR(128) NULL,
  metadata              JSON NULL,
  captured_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (artifact_id),
  UNIQUE KEY uq_artifacts_sha_uri (sha256, storage_uri),
  KEY idx_artifacts_step (job_step_id),
  KEY idx_artifacts_event (event_id),
  KEY idx_artifacts_model (model_name, model_version),
  CONSTRAINT fk_artifacts_device FOREIGN KEY (device_id)
    REFERENCES devices (device_id),
  CONSTRAINT fk_artifacts_job FOREIGN KEY (job_id)
    REFERENCES jobs (job_id),
  CONSTRAINT fk_artifacts_step FOREIGN KEY (job_step_id)
    REFERENCES job_steps (job_step_id),
  CONSTRAINT fk_artifacts_event FOREIGN KEY (event_id)
    REFERENCES operation_events (event_id),
  CONSTRAINT chk_artifacts_type CHECK (artifact_type IN
    ('image','video','pointcloud','rosbag','episode','dataset','model','report'))
) ENGINE=InnoDB;
