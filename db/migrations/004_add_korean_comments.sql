-- Add Korean table and column comments to an existing v4 database.
-- This migration changes metadata only and does not delete application data.

ALTER TABLE `trihouse_fms`.`locations`
  COMMENT = '창고의 랙, 슬롯, 도크, 충전기, 작업장, 안전 노드와 RMF waypoint를 통합 관리한다.';

ALTER TABLE `trihouse_fms`.`locations`
  MODIFY COLUMN location_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '연결된 운영 위치의 내부 식별자',
  MODIFY COLUMN parent_location_id BIGINT UNSIGNED NULL COMMENT '위치 계층에서 바로 상위에 있는 운영 위치 식별자',
  MODIFY COLUMN location_code      VARCHAR(96) NOT NULL COMMENT '운영 화면과 외부 연동에서 사용하는 위치 고유 코드',
  MODIFY COLUMN name               VARCHAR(160) NULL COMMENT '운영자 화면에 표시할 위치 이름',
  MODIFY COLUMN location_type      VARCHAR(32) NOT NULL COMMENT '랙, 슬롯, waypoint, 도크, 충전기, 작업장 등 위치 종류 코드',
  MODIFY COLUMN zone_code          VARCHAR(64) NULL COMMENT '창고 운영 구역을 식별하는 코드',
  MODIFY COLUMN temperature_zone   VARCHAR(16) NULL COMMENT '상온 ambient, 냉장 chilled 또는 냉동 frozen 보관 구역 코드',
  MODIFY COLUMN map_name           VARCHAR(96) NULL COMMENT 'Open-RMF와 로봇 navigation에서 사용하는 지도 이름',
  MODIFY COLUMN rmf_waypoint_name  VARCHAR(128) NULL COMMENT 'Open-RMF navigation graph의 waypoint 이름',
  MODIFY COLUMN pose_x             DOUBLE NULL COMMENT '지도 좌표계 기준 X 좌표이며 단위는 m',
  MODIFY COLUMN pose_y             DOUBLE NULL COMMENT '지도 좌표계 기준 Y 좌표이며 단위는 m',
  MODIFY COLUMN pose_yaw           DOUBLE NULL COMMENT '지도 좌표계 기준 회전각이며 단위는 rad',
  MODIFY COLUMN state              VARCHAR(24) NOT NULL DEFAULT 'available' COMMENT '위치의 현재 운영 상태이며 available, reserved, occupied, blocked, maintenance 중 하나',
  MODIFY COLUMN metadata           JSON NULL COMMENT '위치별 확장 속성과 외부 연동 값을 저장하는 JSON 객체';

ALTER TABLE `trihouse_fms`.`map_features`
  COMMENT = '지도 revision별 표식, 정적 장애물, 병목, 출입문과 진입 금지 구역의 공간 정보를 관리한다.';

ALTER TABLE `trihouse_fms`.`map_features`
  MODIFY COLUMN feature_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '지도 feature를 식별하는 자동 증가 번호',
  MODIFY COLUMN map_name            VARCHAR(96) NOT NULL COMMENT 'Open-RMF와 로봇 navigation에서 사용하는 지도 이름',
  MODIFY COLUMN map_revision        VARCHAR(128) NOT NULL COMMENT '좌표와 feature가 유효한 지도 버전 식별자',
  MODIFY COLUMN feature_code        VARCHAR(128) NOT NULL COMMENT '지도 revision 안에서 feature를 식별하는 업무 코드',
  MODIFY COLUMN feature_type        VARCHAR(24) NOT NULL COMMENT '표식, 정적 장애물, 병목, 출입문 또는 진입 금지 구역 코드',
  MODIFY COLUMN location_id         BIGINT UNSIGNED NULL COMMENT '연결된 운영 위치의 내부 식별자',
  MODIFY COLUMN marker_code         INT UNSIGNED NULL COMMENT 'QR 또는 ArUco 표식에서 읽는 숫자 코드',
  MODIFY COLUMN geometry            JSON NOT NULL COMMENT '지도 좌표계의 점, 선 또는 다각형 공간 정보를 담은 JSON 객체',
  MODIFY COLUMN properties          JSON NULL COMMENT '지도 feature의 운영 규칙과 표시 속성을 담은 JSON 객체',
  MODIFY COLUMN active              TINYINT(1) NOT NULL DEFAULT 1 COMMENT '해당 지도 revision에서 feature를 운영 규칙에 사용할지 나타내는 값';

ALTER TABLE `trihouse_fms`.`workers`
  COMMENT = '관제 요청, 수동 복구와 안전 해제에 대한 책임을 식별할 작업자 계정과 권한 범위를 관리한다.';

ALTER TABLE `trihouse_fms`.`workers`
  MODIFY COLUMN worker_id          VARCHAR(64) NOT NULL COMMENT '작업자 계정을 식별하는 내부 고유 값',
  MODIFY COLUMN worker_code        VARCHAR(64) NOT NULL COMMENT '운영 화면과 인증 연동에서 사용하는 작업자 고유 코드',
  MODIFY COLUMN name               VARCHAR(128) NOT NULL COMMENT '운영자 화면과 감사 기록에 표시할 작업자 이름',
  MODIFY COLUMN role               VARCHAR(32) NOT NULL COMMENT '작업자의 운영 권한 역할 코드',
  MODIFY COLUMN external_auth_id   VARCHAR(128) NULL COMMENT 'SSO 또는 외부 인증 시스템에서 사용하는 작업자 식별자',
  MODIFY COLUMN allowed_zones      JSON NULL COMMENT '작업자가 접근하거나 조작할 수 있는 구역 코드의 JSON 배열',
  MODIFY COLUMN active             TINYINT(1) NOT NULL DEFAULT 1 COMMENT '작업자 계정이 현재 업무 요청과 승인에 참여할 수 있는지 나타내는 값',
  MODIFY COLUMN registered_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '작업자 또는 장비가 운영 시스템에 등록된 시각',
  MODIFY COLUMN retired_at         DATETIME(6) NULL COMMENT '작업자 또는 장비를 운영 대상에서 제외한 시각';

