/// 운영 분석이 읽는 기록을 MySQL 에서 가져온다.
///
/// 설정 기록(`map_project_changes`)과 운영 기록(`events` · `tasks` · `orders` ·
/// `incidents` · `stock_moves`)을 **같은 시간축**에 놓는다. 어제까지 되던 것이
/// 오늘 안 되면 그 사이에 무엇을 바꿨는지 함께 봐야 한다.
///
/// map_project_store_io.dart 와 같은 방식으로 `mysql` 클라이언트를 직접 부르고
/// 값은 base64 로 실어 나른다. 메시지에 따옴표·줄바꿈이 섞여 있어 이스케이프를
/// 손으로 맞추는 건 위험하다.
library;

import 'dart:convert';
import 'dart:io';

import 'operations_log_models.dart';

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
    throw StateError('운영 기록 조회 실패: ${error.trim()}');
  }
  return output.trim();
}

String _encode(String value) => base64Encode(utf8.encode(value));

String _decodeResult(String output) {
  if (output.isEmpty) return '';
  final line = output.split('\n').last.trim();
  if (line.isEmpty || line == 'NULL') return '';
  return utf8.decode(base64Decode(line));
}

String _toBase64(String expression) =>
    "REPLACE(REPLACE(TO_BASE64($expression), '\\n', ''), '\\r', '')";

/// 갈래마다 `at` 컬럼 이름이 다르다. 한자리에 모아 둔다.
///
/// 작업은 만든 때(`created_at`)를 기준으로 센다. 끝난 때로 세면 아직 도는 것이
/// 어느 날에도 안 잡힌다.
const Map<String, ({String table, String at})> _sources = {
  'task': (table: 'tasks', at: 'created_at'),
  'order': (table: 'orders', at: 'created_at'),
  'event': (table: 'events', at: 'at'),
  'incident': (table: 'incidents', at: 'at'),
  'stock': (table: 'stock_moves', at: 'at'),
};

/// 갈래별 건수를 `달` 또는 `날짜` 로 묶는 SQL 을 만든다.
String _bucketUnion(String bucketExpression, String where) => [
  for (final entry in _sources.entries)
    "SELECT '${entry.key}' AS kind, "
        "${bucketExpression.replaceAll('@at', entry.value.at)} AS bucket, "
        'COUNT(*) AS n FROM ${entry.value.table} '
        "WHERE ${where.replaceAll('@at', entry.value.at)} "
        'GROUP BY bucket',
  "SELECT 'setting' AS kind, "
      "${bucketExpression.replaceAll('@at', 'at')} AS bucket, "
      'COUNT(*) AS n FROM map_project_changes '
      "WHERE ${where.replaceAll('@at', 'at')} "
      'GROUP BY bucket',
].join('\n  UNION ALL\n  ');

/// 기록이 있는 달 목록. 최근 달이 먼저 온다.
Future<List<OperationMonth>> loadOperationMonths() async {
  final union = _bucketUnion("DATE_FORMAT(@at, '%Y-%m')", '@at IS NOT NULL');
  final output = await _query('''
SELECT ${_toBase64('''CAST(
  COALESCE(
    (SELECT JSON_ARRAYAGG(JSON_OBJECT('kind', kind, 'bucket', bucket, 'n', n))
     FROM ($union) AS b),
    JSON_ARRAY()
  ) AS CHAR
)''')};
''');
  final decoded = _decodeResult(output);
  if (decoded.isEmpty) return const [];
  final rows = (jsonDecode(decoded) as List<dynamic>)
      .cast<Map<String, dynamic>>();
  final byMonth = <String, Map<OperationLogKind, int>>{};
  for (final row in rows) {
    final bucket = row['bucket'] as String?;
    if (bucket == null || bucket.length < 7) continue;
    final counts = byMonth.putIfAbsent(bucket, () => {});
    final kind = OperationLogKind.parse(row['kind'] as String);
    counts[kind] = (counts[kind] ?? 0) + (row['n'] as num).toInt();
  }
  final months = [
    for (final entry in byMonth.entries)
      OperationMonth(
        year: int.parse(entry.key.substring(0, 4)),
        month: int.parse(entry.key.substring(5, 7)),
        counts: entry.value,
      ),
  ]..sort((a, b) => b.key.compareTo(a.key));
  return months;
}

