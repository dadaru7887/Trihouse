-- ============================================================================
-- FMS MySQL 스키마 v4
--
-- 목적
--   Pinky-pro 주행로봇 2대와 OMX-AI 로봇팔 2대를 함께 운영한다.
--   Open-RMF는 주행로봇의 교통을, Cyclo/OMX는 조작을 맡고,
--   데이터베이스는 입출고·재고·작업·안전·감사 이력 관리를 담당한다.
--
-- 운영 원칙
--   * MySQL 8.0 이상, InnoDB, Asia/Seoul DATETIME(6)을 사용한다.
--   * Gateway는 연결 직후 SET time_zone = '+09:00'을 실행한다.
--   * 이 파일은 실제 운영 예시 데이터를 넣지 않는다.
--   * UI와 장비 어댑터는 FMS API만 사용하며 MySQL 쓰기 권한을 받지 않는다.
--   * VLM/RL의 관측과 복구 제안은 기록 대상이며, 전역 배차·최종 안전 권한은
--     FMS와 Safety Supervisor에 남긴다.
-- ============================================================================

CREATE DATABASE IF NOT EXISTS `trihouse_fms`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `trihouse_fms`;

-- [공간·작업장] 창고의 모든 운영 위치를 관리한다.
-- 랙·슬롯·도크·충전기·포장대·OMX 작업장·RMF waypoint를 한 기준으로 연결한다.
CREATE TABLE IF NOT EXISTS locations (
  location_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '연결된 운영 위치의 내부 식별자',
  parent_location_id BIGINT UNSIGNED NULL COMMENT '위치 계층에서 바로 상위에 있는 운영 위치 식별자',
  location_code      VARCHAR(96) NOT NULL COMMENT '운영 화면과 외부 연동에서 사용하는 위치 고유 코드',
  name               VARCHAR(160) NULL COMMENT '운영자 화면에 표시할 위치 이름',
  location_type      VARCHAR(32) NOT NULL COMMENT '랙, 슬롯, waypoint, 도크, 충전기, 작업장 등 위치 종류 코드',
  zone_code          VARCHAR(64) NULL COMMENT '창고 운영 구역을 식별하는 코드',
  temperature_zone   VARCHAR(16) NULL COMMENT '상온 ambient, 냉장 chilled 또는 냉동 frozen 보관 구역 코드',
  map_name           VARCHAR(96) NULL COMMENT 'Open-RMF와 로봇 navigation에서 사용하는 지도 이름',
  rmf_waypoint_name  VARCHAR(128) NULL COMMENT 'Open-RMF navigation graph의 waypoint 이름',
  pose_x             DOUBLE NULL COMMENT '지도 좌표계 기준 X 좌표이며 단위는 m',
  pose_y             DOUBLE NULL COMMENT '지도 좌표계 기준 Y 좌표이며 단위는 m',
  pose_yaw           DOUBLE NULL COMMENT '지도 좌표계 기준 회전각이며 단위는 rad',
  state              VARCHAR(24) NOT NULL DEFAULT 'available' COMMENT '위치의 현재 운영 상태이며 available, reserved, occupied, blocked, maintenance 중 하나',
  metadata           JSON NULL COMMENT '위치별 확장 속성과 외부 연동 값을 저장하는 JSON 객체',
  PRIMARY KEY (location_id),
  UNIQUE KEY uq_locations_code (location_code),
  UNIQUE KEY uq_locations_rmf_waypoint (map_name, rmf_waypoint_name),
  KEY idx_locations_zone_type (zone_code, location_type),
  CONSTRAINT fk_locations_parent
    FOREIGN KEY (parent_location_id) REFERENCES locations (location_id),
  CONSTRAINT chk_locations_type CHECK (location_type IN
    ('rack','slot','waypoint','staging','inbound_dock','outbound_dock',
     'charger','workstation','door','safe_node')),
  CONSTRAINT chk_locations_temperature CHECK (temperature_zone IS NULL OR
    temperature_zone IN ('ambient','chilled','frozen')),
  CONSTRAINT chk_locations_state CHECK (state IN
    ('available','reserved','occupied','blocked','maintenance'))
) ENGINE=InnoDB COMMENT='창고의 랙, 슬롯, 도크, 충전기, 작업장, 안전 노드와 RMF waypoint를 통합 관리한다.';

-- [공간·작업장] 지도에서 운영에 의미가 있는 feature를 관리한다.
-- 정적 장애물·ArUco marker·병목 통로·출입문·진입 금지 구역을 표현한다.
-- 실제 Nav2/RMF 지도 파일은 버전 관리 저장소에 두고, 이 테이블은 UI·운영 규칙·
-- marker 조회를 위한 메타데이터만 가진다.
CREATE TABLE IF NOT EXISTS map_features (
  feature_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '지도 feature를 식별하는 자동 증가 번호',
  map_name            VARCHAR(96) NOT NULL COMMENT 'Open-RMF와 로봇 navigation에서 사용하는 지도 이름',
  map_revision        VARCHAR(128) NOT NULL COMMENT '좌표와 feature가 유효한 지도 버전 식별자',
  feature_code        VARCHAR(128) NOT NULL COMMENT '지도 revision 안에서 feature를 식별하는 업무 코드',
  feature_type        VARCHAR(24) NOT NULL COMMENT '표식, 정적 장애물, 병목, 출입문 또는 진입 금지 구역 코드',
  location_id         BIGINT UNSIGNED NULL COMMENT '연결된 운영 위치의 내부 식별자',
  marker_code         INT UNSIGNED NULL COMMENT 'QR 또는 ArUco 표식에서 읽는 숫자 코드',
  geometry            JSON NOT NULL COMMENT '지도 좌표계의 점, 선 또는 다각형 공간 정보를 담은 JSON 객체',
  properties          JSON NULL COMMENT '지도 feature의 운영 규칙과 표시 속성을 담은 JSON 객체',
  active              TINYINT(1) NOT NULL DEFAULT 1 COMMENT '해당 지도 revision에서 feature를 운영 규칙에 사용할지 나타내는 값',
  PRIMARY KEY (feature_id),
  UNIQUE KEY uq_map_features_code (map_name, map_revision, feature_code),
  UNIQUE KEY uq_map_features_marker (map_name, map_revision, marker_code),
  KEY idx_map_features_location (location_id),
  KEY idx_map_features_type (map_name, feature_type, active),
  CONSTRAINT fk_map_features_location FOREIGN KEY (location_id)
    REFERENCES locations (location_id),
  CONSTRAINT chk_map_features_type CHECK (feature_type IN
    ('fiducial','static_obstacle','bottleneck','door','no_go_zone')),
  CONSTRAINT chk_map_features_marker CHECK
    ((feature_type = 'fiducial' AND marker_code IS NOT NULL) OR
     (feature_type <> 'fiducial' AND marker_code IS NULL))
) ENGINE=InnoDB COMMENT='지도 revision별 표식, 정적 장애물, 병목, 출입문과 진입 금지 구역의 공간 정보를 관리한다.';

-- [사람·권한] 관제 요청·수동 복구·안전 해제에 책임을 남길 작업자 계정이다.
-- 카메라가 감지한 사람의 실시간 위치를 기록하는 테이블이 아니다.
CREATE TABLE IF NOT EXISTS workers (
  worker_id          VARCHAR(64) NOT NULL COMMENT '작업자 계정을 식별하는 내부 고유 값',
  worker_code        VARCHAR(64) NOT NULL COMMENT '운영 화면과 인증 연동에서 사용하는 작업자 고유 코드',
  name               VARCHAR(128) NOT NULL COMMENT '운영자 화면과 감사 기록에 표시할 작업자 이름',
  role               VARCHAR(32) NOT NULL COMMENT '작업자의 운영 권한 역할 코드',
  external_auth_id   VARCHAR(128) NULL COMMENT 'SSO 또는 외부 인증 시스템에서 사용하는 작업자 식별자',
  allowed_zones      JSON NULL COMMENT '작업자가 접근하거나 조작할 수 있는 구역 코드의 JSON 배열',
  active             TINYINT(1) NOT NULL DEFAULT 1 COMMENT '작업자 계정이 현재 업무 요청과 승인에 참여할 수 있는지 나타내는 값',
  registered_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '작업자 또는 장비가 운영 시스템에 등록된 시각',
  retired_at         DATETIME(6) NULL COMMENT '작업자 또는 장비를 운영 대상에서 제외한 시각',
  PRIMARY KEY (worker_id),
  UNIQUE KEY uq_workers_code (worker_code),
  UNIQUE KEY uq_workers_external_auth (external_auth_id),
  KEY idx_workers_role_active (role, active),
  CONSTRAINT chk_workers_role CHECK (role IN
    ('operator','supervisor','safety_manager','administrator'))
) ENGINE=InnoDB COMMENT='관제 요청, 수동 복구와 안전 해제에 대한 책임을 식별할 작업자 계정과 권한 범위를 관리한다.';