ALTER TABLE `trihouse_fms`.`devices`
  COMMENT = 'Pinky 주행로봇과 OMX 로봇팔의 모델, 소속, 위치, 제어 모드와 기능을 관리한다.';

ALTER TABLE `trihouse_fms`.`devices`
  MODIFY COLUMN device_id            VARCHAR(64) NOT NULL COMMENT 'Pinky 또는 OMX 장비를 식별하는 고유 코드',
  MODIFY COLUMN device_type          VARCHAR(16) NOT NULL COMMENT '장비를 주행로봇 mobile 또는 로봇팔 arm으로 구분하는 코드',
  MODIFY COLUMN name                 VARCHAR(128) NOT NULL COMMENT '운영자 화면에 표시할 장비 이름',
  MODIFY COLUMN model                VARCHAR(96) NOT NULL COMMENT '장비 제조사 또는 제품 모델 이름',
  MODIFY COLUMN fleet_name           VARCHAR(96) NULL COMMENT '주행로봇이 소속된 Open-RMF fleet 이름',
  MODIFY COLUMN home_location_id     BIGINT UNSIGNED NULL COMMENT '장비가 대기하거나 복귀할 기본 운영 위치 식별자',
  MODIFY COLUMN current_location_id  BIGINT UNSIGNED NULL COMMENT '장비가 현재 위치한 것으로 확정된 운영 위치 식별자',
  MODIFY COLUMN control_mode         VARCHAR(24) NOT NULL DEFAULT 'automatic' COMMENT '장비의 자동, 수동, 오프라인, 정비 또는 안전 정지 제어 모드',
  MODIFY COLUMN active               TINYINT(1) NOT NULL DEFAULT 1 COMMENT '장비가 현재 배차와 작업 할당 대상인지 나타내는 값',
  MODIFY COLUMN capabilities         JSON NULL COMMENT '장비가 지원하는 동작과 기능을 표현한 JSON 객체',
  MODIFY COLUMN registered_at        DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '작업자 또는 장비가 운영 시스템에 등록된 시각',
  MODIFY COLUMN retired_at           DATETIME(6) NULL COMMENT '작업자 또는 장비를 운영 대상에서 제외한 시각';

ALTER TABLE `trihouse_fms`.`inventory_lots`
  COMMENT = '상품 로트별 보관 위치, 유통기한, 가용 수량, 예약 수량과 보관 상태를 관리한다.';

ALTER TABLE `trihouse_fms`.`inventory_lots`
  MODIFY COLUMN lot_id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '연결된 재고 로트의 내부 식별자',
  MODIFY COLUMN product_code       VARCHAR(96) NOT NULL COMMENT '상품 종류를 식별하는 업무 코드',
  MODIFY COLUMN lot_code           VARCHAR(128) NOT NULL COMMENT '입고 단위와 추적에 사용하는 재고 로트 고유 코드',
  MODIFY COLUMN item_name          VARCHAR(160) NULL COMMENT '운영자 화면에 표시할 상품 이름',
  MODIFY COLUMN temperature_zone   VARCHAR(16) NOT NULL COMMENT '상온 ambient, 냉장 chilled 또는 냉동 frozen 보관 구역 코드',
  MODIFY COLUMN location_id        BIGINT UNSIGNED NULL COMMENT '연결된 운영 위치의 내부 식별자',
  MODIFY COLUMN expiry_date        DATE NOT NULL COMMENT '재고 로트의 유통기한 날짜',
  MODIFY COLUMN unit_weight_kg     DECIMAL(10,3) NULL COMMENT '상품 한 단위의 kg 기준 무게',
  MODIFY COLUMN available_qty      INT NOT NULL DEFAULT 0 COMMENT '현재 로트에서 물리적으로 보유한 전체 수량',
  MODIFY COLUMN reserved_qty       INT NOT NULL DEFAULT 0 COMMENT '출고 등의 업무를 위해 선점된 수량',
  MODIFY COLUMN state              VARCHAR(24) NOT NULL DEFAULT 'stored' COMMENT '재고 로트의 입고 대기, 보관, 보류, 소진, 만료 또는 손상 상태',
  MODIFY COLUMN received_at        DATETIME(6) NULL COMMENT '재고 로트의 입고가 완료된 시각',
  MODIFY COLUMN updated_at         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                         ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '해당 레코드가 마지막으로 수정된 시각';

ALTER TABLE `trihouse_fms`.`jobs`
  COMMENT = '입고, 출고, 이동, 보충, 폐기, 복구와 비상 대응 업무의 전체 수명주기를 관리한다.';

