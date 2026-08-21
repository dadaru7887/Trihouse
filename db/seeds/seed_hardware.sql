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

SET @wh_amb_id = (SELECT location_id FROM locations WHERE location_code = 'WH-AMB-01');
SET @wh_chl_id = (SELECT location_id FROM locations WHERE location_code = 'WH-CHL-01');
SET @wh_frz_id = (SELECT location_id FROM locations WHERE location_code = 'WH-FRZ-01');
SET @packing_id = (SELECT location_id FROM locations WHERE location_code = 'PACKING-01');

-- EN: These provisional poses mirror the new_map_2 JSONL and must be rechecked before physical motion.
-- KO: 아래 임시 pose는 new_map_2 JSONL과 일치하며, 실물 주행 전 남은 좌표를 재확인한다.
INSERT INTO locations
  (parent_location_id, location_code, name, location_type, zone_code,
   temperature_zone, map_name, rmf_waypoint_name, pose_x, pose_y, pose_yaw,
   state, metadata)
VALUES
  (@wh_amb_id,
   'WH-AMB-01-DOCK-01', 'Ambient Storage Loading Dock 01', 'loading_dock',
   'ambient', 'ambient', 'new_map_2', 'ambient_storage_loading_dock_01',
   1.234, 0.743, 2.255, 'available',
   JSON_OBJECT('coordinate_source', 'trihouse_test_01_physical_features.new_map_2.jsonl', 'provisional', true)),
  (@wh_chl_id,
   'WH-CHL-01-DOCK-01', 'Chilled Storage Loading Dock 01', 'loading_dock',
   'chilled', 'chilled', 'new_map_2', 'chilled_storage_loading_dock_01',
   1.26, 0.193, -2.258, 'available',
   JSON_OBJECT('coordinate_source', 'trihouse_test_01_physical_features.new_map_2.jsonl', 'provisional', true)),
  (@wh_frz_id,
   'WH-FRZ-01-DOCK-01', 'Frozen Storage Loading Dock 01', 'loading_dock',
   'frozen', 'frozen', 'new_map_2', 'frozen_storage_loading_dock_01',
   1.3314581184, -0.8149269956, -1.57214, 'available',
   JSON_OBJECT('coordinate_source', 'trihouse_test_01_physical_features.new_map_2.jsonl', 'provisional', true)),
  (@packing_id,
   'PACKING-01-DOCK-01', 'Packing Station Loading Dock 01', 'loading_dock',
   'packing', 'ambient', 'new_map_2', 'packing_station_loading_dock_01',
   0.351, -0.49, 0.231, 'available',
   JSON_OBJECT('coordinate_source', 'trihouse_test_01_physical_features.new_map_2.jsonl', 'provisional', true)),
  (@packing_id,
   'PACKING-01-DOCK-02', 'Packing Station Loading Dock 02', 'loading_dock',
   'packing', 'ambient', 'new_map_2', 'packing_station_loading_dock_02',
   0.351, -1.017, 0.231, 'available',
   JSON_OBJECT('coordinate_source', 'trihouse_test_01_physical_features.new_map_2.jsonl', 'provisional', true)),
  (NULL, 'TRIHOUSE-TEST-01-SAFETY-01', 'Safety Zone 01', 'safe_node',
   'safety', NULL, 'new_map_2', 'safety_zone_01',
   0.613, -1.249, 0.0, 'available',
   JSON_OBJECT('coordinate_source', 'trihouse_test_01_physical_features.new_map_2.jsonl', 'provisional', true)),
  (NULL, 'TRIHOUSE-TEST-01-CHG-01', 'Pinky Charging Station 01', 'charger',
   'charging', NULL, 'new_map_2', 'charging_station_01',
   0.0570244747, 0.1949666005, 0.1093261667, 'available',
   JSON_OBJECT('coordinate_source', 'trihouse_test_01_physical_features.new_map_2.jsonl', 'provisional', true)),
  (NULL, 'TRIHOUSE-TEST-01-CHG-02', 'Pinky Charging Station 02', 'charger',
   'charging', NULL, 'new_map_2', 'charging_station_02',
   0.1336554086, -0.0065562838, 0.1569596446, 'available',
   JSON_OBJECT('coordinate_source', 'trihouse_test_01_physical_features.new_map_2.jsonl', 'provisional', true)),
  (NULL, 'TRIHOUSE-TEST-01-CHG-EXIT', 'Charging Station Narrow Exit', 'staging',
   'charging', NULL, 'new_map_2', 'charging_station_narrow_exit',
   0.7992961442, 0.0854053105, 0.0923642279, 'available',
   JSON_OBJECT('coordinate_source', 'waypoint.md', 'provisional', false)),
  (@wh_frz_id, 'WH-FRZ-01-NARROW-ENTRY', 'Frozen Storage Narrow Entry', 'staging',
   'frozen', 'frozen', 'new_map_2', 'frozen_storage_narrow_entry',
   1.1792881155, -1.1896842748, 0.010938119, 'available',
   JSON_OBJECT('coordinate_source', 'waypoint.md', 'provisional', false))
ON DUPLICATE KEY UPDATE
  parent_location_id = VALUES(parent_location_id),
  name = VALUES(name),
  location_type = VALUES(location_type),
  zone_code = VALUES(zone_code),
  temperature_zone = VALUES(temperature_zone),
  map_name = VALUES(map_name),
  rmf_waypoint_name = VALUES(rmf_waypoint_name),
  pose_x = VALUES(pose_x),
  pose_y = VALUES(pose_y),
  pose_yaw = VALUES(pose_yaw),
  state = VALUES(state),
  metadata = VALUES(metadata);

