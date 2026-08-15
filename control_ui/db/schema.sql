-- RoboSapiens 물류 플랫폼 — MySQL 스키마 (원장 / system of record)
--
-- 이 시스템의 원장은 이 데이터베이스이며, 관제센터·소비자 앱이 들고 있는
-- 메모리 상태는 캐시다. 재기동하면 여기 남은 내용으로 복원된다.
--
-- SQLite(robo_control.db) 스키마 v2와 1:1 대응한다. 타입 매핑:
--   TEXT(ISO8601)  -> DATETIME(6)   (마이크로초까지 보존, 로컬 시각 그대로)
--   INTEGER(0/1)   -> TINYINT(1)
--   TEXT(enum.name)-> VARCHAR(32)   (Dart enum 이름 문자열. ENUM 타입을 쓰지
--                                    않는 이유는 enum 값이 늘 때 DDL 변경을
--                                    강제하지 않기 위함)
--
-- 적용:  mysql -u <user> -p < db/schema.sql

CREATE DATABASE IF NOT EXISTS `robosapiens`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `robosapiens`;

-- SQLite의 PRAGMA user_version 대응. 마이그레이션 단계를 기록한다.
CREATE TABLE IF NOT EXISTS `schema_version` (
  `id`         TINYINT      NOT NULL DEFAULT 1,
  `version`    INT          NOT NULL,
  `applied_at` DATETIME(6)  NOT NULL,
  PRIMARY KEY (`id`),
  CONSTRAINT `chk_schema_version_single_row` CHECK (`id` = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ---------------------------------------------------------------------------
-- 마스터 데이터
-- ---------------------------------------------------------------------------

-- 로봇 등록 정보. 텔레메트리와 분리된 마스터 데이터.
-- 등록 해제는 삭제가 아니라 active = 0 + retired_at 기록(이력 보존).
CREATE TABLE IF NOT EXISTS `robots` (
  `id`              VARCHAR(64)  NOT NULL,
  `name`            VARCHAR(128) NOT NULL,
  `model`           VARCHAR(64)  NOT NULL,
  -- TempZone.name 을 콤마로 이어 붙인 값. 예: 'ambient,chilled'
  `zone_rating`     VARCHAR(64)  NOT NULL,
  `home_charger_id` VARCHAR(64)  NOT NULL,
  `reserve`         TINYINT(1)   NOT NULL DEFAULT 0,
  `active`          TINYINT(1)   NOT NULL DEFAULT 1,
  `registered_at`   DATETIME(6)  NOT NULL,
  `retired_at`      DATETIME(6)  NULL,
  PRIMARY KEY (`id`),
  KEY `idx_robots_active` (`active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 로봇당 최신 스냅샷 1행. 고빈도 위치 갱신은 여기에만 반영한다(UPSERT).
CREATE TABLE IF NOT EXISTS `robot_telemetry` (
  `robot_id`     VARCHAR(64)  NOT NULL,
  `at`           DATETIME(6)  NOT NULL,
  `state`        VARCHAR(32)  NOT NULL,
  `battery`      DOUBLE       NOT NULL,
  `x`            DOUBLE       NOT NULL,
  `y`            DOUBLE       NOT NULL,
  `heading`      DOUBLE       NOT NULL,
  `task_id`      VARCHAR(64)  NULL,
  `progress`     DOUBLE       NOT NULL DEFAULT 0,
  `activity`     VARCHAR(255) NULL,
  `odometer`     DOUBLE       NOT NULL DEFAULT 0,
  `power_saving` TINYINT(1)   NOT NULL DEFAULT 0,
  `completed`    INT          NOT NULL DEFAULT 0,
  `failed`       INT          NOT NULL DEFAULT 0,
  PRIMARY KEY (`robot_id`),
  CONSTRAINT `fk_telemetry_robot` FOREIGN KEY (`robot_id`)
    REFERENCES `robots` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 현장 작업자. 등록 해제도 로봇과 같은 방식(active = 0).
CREATE TABLE IF NOT EXISTS `workers` (
  `id`            VARCHAR(64)  NOT NULL,
  `name`          VARCHAR(128) NOT NULL,
  `role`          VARCHAR(64)  NOT NULL,
  `zone`          VARCHAR(32)  NOT NULL,
  `active`        TINYINT(1)   NOT NULL DEFAULT 1,
  `registered_at` DATETIME(6)  NOT NULL,
  `retired_at`    DATETIME(6)  NULL,
  PRIMARY KEY (`id`),
  KEY `idx_workers_active` (`active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ---------------------------------------------------------------------------
-- 재고
-- ---------------------------------------------------------------------------

-- 로트 = 재고의 최소 관리 단위. FEFO 판단 기준이 expiry.
-- reserved 는 배차 예약분(실물 이동 없음). 가용 = qty - reserved.
CREATE TABLE IF NOT EXISTS `lots` (
  `id`          VARCHAR(64)  NOT NULL,
  `sku`         VARCHAR(64)  NOT NULL,
  `name`        VARCHAR(128) NOT NULL,
  `zone`        VARCHAR(32)  NOT NULL,
  `location_id` VARCHAR(64)  NOT NULL,
  `qty`         INT          NOT NULL,
  `reserved`    INT          NOT NULL DEFAULT 0,
  `expiry`      DATETIME(6)  NOT NULL,
  `received_at` DATETIME(6)  NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_lots_sku_expiry` (`sku`, `expiry`),
  KEY `idx_lots_location` (`location_id`),
  CONSTRAINT `chk_lots_qty`          CHECK (`qty` >= 0),
  CONSTRAINT `chk_lots_reserved`     CHECK (`reserved` >= 0),
  CONSTRAINT `chk_lots_reserved_max` CHECK (`reserved` <= `qty`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 재고 원장 — 수량이 바뀐 모든 사건을 append-only로 남긴다.
-- lot_id 에 FK를 걸지 않는 이유: 로트가 소진·삭제된 뒤에도 이력은 남아야 한다.
CREATE TABLE IF NOT EXISTS `stock_moves` (
  `id`        BIGINT       NOT NULL AUTO_INCREMENT,
  `at`        DATETIME(6)  NOT NULL,
  `lot_id`    VARCHAR(64)  NOT NULL,
  `sku`       VARCHAR(64)  NOT NULL,
  `delta`     INT          NOT NULL,
  `qty_after` INT          NOT NULL,
  -- StockMoveReason.name: inbound|outbound|disposal|adjustment|cycleCount|initial
  `reason`    VARCHAR(32)  NOT NULL,
  `task_id`   VARCHAR(64)  NULL,
  `order_id`  VARCHAR(64)  NULL,
  `operator`  VARCHAR(128) NULL,
  `note`      VARCHAR(512) NULL,
  PRIMARY KEY (`id`),
  KEY `idx_moves_at` (`at`),
  KEY `idx_moves_lot` (`lot_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ---------------------------------------------------------------------------
-- 주문 — 소비자 앱과 관제센터의 접점
-- ---------------------------------------------------------------------------

-- expanded = 0 은 관제가 아직 태스크로 전개하지 않은 주문(소비자 앱 접수분).
CREATE TABLE IF NOT EXISTS `orders` (
  `id`           VARCHAR(64)  NOT NULL,
  `customer`     VARCHAR(128) NOT NULL,
  `urgency`      VARCHAR(32)  NOT NULL,
  `created_at`   DATETIME(6)  NOT NULL,
  `due_at`       DATETIME(6)  NOT NULL,
  `line_count`   INT          NOT NULL,
  `state`        VARCHAR(32)  NOT NULL,
  `done_lines`   INT          NOT NULL DEFAULT 0,
  `failed_lines` INT          NOT NULL DEFAULT 0,
  `closed_at`    DATETIME(6)  NULL,
  `source`       VARCHAR(32)  NOT NULL DEFAULT 'auto',
  `expanded`     TINYINT(1)   NOT NULL DEFAULT 1,
  PRIMARY KEY (`id`),
  KEY `idx_orders_created` (`created_at`),
  KEY `idx_orders_expanded` (`expanded`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 주문이 담고 있는 품목·수량. lot_id 가 비면 FEFO 규칙으로 관제가 고른다.
CREATE TABLE IF NOT EXISTS `order_lines` (
  `order_id` VARCHAR(64)  NOT NULL,
  `seq`      INT          NOT NULL,
  `sku`      VARCHAR(64)  NOT NULL,
  `name`     VARCHAR(128) NOT NULL,
  `qty`      INT          NOT NULL,
  `lot_id`   VARCHAR(64)  NULL,
  PRIMARY KEY (`order_id`, `seq`),
  KEY `idx_order_lines_order` (`order_id`),
  CONSTRAINT `fk_order_lines_order` FOREIGN KEY (`order_id`)
    REFERENCES `orders` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ---------------------------------------------------------------------------
-- 태스크
-- ---------------------------------------------------------------------------

-- order_id 에 FK를 걸지 않는 이유: 완결 태스크는 purgeTerminalBefore 로
-- 주문과 독립적인 주기로 정리된다(SQLite 원본 스키마와 동일).
CREATE TABLE IF NOT EXISTS `tasks` (
  `id`           VARCHAR(64)  NOT NULL,
  `type`         VARCHAR(32)  NOT NULL,
  `title`        VARCHAR(255) NOT NULL,
  `urgency`      VARCHAR(32)  NOT NULL,
  `zone`         VARCHAR(32)  NOT NULL,
  `order_id`     VARCHAR(64)  NULL,
  `sku`          VARCHAR(64)  NULL,
  `lot_id`       VARCHAR(64)  NULL,
  `expiry`       DATETIME(6)  NULL,
  `qty`          INT          NOT NULL DEFAULT 1,
  `requested_by` VARCHAR(64)  NULL,
  `origin_label` VARCHAR(128) NOT NULL,
  `dest_label`   VARCHAR(128) NOT NULL,
  `state`        VARCHAR(32)  NOT NULL,
  `robot_id`     VARCHAR(64)  NULL,
  `step_index`   INT          NOT NULL DEFAULT 0,
  `retries`      INT          NOT NULL DEFAULT 0,
  `fail_reason`  VARCHAR(512) NULL,
  `score`        DOUBLE       NOT NULL DEFAULT 0,
  `created_at`   DATETIME(6)  NOT NULL,
  `assigned_at`  DATETIME(6)  NULL,
  `started_at`   DATETIME(6)  NULL,
  `ended_at`     DATETIME(6)  NULL,
  PRIMARY KEY (`id`),
  KEY `idx_tasks_state` (`state`),
  KEY `idx_tasks_created` (`created_at`),
  KEY `idx_tasks_order` (`order_id`),
  -- purgeTerminalBefore(state IN (...) AND ended_at < ?) 전용
  KEY `idx_tasks_state_ended` (`state`, `ended_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `task_steps` (
  `task_id`     VARCHAR(64)  NOT NULL,
  `seq`         INT          NOT NULL,
  `kind`        VARCHAR(32)  NOT NULL,
  `label`       VARCHAR(128) NOT NULL,
  `target_x`    DOUBLE       NOT NULL,
  `target_y`    DOUBLE       NOT NULL,
  `duration`    DOUBLE       NOT NULL,
  `resource_id` VARCHAR(64)  NULL,
  PRIMARY KEY (`task_id`, `seq`),
  CONSTRAINT `fk_task_steps_task` FOREIGN KEY (`task_id`)
    REFERENCES `tasks` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- RMF Control UI 의 작업 정의는 맵 프로젝트에 속한다. 정의는 아래
-- '맵 프로젝트' 절에 map_projects 다음으로 있다(외래 키 순서 때문).


-- ---------------------------------------------------------------------------
-- 맵 프로젝트 — 지도 이름이 곧 프로젝트 구분자
--
-- 한 대의 관제가 여러 창고(프로젝트)를 다룬다. 프로젝트가 다르면 Waypoint,
-- Lane, 벽, 축척이 전부 별개이므로 지도 이름으로 갈라 담는다.
--
-- `payload` 가 복원의 원본이다. 도면 이미지 바이트와 벽·바닥 마스크까지 통째로
-- 들고 있어 이것만 있으면 편집 화면을 그대로 되살릴 수 있다.
-- 아래 map_project_waypoints / map_project_lanes 는 그 payload 에서 뽑아낸
-- 조회용 사본이다. 저장할 때마다 지우고 다시 채우므로 payload 와 어긋나지
-- 않는다. 관제나 다른 도구가 도면 수백 KB를 읽지 않고도 "이 맵의 주차 자리가
-- 어디인가"를 물어볼 수 있게 하려고 둔다.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `map_projects` (
  `id`             BIGINT       NOT NULL AUTO_INCREMENT,
  -- 프로젝트 구분자. 같은 이름의 프로젝트는 하나만 존재한다. 앱은 저장 전에
  -- 이 이름의 존재 여부를 확인해 덮어쓸지 다른 이름으로 갈지 사용자에게 묻는다.
  `map_name`       VARCHAR(128) NOT NULL,
  -- 프로젝트 JSON 의 스키마 번호(.rmfproject 의 `version` 과 같은 값).
  `format_version` INT          NOT NULL,
  `payload`        JSON         NOT NULL,

  -- 도면 원본. payload 안에도 base64로 들어 있지만, 관제나 배포 도구가 수백 KB
  -- 짜리 JSON을 파싱하지 않고 이미지만 바로 꺼내 쓸 수 있게 따로 둔다.
  `drawing_name`      VARCHAR(255) NULL,
  `drawing_extension` VARCHAR(16)  NULL,
  `drawing_bytes`     LONGBLOB     NULL,
  `drawing_width`     INT          NULL,
  `drawing_height`    INT          NULL,

  -- 저장 시점에 만들어 둔 Open-RMF building.yaml. payload 에서 다시 뽑아낼 수
  -- 있는 값이지만, 배포 쪽이 Flutter 앱을 거치지 않고 바로 집어갈 수 있어야
  -- 한다. 저장할 때마다 다시 만들어 넣으므로 payload 와 어긋나지 않는다.
  -- 맵이 아직 YAML 로 만들 수 있는 상태가 아니면 NULL 이다.
  `building_yaml`      LONGTEXT     NULL,
  `building_yaml_name` VARCHAR(255) NULL,

  `waypoint_count` INT          NOT NULL DEFAULT 0,
  `lane_count`     INT          NOT NULL DEFAULT 0,
  `created_at`     DATETIME(6)  NOT NULL,
  `updated_at`     DATETIME(6)  NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_map_projects_name` (`map_name`),
  KEY `idx_map_projects_updated` (`updated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 프로젝트별 Waypoint 조회용 사본. seq 는 프로젝트 안에서의 입력 순서다.
CREATE TABLE IF NOT EXISTS `map_project_waypoints` (
  `project_id` BIGINT       NOT NULL,
  `seq`        INT          NOT NULL,
  `name`       VARCHAR(128) NOT NULL,
  -- 대기(is_holding_point) | 주차(is_parking_spot) | 홈 | 충전 | 픽업 |
  -- 드랍오프 | 설비. RMF Control UI 의 카테고리 문자열 그대로다.
  `category`   VARCHAR(32)  NOT NULL,
  `x`          DOUBLE       NOT NULL,
  `y`          DOUBLE       NOT NULL,
  PRIMARY KEY (`project_id`, `seq`),
  KEY `idx_map_waypoints_category` (`project_id`, `category`),
  KEY `idx_map_waypoints_name` (`project_id`, `name`),
  CONSTRAINT `fk_map_waypoints_project` FOREIGN KEY (`project_id`)
    REFERENCES `map_projects` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- RMF Control UI에서 작성한 재사용 가능한 작업 정의. payload에는 지도 Waypoint,
-- 단계와 배정 정보를 JSON으로 보존한다.
--
-- 프로젝트에 속한다. payload 안의 단계가 그 맵의 Waypoint 좌표와 이름을 그대로
-- 들고 있기 때문이다 — `창고 1층`의 홈1(12.5, -3.25)로 가는 작업을 `창고 2층`
-- 에서 꺼내면 그 좌표는 아무 데도 가리키지 않는다. 프로젝트를 지우면 그 맵의
-- 작업도 함께 사라진다.
--
-- 작업 번호(id)는 앱이 프로젝트 안에서 매기므로 서로 다른 맵이 같은 번호를 쓸
-- 수 있다. 그래서 기본 키가 (map_project_id, id) 복합키다.
CREATE TABLE IF NOT EXISTS `rmf_ui_tasks` (
  `map_project_id` BIGINT       NOT NULL,
  `id`             VARCHAR(64)  NOT NULL,
  `name`           VARCHAR(255) NOT NULL,
  `status`         VARCHAR(32)  NOT NULL,
  `payload`        JSON         NOT NULL,
  `created_at`     DATETIME(6)  NOT NULL,
  `updated_at`     DATETIME(6)  NOT NULL,
  PRIMARY KEY (`map_project_id`, `id`),
  KEY `idx_rmf_ui_tasks_status` (`map_project_id`, `status`),
  KEY `idx_rmf_ui_tasks_updated` (`map_project_id`, `updated_at`),
  CONSTRAINT `fk_rmf_ui_tasks_project` FOREIGN KEY (`map_project_id`)
    REFERENCES `map_projects` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 작업 생성·수정·삭제·상태 변경 이력. 작업을 지운 뒤에도 그 프로젝트 안에서는
-- 기록이 남는다(task_id 에 외래 키를 걸지 않는 이유). 프로젝트 자체를 지우면
-- 함께 사라진다.
CREATE TABLE IF NOT EXISTS `rmf_ui_task_history` (
  `id`             BIGINT      NOT NULL AUTO_INCREMENT,
  `map_project_id` BIGINT      NOT NULL,
  `task_id`        VARCHAR(64) NOT NULL,
  `event_type`     VARCHAR(32) NOT NULL,
  `payload`        JSON        NOT NULL,
  `recorded_at`    DATETIME(6) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_rmf_ui_task_history_task`
    (`map_project_id`, `task_id`, `recorded_at`),
  KEY `idx_rmf_ui_task_history_at` (`map_project_id`, `recorded_at`),
  CONSTRAINT `fk_rmf_ui_task_history_project` FOREIGN KEY (`map_project_id`)
    REFERENCES `map_projects` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 프로젝트별 RMF 플릿 설정 (프로젝트당 1행).
--
-- 맵이 다르면 Waypoint 이름도 충전소 위치도 다르므로 플릿 설정은 프로젝트를
-- 따라가야 한다. 전역 fleet.yaml 하나를 돌려 쓰면 맵을 바꾸는 순간 spawn 좌표와
-- charger 이름이 어긋난다.
--
-- `settings` 에는 Open-RMF fleet adapter 의 rmf_fleet 블록에 그대로 대응하는
-- 값(속도·가속도 한계, 프로필 반경, 배터리·기구 계수, 재충전 임계값 등)을
-- JSON 으로 담는다. 항목이 늘어도 DDL 을 바꾸지 않기 위해서다.
CREATE TABLE IF NOT EXISTS `map_project_fleets` (
  `project_id` BIGINT      NOT NULL,
  `fleet_name` VARCHAR(64) NOT NULL,
  `settings`   JSON        NOT NULL,
  `updated_at` DATETIME(6) NOT NULL,
  PRIMARY KEY (`project_id`),
  CONSTRAINT `fk_map_fleets_project` FOREIGN KEY (`project_id`)
    REFERENCES `map_projects` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 프로젝트별 로봇. Gazebo spawn 과 fleet adapter 의 robots 항목을 함께 만든다.
CREATE TABLE IF NOT EXISTS `map_project_robots` (
  `project_id`       BIGINT       NOT NULL,
  `robot_id`         VARCHAR(64)  NOT NULL,
  `seq`              INT          NOT NULL,
  `display_name`     VARCHAR(128) NOT NULL,
  `model`            VARCHAR(64)  NOT NULL,
  -- 'mobile' 이면 돌아다니는 로봇, 'workcell' 이면 설비 자리에 고정된 설치 로봇.
  -- 설치 로봇은 fleet adapter 의 robots 에 들어가지 않는다. 배차 대상이 아니다.
  `kind`             VARCHAR(16)  NOT NULL DEFAULT 'mobile',
  -- 값이 어디서 오는가. 'mock' 앱 안 · 'gazebo' 시뮬레이션 · 'real' 실물.
  -- mock 은 fleet adapter 에도 Gazebo bringup 에도 들어가지 않는다.
  -- real 은 fleet adapter 에는 가지만 Gazebo 에는 안 간다.
  `data_source`      VARCHAR(16)  NOT NULL DEFAULT 'mock',
  -- system ID의 호환 사본. robot_id와 항상 같으며 Gazebo 모델명 및
  -- 토픽 네임스페이스로 쓴다(/<gz_name>/odom).
  `gz_name`          VARCHAR(64)  NOT NULL,
  -- TempZone.name 을 콤마로 이어 붙인 값. 예: 'ambient,chilled'
  `zones`            VARCHAR(64)  NOT NULL,
  -- 이 로봇이 서 있는 Waypoint 이름.
  -- 이동 로봇이면 충전 Waypoint 로 fleet adapter 의 robots[].charger 가 되고,
  -- 설치 로봇이면 설비 Waypoint 로 그 자리에 고정 설치된다.
  `charger_waypoint` VARCHAR(128) NULL,
  `spawn_x`          DOUBLE       NULL,
  `spawn_y`          DOUBLE       NULL,
  `spawn_heading`    DOUBLE       NOT NULL DEFAULT 0,
  PRIMARY KEY (`project_id`, `robot_id`),
  KEY `idx_map_robots_seq` (`project_id`, `seq`),
  CONSTRAINT `fk_map_robots_project` FOREIGN KEY (`project_id`)
    REFERENCES `map_projects` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 프로젝트에서 만들어진 설정 파일 전부.
--
-- building.yaml, nav graph, fleet adapter 설정, Gazebo spawn 목록, launch 를
-- 한자리에 모아 둔다. 배포와 실행에 필요한 것을 프로젝트 하나만 열어 전부 볼 수
-- 있어야 한다 — 파일이 디스크 여기저기 흩어져 있으면 어느 것이 이 맵의 것인지
-- 알 수 없다.
--
-- 프로젝트를 저장할 때마다 다시 만들어 넣으므로 payload 와 어긋나지 않는다.
CREATE TABLE IF NOT EXISTS `map_project_files` (
  `project_id`   BIGINT       NOT NULL,
  `file_name`    VARCHAR(255) NOT NULL,
  -- building | fleet_adapter | fleet_sim | launch | bringup | script
  `kind`         VARCHAR(32)  NOT NULL,
  -- 이 파일이 무엇이고 어디에 쓰이는지. 화면에서 파일과 함께 보여 준다 —
  -- 이름만으로는 building.yaml 과 fleet.yaml 이 각각 무엇을 하는지 알 수 없다.
  `description`  VARCHAR(512) NOT NULL DEFAULT '',
  -- 실행 권한이 필요한 파일(.sh)인지. 내보낼 때 chmod +x 한다.
  `executable`   TINYINT(1)   NOT NULL DEFAULT 0,
  `content`      LONGTEXT     NOT NULL,
  `generated_at` DATETIME(6)  NOT NULL,
  PRIMARY KEY (`project_id`, `file_name`),
  KEY `idx_map_files_kind` (`project_id`, `kind`),
  CONSTRAINT `fk_map_files_project` FOREIGN KEY (`project_id`)
    REFERENCES `map_projects` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 프로젝트별 Lane 조회용 사본.
CREATE TABLE IF NOT EXISTS `map_project_lanes` (
  `project_id`  BIGINT      NOT NULL,
  `seq`         INT         NOT NULL,
  `start_x`     DOUBLE      NOT NULL,
  `start_y`     DOUBLE      NOT NULL,
  `end_x`       DOUBLE      NOT NULL,
  `end_y`       DOUBLE      NOT NULL,
  -- 양방향 | 정방향 | 역방향
  `direction`   VARCHAR(16) NOT NULL,
  `speed_limit` DOUBLE      NULL,
  `orientation` VARCHAR(16) NULL,
  `mutex_group` VARCHAR(64) NULL,
  PRIMARY KEY (`project_id`, `seq`),
  CONSTRAINT `fk_map_lanes_project` FOREIGN KEY (`project_id`)
    REFERENCES `map_projects` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ---------------------------------------------------------------------------
-- 운행 이력 · 안전
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `events` (
  `id`       BIGINT       NOT NULL AUTO_INCREMENT,
  `at`       DATETIME(6)  NOT NULL,
  `severity` VARCHAR(32)  NOT NULL,
  `category` VARCHAR(64)  NOT NULL,
  `source`   VARCHAR(64)  NOT NULL,
  `message`  VARCHAR(512) NOT NULL,
  `task_id`  VARCHAR(64)  NULL,
  `order_id` VARCHAR(64)  NULL,
  PRIMARY KEY (`id`),
  KEY `idx_events_at` (`at`),
  KEY `idx_events_category` (`category`),
  KEY `idx_events_severity` (`severity`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `incidents` (
  `id`          VARCHAR(64)  NOT NULL,
  `type`        VARCHAR(32)  NOT NULL,
  `at`          DATETIME(6)  NOT NULL,
  `description` VARCHAR(512) NOT NULL,
  `zone`        VARCHAR(32)  NULL,
  `pos_x`       DOUBLE       NULL,
  `pos_y`       DOUBLE       NULL,
  `radius`      DOUBLE       NOT NULL DEFAULT 0,
  `active`      TINYINT(1)   NOT NULL DEFAULT 1,
  `cleared_at`  DATETIME(6)  NULL,
  -- 조치 이력. 저장소 계층이 구분자로 이어 붙인 문자열.
  `actions`     TEXT         NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_incidents_at` (`at`),
  KEY `idx_incidents_active` (`active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ---------------------------------------------------------------------------
-- ID 시퀀스 — 재기동해도 번호가 이어지도록 저장한다.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `counters` (
  `name`  VARCHAR(64) NOT NULL,
  `value` BIGINT      NOT NULL,
  PRIMARY KEY (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS `map_project_changes` (
  `id`         BIGINT       NOT NULL AUTO_INCREMENT,
  `project_id` BIGINT       NOT NULL,
  `at`         DATETIME(6)  NOT NULL,
  -- 'robot' 로봇 등록 · 'fleet' 플릿 설정 · 'file' 생성 파일 · 'project' 프로젝트
  `category`   VARCHAR(32)  NOT NULL,
  -- 'added' 추가 · 'changed' 변경 · 'removed' 삭제
  `action`     VARCHAR(16)  NOT NULL,
  -- 무엇이 바뀌었나. 로봇 ID, 파일 이름 등.
  `target`     VARCHAR(255) NOT NULL,
  `summary`    VARCHAR(512) NOT NULL DEFAULT '',
  PRIMARY KEY (`id`),
  KEY `idx_map_changes_at` (`project_id`, `at`),
  KEY `idx_map_changes_day` (`at`),
  CONSTRAINT `fk_map_changes_project`
    FOREIGN KEY (`project_id`) REFERENCES `map_projects` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- v3: 맵 프로젝트 테이블(map_projects / map_project_waypoints /
--     map_project_lanes) 추가. 여러 창고 맵을 지도 이름으로 구분해 담는다.
-- v4: rmf_ui_tasks / rmf_ui_task_history 를 맵 프로젝트에 귀속.
--     이미 v3 로 쓰던 데이터베이스는 db/migrate_v3_to_v4.sql 을 적용한다.
-- v5: map_projects 에 도면 원본(drawing_bytes)과 building.yaml 을 함께 보관.
--     v4 데이터베이스는 db/migrate_v4_to_v5.sql 을 적용한다.
-- v6: RMF 설정을 프로젝트에 귀속. map_project_fleets / map_project_robots /
--     map_project_files 추가. v5 는 db/migrate_v5_to_v6.sql 을 적용한다.
-- v7: 설정 파일에 설명과 실행 권한 표시 추가.
--     v6 은 db/migrate_v6_to_v7.sql 을 적용한다.
-- v8: 로봇에 종류(이동/설치) 추가. 설치 로봇은 설비 Waypoint 에 고정되고
--     fleet adapter 에 들어가지 않는다. v7 은 db/migrate_v7_to_v8.sql 을 적용한다.
-- v9: 설정 변경 기록(map_project_changes) 추가. 운영 기록과 같은 시간축에서
--     본다. v8 은 db/migrate_v8_to_v9.sql 을 적용한다.
-- v10: 로봇마다 값의 출처(Mock/Gazebo/실물)를 적는다. 실행에 들어가는 자리가
--      여기서 갈린다. v9 는 db/migrate_v9_to_v10.sql 을 적용한다.
-- v11: robot_id를 Gazebo 모델명/ROS namespace와 같은 system ID로 통일한다.
--      v10 은 db/migrate_v10_to_v11.sql 을 적용한다.
INSERT INTO `schema_version` (`id`, `version`, `applied_at`)
VALUES (1, 11, NOW(6))
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`), `applied_at` = NOW(6);
