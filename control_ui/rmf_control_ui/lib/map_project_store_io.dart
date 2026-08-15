/// 맵 프로젝트를 MySQL `robosapiens` 에 프로젝트 이름으로 구분해 담는다.
///
/// 한 관제가 여러 창고를 다루므로 프로젝트가 다르면 Waypoint·Lane·축척·도면이
/// 전부 별개다. `map_projects.map_name` 이 그 구분자이며 UNIQUE 다 — 같은
/// 이름으로 저장하려 하면 앱이 먼저 [mapProjectExists] 로 확인해 덮어쓸지 다른
/// 이름을 쓸지 사용자에게 묻는다.
///
/// **이 이름은 사람이 정한 프로젝트 이름이고 도면 파일 이름과 무관하다.** 컬럼
/// 이름이 `map_name` 인 것은 지도 이름이 곧 구분자였던 시절에 붙은 이름이다.
/// 도면 이름은 `drawing_name` 에 따로 있어서, 같은 도면으로 만든 여러 프로젝트가
/// 서로 다른 행으로 남는다.
///
/// task_store_io.dart 와 같은 방식으로 `mysql` 클라이언트를 직접 부른다. 값은
/// 전부 base64 로 실어 보내고 받는다. 도면 이미지가 통째로 들어간 수백 KB짜리
/// JSON 이라 따옴표·역슬래시·개행 이스케이프를 손으로 맞추는 건 위험하다.
library;

import 'dart:convert';
import 'dart:io';

import 'map_project_models.dart';
import 'simulation_backend.dart';

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
    throw StateError('맵 프로젝트 저장소 접근 실패: ${error.trim()}');
  }
  return output.trim();
}

String _encode(String value) => base64Encode(utf8.encode(value));

/// base64 로 감싸 돌려받은 마지막 줄을 원문으로 되돌린다.
///
/// MySQL 의 `TO_BASE64` 는 76자마다 개행을 넣으므로 그 개행을 SQL 쪽에서 이미
/// 걷어낸 상태로 받는다. 값이 없으면 빈 문자열이 온다.
String _decodeResult(String output) {
  if (output.isEmpty) return '';
  final line = output.split('\n').last.trim();
  if (line.isEmpty || line == 'NULL') return '';
  return utf8.decode(base64Decode(line));
}

/// 컬럼 값을 개행 없는 base64 한 줄로 뽑는 SQL 조각.
String _toBase64(String expression) =>
    "REPLACE(REPLACE(TO_BASE64($expression), '\\n', ''), '\\r', '')";

/// `map_name` 은 utf8mb4_unicode_ci 컬럼인데 사용자 변수는 접속 collation
/// (MySQL 8 기본 utf8mb4_0900_ai_ci)을 따라간다. 그대로 비교하면 illegal mix
/// of collations 로 죽으므로 비교할 때마다 컬럼 쪽에 맞춰 준다.
const String _nameParam = '(@map_name COLLATE utf8mb4_unicode_ci)';

/// 저장된 프로젝트 목록. 도면 바이트는 읽지 않는다.
Future<List<MapProjectSummary>> listMapProjects() async {
  final output = await _query('''
SELECT ${_toBase64('''CAST(
  COALESCE(
    JSON_ARRAYAGG(
      JSON_OBJECT(
        'mapName', map_name,
        'drawingName', drawing_name,
        'waypointCount', waypoint_count,
        'laneCount', lane_count,
        'hasBuildingYaml', building_yaml IS NOT NULL,
        'updatedAt', DATE_FORMAT(updated_at, '%Y-%m-%dT%H:%i:%s.%f')
      )
    ),
    JSON_ARRAY()
  ) AS CHAR
)''')}
FROM map_projects;
''');
  final decoded = _decodeResult(output);
  if (decoded.isEmpty) return const [];
  final rows = jsonDecode(decoded) as List<dynamic>;
  final summaries = [
    for (final row in rows.cast<Map<String, dynamic>>())
      MapProjectSummary(
        mapName: row['mapName'] as String,
        drawingName: row['drawingName'] as String?,
        waypointCount: (row['waypointCount'] as num).toInt(),
        laneCount: (row['laneCount'] as num).toInt(),
        // JSON_OBJECT 안의 `IS NOT NULL` 은 JSON boolean 으로 나온다.
        hasBuildingYaml: row['hasBuildingYaml'] as bool? ?? false,
        updatedAt:
            DateTime.tryParse(row['updatedAt'] as String? ?? '') ??
            DateTime.fromMillisecondsSinceEpoch(0),
      ),
  ];
  // JSON_ARRAYAGG 는 순서를 보장하지 않는다. 최근 저장 순으로 여기서 세운다.
  summaries.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
  return summaries;
}

