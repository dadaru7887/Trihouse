-- Trihouse FMS deterministic development seed.
USE `trihouse_fms`;

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
  map_name = VALUES(map_name),
  rmf_waypoint_name = VALUES(rmf_waypoint_name),
  state = VALUES(state);

INSERT INTO workers
  (worker_id, worker_code, name, role, allowed_zones, active, registered_at)
VALUES
  ('W-OP-01', 'OP-01', '개발 운영자', 'operator',
   JSON_ARRAY('ambient', 'outbound'), 1, '2026-08-03 09:00:00.000000'),
  ('W-SAFE-01', 'SAFE-01', '개발 안전 관리자', 'safety_manager',
   JSON_ARRAY('ambient', 'chilled', 'frozen', 'outbound'), 1,
   '2026-08-03 09:00:00.000000')
ON DUPLICATE KEY UPDATE
  name = VALUES(name),
  role = VALUES(role),
  active = VALUES(active);

INSERT INTO devices
  (device_id, device_type, name, model, fleet_name, home_location_id,
   current_location_id, control_mode, active, capabilities, registered_at)
VALUES
  ('PK_01', 'mobile', 'Pinky-Pro #1', 'Pinky-Pro', 'project1_pinky',
   (SELECT location_id FROM locations WHERE location_code = 'CHG-01'),
   (SELECT location_id FROM locations WHERE location_code = 'CHG-01'),
   'automatic', 1, JSON_OBJECT('navigation', true, 'rmf', true,
     'rmf_robot_name', 'PK_01'),
   '2026-08-03 09:00:00.000000'),
  ('PK_02', 'mobile', 'Pinky-Pro #2', 'Pinky-Pro', 'project1_pinky',
   (SELECT location_id FROM locations WHERE location_code = 'CHG-02'),
   (SELECT location_id FROM locations WHERE location_code = 'CHG-02'),
   'automatic', 1, JSON_OBJECT('navigation', true, 'rmf', true,
     'rmf_robot_name', 'PK_02'),
   '2026-08-03 09:00:00.000000'),
  ('OMX_01', 'arm', 'OMX-AI #1', 'OMX-AI', NULL,
   (SELECT location_id FROM locations WHERE location_code = 'OMX-WS-01'),
   (SELECT location_id FROM locations WHERE location_code = 'OMX-WS-01'),
   'automatic', 1, JSON_OBJECT('pick', true, 'place', true),
   '2026-08-03 09:00:00.000000'),
  ('OMX_02', 'arm', 'OMX-AI #2', 'OMX-AI', NULL,
   (SELECT location_id FROM locations WHERE location_code = 'OMX-WS-02'),
   (SELECT location_id FROM locations WHERE location_code = 'OMX-WS-02'),
   'automatic', 1, JSON_OBJECT('pick', true, 'place', true),
   '2026-08-03 09:00:00.000000')
ON DUPLICATE KEY UPDATE
  name = VALUES(name),
  fleet_name = VALUES(fleet_name),
  active = VALUES(active),
  capabilities = VALUES(capabilities);

INSERT INTO device_states
  (device_id, observed_at, state, health, pose_x, pose_y, pose_yaw,
   battery_pct, progress, details)
VALUES
  ('PK_01', '2026-08-03 09:00:00.000000', 'idle', 'ok',
   2.0, 2.0, 3.141593, 92.00, 0.0000, JSON_OBJECT('source', 'dev_seed')),
  ('PK_02', '2026-08-03 09:00:00.000000', 'idle', 'ok',
   2.5, 2.0, 3.141593, 88.00, 0.0000, JSON_OBJECT('source', 'dev_seed')),
  ('OMX_01', '2026-08-03 09:00:00.000000', 'idle', 'ok',
   NULL, NULL, NULL, NULL, 0.0000, JSON_OBJECT('source', 'dev_seed')),
  ('OMX_02', '2026-08-03 09:00:00.000000', 'idle', 'ok',
   NULL, NULL, NULL, NULL, 0.0000, JSON_OBJECT('source', 'dev_seed'))
ON DUPLICATE KEY UPDATE
  observed_at = VALUES(observed_at),
  state = VALUES(state),
  health = VALUES(health),
  battery_pct = VALUES(battery_pct),
  details = VALUES(details);

INSERT INTO inventory_lots
  (product_code, lot_code, item_name, temperature_zone, location_id,
   expiry_date, available_qty, reserved_qty, state, received_at)
VALUES
  ('SKU-AMBIENT-001', 'LOT-DEV-001', '개발용 상온 상품 A', 'ambient',
   (SELECT location_id FROM locations WHERE location_code = 'A-SLOT-01'),
   '2027-01-31', 100, 5, 'stored', '2026-08-03 09:00:00.000000'),
  ('SKU-AMBIENT-002', 'LOT-DEV-002', '개발용 상온 상품 B', 'ambient',
   (SELECT location_id FROM locations WHERE location_code = 'A-SLOT-01'),
   '2027-02-28', 60, 0, 'stored', '2026-08-03 09:00:00.000000')
ON DUPLICATE KEY UPDATE
  item_name = VALUES(item_name),
  location_id = VALUES(location_id),
  expiry_date = VALUES(expiry_date),
  state = VALUES(state);

INSERT INTO jobs
  (job_code, operation_type, priority, state, requested_by,
   external_reference, source_location_id, destination_location_id, due_at,
   assigned_mobile_id, context, created_at)
VALUES
  ('JOB-DEV-001', 'outbound', 'normal', 'queued', 'W-OP-01',
   '00000000-0000-0000-0000-000000000001',
   (SELECT location_id FROM locations WHERE location_code = 'A-SLOT-01'),
   (SELECT location_id FROM locations WHERE location_code = 'OUT-DOCK-01'),
   '2026-08-03 10:00:00.000000', 'PK_01',
   JSON_OBJECT('source', 'dev_seed'), '2026-08-03 09:05:00.000000')
ON DUPLICATE KEY UPDATE
  priority = VALUES(priority),
  state = VALUES(state),
  assigned_mobile_id = VALUES(assigned_mobile_id),
  context = VALUES(context);

INSERT INTO job_items
  (job_id, product_code, requested_qty, completed_qty, lot_id,
   verification_state, metadata)
SELECT
  j.job_id, 'SKU-AMBIENT-001', 5, 0, l.lot_id, 'pending',
  JSON_OBJECT('source', 'dev_seed')
FROM jobs j
JOIN inventory_lots l ON l.lot_code = 'LOT-DEV-001'
WHERE j.job_code = 'JOB-DEV-001'
  AND NOT EXISTS (
    SELECT 1 FROM job_items existing WHERE existing.job_id = j.job_id
  );

INSERT INTO job_steps
  (job_id, step_no, executor_type, assigned_device_id, action_type,
   target_location_id, state, input)
SELECT
  j.job_id, 1, 'mobile', 'PK_01', 'navigate',
  target.location_id, 'pending', JSON_OBJECT('source', 'dev_seed')
FROM jobs j
JOIN locations target ON target.location_code = 'A-SLOT-01'
WHERE j.job_code = 'JOB-DEV-001'
ON DUPLICATE KEY UPDATE
  assigned_device_id = VALUES(assigned_device_id),
  target_location_id = VALUES(target_location_id),
  state = VALUES(state),
  input = VALUES(input);