-- [장비] Pinky와 OMX의 공통 장비 마스터다.
-- 실시간 상태와 작업 실행 내용은 아래 device_states·job_steps에서 관리한다.
CREATE TABLE IF NOT EXISTS devices (
  device_id            VARCHAR(64) NOT NULL COMMENT 'Pinky 또는 OMX 장비를 식별하는 고유 코드',
  device_type          VARCHAR(16) NOT NULL COMMENT '장비를 주행로봇 mobile 또는 로봇팔 arm으로 구분하는 코드',
  name                 VARCHAR(128) NOT NULL COMMENT '운영자 화면에 표시할 장비 이름',
  model                VARCHAR(96) NOT NULL COMMENT '장비 제조사 또는 제품 모델 이름',
  fleet_name           VARCHAR(96) NULL COMMENT '주행로봇이 소속된 Open-RMF fleet 이름',
  home_location_id     BIGINT UNSIGNED NULL COMMENT '장비가 대기하거나 복귀할 기본 운영 위치 식별자',
  current_location_id  BIGINT UNSIGNED NULL COMMENT '장비가 현재 위치한 것으로 확정된 운영 위치 식별자',
  control_mode         VARCHAR(24) NOT NULL DEFAULT 'automatic' COMMENT '장비의 자동, 수동, 오프라인, 정비 또는 안전 정지 제어 모드',
  active               TINYINT(1) NOT NULL DEFAULT 1 COMMENT '장비가 현재 배차와 작업 할당 대상인지 나타내는 값',
  capabilities         JSON NULL COMMENT '장비가 지원하는 동작과 기능을 표현한 JSON 객체',
  registered_at        DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '작업자 또는 장비가 운영 시스템에 등록된 시각',
  retired_at           DATETIME(6) NULL COMMENT '작업자 또는 장비를 운영 대상에서 제외한 시각',
  PRIMARY KEY (device_id),
  KEY idx_devices_type_active (device_type, active),
  KEY idx_devices_fleet (fleet_name),
  CONSTRAINT fk_devices_home FOREIGN KEY (home_location_id)
    REFERENCES locations (location_id),
  CONSTRAINT fk_devices_current FOREIGN KEY (current_location_id)
    REFERENCES locations (location_id),
  CONSTRAINT chk_devices_type CHECK (device_type IN ('mobile','arm')),
  CONSTRAINT chk_devices_mode CHECK (control_mode IN
    ('automatic','manual','offline','maintenance','safety_hold'))
) ENGINE=InnoDB COMMENT='Pinky 주행로봇과 OMX 로봇팔의 모델, 소속, 위치, 제어 모드와 기능을 관리한다.';

-- [재고] 유통기한과 보관 온도를 가진 재고 lot의 현재 수량을 관리한다.
-- reserved_qty는 일시적인 업무 예약이며, 수량 변동의 증거는 inventory_moves에 남긴다.
CREATE TABLE IF NOT EXISTS inventory_lots (
  lot_id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '연결된 재고 로트의 내부 식별자',
  product_code       VARCHAR(96) NOT NULL COMMENT '상품 종류를 식별하는 업무 코드',
  lot_code           VARCHAR(128) NOT NULL COMMENT '입고 단위와 추적에 사용하는 재고 로트 고유 코드',
  item_name          VARCHAR(160) NULL COMMENT '운영자 화면에 표시할 상품 이름',
  temperature_zone   VARCHAR(16) NOT NULL COMMENT '상온 ambient, 냉장 chilled 또는 냉동 frozen 보관 구역 코드',
  location_id        BIGINT UNSIGNED NULL COMMENT '연결된 운영 위치의 내부 식별자',
  expiry_date        DATE NOT NULL COMMENT '재고 로트의 유통기한 날짜',
  unit_weight_kg     DECIMAL(10,3) NULL COMMENT '상품 한 단위의 kg 기준 무게',
  available_qty      INT NOT NULL DEFAULT 0 COMMENT '현재 로트에서 물리적으로 보유한 전체 수량',
  reserved_qty       INT NOT NULL DEFAULT 0 COMMENT '출고 등의 업무를 위해 선점된 수량',
  state              VARCHAR(24) NOT NULL DEFAULT 'stored' COMMENT '재고 로트의 입고 대기, 보관, 보류, 소진, 만료 또는 손상 상태',
  received_at        DATETIME(6) NULL COMMENT '재고 로트의 입고가 완료된 시각',
  updated_at         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                       ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '해당 레코드가 마지막으로 수정된 시각',
  PRIMARY KEY (lot_id),
  UNIQUE KEY uq_inventory_lots_lot_code (lot_code),
  KEY idx_lots_product_expiry (product_code, expiry_date),
  KEY idx_lots_location (location_id),
  CONSTRAINT fk_lots_location FOREIGN KEY (location_id)
    REFERENCES locations (location_id),
  CONSTRAINT chk_lots_temperature CHECK (temperature_zone IN
    ('ambient','chilled','frozen')),
  CONSTRAINT chk_lots_qty CHECK
    (available_qty >= 0 AND reserved_qty >= 0
      AND reserved_qty <= available_qty),
  CONSTRAINT chk_lots_state CHECK (state IN
    ('pending_inbound','stored','on_hold','depleted','expired','damaged'))
) ENGINE=InnoDB COMMENT='상품 로트별 보관 위치, 유통기한, 가용 수량, 예약 수량과 보관 상태를 관리한다.';

