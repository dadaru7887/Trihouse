-- ============================================================================
-- FMS MySQL 스키마 v5
--
-- 목적
--   Pinky-pro 주행로봇 2대와 OMX-AI 로봇팔 2대를 함께 운영한다.
--   Open-RMF는 주행로봇의 교통을, Cyclo/OMX는 조작을 맡고,
--   데이터베이스는 입출고·재고·작업·안전·감사 이력 관리를 담당한다.
--
-- 운영 원칙
--   * MySQL 8.0 이상, InnoDB, Asia/Seoul DATETIME(6)을 사용한다.
--   * Gateway는 연결 직후 SET time_zone = '+09:00'을 실행한다.
--   * 이 파일은 실제 운영 예시 데이터를 넣지 않는다.
--   * UI와 장비 어댑터는 FMS API만 사용하며 MySQL 쓰기 권한을 받지 않는다.
--   * VLM/RL의 관측과 복구 제안은 기록 대상이며, 전역 배차·최종 안전 권한은
--     FMS와 Safety Supervisor에 남긴다.
-- ============================================================================

CREATE DATABASE IF NOT EXISTS `trihouse_fms`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `trihouse_fms`;

-- [지도 편집 원본] Control System UI의 draft 프로젝트를 보관한다.
CREATE TABLE IF NOT EXISTS map_projects (
  project_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Internal map-project identifier.',
  map_name            VARCHAR(95) NOT NULL COMMENT 'Unique project and RMF map name; bounded for map_name plus SHA-256 revision.',
  format_version      INT UNSIGNED NOT NULL COMMENT 'Version of the editable project payload.',
  payload             JSON NOT NULL COMMENT 'Canonical editable map-project payload.',
  drawing_name        VARCHAR(255) NULL COMMENT 'Original drawing file name.',
  drawing_extension   VARCHAR(16) NULL COMMENT 'Original drawing extension.',
  drawing_bytes       LONGBLOB NULL COMMENT 'Original drawing bytes.',
  drawing_width       INT UNSIGNED NULL COMMENT 'Drawing width in pixels.',
  drawing_height      INT UNSIGNED NULL COMMENT 'Drawing height in pixels.',
  building_yaml       LONGTEXT NULL COMMENT 'Generated Open-RMF building YAML.',
  building_yaml_name  VARCHAR(255) NULL COMMENT 'Generated building YAML file name.',
  waypoint_count      INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Number of active draft waypoints.',
  lane_count          INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Deprecated compatibility counter; new drafts do not use lanes.',
  draft_revision      BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT 'Optimistic draft version.',
  created_at          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the map project was created.',
  updated_at          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                        ON UPDATE CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the map project was last updated.',
  PRIMARY KEY (project_id),
  UNIQUE KEY uq_map_projects_name (map_name),
  CONSTRAINT chk_map_projects_name CHECK
    (REGEXP_LIKE(map_name, '^[A-Za-z0-9_][A-Za-z0-9_-]{0,94}$', 'c')),
  CONSTRAINT chk_map_projects_payload CHECK (JSON_TYPE(payload) = 'OBJECT')
) ENGINE=InnoDB COMMENT='Stores editable map projects used to generate Open-RMF artifacts.';

