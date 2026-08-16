-- Use one direction-neutral loading dock for inbound and outbound jobs, and
-- introduce a dedicated mandatory stop before bottleneck/ArUco admission.
-- Location and waypoint identities are preserved.
-- Requires migration 008_add_waypoint_operational_roles.sql to be applied first.

USE `trihouse_fms`;

INSERT INTO locations
  (location_code, name, location_type, zone_code, temperature_zone, state, metadata)
VALUES
  ('PACKING-01', 'Packing Station', 'workstation', 'packing', 'ambient',
   'available', JSON_OBJECT('authoring_managed', false))
ON DUPLICATE KEY UPDATE
  name = VALUES(name),
  location_type = VALUES(location_type),
  zone_code = VALUES(zone_code),
  temperature_zone = VALUES(temperature_zone);

ALTER TABLE locations
  DROP CHECK chk_locations_type,
  ADD CONSTRAINT chk_locations_type CHECK (location_type IN
    ('rack','slot','waypoint','staging','inbound_dock','outbound_dock','loading_dock',
     'charger','workstation','door','safe_node'));

UPDATE locations
SET metadata = JSON_SET(
      COALESCE(metadata, JSON_OBJECT()),
      '$.operational_role', 'loading_dock',
      '$.legacy_location_type', location_type
    ),
    location_type = 'loading_dock'
WHERE location_type IN ('inbound_dock','outbound_dock');

ALTER TABLE locations
  DROP CHECK chk_locations_type,
  ADD CONSTRAINT chk_locations_type CHECK (location_type IN
    ('rack','slot','waypoint','staging','loading_dock',
     'charger','workstation','door','safe_node'));

UPDATE map_project_waypoints
SET operational_role = 'loading_dock',
    category = 'holding'
WHERE operational_role IN (
  'ambient_storage_access',
  'chilled_storage_access',
  'frozen_storage_access',
  'packing_handover',
  'loading_dock'
);

ALTER TABLE map_project_waypoints
  DROP CHECK chk_map_waypoints_operational_role,
  ADD CONSTRAINT chk_map_waypoints_operational_role CHECK (operational_role IN
    ('safety_zone','charging_station','loading_dock','bottleneck_waiting_point',
     'transit_waypoint','parking_spot','inspection_point','workcell_station'));