-- [업무] 입고·출고·이동·보충·폐기·복구·비상 대응을 하나의 업무 단위로 관리한다.
-- 주문과 로봇 미션을 별도 헤더로 나누지 않아 운영자가 한 화면에서 상태를 본다.
CREATE TABLE IF NOT EXISTS jobs (
  job_id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '업무를 식별하는 자동 증가 번호',
  parent_job_id        BIGINT UNSIGNED NULL COMMENT '하위 업무를 생성한 상위 업무의 식별자',
  job_code             VARCHAR(64) NOT NULL COMMENT '운영 화면과 외부 연동에서 사용하는 업무 고유 코드',
  operation_type       VARCHAR(24) NOT NULL COMMENT '입고, 출고, 이동, 보충, 폐기, 복구 또는 비상 업무 종류 코드',
  priority             VARCHAR(16) NOT NULL DEFAULT 'normal' COMMENT '업무의 critical, high, normal 또는 low 우선순위 코드',
  priority_rank        TINYINT UNSIGNED GENERATED ALWAYS AS (
    CASE priority
      WHEN 'critical' THEN 1
      WHEN 'high' THEN 2
      WHEN 'normal' THEN 3
      WHEN 'low' THEN 4
    END
  ) STORED COMMENT '우선순위 정렬을 위해 자동 계산되는 숫자 값',
  state                VARCHAR(24) NOT NULL DEFAULT 'pending' COMMENT '업무의 대기부터 계획, 실행, 완료, 실패, 취소와 안전 보류까지의 상태',
  revision             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '동시 수정 충돌을 탐지하기 위한 낙관적 잠금 버전',
  requested_by         VARCHAR(64) NULL COMMENT '업무 생성을 요청한 작업자의 식별자',
  external_reference   VARCHAR(128) NULL COMMENT '외부 시스템의 요청이나 작업과 연결하는 참조 값',
  source_location_id   BIGINT UNSIGNED NULL COMMENT '업무가 시작되는 운영 위치 식별자',
  destination_location_id BIGINT UNSIGNED NULL COMMENT '업무가 최종적으로 도착해야 하는 운영 위치 식별자',
  due_at               DATETIME(6) NULL COMMENT '업무 완료가 요구되는 기한 시각',
  assigned_mobile_id   VARCHAR(64) NULL COMMENT '업무에 배정된 Pinky 주행로봇의 장비 식별자',
  failure_reason       VARCHAR(512) NULL COMMENT '업무 또는 실행 단계가 실패한 구체적인 원인',
  context              JSON NULL COMMENT '업무 생성 원인과 외부 요청의 확장 맥락을 저장하는 JSON 객체',
  created_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '해당 레코드가 데이터베이스에 생성된 시각',
  started_at           DATETIME(6) NULL COMMENT '업무, 단계 또는 복구 행동이 실제로 시작된 시각',
  completed_at         DATETIME(6) NULL COMMENT '업무, 단계 또는 복구 행동이 완료된 시각',
  PRIMARY KEY (job_id),
  UNIQUE KEY uq_jobs_code (job_code),
  UNIQUE KEY uq_jobs_external_reference (external_reference),
  KEY idx_jobs_dispatch (state, priority_rank, due_at, created_at),
  KEY idx_jobs_mobile (assigned_mobile_id, state),
  KEY idx_jobs_parent (parent_job_id),
  CONSTRAINT fk_jobs_parent FOREIGN KEY (parent_job_id)
    REFERENCES jobs (job_id),
  CONSTRAINT fk_jobs_source FOREIGN KEY (source_location_id)
    REFERENCES locations (location_id),
  CONSTRAINT fk_jobs_destination FOREIGN KEY (destination_location_id)
    REFERENCES locations (location_id),
  CONSTRAINT fk_jobs_mobile FOREIGN KEY (assigned_mobile_id)
    REFERENCES devices (device_id),
  CONSTRAINT fk_jobs_requester FOREIGN KEY (requested_by)
    REFERENCES workers (worker_id),
  CONSTRAINT chk_jobs_type CHECK (operation_type IN
    ('inbound','outbound','relocation','replenishment','disposal','recovery','emergency')),
  CONSTRAINT chk_jobs_priority CHECK (priority IN ('critical','high','normal','low')),
  CONSTRAINT chk_jobs_state CHECK (state IN
    ('pending','planned','running','waiting','blocked','completed','failed',
     'cancelled','safety_hold'))
) ENGINE=InnoDB COMMENT='입고, 출고, 이동, 보충, 폐기, 복구와 비상 대응 업무의 전체 수명주기를 관리한다.';

-- [업무] 한 업무에 포함된 상품·lot·수량·검수 상태를 관리한다.
-- 입고 예정 품목, 출고 요청 품목, 실제로 배정된 lot을 같은 구조로 기록한다.
CREATE TABLE IF NOT EXISTS job_items (
  job_item_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '업무 품목을 식별하는 자동 증가 번호',
  job_id              BIGINT UNSIGNED NOT NULL COMMENT '업무를 식별하는 자동 증가 번호',
  product_code        VARCHAR(96) NOT NULL COMMENT '상품 종류를 식별하는 업무 코드',
  requested_qty       INT NOT NULL COMMENT '업무에서 처리하도록 요청한 상품 수량',
  completed_qty       INT NOT NULL DEFAULT 0 COMMENT '업무 품목 중 실제 처리가 완료된 수량',
  lot_id              BIGINT UNSIGNED NULL COMMENT '연결된 재고 로트의 내부 식별자',
  handling_unit_code  VARCHAR(128) NULL COMMENT '바구니, 박스 또는 팔레트 등 취급 단위의 식별 코드',
  verification_state  VARCHAR(24) NOT NULL DEFAULT 'pending' COMMENT '업무 품목의 미검수, 일치, 불일치 또는 수동 검토 상태 코드',
  metadata            JSON NULL COMMENT '업무 품목별 검수와 외부 주문의 확장 값을 저장하는 JSON 객체',
  PRIMARY KEY (job_item_id),
  KEY idx_job_items_job (job_id),
  KEY idx_job_items_lot (lot_id),
  CONSTRAINT fk_job_items_job FOREIGN KEY (job_id)
    REFERENCES jobs (job_id) ON DELETE CASCADE,
  CONSTRAINT fk_job_items_lot FOREIGN KEY (lot_id)
    REFERENCES inventory_lots (lot_id),
  CONSTRAINT chk_job_items_qty CHECK
    (requested_qty > 0 AND completed_qty >= 0 AND completed_qty <= requested_qty),
  CONSTRAINT chk_job_items_verification CHECK (verification_state IN
    ('pending','matched','mismatch','manual_review'))
) ENGINE=InnoDB COMMENT='업무에 포함된 상품, 요청 수량, 완료 수량, 배정 로트와 검수 상태를 관리한다.';

-- [업무] 업무를 Pinky 이동·OMX 조작·검수·인계 순서의 실행 단계로 나눈다.
-- rmf_task_id로 RMF 작업을 직접 연결하고, 모델 이름·버전으로 VLM/RL 판단을
-- 별도 테이블 없이 추적한다.
CREATE TABLE IF NOT EXISTS job_steps (
  job_step_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '업무 실행 단계를 식별하는 자동 증가 번호',
  job_id               BIGINT UNSIGNED NOT NULL COMMENT '업무를 식별하는 자동 증가 번호',
  step_no              SMALLINT UNSIGNED NOT NULL COMMENT '같은 업무 또는 에피소드 안에서 실행 순서를 나타내는 번호',
  executor_type        VARCHAR(16) NOT NULL COMMENT '업무 단계의 실행 주체를 mobile, arm 또는 fms로 구분하는 코드',
  assigned_device_id   VARCHAR(64) NULL COMMENT '업무 단계를 실행하도록 배정된 장비 식별자',
  action_type          VARCHAR(32) NOT NULL COMMENT '실행할 동작 종류를 나타내는 코드 값',
  target_location_id   BIGINT UNSIGNED NULL COMMENT '업무 단계가 이동하거나 조작할 목표 운영 위치 식별자',
  state                VARCHAR(24) NOT NULL DEFAULT 'pending' COMMENT '업무 단계의 대기, 큐 등록, 실행, 성공, 실패, 보류 또는 취소 상태',
  rmf_task_id          VARCHAR(128) NULL COMMENT 'Open-RMF에서 발급한 이동 작업 식별자',
  policy_name          VARCHAR(128) NULL COMMENT '업무 단계 판단에 사용한 정책 이름',
  policy_version       VARCHAR(128) NULL COMMENT '업무 단계 판단에 사용한 정책 버전',
  retry_count          SMALLINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '업무 단계 실행을 다시 시도한 누적 횟수',
  failure_reason       VARCHAR(512) NULL COMMENT '업무 또는 실행 단계가 실패한 구체적인 원인',
  input                JSON NULL COMMENT '업무 단계를 실행할 때 전달한 입력 값을 저장하는 JSON 객체',
  result               JSON NULL COMMENT '업무 단계 실행 후 반환된 결과를 저장하는 JSON 객체',
  started_at           DATETIME(6) NULL COMMENT '업무, 단계 또는 복구 행동이 실제로 시작된 시각',
  completed_at         DATETIME(6) NULL COMMENT '업무, 단계 또는 복구 행동이 완료된 시각',
  PRIMARY KEY (job_step_id),
  UNIQUE KEY uq_job_steps_order (job_id, step_no),
  UNIQUE KEY uq_job_steps_rmf_task (rmf_task_id),
  KEY idx_job_steps_device_state (assigned_device_id, state),
  KEY idx_job_steps_dispatch (state, executor_type),
  CONSTRAINT fk_job_steps_job FOREIGN KEY (job_id)
    REFERENCES jobs (job_id) ON DELETE CASCADE,
  CONSTRAINT fk_job_steps_device FOREIGN KEY (assigned_device_id)
    REFERENCES devices (device_id),
  CONSTRAINT fk_job_steps_target FOREIGN KEY (target_location_id)
    REFERENCES locations (location_id),
  CONSTRAINT chk_job_steps_executor CHECK (executor_type IN ('mobile','arm','fms')),
  CONSTRAINT chk_job_steps_action CHECK (action_type IN
    ('navigate','dock','inspect','pick','load','unload','place','verify',
     'handover','wait','recover','return_home','safety_stop')),
  CONSTRAINT chk_job_steps_state CHECK (state IN
    ('pending','queued','running','succeeded','failed','on_hold','cancelled'))
) ENGINE=InnoDB COMMENT='업무를 Pinky 이동, OMX 조작, 검수와 인계 단위의 순서 있는 실행 단계로 관리한다.';

