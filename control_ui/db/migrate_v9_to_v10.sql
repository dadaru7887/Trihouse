-- v9 -> v10
--
-- 로봇마다 값이 어디서 오는지 적는다.
--
-- 지금까지 실행 방식은 앱 전체에 하나뿐이었다(로봇 화면의 드롭다운). 실물 두
-- 대를 돌리면서 한 대만 Gazebo 로 시험하는 구성은 담을 수 없었다.
--
-- 무엇을 고르느냐에 따라 실행에 들어가는 자리가 갈린다.
--
--   mock    앱 안에서만 돈다. fleet adapter 에도 Gazebo 에도 가지 않는다.
--   gazebo  Gazebo 가 물리를 돌리고 토픽으로 주고받는다. 셋 다 들어간다.
--   real    실물이 이미 있다. fleet adapter 에는 가지만 Gazebo 에는 안 간다.
--
-- 기존 행은 앱 Mock 으로 보고 있었으므로 기본값이 그대로 맞다.

ALTER TABLE `map_project_robots`
  ADD COLUMN `data_source` VARCHAR(16) NOT NULL DEFAULT 'mock' AFTER `kind`;

INSERT INTO `schema_version` (`id`, `version`, `applied_at`)
VALUES (1, 10, NOW(6))
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`), `applied_at` = NOW(6);