/// 같은 지도 이름의 프로젝트가 이미 있는지.
Future<bool> mapProjectExists(String mapName) async {
  final output = await _query('''
SET @map_name = CONVERT(FROM_BASE64('${_encode(mapName)}') USING utf8mb4);
SELECT COUNT(*) FROM map_projects WHERE map_name = $_nameParam;
''');
  final line = output.split('\n').last.trim();
  return (int.tryParse(line) ?? 0) > 0;
}

/// 프로젝트를 저장한다. 같은 이름이 있으면 그 프로젝트를 덮어쓴다.
///
/// 호출 전에 [mapProjectExists] 로 확인해 사용자 동의를 받아야 한다 — 이
/// 함수는 이미 결정이 끝났다고 보고 그대로 쓴다.
///
/// `payload` 는 편집 화면을 그대로 되살릴 수 있는 프로젝트 JSON 전체다.
/// 조회용 사본(map_project_waypoints / map_project_lanes)은 그 payload 에서
/// 다시 뽑아 채우므로 두 곳이 어긋날 수 없다.
/// [buildingYaml] 은 배포 쪽이 Flutter 앱을 거치지 않고 바로 집어갈 수 있도록
/// 함께 넣어 둔다. 맵이 아직 YAML 로 만들 수 있는 상태가 아니면 null 이다.
Future<void> saveMapProject({
  required String mapName,
  required String payloadJson,
  String? buildingYaml,
  String? buildingYamlName,
}) async {
  // 도면 바이트는 payload 안에 이미 base64 로 있으니 SQL 에서 뽑아 쓴다.
  // 같은 이미지를 두 번 실어 보낼 이유가 없다.
  final yaml = buildingYaml == null
      ? 'NULL'
      : "CONVERT(FROM_BASE64('${_encode(buildingYaml)}') USING utf8mb4)";
  final yamlName = buildingYamlName == null
      ? 'NULL'
      : "CONVERT(FROM_BASE64('${_encode(buildingYamlName)}') USING utf8mb4)";
  await _query('''
SET @map_name = CONVERT(FROM_BASE64('${_encode(mapName)}') USING utf8mb4);
SET @payload = CAST(
  CONVERT(FROM_BASE64('${_encode(payloadJson)}') USING utf8mb4) AS JSON
);
-- 도면이 없는 프로젝트도 있다. JSON null 을 그대로 FROM_BASE64 에 넘기면
-- 'null' 이라는 문자열을 디코딩해 쓰레기 바이트가 들어가므로 타입을 본다.
SET @drawing_bytes = CASE
  WHEN JSON_TYPE(JSON_EXTRACT(@payload, '\$.drawing.bytes')) = 'STRING'
  THEN FROM_BASE64(JSON_UNQUOTE(JSON_EXTRACT(@payload, '\$.drawing.bytes')))
  ELSE NULL
END;
START TRANSACTION;

INSERT INTO map_projects (
  map_name, format_version, payload,
  drawing_name, drawing_extension, drawing_bytes, drawing_width, drawing_height,
  building_yaml, building_yaml_name,
  waypoint_count, lane_count, created_at, updated_at
)
VALUES (
  @map_name,
  COALESCE(CAST(JSON_EXTRACT(@payload, '\$.version') AS UNSIGNED), 0),
  @payload,
  JSON_UNQUOTE(JSON_EXTRACT(@payload, '\$.drawing.name')),
  JSON_UNQUOTE(JSON_EXTRACT(@payload, '\$.drawing.extension')),
  @drawing_bytes,
  JSON_EXTRACT(@payload, '\$.drawing.pixelWidth'),
  JSON_EXTRACT(@payload, '\$.drawing.pixelHeight'),
  $yaml,
  $yamlName,
  COALESCE(JSON_LENGTH(@payload, '\$.waypoints'), 0),
  COALESCE(JSON_LENGTH(@payload, '\$.laneDirections'), 0),
  NOW(6), NOW(6)
)
ON DUPLICATE KEY UPDATE
  format_version     = VALUES(format_version),
  payload            = VALUES(payload),
  drawing_name       = VALUES(drawing_name),
  drawing_extension  = VALUES(drawing_extension),
  drawing_bytes      = VALUES(drawing_bytes),
  drawing_width      = VALUES(drawing_width),
  drawing_height     = VALUES(drawing_height),
  building_yaml      = VALUES(building_yaml),
  building_yaml_name = VALUES(building_yaml_name),
  waypoint_count     = VALUES(waypoint_count),
  lane_count         = VALUES(lane_count),
  updated_at         = NOW(6);

SET @project_id = (
  SELECT id FROM map_projects WHERE map_name = $_nameParam
);

-- 조회용 사본은 증분이 아니라 통째로 다시 만든다. Waypoint 를 지운 저장이
-- 반영되지 않는 사고를 없애려는 것이다.
DELETE FROM map_project_waypoints WHERE project_id = @project_id;
DELETE FROM map_project_lanes     WHERE project_id = @project_id;

INSERT INTO map_project_waypoints (project_id, seq, name, category, x, y)
SELECT @project_id, wp.seq, COALESCE(wp.name, ''), COALESCE(wp.category, '대기'),
       wp.x, wp.y
FROM JSON_TABLE(
  @payload,
  '\$.waypoints[*]' COLUMNS (
    seq      FOR ORDINALITY,
    name     VARCHAR(128) PATH '\$.name',
    category VARCHAR(32)  PATH '\$.category',
    x        DOUBLE       PATH '\$.point[0]',
    y        DOUBLE       PATH '\$.point[1]'
  )
) AS wp
WHERE wp.x IS NOT NULL AND wp.y IS NOT NULL;

INSERT INTO map_project_lanes (
  project_id, seq, start_x, start_y, end_x, end_y,
  direction, speed_limit, orientation, mutex_group
)
SELECT @project_id, ln.seq, ln.start_x, ln.start_y, ln.end_x, ln.end_y,
       COALESCE(ln.direction, '양방향'), ln.speed_limit, ln.orientation,
       ln.mutex_group
FROM JSON_TABLE(
  @payload,
  '\$.laneDirections[*]' COLUMNS (
    seq         FOR ORDINALITY,
    start_x     DOUBLE      PATH '\$.start[0]',
    start_y     DOUBLE      PATH '\$.start[1]',
    end_x       DOUBLE      PATH '\$.end[0]',
    end_y       DOUBLE      PATH '\$.end[1]',
    direction   VARCHAR(16) PATH '\$.direction',
    speed_limit DOUBLE      PATH '\$.speedLimit',
    orientation VARCHAR(16) PATH '\$.orientation',
    mutex_group VARCHAR(64) PATH '\$.mutex'
  )
) AS ln
WHERE ln.start_x IS NOT NULL AND ln.end_x IS NOT NULL;

COMMIT;
''');
}

