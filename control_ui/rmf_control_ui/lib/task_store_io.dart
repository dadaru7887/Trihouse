import 'dart:convert';
import 'dart:io';

Map<String, String> _mysqlEnvironment() {
  final password =
      Platform.environment['ROBOSAPIENS_DB_PASSWORD'] ?? 'robosapiens';
  return {...Platform.environment, 'MYSQL_PWD': password};
}

List<String> _mysqlArguments() => [
  '--batch',
  '--raw',
  '--skip-column-names',
  '--host=${Platform.environment['ROBOSAPIENS_DB_HOST'] ?? '127.0.0.1'}',
  '--port=${Platform.environment['ROBOSAPIENS_DB_PORT'] ?? '3306'}',
  '--user=${Platform.environment['ROBOSAPIENS_DB_USER'] ?? 'root'}',
  Platform.environment['ROBOSAPIENS_DB_NAME'] ?? 'robosapiens',
];

Future<String> _query(String sql) async {
  final process = await Process.start(
    'mysql',
    _mysqlArguments(),
    environment: _mysqlEnvironment(),
  );
  process.stdin.write(sql);
  await process.stdin.close();
  final outputFuture = process.stdout.transform(utf8.decoder).join();
  final errorFuture = process.stderr.transform(utf8.decoder).join();
  final exitCode = await process.exitCode;
  final output = await outputFuture;
  final error = await errorFuture;
  if (exitCode != 0) {
    throw StateError('MySQL 작업 실패: ${error.trim()}');
  }
  return output.trim();
}

/// `map_name` 은 utf8mb4_unicode_ci 컬럼인데 사용자 변수는 접속 collation
/// (MySQL 8 기본 utf8mb4_0900_ai_ci)을 따라간다. 비교할 때마다 맞춰 준다.
const String _nameParam = '(@map_name COLLATE utf8mb4_unicode_ci)';

/// 열려 있는 맵 프로젝트를 잡는 SQL 머리말.
///
/// 작업은 맵 프로젝트에 속한다 — payload 안의 단계가 그 맵의 Waypoint 좌표를
/// 그대로 들고 있어서, 다른 맵에서 꺼내면 아무 데도 가리키지 않기 때문이다.
/// 이름에 해당하는 프로젝트가 없으면 @project_id 가 NULL 이 되고, 뒤따르는
/// INSERT 가 NOT NULL 위반으로 즉시 멈춘다. 조용히 엉뚱한 맵에 붙는 것보다
/// 낫다.
String _projectPreamble(String mapName) =>
    "SET @map_name = CONVERT(FROM_BASE64('${base64Encode(utf8.encode(mapName))}') USING utf8mb4);\n"
    'SET @project_id = (SELECT id FROM map_projects WHERE map_name = $_nameParam);';

/// [mapName] 프로젝트에 저장된 작업 목록. 프로젝트가 없으면 빈 목록이다.
///
/// 스키마는 db/schema.sql 이 갖는다. 예전에는 이 자리에서 CREATE TABLE 을
/// 했지만, 그러면 map_project_id 가 없는 옛 모양의 표가 새로 생겨 버린다.
Future<String?> loadSavedTasks(String mapName) async {
  final output = await _query('''
${_projectPreamble(mapName)}
SELECT COALESCE(JSON_ARRAYAGG(payload), JSON_ARRAY())
FROM rmf_ui_tasks
WHERE map_project_id = @project_id;
''');
  return output.isEmpty ? '[]' : output.split('\n').last;
}