-- [점유] 병목 통로의 진입 권한과 도크·포장대·OMX의 사용 시간을 관리한다.
-- 병목은 map_feature_id를 잠그고, 시간 예약은 예정 사용 구간이 겹치지 않도록
-- FMS가 관리한다. 활성 상태의 실제 점유는 유일 키로 한 장비만 허용한다.
CREATE TABLE IF NOT EXISTS reservations (
  reservation_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '자원 예약을 식별하는 자동 증가 번호',
  job_id               BIGINT UNSIGNED NOT NULL COMMENT '업무를 식별하는 자동 증가 번호',
  job_step_id          BIGINT UNSIGNED NULL COMMENT '업무 실행 단계를 식별하는 자동 증가 번호',
  location_id          BIGINT UNSIGNED NULL COMMENT '연결된 운영 위치의 내부 식별자',
  device_id            VARCHAR(64) NULL COMMENT 'Pinky 또는 OMX 장비를 식별하는 고유 코드',
  map_feature_id       BIGINT UNSIGNED NULL COMMENT '병목 잠금과 연결된 지도 feature 식별자',
  reservation_mode     VARCHAR(24) NOT NULL DEFAULT 'exclusive_lock' COMMENT '독점 잠금, 병목 잠금 또는 시간 예약 방식 코드',
  state                VARCHAR(16) NOT NULL DEFAULT 'reserved' COMMENT '예약의 reserved, in_use, released, expired 또는 cancelled 상태',
  planned_start_at     DATETIME(6) NULL COMMENT '예약 자원의 사용을 시작할 예정 시각',
  planned_end_at       DATETIME(6) NULL COMMENT '예약 자원의 사용을 마칠 예정 시각',
  entered_at           DATETIME(6) NULL COMMENT '장비가 예약 자원에 실제로 진입한 시각',
  exited_at            DATETIME(6) NULL COMMENT '장비가 예약 자원에서 실제로 빠져나온 시각',
  expires_at           DATETIME(6) NOT NULL COMMENT '점유 확인이 없을 때 예약을 자동 만료할 기준 시각',
  created_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '해당 레코드가 데이터베이스에 생성된 시각',
  released_at          DATETIME(6) NULL COMMENT '예약 자원이 정상 또는 수동으로 해제된 시각',
  active_resource_key  VARCHAR(160) GENERATED ALWAYS AS (
    CASE
      WHEN reservation_mode = 'bottleneck_lock'
       AND state IN ('reserved','in_use')
        THEN CONCAT('feature:', map_feature_id)
      WHEN reservation_mode = 'exclusive_lock'
       AND state IN ('reserved','in_use')
        THEN CASE WHEN location_id IS NOT NULL THEN CONCAT('location:', location_id)
                  ELSE CONCAT('device:', device_id) END
      WHEN reservation_mode = 'time_slot'
       AND state = 'in_use'
        THEN CASE WHEN location_id IS NOT NULL THEN CONCAT('location:', location_id)
                  ELSE CONCAT('device:', device_id) END
      ELSE NULL
    END
  ) STORED COMMENT '활성 예약의 자원 중복을 방지하기 위해 계산한 고유 키',
  PRIMARY KEY (reservation_id),
  UNIQUE KEY uq_reservations_active_resource (active_resource_key),
  KEY idx_reservations_expiry (state, expires_at),
  KEY idx_reservations_job (job_id),
  KEY idx_reservations_location_schedule
    (location_id, state, planned_start_at, planned_end_at),
  KEY idx_reservations_device_schedule
    (device_id, state, planned_start_at, planned_end_at),
  KEY idx_reservations_feature_state (map_feature_id, state),
  KEY idx_reservations_feature_expiry (map_feature_id, state, expires_at),
  CONSTRAINT fk_reservations_job FOREIGN KEY (job_id)
    REFERENCES jobs (job_id) ON DELETE CASCADE,
  CONSTRAINT fk_reservations_step FOREIGN KEY (job_step_id)
    REFERENCES job_steps (job_step_id) ON DELETE SET NULL,
  CONSTRAINT fk_reservations_location FOREIGN KEY (location_id)
    REFERENCES locations (location_id),
  CONSTRAINT fk_reservations_device FOREIGN KEY (device_id)
    REFERENCES devices (device_id),
  CONSTRAINT fk_reservations_feature FOREIGN KEY (map_feature_id)
    REFERENCES map_features (feature_id),
  CONSTRAINT chk_reservations_target CHECK
    ((reservation_mode = 'bottleneck_lock' AND map_feature_id IS NOT NULL
      AND location_id IS NULL AND device_id IS NULL) OR
     (reservation_mode IN ('exclusive_lock','time_slot') AND map_feature_id IS NULL
      AND ((location_id IS NOT NULL AND device_id IS NULL) OR
           (location_id IS NULL AND device_id IS NOT NULL)))),
  CONSTRAINT chk_reservations_mode CHECK
    (reservation_mode IN ('exclusive_lock','bottleneck_lock','time_slot')),
  CONSTRAINT chk_reservations_schedule CHECK
    ((reservation_mode = 'time_slot' AND planned_start_at IS NOT NULL
      AND planned_end_at IS NOT NULL AND planned_start_at < planned_end_at) OR
     (reservation_mode <> 'time_slot' AND planned_start_at IS NULL
      AND planned_end_at IS NULL)),
  CONSTRAINT chk_reservations_expiry CHECK (expires_at > created_at),
  CONSTRAINT chk_reservations_state CHECK (state IN
    ('reserved','in_use','released','expired','cancelled'))
) ENGINE=InnoDB COMMENT='병목 통로의 진입 권한과 도크, 작업장, 장비의 독점 또는 시간대별 사용 예약을 관리한다.';