ALTER TABLE `trihouse_fms`.`jobs`
  MODIFY COLUMN job_id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '업무를 식별하는 자동 증가 번호',
  MODIFY COLUMN parent_job_id        BIGINT UNSIGNED NULL COMMENT '하위 업무를 생성한 상위 업무의 식별자',
  MODIFY COLUMN job_code             VARCHAR(64) NOT NULL COMMENT '운영 화면과 외부 연동에서 사용하는 업무 고유 코드',
  MODIFY COLUMN operation_type       VARCHAR(24) NOT NULL COMMENT '입고, 출고, 이동, 보충, 폐기, 복구 또는 비상 업무 종류 코드',
  MODIFY COLUMN priority             VARCHAR(16) NOT NULL DEFAULT 'normal' COMMENT '업무의 critical, high, normal 또는 low 우선순위 코드',
  MODIFY COLUMN priority_rank        TINYINT UNSIGNED GENERATED ALWAYS AS (
      CASE priority
        WHEN 'critical' THEN 1
        WHEN 'high' THEN 2
        WHEN 'normal' THEN 3
        WHEN 'low' THEN 4
      END
    ) STORED COMMENT '우선순위 정렬을 위해 자동 계산되는 숫자 값',
  MODIFY COLUMN state                VARCHAR(24) NOT NULL DEFAULT 'pending' COMMENT '업무의 대기부터 계획, 실행, 완료, 실패, 취소와 안전 보류까지의 상태',
  MODIFY COLUMN revision             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '동시 수정 충돌을 탐지하기 위한 낙관적 잠금 버전',
  MODIFY COLUMN requested_by         VARCHAR(64) NULL COMMENT '업무 생성을 요청한 작업자의 식별자',
  MODIFY COLUMN external_reference   VARCHAR(128) NULL COMMENT '외부 시스템의 요청이나 작업과 연결하는 참조 값',
  MODIFY COLUMN source_location_id   BIGINT UNSIGNED NULL COMMENT '업무가 시작되는 운영 위치 식별자',
  MODIFY COLUMN destination_location_id BIGINT UNSIGNED NULL COMMENT '업무가 최종적으로 도착해야 하는 운영 위치 식별자',
  MODIFY COLUMN due_at               DATETIME(6) NULL COMMENT '업무 완료가 요구되는 기한 시각',
  MODIFY COLUMN assigned_mobile_id   VARCHAR(64) NULL COMMENT '업무에 배정된 Pinky 주행로봇의 장비 식별자',
  MODIFY COLUMN failure_reason       VARCHAR(512) NULL COMMENT '업무 또는 실행 단계가 실패한 구체적인 원인',
  MODIFY COLUMN context              JSON NULL COMMENT '업무 생성 원인과 외부 요청의 확장 맥락을 저장하는 JSON 객체',
  MODIFY COLUMN created_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '해당 레코드가 데이터베이스에 생성된 시각',
  MODIFY COLUMN started_at           DATETIME(6) NULL COMMENT '업무, 단계 또는 복구 행동이 실제로 시작된 시각',
  MODIFY COLUMN completed_at         DATETIME(6) NULL COMMENT '업무, 단계 또는 복구 행동이 완료된 시각';

ALTER TABLE `trihouse_fms`.`job_items`
  COMMENT = '업무에 포함된 상품, 요청 수량, 완료 수량, 배정 로트와 검수 상태를 관리한다.';

ALTER TABLE `trihouse_fms`.`job_items`
  MODIFY COLUMN job_item_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '업무 품목을 식별하는 자동 증가 번호',
  MODIFY COLUMN job_id              BIGINT UNSIGNED NOT NULL COMMENT '업무를 식별하는 자동 증가 번호',
  MODIFY COLUMN product_code        VARCHAR(96) NOT NULL COMMENT '상품 종류를 식별하는 업무 코드',
  MODIFY COLUMN requested_qty       INT NOT NULL COMMENT '업무에서 처리하도록 요청한 상품 수량',
  MODIFY COLUMN completed_qty       INT NOT NULL DEFAULT 0 COMMENT '업무 품목 중 실제 처리가 완료된 수량',
  MODIFY COLUMN lot_id              BIGINT UNSIGNED NULL COMMENT '연결된 재고 로트의 내부 식별자',
  MODIFY COLUMN handling_unit_code  VARCHAR(128) NULL COMMENT '바구니, 박스 또는 팔레트 등 취급 단위의 식별 코드',
  MODIFY COLUMN verification_state  VARCHAR(24) NOT NULL DEFAULT 'pending' COMMENT '업무 품목의 미검수, 일치, 불일치 또는 수동 검토 상태 코드',
  MODIFY COLUMN metadata            JSON NULL COMMENT '업무 품목별 검수와 외부 주문의 확장 값을 저장하는 JSON 객체';

ALTER TABLE `trihouse_fms`.`job_steps`
  COMMENT = '업무를 Pinky 이동, OMX 조작, 검수와 인계 단위의 순서 있는 실행 단계로 관리한다.';

