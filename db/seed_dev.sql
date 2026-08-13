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

-- Physical warehouse parents are operational groupings, not RMF waypoints.
-- Their map and pose fields stay NULL until the Control System UI publishes them.
INSERT INTO locations
  (location_code, name, location_type, zone_code, temperature_zone, state)
VALUES
  ('WH-AMB-01', '상온창고', 'rack', 'ambient', 'ambient', 'available'),
  ('WH-CHL-01', '냉장창고', 'rack', 'chilled', 'chilled', 'available'),
  ('WH-FRZ-01', '냉동창고', 'rack', 'frozen', 'frozen', 'available')
ON DUPLICATE KEY UPDATE
  name = VALUES(name),
  location_type = VALUES(location_type),
  zone_code = VALUES(zone_code),
  temperature_zone = VALUES(temperature_zone),
  state = VALUES(state);

-- Each final storage slot records only its physical level and position.
SET @wh_amb_id = (SELECT location_id FROM locations WHERE location_code = 'WH-AMB-01');
SET @wh_chl_id = (SELECT location_id FROM locations WHERE location_code = 'WH-CHL-01');
SET @wh_frz_id = (SELECT location_id FROM locations WHERE location_code = 'WH-FRZ-01');

INSERT INTO locations
  (parent_location_id, location_code, name, location_type, zone_code,
   temperature_zone, state, metadata)
VALUES
  (@wh_amb_id,
   'AMB-L1-S01', '상온창고 1층 구역 1', 'slot', 'ambient', 'ambient',
   'occupied', JSON_OBJECT('shelf_level', 1, 'slot_index', 1)),
  (@wh_amb_id,
   'AMB-L1-S02', '상온창고 1층 구역 2', 'slot', 'ambient', 'ambient',
   'available', JSON_OBJECT('shelf_level', 1, 'slot_index', 2)),
  (@wh_amb_id,
   'AMB-L2-S01', '상온창고 2층 구역 1', 'slot', 'ambient', 'ambient',
   'occupied', JSON_OBJECT('shelf_level', 2, 'slot_index', 1)),
  (@wh_amb_id,
   'AMB-L2-S02', '상온창고 2층 구역 2', 'slot', 'ambient', 'ambient',
   'occupied', JSON_OBJECT('shelf_level', 2, 'slot_index', 2)),
  (@wh_chl_id,
   'CHL-L1-S01', '냉장창고 1층 구역 1', 'slot', 'chilled', 'chilled',
   'occupied', JSON_OBJECT('shelf_level', 1, 'slot_index', 1)),
  (@wh_chl_id,
   'CHL-L1-S02', '냉장창고 1층 구역 2', 'slot', 'chilled', 'chilled',
   'occupied', JSON_OBJECT('shelf_level', 1, 'slot_index', 2)),
  (@wh_chl_id,
   'CHL-L2-S01', '냉장창고 2층 구역 1', 'slot', 'chilled', 'chilled',
   'occupied', JSON_OBJECT('shelf_level', 2, 'slot_index', 1)),
  (@wh_chl_id,
   'CHL-L2-S02', '냉장창고 2층 구역 2', 'slot', 'chilled', 'chilled',
   'occupied', JSON_OBJECT('shelf_level', 2, 'slot_index', 2)),
  (@wh_frz_id,
   'FRZ-L1-S01', '냉동창고 1층 구역 1', 'slot', 'frozen', 'frozen',
   'occupied', JSON_OBJECT('shelf_level', 1, 'slot_index', 1)),
  (@wh_frz_id,
   'FRZ-L1-S02', '냉동창고 1층 구역 2', 'slot', 'frozen', 'frozen',
   'occupied', JSON_OBJECT('shelf_level', 1, 'slot_index', 2)),
  (@wh_frz_id,
   'FRZ-L2-S01', '냉동창고 2층 구역 1', 'slot', 'frozen', 'frozen',
   'occupied', JSON_OBJECT('shelf_level', 2, 'slot_index', 1)),
  (@wh_frz_id,
   'FRZ-L2-S02', '냉동창고 2층 구역 2', 'slot', 'frozen', 'frozen',
   'occupied', JSON_OBJECT('shelf_level', 2, 'slot_index', 2))
ON DUPLICATE KEY UPDATE
  parent_location_id = VALUES(parent_location_id),
  name = VALUES(name),
  location_type = VALUES(location_type),
  zone_code = VALUES(zone_code),
  temperature_zone = VALUES(temperature_zone),
  state = VALUES(state),
  metadata = VALUES(metadata);

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
   expiry_date, unit_weight_kg, available_qty, reserved_qty, state, received_at)
