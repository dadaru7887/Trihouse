-- Add canonical map authoring and immutable publication tables to an existing
-- Trihouse MySQL volume. Safe to run more than once.
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
  lane_count          INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Number of active draft lanes.',
  draft_revision      BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT 'Optimistic draft version.',
  created_at          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                        ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (project_id),
  UNIQUE KEY uq_map_projects_name (map_name),
  CONSTRAINT chk_map_projects_payload CHECK (JSON_TYPE(payload) = 'OBJECT')
) ENGINE=InnoDB COMMENT='Stores editable map projects used to generate Open-RMF artifacts.';

CREATE TABLE IF NOT EXISTS map_project_waypoints (
  waypoint_uuid       CHAR(36) NOT NULL COMMENT 'Immutable waypoint UUID.',
  project_id          BIGINT UNSIGNED NOT NULL,
  seq                 INT UNSIGNED NOT NULL COMMENT 'Stable display order within the current draft.',
  location_code       VARCHAR(96) NULL COMMENT 'Stable FMS location business key for operational waypoints.',
  rmf_waypoint_name   VARCHAR(128) NOT NULL COMMENT 'Waypoint name written to the RMF graph.',
  category            VARCHAR(32) NOT NULL COMMENT 'UI waypoint category.',
  x                   DOUBLE NOT NULL COMMENT 'Drawing-space X coordinate used by the editor.',
  y                   DOUBLE NOT NULL COMMENT 'Drawing-space Y coordinate used by the editor.',
  yaw                 DOUBLE NULL COMMENT 'Drawing-space heading retained by the editor.',
  map_x               DOUBLE NULL COMMENT 'Published RMF map-frame X coordinate in meters.',
  map_y               DOUBLE NULL COMMENT 'Published RMF map-frame Y coordinate in meters.',
  map_yaw             DOUBLE NULL COMMENT 'Published RMF map-frame heading in radians.',
  active              TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (project_id, seq),
  UNIQUE KEY uq_map_waypoints_uuid (waypoint_uuid),
  UNIQUE KEY uq_map_waypoints_name (project_id, rmf_waypoint_name),
  UNIQUE KEY uq_map_waypoints_location (project_id, location_code),
  CONSTRAINT fk_map_waypoints_project FOREIGN KEY (project_id)
    REFERENCES map_projects (project_id) ON DELETE CASCADE,
  CONSTRAINT chk_map_waypoints_category CHECK (category IN
    ('대기','주차','홈','충전','픽업','드랍오프','설비','일반')),
  CONSTRAINT chk_map_waypoints_uuid CHECK
    (waypoint_uuid REGEXP '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
) ENGINE=InnoDB COMMENT='Stores stable waypoint identities and FMS location mappings for map drafts.';

CREATE TABLE IF NOT EXISTS map_project_lanes (
  lane_uuid            CHAR(36) NOT NULL COMMENT 'Immutable lane UUID.',
  project_id           BIGINT UNSIGNED NOT NULL,
  seq                  INT UNSIGNED NOT NULL COMMENT 'Display order within the current draft.',
  start_waypoint_uuid  CHAR(36) NOT NULL,
  end_waypoint_uuid    CHAR(36) NOT NULL,
  direction            VARCHAR(16) NOT NULL,
  speed_limit          DOUBLE NULL,
  orientation          VARCHAR(16) NULL,
  mutex_group          VARCHAR(64) NULL,
  active               TINYINT(1) NOT NULL DEFAULT 1,
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
) ENGINE=InnoDB COMMENT='Stores lane topology by stable waypoint UUID instead of floating-point coordinates.';

CREATE TABLE IF NOT EXISTS map_project_files (
  project_id    BIGINT UNSIGNED NOT NULL,
  file_name     VARCHAR(255) NOT NULL,
  kind          VARCHAR(32) NOT NULL,
  description   VARCHAR(512) NOT NULL DEFAULT '',
  executable    TINYINT(1) NOT NULL DEFAULT 0,
  content       LONGTEXT NOT NULL,
  generated_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (project_id, file_name),
  KEY idx_map_files_kind (project_id, kind),
  CONSTRAINT fk_map_files_project FOREIGN KEY (project_id)
    REFERENCES map_projects (project_id) ON DELETE CASCADE
) ENGINE=InnoDB COMMENT='Stores generated launch, fleet, bridge, and script files for each editable map project.';

CREATE TABLE IF NOT EXISTS map_project_fleets (
  project_id       BIGINT UNSIGNED NOT NULL,
  fleet_name       VARCHAR(96) NOT NULL,
  settings         JSON NOT NULL,
  updated_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                     ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (project_id),
  CONSTRAINT fk_map_fleets_project FOREIGN KEY (project_id)
    REFERENCES map_projects (project_id) ON DELETE CASCADE,
  CONSTRAINT chk_map_fleets_settings CHECK (JSON_TYPE(settings) = 'OBJECT')
) ENGINE=InnoDB COMMENT='Stores draft Open-RMF fleet parameters per map project.';

CREATE TABLE IF NOT EXISTS map_project_robots (
  project_id        BIGINT UNSIGNED NOT NULL,
  robot_id          VARCHAR(64) NOT NULL,
  seq               INT UNSIGNED NOT NULL,
  display_name      VARCHAR(128) NOT NULL,
  model             VARCHAR(96) NOT NULL,
  kind              VARCHAR(16) NOT NULL,
  data_source       VARCHAR(16) NOT NULL,
  gz_name           VARCHAR(64) NOT NULL,
  zones             JSON NOT NULL,
  charger_waypoint_uuid CHAR(36) NULL,
  spawn_x           DOUBLE NULL,
  spawn_y           DOUBLE NULL,
  spawn_heading     DOUBLE NOT NULL DEFAULT 0,
  PRIMARY KEY (project_id, robot_id),
  UNIQUE KEY uq_map_robots_seq (project_id, seq),
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
  map_name           VARCHAR(95) NOT NULL,
  source_project_id  BIGINT UNSIGNED NOT NULL,
  draft_revision     BIGINT UNSIGNED NOT NULL,
  state              VARCHAR(16) NOT NULL DEFAULT 'published',
  building_sha256    CHAR(64) NOT NULL,
  nav_graph_sha256   CHAR(64) NOT NULL,
  world_sha256       CHAR(64) NOT NULL,
  manifest           JSON NOT NULL,
  published_by       VARCHAR(64) NOT NULL,
  published_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
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