/// 프로젝트 JSON 전체를 돌려준다. 없으면 null.
Future<String?> loadMapProject(String mapName) async {
  final output = await _query('''
SET @map_name = CONVERT(FROM_BASE64('${_encode(mapName)}') USING utf8mb4);
SELECT ${_toBase64('CAST(payload AS CHAR)')}
FROM map_projects WHERE map_name = $_nameParam;
''');
  final decoded = _decodeResult(output);
  return decoded.isEmpty ? null : decoded;
}

/// 저장해 둔 building.yaml. 없으면 null.
///
/// 배포 도구가 Flutter 앱을 열지 않고도 맵을 집어갈 수 있게 하는 통로다.
Future<String?> loadMapProjectYaml(String mapName) async {
  final output = await _query('''
SET @map_name = CONVERT(FROM_BASE64('${_encode(mapName)}') USING utf8mb4);
SELECT ${_toBase64('building_yaml')}
FROM map_projects WHERE map_name = $_nameParam;
''');
  final decoded = _decodeResult(output);
  return decoded.isEmpty ? null : decoded;
}

/// 프로젝트를 지운다. Waypoint·Lane 사본은 FK CASCADE 로 함께 사라진다.
Future<void> deleteMapProject(String mapName) async {
  await _query('''
SET @map_name = CONVERT(FROM_BASE64('${_encode(mapName)}') USING utf8mb4);
DELETE FROM map_projects WHERE map_name = $_nameParam;
''');
}

