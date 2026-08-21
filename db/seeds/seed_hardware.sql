-- Trihouse FMS physical registry seed.
USE `trihouse_fms`;

INSERT INTO locations
  (location_code, name, location_type, zone_code, temperature_zone, state)
VALUES
  ('A-SLOT-01', 'Ambient Rack Slot 01', 'slot', 'ambient', 'ambient',
   'available'),
  ('OUT-DOCK-01', 'Loading Dock 01', 'loading_dock', 'outbound', NULL,
   'available'),
  ('CHG-01', 'Pinky Charging Station 01', 'charger', 'ambient', NULL,
   'available'),
  ('CHG-02', 'Pinky Charging Station 02', 'charger', 'ambient', NULL,
   'available'),
  ('IN-WAIT-01', 'Inbound Waiting Point 01', 'staging', 'ambient', NULL,
   'available'),
  ('NARROW-WAIT-01', 'Narrow-Aisle Waiting Point 01', 'staging', 'ambient', NULL,
   'available'),
  ('OMX-WS-01', 'OMX Handover Workcell 01', 'workstation', 'ambient', 'ambient',
   'available'),
  ('OMX-WS-02', 'OMX Handover Workcell 02', 'workstation', 'ambient', 'ambient',
   'available')
ON DUPLICATE KEY UPDATE
  name = VALUES(name),
  state = VALUES(state);

-- EN: Warehouse parents are operational groups, not RMF waypoints; map poses remain NULL until publication.
-- KO: 창고 상위 위치는 RMF waypoint가 아닌 운영 그룹이며 지도 발행 전까지 pose를 NULL로 둔다.
INSERT INTO locations
  (location_code, name, location_type, zone_code, temperature_zone, state)
VALUES
  ('WH-AMB-01', 'Ambient Storage', 'rack', 'ambient', 'ambient', 'available'),
  ('WH-CHL-01', 'Chilled Storage', 'rack', 'chilled', 'chilled', 'available'),
  ('WH-FRZ-01', 'Frozen Storage', 'rack', 'frozen', 'frozen', 'available'),
  ('PACKING-01', 'Packing Station', 'workstation', 'packing', 'ambient', 'available')
ON DUPLICATE KEY UPDATE
  name = VALUES(name),
  location_type = VALUES(location_type),
  zone_code = VALUES(zone_code),
  temperature_zone = VALUES(temperature_zone),
  state = VALUES(state);

-- EN: Final storage slots record only their physical level and index.
-- KO: 최종 보관 슬롯에는 실제 단수와 칸 번호만 기록한다.
SET @wh_amb_id = (SELECT location_id FROM locations WHERE location_code = 'WH-AMB-01');
SET @wh_chl_id = (SELECT location_id FROM locations WHERE location_code = 'WH-CHL-01');
SET @wh_frz_id = (SELECT location_id FROM locations WHERE location_code = 'WH-FRZ-01');

INSERT INTO locations
  (parent_location_id, location_code, name, location_type, zone_code,
   temperature_zone, state, metadata)
