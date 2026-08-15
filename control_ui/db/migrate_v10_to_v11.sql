-- v10 -> v11
-- robot_id, Gazebo 모델명, ROS namespace, RMF 로봇 이름을 하나의 system ID로
-- 통일한다. 기존 gz_name은 실제 ROS/Gazebo에서 쓰던 안전한 이름이므로 이를
-- 새 robot_id로 채택하고 display_name은 사람에게 보여 줄 이름으로 남긴다.
--
-- 실행:
--   mysql -u root -p --default-character-set=utf8mb4 robosapiens \
--     < db/migrate_v10_to_v11.sql

START TRANSACTION;

-- 같은 프로젝트 안의 gz_name 중복을 먼저 검증한다. 중복이면 UNIQUE 추가에서
-- 중단되어 아래 데이터 변경은 실행되지 않는다.
ALTER TABLE `map_project_robots`
  ADD UNIQUE KEY `uq_map_robots_gz_name_v11` (`project_id`, `gz_name`);

CREATE TEMPORARY TABLE `robot_id_migration_v11` (
  `project_id` BIGINT      NOT NULL,
  `old_id`     VARCHAR(64) NOT NULL,
  `new_id`     VARCHAR(64) NOT NULL,
  `temp_id`    VARCHAR(64) NOT NULL,
  PRIMARY KEY (`project_id`, `old_id`),
  UNIQUE KEY (`project_id`, `new_id`),
  UNIQUE KEY (`project_id`, `temp_id`)
);

INSERT INTO `robot_id_migration_v11` (`project_id`, `old_id`, `new_id`, `temp_id`)
SELECT `project_id`, `robot_id`, `gz_name`,
       CONCAT('__v11_', MD5(CONCAT(`project_id`, ':', `robot_id`)))
FROM `map_project_robots`
WHERE BINARY `robot_id` <> BINARY `gz_name`;

-- 현재 작업의 등록 ID 참조도 함께 이동한다. __auto__처럼 등록과 무관한 값은
-- JOIN되지 않으므로 그대로 유지된다.
UPDATE `rmf_ui_tasks` AS t
JOIN `robot_id_migration_v11` AS m
  ON m.project_id = t.map_project_id
 AND JSON_UNQUOTE(JSON_EXTRACT(t.payload, '$.robotId')) = m.old_id
SET t.payload = JSON_SET(t.payload, '$.robotId', m.new_id),
    t.updated_at = NOW(6)
WHERE BINARY m.old_id <> BINARY m.new_id;

-- 먼저 충돌하지 않는 임시 ID로 옮긴 뒤 최종 ID를 넣는다. 새 ID가 다른 행의
-- 옛 ID와 우연히 같아도 PK 충돌 없이 이름 교환을 끝낼 수 있다.
UPDATE `map_project_robots` AS r
JOIN `robot_id_migration_v11` AS m
  ON m.project_id = r.project_id AND m.old_id = r.robot_id
SET r.robot_id = m.temp_id;

UPDATE `map_project_robots` AS r
JOIN `robot_id_migration_v11` AS m
  ON m.project_id = r.project_id AND m.temp_id = r.robot_id
SET r.robot_id = m.new_id,
    r.gz_name = m.new_id;

-- 과거 자동 생성 표시명만 PK-01/OMX-01 형태로 정리한다. 사용자가 직접 정한
-- 표시 이름은 보존한다. system ID는 소문자여도 표시 이름의 업무 접두사는
-- 대문자로 유지한다.
UPDATE `map_project_robots`
SET `display_name` = CASE
  WHEN `robot_id` REGEXP '^pinky_[0-9]+$'
    THEN CONCAT('PK-', SUBSTRING_INDEX(`robot_id`, '_', -1))
  WHEN `robot_id` REGEXP '^omx_[0-9]+$'
    THEN CONCAT('OMX-', SUBSTRING_INDEX(`robot_id`, '_', -1))
  ELSE `display_name`
END
WHERE (`robot_id` REGEXP '^(pinky|omx)_[0-9]+$')
  AND (`display_name` REGEXP '^(PK|OMX|pinky|omx)[_-][0-9]+$'
       OR `display_name` REGEXP '^(핑키|매니퓰레이터) [0-9]+호$');

ALTER TABLE `map_project_robots`
  DROP INDEX `uq_map_robots_gz_name_v11`;

DROP TEMPORARY TABLE `robot_id_migration_v11`;

INSERT INTO `schema_version` (`id`, `version`, `applied_at`)
VALUES (1, 11, NOW(6))
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`), `applied_at` = NOW(6);

COMMIT;