/// 프로젝트에 딸린 설정 파일 전부를 저장한다. 기존 목록은 지우고 다시 넣는다.
///
/// 저장할 때마다 새로 만들어 넣으므로 맵과 어긋나지 않는다. 지운 파일이 남아
/// 도는 일도 없다.
Future<void> saveMapProjectFiles(
  String mapName,
  List<MapProjectFile> files,
) async {
  final rows = [
    for (final file in files)
      {
        'fileName': file.fileName,
        'kind': file.kind,
        'description': file.description,
        'executable': file.executable ? 1 : 0,
        'content': file.content,
      },
  ];
  await _query('''
SET @map_name = CONVERT(FROM_BASE64('${_encode(mapName)}') USING utf8mb4);
SET @project_id = (
  SELECT id FROM map_projects WHERE map_name = $_nameParam
);
SET @files = CAST(
  CONVERT(FROM_BASE64('${_encode(jsonEncode(rows))}') USING utf8mb4) AS JSON
);
START TRANSACTION;
DELETE FROM map_project_files WHERE project_id = @project_id;
INSERT INTO map_project_files
  (project_id, file_name, kind, description, executable, content, generated_at)
SELECT @project_id, f.file_name, f.kind, COALESCE(f.description, ''),
       COALESCE(f.executable, 0), f.content, NOW(6)
FROM JSON_TABLE(
  @files,
  '\$[*]' COLUMNS (
    file_name   VARCHAR(255) PATH '\$.fileName',
    kind        VARCHAR(32)  PATH '\$.kind',
    description VARCHAR(512) PATH '\$.description',
    executable  INT          PATH '\$.executable',
    content     LONGTEXT     PATH '\$.content'
  )
) AS f;
COMMIT;
''');
}

/// 프로젝트에 딸린 설정 파일 목록. 내용까지 함께 돌려준다.
Future<List<MapProjectFile>> loadMapProjectFiles(String mapName) async {
  final aggregate = '''CAST(
  COALESCE(
    JSON_ARRAYAGG(
      JSON_OBJECT(
        'fileName', f.file_name,
        'kind', f.kind,
        'description', f.description,
        'executable', f.executable,
        'content', f.content,
        'generatedAt', DATE_FORMAT(f.generated_at, '%Y-%m-%dT%H:%i:%s.%f')
      )
    ),
    JSON_ARRAY()
  ) AS CHAR
)''';
  final output = await _query('''
SET @map_name = CONVERT(FROM_BASE64('${_encode(mapName)}') USING utf8mb4);
SELECT ${_toBase64(aggregate)}
FROM map_project_files f
JOIN map_projects p ON p.id = f.project_id
WHERE p.map_name = $_nameParam;
''');
  final decoded = _decodeResult(output);
  if (decoded.isEmpty) return const [];
  final rows = jsonDecode(decoded) as List<dynamic>;
  final files = [
    for (final row in rows.cast<Map<String, dynamic>>())
      MapProjectFile(
        fileName: row['fileName'] as String,
        kind: row['kind'] as String? ?? 'etc',
        description: row['description'] as String? ?? '',
        executable: (row['executable'] as num?)?.toInt() == 1,
        content: row['content'] as String? ?? '',
        generatedAt:
            DateTime.tryParse(row['generatedAt'] as String? ?? '') ??
            DateTime.fromMillisecondsSinceEpoch(0),
      ),
  ];
  // JSON_ARRAYAGG 는 순서를 보장하지 않는다. 이름순으로 세운다.
  files.sort((a, b) => a.fileName.compareTo(b.fileName));
  return files;
}