-- [재고] 재고 수량이 변한 모든 근거를 추가만 가능한 원장으로 남긴다.
-- inventory_lots의 현재 수량 갱신과 이 INSERT는 반드시 같은 트랜잭션에서 처리한다.
CREATE TABLE IF NOT EXISTS inventory_moves (
  inventory_move_id    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '재고 변동 이력을 식별하는 자동 증가 번호',
  lot_id               BIGINT UNSIGNED NOT NULL COMMENT '연결된 재고 로트의 내부 식별자',
  job_id               BIGINT UNSIGNED NULL COMMENT '업무를 식별하는 자동 증가 번호',
  job_step_id          BIGINT UNSIGNED NULL COMMENT '업무 실행 단계를 식별하는 자동 증가 번호',
  move_type            VARCHAR(24) NOT NULL COMMENT '입고, 출고, 예약, 해제, 조정 등 재고 변동 종류 코드',
  quantity_delta       INT NOT NULL COMMENT '가용 수량에 더하거나 뺀 변화량',
  quantity_after       INT NOT NULL COMMENT '재고 변동을 반영한 뒤의 가용 수량',
  reserved_delta       INT NOT NULL DEFAULT 0 COMMENT '예약 수량에 더하거나 뺀 변화량',
  reserved_after       INT NOT NULL DEFAULT 0 COMMENT '재고 변동을 반영한 뒤의 예약 수량',
  recorded_by          VARCHAR(96) NOT NULL COMMENT '재고 변동을 확정한 서비스 또는 작업자 식별 값',
  recorded_at          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '재고 변동이 확정되어 기록된 시각',
  note                 VARCHAR(512) NULL COMMENT '재고 변동의 사유를 보충하는 설명',
  PRIMARY KEY (inventory_move_id),
  KEY idx_inventory_moves_lot_at (lot_id, recorded_at),
  KEY idx_inventory_moves_job (job_id),
  CONSTRAINT fk_inventory_moves_lot FOREIGN KEY (lot_id)
    REFERENCES inventory_lots (lot_id),
  CONSTRAINT fk_inventory_moves_job FOREIGN KEY (job_id)
    REFERENCES jobs (job_id),
  CONSTRAINT fk_inventory_moves_step FOREIGN KEY (job_step_id)
    REFERENCES job_steps (job_step_id),
  CONSTRAINT chk_inventory_moves_qty CHECK
    (quantity_after >= 0 AND reserved_after >= 0
      AND reserved_after <= quantity_after),
  CONSTRAINT chk_inventory_moves_type CHECK (move_type IN
    ('inbound','outbound','reservation','reservation_release','adjustment',
     'disposal','cycle_count'))
) ENGINE=InnoDB COMMENT='재고와 예약 수량이 변한 원인, 증감량, 변경 후 수량과 책임 주체를 불변 이력으로 기록한다.';

-- [장비] 장비별 최신 상태를 한 행으로 보관해 관제 화면과 재시작 복구에 사용한다.
-- Pinky는 위치·배터리를, OMX는 관절·카메라·툴 상태를 details에 기록한다.
CREATE TABLE IF NOT EXISTS device_states (
  device_id            VARCHAR(64) NOT NULL COMMENT 'Pinky 또는 OMX 장비를 식별하는 고유 코드',
  observed_at          DATETIME(6) NOT NULL COMMENT '장비 상태가 실제로 관측된 시각',
  state                VARCHAR(24) NOT NULL COMMENT '장비가 보고한 현재 동작 상태 코드',
  health               VARCHAR(16) NOT NULL DEFAULT 'ok' COMMENT '장비의 정상, 경고, 오류 또는 통신 두절 건강 상태 코드',
  current_job_step_id  BIGINT UNSIGNED NULL COMMENT '장비가 현재 실행 중이라고 보고한 업무 단계 식별자',
  pose_x               DOUBLE NULL COMMENT '지도 좌표계 기준 X 좌표이며 단위는 m',
  pose_y               DOUBLE NULL COMMENT '지도 좌표계 기준 Y 좌표이며 단위는 m',
  pose_yaw             DOUBLE NULL COMMENT '지도 좌표계 기준 회전각이며 단위는 rad',
  battery_pct          DECIMAL(5,2) NULL COMMENT '장비가 보고한 배터리 잔량 백분율',
  progress             DECIMAL(5,4) NULL COMMENT '현재 업무 단계의 진행률이며 0 이상 1 이하로 저장',
  details              JSON NULL COMMENT '장비별 추가 상태와 진단 값을 저장하는 JSON 객체',
  PRIMARY KEY (device_id),
  KEY idx_device_states_step (current_job_step_id),
  CONSTRAINT fk_device_states_device FOREIGN KEY (device_id)
    REFERENCES devices (device_id) ON DELETE CASCADE,
  CONSTRAINT fk_device_states_step FOREIGN KEY (current_job_step_id)
    REFERENCES job_steps (job_step_id) ON DELETE SET NULL,
  CONSTRAINT chk_device_states_state CHECK (state IN
    ('idle','moving','docking','working','waiting','charging','blocked',
     'error','estop','offline','maintenance')),
  CONSTRAINT chk_device_states_health CHECK (health IN
    ('ok','warning','fault','safety_hold')),
  CONSTRAINT chk_device_states_battery CHECK
    (battery_pct IS NULL OR (battery_pct >= 0 AND battery_pct <= 100)),
  CONSTRAINT chk_device_states_progress CHECK
    (progress IS NULL OR (progress >= 0 AND progress <= 1))
) ENGINE=InnoDB COMMENT='장비별 최신 heartbeat, 위치, 배터리, 진행률, 건강 상태와 현재 실행 단계를 관리한다.';

-- [연동] RMF 배차, Pinky/OMX 명령, 장비 응답을 모두 담는 내구성 있는 메시지 큐다.
-- inbound/outbound와 idempotency_key를 함께 기록해 재전송 시 중복 실행을 막는다.
CREATE TABLE IF NOT EXISTS integration_messages (
  message_id           CHAR(36) NOT NULL COMMENT '시스템 간 메시지를 중복 없이 식별하는 UUID',
  direction            VARCHAR(8) NOT NULL COMMENT '메시지의 수신 inbound 또는 송신 outbound 방향 코드',
  channel              VARCHAR(16) NOT NULL COMMENT '메시지가 통신하는 rmf, pinky 또는 omx 채널 코드',
  device_id            VARCHAR(64) NULL COMMENT 'Pinky 또는 OMX 장비를 식별하는 고유 코드',
  job_step_id          BIGINT UNSIGNED NULL COMMENT '업무 실행 단계를 식별하는 자동 증가 번호',
  message_type         VARCHAR(64) NOT NULL COMMENT '명령, 상태 또는 응답의 계약 종류를 나타내는 코드',
  idempotency_key      VARCHAR(160) NOT NULL COMMENT '같은 요청의 중복 실행을 방지하는 업무 멱등 키',
  external_reference   VARCHAR(160) NULL COMMENT '외부 시스템의 요청이나 작업과 연결하는 참조 값',
  state                VARCHAR(16) NOT NULL DEFAULT 'pending' COMMENT '메시지의 pending, sent, acknowledged, failed 또는 dead 상태',
  attempts             SMALLINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '메시지 전송을 시도한 누적 횟수',
  next_attempt_at      DATETIME(6) NULL COMMENT '실패한 메시지를 다음에 재전송할 예정 시각',
  payload              JSON NOT NULL COMMENT '연동 메시지 또는 운영 이벤트의 원본 데이터를 담은 JSON 객체',
  last_error           VARCHAR(512) NULL COMMENT '가장 최근 메시지 전송 실패의 원인',
  created_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '해당 레코드가 데이터베이스에 생성된 시각',
  sent_at              DATETIME(6) NULL COMMENT '메시지가 외부 채널로 전송된 시각',
  acknowledged_at      DATETIME(6) NULL COMMENT '안전 사건 또는 메시지를 인지했다고 확정한 시각',
  PRIMARY KEY (message_id),
  UNIQUE KEY uq_messages_dedupe (direction, channel, idempotency_key),
  KEY idx_messages_delivery (direction, state, next_attempt_at, created_at),
  KEY idx_messages_step (job_step_id),
  CONSTRAINT fk_messages_device FOREIGN KEY (device_id)
    REFERENCES devices (device_id),
  CONSTRAINT fk_messages_step FOREIGN KEY (job_step_id)
    REFERENCES job_steps (job_step_id) ON DELETE SET NULL,
  CONSTRAINT chk_messages_direction CHECK (direction IN ('inbound','outbound')),
  CONSTRAINT chk_messages_channel CHECK (channel IN ('rmf','pinky','omx')),
  CONSTRAINT chk_messages_state CHECK (state IN
    ('pending','sent','acknowledged','completed','failed','dead_letter'))
) ENGINE=InnoDB COMMENT='RMF, Pinky, OMX와 주고받는 명령과 응답의 멱등 처리, 재전송, 전송 완료 상태를 관리한다.';

