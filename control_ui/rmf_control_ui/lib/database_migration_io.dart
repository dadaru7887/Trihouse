import 'dart:convert';
import 'dart:io';

import 'database_migration_models.dart';

Map<String, String> _environment() => {
  ...Platform.environment,
  'MYSQL_PWD': Platform.environment['ROBOSAPIENS_DB_PASSWORD'] ?? 'robosapiens',
};

String get _host => Platform.environment['ROBOSAPIENS_DB_HOST'] ?? '127.0.0.1';
String get _port => Platform.environment['ROBOSAPIENS_DB_PORT'] ?? '3306';
String get _user => Platform.environment['ROBOSAPIENS_DB_USER'] ?? 'root';
String get _database =>
    Platform.environment['ROBOSAPIENS_DB_NAME'] ?? 'robosapiens';

List<String> _connectionArgs({bool database = false}) => [
  '--batch',
  '--raw',
  '--skip-column-names',
  '--default-character-set=utf8mb4',
  '--host=$_host',
  '--port=$_port',
  '--user=$_user',
  if (database) _database,
];

Directory _projectRoot() {
  final configured = Platform.environment['RMF_ROOT'];
  if (configured != null && configured.isNotEmpty) {
    final root = Directory(configured).absolute;
    if (File('${root.path}/db/schema.sql').existsSync()) return root;
  }
  var directory = Directory.current.absolute;
  for (var i = 0; i < 8; i++) {
    if (File('${directory.path}/db/schema.sql').existsSync()) return directory;
    if (directory.parent.path == directory.path) break;
    directory = directory.parent;
  }
  throw StateError('db/schema.sql이 있는 프로젝트 루트를 찾지 못했습니다.');
}

Future<String> _query(String sql, {bool database = false}) async {
  final process = await Process.start(
    'mysql',
    _connectionArgs(database: database),
    environment: _environment(),
  );
  process.stdin.write(sql);
  await process.stdin.close();
  final outputFuture = process.stdout.transform(utf8.decoder).join();
  final errorFuture = process.stderr.transform(utf8.decoder).join();
  final code = await process.exitCode;
  final output = await outputFuture;
  final error = await errorFuture;
  if (code != 0) throw StateError('MySQL 스키마 작업 실패: ${error.trim()}');
  return output.trim();
}

Future<void> _apply(File sql, {bool database = false}) async {
  if (!RegExp(r'^[A-Za-z0-9_]+$').hasMatch(_database)) {
    throw StateError('ROBOSAPIENS_DB_NAME에는 영문·숫자·밑줄만 사용할 수 있습니다.');
  }
  final process = await Process.start(
    'mysql',
    _connectionArgs(database: database),
    environment: _environment(),
  );
  // 배포 환경이 별도 DB 이름을 쓰더라도 schema/migration의 기본 이름을 그
  // 환경에 맞춘다. 식별자는 위에서 엄격하게 검증했으므로 SQL 삽입이 없다.
  final contents = (await sql.readAsString()).replaceAll(
    '`robosapiens`',
    '`$_database`',
  );
  process.stdin.write(contents);
  await process.stdin.close();
  final errorFuture = process.stderr.transform(utf8.decoder).join();
  final code = await process.exitCode;
  final error = await errorFuture;
  if (code != 0) {
    throw StateError('${sql.path} 적용 실패: ${error.trim()}');
  }
}

Future<String> _backup(Directory root) async {
  final backupDir = Directory('${root.path}/db/backups');
  await backupDir.create(recursive: true);
  final now = DateTime.now().toUtc().toIso8601String().replaceAll(':', '-');
  final backup = File('${backupDir.path}/${_database}_before_$now.sql');
  final process = await Process.start('mysqldump', [
    '--single-transaction',
    '--routines',
    '--triggers',
    '--default-character-set=utf8mb4',
    '--host=$_host',
    '--port=$_port',
    '--user=$_user',
    _database,
  ], environment: _environment());
  final sink = backup.openWrite();
  final outputFuture = sink.addStream(process.stdout).whenComplete(sink.close);
  final errorFuture = process.stderr.transform(utf8.decoder).join();
  final code = await process.exitCode;
  await outputFuture;
  final error = await errorFuture;
  if (code != 0) {
    if (await backup.exists()) await backup.delete();
    throw StateError('DB 백업 실패로 migration을 중단했습니다: ${error.trim()}');
  }
  return backup.path;
}

Future<DatabaseMigrationResult> migrateDatabaseSchema() async {
  final root = _projectRoot();
  final schema = File('${root.path}/db/schema.sql');
  final schemaText = await schema.readAsString();
  final latestMatches = RegExp(
    r'VALUES\s*\(1,\s*(\d+)',
    multiLine: true,
  ).allMatches(schemaText).toList();
  if (latestMatches.isEmpty) {
    throw StateError('schema.sql에서 최신 schema version을 찾지 못했습니다.');
  }
  final latest = int.parse(latestMatches.last.group(1)!);
  final escapedDb = _database.replaceAll("'", "''");
  final exists = await _query(
    "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='$escapedDb';",
  );
  if (exists.trim() == '0') {
    await _apply(schema);
    return DatabaseMigrationResult(
      fromVersion: null,
      toVersion: latest,
      applied: ['schema.sql'],
    );
  }
  final versionTable = await _query(
    "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='$escapedDb' AND TABLE_NAME='schema_version';",
  );
  if (versionTable.trim() == '0') {
    throw StateError(
      '기존 DB에 schema_version 테이블이 없습니다. 자동으로 버전을 추정할 수 없어 변경하지 않았습니다.',
    );
  }
  final versionText = await _query(
    'SELECT version FROM schema_version WHERE id=1;',
    database: true,
  );
  final current = int.tryParse(versionText.split('\n').last.trim());
  if (current == null) throw StateError('현재 DB schema version을 읽지 못했습니다.');
  final migrationFiles = <int, File>{};
  await for (final entity in Directory('${root.path}/db').list()) {
    if (entity is! File) continue;
    final match = RegExp(
      r'migrate_v(\d+)_to_v(\d+)\.sql$',
    ).firstMatch(entity.path);
    if (match == null) continue;
    final from = int.parse(match.group(1)!);
    final to = int.parse(match.group(2)!);
    if (to == from + 1) migrationFiles[to] = entity;
  }
  final targets = requiredMigrationTargets(
    current: current,
    latest: latest,
    availableTargets: migrationFiles.keys.toSet(),
  );
  if (targets.isEmpty) {
    return DatabaseMigrationResult(
      fromVersion: current,
      toVersion: latest,
      applied: const [],
    );
  }
  final backup = await _backup(root);
  final applied = <String>[];
  for (final target in targets) {
    final file = migrationFiles[target]!;
    await _apply(file, database: true);
    applied.add(file.uri.pathSegments.last);
    final actual = await _query(
      'SELECT version FROM schema_version WHERE id=1;',
      database: true,
    );
    if (actual.trim().split('\n').last != '$target') {
      throw StateError('${file.path} 적용 후 schema version이 v$target이 아닙니다.');
    }
  }
  return DatabaseMigrationResult(
    fromVersion: current,
    toVersion: latest,
    applied: applied,
    backupPath: backup,
  );
}