/// 분석 목록용 설정 파일 메타데이터. 큰 원문은 펼칠 때만 따로 읽는다.
Future<List<MapProjectFile>> loadMapProjectFileSummaries(String mapName) async {
  final output = await _query('''
SET @map_name = CONVERT(FROM_BASE64('${_encode(mapName)}') USING utf8mb4);
SELECT ${_toBase64("JSON_OBJECT(\n"
  "  'fileName', f.file_name, 'kind', f.kind, 'description', f.description,\n"
  "  'executable', f.executable, 'contentBytes', OCTET_LENGTH(f.content),\n"
  "  'generatedAt', DATE_FORMAT(f.generated_at, '%Y-%m-%dT%H:%i:%s.%f')\n"
  ")")}
FROM map_project_files f
JOIN map_projects p ON p.id = f.project_id
WHERE p.map_name = $_nameParam
ORDER BY f.file_name;
''');
  if (output.isEmpty) return const [];
  return [
    for (final line in output.split('\n'))
      if (line.trim().isNotEmpty)
        (() {
          final row =
              jsonDecode(utf8.decode(base64Decode(line.trim())))
                  as Map<String, dynamic>;
          return MapProjectFile(
            fileName: row['fileName'] as String,
            kind: row['kind'] as String? ?? 'etc',
            description:
                '${row['description'] as String? ?? ''}'
                ' · 원문 ${(row['contentBytes'] as num? ?? 0)} bytes',
            executable: (row['executable'] as num?)?.toInt() == 1,
            content: '',
            generatedAt:
                DateTime.tryParse(row['generatedAt'] as String? ?? '') ??
                DateTime.fromMillisecondsSinceEpoch(0),
          );
        })(),
  ];
}

/// 분석 화면에서 파일 하나를 펼쳤을 때만 원문을 읽는다.
Future<String?> loadMapProjectFileContent(
  String mapName,
  String fileName,
) async {
  final output = await _query('''
SET @map_name = CONVERT(FROM_BASE64('${_encode(mapName)}') USING utf8mb4);
SET @file_name = CONVERT(FROM_BASE64('${_encode(fileName)}') USING utf8mb4);
SELECT ${_toBase64('LEFT(f.content, 200000)')}
FROM map_project_files f
JOIN map_projects p ON p.id = f.project_id
WHERE p.map_name = $_nameParam AND BINARY f.file_name = BINARY @file_name
LIMIT 1;
''');
  if (output.isEmpty) return null;
  return _decodeResult(output);
}

/// 프로젝트의 플릿 설정과 로봇 목록을 저장한다.
///
/// 로봇의 zones 는 콤마로 이어 붙인 문자열(`zonesText`)로 넘긴다. JSON_TABLE 로
/// 배열을 한 칸에 담을 수 없기 때문이다.
/// 플릿 설정만 저장한다. 로봇 목록은 건드리지 않는다.
///
/// [saveMapProjectFleet] 은 로봇을 통째로 지우고 다시 넣는다. 화면이 로봇을
/// 안 들고 있을 때 그것을 부르면 등록해 둔 로봇이 전부 사라진다 — 실제로
/// 그렇게 셋이 날아갔다.
Future<void> saveMapProjectFleetSettings(
  String mapName,
  Map<String, Object?> settings,
) async {
  await _query('''
SET @map_name = CONVERT(FROM_BASE64('${_encode(mapName)}') USING utf8mb4);
SET @project_id = (
  SELECT id FROM map_projects WHERE map_name = $_nameParam
);
SET @settings = CAST(
  CONVERT(FROM_BASE64('${_encode(jsonEncode(settings))}') USING utf8mb4) AS JSON
);
INSERT INTO map_project_fleets (project_id, fleet_name, settings, updated_at)
VALUES (
  @project_id,
  COALESCE(JSON_UNQUOTE(JSON_EXTRACT(@settings, '\$.fleetName')), 'pinky'),
  @settings,
  NOW(6)
)
ON DUPLICATE KEY UPDATE
  fleet_name = VALUES(fleet_name),
  settings   = VALUES(settings),
  updated_at = NOW(6);
''');
}