ALTER TABLE `trihouse_fms`.`job_steps`
  MODIFY COLUMN job_step_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '업무 실행 단계를 식별하는 자동 증가 번호',
  MODIFY COLUMN job_id               BIGINT UNSIGNED NOT NULL COMMENT '업무를 식별하는 자동 증가 번호',
  MODIFY COLUMN step_no              SMALLINT UNSIGNED NOT NULL COMMENT '같은 업무 또는 에피소드 안에서 실행 순서를 나타내는 번호',
  MODIFY COLUMN executor_type        VARCHAR(16) NOT NULL COMMENT '업무 단계의 실행 주체를 mobile, arm 또는 fms로 구분하는 코드',
  MODIFY COLUMN assigned_device_id   VARCHAR(64) NULL COMMENT '업무 단계를 실행하도록 배정된 장비 식별자',
  MODIFY COLUMN action_type          VARCHAR(32) NOT NULL COMMENT '실행할 동작 종류를 나타내는 코드 값',
  MODIFY COLUMN target_location_id   BIGINT UNSIGNED NULL COMMENT '업무 단계가 이동하거나 조작할 목표 운영 위치 식별자',
  MODIFY COLUMN state                VARCHAR(24) NOT NULL DEFAULT 'pending' COMMENT '업무 단계의 대기, 큐 등록, 실행, 성공, 실패, 보류 또는 취소 상태',
  MODIFY COLUMN rmf_task_id          VARCHAR(128) NULL COMMENT 'Open-RMF에서 발급한 이동 작업 식별자',
  MODIFY COLUMN policy_name          VARCHAR(128) NULL COMMENT '업무 단계 판단에 사용한 정책 이름',
  MODIFY COLUMN policy_version       VARCHAR(128) NULL COMMENT '업무 단계 판단에 사용한 정책 버전',
  MODIFY COLUMN retry_count          SMALLINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '업무 단계 실행을 다시 시도한 누적 횟수',
  MODIFY COLUMN failure_reason       VARCHAR(512) NULL COMMENT '업무 또는 실행 단계가 실패한 구체적인 원인',
  MODIFY COLUMN input                JSON NULL COMMENT '업무 단계를 실행할 때 전달한 입력 값을 저장하는 JSON 객체',
  MODIFY COLUMN result               JSON NULL COMMENT '업무 단계 실행 후 반환된 결과를 저장하는 JSON 객체',
  MODIFY COLUMN started_at           DATETIME(6) NULL COMMENT '업무, 단계 또는 복구 행동이 실제로 시작된 시각',
  MODIFY COLUMN completed_at         DATETIME(6) NULL COMMENT '업무, 단계 또는 복구 행동이 완료된 시각';

ALTER TABLE `trihouse_fms`.`reservations`
  COMMENT = '병목 통로의 진입 권한과 도크, 작업장, 장비의 독점 또는 시간대별 사용 예약을 관리한다.';

ALTER TABLE `trihouse_fms`.`reservations`
  MODIFY COLUMN reservation_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '자원 예약을 식별하는 자동 증가 번호',
  MODIFY COLUMN job_id               BIGINT UNSIGNED NOT NULL COMMENT '업무를 식별하는 자동 증가 번호',
  MODIFY COLUMN job_step_id          BIGINT UNSIGNED NULL COMMENT '업무 실행 단계를 식별하는 자동 증가 번호',
  MODIFY COLUMN location_id          BIGINT UNSIGNED NULL COMMENT '연결된 운영 위치의 내부 식별자',
  MODIFY COLUMN device_id            VARCHAR(64) NULL COMMENT 'Pinky 또는 OMX 장비를 식별하는 고유 코드',
  MODIFY COLUMN map_feature_id       BIGINT UNSIGNED NULL COMMENT '병목 잠금과 연결된 지도 feature 식별자',
  MODIFY COLUMN reservation_mode     VARCHAR(24) NOT NULL DEFAULT 'exclusive_lock' COMMENT '독점 잠금, 병목 잠금 또는 시간 예약 방식 코드',
  MODIFY COLUMN state                VARCHAR(16) NOT NULL DEFAULT 'reserved' COMMENT '예약의 reserved, in_use, released, expired 또는 cancelled 상태',
  MODIFY COLUMN planned_start_at     DATETIME(6) NULL COMMENT '예약 자원의 사용을 시작할 예정 시각',
  MODIFY COLUMN planned_end_at       DATETIME(6) NULL COMMENT '예약 자원의 사용을 마칠 예정 시각',
  MODIFY COLUMN entered_at           DATETIME(6) NULL COMMENT '장비가 예약 자원에 실제로 진입한 시각',
  MODIFY COLUMN exited_at            DATETIME(6) NULL COMMENT '장비가 예약 자원에서 실제로 빠져나온 시각',
  MODIFY COLUMN expires_at           DATETIME(6) NOT NULL COMMENT '점유 확인이 없을 때 예약을 자동 만료할 기준 시각',
  MODIFY COLUMN created_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '해당 레코드가 데이터베이스에 생성된 시각',
  MODIFY COLUMN released_at          DATETIME(6) NULL COMMENT '예약 자원이 정상 또는 수동으로 해제된 시각',
  MODIFY COLUMN active_resource_key  VARCHAR(160) GENERATED ALWAYS AS (
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
    ) STORED COMMENT '활성 예약의 자원 중복을 방지하기 위해 계산한 고유 키';

ALTER TABLE `trihouse_fms`.`inventory_moves`
  COMMENT = '재고와 예약 수량이 변한 원인, 증감량, 변경 후 수량과 책임 주체를 불변 이력으로 기록한다.';

ALTER TABLE `trihouse_fms`.`inventory_moves`
  MODIFY COLUMN inventory_move_id    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '재고 변동 이력을 식별하는 자동 증가 번호',
  MODIFY COLUMN lot_id               BIGINT UNSIGNED NOT NULL COMMENT '연결된 재고 로트의 내부 식별자',
  MODIFY COLUMN job_id               BIGINT UNSIGNED NULL COMMENT '업무를 식별하는 자동 증가 번호',
  MODIFY COLUMN job_step_id          BIGINT UNSIGNED NULL COMMENT '업무 실행 단계를 식별하는 자동 증가 번호',
  MODIFY COLUMN move_type            VARCHAR(24) NOT NULL COMMENT '입고, 출고, 예약, 해제, 조정 등 재고 변동 종류 코드',
  MODIFY COLUMN quantity_delta       INT NOT NULL COMMENT '가용 수량에 더하거나 뺀 변화량',
  MODIFY COLUMN quantity_after       INT NOT NULL COMMENT '재고 변동을 반영한 뒤의 가용 수량',
  MODIFY COLUMN reserved_delta       INT NOT NULL DEFAULT 0 COMMENT '예약 수량에 더하거나 뺀 변화량',
  MODIFY COLUMN reserved_after       INT NOT NULL DEFAULT 0 COMMENT '재고 변동을 반영한 뒤의 예약 수량',
  MODIFY COLUMN recorded_by          VARCHAR(96) NOT NULL COMMENT '재고 변동을 확정한 서비스 또는 작업자 식별 값',
  MODIFY COLUMN recorded_at          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '재고 변동이 확정되어 기록된 시각',
  MODIFY COLUMN note                 VARCHAR(512) NULL COMMENT '재고 변동의 사유를 보충하는 설명';

