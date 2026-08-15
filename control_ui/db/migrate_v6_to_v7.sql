-- robosapiens 스키마 v6 → v7
--
-- 설정 파일에 설명과 실행 권한 표시를 더한다.
--
-- 왜 필요한가: 파일 이름만으로는 building.yaml 과 fleet.yaml 이 각각 무엇을
-- 하는지, run_*.sh 를 언제 쓰는지 알 수 없다. 프로젝트를 열어 설정을 보는
-- 사람에게 파일과 함께 설명이 보여야 한다. .sh 는 내보낼 때 실행 권한이
-- 필요하므로 따로 표시한다.
--
-- 적용:
--   mysql -u root -p --default-character-set=utf8mb4 < db/migrate_v6_to_v7.sql

SET NAMES utf8mb4;
USE `robosapiens`;

START TRANSACTION;

ALTER TABLE `map_project_files`
  ADD COLUMN `description` VARCHAR(512) NOT NULL DEFAULT '' AFTER `kind`,
  ADD COLUMN `executable`  TINYINT(1)   NOT NULL DEFAULT 0  AFTER `description`;

INSERT INTO `schema_version` (`id`, `version`, `applied_at`)
VALUES (1, 7, NOW(6))
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`), `applied_at` = NOW(6);

COMMIT;

SELECT `version` AS `schema_version` FROM `schema_version` WHERE `id` = 1;
