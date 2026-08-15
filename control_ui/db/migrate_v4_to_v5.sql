-- robosapiens 스키마 v4 → v5
--
-- 맵 프로젝트에 도면 원본과 Open-RMF building.yaml 을 함께 보관한다.
--
-- 왜 필요한가: 지금까지 도면은 payload(JSON) 안에 base64 로만 들어 있었고
-- YAML 은 아예 저장되지 않았다. 그래서 관제나 배포 도구가 도면 하나를 꺼내려고
-- 수백 KB짜리 JSON 을 파싱해야 했고, YAML 은 Flutter 앱을 열어 다시 만들어야만
-- 얻을 수 있었다. 프로젝트 하나만 보면 배포에 필요한 것이 다 있어야 한다.
--
-- 기존 데이터는 지우지 않는다. 새 열은 전부 NULL 로 시작하며, 각 프로젝트를
-- 앱에서 한 번 다시 저장하면 그때 채워진다. payload 는 그대로 있으므로 그때까지
-- 도면을 잃지 않는다.
--
-- 적용:
--   mysql -u root -p --default-character-set=utf8mb4 < db/migrate_v4_to_v5.sql

SET NAMES utf8mb4;
USE `robosapiens`;

START TRANSACTION;

ALTER TABLE `map_projects`
  ADD COLUMN `drawing_extension`  VARCHAR(16)  NULL AFTER `drawing_name`,
  ADD COLUMN `drawing_bytes`      LONGBLOB     NULL AFTER `drawing_extension`,
  ADD COLUMN `drawing_width`      INT          NULL AFTER `drawing_bytes`,
  ADD COLUMN `drawing_height`     INT          NULL AFTER `drawing_width`,
  ADD COLUMN `building_yaml`      LONGTEXT     NULL AFTER `drawing_height`,
  ADD COLUMN `building_yaml_name` VARCHAR(255) NULL AFTER `building_yaml`;

-- 도면은 payload 에 이미 base64 로 있으므로 여기서 옮겨 담을 수 있다.
-- YAML 은 도면·벽·Lane 을 실제로 계산해야 나오는 값이라 SQL 로는 만들 수 없다.
-- 앱에서 프로젝트를 다시 저장할 때 채워진다.
UPDATE `map_projects`
SET
  `drawing_extension` = JSON_UNQUOTE(JSON_EXTRACT(`payload`, '$.drawing.extension')),
  `drawing_bytes` = FROM_BASE64(
    JSON_UNQUOTE(JSON_EXTRACT(`payload`, '$.drawing.bytes'))
  ),
  `drawing_width` = JSON_EXTRACT(`payload`, '$.drawing.pixelWidth'),
  `drawing_height` = JSON_EXTRACT(`payload`, '$.drawing.pixelHeight')
WHERE JSON_EXTRACT(`payload`, '$.drawing.bytes') IS NOT NULL
  AND JSON_TYPE(JSON_EXTRACT(`payload`, '$.drawing.bytes')) <> 'NULL';

INSERT INTO `schema_version` (`id`, `version`, `applied_at`)
VALUES (1, 5, NOW(6))
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`), `applied_at` = NOW(6);

COMMIT;

SELECT `version` AS `schema_version` FROM `schema_version` WHERE `id` = 1;
SELECT
  `map_name`,
  `drawing_name`,
  LENGTH(`drawing_bytes`) AS `도면_바이트`,
  IF(`building_yaml` IS NULL, '다시 저장 필요', 'ok') AS `yaml`
FROM `map_projects`;
