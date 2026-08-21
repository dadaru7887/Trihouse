-- Normalize legacy device aliases without changing the database structure.
-- Run with a migration client that stops and rolls back when a statement fails.

USE `trihouse_fms`;

START TRANSACTION;

-- 기존 volume에서도 project1의 운영 location code와 RMF waypoint를 같은
-- registry로 맞춘다. 스키마나 location_id는 바꾸지 않고 code 기준 upsert한다.
INSERT INTO locations
  (location_code, name, location_type, zone_code, temperature_zone,
   map_name, rmf_waypoint_name, pose_x, pose_y, pose_yaw, state)
VALUES
  ('A-SLOT-01', '상온 랙 슬롯 1', 'slot', 'ambient', 'ambient',
   'project1', '픽업1', 4.0, 3.0, 0.0, 'available'),
  ('OUT-DOCK-01', '출고 도크 1', 'outbound_dock', 'outbound', NULL,
   'project1', '드랍오프1', 28.0, 6.0, 0.0, 'available'),
  ('CHG-01', 'Pinky 충전기 1', 'charger', 'ambient', NULL,
   'project1', '충전1', 2.0, 2.0, 3.141593, 'available'),
  ('CHG-02', 'Pinky 충전기 2', 'charger', 'ambient', NULL,
   'project1', '충전2', 2.5, 2.0, 3.141593, 'available'),
  ('IN-WAIT-01', '입고 대기점 1', 'staging', 'ambient', NULL,
   'project1', '대기1', NULL, NULL, NULL, 'available'),
  ('NARROW-WAIT-01', '협로 대기점 1', 'staging', 'ambient', NULL,
   'project1', '대기3', NULL, NULL, NULL, 'available'),
  ('OMX-WS-01', 'OMX 인계 작업장 1', 'workstation', 'ambient', 'ambient',
   'project1', '설비1', 18.0, 6.0, 0.0, 'available'),
  ('OMX-WS-02', 'OMX 인계 작업장 2', 'workstation', 'ambient', 'ambient',
   'project1', '설비2', NULL, NULL, NULL, 'available')
ON DUPLICATE KEY UPDATE
  name = VALUES(name),
  location_type = VALUES(location_type),
  zone_code = VALUES(zone_code),
  temperature_zone = VALUES(temperature_zone),
  map_name = VALUES(map_name),
  rmf_waypoint_name = VALUES(rmf_waypoint_name),
  state = VALUES(state);

-- Ensure every destination row exists before moving foreign-key references.
INSERT INTO devices
  (device_id, device_type, name, model, fleet_name, home_location_id,
   current_location_id, control_mode, active, capabilities, registered_at,
   retired_at)
SELECT
  'PK_01', device_type, name, model, 'project1_pinky', home_location_id,
  current_location_id, control_mode, active, capabilities, registered_at,
  retired_at
FROM devices
WHERE device_id IN ('PK_01', 'PINKY-01', 'PK-01')
ORDER BY FIELD(device_id, 'PK_01', 'PINKY-01', 'PK-01')
LIMIT 1
ON DUPLICATE KEY UPDATE device_id = VALUES(device_id);

INSERT INTO devices
  (device_id, device_type, name, model, fleet_name, home_location_id,
   current_location_id, control_mode, active, capabilities, registered_at,
   retired_at)
SELECT
  'PK_02', device_type, name, model, 'project1_pinky', home_location_id,
  current_location_id, control_mode, active, capabilities, registered_at,
  retired_at
FROM devices
WHERE device_id IN ('PK_02', 'PINKY-02', 'PK-02')
ORDER BY FIELD(device_id, 'PK_02', 'PINKY-02', 'PK-02')
LIMIT 1
ON DUPLICATE KEY UPDATE device_id = VALUES(device_id);

INSERT INTO devices
  (device_id, device_type, name, model, fleet_name, home_location_id,
   current_location_id, control_mode, active, capabilities, registered_at,
   retired_at)
SELECT
  'OMX_01', device_type, name, model, NULL, home_location_id,
  current_location_id, control_mode, active, capabilities, registered_at,
  retired_at
FROM devices
WHERE device_id IN ('OMX_01', 'OMX-01')
ORDER BY FIELD(device_id, 'OMX_01', 'OMX-01')
LIMIT 1
ON DUPLICATE KEY UPDATE device_id = VALUES(device_id);

INSERT INTO devices
  (device_id, device_type, name, model, fleet_name, home_location_id,
   current_location_id, control_mode, active, capabilities, registered_at,
   retired_at)
SELECT
  'OMX_02', device_type, name, model, NULL, home_location_id,
  current_location_id, control_mode, active, capabilities, registered_at,
  retired_at