-- [지도 편집 원본] 업로드된 지도·도면·실측 feature 원본을 프로젝트별 불변 row로 보관한다.
CREATE TABLE IF NOT EXISTS map_project_sources (
  source_uuid   CHAR(36) NOT NULL COMMENT 'Immutable UUID of the uploaded project source.',
  project_id    BIGINT UNSIGNED NOT NULL COMMENT 'Identifier of the project that owns this source row.',
  source_type   VARCHAR(32) NOT NULL COMMENT 'Constrained category of the uploaded map source.',
  file_name     VARCHAR(255) NOT NULL COMMENT 'Original file name supplied for this source.',
  mime_type     VARCHAR(128) NOT NULL COMMENT 'Media type declared for the source bytes.',
  content_bytes LONGBLOB NOT NULL COMMENT 'Immutable original bytes of the uploaded source.',
  sha256        CHAR(64) NOT NULL COMMENT 'Lowercase SHA-256 digest of the source bytes.',
  byte_size     BIGINT UNSIGNED NOT NULL COMMENT 'Size of the source content in bytes.',
  metadata      JSON NULL COMMENT 'Optional source-specific metadata object.',
  created_at    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the immutable source row was created.',
  PRIMARY KEY (source_uuid),
  KEY idx_map_project_sources_project (project_id, source_type, created_at),
  CONSTRAINT fk_map_project_sources_project FOREIGN KEY (project_id)
    REFERENCES map_projects(project_id) ON DELETE CASCADE,
  CONSTRAINT chk_map_project_sources_type CHECK (source_type IN
    ('slam_yaml','slam_image','floor_plan','physical_features_import')),
  CONSTRAINT chk_map_project_sources_hash CHECK
    (sha256 REGEXP '^[0-9a-f]{64}$' AND byte_size > 0),
  CONSTRAINT chk_map_project_sources_metadata CHECK
    (metadata IS NULL OR JSON_TYPE(metadata) = 'OBJECT'),
  CONSTRAINT chk_map_project_sources_uuid CHECK
    (source_uuid REGEXP '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
) ENGINE=InnoDB COMMENT='Stores immutable binary map sources scoped to one editable map project.';

CREATE TABLE IF NOT EXISTS map_project_waypoints (
  waypoint_uuid       CHAR(36) NOT NULL COMMENT 'Immutable waypoint UUID.',
  project_id          BIGINT UNSIGNED NOT NULL COMMENT 'Identifier of the parent map project.',
  seq                 INT UNSIGNED NOT NULL COMMENT 'Stable display order within the current draft.',
  location_code       VARCHAR(96) NULL COMMENT 'Stable FMS location business key for operational waypoints.',
  rmf_waypoint_name   VARCHAR(128) NOT NULL COMMENT 'Waypoint name written to the RMF graph.',
  category            VARCHAR(32) NOT NULL COMMENT 'Canonical English UI/RMF waypoint category.',
  operational_role    VARCHAR(40) NOT NULL DEFAULT 'transit_waypoint'
    COMMENT 'Warehouse operation role selected in the UI and projected to locations.',
  temperature_zone    VARCHAR(16) NULL
    COMMENT 'Optional ambient, chilled, or frozen operating zone.',
  parent_location_code VARCHAR(96) NULL
    COMMENT 'Optional canonical location_code of the warehouse or station that owns this access point.',
  x                   DOUBLE NOT NULL COMMENT 'Drawing-space X coordinate used by the editor.',
  y                   DOUBLE NOT NULL COMMENT 'Drawing-space Y coordinate used by the editor.',
  yaw                 DOUBLE NULL COMMENT 'Drawing-space heading retained by the editor.',
  map_x               DOUBLE NULL COMMENT 'Published RMF map-frame X coordinate in meters.',
  map_y               DOUBLE NULL COMMENT 'Published RMF map-frame Y coordinate in meters.',
  map_yaw             DOUBLE NULL COMMENT 'Published RMF map-frame heading in radians.',
  active              TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'Indicates whether the waypoint belongs to the active draft.',
  PRIMARY KEY (project_id, seq),
  UNIQUE KEY uq_map_waypoints_uuid (waypoint_uuid),
  UNIQUE KEY uq_map_waypoints_name (project_id, rmf_waypoint_name),
  UNIQUE KEY uq_map_waypoints_location (project_id, location_code),
  CONSTRAINT fk_map_waypoints_project FOREIGN KEY (project_id)
    REFERENCES map_projects (project_id) ON DELETE CASCADE,
  CONSTRAINT chk_map_waypoints_category CHECK (category IN
    ('waypoint','holding','parking','home','charger','pickup','dropoff','equipment')),
  CONSTRAINT chk_map_waypoints_operational_role CHECK (operational_role IN
    ('safety_zone','charging_station','loading_dock','bottleneck_waiting_point',
     'transit_waypoint','parking_spot','inspection_point','workcell_station')),
  CONSTRAINT chk_map_waypoints_temperature_zone CHECK
    (temperature_zone IS NULL OR temperature_zone IN ('ambient','chilled','frozen')),
  CONSTRAINT chk_map_waypoints_uuid CHECK
    (waypoint_uuid REGEXP '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
) ENGINE=InnoDB COMMENT='Stores stable waypoint identities and FMS location mappings for map drafts.';

CREATE TABLE IF NOT EXISTS map_project_lanes (
  lane_uuid            CHAR(36) NOT NULL COMMENT 'Immutable lane UUID.',
  project_id           BIGINT UNSIGNED NOT NULL COMMENT 'Identifier of the parent map project.',
  seq                  INT UNSIGNED NOT NULL COMMENT 'Display order within the current draft.',
  start_waypoint_uuid  CHAR(36) NOT NULL COMMENT 'UUID of the lane start waypoint.',
  end_waypoint_uuid    CHAR(36) NOT NULL COMMENT 'UUID of the lane end waypoint.',
  direction            VARCHAR(16) NOT NULL COMMENT 'Allowed travel direction for the lane.',
  speed_limit          DOUBLE NULL COMMENT 'Optional lane speed limit in meters per second.',
  orientation          VARCHAR(16) NULL COMMENT 'Optional robot orientation constraint for the lane.',
  mutex_group          VARCHAR(64) NULL COMMENT 'Optional mutual-exclusion group used by the lane.',
  active               TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Dormant compatibility flag; new drafts never activate lanes.',
  PRIMARY KEY (project_id, seq),
  UNIQUE KEY uq_map_lanes_uuid (lane_uuid),
  CONSTRAINT fk_map_lanes_project FOREIGN KEY (project_id)
    REFERENCES map_projects (project_id) ON DELETE CASCADE,
  CONSTRAINT fk_map_lanes_start FOREIGN KEY (start_waypoint_uuid)
    REFERENCES map_project_waypoints (waypoint_uuid),
  CONSTRAINT fk_map_lanes_end FOREIGN KEY (end_waypoint_uuid)
    REFERENCES map_project_waypoints (waypoint_uuid),
  CONSTRAINT chk_map_lanes_endpoints CHECK (start_waypoint_uuid <> end_waypoint_uuid),
  CONSTRAINT chk_map_lanes_direction CHECK
    (direction IN ('양방향','정방향','역방향'))
) ENGINE=InnoDB COMMENT='Dormant compatibility storage for legacy lane topology; new drafts never read or write it.';

CREATE TABLE IF NOT EXISTS map_project_files (
  project_id    BIGINT UNSIGNED NOT NULL COMMENT 'Identifier of the parent map project.',
  file_name     VARCHAR(255) NOT NULL COMMENT 'File name unique within the map project.',
  kind          VARCHAR(32) NOT NULL COMMENT 'Generated file category.',
  description   VARCHAR(512) NOT NULL DEFAULT '' COMMENT 'Human-readable description of the generated file.',
  executable    TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Indicates whether the generated file must be executable.',
  content       LONGTEXT NOT NULL COMMENT 'Text content of the generated file.',
  generated_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the file content was generated.',
  PRIMARY KEY (project_id, file_name),
  KEY idx_map_files_kind (project_id, kind),
  CONSTRAINT fk_map_files_project FOREIGN KEY (project_id)
    REFERENCES map_projects (project_id) ON DELETE CASCADE
) ENGINE=InnoDB COMMENT='Stores generated launch, fleet, bridge, and script files for each editable map project.';

CREATE TABLE IF NOT EXISTS map_project_fleets (
  project_id       BIGINT UNSIGNED NOT NULL COMMENT 'Identifier of the parent map project.',
  fleet_name       VARCHAR(96) NOT NULL COMMENT 'Open-RMF fleet name for the map project.',
  settings         JSON NOT NULL COMMENT 'JSON object containing draft fleet parameters.',
  updated_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                     ON UPDATE CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the fleet settings were last updated.',
  PRIMARY KEY (project_id),
  CONSTRAINT fk_map_fleets_project FOREIGN KEY (project_id)
    REFERENCES map_projects (project_id) ON DELETE CASCADE,
  CONSTRAINT chk_map_fleets_settings CHECK (JSON_TYPE(settings) = 'OBJECT')
) ENGINE=InnoDB COMMENT='Stores draft Open-RMF fleet parameters per map project.';

CREATE TABLE IF NOT EXISTS map_project_robots (
  project_id        BIGINT UNSIGNED NOT NULL COMMENT 'Identifier of the parent map project.',
  robot_id          VARCHAR(64) NOT NULL COMMENT 'Stable robot identifier within the map project.',
  seq               INT UNSIGNED NOT NULL COMMENT 'Stable display order within the map project.',
  display_name      VARCHAR(128) NOT NULL COMMENT 'Robot name displayed in operator interfaces.',
  model             VARCHAR(96) NOT NULL COMMENT 'Robot model name.',
  kind              VARCHAR(16) NOT NULL COMMENT 'Robot role: mobile robot or workcell.',
  data_source       VARCHAR(16) NOT NULL COMMENT 'Runtime source: mock, Gazebo, or real hardware.',
  gz_name           VARCHAR(64) NOT NULL COMMENT 'Gazebo model and namespace name.',
  zones             JSON NOT NULL COMMENT 'JSON array of zones the robot may serve.',
  charger_waypoint_uuid CHAR(36) NULL COMMENT 'UUID of the assigned charger waypoint.',
  spawn_x           DOUBLE NULL COMMENT 'Optional Gazebo spawn X coordinate in meters.',
  spawn_y           DOUBLE NULL COMMENT 'Optional Gazebo spawn Y coordinate in meters.',
  spawn_heading     DOUBLE NOT NULL DEFAULT 0 COMMENT 'Gazebo spawn heading in radians.',
  PRIMARY KEY (project_id, robot_id),
  UNIQUE KEY uq_map_robots_seq (project_id, seq),
  UNIQUE KEY uq_map_robots_gz_name (project_id, gz_name),
  CONSTRAINT fk_map_robots_project FOREIGN KEY (project_id)
    REFERENCES map_projects (project_id) ON DELETE CASCADE,
  CONSTRAINT fk_map_robots_charger FOREIGN KEY (charger_waypoint_uuid)
    REFERENCES map_project_waypoints (waypoint_uuid),
  CONSTRAINT chk_map_robots_kind CHECK (kind IN ('mobile','workcell')),
  CONSTRAINT chk_map_robots_source CHECK (data_source IN ('mock','gazebo','real')),
  CONSTRAINT chk_map_robots_zones CHECK (JSON_TYPE(zones) = 'ARRAY')
) ENGINE=InnoDB COMMENT='Stores map-specific mobile robot and workcell placement drafts.';

CREATE TABLE IF NOT EXISTS map_revisions (
  map_revision       VARCHAR(160) NOT NULL COMMENT 'Published content revision used by RMF and Pinky.',
  map_name           VARCHAR(95) NOT NULL COMMENT 'Name of the published map.',
  source_project_id  BIGINT UNSIGNED NOT NULL COMMENT 'Identifier of the source map project.',
  draft_revision     BIGINT UNSIGNED NOT NULL COMMENT 'Draft revision used to create the publication.',
  state              VARCHAR(16) NOT NULL DEFAULT 'published' COMMENT 'Publication state: published or retired.',
  building_sha256    CHAR(64) NOT NULL COMMENT 'SHA-256 digest of the building YAML.',
  nav_graph_sha256   CHAR(64) NOT NULL COMMENT 'SHA-256 digest of the navigation graph.',
  world_sha256       CHAR(64) NOT NULL COMMENT 'SHA-256 digest of the Gazebo world.',
  manifest           JSON NOT NULL COMMENT 'JSON object containing the immutable publication manifest.',
  published_by       VARCHAR(64) NOT NULL COMMENT 'Worker or process that published the map.',
  published_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the map revision was published.',
  PRIMARY KEY (map_revision),
  UNIQUE KEY uq_map_revisions_revision (map_revision),
  KEY idx_map_revisions_current (map_name, state, published_at),
  CONSTRAINT fk_map_revisions_project FOREIGN KEY (source_project_id)
    REFERENCES map_projects (project_id),
  CONSTRAINT chk_map_revisions_state CHECK (state IN ('published','retired')),
  CONSTRAINT chk_map_revisions_manifest CHECK (JSON_TYPE(manifest) = 'OBJECT'),
  CONSTRAINT chk_map_revisions_hashes CHECK (
    building_sha256 REGEXP '^[0-9a-f]{64}$'
    AND nav_graph_sha256 REGEXP '^[0-9a-f]{64}$'
    AND world_sha256 REGEXP '^[0-9a-f]{64}$')
) ENGINE=InnoDB COMMENT='Stores immutable published map manifests and artifact hashes.';


-- [공간·작업장] 창고의 모든 운영 위치를 관리한다.
-- 랙·슬롯·도크·충전기·포장대·OMX 작업장·RMF waypoint를 한 기준으로 연결한다.
CREATE TABLE IF NOT EXISTS locations (
  location_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related location.',
  parent_location_id BIGINT UNSIGNED NULL COMMENT 'Identifier of the related parent location.',
  location_code      VARCHAR(96) NOT NULL COMMENT 'Business code for location.',
  name               VARCHAR(160) NULL COMMENT 'Location name displayed in operator interfaces.',
  location_type      VARCHAR(32) NOT NULL COMMENT 'Code identifying the location type.',
  zone_code          VARCHAR(64) NULL COMMENT 'Business code for zone.',
  temperature_zone   VARCHAR(16) NULL COMMENT 'Temperature zone for this record.',
  map_name           VARCHAR(96) NULL COMMENT 'Name of the map.',
  rmf_waypoint_name  VARCHAR(128) NULL COMMENT 'Name of the rmf waypoint.',
  pose_x             DOUBLE NULL COMMENT 'X coordinate in the map frame, in meters.',
  pose_y             DOUBLE NULL COMMENT 'Y coordinate in the map frame, in meters.',
  pose_yaw           DOUBLE NULL COMMENT 'Heading in the map frame, in radians.',
  state              VARCHAR(24) NOT NULL DEFAULT 'available' COMMENT 'Current location status: available, reserved, occupied, blocked, or maintenance.',
  metadata           JSON NULL COMMENT 'JSON object containing location-specific attributes and external integration values.',
  PRIMARY KEY (location_id),
  UNIQUE KEY uq_locations_code (location_code),
  UNIQUE KEY uq_locations_rmf_waypoint (map_name, rmf_waypoint_name),
  KEY idx_locations_zone_type (zone_code, location_type),
  CONSTRAINT fk_locations_parent
    FOREIGN KEY (parent_location_id) REFERENCES locations (location_id),
  CONSTRAINT chk_locations_type CHECK (location_type IN
    ('rack','slot','waypoint','staging','loading_dock',
     'charger','workstation','door','safe_node')),
  CONSTRAINT chk_locations_temperature CHECK (temperature_zone IS NULL OR
    temperature_zone IN ('ambient','chilled','frozen')),
  CONSTRAINT chk_locations_state CHECK (state IN
    ('available','reserved','occupied','blocked','maintenance'))
) ENGINE=InnoDB COMMENT='Manages warehouse racks, slots, docks, chargers, workstations, safety nodes, and RMF waypoints.';

-- [공간·작업장] 지도에서 운영에 의미가 있는 feature를 관리한다.
-- 정적 장애물·ArUco marker·병목 통로·출입문·진입 금지 구역을 표현한다.
-- 실제 Nav2/RMF 지도 파일은 버전 관리 저장소에 두고, 이 테이블은 UI·운영 규칙·
-- marker 조회를 위한 메타데이터만 가진다.
CREATE TABLE IF NOT EXISTS map_features (
  feature_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related feature.',
  map_name            VARCHAR(96) NOT NULL COMMENT 'Name of the map.',
  map_revision        VARCHAR(160) NOT NULL COMMENT 'Map revision for this record.',
  feature_code        VARCHAR(128) NOT NULL COMMENT 'Business code for feature.',
  feature_type        VARCHAR(24) NOT NULL COMMENT 'Code identifying the feature type.',
  location_id         BIGINT UNSIGNED NULL COMMENT 'Identifier of the related location.',
  marker_code         INT UNSIGNED NULL COMMENT 'Business code for marker.',
  geometry            JSON NOT NULL COMMENT 'JSON geometry describing a point, line, or polygon in map coordinates.',
  properties          JSON NULL COMMENT 'JSON object containing additional properties data.',
  active              TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'Indicates whether this feature is used by operating rules for the map revision.',
  PRIMARY KEY (feature_id),
  UNIQUE KEY uq_map_features_code (map_name, map_revision, feature_code),
  UNIQUE KEY uq_map_features_marker (map_name, map_revision, marker_code),
  KEY idx_map_features_location (location_id),
  KEY idx_map_features_type (map_name, feature_type, active),
  CONSTRAINT fk_map_features_location FOREIGN KEY (location_id)
    REFERENCES locations (location_id),
  CONSTRAINT chk_map_features_type CHECK (feature_type IN
    ('fiducial','static_obstacle','bottleneck','door','no_go_zone',
     'facility_footprint','safety_zone','speed_zone','camera')),
  CONSTRAINT chk_map_features_marker CHECK
    ((feature_type = 'fiducial' AND marker_code IS NOT NULL) OR
     (feature_type <> 'fiducial' AND marker_code IS NULL))
) ENGINE=InnoDB COMMENT='Manages spatial data for markers, static obstacles, bottlenecks, doors, and restricted areas by map revision.';

-- [사람·권한] 관제 요청·수동 복구·안전 해제에 책임을 남길 작업자 계정이다.
-- 카메라가 감지한 사람의 실시간 위치를 기록하는 테이블이 아니다.
CREATE TABLE IF NOT EXISTS workers (
  worker_id          VARCHAR(64) NOT NULL COMMENT 'Identifier of the related worker.',
  worker_code        VARCHAR(64) NOT NULL COMMENT 'Business code for worker.',
  name               VARCHAR(128) NOT NULL COMMENT 'Worker name displayed in operator interfaces and audit records.',
  role               VARCHAR(32) NOT NULL COMMENT 'Role for this record.',
  external_auth_id   VARCHAR(128) NULL COMMENT 'Identifier of the related external auth.',
  allowed_zones      JSON NULL COMMENT 'JSON array of zone codes the worker may access or operate.',
  active             TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'Indicates whether this worker account may participate in job requests and approvals.',
  registered_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the registered event occurred.',
  retired_at         DATETIME(6) NULL COMMENT 'Timestamp when the retired event occurred.',
  PRIMARY KEY (worker_id),
  UNIQUE KEY uq_workers_code (worker_code),
  UNIQUE KEY uq_workers_external_auth (external_auth_id),
  KEY idx_workers_role_active (role, active),
  CONSTRAINT chk_workers_role CHECK (role IN
    ('operator','supervisor','safety_manager','administrator'))
) ENGINE=InnoDB COMMENT='Manages worker accounts and permission scopes for control requests, manual recovery, and safety release actions.';

-- [장비] Pinky와 OMX의 공통 장비 마스터다.
-- 실시간 상태와 작업 실행 내용은 아래 device_states·job_steps에서 관리한다.
CREATE TABLE IF NOT EXISTS devices (
  device_id            VARCHAR(64) NOT NULL COMMENT 'Identifier of the related device.',
  device_type          VARCHAR(16) NOT NULL COMMENT 'Code identifying the device type.',
  name                 VARCHAR(128) NOT NULL COMMENT 'Device name displayed in operator interfaces.',
  model                VARCHAR(96) NOT NULL COMMENT 'Model for this record.',
  fleet_name           VARCHAR(96) NULL COMMENT 'Name of the fleet.',
  home_location_id     BIGINT UNSIGNED NULL COMMENT 'Identifier of the related home location.',
  current_location_id  BIGINT UNSIGNED NULL COMMENT 'Identifier of the related current location.',
  control_mode         VARCHAR(24) NOT NULL DEFAULT 'automatic' COMMENT 'Device control mode, such as automatic, manual, offline, maintenance, or safety stop.',
  active               TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'Indicates whether this device is eligible for dispatch and job assignment.',
  capabilities         JSON NULL COMMENT 'JSON object describing actions and features supported by the device.',
  registered_at        DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the registered event occurred.',
  retired_at           DATETIME(6) NULL COMMENT 'Timestamp when the retired event occurred.',
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
) ENGINE=InnoDB COMMENT='Manages models, fleets, locations, control modes, and capabilities for Pinky mobile robots and OMX robot arms.';

-- [재고] 유통기한과 보관 온도를 가진 재고 lot의 현재 수량을 관리한다.
-- reserved_qty는 일시적인 업무 예약이며, 수량 변동의 증거는 inventory_moves에 남긴다.
CREATE TABLE IF NOT EXISTS inventory_lots (
  lot_id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related lot.',
  product_code       VARCHAR(96) NOT NULL COMMENT 'Business code for product.',
  lot_code           VARCHAR(128) NOT NULL COMMENT 'Business code for lot.',
  item_name          VARCHAR(160) NULL COMMENT 'Name of the item.',
  temperature_zone   VARCHAR(16) NOT NULL COMMENT 'Temperature zone for this record.',
  location_id        BIGINT UNSIGNED NULL COMMENT 'Identifier of the related location.',
  expiry_date        DATE NOT NULL COMMENT 'Expiry date for this record.',
  unit_weight_kg     DECIMAL(10,3) NULL COMMENT 'Weight of one product unit in kilograms.',
  available_qty      INT NOT NULL DEFAULT 0 COMMENT 'Total physical quantity currently held in the inventory lot.',
  reserved_qty       INT NOT NULL DEFAULT 0 COMMENT 'Quantity for reserved.',
  state              VARCHAR(24) NOT NULL DEFAULT 'stored' COMMENT 'Inventory-lot status, such as pending receipt, stored, held, depleted, expired, or damaged.',
  received_at        DATETIME(6) NULL COMMENT 'Timestamp when the received event occurred.',
  updated_at         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                       ON UPDATE CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the updated event occurred.',
  PRIMARY KEY (lot_id),
  UNIQUE KEY uq_inventory_lots_lot_code (lot_code),
  KEY idx_lots_product_expiry (product_code, expiry_date),
  KEY idx_lots_location (location_id),
  CONSTRAINT fk_lots_location FOREIGN KEY (location_id)
    REFERENCES locations (location_id),
  CONSTRAINT chk_lots_temperature CHECK (temperature_zone IN
    ('ambient','chilled','frozen')),
  CONSTRAINT chk_lots_qty CHECK
    (available_qty >= 0 AND reserved_qty >= 0
      AND reserved_qty <= available_qty),
  CONSTRAINT chk_lots_state CHECK (state IN
    ('pending_inbound','stored','on_hold','depleted','expired','damaged'))
) ENGINE=InnoDB COMMENT='Manages storage location, expiration date, available quantity, reserved quantity, and status for each inventory lot.';

-- [업무] 입고·출고·이동·보충·폐기·복구·비상 대응을 하나의 업무 단위로 관리한다.
-- 주문과 로봇 미션을 별도 헤더로 나누지 않아 운영자가 한 화면에서 상태를 본다.
CREATE TABLE IF NOT EXISTS jobs (
  job_id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related job.',
  parent_job_id        BIGINT UNSIGNED NULL COMMENT 'Identifier of the related parent job.',
  job_code             VARCHAR(64) NOT NULL COMMENT 'Business code for job.',
  operation_type       VARCHAR(24) NOT NULL COMMENT 'Code identifying the operation type.',
  priority             VARCHAR(16) NOT NULL DEFAULT 'normal' COMMENT 'Job priority code: critical, high, normal, or low.',
  priority_rank        TINYINT UNSIGNED GENERATED ALWAYS AS (
    CASE priority
      WHEN 'critical' THEN 1
      WHEN 'high' THEN 2
      WHEN 'normal' THEN 3
      WHEN 'low' THEN 4
    END
  ) STORED COMMENT 'Automatically calculated numeric value used to sort priorities.',
  state                VARCHAR(24) NOT NULL DEFAULT 'queued' COMMENT 'Job lifecycle status: queued, assigned, running, held, completed, failed, or cancelled.',
  state_reason_code    VARCHAR(96) NULL COMMENT 'Stable reason code explaining the current job state.',
  state_detail         VARCHAR(1024) NULL COMMENT 'Operator-readable detail for the current job state.',
  result_code          VARCHAR(96) NULL COMMENT 'Stable final result code for a terminal job.',
  revision             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Optimistic-lock version used to detect concurrent updates.',
  requested_by         VARCHAR(64) NULL COMMENT 'Requested by for this record.',
  external_reference   VARCHAR(128) NULL COMMENT 'External reference for this record.',
  source_location_id   BIGINT UNSIGNED NULL COMMENT 'Identifier of the related source location.',
  destination_location_id BIGINT UNSIGNED NULL COMMENT 'Identifier of the related destination location.',
  due_at               DATETIME(6) NULL COMMENT 'Timestamp when the due event occurred.',
  assigned_mobile_id   VARCHAR(64) NULL COMMENT 'Identifier of the related assigned mobile.',
  failure_reason       VARCHAR(512) NULL COMMENT 'Specific reason the job or execution step failed.',
  context              JSON NULL COMMENT 'JSON object containing the job origin and extended context from external requests.',
  created_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the created event occurred.',
  started_at           DATETIME(6) NULL COMMENT 'Timestamp when the started event occurred.',
  completed_at         DATETIME(6) NULL COMMENT 'Timestamp when the completed event occurred.',
  updated_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                         ON UPDATE CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the updated event occurred.',
  PRIMARY KEY (job_id),
  UNIQUE KEY uq_jobs_code (job_code),
  UNIQUE KEY uq_jobs_external_reference (external_reference),
  KEY idx_jobs_dispatch (state, priority_rank, due_at, created_at),
  KEY idx_jobs_mobile (assigned_mobile_id, state),
  KEY idx_jobs_parent (parent_job_id),
  CONSTRAINT fk_jobs_parent FOREIGN KEY (parent_job_id)
    REFERENCES jobs (job_id),
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
    ('queued','assigned','running','held','completed','failed',
     'cancelled'))
) ENGINE=InnoDB COMMENT='Manages the full lifecycle of inbound, outbound, transfer, replenishment, disposal, recovery, and emergency jobs.';

-- [업무] 한 업무에 포함된 상품·lot·수량·검수 상태를 관리한다.
-- 입고 예정 품목, 출고 요청 품목, 실제로 배정된 lot을 같은 구조로 기록한다.
CREATE TABLE IF NOT EXISTS job_items (
  job_item_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related job item.',
  job_id              BIGINT UNSIGNED NOT NULL COMMENT 'Identifier of the related job.',
  product_code        VARCHAR(96) NOT NULL COMMENT 'Business code for product.',
  requested_qty       INT NOT NULL COMMENT 'Quantity for requested.',
  completed_qty       INT NOT NULL DEFAULT 0 COMMENT 'Quantity for completed.',
  lot_id              BIGINT UNSIGNED NULL COMMENT 'Identifier of the related lot.',
  handling_unit_code  VARCHAR(128) NULL COMMENT 'Business code for handling unit.',
  verification_state  VARCHAR(24) NOT NULL DEFAULT 'pending' COMMENT 'Verification state for this record.',
  metadata            JSON NULL COMMENT 'JSON object containing item-specific verification and external-order values.',
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
) ENGINE=InnoDB COMMENT='Manages products, requested and completed quantities, assigned lots, and verification status for each job.';

-- [업무] 업무를 Pinky 이동·OMX 조작·검수·인계 순서의 실행 단계로 나눈다.
-- rmf_task_id로 RMF 작업을 직접 연결하고, 모델 이름·버전으로 VLM/RL 판단을
-- 별도 테이블 없이 추적한다.
CREATE TABLE IF NOT EXISTS job_steps (
  job_step_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related job step.',
  job_id               BIGINT UNSIGNED NOT NULL COMMENT 'Identifier of the related job.',
  step_no              SMALLINT UNSIGNED NOT NULL COMMENT 'Execution order within the same job or recovery episode.',
  executor_type        VARCHAR(16) NOT NULL COMMENT 'Code identifying the executor type.',
  assigned_device_id   VARCHAR(64) NULL COMMENT 'Identifier of the related assigned device.',
  assignment_revision  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Assignment revision used to reject stale execution results.',
  action_type          VARCHAR(32) NOT NULL COMMENT 'Code identifying the action type.',
  target_location_id   BIGINT UNSIGNED NULL COMMENT 'Identifier of the related target location.',
  state                VARCHAR(24) NOT NULL DEFAULT 'pending' COMMENT 'Job-step status: pending, running, succeeded, failed, or cancelled.',
  rmf_task_id          VARCHAR(128) NULL COMMENT 'Identifier of the related rmf task.',
  rmf_phase_id         VARCHAR(128) NULL COMMENT 'Open-RMF phase identifier associated with this job step.',
  rmf_event_id         VARCHAR(128) NULL COMMENT 'Open-RMF event identifier associated with this job step.',
  rmf_status           VARCHAR(32) NULL COMMENT 'Latest Open-RMF task status observed for this job step.',
  rmf_status_observed_at DATETIME(6) NULL COMMENT 'Timestamp when the latest Open-RMF status was observed.',
  policy_name          VARCHAR(128) NULL COMMENT 'Name of the policy.',
  policy_version       VARCHAR(128) NULL COMMENT 'Policy version for this record.',
  retry_count          SMALLINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Total number of retries for this job step.',
  failure_reason       VARCHAR(512) NULL COMMENT 'Specific reason the job or execution step failed.',
  final_outcome_reason_code VARCHAR(96) NULL COMMENT 'Stable reason code for the final step outcome.',
  final_method_code    VARCHAR(96) NULL COMMENT 'Method code used by the final execution attempt.',
  input                JSON NULL COMMENT 'JSON object containing additional input data.',
  result               JSON NULL COMMENT 'JSON object containing additional result data.',
  started_at           DATETIME(6) NULL COMMENT 'Timestamp when the started event occurred.',
  completed_at         DATETIME(6) NULL COMMENT 'Timestamp when the completed event occurred.',
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
    ('pending','running','succeeded','failed','cancelled'))
) ENGINE=InnoDB COMMENT='Manages ordered execution steps for Pinky movement, OMX manipulation, verification, and handoff operations.';

