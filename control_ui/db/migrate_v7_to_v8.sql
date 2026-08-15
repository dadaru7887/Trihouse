-- v7 -> v8
--
-- 로봇에 종류를 붙인다.
--
-- 지금까지 등록은 이동 로봇만 가정했다. 자리를 충전 Waypoint 에서만 고를 수
-- 있었고, 등록한 것은 모두 fleet adapter 의 robots 로 나갔다. OpenMANIPULATOR
-- 처럼 설비 자리에 고정되는 로봇은 넣을 곳이 없었다.
--
-- 설치 로봇을 플릿에 넣으면 fleet adapter 가 배차 대상으로 보고 갈 수 없는
-- 곳으로 보내려 한다. Open-RMF 에서 그런 것은 플릿이 아니라 workcell 이다.
--
-- 기존 행은 모두 이동 로봇이었으므로 기본값이 그대로 맞다.

ALTER TABLE `map_project_robots`
  ADD COLUMN `kind` VARCHAR(16) NOT NULL DEFAULT 'mobile' AFTER `model`;

INSERT INTO `schema_version` (`id`, `version`, `applied_at`)
VALUES (1, 8, NOW(6))
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`), `applied_at` = NOW(6);
