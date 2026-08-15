-- robosapiens 스키마 v5 → v6
--
-- RMF 설정을 맵 프로젝트에 귀속시킨다.
--
-- 왜 필요한가: 지금까지 플릿 설정은 robo_pinky/src/robo_pinky_sim/config/fleet.yaml
-- 하나였다. 맵이 다르면 Waypoint 이름도 충전소 위치도 다르므로, 프로젝트를 바꾸는
-- 순간 spawn 좌표와 charger 이름이 어긋난다. 배포·실행에 필요한 설정 파일이
-- 디스크 여기저기 흩어져 있어 어느 것이 이 맵의 것인지도 알 수 없었다.
--
-- 기존 데이터는 지우지 않는다. 새 표는 비어 있고, 각 프로젝트를 앱에서 한 번 다시
-- 저장하면 그때 채워진다.
--
-- 적용:
--   mysql -u root -p --default-character-set=utf8mb4 < db/migrate_v5_to_v6.sql

SET NAMES utf8mb4;
USE `robosapiens`;

START TRANSACTION;

CREATE TABLE IF NOT EXISTS `map_project_fleets` (
  `project_id` BIGINT      NOT NULL,
  `fleet_name` VARCHAR(64) NOT NULL,
  `settings`   JSON        NOT NULL,
  `updated_at` DATETIME(6) NOT NULL,
  PRIMARY KEY (`project_id`),
  CONSTRAINT `fk_map_fleets_project` FOREIGN KEY (`project_id`)
    REFERENCES `map_projects` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `map_project_robots` (
  `project_id`       BIGINT       NOT NULL,
  `robot_id`         VARCHAR(64)  NOT NULL,
  `seq`              INT          NOT NULL,
  `display_name`     VARCHAR(128) NOT NULL,
  `model`            VARCHAR(64)  NOT NULL,
  `gz_name`          VARCHAR(64)  NOT NULL,
  `zones`            VARCHAR(64)  NOT NULL,
  `charger_waypoint` VARCHAR(128) NULL,
  `spawn_x`          DOUBLE       NULL,
  `spawn_y`          DOUBLE       NULL,
  `spawn_heading`    DOUBLE       NOT NULL DEFAULT 0,
  PRIMARY KEY (`project_id`, `robot_id`),
  KEY `idx_map_robots_seq` (`project_id`, `seq`),
  CONSTRAINT `fk_map_robots_project` FOREIGN KEY (`project_id`)
    REFERENCES `map_projects` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `map_project_files` (
  `project_id`   BIGINT       NOT NULL,
  `file_name`    VARCHAR(255) NOT NULL,
  `kind`         VARCHAR(32)  NOT NULL,
  `content`      LONGTEXT     NOT NULL,
  `generated_at` DATETIME(6)  NOT NULL,
  PRIMARY KEY (`project_id`, `file_name`),
  KEY `idx_map_files_kind` (`project_id`, `kind`),
  CONSTRAINT `fk_map_files_project` FOREIGN KEY (`project_id`)
    REFERENCES `map_projects` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 이미 보관해 둔 building.yaml 은 설정 파일 목록에도 함께 보이게 옮겨 담는다.
INSERT INTO `map_project_files`
  (`project_id`, `file_name`, `kind`, `content`, `generated_at`)
SELECT
  `id`,
  COALESCE(`building_yaml_name`, CONCAT(`map_name`, '.building.yaml')),
  'building',
  `building_yaml`,
  `updated_at`
FROM `map_projects`
WHERE `building_yaml` IS NOT NULL
ON DUPLICATE KEY UPDATE `content` = VALUES(`content`);

INSERT INTO `schema_version` (`id`, `version`, `applied_at`)
VALUES (1, 6, NOW(6))
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`), `applied_at` = NOW(6);

COMMIT;

SELECT `version` AS `schema_version` FROM `schema_version` WHERE `id` = 1;
SELECT `map_name`, COUNT(f.`file_name`) AS `설정파일`
FROM `map_projects` p LEFT JOIN `map_project_files` f ON f.`project_id` = p.`id`
GROUP BY p.`id`;