VALUES
  ('SKU-ORANGE', 'LOT-AMB-ORANGE-001', 'Orange', 'ambient',
   (SELECT location_id FROM locations WHERE location_code = 'AMB-L2-S01'),
   '2026-08-28', 0.200, 1, 0, 'stored', CURRENT_TIMESTAMP(6)),
  ('SKU-STRAWBERRY', 'LOT-AMB-STRAWBERRY-001', 'Strawberry', 'ambient',
   (SELECT location_id FROM locations WHERE location_code = 'AMB-L2-S02'),
   '2026-08-27', 0.250, 1, 0, 'stored', CURRENT_TIMESTAMP(6)),
  ('SKU-MANDARIN', 'LOT-AMB-MANDARIN-001', 'Mandarin', 'ambient',
   (SELECT location_id FROM locations WHERE location_code = 'AMB-L1-S01'),
   '2026-09-02', 0.120, 2, 0, 'stored', CURRENT_TIMESTAMP(6)),
  ('SKU-COFFEE', 'LOT-CHL-COFFEE-001', 'Coffee', 'chilled',
   (SELECT location_id FROM locations WHERE location_code = 'CHL-L2-S01'),
   '2026-10-31', 0.250, 1, 0, 'stored', CURRENT_TIMESTAMP(6)),
  ('SKU-SANDWICH', 'LOT-CHL-SANDWICH-001', 'Sandwich', 'chilled',
   (SELECT location_id FROM locations WHERE location_code = 'CHL-L2-S02'),
   '2026-09-10', 0.180, 2, 0, 'stored', CURRENT_TIMESTAMP(6)),
  ('SKU-YOGURT', 'LOT-CHL-YOGURT-001', 'Yogurt', 'chilled',
   (SELECT location_id FROM locations WHERE location_code = 'CHL-L1-S01'),
   '2026-09-30', 0.100, 2, 0, 'stored', CURRENT_TIMESTAMP(6)),
  ('SKU-MILK', 'LOT-CHL-MILK-001', 'Milk', 'chilled',
   (SELECT location_id FROM locations WHERE location_code = 'CHL-L1-S02'),
   '2026-09-20', 0.200, 1, 0, 'stored', CURRENT_TIMESTAMP(6)),
  ('SKU-PORKBELLY', 'LOT-FRZ-PORKBELLY-001', 'Pork belly', 'frozen',
   (SELECT location_id FROM locations WHERE location_code = 'FRZ-L2-S01'),
   '2027-08-13', 0.500, 2, 0, 'stored', CURRENT_TIMESTAMP(6)),
  ('SKU-DUMPLING', 'LOT-FRZ-DUMPLING-001', 'Dumpling', 'frozen',
   (SELECT location_id FROM locations WHERE location_code = 'FRZ-L2-S02'),
   '2027-08-20', 0.400, 1, 0, 'stored', CURRENT_TIMESTAMP(6)),
  ('SKU-ICEBAR', 'LOT-FRZ-ICEBAR-001', 'Ice bar', 'frozen',
   (SELECT location_id FROM locations WHERE location_code = 'FRZ-L1-S01'),
   '2027-08-25', 0.080, 2, 0, 'stored', CURRENT_TIMESTAMP(6)),
  ('SKU-ICECONE', 'LOT-FRZ-ICECONE-001', 'Ice cone', 'frozen',
   (SELECT location_id FROM locations WHERE location_code = 'FRZ-L1-S02'),
   '2027-08-31', 0.150, 2, 0, 'stored', CURRENT_TIMESTAMP(6))
ON DUPLICATE KEY UPDATE
  product_code = VALUES(product_code),
  item_name = VALUES(item_name),
  temperature_zone = VALUES(temperature_zone),
  location_id = VALUES(location_id),
  expiry_date = VALUES(expiry_date),
  unit_weight_kg = VALUES(unit_weight_kg),
  available_qty = VALUES(available_qty),
  reserved_qty = VALUES(reserved_qty),
  state = VALUES(state);

INSERT INTO jobs
  (job_code, operation_type, priority, state, requested_by,
   external_reference, source_location_id, destination_location_id, due_at,
   assigned_mobile_id, context, created_at)
VALUES
  ('JOB-DEV-001', 'outbound', 'normal', 'queued', 'W-OP-01',
   '00000000-0000-0000-0000-000000000001',
   (SELECT location_id FROM locations WHERE location_code = 'AMB-L2-S01'),
   (SELECT location_id FROM locations WHERE location_code = 'OUT-DOCK-01'),
   '2026-08-03 10:00:00.000000', 'PK_01',
   JSON_OBJECT('source', 'dev_seed'), '2026-08-03 09:05:00.000000')
ON DUPLICATE KEY UPDATE
  priority = VALUES(priority),
  state = VALUES(state),
  source_location_id = VALUES(source_location_id),
  destination_location_id = VALUES(destination_location_id),
  due_at = VALUES(due_at),
  assigned_mobile_id = VALUES(assigned_mobile_id),
  context = VALUES(context);

UPDATE job_items item
JOIN jobs job ON job.job_id = item.job_id
JOIN inventory_lots lot ON lot.lot_code = 'LOT-AMB-ORANGE-001'
SET item.product_code = 'SKU-ORANGE',
    item.requested_qty = 1,
    item.completed_qty = 0,
    item.lot_id = lot.lot_id,
    item.verification_state = 'pending',
    item.metadata = JSON_OBJECT('source', 'dev_seed')
WHERE job.job_code = 'JOB-DEV-001';

INSERT INTO job_items
  (job_id, product_code, requested_qty, completed_qty, lot_id,
   verification_state, metadata)
SELECT
  j.job_id, 'SKU-ORANGE', 1, 0, l.lot_id, 'pending',
  JSON_OBJECT('source', 'dev_seed')
FROM jobs j
JOIN inventory_lots l ON l.lot_code = 'LOT-AMB-ORANGE-001'
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