-- [업무 실행 이력] Pinky·OMX·FMS가 한 단계에서 수행한 개별 시도를 추가 전용으로 기록한다.
-- 현재 상태는 job_steps에, 재시도별 방법·근거·성공 조건·관측값은 이 테이블에 보존한다.
CREATE TABLE IF NOT EXISTS job_step_attempts (
  attempt_uuid          CHAR(36) NOT NULL COMMENT 'UUID that identifies one execution attempt across systems.',
  job_step_id           BIGINT UNSIGNED NOT NULL COMMENT 'Identifier of the related job step.',
  assignment_revision   BIGINT UNSIGNED NOT NULL COMMENT 'Assignment revision used to reject stale execution results.',
  actor_role            VARCHAR(16) NOT NULL COMMENT 'Execution actor role: Pinky, OMX, or FMS.',
  actor_device_id       VARCHAR(64) NULL COMMENT 'Device identifier for the execution actor when the role is Pinky or OMX.',
  attempt_no            SMALLINT UNSIGNED NOT NULL COMMENT 'One-based attempt number within the step, revision, and actor role.',
  event_uuid            CHAR(36) NULL COMMENT 'UUID of the related event.',
  command_uuid          CHAR(36) NOT NULL COMMENT 'UUID of the command that initiated this execution attempt.',
  state                 VARCHAR(16) NOT NULL DEFAULT 'created' COMMENT 'Attempt progress: created, dispatched, running, reconciling, or finished.',
  outcome               VARCHAR(16) NULL COMMENT 'Terminal attempt outcome: succeeded, failed, aborted, or cancelled.',
  success               TINYINT(1) NULL COMMENT 'Indicates whether the terminal attempt satisfied every success criterion.',
  method_code           VARCHAR(96) NOT NULL COMMENT 'Stable code for the execution method selected before dispatch.',
  selection_reason_code VARCHAR(96) NULL COMMENT 'Stable reason code explaining why the execution method was selected.',
  outcome_reason_code   VARCHAR(96) NULL COMMENT 'Stable reason code produced from structured execution facts.',
  failure_domain        VARCHAR(32) NOT NULL DEFAULT 'none' COMMENT 'Layer responsible for failure, or none for successful and active attempts.',
  detail                VARCHAR(1024) NULL COMMENT 'Operator-readable detail that is not used as a decision branch.',
  parameters            JSON NULL COMMENT 'JSON object containing command and method parameters.',
  criteria              JSON NULL COMMENT 'JSON object containing expected, observed, and passed success criteria.',
  metrics               JSON NULL COMMENT 'JSON object containing measured execution values and units.',
  before_observation    JSON NULL COMMENT 'JSON object containing the state observed before execution.',
  after_observation     JSON NULL COMMENT 'JSON object containing the state observed after execution.',
  evidence_refs         JSON NULL COMMENT 'JSON array containing image, video, ROS bag, RMF log, or artifact references.',
  policy_source         VARCHAR(16) NOT NULL DEFAULT 'rule' COMMENT 'Source that selected the method, such as rule, RMF, Nav2, VLM, RL, or operator.',
  policy_name           VARCHAR(128) NULL COMMENT 'Name of the policy.',
  policy_version        VARCHAR(128) NULL COMMENT 'Policy version for this record.',
  model_name            VARCHAR(128) NULL COMMENT 'Name of the model.',
  model_version         VARCHAR(128) NULL COMMENT 'Model version for this record.',
  data_quality_status   VARCHAR(16) NOT NULL DEFAULT 'complete' COMMENT 'Quality status of the record: complete, incomplete, or invalid.',
  started_at            DATETIME(6) NULL COMMENT 'Timestamp when the started event occurred.',
  completed_at          DATETIME(6) NULL COMMENT 'Timestamp when the completed event occurred.',
  created_at            DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the created event occurred.',
  PRIMARY KEY (attempt_uuid),
  UNIQUE KEY uq_attempts_event (event_uuid),
  UNIQUE KEY uq_attempts_command (command_uuid),
  UNIQUE KEY uq_attempts_sequence
    (job_step_id, assignment_revision, actor_role, attempt_no),
  KEY idx_attempts_actor_time (actor_device_id, created_at),
  KEY idx_attempts_outcome (outcome, failure_domain, completed_at),
  CONSTRAINT fk_attempts_step FOREIGN KEY (job_step_id)
    REFERENCES job_steps (job_step_id) ON DELETE CASCADE,
  CONSTRAINT fk_attempts_device FOREIGN KEY (actor_device_id)
    REFERENCES devices (device_id),
  CONSTRAINT chk_attempts_number CHECK (attempt_no > 0),
  CONSTRAINT chk_attempts_actor CHECK (actor_role IN ('pinky','omx','fms')),
  CONSTRAINT chk_attempts_actor_device CHECK
    ((actor_role IN ('pinky','omx') AND actor_device_id IS NOT NULL) OR
     (actor_role = 'fms')),
  CONSTRAINT chk_attempts_state CHECK (state IN
    ('created','dispatched','running','reconciling','finished')),
  CONSTRAINT chk_attempts_outcome CHECK
    (outcome IS NULL OR outcome IN ('succeeded','failed','aborted','cancelled')),
  CONSTRAINT chk_attempts_failure_domain CHECK (failure_domain IN
    ('none','robot','perception','navigation','manipulation','safety',
     'integration','operator','unknown')),
  CONSTRAINT chk_attempts_policy_source CHECK (policy_source IN
    ('rule','rmf','nav2','vlm','rl','operator','hardware')),
  CONSTRAINT chk_attempts_data_quality CHECK (data_quality_status IN
    ('complete','incomplete','invalid')),
  CONSTRAINT chk_attempts_success CHECK
    (success IS NULL OR success IN (0, 1)),
  CONSTRAINT chk_attempts_terminal CHECK
    ((state <> 'finished' AND outcome IS NULL AND success IS NULL
      AND outcome_reason_code IS NULL AND completed_at IS NULL) OR
     (state = 'finished' AND outcome IS NOT NULL AND success IS NOT NULL
      AND outcome_reason_code IS NOT NULL AND completed_at IS NOT NULL
      AND started_at IS NOT NULL AND completed_at >= started_at)),
  CONSTRAINT chk_attempts_success_outcome CHECK
    ((success IS NULL AND outcome IS NULL) OR
     (success = 1 AND outcome = 'succeeded' AND failure_domain = 'none') OR
     (success = 0 AND outcome IN ('failed','aborted','cancelled'))),
  CONSTRAINT chk_attempts_lineage CHECK
    ((policy_name IS NULL AND policy_version IS NULL) OR
     (policy_name IS NOT NULL AND policy_version IS NOT NULL)),
  CONSTRAINT chk_attempts_model_lineage CHECK
    ((model_name IS NULL AND model_version IS NULL) OR
     (model_name IS NOT NULL AND model_version IS NOT NULL))
) ENGINE=InnoDB COMMENT='Records each Pinky, OMX, or FMS execution attempt with structured methods, evidence, criteria, metrics, and outcomes.';

