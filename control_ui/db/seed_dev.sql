-- RoboSapiens 물류 플랫폼 — 로컬 개발용 시드 데이터
--
-- db/schema.sql 로 만든 빈 `robosapiens` 를 개발·시연이 가능한 상태로 채운다.
-- 운영 데이터가 아니다. 새 PC에서 작업을 시작하거나, 로컬 DB를 알려진
-- 상태로 되돌릴 때 쓴다.
--
-- 적용:
--   mysql -u root -p --default-character-set=utf8mb4 < db/schema.sql
--   mysql -u root -p --default-character-set=utf8mb4 < db/seed_dev.sql
--
-- 전체 재적재다. 아래 테이블의 기존 행을 지우고 다시 넣으므로 여러 번 돌려도
-- 같은 결과가 나온다. 시각만 실행 시점(NOW) 기준으로 다시 잡힌다.
--
-- 맵 프로젝트에 딸린 표(map_projects, map_project_waypoints, map_project_lanes,
-- rmf_ui_tasks, rmf_ui_task_history)는 건드리지 않는다. 사용자가 앱에서 만든
-- 실제 작업물이지 시연용 표본이 아니다. 이 파일을 다시 돌려도 저장해 둔 창고
-- 맵과 그 작업은 그대로 남는다.
--
-- 값의 출처 — 임의로 지어낸 문자열이 아니라 코드의 실제 규약을 따른다:
--   로봇 RS-01~08          robo_control/lib/core/fleet_engine.dart `_seedRobots`
--   작업자 W-01~06         robo_control/lib/core/fleet_engine.dart `_seedWorkers`
--   랙 슬롯 {코드}-{행}-{열} robo_control/lib/core/layout.dart (4행 × 20열)
--                          상온 A 1~8열 · 냉장 C 9~15열 · 냉동 F 16~20열
--   설비 IN/OUT/CHG/WS/…    robo_control/lib/core/layout.dart `stations`
--   enum 문자열             robo_core/lib/models/enums.dart, models/task.dart,
--                          data/repositories.dart (모두 Dart enum 이름 그대로)
--   ID 프리픽스·카운터       robo_control/lib/core/fleet_engine.dart `_counterOf`

SET NAMES utf8mb4;
USE `robosapiens`;

START TRANSACTION;

-- 자식 → 부모 역순으로 비운다.
DELETE FROM `task_steps`;
DELETE FROM `tasks`;
DELETE FROM `order_lines`;
DELETE FROM `orders`;
DELETE FROM `stock_moves`;
DELETE FROM `lots`;
DELETE FROM `incidents`;
DELETE FROM `events`;
DELETE FROM `workers`;
DELETE FROM `robot_telemetry`;
DELETE FROM `robots`;
DELETE FROM `counters`;


-- ---------------------------------------------------------------------------
-- 로봇 — fleet_engine `_seedRobots` 와 동일한 편성
-- zone_rating 은 TempZone.name 을 콤마로 이어 붙인 값이다.
-- RS-07·RS-08 은 예비기(reserve = 1), RS-09 는 등록 해제 이력 보존 사례.
-- ---------------------------------------------------------------------------
INSERT INTO `robots`
  (`id`, `name`, `model`, `zone_rating`, `home_charger_id`, `reserve`, `active`, `registered_at`, `retired_at`) VALUES
  ('RS-01', '알파',     'RSX-200',  'ambient,chilled',        'CHG-1', 0, 1, NOW(6) - INTERVAL 210 DAY, NULL),
  ('RS-02', '브라보',   'RSX-200',  'ambient,chilled',        'CHG-1', 0, 1, NOW(6) - INTERVAL 210 DAY, NULL),
  ('RS-03', '찰리',     'RSX-200',  'ambient,chilled',        'CHG-2', 0, 1, NOW(6) - INTERVAL 198 DAY, NULL),
  ('RS-04', '델타',     'RSX-220',  'ambient,chilled',        'CHG-2', 0, 1, NOW(6) - INTERVAL 150 DAY, NULL),
  ('RS-05', '에코',     'RSX-300C', 'ambient,chilled,frozen', 'CHG-4', 0, 1, NOW(6) - INTERVAL 120 DAY, NULL),
  ('RS-06', '폭스트롯', 'RSX-300C', 'ambient,chilled,frozen', 'CHG-4', 0, 1, NOW(6) - INTERVAL 120 DAY, NULL),
  ('RS-07', '골프',     'RSX-220',  'ambient,chilled',        'CHG-3', 1, 1, NOW(6) - INTERVAL  60 DAY, NULL),
  ('RS-08', '호텔',     'RSX-300C', 'ambient,chilled,frozen', 'CHG-3', 1, 1, NOW(6) - INTERVAL  60 DAY, NULL),
  -- 등록 해제는 삭제가 아니라 active = 0 + retired_at 이다.
  ('RS-09', '인디아',   'RSX-100',  'ambient',                'CHG-1', 0, 0, NOW(6) - INTERVAL 400 DAY, NOW(6) - INTERVAL 30 DAY);