/// 고른 달의 날짜별 건수. 기록이 없는 날은 빠진다.
Future<List<OperationDay>> loadOperationDays(int year, int month) async {
  final prefix = '$year-${month.toString().padLeft(2, '0')}';
  final union = _bucketUnion(
    'DATE(@at)',
    "DATE_FORMAT(@at, '%Y-%m') = '$prefix'",
  );
  final output = await _query('''
SELECT ${_toBase64('''CAST(
  COALESCE(
    (SELECT JSON_ARRAYAGG(JSON_OBJECT('kind', kind, 'bucket', bucket, 'n', n))
     FROM ($union) AS b),
    JSON_ARRAY()
  ) AS CHAR
)''')};
''');
  final decoded = _decodeResult(output);
  if (decoded.isEmpty) return const [];
  final rows = (jsonDecode(decoded) as List<dynamic>)
      .cast<Map<String, dynamic>>();
  final byDay = <String, Map<OperationLogKind, int>>{};
  for (final row in rows) {
    final bucket = row['bucket'] as String?;
    if (bucket == null || bucket.length < 10) continue;
    final counts = byDay.putIfAbsent(bucket.substring(0, 10), () => {});
    final kind = OperationLogKind.parse(row['kind'] as String);
    counts[kind] = (counts[kind] ?? 0) + (row['n'] as num).toInt();
  }
  final days = [
    for (final entry in byDay.entries)
      OperationDay(date: DateTime.parse(entry.key), counts: entry.value),
  ]..sort((a, b) => a.date.compareTo(b.date));
  return days;
}