-- [점유] 병목 통로의 진입 권한과 도크·포장대·OMX의 사용 시간을 관리한다.
-- 병목은 map_feature_id를 잠그고, 시간 예약은 예정 사용 구간이 겹치지 않도록
-- FMS가 관리한다. 활성 상태의 실제 점유는 유일 키로 한 장비만 허용한다.
CREATE TABLE IF NOT EXISTS reservations (
  reservation_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related reservation.',
  job_id               BIGINT UNSIGNED NOT NULL COMMENT 'Identifier of the related job.',
  job_step_id          BIGINT UNSIGNED NULL COMMENT 'Identifier of the related job step.',
  location_id          BIGINT UNSIGNED NULL COMMENT 'Identifier of the related location.',
  device_id            VARCHAR(64) NULL COMMENT 'Identifier of the related device.',
  map_feature_id       BIGINT UNSIGNED NULL COMMENT 'Identifier of the related map feature.',
  reservation_mode     VARCHAR(24) NOT NULL DEFAULT 'exclusive_lock' COMMENT 'Reservation mode for this record.',
  state                VARCHAR(16) NOT NULL DEFAULT 'reserved' COMMENT 'Reservation status: reserved, in use, released, expired, or cancelled.',
  planned_start_at     DATETIME(6) NULL COMMENT 'Timestamp when the planned start event occurred.',
  planned_end_at       DATETIME(6) NULL COMMENT 'Timestamp when the planned end event occurred.',
  entered_at           DATETIME(6) NULL COMMENT 'Timestamp when the entered event occurred.',
  exited_at            DATETIME(6) NULL COMMENT 'Timestamp when the exited event occurred.',
  expires_at           DATETIME(6) NOT NULL COMMENT 'Timestamp when the expires event occurred.',
  created_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the created event occurred.',
  released_at          DATETIME(6) NULL COMMENT 'Timestamp when the released event occurred.',
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
  ) STORED COMMENT 'Calculated unique key that prevents conflicting active resource reservations.',
  PRIMARY KEY (reservation_id),
  UNIQUE KEY uq_reservations_active_resource (active_resource_key),
  KEY idx_reservations_expiry (state, expires_at),
  KEY idx_reservations_job (job_id),
  KEY idx_reservations_location_schedule
    (location_id, state, planned_start_at, planned_end_at),
  KEY idx_reservations_device_schedule
    (device_id, state, planned_start_at, planned_end_at),
  KEY idx_reservations_feature_state (map_feature_id, state),
  KEY idx_reservations_feature_expiry (map_feature_id, state, expires_at),
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
  CONSTRAINT chk_reservations_expiry CHECK (expires_at > created_at),
  CONSTRAINT chk_reservations_state CHECK (state IN
    ('reserved','in_use','released','expired','cancelled'))
) ENGINE=InnoDB COMMENT='Manages access to bottlenecks and exclusive or time-based reservations for docks, workstations, and devices.';