Future<void> saveMapProjectFleet(
  String mapName, {
  required Map<String, Object?> settings,
  required List<Map<String, Object?>> robots,
}) async {
  await _query('''
SET @map_name = CONVERT(FROM_BASE64('${_encode(mapName)}') USING utf8mb4);
SET @project_id = (
  SELECT id FROM map_projects WHERE map_name = $_nameParam
);
SET @settings = CAST(
  CONVERT(FROM_BASE64('${_encode(jsonEncode(settings))}') USING utf8mb4) AS JSON
);
SET @robots = CAST(
  CONVERT(FROM_BASE64('${_encode(jsonEncode(robots))}') USING utf8mb4) AS JSON
);
START TRANSACTION;

INSERT INTO map_project_fleets (project_id, fleet_name, settings, updated_at)
VALUES (
  @project_id,
  COALESCE(JSON_UNQUOTE(JSON_EXTRACT(@settings, '\$.fleetName')), 'pinky'),
  @settings,
  NOW(6)
)
ON DUPLICATE KEY UPDATE
  fleet_name = VALUES(fleet_name),
  settings   = VALUES(settings),
  updated_at = NOW(6);

DELETE FROM map_project_robots WHERE project_id = @project_id;
INSERT INTO map_project_robots (
  project_id, robot_id, seq, display_name, model, kind, data_source, gz_name,
  zones, charger_waypoint, spawn_x, spawn_y, spawn_heading
)
SELECT
  @project_id, r.robot_id, r.seq, r.display_name, r.model,
  COALESCE(r.kind, 'mobile'), COALESCE(r.data_source, 'mock'), r.gz_name,
  COALESCE(r.zones, ''), r.charger_waypoint, r.spawn_x, r.spawn_y,
  COALESCE(r.spawn_heading, 0)
FROM JSON_TABLE(
  @robots,
  '\$[*]' COLUMNS (
    seq              FOR ORDINALITY,
    robot_id         VARCHAR(64)  PATH '\$.robotId',
    display_name     VARCHAR(128) PATH '\$.displayName',
    model            VARCHAR(64)  PATH '\$.model',
    kind             VARCHAR(16)  PATH '\$.kind',
    data_source      VARCHAR(16)  PATH '\$.dataSource',
    gz_name          VARCHAR(64)  PATH '\$.gzName',
    zones            VARCHAR(64)  PATH '\$.zonesText',
    charger_waypoint VARCHAR(128) PATH '\$.chargerWaypoint',
    spawn_x          DOUBLE       PATH '\$.spawnX',
    spawn_y          DOUBLE       PATH '\$.spawnY',
    spawn_heading    DOUBLE       PATH '\$.spawnHeading'
  )
) AS r
WHERE r.robot_id IS NOT NULL;

COMMIT;
''');
}

/// 프로젝트의 플릿 설정과 로봇 목록. 설정이 없으면 null.
Future<Map<String, dynamic>?> loadMapProjectFleet(String mapName) async {
  final aggregate =
      '''CAST(
  JSON_OBJECT(
    'settings', (
      SELECT fl.settings FROM map_project_fleets fl
      JOIN map_projects p2 ON p2.id = fl.project_id
      WHERE p2.map_name = $_nameParam
    ),
    'robots', (
      SELECT COALESCE(
        JSON_ARRAYAGG(
          JSON_OBJECT(
            'seq', r.seq,
            'robotId', r.robot_id,
            'displayName', r.display_name,
            'model', r.model,
            'kind', r.kind,
            'dataSource', r.data_source,
            'gzName', r.gz_name,
            'zonesText', r.zones,
            'chargerWaypoint', r.charger_waypoint,
            'spawnX', r.spawn_x,
            'spawnY', r.spawn_y,
            'spawnHeading', r.spawn_heading
          )
        ),
        JSON_ARRAY()
      )
      FROM map_project_robots r
      JOIN map_projects p3 ON p3.id = r.project_id
      WHERE p3.map_name = $_nameParam
    )
  ) AS CHAR
)''';
  final output = await _query('''
SET @map_name = CONVERT(FROM_BASE64('${_encode(mapName)}') USING utf8mb4);
SELECT ${_toBase64(aggregate)};
''');
  final decoded = _decodeResult(output);
  if (decoded.isEmpty) return null;
  final data = jsonDecode(decoded) as Map<String, dynamic>;
  if (data['settings'] == null) return null;
  return data;
}