-- 로봇당 최신 스냅샷 1행. 운영 중에는 UPSERT로 갱신된다.
-- 좌표는 fleet_engine 초기 배치, state 는 RobotState.name.
INSERT INTO `robot_telemetry`
  (`robot_id`, `at`, `state`, `battery`, `x`, `y`, `heading`, `task_id`, `progress`, `activity`, `odometer`, `power_saving`, `completed`, `failed`) VALUES
  ('RS-01', NOW(6) - INTERVAL 4 SECOND, 'moving',     94.2,  20.0, 22.0,   0.00, 'TSK-0002', 0.42, 'A-01-03 집품 이동',  18422.5, 0,  312, 4),
  ('RS-02', NOW(6) - INTERVAL 3 SECOND, 'picking',    86.1,  35.0, 54.0,   1.57, 'TSK-0003', 0.65, 'A-03-06 집품',       17110.0, 0,  298, 2),
  ('RS-03', NOW(6) - INTERVAL 5 SECOND, 'idle',       73.4,  50.0, 38.0,   3.14, NULL,       0.00, NULL,                 15980.2, 0,  276, 5),
  ('RS-04', NOW(6) - INTERVAL 2 SECOND, 'charging',   41.8,  65.0, 22.0,   0.00, NULL,       0.00, 'CHG-2 충전',          12044.7, 0,  201, 3),
  ('RS-05', NOW(6) - INTERVAL 3 SECOND, 'placing',    89.6,  95.0, 54.0,  -1.57, 'TSK-0004', 0.80, 'OUT-1 하역',           9877.1, 0,  164, 1),
  ('RS-06', NOW(6) - INTERVAL 6 SECOND, 'blocked',    45.3, 110.0, 38.0,   2.20, 'TSK-0005', 0.15, 'F-02-18 자원 대기',    9312.6, 0,  158, 6),
  ('RS-07', NOW(6) - INTERVAL 9 SECOND, 'standby',   100.0,  65.0, 68.0,   0.00, NULL,       0.00, '예비 대기',            2201.3, 0,   38, 0),
  ('RS-08', NOW(6) - INTERVAL 9 SECOND, 'powerSaving', 99.1,  80.0, 68.0,   0.00, NULL,      0.00, '절전',                 1988.4, 1,   31, 0),
  ('RS-09', NOW(6) - INTERVAL 30 DAY,   'idle',        12.0,  20.0, 13.0,   0.00, NULL,       0.00, '등록 해제됨',         44210.9, 0, 1024, 41);


-- ---------------------------------------------------------------------------
-- 현장 작업자 — fleet_engine `_seedWorkers` 와 동일
-- ---------------------------------------------------------------------------
INSERT INTO `workers`
  (`id`, `name`, `role`, `zone`, `active`, `registered_at`, `retired_at`) VALUES
  ('W-01', '김선우', '피킹',      'ambient', 1, NOW(6) - INTERVAL 300 DAY, NULL),
  ('W-02', '이도현', '검수',      'ambient', 1, NOW(6) - INTERVAL 300 DAY, NULL),
  ('W-03', '박서연', '포장',      'ambient', 1, NOW(6) - INTERVAL 240 DAY, NULL),
  ('W-04', '최민재', '냉장 피킹', 'chilled', 1, NOW(6) - INTERVAL 180 DAY, NULL),
  ('W-05', '정하늘', '냉장 검수', 'chilled', 1, NOW(6) - INTERVAL 180 DAY, NULL),
  ('W-06', '한지우', '냉동 피킹', 'frozen',  1, NOW(6) - INTERVAL  90 DAY, NULL),
  ('W-07', '오세훈', '피킹',      'ambient', 0, NOW(6) - INTERVAL 500 DAY, NOW(6) - INTERVAL 45 DAY);