-- [재고] 재고 수량이 변한 모든 근거를 추가만 가능한 원장으로 남긴다.
-- inventory_lots의 현재 수량 갱신과 이 INSERT는 반드시 같은 트랜잭션에서 처리한다.
CREATE TABLE IF NOT EXISTS inventory_moves (
  inventory_move_id    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related inventory move.',
  lot_id               BIGINT UNSIGNED NOT NULL COMMENT 'Identifier of the related lot.',
  job_id               BIGINT UNSIGNED NULL COMMENT 'Identifier of the related job.',
  job_step_id          BIGINT UNSIGNED NULL COMMENT 'Identifier of the related job step.',
  move_type            VARCHAR(24) NOT NULL COMMENT 'Code identifying the move type.',
  quantity_delta       INT NOT NULL COMMENT 'Amount added to or removed from the available quantity.',
  quantity_after       INT NOT NULL COMMENT 'Available quantity after applying the inventory movement.',
  reserved_delta       INT NOT NULL DEFAULT 0 COMMENT 'Amount added to or removed from the reserved quantity.',
  reserved_after       INT NOT NULL DEFAULT 0 COMMENT 'Reserved quantity after applying the inventory movement.',
  recorded_by          VARCHAR(96) NOT NULL COMMENT 'Recorded by for this record.',
  recorded_at          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the recorded event occurred.',
  note                 VARCHAR(512) NULL COMMENT 'Additional explanation for the inventory movement.',
  PRIMARY KEY (inventory_move_id),
  KEY idx_inventory_moves_lot_at (lot_id, recorded_at),
  KEY idx_inventory_moves_job (job_id),
  CONSTRAINT fk_inventory_moves_lot FOREIGN KEY (lot_id)
    REFERENCES inventory_lots (lot_id),
  CONSTRAINT fk_inventory_moves_job FOREIGN KEY (job_id)
    REFERENCES jobs (job_id),
  CONSTRAINT fk_inventory_moves_step FOREIGN KEY (job_step_id)
    REFERENCES job_steps (job_step_id),
  CONSTRAINT chk_inventory_moves_qty CHECK
    (quantity_after >= 0 AND reserved_after >= 0
      AND reserved_after <= quantity_after),
  CONSTRAINT chk_inventory_moves_type CHECK (move_type IN
    ('inbound','outbound','reservation','reservation_release','adjustment',
     'disposal','cycle_count'))
) ENGINE=InnoDB COMMENT='Records immutable inventory and reservation quantity changes, resulting balances, reasons, and responsible actors.';

