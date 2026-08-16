-- Prevent two robots in one map project from sharing a Gazebo entity/ROS namespace.
-- Resolve any duplicate rows manually before applying this migration; silently
-- renaming a runtime identity would break launch files and topic ownership.
USE `trihouse_fms`;

SET @has_index := (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'map_project_robots'
    AND index_name = 'uq_map_robots_gz_name'
);
SET @ddl := IF(
  @has_index = 0,
  'ALTER TABLE map_project_robots ADD UNIQUE KEY uq_map_robots_gz_name (project_id, gz_name)',
  'SELECT 1'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