-- ---------------------------------------------------------------------------
-- 재고 로트
-- 같은 SKU에 만료일이 다른 로트를 여러 개 둔다 — FEFO(가까운 expiry 우선)가
-- 실제로 동작하는지 눈으로 확인할 수 있어야 한다.
-- 가용 수량 = qty - reserved. LOT-0011 은 전량 예약(가용 0) 사례.
-- LOT-0012 는 이미 만료 — 유통기한 회수(disposal) 태스크의 대상이다.
-- ---------------------------------------------------------------------------
INSERT INTO `lots`
  (`id`, `sku`, `name`, `zone`, `location_id`, `qty`, `reserved`, `expiry`, `received_at`) VALUES
  -- 상온 (A, 1~8열)
  ('LOT-0001', 'SKU-RICE',   '즉석밥 210g',    'ambient', 'A-01-03', 240,  12, NOW(6) + INTERVAL 180 DAY, NOW(6) - INTERVAL 21 DAY),
  ('LOT-0002', 'SKU-RICE',   '즉석밥 210g',    'ambient', 'A-02-05', 180,   0, NOW(6) + INTERVAL 240 DAY, NOW(6) - INTERVAL  9 DAY),
  ('LOT-0003', 'SKU-WATER',  '생수 2L 6입',    'ambient', 'A-03-06', 320,  24, NOW(6) + INTERVAL 300 DAY, NOW(6) - INTERVAL 30 DAY),
  ('LOT-0004', 'SKU-RAMEN',  '봉지라면 5입',   'ambient', 'A-04-02', 150,   0, NOW(6) + INTERVAL 150 DAY, NOW(6) - INTERVAL 14 DAY),
  -- 냉장 (C, 9~15열)
  ('LOT-0005', 'SKU-MILK',   '멸균우유 1L',    'chilled', 'C-01-09', 120,   8, NOW(6) + INTERVAL  12 DAY, NOW(6) - INTERVAL  4 DAY),
  ('LOT-0006', 'SKU-MILK',   '멸균우유 1L',    'chilled', 'C-02-10',  80,   0, NOW(6) + INTERVAL  26 DAY, NOW(6) - INTERVAL  1 DAY),
  ('LOT-0007', 'SKU-YOGURT', '요거트 4입',     'chilled', 'C-03-12',  96,   6, NOW(6) + INTERVAL   9 DAY, NOW(6) - INTERVAL  3 DAY),
  ('LOT-0008', 'SKU-TOFU',   '두부 300g',      'chilled', 'C-04-14',  64,   0, NOW(6) + INTERVAL   5 DAY, NOW(6) - INTERVAL  2 DAY),
  -- 냉동 (F, 16~20열)
  ('LOT-0009', 'SKU-ICE',    '아이스크림 4입', 'frozen',  'F-01-17', 140,  10, NOW(6) + INTERVAL 210 DAY, NOW(6) - INTERVAL 20 DAY),
  ('LOT-0010', 'SKU-DUMP',   '냉동만두 1kg',   'frozen',  'F-02-18', 110,   0, NOW(6) + INTERVAL 160 DAY, NOW(6) - INTERVAL 11 DAY),
  ('LOT-0011', 'SKU-DUMP',   '냉동만두 1kg',   'frozen',  'F-03-19',  30,  30, NOW(6) + INTERVAL  95 DAY, NOW(6) - INTERVAL 40 DAY),
  ('LOT-0012', 'SKU-YOGURT', '요거트 4입',     'chilled', 'C-04-15',  18,   0, NOW(6) - INTERVAL   2 DAY, NOW(6) - INTERVAL 25 DAY);