-- [장비] 장비별 최신 상태를 한 행으로 보관해 관제 화면과 재시작 복구에 사용한다.
-- Pinky는 위치·배터리를, OMX는 관절·카메라·툴 상태를 details에 기록한다.
CREATE TABLE IF NOT EXISTS device_states (
  device_id            VARCHAR(64) NOT NULL COMMENT 'Identifier of the related device.',
  observed_at          DATETIME(6) NOT NULL COMMENT 'Timestamp when the observed event occurred.',
  state                VARCHAR(24) NOT NULL COMMENT 'Current operating-state code reported by the device.',
  health               VARCHAR(16) NOT NULL DEFAULT 'ok' COMMENT 'Device health code, such as healthy, warning, error, or unreachable.',
  current_job_step_id  BIGINT UNSIGNED NULL COMMENT 'Identifier of the related current job step.',
  pose_x               DOUBLE NULL COMMENT 'X coordinate in the map frame, in meters.',
  pose_y               DOUBLE NULL COMMENT 'Y coordinate in the map frame, in meters.',
  pose_yaw             DOUBLE NULL COMMENT 'Heading in the map frame, in radians.',
  battery_pct          DECIMAL(5,2) NULL COMMENT 'Remaining battery percentage reported by the device.',
  progress             DECIMAL(5,4) NULL COMMENT 'Progress of the current job step, from 0 through 1.',
  details              JSON NULL COMMENT 'JSON object containing additional details data.',
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
) ENGINE=InnoDB COMMENT='Stores the latest heartbeat, location, battery level, progress, health, and active step for each device.';

-- [연동] RMF 배차, Pinky/OMX 명령, 장비 응답을 모두 담는 내구성 있는 메시지 큐다.
-- inbound/outbound와 idempotency_key를 함께 기록해 재전송 시 중복 실행을 막는다.
CREATE TABLE IF NOT EXISTS integration_messages (
  message_id           CHAR(36) NOT NULL COMMENT 'Identifier of the related message.',
  direction            VARCHAR(8) NOT NULL COMMENT 'Message direction: inbound or outbound.',
  channel              VARCHAR(16) NOT NULL COMMENT 'Channel for this record.',
  device_id            VARCHAR(64) NULL COMMENT 'Identifier of the related device.',
  job_step_id          BIGINT UNSIGNED NULL COMMENT 'Identifier of the related job step.',
  message_type         VARCHAR(64) NOT NULL COMMENT 'Code identifying the message type.',
  idempotency_key      VARCHAR(160) NOT NULL COMMENT 'Business key that prevents duplicate execution of the same request.',
  external_reference   VARCHAR(160) NULL COMMENT 'External reference for this record.',
  state                VARCHAR(16) NOT NULL DEFAULT 'pending' COMMENT 'Message status: pending, sent, acknowledged, failed, or dead.',
  attempts             SMALLINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Total number of message delivery attempts.',
  next_attempt_at      DATETIME(6) NULL COMMENT 'Timestamp when the next attempt event occurred.',
  payload              JSON NOT NULL COMMENT 'JSON object containing additional payload data.',
  last_error           VARCHAR(512) NULL COMMENT 'Last error for this record.',
  created_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the created event occurred.',
  sent_at              DATETIME(6) NULL COMMENT 'Timestamp when the sent event occurred.',
  acknowledged_at      DATETIME(6) NULL COMMENT 'Timestamp when the acknowledged event occurred.',
  PRIMARY KEY (message_id),
  UNIQUE KEY uq_messages_dedupe (direction, channel, idempotency_key),
  KEY idx_messages_delivery (direction, state, next_attempt_at, created_at),
  KEY idx_messages_step (job_step_id),
  CONSTRAINT fk_messages_device FOREIGN KEY (device_id)
    REFERENCES devices (device_id),
  CONSTRAINT fk_messages_step FOREIGN KEY (job_step_id)
    REFERENCES job_steps (job_step_id) ON DELETE SET NULL,
  CONSTRAINT chk_messages_direction CHECK (direction IN ('inbound','outbound')),
  CONSTRAINT chk_messages_channel CHECK (channel IN ('rmf','pinky','omx')),
  CONSTRAINT chk_messages_state CHECK (state IN
    ('pending','sent','acknowledged','completed','failed','dead_letter'))
) ENGINE=InnoDB COMMENT='Manages idempotency, retries, and delivery status for commands and responses exchanged with RMF, Pinky, and OMX.';

-- [운영·AI·안전] 현재 진행 중인 안전 사고를 관리한다.
-- 단순 로그와 달리 active 상태·영향 위치·해제 승인자를 가지며, FMS가 해당 구역을
-- 차단하고 RMF 재계획 또는 정지를 요청하는 기준이 된다.
CREATE TABLE IF NOT EXISTS incidents (
  incident_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related incident.',
  incident_code        VARCHAR(64) NOT NULL COMMENT 'Business code for incident.',
  incident_type        VARCHAR(32) NOT NULL COMMENT 'Code identifying the incident type.',
  severity             VARCHAR(16) NOT NULL COMMENT 'Severity for this record.',
  state                VARCHAR(24) NOT NULL DEFAULT 'active' COMMENT 'Safety-incident status: open, acknowledged, mitigating, resolved, or closed.',
  location_id          BIGINT UNSIGNED NULL COMMENT 'Identifier of the related location.',
  geometry             JSON NULL COMMENT 'JSON geometry describing the point or area affected by the safety incident.',
  description          VARCHAR(512) NOT NULL COMMENT 'Operator-readable description of the cause and circumstances of the safety incident.',
  raised_by_worker_id  VARCHAR(64) NULL COMMENT 'Identifier of the related raised by worker.',
  acknowledged_by_worker_id VARCHAR(64) NULL COMMENT 'Identifier of the related acknowledged by worker.',
  resolved_by_worker_id VARCHAR(64) NULL COMMENT 'Identifier of the related resolved by worker.',
  raised_at            DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the raised event occurred.',
  acknowledged_at      DATETIME(6) NULL COMMENT 'Timestamp when the acknowledged event occurred.',
  resolved_at          DATETIME(6) NULL COMMENT 'Timestamp when the resolved event occurred.',
  context              JSON NULL COMMENT 'JSON object containing sensor observations, response procedures, and other incident details.',
  PRIMARY KEY (incident_id),
  UNIQUE KEY uq_incidents_code (incident_code),
  KEY idx_incidents_active (state, severity, raised_at),
  KEY idx_incidents_location (location_id, state),
  CONSTRAINT fk_incidents_location FOREIGN KEY (location_id)
    REFERENCES locations (location_id),
  CONSTRAINT fk_incidents_raised_by FOREIGN KEY (raised_by_worker_id)
    REFERENCES workers (worker_id),
  CONSTRAINT fk_incidents_acknowledged_by FOREIGN KEY (acknowledged_by_worker_id)
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
) ENGINE=InnoDB COMMENT='Manages safety incidents from detection through resolution, including people, fall risks, collision risks, and emergency stops.';