/// [mapName] 프로젝트의 작업 목록을 [contents] 스냅샷으로 통째로 맞춘다.
///
/// 증분이 아니라 전체 치환이다. 다른 프로젝트의 작업은 건드리지 않는다.
Future<void> saveTasks(String mapName, String contents) async {
  final snapshot = base64Encode(utf8.encode(contents));
  await _query('''
${_projectPreamble(mapName)}
SET @snapshot = CAST(CONVERT(FROM_BASE64('$snapshot') USING utf8mb4) AS JSON);
START TRANSACTION;

INSERT INTO rmf_ui_task_history
  (map_project_id, task_id, event_type, payload, recorded_at)
SELECT @project_id, incoming.id, 'created', incoming.payload, NOW(6)
FROM JSON_TABLE(
  @snapshot,
  '\$[*]' COLUMNS (
    id VARCHAR(64) PATH '\$.id',
    payload JSON PATH '\$'
  )
) AS incoming
LEFT JOIN rmf_ui_tasks existing
  ON existing.map_project_id = @project_id
 AND existing.id = (incoming.id COLLATE utf8mb4_unicode_ci)
WHERE existing.id IS NULL;

INSERT INTO rmf_ui_task_history
  (map_project_id, task_id, event_type, payload, recorded_at)
SELECT
  @project_id,
  incoming.id,
  CASE
    WHEN JSON_UNQUOTE(JSON_EXTRACT(existing.payload, '\$.status')) <> incoming.status
      THEN 'status_changed'
    ELSE 'updated'
  END,
  incoming.payload,
  NOW(6)
FROM JSON_TABLE(
  @snapshot,
  '\$[*]' COLUMNS (
    id VARCHAR(64) PATH '\$.id',
    status VARCHAR(32) PATH '\$.status',
    payload JSON PATH '\$'
  )
) AS incoming
JOIN rmf_ui_tasks existing
  ON existing.map_project_id = @project_id
 AND existing.id = (incoming.id COLLATE utf8mb4_unicode_ci)
WHERE NOT (existing.payload <=> incoming.payload);

INSERT INTO rmf_ui_task_history
  (map_project_id, task_id, event_type, payload, recorded_at)
SELECT @project_id, existing.id, 'deleted', existing.payload, NOW(6)
FROM rmf_ui_tasks existing
LEFT JOIN JSON_TABLE(
  @snapshot,
  '\$[*]' COLUMNS (id VARCHAR(64) PATH '\$.id')
) AS incoming
  ON existing.id = (incoming.id COLLATE utf8mb4_unicode_ci)
WHERE existing.map_project_id = @project_id AND incoming.id IS NULL;

INSERT INTO rmf_ui_tasks
  (map_project_id, id, name, status, payload, created_at, updated_at)
SELECT
  @project_id,
  incoming.id,
  incoming.name,
  incoming.status,
  incoming.payload,
  STR_TO_DATE(incoming.created_at, '%Y-%m-%dT%H:%i:%s.%f'),
  NOW(6)
FROM JSON_TABLE(
  @snapshot,
  '\$[*]' COLUMNS (
    id VARCHAR(64) PATH '\$.id',
    name VARCHAR(255) PATH '\$.name',
    status VARCHAR(32) PATH '\$.status',
    created_at VARCHAR(64) PATH '\$.createdAt',
    payload JSON PATH '\$'
  )
) AS incoming
ON DUPLICATE KEY UPDATE
  name = VALUES(name),
  status = VALUES(status),
  payload = VALUES(payload),
  updated_at = NOW(6);

DELETE existing
FROM rmf_ui_tasks existing
LEFT JOIN JSON_TABLE(
  @snapshot,
  '\$[*]' COLUMNS (id VARCHAR(64) PATH '\$.id')
) AS incoming
  ON existing.id = (incoming.id COLLATE utf8mb4_unicode_ci)
WHERE existing.map_project_id = @project_id AND incoming.id IS NULL;

COMMIT;
''');
}

Future<String> loadPendingOrders() async {
  final output = await _query('''
SELECT COALESCE(JSON_ARRAYAGG(order_data), JSON_ARRAY())
FROM (
  SELECT JSON_OBJECT(
    'id', orders.id,
    'customer', orders.customer,
    'urgency', orders.urgency,
    'zones', COALESCE(
      (
        SELECT JSON_ARRAYAGG(
          COALESCE(
            (
              SELECT lots.zone
              FROM lots
              WHERE lots.sku = order_lines.sku AND lots.qty > lots.reserved
              ORDER BY lots.expiry
              LIMIT 1
            ),
            'ambient'
          )
        )
        FROM order_lines
        WHERE order_lines.order_id = orders.id
      ),
      JSON_ARRAY('ambient')
    )
  ) AS order_data
  FROM orders
  WHERE expanded = 0
  ORDER BY created_at
  LIMIT 20
) pending;
''');
  return output.isEmpty ? '[]' : output.split('\n').last;
}

Future<void> markOrderDispatched(String orderId, String taskId) async {
  final encodedOrderId = base64Encode(utf8.encode(orderId));
  final encodedTaskId = base64Encode(utf8.encode(taskId));
  await _query('''
SET @order_id = CONVERT(FROM_BASE64('$encodedOrderId') USING utf8mb4);
SET @task_id = CONVERT(FROM_BASE64('$encodedTaskId') USING utf8mb4);
START TRANSACTION;
UPDATE orders SET expanded = 1
WHERE id = (@order_id COLLATE utf8mb4_unicode_ci) AND expanded = 0;
INSERT INTO events (
  at, severity, category, source, message, task_id, order_id
)
SELECT
  NOW(6), 'info', 'order_dispatch', 'rmf_control_ui',
  CONCAT('주문 자동 분류 및 작업 생성: ', @task_id), @task_id, @order_id
WHERE ROW_COUNT() > 0;
COMMIT;
''');
}