FROM devices
WHERE device_id IN ('OMX_02', 'OMX-02')
ORDER BY FIELD(device_id, 'OMX_02', 'OMX-02')
LIMIT 1
ON DUPLICATE KEY UPDATE device_id = VALUES(device_id);

-- device_states has one row per device. Keep the newest state when aliases overlap.
INSERT INTO device_states
  (device_id, observed_at, state, health, current_job_step_id, pose_x, pose_y,
   pose_yaw, battery_pct, progress, details)
SELECT
  'PK_01', observed_at, state, health, current_job_step_id, pose_x, pose_y,
  pose_yaw, battery_pct, progress, details
FROM device_states
WHERE device_id IN ('PK_01', 'PINKY-01', 'PK-01')
ORDER BY observed_at DESC, FIELD(device_id, 'PK_01', 'PINKY-01', 'PK-01')
LIMIT 1
ON DUPLICATE KEY UPDATE
  observed_at = VALUES(observed_at),
  state = VALUES(state),
  health = VALUES(health),
  current_job_step_id = VALUES(current_job_step_id),
  pose_x = VALUES(pose_x),
  pose_y = VALUES(pose_y),
  pose_yaw = VALUES(pose_yaw),
  battery_pct = VALUES(battery_pct),
  progress = VALUES(progress),
  details = VALUES(details);

INSERT INTO device_states
  (device_id, observed_at, state, health, current_job_step_id, pose_x, pose_y,
   pose_yaw, battery_pct, progress, details)
SELECT
  'PK_02', observed_at, state, health, current_job_step_id, pose_x, pose_y,
  pose_yaw, battery_pct, progress, details
FROM device_states
WHERE device_id IN ('PK_02', 'PINKY-02', 'PK-02')
ORDER BY observed_at DESC, FIELD(device_id, 'PK_02', 'PINKY-02', 'PK-02')
LIMIT 1
ON DUPLICATE KEY UPDATE
  observed_at = VALUES(observed_at),
  state = VALUES(state),
  health = VALUES(health),
  current_job_step_id = VALUES(current_job_step_id),
  pose_x = VALUES(pose_x),
  pose_y = VALUES(pose_y),
  pose_yaw = VALUES(pose_yaw),
  battery_pct = VALUES(battery_pct),
  progress = VALUES(progress),
  details = VALUES(details);

INSERT INTO device_states
  (device_id, observed_at, state, health, current_job_step_id, pose_x, pose_y,
   pose_yaw, battery_pct, progress, details)
SELECT
  'OMX_01', observed_at, state, health, current_job_step_id, pose_x, pose_y,
  pose_yaw, battery_pct, progress, details
FROM device_states
WHERE device_id IN ('OMX_01', 'OMX-01')
ORDER BY observed_at DESC, FIELD(device_id, 'OMX_01', 'OMX-01')
LIMIT 1
ON DUPLICATE KEY UPDATE
  observed_at = VALUES(observed_at),
  state = VALUES(state),
  health = VALUES(health),
  current_job_step_id = VALUES(current_job_step_id),
  pose_x = VALUES(pose_x),
  pose_y = VALUES(pose_y),
  pose_yaw = VALUES(pose_yaw),
  battery_pct = VALUES(battery_pct),
  progress = VALUES(progress),
  details = VALUES(details);

INSERT INTO device_states
  (device_id, observed_at, state, health, current_job_step_id, pose_x, pose_y,
   pose_yaw, battery_pct, progress, details)
SELECT
  'OMX_02', observed_at, state, health, current_job_step_id, pose_x, pose_y,
  pose_yaw, battery_pct, progress, details
FROM device_states
WHERE device_id IN ('OMX_02', 'OMX-02')
ORDER BY observed_at DESC, FIELD(device_id, 'OMX_02', 'OMX-02')
LIMIT 1
ON DUPLICATE KEY UPDATE
  observed_at = VALUES(observed_at),
  state = VALUES(state),
  health = VALUES(health),
  current_job_step_id = VALUES(current_job_step_id),
  pose_x = VALUES(pose_x),
  pose_y = VALUES(pose_y),
  pose_yaw = VALUES(pose_yaw),
  battery_pct = VALUES(battery_pct),
  progress = VALUES(progress),
  details = VALUES(details);

-- Move every direct device foreign key while both old and new parents exist.
UPDATE jobs SET assigned_mobile_id = CASE
  WHEN assigned_mobile_id IN ('PINKY-01', 'PK-01') THEN 'PK_01'
  WHEN assigned_mobile_id IN ('PINKY-02', 'PK-02') THEN 'PK_02'
  WHEN assigned_mobile_id = 'OMX-01' THEN 'OMX_01'
  WHEN assigned_mobile_id = 'OMX-02' THEN 'OMX_02'
  ELSE assigned_mobile_id END