-- [운영·AI·안전] 작업·안전·VLM·RL 판단을 시간 순서대로 추가만 가능한 로그로 남긴다.
-- VLM/RL 제안은 여기 기록한 뒤 Safety Supervisor가 승인한 허용된 복구 행동만 실행한다.
CREATE TABLE IF NOT EXISTS operation_events (
  event_id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related event.',
  event_uuid           CHAR(36) NOT NULL COMMENT 'UUID of the related event.',
  correlation_uuid     CHAR(36) NULL COMMENT 'UUID that groups events belonging to the same distributed operation.',
  causation_event_uuid CHAR(36) NULL COMMENT 'UUID of the event that directly caused this event.',
  attempt_uuid         CHAR(36) NULL COMMENT 'UUID that identifies one execution attempt across systems.',
  occurred_at          DATETIME(6) NOT NULL COMMENT 'Timestamp when the occurred event occurred.',
  actor_worker_id      VARCHAR(64) NULL COMMENT 'Identifier of the related actor worker.',
  device_id            VARCHAR(64) NULL COMMENT 'Identifier of the related device.',
  job_id               BIGINT UNSIGNED NULL COMMENT 'Identifier of the related job.',
  job_step_id          BIGINT UNSIGNED NULL COMMENT 'Identifier of the related job step.',
  incident_id          BIGINT UNSIGNED NULL COMMENT 'Identifier of the related incident.',
  severity             VARCHAR(16) NOT NULL DEFAULT 'info' COMMENT 'Severity for this record.',
  category             VARCHAR(24) NOT NULL COMMENT 'Category for this record.',
  event_type           VARCHAR(96) NOT NULL COMMENT 'Code identifying the event type.',
  message              VARCHAR(512) NULL COMMENT 'Operator-readable summary of the operation event.',
  model_name           VARCHAR(128) NULL COMMENT 'Name of the model.',
  model_version        VARCHAR(128) NULL COMMENT 'Model version for this record.',
  confidence           DECIMAL(6,5) NULL COMMENT 'Model confidence value from 0 through 1.',
  safety_decision      VARCHAR(16) NULL COMMENT 'Safety decision for this record.',
  payload              JSON NULL COMMENT 'JSON object containing detailed observations and decision evidence for the event type.',
  PRIMARY KEY (event_id),
  UNIQUE KEY uq_operation_events_uuid (event_uuid),
  KEY idx_events_occurred_at (occurred_at DESC),
  KEY idx_events_actor_at (actor_worker_id, occurred_at),
  KEY idx_events_device_at (device_id, occurred_at),
  KEY idx_events_job_at (job_id, occurred_at),
  KEY idx_events_incident_at (incident_id, occurred_at),
  KEY idx_events_category_at (category, occurred_at),
  KEY idx_events_correlation (correlation_uuid, occurred_at),
  KEY idx_events_attempt (attempt_uuid, occurred_at),
  CONSTRAINT fk_events_device FOREIGN KEY (device_id)
    REFERENCES devices (device_id),
  CONSTRAINT fk_events_actor FOREIGN KEY (actor_worker_id)
    REFERENCES workers (worker_id),
  CONSTRAINT fk_events_job FOREIGN KEY (job_id)
    REFERENCES jobs (job_id),
  CONSTRAINT fk_events_step FOREIGN KEY (job_step_id)
    REFERENCES job_steps (job_step_id),
  CONSTRAINT fk_events_attempt FOREIGN KEY (attempt_uuid)
    REFERENCES job_step_attempts (attempt_uuid),
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
) ENGINE=InnoDB COMMENT='Records chronological audit events for jobs, devices, safety decisions, model decisions, and operator actions.';

-- [학습 원본] 이미지·영상·point cloud·ROS bag·Cyclo episode·데이터셋·모델의
-- 파일 자체가 아니라 위치와 무결성 정보를 관리한다. 원본은 NAS/MinIO/S3에 저장한다.
CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related artifact.',
  artifact_type         VARCHAR(24) NOT NULL COMMENT 'Code identifying the artifact type.',
  storage_uri           VARCHAR(1024) NOT NULL COMMENT 'URI of the stored storage data.',
  storage_uri_hash      BINARY(32) GENERATED ALWAYS AS
                          (UNHEX(SHA2(storage_uri, 256))) STORED COMMENT 'Storage uri hash for this record.',
  sha256                CHAR(64) NOT NULL COMMENT 'SHA-256 hash used to verify the integrity of the sha256.',
  mime_type             VARCHAR(128) NULL COMMENT 'Code identifying the mime type.',
  byte_size             BIGINT UNSIGNED NULL COMMENT 'Byte size for this record.',
  device_id             VARCHAR(64) NULL COMMENT 'Identifier of the related device.',
  job_id                BIGINT UNSIGNED NULL COMMENT 'Identifier of the related job.',
  job_step_id           BIGINT UNSIGNED NULL COMMENT 'Identifier of the related job step.',
  event_id              BIGINT UNSIGNED NULL COMMENT 'Identifier of the related event.',
  model_name            VARCHAR(128) NULL COMMENT 'Name of the model.',
  model_version         VARCHAR(128) NULL COMMENT 'Model version for this record.',
  metadata              JSON NULL COMMENT 'JSON object containing artifact-specific details such as codec, resolution, and dataset split.',
  captured_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the captured event occurred.',
  PRIMARY KEY (artifact_id),
  UNIQUE KEY uq_artifacts_sha_uri (sha256, storage_uri_hash),
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
) ENGINE=InnoDB COMMENT='Manages storage locations and integrity metadata for videos, images, rosbags, episodes, datasets, models, and reports.';

-- [복구 Reference Memory] safe_node의 좌표를 복제하지 않고 복구 목표로서의
-- 사용 가능 상태와 신뢰도만 관리한다. location_type = 'safe_node' 검증과 지도
-- revision 일치 검증은 다른 행 조회가 필요한 규칙이므로 Gateway가 담당한다.
CREATE TABLE IF NOT EXISTS location_recovery_profiles (
  reference_node_uuid    CHAR(36) NOT NULL COMMENT 'UUID of the related reference node.',
  location_id            BIGINT UNSIGNED NOT NULL COMMENT 'Identifier of the related location.',
  map_revision           VARCHAR(128) NOT NULL COMMENT 'Map revision for this record.',
  recovery_roles         JSON NOT NULL COMMENT 'Recovery roles for this record.',
  availability_status    VARCHAR(16) NOT NULL DEFAULT 'active' COMMENT 'Current availability status code.',
  reliability_alpha      DECIMAL(12,4) NOT NULL DEFAULT 1.0000 COMMENT 'Accumulated beta-distribution alpha value for successful recovery-node outcomes.',
  reliability_beta       DECIMAL(12,4) NOT NULL DEFAULT 1.0000 COMMENT 'Accumulated beta-distribution beta value for failed recovery-node outcomes.',
  last_verified_at       DATETIME(6) NULL COMMENT 'Timestamp when the last verified event occurred.',
  last_outcome_at        DATETIME(6) NULL COMMENT 'Timestamp when the last outcome event occurred.',
  reviewed_by_worker_id  VARCHAR(64) NULL COMMENT 'Identifier of the related reviewed by worker.',
  revision               BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Optimistic-lock version used to detect concurrent updates.',
  notes                  VARCHAR(1024) NULL COMMENT 'Review notes and cautions for the recovery reference node.',
  created_at             DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the created event occurred.',
  updated_at             DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                           ON UPDATE CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the updated event occurred.',
  PRIMARY KEY (reference_node_uuid),
  UNIQUE KEY uq_recovery_profiles_location (location_id),
  KEY idx_recovery_profiles_lookup
    (map_revision, availability_status, last_verified_at),
  KEY idx_recovery_profiles_reviewer (reviewed_by_worker_id),
  CONSTRAINT fk_recovery_profiles_location FOREIGN KEY (location_id)
    REFERENCES locations (location_id),
  CONSTRAINT fk_recovery_profiles_reviewer FOREIGN KEY (reviewed_by_worker_id)
    REFERENCES workers (worker_id),
  CONSTRAINT chk_recovery_profiles_map_revision CHECK
    (CHAR_LENGTH(TRIM(map_revision)) > 0),
  CONSTRAINT chk_recovery_profiles_roles CHECK
    (JSON_TYPE(recovery_roles) = 'ARRAY'
      AND JSON_LENGTH(recovery_roles) > 0
      AND JSON_CONTAINS(
        JSON_ARRAY('wait','retreat','detour','rejoin'), recovery_roles
      )),
  CONSTRAINT chk_recovery_profiles_status CHECK (availability_status IN
    ('active','suspect','quarantined','retired')),
  CONSTRAINT chk_recovery_profiles_reliability CHECK
    (reliability_alpha > 0 AND reliability_beta > 0)
) ENGINE=InnoDB COMMENT='Manages recovery roles, availability, and beta-distribution reliability values for each safety node.';