ALTER TABLE `trihouse_fms`.`device_states`
  COMMENT = '장비별 최신 heartbeat, 위치, 배터리, 진행률, 건강 상태와 현재 실행 단계를 관리한다.';

ALTER TABLE `trihouse_fms`.`device_states`
  MODIFY COLUMN device_id            VARCHAR(64) NOT NULL COMMENT 'Pinky 또는 OMX 장비를 식별하는 고유 코드',
  MODIFY COLUMN observed_at          DATETIME(6) NOT NULL COMMENT '장비 상태가 실제로 관측된 시각',
  MODIFY COLUMN state                VARCHAR(24) NOT NULL COMMENT '장비가 보고한 현재 동작 상태 코드',
  MODIFY COLUMN health               VARCHAR(16) NOT NULL DEFAULT 'ok' COMMENT '장비의 정상, 경고, 오류 또는 통신 두절 건강 상태 코드',
  MODIFY COLUMN current_job_step_id  BIGINT UNSIGNED NULL COMMENT '장비가 현재 실행 중이라고 보고한 업무 단계 식별자',
  MODIFY COLUMN pose_x               DOUBLE NULL COMMENT '지도 좌표계 기준 X 좌표이며 단위는 m',
  MODIFY COLUMN pose_y               DOUBLE NULL COMMENT '지도 좌표계 기준 Y 좌표이며 단위는 m',
  MODIFY COLUMN pose_yaw             DOUBLE NULL COMMENT '지도 좌표계 기준 회전각이며 단위는 rad',
  MODIFY COLUMN battery_pct          DECIMAL(5,2) NULL COMMENT '장비가 보고한 배터리 잔량 백분율',
  MODIFY COLUMN progress             DECIMAL(5,4) NULL COMMENT '현재 업무 단계의 진행률이며 0 이상 1 이하로 저장',
  MODIFY COLUMN details              JSON NULL COMMENT '장비별 추가 상태와 진단 값을 저장하는 JSON 객체';

ALTER TABLE `trihouse_fms`.`integration_messages`
  COMMENT = 'RMF, Pinky, OMX와 주고받는 명령과 응답의 멱등 처리, 재전송, 전송 완료 상태를 관리한다.';

ALTER TABLE `trihouse_fms`.`integration_messages`
  MODIFY COLUMN message_id           CHAR(36) NOT NULL COMMENT '시스템 간 메시지를 중복 없이 식별하는 UUID',
  MODIFY COLUMN direction            VARCHAR(8) NOT NULL COMMENT '메시지의 수신 inbound 또는 송신 outbound 방향 코드',
  MODIFY COLUMN channel              VARCHAR(16) NOT NULL COMMENT '메시지가 통신하는 rmf, pinky 또는 omx 채널 코드',
  MODIFY COLUMN device_id            VARCHAR(64) NULL COMMENT 'Pinky 또는 OMX 장비를 식별하는 고유 코드',
  MODIFY COLUMN job_step_id          BIGINT UNSIGNED NULL COMMENT '업무 실행 단계를 식별하는 자동 증가 번호',
  MODIFY COLUMN message_type         VARCHAR(64) NOT NULL COMMENT '명령, 상태 또는 응답의 계약 종류를 나타내는 코드',
  MODIFY COLUMN idempotency_key      VARCHAR(160) NOT NULL COMMENT '같은 요청의 중복 실행을 방지하는 업무 멱등 키',
  MODIFY COLUMN external_reference   VARCHAR(160) NULL COMMENT '외부 시스템의 요청이나 작업과 연결하는 참조 값',
  MODIFY COLUMN state                VARCHAR(16) NOT NULL DEFAULT 'pending' COMMENT '메시지의 pending, sent, acknowledged, failed 또는 dead 상태',
  MODIFY COLUMN attempts             SMALLINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '메시지 전송을 시도한 누적 횟수',
  MODIFY COLUMN next_attempt_at      DATETIME(6) NULL COMMENT '실패한 메시지를 다음에 재전송할 예정 시각',
  MODIFY COLUMN payload              JSON NOT NULL COMMENT '연동 메시지 또는 운영 이벤트의 원본 데이터를 담은 JSON 객체',
  MODIFY COLUMN last_error           VARCHAR(512) NULL COMMENT '가장 최근 메시지 전송 실패의 원인',
  MODIFY COLUMN created_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '해당 레코드가 데이터베이스에 생성된 시각',
  MODIFY COLUMN sent_at              DATETIME(6) NULL COMMENT '메시지가 외부 채널로 전송된 시각',
  MODIFY COLUMN acknowledged_at      DATETIME(6) NULL COMMENT '안전 사건 또는 메시지를 인지했다고 확정한 시각';