WHERE assigned_mobile_id IN
  ('PINKY-01', 'PINKY-02', 'PK-01', 'PK-02', 'OMX-01', 'OMX-02');

UPDATE job_steps SET assigned_device_id = CASE
  WHEN assigned_device_id IN ('PINKY-01', 'PK-01') THEN 'PK_01'
  WHEN assigned_device_id IN ('PINKY-02', 'PK-02') THEN 'PK_02'
  WHEN assigned_device_id = 'OMX-01' THEN 'OMX_01'
  WHEN assigned_device_id = 'OMX-02' THEN 'OMX_02'
  ELSE assigned_device_id END
WHERE assigned_device_id IN
  ('PINKY-01', 'PINKY-02', 'PK-01', 'PK-02', 'OMX-01', 'OMX-02');

UPDATE job_step_attempts SET actor_device_id = CASE
  WHEN actor_device_id IN ('PINKY-01', 'PK-01') THEN 'PK_01'
  WHEN actor_device_id IN ('PINKY-02', 'PK-02') THEN 'PK_02'
  WHEN actor_device_id = 'OMX-01' THEN 'OMX_01'
  WHEN actor_device_id = 'OMX-02' THEN 'OMX_02'
  ELSE actor_device_id END
WHERE actor_device_id IN
  ('PINKY-01', 'PINKY-02', 'PK-01', 'PK-02', 'OMX-01', 'OMX-02');

UPDATE reservations SET device_id = CASE
  WHEN device_id IN ('PINKY-01', 'PK-01') THEN 'PK_01'
  WHEN device_id IN ('PINKY-02', 'PK-02') THEN 'PK_02'
  WHEN device_id = 'OMX-01' THEN 'OMX_01'
  WHEN device_id = 'OMX-02' THEN 'OMX_02'
  ELSE device_id END
WHERE device_id IN
  ('PINKY-01', 'PINKY-02', 'PK-01', 'PK-02', 'OMX-01', 'OMX-02');

UPDATE integration_messages SET device_id = CASE
  WHEN device_id IN ('PINKY-01', 'PK-01') THEN 'PK_01'
  WHEN device_id IN ('PINKY-02', 'PK-02') THEN 'PK_02'
  WHEN device_id = 'OMX-01' THEN 'OMX_01'
  WHEN device_id = 'OMX-02' THEN 'OMX_02'
  ELSE device_id END
WHERE device_id IN
  ('PINKY-01', 'PINKY-02', 'PK-01', 'PK-02', 'OMX-01', 'OMX-02');

UPDATE operation_events SET device_id = CASE
  WHEN device_id IN ('PINKY-01', 'PK-01') THEN 'PK_01'
  WHEN device_id IN ('PINKY-02', 'PK-02') THEN 'PK_02'
  WHEN device_id = 'OMX-01' THEN 'OMX_01'
  WHEN device_id = 'OMX-02' THEN 'OMX_02'
  ELSE device_id END
WHERE device_id IN
  ('PINKY-01', 'PINKY-02', 'PK-01', 'PK-02', 'OMX-01', 'OMX-02');

UPDATE artifacts SET device_id = CASE
  WHEN device_id IN ('PINKY-01', 'PK-01') THEN 'PK_01'
  WHEN device_id IN ('PINKY-02', 'PK-02') THEN 'PK_02'
  WHEN device_id = 'OMX-01' THEN 'OMX_01'
  WHEN device_id = 'OMX-02' THEN 'OMX_02'
  ELSE device_id END
WHERE device_id IN
  ('PINKY-01', 'PINKY-02', 'PK-01', 'PK-02', 'OMX-01', 'OMX-02');

DELETE FROM device_states
WHERE device_id IN
  ('PINKY-01', 'PINKY-02', 'PK-01', 'PK-02', 'OMX-01', 'OMX-02');

DELETE FROM devices
WHERE device_id IN
  ('PINKY-01', 'PINKY-02', 'PK-01', 'PK-02', 'OMX-01', 'OMX-02');

UPDATE devices
SET fleet_name = 'project1_pinky'
WHERE fleet_name = 'pinky_fleet'
   OR device_id IN ('PK_01', 'PK_02');

UPDATE devices
SET capabilities = JSON_SET(
  COALESCE(capabilities, JSON_OBJECT()), '$.rmf_robot_name', device_id
)
WHERE device_id IN ('PK_01', 'PK_02');

UPDATE devices
SET fleet_name = NULL
WHERE device_id IN ('OMX_01', 'OMX_02');

COMMIT;