Future<void> saveProjectSimulationSettings(
  String mapName,
  ProjectSimulationSettings settings,
) async {
  final payload = jsonEncode({
    'backend': settings.backend.storageValue,
    'simulatorGui': settings.simulatorGui,
    'rviz': settings.rviz,
    'gazeboSettings': settings.gazeboSettings,
    'isaacSettings': settings.isaacSettings,
    'coordinateTransform': settings.coordinateTransform,
  });
  await _query('''
SET @map_name = CONVERT(FROM_BASE64('${_encode(mapName)}') USING utf8mb4);
SET @project_id = (SELECT id FROM map_projects WHERE map_name = @map_name);
SET @simulation = CAST(
  CONVERT(FROM_BASE64('${_encode(payload)}') USING utf8mb4) AS JSON
);
INSERT INTO map_project_simulation_settings (
  project_id, default_backend, simulator_gui, rviz_enabled,
  gazebo_settings, isaac_settings, coordinate_transform, updated_at
)
VALUES (
  @project_id,
  JSON_UNQUOTE(JSON_EXTRACT(@simulation, '\$.backend')),
  JSON_EXTRACT(@simulation, '\$.simulatorGui') = TRUE,
  JSON_EXTRACT(@simulation, '\$.rviz') = TRUE,
  JSON_EXTRACT(@simulation, '\$.gazeboSettings'),
  JSON_EXTRACT(@simulation, '\$.isaacSettings'),
  JSON_EXTRACT(@simulation, '\$.coordinateTransform'),
  NOW(6)
)
ON DUPLICATE KEY UPDATE
  default_backend = VALUES(default_backend),
  simulator_gui = VALUES(simulator_gui),
  rviz_enabled = VALUES(rviz_enabled),
  gazebo_settings = VALUES(gazebo_settings),
  isaac_settings = VALUES(isaac_settings),
  coordinate_transform = VALUES(coordinate_transform),
  updated_at = NOW(6);
''');
}

Future<ProjectSimulationSettings> loadProjectSimulationSettings(
  String mapName,
) async {
  final aggregate = '''CAST(JSON_OBJECT(
    'backend', s.default_backend,
    'simulatorGui', s.simulator_gui = 1,
    'rviz', s.rviz_enabled = 1,
    'gazeboSettings', s.gazebo_settings,
    'isaacSettings', s.isaac_settings,
    'coordinateTransform', s.coordinate_transform
  ) AS CHAR)''';
  final output = await _query('''
SET @map_name = CONVERT(FROM_BASE64('${_encode(mapName)}') USING utf8mb4);
SELECT ${_toBase64(aggregate)}
FROM map_project_simulation_settings s
JOIN map_projects p ON p.id = s.project_id
WHERE p.map_name = @map_name;
''');
  final decoded = _decodeResult(output);
  if (decoded.isEmpty) return const ProjectSimulationSettings();
  final data = jsonDecode(decoded) as Map<String, dynamic>;
  Map<String, Object?> objectMap(String key) =>
      Map<String, Object?>.from(data[key] as Map? ?? const {});
  return ProjectSimulationSettings(
    backend: SimulationBackend.parse(data['backend'] as String?),
    simulatorGui: data['simulatorGui'] == true || data['simulatorGui'] == 1,
    rviz: data['rviz'] == true || data['rviz'] == 1,
    gazeboSettings: objectMap('gazeboSettings'),
    isaacSettings: objectMap('isaacSettings'),
    coordinateTransform: objectMap('coordinateTransform'),
  );
}