ALTER TABLE `trihouse_fms`.`incidents`
  COMMENT = '사람 감지, 낙상 후보, 충돌 위험, 비상 정지 등 안전 사건의 인지부터 해소까지를 관리한다.';

ALTER TABLE `trihouse_fms`.`incidents`
  MODIFY COLUMN incident_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '안전 사건을 식별하는 자동 증가 번호',
  MODIFY COLUMN incident_code        VARCHAR(64) NOT NULL COMMENT '운영 화면과 보고서에서 사용하는 안전 사건 고유 코드',
  MODIFY COLUMN incident_type        VARCHAR(32) NOT NULL COMMENT '사람, 낙상, 충돌 위험, 비상 정지 등 사건 종류 코드',
  MODIFY COLUMN severity             VARCHAR(16) NOT NULL COMMENT '사건 또는 이벤트의 영향 수준을 나타내는 코드',
  MODIFY COLUMN state                VARCHAR(24) NOT NULL DEFAULT 'active' COMMENT '안전 사건의 open, acknowledged, mitigating, resolved 또는 closed 상태',
  MODIFY COLUMN location_id          BIGINT UNSIGNED NULL COMMENT '연결된 운영 위치의 내부 식별자',
  MODIFY COLUMN geometry             JSON NULL COMMENT '안전 사건이 영향을 주는 점 또는 구역을 표현한 JSON 공간 정보',
  MODIFY COLUMN description          VARCHAR(512) NOT NULL COMMENT '안전 사건의 원인과 상황을 운영자가 이해할 수 있게 기록한 설명',
  MODIFY COLUMN raised_by_worker_id  VARCHAR(64) NULL COMMENT '안전 사건을 수동으로 등록한 작업자 식별자',
  MODIFY COLUMN acknowledged_by_worker_id VARCHAR(64) NULL COMMENT '안전 사건을 인지 처리한 작업자의 식별자',
  MODIFY COLUMN resolved_by_worker_id VARCHAR(64) NULL COMMENT '안전 사건을 최종 해소 처리한 작업자 식별자',
  MODIFY COLUMN raised_at            DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '안전 사건이 최초로 발생하거나 등록된 시각',
  MODIFY COLUMN acknowledged_at      DATETIME(6) NULL COMMENT '안전 사건 또는 메시지를 인지했다고 확정한 시각',
  MODIFY COLUMN resolved_at          DATETIME(6) NULL COMMENT '안전 사건의 원인이 제거되어 해소된 시각',
  MODIFY COLUMN context              JSON NULL COMMENT '센서 관측과 대응 절차 등 안전 사건의 추가 정보를 저장하는 JSON 객체';

ALTER TABLE `trihouse_fms`.`operation_events`
  COMMENT = '업무, 장비, 안전, 모델 판단과 운영자 조치의 시간순 감사 이벤트를 기록한다.';

ALTER TABLE `trihouse_fms`.`operation_events`
  MODIFY COLUMN event_id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '운영 이벤트를 내부에서 식별하는 자동 증가 번호',
  MODIFY COLUMN event_uuid           CHAR(36) NOT NULL COMMENT '시스템 간 중복 없이 운영 이벤트를 식별하는 UUID',
  MODIFY COLUMN occurred_at          DATETIME(6) NOT NULL COMMENT '운영 이벤트가 실제로 발생한 시각',
  MODIFY COLUMN actor_worker_id      VARCHAR(64) NULL COMMENT '운영 이벤트의 사용자 조치를 수행한 작업자 식별자',
  MODIFY COLUMN device_id            VARCHAR(64) NULL COMMENT 'Pinky 또는 OMX 장비를 식별하는 고유 코드',
  MODIFY COLUMN job_id               BIGINT UNSIGNED NULL COMMENT '업무를 식별하는 자동 증가 번호',
  MODIFY COLUMN job_step_id          BIGINT UNSIGNED NULL COMMENT '업무 실행 단계를 식별하는 자동 증가 번호',
  MODIFY COLUMN incident_id          BIGINT UNSIGNED NULL COMMENT '안전 사건을 식별하는 자동 증가 번호',
  MODIFY COLUMN severity             VARCHAR(16) NOT NULL DEFAULT 'info' COMMENT '사건 또는 이벤트의 영향 수준을 나타내는 코드',
  MODIFY COLUMN category             VARCHAR(24) NOT NULL COMMENT '운영 이벤트가 속한 기능 영역을 구분하는 코드 값',
  MODIFY COLUMN event_type           VARCHAR(96) NOT NULL COMMENT '발생한 운영 이벤트의 세부 종류를 나타내는 코드',
  MODIFY COLUMN message              VARCHAR(512) NULL COMMENT '운영자가 이벤트를 이해할 수 있도록 기록한 요약 메시지',
  MODIFY COLUMN model_name           VARCHAR(128) NULL COMMENT '판단 또는 산출물 생성에 사용한 모델 이름',
  MODIFY COLUMN model_version        VARCHAR(128) NULL COMMENT '판단 또는 산출물 생성에 사용한 모델 버전',
  MODIFY COLUMN confidence           DECIMAL(6,5) NULL COMMENT '모델 판단의 신뢰도 값이며 0 이상 1 이하로 저장',
  MODIFY COLUMN safety_decision      VARCHAR(16) NULL COMMENT '모델 제안에 대한 안전 계층의 승인, 거부 또는 보류 결정 코드',
  MODIFY COLUMN payload              JSON NULL COMMENT '이벤트 종류별 상세 관측과 판단 근거를 저장하는 JSON 객체';

ALTER TABLE `trihouse_fms`.`artifacts`
  COMMENT = '영상, 이미지, rosbag, episode, dataset, model과 보고서의 저장 위치와 무결성 정보를 관리한다.';