-- [운영·AI·안전] 현재 진행 중인 안전 사고를 관리한다.
-- 단순 로그와 달리 active 상태·영향 위치·해제 승인자를 가지며, FMS가 해당 구역을
-- 차단하고 RMF 재계획 또는 정지를 요청하는 기준이 된다.
CREATE TABLE IF NOT EXISTS incidents (
  incident_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '안전 사건을 식별하는 자동 증가 번호',
  incident_code        VARCHAR(64) NOT NULL COMMENT '운영 화면과 보고서에서 사용하는 안전 사건 고유 코드',
  incident_type        VARCHAR(32) NOT NULL COMMENT '사람, 낙상, 충돌 위험, 비상 정지 등 사건 종류 코드',
  severity             VARCHAR(16) NOT NULL COMMENT '사건 또는 이벤트의 영향 수준을 나타내는 코드',
  state                VARCHAR(24) NOT NULL DEFAULT 'active' COMMENT '안전 사건의 open, acknowledged, mitigating, resolved 또는 closed 상태',
  location_id          BIGINT UNSIGNED NULL COMMENT '연결된 운영 위치의 내부 식별자',
  geometry             JSON NULL COMMENT '안전 사건이 영향을 주는 점 또는 구역을 표현한 JSON 공간 정보',
  description          VARCHAR(512) NOT NULL COMMENT '안전 사건의 원인과 상황을 운영자가 이해할 수 있게 기록한 설명',
  raised_by_worker_id  VARCHAR(64) NULL COMMENT '안전 사건을 수동으로 등록한 작업자 식별자',
  acknowledged_by_worker_id VARCHAR(64) NULL COMMENT '안전 사건을 인지 처리한 작업자의 식별자',
  resolved_by_worker_id VARCHAR(64) NULL COMMENT '안전 사건을 최종 해소 처리한 작업자 식별자',
  raised_at            DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '안전 사건이 최초로 발생하거나 등록된 시각',
  acknowledged_at      DATETIME(6) NULL COMMENT '안전 사건 또는 메시지를 인지했다고 확정한 시각',
  resolved_at          DATETIME(6) NULL COMMENT '안전 사건의 원인이 제거되어 해소된 시각',
  context              JSON NULL COMMENT '센서 관측과 대응 절차 등 안전 사건의 추가 정보를 저장하는 JSON 객체',
  PRIMARY KEY (incident_id),
  UNIQUE KEY uq_incidents_code (incident_code),
  KEY idx_incidents_active (state, severity, raised_at),
  KEY idx_incidents_location (location_id, state),
  CONSTRAINT fk_incidents_location FOREIGN KEY (location_id)
    REFERENCES locations (location_id),
  CONSTRAINT fk_incidents_raised_by FOREIGN KEY (raised_by_worker_id)
    REFERENCES workers (worker_id),
  CONSTRAINT fk_incidents_acknowledged_by FOREIGN KEY (acknowledged_by_worker_id)
    REFERENCES workers (worker_id),
  CONSTRAINT fk_incidents_resolved_by FOREIGN KEY (resolved_by_worker_id)
    REFERENCES workers (worker_id),
  CONSTRAINT chk_incidents_type CHECK (incident_type IN
    ('worker_intrusion','worker_emergency','estop','spill','blocked_path',
     'fire','power_cut','device_fault')),
  CONSTRAINT chk_incidents_severity CHECK (severity IN
    ('info','warning','serious','critical')),
  CONSTRAINT chk_incidents_state CHECK (state IN
    ('active','acknowledged','resolved','cancelled'))
) ENGINE=InnoDB COMMENT='사람 감지, 낙상 후보, 충돌 위험, 비상 정지 등 안전 사건의 인지부터 해소까지를 관리한다.';

-- [운영·AI·안전] 작업·안전·VLM·RL 판단을 시간 순서대로 추가만 가능한 로그로 남긴다.
-- VLM/RL 제안은 여기 기록한 뒤 Safety Supervisor가 승인한 허용된 복구 행동만 실행한다.
CREATE TABLE IF NOT EXISTS operation_events (
  event_id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '운영 이벤트를 내부에서 식별하는 자동 증가 번호',
  event_uuid           CHAR(36) NOT NULL COMMENT '시스템 간 중복 없이 운영 이벤트를 식별하는 UUID',
  occurred_at          DATETIME(6) NOT NULL COMMENT '운영 이벤트가 실제로 발생한 시각',
  actor_worker_id      VARCHAR(64) NULL COMMENT '운영 이벤트의 사용자 조치를 수행한 작업자 식별자',
  device_id            VARCHAR(64) NULL COMMENT 'Pinky 또는 OMX 장비를 식별하는 고유 코드',
  job_id               BIGINT UNSIGNED NULL COMMENT '업무를 식별하는 자동 증가 번호',
  job_step_id          BIGINT UNSIGNED NULL COMMENT '업무 실행 단계를 식별하는 자동 증가 번호',
  incident_id          BIGINT UNSIGNED NULL COMMENT '안전 사건을 식별하는 자동 증가 번호',
  severity             VARCHAR(16) NOT NULL DEFAULT 'info' COMMENT '사건 또는 이벤트의 영향 수준을 나타내는 코드',
  category             VARCHAR(24) NOT NULL COMMENT '운영 이벤트가 속한 기능 영역을 구분하는 코드 값',
  event_type           VARCHAR(96) NOT NULL COMMENT '발생한 운영 이벤트의 세부 종류를 나타내는 코드',
  message              VARCHAR(512) NULL COMMENT '운영자가 이벤트를 이해할 수 있도록 기록한 요약 메시지',
  model_name           VARCHAR(128) NULL COMMENT '판단 또는 산출물 생성에 사용한 모델 이름',
  model_version        VARCHAR(128) NULL COMMENT '판단 또는 산출물 생성에 사용한 모델 버전',
  confidence           DECIMAL(6,5) NULL COMMENT '모델 판단의 신뢰도 값이며 0 이상 1 이하로 저장',
  safety_decision      VARCHAR(16) NULL COMMENT '모델 제안에 대한 안전 계층의 승인, 거부 또는 보류 결정 코드',
  payload              JSON NULL COMMENT '이벤트 종류별 상세 관측과 판단 근거를 저장하는 JSON 객체',
  PRIMARY KEY (event_id),
  UNIQUE KEY uq_operation_events_uuid (event_uuid),
  KEY idx_events_occurred_at (occurred_at DESC),
  KEY idx_events_actor_at (actor_worker_id, occurred_at),
  KEY idx_events_device_at (device_id, occurred_at),
  KEY idx_events_job_at (job_id, occurred_at),
  KEY idx_events_incident_at (incident_id, occurred_at),
  KEY idx_events_category_at (category, occurred_at),
  CONSTRAINT fk_events_device FOREIGN KEY (device_id)
    REFERENCES devices (device_id),
  CONSTRAINT fk_events_actor FOREIGN KEY (actor_worker_id)
    REFERENCES workers (worker_id),
  CONSTRAINT fk_events_job FOREIGN KEY (job_id)
    REFERENCES jobs (job_id),
  CONSTRAINT fk_events_step FOREIGN KEY (job_step_id)
    REFERENCES job_steps (job_step_id),
  CONSTRAINT fk_events_incident FOREIGN KEY (incident_id)
    REFERENCES incidents (incident_id),
  CONSTRAINT chk_events_severity CHECK (severity IN
    ('debug','info','warning','serious','critical')),
  CONSTRAINT chk_events_category CHECK (category IN
    ('operation','inventory','rmf','omx','vision','policy','safety','system')),
  CONSTRAINT chk_events_safety_decision CHECK (safety_decision IS NULL OR
    safety_decision IN ('approved','denied','stopped','manual_review')),
  CONSTRAINT chk_events_confidence CHECK
    (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
) ENGINE=InnoDB COMMENT='업무, 장비, 안전, 모델 판단과 운영자 조치의 시간순 감사 이벤트를 기록한다.';

-- [학습 원본] 이미지·영상·point cloud·ROS bag·Cyclo episode·데이터셋·모델의
-- 파일 자체가 아니라 위치와 무결성 정보를 관리한다. 원본은 NAS/MinIO/S3에 저장한다.
CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '파일 산출물을 식별하는 자동 증가 번호',
  artifact_type         VARCHAR(24) NOT NULL COMMENT '산출물의 형식을 구분하는 코드 값',
  storage_uri           VARCHAR(1024) NOT NULL COMMENT '산출물 파일이 보관된 객체 저장소 또는 파일 시스템 URI',
  storage_uri_hash      BINARY(32) GENERATED ALWAYS AS
                          (UNHEX(SHA2(storage_uri, 256))) STORED COMMENT '긴 저장 URI의 중복을 검사하기 위해 계산한 이진 해시',
  sha256                CHAR(64) NOT NULL COMMENT '산출물 내용의 무결성을 확인하는 SHA-256 해시',
  mime_type             VARCHAR(128) NULL COMMENT '산출물 파일의 MIME 형식',
  byte_size             BIGINT UNSIGNED NULL COMMENT '산출물 파일의 바이트 단위 크기',
  device_id             VARCHAR(64) NULL COMMENT 'Pinky 또는 OMX 장비를 식별하는 고유 코드',
  job_id                BIGINT UNSIGNED NULL COMMENT '업무를 식별하는 자동 증가 번호',
  job_step_id           BIGINT UNSIGNED NULL COMMENT '업무 실행 단계를 식별하는 자동 증가 번호',
  event_id              BIGINT UNSIGNED NULL COMMENT '운영 이벤트를 내부에서 식별하는 자동 증가 번호',
  model_name            VARCHAR(128) NULL COMMENT '판단 또는 산출물 생성에 사용한 모델 이름',
  model_version         VARCHAR(128) NULL COMMENT '판단 또는 산출물 생성에 사용한 모델 버전',
  metadata              JSON NULL COMMENT '코덱, 해상도, dataset split 등 산출물별 확장 정보를 저장하는 JSON 객체',
  captured_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '산출물의 원본 데이터가 취득된 시각',
  PRIMARY KEY (artifact_id),
  UNIQUE KEY uq_artifacts_sha_uri (sha256, storage_uri_hash),
  KEY idx_artifacts_step (job_step_id),
  KEY idx_artifacts_event (event_id),
  KEY idx_artifacts_model (model_name, model_version),
  CONSTRAINT fk_artifacts_device FOREIGN KEY (device_id)
    REFERENCES devices (device_id),
  CONSTRAINT fk_artifacts_job FOREIGN KEY (job_id)
    REFERENCES jobs (job_id),
  CONSTRAINT fk_artifacts_step FOREIGN KEY (job_step_id)
    REFERENCES job_steps (job_step_id),
  CONSTRAINT fk_artifacts_event FOREIGN KEY (event_id)
    REFERENCES operation_events (event_id),
  CONSTRAINT chk_artifacts_type CHECK (artifact_type IN
    ('image','video','pointcloud','rosbag','episode','dataset','model','report'))
) ENGINE=InnoDB COMMENT='영상, 이미지, rosbag, episode, dataset, model과 보고서의 저장 위치와 무결성 정보를 관리한다.';

