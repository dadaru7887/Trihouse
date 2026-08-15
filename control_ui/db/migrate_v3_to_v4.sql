-- robosapiens 스키마 v3 → v4
--
-- RMF Control UI 의 작업(rmf_ui_tasks)과 그 이력(rmf_ui_task_history)을 맵
-- 프로젝트에 귀속시킨다.
--
-- 왜 필요한가: 작업 payload 는 그 맵의 Waypoint 좌표와 이름을 그대로 들고
-- 있다. 프로젝트 구분이 없으면 `창고 1층`에서 만든 홈1(12.5, -3.25)로 가는
-- 작업이 `창고 2층`을 열어도 그대로 뜨고, 그 좌표는 거기서 아무 데도 가리키지
-- 않는다. 맵 프로젝트가 하나도 없는데 대시보드에 작업이 남아 있는 것도 같은
-- 원인이다.
--
-- 주의: **기존 작업 행은 전부 지운다.** v3 에는 프로젝트 개념이 없었으므로
-- 남아 있는 작업이 어느 맵의 것인지 알아낼 방법이 없다. 임의의 프로젝트에
-- 붙이면 좌표가 어긋난 작업이 조용히 살아남는다. 이력도 같은 이유로 지운다.
--
-- 적용:
--   mysql -u root -p --default-character-set=utf8mb4 < db/migrate_v3_to_v4.sql
--
-- 이 파일은 v3 데이터베이스에만 쓴다. 새로 만드는 경우는 db/schema.sql 만으로
-- 충분하다.

SET NAMES utf8mb4;
USE `robosapiens`;

START TRANSACTION;

-- 어느 맵의 작업인지 알 수 없는 행을 버린다.
DELETE FROM `rmf_ui_task_history`;
DELETE FROM `rmf_ui_tasks`;

-- 작업: 프로젝트 귀속 + 복합 기본키(맵이 다르면 같은 작업 번호를 쓸 수 있다).
ALTER TABLE `rmf_ui_tasks`
  ADD COLUMN `map_project_id` BIGINT NOT NULL FIRST,
  DROP PRIMARY KEY,
  ADD PRIMARY KEY (`map_project_id`, `id`),
  DROP INDEX `idx_rmf_ui_tasks_status`,
  DROP INDEX `idx_rmf_ui_tasks_updated`,
  ADD KEY `idx_rmf_ui_tasks_status` (`map_project_id`, `status`),
  ADD KEY `idx_rmf_ui_tasks_updated` (`map_project_id`, `updated_at`),
  ADD CONSTRAINT `fk_rmf_ui_tasks_project` FOREIGN KEY (`map_project_id`)
    REFERENCES `map_projects` (`id`) ON DELETE CASCADE;

-- 이력: 프로젝트 귀속. task_id 에는 계속 외래 키를 걸지 않는다 — 작업을 지운
-- 뒤에도 그 프로젝트 안에서는 기록이 남아야 한다.
ALTER TABLE `rmf_ui_task_history`
  ADD COLUMN `map_project_id` BIGINT NOT NULL AFTER `id`,
  DROP INDEX `idx_rmf_ui_task_history_task`,
  DROP INDEX `idx_rmf_ui_task_history_at`,
  ADD KEY `idx_rmf_ui_task_history_task`
    (`map_project_id`, `task_id`, `recorded_at`),
  ADD KEY `idx_rmf_ui_task_history_at` (`map_project_id`, `recorded_at`),
  ADD CONSTRAINT `fk_rmf_ui_task_history_project` FOREIGN KEY (`map_project_id`)
    REFERENCES `map_projects` (`id`) ON DELETE CASCADE;

INSERT INTO `schema_version` (`id`, `version`, `applied_at`)
VALUES (1, 4, NOW(6))
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`), `applied_at` = NOW(6);

COMMIT;

SELECT `version` AS `schema_version` FROM `schema_version` WHERE `id` = 1;
SHOW CREATE TABLE `rmf_ui_tasks`;