VALUES
  (@wh_amb_id,
   'AMB-L1-S01', 'Ambient Storage L1 Slot 01', 'slot', 'ambient', 'ambient',
   'available', JSON_OBJECT('shelf_level', 1, 'slot_index', 1)),
  (@wh_amb_id,
   'AMB-L1-S02', 'Ambient Storage L1 Slot 02', 'slot', 'ambient', 'ambient',
   'available', JSON_OBJECT('shelf_level', 1, 'slot_index', 2)),
  (@wh_amb_id,
   'AMB-L2-S01', 'Ambient Storage L2 Slot 01', 'slot', 'ambient', 'ambient',
   'available', JSON_OBJECT('shelf_level', 2, 'slot_index', 1)),
  (@wh_amb_id,
   'AMB-L2-S02', 'Ambient Storage L2 Slot 02', 'slot', 'ambient', 'ambient',
   'available', JSON_OBJECT('shelf_level', 2, 'slot_index', 2)),
  (@wh_chl_id,
   'CHL-L1-S01', 'Chilled Storage L1 Slot 01', 'slot', 'chilled', 'chilled',
   'available', JSON_OBJECT('shelf_level', 1, 'slot_index', 1)),
  (@wh_chl_id,
   'CHL-L1-S02', 'Chilled Storage L1 Slot 02', 'slot', 'chilled', 'chilled',
   'available', JSON_OBJECT('shelf_level', 1, 'slot_index', 2)),
  (@wh_chl_id,
   'CHL-L2-S01', 'Chilled Storage L2 Slot 01', 'slot', 'chilled', 'chilled',
   'available', JSON_OBJECT('shelf_level', 2, 'slot_index', 1)),
  (@wh_chl_id,
   'CHL-L2-S02', 'Chilled Storage L2 Slot 02', 'slot', 'chilled', 'chilled',
   'available', JSON_OBJECT('shelf_level', 2, 'slot_index', 2)),
  (@wh_frz_id,
   'FRZ-L1-S01', 'Frozen Storage L1 Slot 01', 'slot', 'frozen', 'frozen',
   'available', JSON_OBJECT('shelf_level', 1, 'slot_index', 1)),
  (@wh_frz_id,
   'FRZ-L1-S02', 'Frozen Storage L1 Slot 02', 'slot', 'frozen', 'frozen',
   'available', JSON_OBJECT('shelf_level', 1, 'slot_index', 2)),
  (@wh_frz_id,
   'FRZ-L2-S01', 'Frozen Storage L2 Slot 01', 'slot', 'frozen', 'frozen',
   'available', JSON_OBJECT('shelf_level', 2, 'slot_index', 1)),
  (@wh_frz_id,
   'FRZ-L2-S02', 'Frozen Storage L2 Slot 02', 'slot', 'frozen', 'frozen',
   'available', JSON_OBJECT('shelf_level', 2, 'slot_index', 2))
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
  ('W-OP-01', 'OP-01', 'Physical Test Operator', 'operator',
   JSON_ARRAY('ambient', 'outbound'), 1, '2026-08-03 09:00:00.000000'),
  ('W-SAFE-01', 'SAFE-01', 'Physical Test Safety Manager', 'safety_manager',
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
  ('PK_01', 'mobile', 'PK_01', 'Pinky-Pro', 'project1_pinky',
   (SELECT location_id FROM locations WHERE location_code = 'CHG-01'),
   (SELECT location_id FROM locations WHERE location_code = 'CHG-01'),
   'automatic', 1, JSON_OBJECT('navigation', true, 'rmf', true,
     'rmf_robot_name', 'PK_01'),
   '2026-08-03 09:00:00.000000'),
  ('PK_02', 'mobile', 'PK_02', 'Pinky-Pro', 'project1_pinky',
   (SELECT location_id FROM locations WHERE location_code = 'CHG-02'),
   (SELECT location_id FROM locations WHERE location_code = 'CHG-02'),
   'automatic', 1, JSON_OBJECT('navigation', true, 'rmf', true,
     'rmf_robot_name', 'PK_02'),
   '2026-08-03 09:00:00.000000'),
  ('OMX_01', 'arm', 'OMX_01', 'OMX-AI', NULL,
   (SELECT location_id FROM locations WHERE location_code = 'OMX-WS-01'),
   (SELECT location_id FROM locations WHERE location_code = 'OMX-WS-01'),
   'automatic', 1, JSON_OBJECT('pick', true, 'place', true),
   '2026-08-03 09:00:00.000000'),
  ('OMX_02', 'arm', 'OMX_02', 'OMX-AI', NULL,
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
   NULL, NULL, NULL, 92.00, 0.0000,
   JSON_OBJECT('source', 'physical_seed', 'pose_source', 'deployment_charger_import')),
  ('PK_02', '2026-08-03 09:00:00.000000', 'idle', 'ok',
   NULL, NULL, NULL, 88.00, 0.0000,
   JSON_OBJECT('source', 'physical_seed', 'pose_source', 'deployment_charger_import')),
  ('OMX_01', '2026-08-03 09:00:00.000000', 'idle', 'ok',
   NULL, NULL, NULL, NULL, 0.0000, JSON_OBJECT('source', 'physical_seed')),
  ('OMX_02', '2026-08-03 09:00:00.000000', 'idle', 'ok',
   NULL, NULL, NULL, NULL, 0.0000, JSON_OBJECT('source', 'physical_seed'))
ON DUPLICATE KEY UPDATE
  observed_at = VALUES(observed_at),
  state = VALUES(state),
  health = VALUES(health),
  battery_pct = VALUES(battery_pct),
  details = VALUES(details);