-- [복구 Reference Memory] safe_node의 좌표를 복제하지 않고 복구 목표로서의
-- 사용 가능 상태와 신뢰도만 관리한다. location_type = 'safe_node' 검증과 지도
-- revision 일치 검증은 다른 행 조회가 필요한 규칙이므로 Gateway가 담당한다.
CREATE TABLE IF NOT EXISTS location_recovery_profiles (
  reference_node_uuid    CHAR(36) NOT NULL COMMENT '복구 목표로 사용할 안전 노드를 식별하는 UUID',
  location_id            BIGINT UNSIGNED NOT NULL COMMENT '연결된 운영 위치의 내부 식별자',
  map_revision           VARCHAR(128) NOT NULL COMMENT '좌표와 feature가 유효한 지도 버전 식별자',
  recovery_roles         JSON NOT NULL COMMENT '안전 노드가 지원하는 wait, retreat, detour, rejoin 역할의 JSON 배열',
  availability_status    VARCHAR(16) NOT NULL DEFAULT 'active' COMMENT '복구 기준 노드의 현재 사용 가능 상태 코드',
  reliability_alpha      DECIMAL(12,4) NOT NULL DEFAULT 1.0000 COMMENT '복구 노드 성공 신뢰도의 베타 분포 alpha 누적 값',
  reliability_beta       DECIMAL(12,4) NOT NULL DEFAULT 1.0000 COMMENT '복구 노드 실패 신뢰도의 베타 분포 beta 누적 값',
  last_verified_at       DATETIME(6) NULL COMMENT '복구 기준 노드의 위치와 안전성을 마지막으로 검증한 시각',
  last_outcome_at        DATETIME(6) NULL COMMENT '복구 기준 노드가 실제 결과에 사용된 가장 최근 시각',
  reviewed_by_worker_id  VARCHAR(64) NULL COMMENT '복구 기준 노드의 상태를 마지막으로 검토한 작업자 식별자',
  revision               BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '동시 수정 충돌을 탐지하기 위한 낙관적 잠금 버전',
  notes                  VARCHAR(1024) NULL COMMENT '복구 기준 노드의 검토 결과와 주의사항',
  created_at             DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '해당 레코드가 데이터베이스에 생성된 시각',
  updated_at             DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                           ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '해당 레코드가 마지막으로 수정된 시각',
  PRIMARY KEY (reference_node_uuid),
  UNIQUE KEY uq_recovery_profiles_location (location_id),
  KEY idx_recovery_profiles_lookup
    (map_revision, availability_status, last_verified_at),
  KEY idx_recovery_profiles_reviewer (reviewed_by_worker_id),
  CONSTRAINT fk_recovery_profiles_location FOREIGN KEY (location_id)
    REFERENCES locations (location_id),
  CONSTRAINT fk_recovery_profiles_reviewer FOREIGN KEY (reviewed_by_worker_id)
    REFERENCES workers (worker_id),
  CONSTRAINT chk_recovery_profiles_map_revision CHECK
    (CHAR_LENGTH(TRIM(map_revision)) > 0),
  CONSTRAINT chk_recovery_profiles_roles CHECK
    (JSON_TYPE(recovery_roles) = 'ARRAY'
      AND JSON_LENGTH(recovery_roles) > 0
      AND JSON_CONTAINS(
        JSON_ARRAY('wait','retreat','detour','rejoin'), recovery_roles
      )),
  CONSTRAINT chk_recovery_profiles_status CHECK (availability_status IN
    ('active','suspect','quarantined','retired')),
  CONSTRAINT chk_recovery_profiles_reliability CHECK
    (reliability_alpha > 0 AND reliability_beta > 0)
) ENGINE=InnoDB COMMENT='안전 노드별 복구 역할, 사용 가능 상태와 베타 분포 기반 신뢰도를 관리한다.';

-- ============================================================================
-- VLM/RL 복구 경험(Episodic Memory)
--
-- trihouse_fms와 FK를 만들지 않는다. FMS event/job/reference UUID의 존재와
-- map revision 일치는 Gateway가 확인해 두 DB의 백업·복구 수명주기를 분리한다.
-- ============================================================================

CREATE DATABASE IF NOT EXISTS `trihouse_recovery`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `trihouse_recovery`;

