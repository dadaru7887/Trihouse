-- Add searchable, canonical English operational metadata to map waypoints.
-- This migration preserves all waypoint identities and coordinates.
-- Run once against an existing Trihouse volume after taking a backup.

USE `trihouse_fms`;

-- DDL auto-commits in MySQL. Keep this migration restartable so a failure after
-- adding one or more columns can be repaired by running the same file again.
DROP PROCEDURE IF EXISTS migrate_008_waypoint_operational_roles;
DELIMITER $$
CREATE PROCEDURE migrate_008_waypoint_operational_roles()
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'map_project_waypoints'
      AND COLUMN_NAME = 'operational_role'
  ) THEN
    ALTER TABLE map_project_waypoints
      ADD COLUMN operational_role VARCHAR(40) NOT NULL DEFAULT 'transit_waypoint'
        COMMENT 'Warehouse operation role selected in the UI and projected to locations.'
        AFTER category;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'map_project_waypoints'
      AND COLUMN_NAME = 'temperature_zone'
  ) THEN
    ALTER TABLE map_project_waypoints
      ADD COLUMN temperature_zone VARCHAR(16) NULL
        COMMENT 'Optional ambient, chilled, or frozen operating zone.'
        AFTER operational_role;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'map_project_waypoints'
      AND COLUMN_NAME = 'parent_location_code'
  ) THEN
    ALTER TABLE map_project_waypoints
      ADD COLUMN parent_location_code VARCHAR(96) NULL
        COMMENT 'Optional canonical location_code of the warehouse or station that owns this access point.'
        AFTER temperature_zone;
  END IF;

  -- The legacy constraint accepts only Korean categories. Remove it before
  -- converting rows to their canonical English values.
  IF EXISTS (
    SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
    WHERE CONSTRAINT_SCHEMA = DATABASE()
      AND TABLE_NAME = 'map_project_waypoints'
      AND CONSTRAINT_NAME = 'chk_map_waypoints_category'
      AND CONSTRAINT_TYPE = 'CHECK'
  ) THEN
    ALTER TABLE map_project_waypoints
      DROP CHECK chk_map_waypoints_category;
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
    WHERE CONSTRAINT_SCHEMA = DATABASE()
      AND TABLE_NAME = 'map_project_waypoints'
      AND CONSTRAINT_NAME = 'chk_map_waypoints_operational_role'
      AND CONSTRAINT_TYPE = 'CHECK'
  ) THEN
    ALTER TABLE map_project_waypoints
      DROP CHECK chk_map_waypoints_operational_role;
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
    WHERE CONSTRAINT_SCHEMA = DATABASE()
      AND TABLE_NAME = 'map_project_waypoints'
      AND CONSTRAINT_NAME = 'chk_map_waypoints_temperature_zone'
      AND CONSTRAINT_TYPE = 'CHECK'
  ) THEN
    ALTER TABLE map_project_waypoints
      DROP CHECK chk_map_waypoints_temperature_zone;
  END IF;

  -- Preserve compatibility with old Korean UI payloads while converting the
  -- relational projection to canonical English values. Generic waiting points
  -- are not promoted to safety zones without explicit naming evidence.
  UPDATE map_project_waypoints
  SET operational_role = CASE
        WHEN LOWER(rmf_waypoint_name) REGEXP '(^|[_ -])(safe|safety)([_ -]|$)'
          THEN 'safety_zone'
        WHEN HEX(category) = 'ECB6A9ECA084' THEN 'charging_station'
        WHEN HEX(category) = 'ED94BDEC9785' THEN 'loading_dock'
        WHEN HEX(category) IN (
          'EB939CEB9E8DEC98A4ED9484',
          'EB939CEBA1ADEC98A4ED9484'
        ) THEN 'packing_handover'
        WHEN HEX(category) IN ('ECA3BCECB0A8', 'ED9988') THEN 'parking_spot'
        WHEN HEX(category) = 'EC84A4EBB984' THEN 'workcell_station'
        ELSE operational_role
      END,
      category = CASE HEX(category)
        WHEN 'EB8C80EAB8B0' THEN 'holding'
        WHEN 'ECA3BCECB0A8' THEN 'parking'
        WHEN 'ED9988' THEN 'home'
        WHEN 'ECB6A9ECA084' THEN 'charger'
        WHEN 'ED94BDEC9785' THEN 'pickup'
        WHEN 'EB939CEB9E8DEC98A4ED9484' THEN 'dropoff'
        WHEN 'EB939CEBA1ADEC98A4ED9484' THEN 'dropoff'
        WHEN 'EC84A4EBB984' THEN 'equipment'
        WHEN 'EC9DBCEBB098' THEN 'waypoint'
        ELSE category
      END;

  ALTER TABLE map_project_waypoints
    ADD CONSTRAINT chk_map_waypoints_category CHECK (category IN
      ('waypoint','holding','parking','home','charger','pickup','dropoff','equipment')),
    ADD CONSTRAINT chk_map_waypoints_operational_role CHECK (operational_role IN
      ('ambient_storage_access','chilled_storage_access','frozen_storage_access',
       'safety_zone','charging_station','packing_handover','loading_dock',
       'transit_waypoint','parking_spot','inspection_point','workcell_station')),
    ADD CONSTRAINT chk_map_waypoints_temperature_zone CHECK
      (temperature_zone IS NULL OR temperature_zone IN ('ambient','chilled','frozen'));
