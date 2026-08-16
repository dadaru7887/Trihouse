-- Make one map_name safe to use unchanged in DB, Open-RMF/Gazebo configs,
-- launch names, and filesystem artifacts. Inspect and rename legacy rows that
-- violate this rule before applying the CHECK; this migration never guesses.

USE `trihouse_fms`;

SELECT map_name AS invalid_map_name
FROM map_projects
WHERE NOT REGEXP_LIKE(map_name, '^[A-Za-z0-9_][A-Za-z0-9_-]{0,94}$', 'c');

ALTER TABLE map_projects
  ADD CONSTRAINT chk_map_projects_name CHECK
    (REGEXP_LIKE(map_name, '^[A-Za-z0-9_][A-Za-z0-9_-]{0,94}$', 'c'));