-- 복구 trigger부터 성공·중단·실패까지 한 사건과 사용 모델 계보를 저장한다.
CREATE TABLE IF NOT EXISTS recovery_episodes (
  recovery_episode_uuid     CHAR(36) NOT NULL COMMENT '하나의 복구 사건을 시스템 간 고유하게 식별하는 UUID',
  source_event_uuid         CHAR(36) NULL COMMENT '복구 에피소드를 시작시킨 FMS 운영 이벤트 UUID',
  device_id                 VARCHAR(64) NOT NULL COMMENT 'Pinky 또는 OMX 장비를 식별하는 고유 코드',
  fms_job_id                BIGINT UNSIGNED NULL COMMENT '복구 에피소드와 연결된 FMS 업무 식별자이며 물리적 외래 키는 두지 않음',
  fms_job_step_id           BIGINT UNSIGNED NULL COMMENT '복구 에피소드와 연결된 FMS 업무 단계 식별자이며 물리적 외래 키는 두지 않음',
  map_name                  VARCHAR(96) NOT NULL COMMENT 'Open-RMF와 로봇 navigation에서 사용하는 지도 이름',
  map_revision              VARCHAR(128) NOT NULL COMMENT '좌표와 feature가 유효한 지도 버전 식별자',
  trigger_type              VARCHAR(24) NOT NULL COMMENT '복구를 시작시킨 정체, 사람, 저시정 또는 위치 추정 문제 코드',
  vlm_model_name            VARCHAR(128) NULL COMMENT '복구 상황 해석에 사용한 VLM 모델 이름',
  vlm_model_version         VARCHAR(128) NULL COMMENT '복구 상황 해석에 사용한 VLM 모델 버전',
  recovery_policy_name      VARCHAR(128) NOT NULL COMMENT '실행한 복구 정책의 이름',
  recovery_policy_version   VARCHAR(128) NOT NULL COMMENT '실행한 복구 정책의 버전',
  started_at                DATETIME(6) NOT NULL COMMENT '업무, 단계 또는 복구 행동이 실제로 시작된 시각',
  ended_at                  DATETIME(6) NULL COMMENT '복구 에피소드가 성공, 중단 또는 실패로 종료된 시각',
  final_status              VARCHAR(16) NOT NULL DEFAULT 'running' COMMENT '복구 에피소드의 실행 중, 성공, 중단 또는 실패 최종 상태',
  summary                   VARCHAR(1024) NULL COMMENT '복구 에피소드의 원인, 행동과 결과를 요약한 설명',
  created_at                DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '해당 레코드가 데이터베이스에 생성된 시각',
  PRIMARY KEY (recovery_episode_uuid),
  KEY idx_recovery_episodes_source_event (source_event_uuid),
  KEY idx_recovery_episodes_device_started (device_id, started_at),
  KEY idx_recovery_episodes_job (fms_job_id, fms_job_step_id),
  KEY idx_recovery_episodes_export
    (map_name, map_revision, final_status, started_at),
  CONSTRAINT chk_recovery_episodes_map CHECK
    (CHAR_LENGTH(TRIM(map_name)) > 0
      AND CHAR_LENGTH(TRIM(map_revision)) > 0),
  CONSTRAINT chk_recovery_episodes_trigger CHECK (trigger_type IN
    ('blocked','person','low_visibility','localization')),
  CONSTRAINT chk_recovery_episodes_vlm_lineage CHECK
    ((vlm_model_name IS NULL AND vlm_model_version IS NULL) OR
     (vlm_model_name IS NOT NULL AND vlm_model_version IS NOT NULL)),
  CONSTRAINT chk_recovery_episodes_status CHECK (final_status IN
    ('running','succeeded','aborted','failed')),
  CONSTRAINT chk_recovery_episodes_time CHECK
    ((final_status = 'running' AND ended_at IS NULL) OR
     (final_status <> 'running' AND ended_at IS NOT NULL
       AND ended_at >= started_at))
) ENGINE=InnoDB COMMENT='복구 trigger부터 종료까지 하나의 사건과 사용한 VLM 및 복구 정책의 계보를 기록한다.';

-- 실제로 실행한 복구 행동 한 번을 저장한다. SAC replay export의 원본이며,
-- 실행되지 않은 VLM 후보와 Safety 결정은 FMS operation_events에만 남긴다.
CREATE TABLE IF NOT EXISTS recovery_steps (
  recovery_step_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '복구 실행 단계를 식별하는 자동 증가 번호',
  recovery_episode_uuid  CHAR(36) NOT NULL COMMENT '하나의 복구 사건을 시스템 간 고유하게 식별하는 UUID',
  step_no                SMALLINT UNSIGNED NOT NULL COMMENT '같은 업무 또는 에피소드 안에서 실행 순서를 나타내는 번호',
  reference_node_uuid    CHAR(36) NULL COMMENT '행동 목표로 선택한 FMS 복구 기준 노드 UUID이며 물리적 외래 키는 두지 않음',
  action_type            VARCHAR(16) NOT NULL COMMENT '실행할 동작 종류를 나타내는 코드 값',
  target_pose            JSON NULL COMMENT '복구 행동이 목표로 삼은 위치와 방향의 JSON 객체',
  before_state_uri       VARCHAR(1024) NULL COMMENT '행동 전 관측 데이터가 저장된 위치 URI',
  before_state_sha256    CHAR(64) NULL COMMENT '행동 전 관측 파일의 무결성을 확인하는 SHA-256 해시',
  after_state_uri        VARCHAR(1024) NULL COMMENT '행동 후 관측 데이터가 저장된 위치 URI',
  after_state_sha256     CHAR(64) NULL COMMENT '행동 후 관측 파일의 무결성을 확인하는 SHA-256 해시',
  reward_components      JSON NULL COMMENT 'RL 학습용 보상을 항목별로 기록한 JSON 객체',
  outcome_class          VARCHAR(16) NOT NULL COMMENT '복구 결과를 safe, boundary 또는 critical로 구분한 코드',
  execution_status       VARCHAR(16) NOT NULL DEFAULT 'queued' COMMENT '복구 행동의 대기, 실행, 성공, 실패 또는 취소 상태 코드',
  is_terminal            TINYINT(1) NOT NULL DEFAULT 0 COMMENT '해당 복구 행동이 에피소드의 마지막 단계인지 나타내는 값',
  started_at             DATETIME(6) NOT NULL COMMENT '업무, 단계 또는 복구 행동이 실제로 시작된 시각',
  completed_at           DATETIME(6) NULL COMMENT '업무, 단계 또는 복구 행동이 완료된 시각',
  created_at             DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '해당 레코드가 데이터베이스에 생성된 시각',
  PRIMARY KEY (recovery_step_id),
  UNIQUE KEY uq_recovery_steps_order (recovery_episode_uuid, step_no),
  KEY idx_recovery_steps_reference (reference_node_uuid),
  KEY idx_recovery_steps_export
    (outcome_class, execution_status, completed_at),
  CONSTRAINT fk_recovery_steps_episode FOREIGN KEY (recovery_episode_uuid)
    REFERENCES recovery_episodes (recovery_episode_uuid) ON DELETE CASCADE,
  CONSTRAINT chk_recovery_steps_number CHECK (step_no > 0),
  CONSTRAINT chk_recovery_steps_action CHECK (action_type IN
    ('wait','retreat','detour','rejoin','stop')),
  CONSTRAINT chk_recovery_steps_target_pose CHECK
    (target_pose IS NULL OR JSON_TYPE(target_pose) = 'OBJECT'),
  CONSTRAINT chk_recovery_steps_before_state CHECK
    ((before_state_uri IS NULL AND before_state_sha256 IS NULL) OR
     (before_state_uri IS NOT NULL AND before_state_sha256 IS NOT NULL)),
  CONSTRAINT chk_recovery_steps_after_state CHECK
    ((after_state_uri IS NULL AND after_state_sha256 IS NULL) OR
     (after_state_uri IS NOT NULL AND after_state_sha256 IS NOT NULL)),
  CONSTRAINT chk_recovery_steps_reward CHECK
    (reward_components IS NULL OR JSON_TYPE(reward_components) = 'OBJECT'),
  CONSTRAINT chk_recovery_steps_outcome CHECK (outcome_class IN
    ('safe','boundary','critical')),
  CONSTRAINT chk_recovery_steps_execution CHECK (execution_status IN
    ('queued','running','succeeded','failed','cancelled')),
  CONSTRAINT chk_recovery_steps_terminal CHECK (is_terminal IN (0, 1)),
  CONSTRAINT chk_recovery_steps_time CHECK
    ((execution_status IN ('queued','running') AND completed_at IS NULL
      AND is_terminal = 0) OR
     (execution_status IN ('succeeded','failed','cancelled')
      AND completed_at IS NOT NULL AND completed_at >= started_at))
) ENGINE=InnoDB COMMENT='복구 에피소드에서 실제 실행한 행동, 전후 관측, 보상, 결과와 완료 상태를 순서대로 기록한다.';