-- ============================================================================
-- VLM/RL 복구 경험(Episodic Memory)
--
-- trihouse_fms와 FK를 만들지 않는다. FMS event/job/reference UUID의 존재와
-- map revision 일치는 Gateway가 확인해 두 DB의 백업·복구 수명주기를 분리한다.
-- ============================================================================

CREATE DATABASE IF NOT EXISTS `trihouse_recovery`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `trihouse_recovery`;

-- 복구 trigger부터 성공·중단·실패까지 한 사건과 사용 모델 계보를 저장한다.
CREATE TABLE IF NOT EXISTS recovery_episodes (
  recovery_episode_uuid     CHAR(36) NOT NULL COMMENT 'UUID of the related recovery episode.',
  source_event_uuid         CHAR(36) NULL COMMENT 'UUID of the related source event.',
  device_id                 VARCHAR(64) NOT NULL COMMENT 'Identifier of the related device.',
  fms_job_id                BIGINT UNSIGNED NULL COMMENT 'Identifier of the related fms job.',
  fms_job_step_id           BIGINT UNSIGNED NULL COMMENT 'Identifier of the related fms job step.',
  map_name                  VARCHAR(96) NOT NULL COMMENT 'Name of the map.',
  map_revision              VARCHAR(128) NOT NULL COMMENT 'Map revision for this record.',
  trigger_type              VARCHAR(24) NOT NULL COMMENT 'Code identifying the trigger type.',
  vlm_model_name            VARCHAR(128) NULL COMMENT 'Name of the vlm model.',
  vlm_model_version         VARCHAR(128) NULL COMMENT 'Vlm model version for this record.',
  recovery_policy_name      VARCHAR(128) NOT NULL COMMENT 'Name of the recovery policy.',
  recovery_policy_version   VARCHAR(128) NOT NULL COMMENT 'Recovery policy version for this record.',
  started_at                DATETIME(6) NOT NULL COMMENT 'Timestamp when the started event occurred.',
  ended_at                  DATETIME(6) NULL COMMENT 'Timestamp when the ended event occurred.',
  final_status              VARCHAR(16) NOT NULL DEFAULT 'running' COMMENT 'Current final status code.',
  summary                   VARCHAR(1024) NULL COMMENT 'Summary for this record.',
  created_at                DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the created event occurred.',
  PRIMARY KEY (recovery_episode_uuid),
  KEY idx_recovery_episodes_source_event (source_event_uuid),
  KEY idx_recovery_episodes_device_started (device_id, started_at),
  KEY idx_recovery_episodes_job (fms_job_id, fms_job_step_id),
  KEY idx_recovery_episodes_export
    (map_name, map_revision, final_status, started_at),
  CONSTRAINT chk_recovery_episodes_map CHECK
    (CHAR_LENGTH(TRIM(map_name)) > 0
      AND CHAR_LENGTH(TRIM(map_revision)) > 0),
  CONSTRAINT chk_recovery_episodes_trigger CHECK (trigger_type IN
    ('blocked','person','low_visibility','localization')),
  CONSTRAINT chk_recovery_episodes_vlm_lineage CHECK
    ((vlm_model_name IS NULL AND vlm_model_version IS NULL) OR
     (vlm_model_name IS NOT NULL AND vlm_model_version IS NOT NULL)),
  CONSTRAINT chk_recovery_episodes_status CHECK (final_status IN
    ('running','succeeded','aborted','failed')),
  CONSTRAINT chk_recovery_episodes_time CHECK
    ((final_status = 'running' AND ended_at IS NULL) OR
     (final_status <> 'running' AND ended_at IS NOT NULL
       AND ended_at >= started_at))
) ENGINE=InnoDB COMMENT='Records each recovery incident from trigger to completion, including VLM and recovery-policy lineage.';

-- 실제로 실행한 복구 행동 한 번을 저장한다. SAC replay export의 원본이며,
-- 실행되지 않은 VLM 후보와 Safety 결정은 FMS operation_events에만 남긴다.
CREATE TABLE IF NOT EXISTS recovery_steps (
  recovery_step_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identifier of the related recovery step.',
  recovery_episode_uuid  CHAR(36) NOT NULL COMMENT 'UUID of the related recovery episode.',
  step_no                SMALLINT UNSIGNED NOT NULL COMMENT 'Execution order within the same job or recovery episode.',
  reference_node_uuid    CHAR(36) NULL COMMENT 'UUID of the FMS recovery reference node selected as the action target; no physical cross-database foreign key is used.',
  action_type            VARCHAR(16) NOT NULL COMMENT 'Code identifying the action type.',
  target_pose            JSON NULL COMMENT 'JSON object containing the target position and orientation for the recovery action.',
  before_state_uri       VARCHAR(1024) NULL COMMENT 'URI of the stored before state data.',
  before_state_sha256    CHAR(64) NULL COMMENT 'SHA-256 hash used to verify the integrity of the before state.',
  after_state_uri        VARCHAR(1024) NULL COMMENT 'URI of the stored after state data.',
  after_state_sha256     CHAR(64) NULL COMMENT 'SHA-256 hash used to verify the integrity of the after state.',
  reward_components      JSON NULL COMMENT 'JSON object containing individual reward components for reinforcement learning.',
  outcome_class          VARCHAR(16) NOT NULL COMMENT 'Outcome class for this record.',
  execution_status       VARCHAR(16) NOT NULL DEFAULT 'queued' COMMENT 'Current execution status code.',
  is_terminal            TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Indicates whether this recovery action is the final step of the episode.',
  started_at             DATETIME(6) NOT NULL COMMENT 'Timestamp when the started event occurred.',
  completed_at           DATETIME(6) NULL COMMENT 'Timestamp when the completed event occurred.',
  created_at             DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'Timestamp when the created event occurred.',
  PRIMARY KEY (recovery_step_id),
  UNIQUE KEY uq_recovery_steps_order (recovery_episode_uuid, step_no),
  KEY idx_recovery_steps_reference (reference_node_uuid),
  KEY idx_recovery_steps_export
    (outcome_class, execution_status, completed_at),
  CONSTRAINT fk_recovery_steps_episode FOREIGN KEY (recovery_episode_uuid)
    REFERENCES recovery_episodes (recovery_episode_uuid) ON DELETE CASCADE,
  CONSTRAINT chk_recovery_steps_number CHECK (step_no > 0),
  CONSTRAINT chk_recovery_steps_action CHECK (action_type IN
    ('wait','retreat','detour','rejoin','stop')),
  CONSTRAINT chk_recovery_steps_target_pose CHECK
    (target_pose IS NULL OR JSON_TYPE(target_pose) = 'OBJECT'),
  CONSTRAINT chk_recovery_steps_before_state CHECK
    ((before_state_uri IS NULL AND before_state_sha256 IS NULL) OR
     (before_state_uri IS NOT NULL AND before_state_sha256 IS NOT NULL)),
  CONSTRAINT chk_recovery_steps_after_state CHECK
    ((after_state_uri IS NULL AND after_state_sha256 IS NULL) OR
     (after_state_uri IS NOT NULL AND after_state_sha256 IS NOT NULL)),
  CONSTRAINT chk_recovery_steps_reward CHECK
    (reward_components IS NULL OR JSON_TYPE(reward_components) = 'OBJECT'),
  CONSTRAINT chk_recovery_steps_outcome CHECK (outcome_class IN
    ('safe','boundary','critical')),
  CONSTRAINT chk_recovery_steps_execution CHECK (execution_status IN
    ('queued','running','succeeded','failed','cancelled')),
  CONSTRAINT chk_recovery_steps_terminal CHECK (is_terminal IN (0, 1)),
  CONSTRAINT chk_recovery_steps_time CHECK
    ((execution_status IN ('queued','running') AND completed_at IS NULL
      AND is_terminal = 0) OR
     (execution_status IN ('succeeded','failed','cancelled')
      AND completed_at IS NOT NULL AND completed_at >= started_at))
) ENGINE=InnoDB COMMENT='Records executed recovery actions, observations, rewards, outcomes, and completion status in sequence.';