-- 재고 원장 — append-only. lot_id 에 FK가 없으므로 소진된 로트의 이력도 남는다.
INSERT INTO `stock_moves`
  (`at`, `lot_id`, `sku`, `delta`, `qty_after`, `reason`, `task_id`, `order_id`, `operator`, `note`) VALUES
  (NOW(6) - INTERVAL 30 DAY, 'LOT-0003', 'SKU-WATER',  340, 340, 'initial',    NULL,       NULL,       NULL,     '기초 재고'),
  (NOW(6) - INTERVAL 25 DAY, 'LOT-0012', 'SKU-YOGURT',  48,  48, 'initial',    NULL,       NULL,       NULL,     '기초 재고'),
  (NOW(6) - INTERVAL 21 DAY, 'LOT-0001', 'SKU-RICE',   240, 240, 'inbound',    'TSK-0001', NULL,       '이도현', 'IN-1 입고 검수 완료'),
  (NOW(6) - INTERVAL 20 DAY, 'LOT-0009', 'SKU-ICE',    140, 140, 'inbound',    NULL,       NULL,       '한지우', 'IN-2 냉동 입고'),
  (NOW(6) - INTERVAL 14 DAY, 'LOT-0004', 'SKU-RAMEN',  150, 150, 'inbound',    NULL,       NULL,       '김선우', NULL),
  (NOW(6) - INTERVAL 12 DAY, 'LOT-0012', 'SKU-YOGURT', -20,  28, 'outbound',   NULL,       'ORD-0001', NULL,     NULL),
  (NOW(6) - INTERVAL 11 DAY, 'LOT-0010', 'SKU-DUMP',   110, 110, 'inbound',    NULL,       NULL,       '한지우', NULL),
  (NOW(6) - INTERVAL  9 DAY, 'LOT-0002', 'SKU-RICE',   180, 180, 'inbound',    NULL,       NULL,       '이도현', NULL),
  (NOW(6) - INTERVAL  7 DAY, 'LOT-0003', 'SKU-WATER',  -20, 320, 'outbound',   NULL,       'ORD-0002', NULL,     NULL),
  (NOW(6) - INTERVAL  6 DAY, 'LOT-0012', 'SKU-YOGURT', -10,  18, 'outbound',   NULL,       'ORD-0002', NULL,     NULL),
  (NOW(6) - INTERVAL  4 DAY, 'LOT-0005', 'SKU-MILK',   120, 120, 'inbound',    NULL,       NULL,       '최민재', NULL),
  (NOW(6) - INTERVAL  3 DAY, 'LOT-0007', 'SKU-YOGURT',  96,  96, 'inbound',    NULL,       NULL,       '정하늘', NULL),
  (NOW(6) - INTERVAL  2 DAY, 'LOT-0008', 'SKU-TOFU',    64,  64, 'inbound',    NULL,       NULL,       '최민재', NULL),
  (NOW(6) - INTERVAL 36 HOUR,'LOT-0004', 'SKU-RAMEN',   -2, 148, 'adjustment', NULL,       NULL,       '박서연', '파손 2개 제외'),
  (NOW(6) - INTERVAL 30 HOUR,'LOT-0004', 'SKU-RAMEN',    2, 150, 'cycleCount', NULL,       NULL,       '박서연', '실사 결과 되돌림'),
  (NOW(6) - INTERVAL  6 HOUR,'LOT-0006', 'SKU-MILK',    80,  80, 'inbound',    NULL,       NULL,       '최민재', NULL),
  (NOW(6) - INTERVAL 90 MINUTE,'LOT-0012','SKU-YOGURT',  0,  18, 'disposal',   'TSK-0007', NULL,       NULL,     '유통기한 경과 — 회수 태스크 지시');


-- ---------------------------------------------------------------------------
-- 주문
-- expanded = 0 이 관제가 아직 태스크로 전개하지 않은 주문이다. 이 값이 곧
-- rmf_control_ui 의 `loadPendingOrders` 가 5초마다 집어가는 대상이므로,
-- 앱을 띄우자마자 자동 분류가 도는 걸 보려면 여기 몇 건 남아 있어야 한다.
-- ORD-0005·0006 이 그 미처리분이다.
-- ---------------------------------------------------------------------------
INSERT INTO `orders`
  (`id`, `customer`, `urgency`, `created_at`, `due_at`, `line_count`, `state`, `done_lines`, `failed_lines`, `closed_at`, `source`, `expanded`) VALUES
  ('ORD-0001', '김하늘', 'normal',   NOW(6) - INTERVAL 12 DAY,   NOW(6) - INTERVAL 12 DAY + INTERVAL 6 HOUR, 2, 'fulfilled', 2, 0, NOW(6) - INTERVAL 12 DAY + INTERVAL 4 HOUR, 'app',  1),
  ('ORD-0002', '박서준', 'high',     NOW(6) - INTERVAL  7 DAY,   NOW(6) - INTERVAL  7 DAY + INTERVAL 4 HOUR, 2, 'partial',   1, 1, NOW(6) - INTERVAL  7 DAY + INTERVAL 5 HOUR, 'app',  1),
  ('ORD-0003', '이수민', 'critical', NOW(6) - INTERVAL  5 HOUR,  NOW(6) + INTERVAL 1 HOUR,                   3, 'working',   1, 0, NULL,                                       'auto', 1),
  ('ORD-0004', '정우진', 'low',      NOW(6) - INTERVAL  3 HOUR,  NOW(6) + INTERVAL 9 HOUR,                   1, 'open',      0, 0, NULL,                                       'auto', 1),
  -- 아래 두 건이 미처리(자동 분류 대기)
  ('ORD-0005', '한예린', 'high',     NOW(6) - INTERVAL 12 MINUTE, NOW(6) + INTERVAL 2 HOUR,                  2, 'open',      0, 0, NULL,                                       'app',  0),
  ('ORD-0006', '윤도경', 'normal',   NOW(6) - INTERVAL  4 MINUTE, NOW(6) + INTERVAL 6 HOUR,                  2, 'open',      0, 0, NULL,                                       'app',  0);