END$$
DELIMITER ;

CALL migrate_008_waypoint_operational_roles();
DROP PROCEDURE migrate_008_waypoint_operational_roles;

-- Canonical display names for existing development/operation warehouse rows.
-- Business keys and RMF waypoint names are intentionally unchanged.
UPDATE locations
SET name = CASE location_code
  WHEN 'A-SLOT-01' THEN 'Ambient Rack Slot 01'
  WHEN 'OUT-DOCK-01' THEN 'Outbound Dock 01'
  WHEN 'CHG-01' THEN 'Pinky Charging Station 01'
  WHEN 'CHG-02' THEN 'Pinky Charging Station 02'
  WHEN 'IN-WAIT-01' THEN 'Inbound Waiting Point 01'
  WHEN 'NARROW-WAIT-01' THEN 'Narrow-Aisle Waiting Point 01'
  WHEN 'OMX-WS-01' THEN 'OMX Handover Workcell 01'
  WHEN 'OMX-WS-02' THEN 'OMX Handover Workcell 02'
  WHEN 'WH-AMB-01' THEN 'Ambient Storage'
  WHEN 'WH-CHL-01' THEN 'Chilled Storage'
  WHEN 'WH-FRZ-01' THEN 'Frozen Storage'
  WHEN 'AMB-L1-S01' THEN 'Ambient Storage L1 Slot 01'
  WHEN 'AMB-L1-S02' THEN 'Ambient Storage L1 Slot 02'
  WHEN 'AMB-L2-S01' THEN 'Ambient Storage L2 Slot 01'
  WHEN 'AMB-L2-S02' THEN 'Ambient Storage L2 Slot 02'
  WHEN 'CHL-L1-S01' THEN 'Chilled Storage L1 Slot 01'
  WHEN 'CHL-L1-S02' THEN 'Chilled Storage L1 Slot 02'
  WHEN 'CHL-L2-S01' THEN 'Chilled Storage L2 Slot 01'
  WHEN 'CHL-L2-S02' THEN 'Chilled Storage L2 Slot 02'
  WHEN 'FRZ-L1-S01' THEN 'Frozen Storage L1 Slot 01'
  WHEN 'FRZ-L1-S02' THEN 'Frozen Storage L1 Slot 02'
  WHEN 'FRZ-L2-S01' THEN 'Frozen Storage L2 Slot 01'
  WHEN 'FRZ-L2-S02' THEN 'Frozen Storage L2 Slot 02'
  ELSE name
END
WHERE location_code IN (
  'A-SLOT-01','OUT-DOCK-01','CHG-01','CHG-02','IN-WAIT-01',
  'NARROW-WAIT-01','OMX-WS-01','OMX-WS-02',
  'WH-AMB-01','WH-CHL-01','WH-FRZ-01',
  'AMB-L1-S01','AMB-L1-S02','AMB-L2-S01','AMB-L2-S02',
  'CHL-L1-S01','CHL-L1-S02','CHL-L2-S01','CHL-L2-S02',
  'FRZ-L1-S01','FRZ-L1-S02','FRZ-L2-S01','FRZ-L2-S02'
);