ALTER TABLE `trihouse_fms`.`artifacts`
  MODIFY COLUMN artifact_id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '파일 산출물을 식별하는 자동 증가 번호',
  MODIFY COLUMN artifact_type         VARCHAR(24) NOT NULL COMMENT '산출물의 형식을 구분하는 코드 값',
  MODIFY COLUMN storage_uri           VARCHAR(1024) NOT NULL COMMENT '산출물 파일이 보관된 객체 저장소 또는 파일 시스템 URI',
  MODIFY COLUMN storage_uri_hash      BINARY(32) GENERATED ALWAYS AS
                            (UNHEX(SHA2(storage_uri, 256))) STORED COMMENT '긴 저장 URI의 중복을 검사하기 위해 계산한 이진 해시',
  MODIFY COLUMN sha256                CHAR(64) NOT NULL COMMENT '산출물 내용의 무결성을 확인하는 SHA-256 해시',
  MODIFY COLUMN mime_type             VARCHAR(128) NULL COMMENT '산출물 파일의 MIME 형식',
  MODIFY COLUMN byte_size             BIGINT UNSIGNED NULL COMMENT '산출물 파일의 바이트 단위 크기',
  MODIFY COLUMN device_id             VARCHAR(64) NULL COMMENT 'Pinky 또는 OMX 장비를 식별하는 고유 코드',
  MODIFY COLUMN job_id                BIGINT UNSIGNED NULL COMMENT '업무를 식별하는 자동 증가 번호',
  MODIFY COLUMN job_step_id           BIGINT UNSIGNED NULL COMMENT '업무 실행 단계를 식별하는 자동 증가 번호',
  MODIFY COLUMN event_id              BIGINT UNSIGNED NULL COMMENT '운영 이벤트를 내부에서 식별하는 자동 증가 번호',
  MODIFY COLUMN model_name            VARCHAR(128) NULL COMMENT '판단 또는 산출물 생성에 사용한 모델 이름',
  MODIFY COLUMN model_version         VARCHAR(128) NULL COMMENT '판단 또는 산출물 생성에 사용한 모델 버전',
  MODIFY COLUMN metadata              JSON NULL COMMENT '코덱, 해상도, dataset split 등 산출물별 확장 정보를 저장하는 JSON 객체',
  MODIFY COLUMN captured_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '산출물의 원본 데이터가 취득된 시각';

ALTER TABLE `trihouse_fms`.`location_recovery_profiles`
  COMMENT = '안전 노드별 복구 역할, 사용 가능 상태와 베타 분포 기반 신뢰도를 관리한다.';

ALTER TABLE `trihouse_fms`.`location_recovery_profiles`
  MODIFY COLUMN reference_node_uuid    CHAR(36) NOT NULL COMMENT '복구 목표로 사용할 안전 노드를 식별하는 UUID',
  MODIFY COLUMN location_id            BIGINT UNSIGNED NOT NULL COMMENT '연결된 운영 위치의 내부 식별자',
  MODIFY COLUMN map_revision           VARCHAR(128) NOT NULL COMMENT '좌표와 feature가 유효한 지도 버전 식별자',
  MODIFY COLUMN recovery_roles         JSON NOT NULL COMMENT '안전 노드가 지원하는 wait, retreat, detour, rejoin 역할의 JSON 배열',
  MODIFY COLUMN availability_status    VARCHAR(16) NOT NULL DEFAULT 'active' COMMENT '복구 기준 노드의 현재 사용 가능 상태 코드',
  MODIFY COLUMN reliability_alpha      DECIMAL(12,4) NOT NULL DEFAULT 1.0000 COMMENT '복구 노드 성공 신뢰도의 베타 분포 alpha 누적 값',
  MODIFY COLUMN reliability_beta       DECIMAL(12,4) NOT NULL DEFAULT 1.0000 COMMENT '복구 노드 실패 신뢰도의 베타 분포 beta 누적 값',
  MODIFY COLUMN last_verified_at       DATETIME(6) NULL COMMENT '복구 기준 노드의 위치와 안전성을 마지막으로 검증한 시각',
  MODIFY COLUMN last_outcome_at        DATETIME(6) NULL COMMENT '복구 기준 노드가 실제 결과에 사용된 가장 최근 시각',
  MODIFY COLUMN reviewed_by_worker_id  VARCHAR(64) NULL COMMENT '복구 기준 노드의 상태를 마지막으로 검토한 작업자 식별자',
  MODIFY COLUMN revision               BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '동시 수정 충돌을 탐지하기 위한 낙관적 잠금 버전',
  MODIFY COLUMN notes                  VARCHAR(1024) NULL COMMENT '복구 기준 노드의 검토 결과와 주의사항',
  MODIFY COLUMN created_at             DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '해당 레코드가 데이터베이스에 생성된 시각',
  MODIFY COLUMN updated_at             DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                             ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '해당 레코드가 마지막으로 수정된 시각';

ALTER TABLE `trihouse_recovery`.`recovery_episodes`
  COMMENT = '복구 trigger부터 종료까지 하나의 사건과 사용한 VLM 및 복구 정책의 계보를 기록한다.';