-- lot_id 가 NULL 인 줄은 FEFO 규칙으로 관제가 로트를 고른다.
INSERT INTO `order_lines`
  (`order_id`, `seq`, `sku`, `name`, `qty`, `lot_id`) VALUES
  ('ORD-0001', 1, 'SKU-YOGURT', '요거트 4입',     2, 'LOT-0012'),
  ('ORD-0001', 2, 'SKU-RICE',   '즉석밥 210g',    4, 'LOT-0001'),
  ('ORD-0002', 1, 'SKU-WATER',  '생수 2L 6입',    1, 'LOT-0003'),
  ('ORD-0002', 2, 'SKU-YOGURT', '요거트 4입',     1, 'LOT-0012'),
  ('ORD-0003', 1, 'SKU-MILK',   '멸균우유 1L',    2, 'LOT-0005'),
  ('ORD-0003', 2, 'SKU-ICE',    '아이스크림 4입', 1, NULL),
  ('ORD-0003', 3, 'SKU-RICE',   '즉석밥 210g',    2, NULL),
  ('ORD-0004', 1, 'SKU-RAMEN',  '봉지라면 5입',   3, NULL),
  -- 미처리 주문: 상온 + 냉동 → zones 가 ['ambient','frozen'] 로 잡혀야 한다
  ('ORD-0005', 1, 'SKU-RICE',   '즉석밥 210g',    2, NULL),
  ('ORD-0005', 2, 'SKU-ICE',    '아이스크림 4입', 1, NULL),
  -- 미처리 주문: 냉장 2줄 → zones 가 ['chilled','chilled'] 로 잡혀야 한다
  ('ORD-0006', 1, 'SKU-MILK',   '멸균우유 1L',    1, NULL),
  ('ORD-0006', 2, 'SKU-TOFU',   '두부 300g',      2, NULL);


-- ---------------------------------------------------------------------------
-- 태스크 — TaskState 전 구간을 한 벌씩 깔아 둔다.
-- pending / claimed / inProgress / blocked / done / failed / cancelled
-- order_id 에 FK가 없다(완결 태스크는 주문과 다른 주기로 정리되므로).
-- ---------------------------------------------------------------------------
INSERT INTO `tasks`
  (`id`, `type`, `title`, `urgency`, `zone`, `order_id`, `sku`, `lot_id`, `expiry`, `qty`, `requested_by`, `origin_label`, `dest_label`, `state`, `robot_id`, `step_index`, `retries`, `fail_reason`, `score`, `created_at`, `assigned_at`, `started_at`, `ended_at`) VALUES
  ('TSK-0001', 'inbound',   '즉석밥 입고 적치',       'normal',   'ambient', NULL,       'SKU-RICE',   'LOT-0001', NOW(6) + INTERVAL 180 DAY, 240, 'W-02', 'IN-1',     'A-01-03', 'done',       'RS-01', 4, 0, NULL,                    12.5, NOW(6) - INTERVAL 21 DAY,    NOW(6) - INTERVAL 21 DAY,     NOW(6) - INTERVAL 21 DAY,      NOW(6) - INTERVAL 21 DAY + INTERVAL 18 MINUTE),
  ('TSK-0002', 'outbound',  '멸균우유 출고 집품',     'critical', 'chilled', 'ORD-0003', 'SKU-MILK',   'LOT-0005', NOW(6) + INTERVAL 12 DAY,    2, NULL,   'C-01-09',  'OUT-1',   'inProgress', 'RS-01', 1, 0, NULL,                    31.0, NOW(6) - INTERVAL 22 MINUTE, NOW(6) - INTERVAL 20 MINUTE,  NOW(6) - INTERVAL 19 MINUTE,   NULL),
  ('TSK-0003', 'outbound',  '생수 출고 집품',         'high',     'ambient', 'ORD-0003', 'SKU-RICE',   'LOT-0001', NOW(6) + INTERVAL 180 DAY,   2, NULL,   'A-03-06',  'OUT-1',   'inProgress', 'RS-02', 2, 0, NULL,                    24.0, NOW(6) - INTERVAL 18 MINUTE, NOW(6) - INTERVAL 17 MINUTE,  NOW(6) - INTERVAL 16 MINUTE,   NULL),
  ('TSK-0004', 'handover',  '냉동 피킹 작업자 인계',  'high',     'frozen',  'ORD-0003', 'SKU-ICE',    'LOT-0009', NOW(6) + INTERVAL 210 DAY,   1, 'W-06', 'F-01-17',  'WS-3',    'inProgress', 'RS-05', 3, 0, NULL,                    22.5, NOW(6) - INTERVAL 14 MINUTE, NOW(6) - INTERVAL 13 MINUTE,  NOW(6) - INTERVAL 12 MINUTE,   NULL),
  ('TSK-0005', 'replenish', '냉동만두 보충',          'normal',   'frozen',  NULL,       'SKU-DUMP',   'LOT-0010', NOW(6) + INTERVAL 160 DAY,  20, NULL,   'F-02-18',  'F-03-19', 'blocked',    'RS-06', 1, 1, NULL,                     8.0, NOW(6) - INTERVAL 11 MINUTE, NOW(6) - INTERVAL 10 MINUTE,  NOW(6) - INTERVAL  9 MINUTE,   NULL),
  ('TSK-0006', 'outbound',  '봉지라면 출고 집품',     'low',      'ambient', 'ORD-0004', 'SKU-RAMEN',  'LOT-0004', NOW(6) + INTERVAL 150 DAY,   3, NULL,   'A-04-02',  'OUT-2',   'pending',    NULL,    0, 0, NULL,                     5.5, NOW(6) - INTERVAL  6 MINUTE, NULL,                         NULL,                          NULL),
  ('TSK-0007', 'disposal',  '유통기한 경과 요거트 회수','high',   'chilled', NULL,       'SKU-YOGURT', 'LOT-0012', NOW(6) - INTERVAL 2 DAY,    18, NULL,   'C-04-15',  'OUT-2',   'claimed',    'RS-03', 0, 0, NULL,                    19.5, NOW(6) - INTERVAL  3 MINUTE, NOW(6) - INTERVAL 90 SECOND,  NULL,                          NULL),
  ('TSK-0008', 'outbound',  '요거트 출고 집품',       'high',     'chilled', 'ORD-0002', 'SKU-YOGURT', 'LOT-0012', NOW(6) - INTERVAL 2 DAY,     1, NULL,   'C-04-15',  'OUT-1',   'failed',     'RS-03', 2, 3, '집품 위치 자원 점유 해제 실패', 14.0, NOW(6) - INTERVAL 7 DAY, NOW(6) - INTERVAL 7 DAY,      NOW(6) - INTERVAL 7 DAY,       NOW(6) - INTERVAL 7 DAY + INTERVAL 22 MINUTE),
  ('TSK-0009', 'relay',     '작업자 간 전달 (취소됨)', 'normal',  'ambient', NULL,       NULL,         NULL,       NULL,                        1, 'W-01', 'WS-1',     'WS-2',    'cancelled',  NULL,    0, 0, '상위 주문 취소',        0.0,  NOW(6) - INTERVAL 2 DAY,     NULL,                         NULL,                          NOW(6) - INTERVAL 2 DAY + INTERVAL 3 MINUTE);