-- EN: Final storage slots record only their physical level and index.
-- KO: 최종 보관 슬롯에는 실제 단수와 칸 번호만 기록한다.
INSERT INTO locations
  (parent_location_id, location_code, name, location_type, zone_code,
   temperature_zone, state, metadata)
VALUES
  (@wh_amb_id,
   'AMB-L1-S01', 'Ambient Storage L1 Slot 01', 'slot', 'ambient', 'ambient',
   'occupied', JSON_OBJECT('shelf_level', 1, 'slot_index', 1)),
  (@wh_amb_id,
   'AMB-L1-S02', 'Ambient Storage L1 Slot 02', 'slot', 'ambient', 'ambient',
   'available', JSON_OBJECT('shelf_level', 1, 'slot_index', 2)),
  (@wh_amb_id,
   'AMB-L2-S01', 'Ambient Storage L2 Slot 01', 'slot', 'ambient', 'ambient',
   'occupied', JSON_OBJECT('shelf_level', 2, 'slot_index', 1)),
  (@wh_amb_id,
   'AMB-L2-S02', 'Ambient Storage L2 Slot 02', 'slot', 'ambient', 'ambient',
   'occupied', JSON_OBJECT('shelf_level', 2, 'slot_index', 2)),
  (@wh_chl_id,
   'CHL-L1-S01', 'Chilled Storage L1 Slot 01', 'slot', 'chilled', 'chilled',
   'occupied', JSON_OBJECT('shelf_level', 1, 'slot_index', 1)),
  (@wh_chl_id,
   'CHL-L1-S02', 'Chilled Storage L1 Slot 02', 'slot', 'chilled', 'chilled',
   'occupied', JSON_OBJECT('shelf_level', 1, 'slot_index', 2)),
  (@wh_chl_id,
   'CHL-L2-S01', 'Chilled Storage L2 Slot 01', 'slot', 'chilled', 'chilled',
   'occupied', JSON_OBJECT('shelf_level', 2, 'slot_index', 1)),
  (@wh_chl_id,
   'CHL-L2-S02', 'Chilled Storage L2 Slot 02', 'slot', 'chilled', 'chilled',
   'occupied', JSON_OBJECT('shelf_level', 2, 'slot_index', 2)),
  (@wh_frz_id,
   'FRZ-L1-S01', 'Frozen Storage L1 Slot 01', 'slot', 'frozen', 'frozen',
   'occupied', JSON_OBJECT('shelf_level', 1, 'slot_index', 1)),
  (@wh_frz_id,
   'FRZ-L1-S02', 'Frozen Storage L1 Slot 02', 'slot', 'frozen', 'frozen',
   'occupied', JSON_OBJECT('shelf_level', 1, 'slot_index', 2)),
  (@wh_frz_id,
   'FRZ-L2-S01', 'Frozen Storage L2 Slot 01', 'slot', 'frozen', 'frozen',
   'occupied', JSON_OBJECT('shelf_level', 2, 'slot_index', 1)),
  (@wh_frz_id,
   'FRZ-L2-S02', 'Frozen Storage L2 Slot 02', 'slot', 'frozen', 'frozen',
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
  ('W-FIELD-01', 'W-FIELD-01', 'Field Worker 01', 'operator',
   JSON_ARRAY('ambient', 'chilled', 'frozen', 'packing'), 1,
   '2026-08-03 09:00:00.000000'),
  ('W-FIELD-02', 'W-FIELD-02', 'Field Worker 02', 'operator',
   JSON_ARRAY('ambient', 'chilled', 'frozen', 'packing'), 1,
   '2026-08-03 09:00:00.000000'),
  ('W-CONTROL-01', 'W-CONTROL-01', 'AI-Server-4060 Control Operator', 'safety_manager',
   JSON_ARRAY('ambient', 'chilled', 'frozen', 'packing', 'safety'), 1,
   '2026-08-03 09:00:00.000000')
ON DUPLICATE KEY UPDATE
  name = VALUES(name),
  role = VALUES(role),
  active = VALUES(active);

INSERT INTO devices
  (device_id, device_type, name, model, fleet_name, home_location_id,
   current_location_id, control_mode, active, capabilities, registered_at)
VALUES
  ('PK_01', 'mobile', 'PK_01', 'Pinky-Pro', 'new_map_2_pinky',
   (SELECT location_id FROM locations WHERE location_code = 'TRIHOUSE-TEST-01-CHG-01'),
   (SELECT location_id FROM locations WHERE location_code = 'TRIHOUSE-TEST-01-CHG-01'),
   'automatic', 1, JSON_OBJECT('navigation', true, 'rmf', true,
     'rmf_robot_name', 'PK_01'),
   '2026-08-03 09:00:00.000000'),
  ('PK_02', 'mobile', 'PK_02', 'Pinky-Pro', 'new_map_2_pinky',
   (SELECT location_id FROM locations WHERE location_code = 'TRIHOUSE-TEST-01-CHG-02'),
   (SELECT location_id FROM locations WHERE location_code = 'TRIHOUSE-TEST-01-CHG-02'),
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

-- EN: Hardware state is created only by a real heartbeat; the seed never makes a device dispatchable.
-- KO: 실물 장비 상태는 실제 heartbeat로만 생성하며 seed가 장비를 배차 가능 상태로 만들지 않는다.
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