ALTER TABLE `trihouse_recovery`.`recovery_episodes`
  MODIFY COLUMN recovery_episode_uuid     CHAR(36) NOT NULL COMMENT '하나의 복구 사건을 시스템 간 고유하게 식별하는 UUID',
  MODIFY COLUMN source_event_uuid         CHAR(36) NULL COMMENT '복구 에피소드를 시작시킨 FMS 운영 이벤트 UUID',
  MODIFY COLUMN device_id                 VARCHAR(64) NOT NULL COMMENT 'Pinky 또는 OMX 장비를 식별하는 고유 코드',
  MODIFY COLUMN fms_job_id                BIGINT UNSIGNED NULL COMMENT '복구 에피소드와 연결된 FMS 업무 식별자이며 물리적 외래 키는 두지 않음',
  MODIFY COLUMN fms_job_step_id           BIGINT UNSIGNED NULL COMMENT '복구 에피소드와 연결된 FMS 업무 단계 식별자이며 물리적 외래 키는 두지 않음',
  MODIFY COLUMN map_name                  VARCHAR(96) NOT NULL COMMENT 'Open-RMF와 로봇 navigation에서 사용하는 지도 이름',
  MODIFY COLUMN map_revision              VARCHAR(128) NOT NULL COMMENT '좌표와 feature가 유효한 지도 버전 식별자',
  MODIFY COLUMN trigger_type              VARCHAR(24) NOT NULL COMMENT '복구를 시작시킨 정체, 사람, 저시정 또는 위치 추정 문제 코드',
  MODIFY COLUMN vlm_model_name            VARCHAR(128) NULL COMMENT '복구 상황 해석에 사용한 VLM 모델 이름',
  MODIFY COLUMN vlm_model_version         VARCHAR(128) NULL COMMENT '복구 상황 해석에 사용한 VLM 모델 버전',
  MODIFY COLUMN recovery_policy_name      VARCHAR(128) NOT NULL COMMENT '실행한 복구 정책의 이름',
  MODIFY COLUMN recovery_policy_version   VARCHAR(128) NOT NULL COMMENT '실행한 복구 정책의 버전',
  MODIFY COLUMN started_at                DATETIME(6) NOT NULL COMMENT '업무, 단계 또는 복구 행동이 실제로 시작된 시각',
  MODIFY COLUMN ended_at                  DATETIME(6) NULL COMMENT '복구 에피소드가 성공, 중단 또는 실패로 종료된 시각',
  MODIFY COLUMN final_status              VARCHAR(16) NOT NULL DEFAULT 'running' COMMENT '복구 에피소드의 실행 중, 성공, 중단 또는 실패 최종 상태',
  MODIFY COLUMN summary                   VARCHAR(1024) NULL COMMENT '복구 에피소드의 원인, 행동과 결과를 요약한 설명',
  MODIFY COLUMN created_at                DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '해당 레코드가 데이터베이스에 생성된 시각';

ALTER TABLE `trihouse_recovery`.`recovery_steps`
  COMMENT = '복구 에피소드에서 실제 실행한 행동, 전후 관측, 보상, 결과와 완료 상태를 순서대로 기록한다.';

ALTER TABLE `trihouse_recovery`.`recovery_steps`
  MODIFY COLUMN recovery_step_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '복구 실행 단계를 식별하는 자동 증가 번호',
  MODIFY COLUMN recovery_episode_uuid  CHAR(36) NOT NULL COMMENT '하나의 복구 사건을 시스템 간 고유하게 식별하는 UUID',
  MODIFY COLUMN step_no                SMALLINT UNSIGNED NOT NULL COMMENT '같은 업무 또는 에피소드 안에서 실행 순서를 나타내는 번호',
  MODIFY COLUMN reference_node_uuid    CHAR(36) NULL COMMENT '행동 목표로 선택한 FMS 복구 기준 노드 UUID이며 물리적 외래 키는 두지 않음',
  MODIFY COLUMN action_type            VARCHAR(16) NOT NULL COMMENT '실행할 동작 종류를 나타내는 코드 값',
  MODIFY COLUMN target_pose            JSON NULL COMMENT '복구 행동이 목표로 삼은 위치와 방향의 JSON 객체',
  MODIFY COLUMN before_state_uri       VARCHAR(1024) NULL COMMENT '행동 전 관측 데이터가 저장된 위치 URI',
  MODIFY COLUMN before_state_sha256    CHAR(64) NULL COMMENT '행동 전 관측 파일의 무결성을 확인하는 SHA-256 해시',
  MODIFY COLUMN after_state_uri        VARCHAR(1024) NULL COMMENT '행동 후 관측 데이터가 저장된 위치 URI',
  MODIFY COLUMN after_state_sha256     CHAR(64) NULL COMMENT '행동 후 관측 파일의 무결성을 확인하는 SHA-256 해시',
  MODIFY COLUMN reward_components      JSON NULL COMMENT 'RL 학습용 보상을 항목별로 기록한 JSON 객체',
  MODIFY COLUMN outcome_class          VARCHAR(16) NOT NULL COMMENT '복구 결과를 safe, boundary 또는 critical로 구분한 코드',
  MODIFY COLUMN execution_status       VARCHAR(16) NOT NULL DEFAULT 'queued' COMMENT '복구 행동의 대기, 실행, 성공, 실패 또는 취소 상태 코드',
  MODIFY COLUMN is_terminal            TINYINT(1) NOT NULL DEFAULT 0 COMMENT '해당 복구 행동이 에피소드의 마지막 단계인지 나타내는 값',
  MODIFY COLUMN started_at             DATETIME(6) NOT NULL COMMENT '업무, 단계 또는 복구 행동이 실제로 시작된 시각',
  MODIFY COLUMN completed_at           DATETIME(6) NULL COMMENT '업무, 단계 또는 복구 행동이 완료된 시각',
  MODIFY COLUMN created_at             DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '해당 레코드가 데이터베이스에 생성된 시각';