-- 태스크 세부 단계. kind 는 StepKind.name (move/pick/place/scan/handover/load/wait).
-- target_x/y 는 layout.dart 의 슬롯·설비 좌표계를 따른다.
INSERT INTO `task_steps`
  (`task_id`, `seq`, `kind`, `label`, `target_x`, `target_y`, `duration`, `resource_id`) VALUES
  ('TSK-0001', 0, 'move',     'IN-1 이동',      14.0,  76.0, 0.0, NULL),
  ('TSK-0001', 1, 'load',     'IN-1 적재',      14.0,  76.0, 8.0, 'IN-1'),
  ('TSK-0001', 2, 'move',     'A-01-03 이동',   20.7,  13.0, 0.0, NULL),
  ('TSK-0001', 3, 'place',    'A-01-03 적치',   20.7,  13.0, 6.0, 'A-01-03'),
  ('TSK-0001', 4, 'scan',     '적치 검수',      20.7,  13.0, 4.0, NULL),

  ('TSK-0002', 0, 'move',     'C-01-09 이동',   54.3,  13.0, 0.0, NULL),
  ('TSK-0002', 1, 'pick',     'C-01-09 집품',   54.3,  13.0, 7.0, 'C-01-09'),
  ('TSK-0002', 2, 'move',     'OUT-1 이동',     96.0,  76.0, 0.0, NULL),
  ('TSK-0002', 3, 'place',    'OUT-1 하역',     96.0,  76.0, 6.0, 'OUT-1'),

  ('TSK-0003', 0, 'move',     'A-03-06 이동',   37.5,  46.0, 0.0, NULL),
  ('TSK-0003', 1, 'pick',     'A-03-06 집품',   37.5,  46.0, 7.0, 'A-03-06'),
  ('TSK-0003', 2, 'move',     'OUT-1 이동',     96.0,  76.0, 0.0, NULL),
  ('TSK-0003', 3, 'place',    'OUT-1 하역',     96.0,  76.0, 6.0, 'OUT-1'),

  ('TSK-0004', 0, 'move',     'F-01-17 이동',   99.1,  13.0, 0.0, NULL),
  ('TSK-0004', 1, 'pick',     'F-01-17 집품',   99.1,  13.0, 7.0, 'F-01-17'),
  ('TSK-0004', 2, 'move',     'WS-3 이동',     104.0,  68.0, 0.0, NULL),
  ('TSK-0004', 3, 'handover', 'W-06 인계',     104.0,  68.0, 12.0, 'WS-3'),

  ('TSK-0005', 0, 'move',     'F-02-18 이동',  104.7,  30.0, 0.0, NULL),
  ('TSK-0005', 1, 'pick',     'F-02-18 집품',  104.7,  30.0, 7.0, 'F-02-18'),
  ('TSK-0005', 2, 'wait',     '자원 대기',     104.7,  30.0, 0.0, 'F-03-19'),
  ('TSK-0005', 3, 'move',     'F-03-19 이동',  110.3,  46.0, 0.0, NULL),
  ('TSK-0005', 4, 'place',    'F-03-19 적치',  110.3,  46.0, 6.0, 'F-03-19'),

  ('TSK-0006', 0, 'move',     'A-04-02 이동',   15.1,  61.0, 0.0, NULL),
  ('TSK-0006', 1, 'pick',     'A-04-02 집품',   15.1,  61.0, 7.0, 'A-04-02'),
  ('TSK-0006', 2, 'move',     'OUT-2 이동',    108.0,  76.0, 0.0, NULL),
  ('TSK-0006', 3, 'place',    'OUT-2 하역',    108.0,  76.0, 6.0, 'OUT-2'),

  ('TSK-0007', 0, 'move',     'C-04-15 이동',   87.9,  61.0, 0.0, NULL),
  ('TSK-0007', 1, 'pick',     'C-04-15 회수',   87.9,  61.0, 7.0, 'C-04-15'),
  ('TSK-0007', 2, 'move',     'OUT-2 이동',    108.0,  76.0, 0.0, NULL),
  ('TSK-0007', 3, 'place',    'OUT-2 폐기 반출',108.0,  76.0, 6.0, 'OUT-2'),

  ('TSK-0008', 0, 'move',     'C-04-15 이동',   87.9,  61.0, 0.0, NULL),
  ('TSK-0008', 1, 'pick',     'C-04-15 집품',   87.9,  61.0, 7.0, 'C-04-15'),
  ('TSK-0008', 2, 'move',     'OUT-1 이동',     96.0,  76.0, 0.0, NULL),

  ('TSK-0009', 0, 'move',     'WS-1 이동',      30.0,  68.0, 0.0, NULL),
  ('TSK-0009', 1, 'handover', 'W-01 수령',      30.0,  68.0, 10.0, 'WS-1');