/// 하루치 기록 전부. 시각 순으로 온다.
///
/// 설정과 운영을 섞어서 돌려준다. 따로 보면 "설정을 바꾼 직후에 작업이 실패했다"
/// 같은 것이 눈에 띄지 않는다.
Future<List<OperationEntry>> loadOperationEntries(DateTime day) async {
  final date =
      '${day.year}-${day.month.toString().padLeft(2, '0')}-'
      '${day.day.toString().padLeft(2, '0')}';
  // 각 갈래에서 같은 모양으로 뽑아 하나로 잇는다. 제목·상세는 base64 로 실어
  // 나르므로 따옴표가 섞여도 안전하다.
  String pick(String expression) => "TO_BASE64($expression)";
  final union =
      '''
SELECT DATE_FORMAT(c.at, '%Y-%m-%dT%H:%i:%s') AS at, 'setting' AS kind,
       ${pick("CONCAT_WS(CHAR(9), c.category, c.action, c.target)")} AS title,
       ${pick('c.summary')} AS detail,
       NULL AS severity, ${pick('p.map_name')} AS project
FROM map_project_changes c JOIN map_projects p ON p.id = c.project_id
WHERE DATE(c.at) = '$date'
UNION ALL
SELECT DATE_FORMAT(created_at, '%Y-%m-%dT%H:%i:%s'), 'task',
       ${pick("CONCAT(id, ' ', title)")},
       ${pick('''CONCAT_WS(' · ', CONCAT('상태 ', state), CONCAT('긴급도 ', urgency),
         NULLIF(CONCAT('로봇 ', COALESCE(robot_id, '')), '로봇 '),
         NULLIF(CONCAT(origin_label, ' → ', dest_label), ' → '))''')},
       ${pick('state')}, NULL
FROM tasks WHERE DATE(created_at) = '$date'
UNION ALL
SELECT DATE_FORMAT(created_at, '%Y-%m-%dT%H:%i:%s'), 'order',
       ${pick("CONCAT(id, ' ', customer)")},
       ${pick('''CONCAT_WS(' · ', CONCAT('상태 ', state), CONCAT('긴급도 ', urgency),
         CONCAT(done_lines, '/', line_count, ' 라인'))''')},
       ${pick('state')}, NULL
FROM orders WHERE DATE(created_at) = '$date'
UNION ALL
SELECT DATE_FORMAT(at, '%Y-%m-%dT%H:%i:%s'), 'event',
       ${pick("CONCAT(category, ' · ', source)")}, ${pick('message')},
       ${pick('severity')}, NULL
FROM events WHERE DATE(at) = '$date'
UNION ALL
SELECT DATE_FORMAT(at, '%Y-%m-%dT%H:%i:%s'), 'incident',
       ${pick("CONCAT(id, ' ', type)")},
       ${pick("CONCAT_WS(' · ', description, CONCAT('구역 ', zone))")},
       ${pick("IF(active, 'active', 'cleared')")}, NULL
FROM incidents WHERE DATE(at) = '$date'
UNION ALL
SELECT DATE_FORMAT(at, '%Y-%m-%dT%H:%i:%s'), 'stock',
       ${pick("CONCAT(sku, ' ', IF(delta >= 0, '+', ''), delta)")},
       ${pick("CONCAT_WS(' · ', CONCAT('로트 ', lot_id), CONCAT('잔량 ', qty_after), reason, note)")},
       NULL, NULL
FROM stock_moves WHERE DATE(at) = '$date'
''';
  final output = await _query('''
SELECT ${_toBase64('''CAST(
  COALESCE(
    (SELECT JSON_ARRAYAGG(JSON_OBJECT(
       'at', at, 'kind', kind, 'title', title, 'detail', detail,
       'severity', severity, 'project', project))
     FROM ($union) AS u),
    JSON_ARRAY()
  ) AS CHAR
)''')};
''');
  final decoded = _decodeResult(output);
  if (decoded.isEmpty) return const [];
  String? text(Object? value) {
    if (value == null) return null;
    // MySQL 의 TO_BASE64 는 76자마다 개행을 넣는다.
    final cleaned = value.toString().replaceAll(RegExp(r'[\r\n]'), '');
    if (cleaned.isEmpty) return null;
    return utf8.decode(base64Decode(cleaned));
  }

  final entries = [
    for (final row
        in (jsonDecode(decoded) as List<dynamic>).cast<Map<String, dynamic>>())
      OperationEntry(
        at: DateTime.parse(row['at'] as String),
        kind: OperationLogKind.parse(row['kind'] as String),
        title: formatEntryTitle(
          OperationLogKind.parse(row['kind'] as String),
          text(row['title']) ?? '',
        ),
        detail: text(row['detail']) ?? '',
        severity: text(row['severity']),
        project: text(row['project']),
      ),
  ]..sort((a, b) => a.at.compareTo(b.at));
  return entries;
}

/// 설정 변경을 기록한다. 빈 목록이면 아무것도 하지 않는다.
///
/// 프로젝트를 저장할 때마다 부른다. 바뀐 것이 없으면 남기지 않는다 — 저장을
/// 누를 때마다 줄이 늘면 무엇이 실제로 달라졌는지 오히려 안 보인다.
Future<void> recordMapProjectChanges(
  String mapName,
  List<MapProjectChange> changes,
) async {
  if (changes.isEmpty) return;
  final payload = jsonEncode([
    for (final change in changes)
      {
        'category': change.category,
        'action': change.action,
        'target': change.target,
        'summary': change.summary,
      },
  ]);
  await _query('''
SET @map_name = CONVERT(FROM_BASE64('${_encode(mapName)}') USING utf8mb4);
SET @changes  = CONVERT(FROM_BASE64('${_encode(payload)}') USING utf8mb4);
SET @project_id = (SELECT id FROM map_projects
                   WHERE map_name = (@map_name COLLATE utf8mb4_unicode_ci));

INSERT INTO map_project_changes (project_id, at, category, action, target, summary)
SELECT @project_id, NOW(6), c.category, c.action, c.target,
       COALESCE(c.summary, '')
FROM JSON_TABLE(
  @changes,
  '\$[*]' COLUMNS (
    category VARCHAR(32)  PATH '\$.category',
    action   VARCHAR(16)  PATH '\$.action',
    target   VARCHAR(255) PATH '\$.target',
    summary  VARCHAR(512) PATH '\$.summary'
  )
) AS c
WHERE @project_id IS NOT NULL AND c.category IS NOT NULL;
''');
}