-- ---------------------------------------------------------------------------
-- RMF Control UI 작업 (rmf_ui_tasks / rmf_ui_task_history) — 시드하지 않는다
--
-- 작업은 맵 프로젝트에 속한다(schema v4). payload 안의 단계가 그 맵의 Waypoint
-- 좌표와 이름을 그대로 담기 때문에, 담을 프로젝트 없이 넣으면 아무 데도
-- 가리키지 않는 목적지를 든 작업이 된다. 맵 프로젝트가 하나도 없는데 대시보드에
-- 작업이 보이던 것이 정확히 그 상태였다.
--
-- 작업을 보려면 앱에서 `프로젝트 저장`으로 맵을 등록한 뒤 그 프로젝트 안에서
-- 만든다.
-- ---------------------------------------------------------------------------


-- ---------------------------------------------------------------------------
-- 운행 이력 · 안전
-- severity 는 Severity.name (info/warning/serious/critical).
-- ---------------------------------------------------------------------------
INSERT INTO `events`
  (`at`, `severity`, `category`, `source`, `message`, `task_id`, `order_id`) VALUES
  (NOW(6) - INTERVAL 21 DAY,     'info',     'inbound',       'fleet_engine',  '입고 적치 완료: LOT-0001 240개',            'TSK-0001', NULL),
  (NOW(6) - INTERVAL  7 DAY,     'serious',  'task_failed',   'fleet_engine',  '집품 위치 자원 점유 해제 실패 — 3회 재시도 후 중단', 'TSK-0008', 'ORD-0002'),
  (NOW(6) - INTERVAL  7 DAY,     'warning',  'order_partial', 'fleet_engine',  '주문 부분 완료: 2줄 중 1줄 실패',            NULL,       'ORD-0002'),
  (NOW(6) - INTERVAL  2 DAY,     'info',     'task_cancelled','fleet_engine',  '상위 주문 취소로 태스크 취소',               'TSK-0009', NULL),
  (NOW(6) - INTERVAL 90 MINUTE,  'warning',  'expiry',        'fleet_engine',  '유통기한 경과 로트 감지: LOT-0012 — 회수 지시', 'TSK-0007', NULL),
  (NOW(6) - INTERVAL 40 MINUTE,  'critical', 'safety',        'safety_monitor','냉장 구획 바닥 결빙 감지 — 해당 구역 서행',   NULL,       NULL),
  (NOW(6) - INTERVAL 22 MINUTE,  'info',     'order_dispatch','rmf_control_ui','주문 자동 분류 및 작업 생성: TSK-0002',      'TSK-0002', 'ORD-0003'),
  (NOW(6) - INTERVAL 18 MINUTE,  'info',     'order_dispatch','rmf_control_ui','주문 자동 분류 및 작업 생성: TSK-0003',      'TSK-0003', 'ORD-0003'),
  (NOW(6) - INTERVAL 12 MINUTE,  'info',     'task_started',  'fleet_engine',  'RS-05 냉동 집품 시작',                       'TSK-0004', 'ORD-0003'),
  (NOW(6) - INTERVAL  9 MINUTE,  'warning',  'blocked',       'fleet_engine',  'RS-06 자원 대기 — F-03-19 점유 중',          'TSK-0005', NULL),
  (NOW(6) - INTERVAL  5 MINUTE,  'info',     'battery',       'fleet_engine',  'RS-04 충전 시작 (41.8%)',                    NULL,       NULL),
  (NOW(6) - INTERVAL  2 MINUTE,  'info',     'telemetry',     'fleet_engine',  '로봇 8대 정상 · 예비 2대 대기',              NULL,       NULL);

-- actions 는 저장소 계층이 구분자로 이어 붙인 조치 이력 문자열이다.
INSERT INTO `incidents`
  (`id`, `type`, `at`, `description`, `zone`, `pos_x`, `pos_y`, `radius`, `active`, `cleared_at`, `actions`) VALUES
  ('INC-0001', 'spill',           NOW(6) - INTERVAL 40 MINUTE, '냉장 구획 통로 바닥 결빙',        'chilled', 70.0, 46.0, 6.0, 1, NULL,                        '감지|해당 구역 서행 지시|W-05 확인 요청'),
  ('INC-0002', 'workerEmergency', NOW(6) - INTERVAL  6 DAY,    '작업자 낙상 신고 — 오인 신고로 확인', 'ambient', 30.0, 68.0, 4.0, 0, NOW(6) - INTERVAL 6 DAY + INTERVAL 11 MINUTE, '신고 접수|WS-1 주변 로봇 정지|현장 확인|오인 확인 후 해제'),
  ('INC-0003', 'powerCut',        NOW(6) - INTERVAL 28 DAY,    '냉동 구획 순간 정전 (12초)',      'frozen',  100.0, 38.0, 20.0, 0, NOW(6) - INTERVAL 28 DAY + INTERVAL 25 MINUTE, '정전 감지|냉동 구획 전 로봇 정지|복전 확인|온도 정상 확인 후 해제');


-- ---------------------------------------------------------------------------
-- ID 시퀀스 — 위에서 쓴 최대 번호와 맞춰 둔다. 앱이 여기서 이어서 발번한다.
-- 이름은 fleet_engine `_counterOf` 의 값(task/order/lot/incident)이다.
-- ---------------------------------------------------------------------------
INSERT INTO `counters` (`name`, `value`) VALUES
  ('task',     9),
  ('order',    6),
  ('lot',     12),
  ('incident', 3);

COMMIT;


-- ---------------------------------------------------------------------------
-- 적재 결과 확인
-- ---------------------------------------------------------------------------
SELECT
  (SELECT COUNT(*) FROM `robots`)              AS `robots`,
  (SELECT COUNT(*) FROM `robot_telemetry`)     AS `telemetry`,
  (SELECT COUNT(*) FROM `workers`)             AS `workers`,
  (SELECT COUNT(*) FROM `lots`)                AS `lots`,
  (SELECT COUNT(*) FROM `stock_moves`)         AS `stock_moves`,
  (SELECT COUNT(*) FROM `orders`)              AS `orders`,
  (SELECT COUNT(*) FROM `order_lines`)         AS `order_lines`,
  (SELECT COUNT(*) FROM `tasks`)               AS `tasks`,
  (SELECT COUNT(*) FROM `task_steps`)          AS `task_steps`,
  (SELECT COUNT(*) FROM `events`)              AS `events`,
  (SELECT COUNT(*) FROM `incidents`)           AS `incidents`,
  (SELECT COUNT(*) FROM `counters`)            AS `counters`,
  (SELECT `version` FROM `schema_version` WHERE `id` = 1) AS `schema_version`;
