/// 웹 빌드용 대체 구현. 브라우저에서는 `mysql` 클라이언트를 실행할 수 없으므로
/// 맵 프로젝트 저장소를 쓸 수 없다. 맵 편집과 YAML 내보내기는 그대로 되고,
/// 프로젝트 저장·불러오기만 파일 방식을 쓰게 된다.
library;

import 'map_project_models.dart';
import 'simulation_backend.dart';

const String _unsupported =
    '웹 빌드에서는 MySQL 맵 프로젝트 저장소를 쓸 수 없습니다. '
    'Linux 데스크톱 앱에서 실행하세요.';

Future<List<MapProjectSummary>> listMapProjects() async => const [];

Future<bool> mapProjectExists(String mapName) async => false;

Future<void> saveMapProject({
  required String mapName,
  required String payloadJson,
  String? buildingYaml,
  String? buildingYamlName,
}) async => throw UnsupportedError(_unsupported);

Future<String?> loadMapProject(String mapName) async =>
    throw UnsupportedError(_unsupported);

Future<String?> loadMapProjectYaml(String mapName) async =>
    throw UnsupportedError(_unsupported);

Future<void> deleteMapProject(String mapName) async =>
    throw UnsupportedError(_unsupported);

Future<void> saveMapProjectFiles(
  String mapName,
  List<MapProjectFile> files,
) async => throw UnsupportedError(_unsupported);

Future<List<MapProjectFile>> loadMapProjectFiles(String mapName) async =>
    const [];

Future<List<MapProjectFile>> loadMapProjectFileSummaries(
  String mapName,
) async => const [];

Future<String?> loadMapProjectFileContent(
  String mapName,
  String fileName,
) async => null;

Future<void> saveMapProjectFleet(
  String mapName, {
  required Map<String, Object?> settings,
  required List<Map<String, Object?>> robots,
}) async => throw UnsupportedError(_unsupported);

Future<void> saveMapProjectFleetSettings(
  String mapName,
  Map<String, Object?> settings,
) async => throw UnsupportedError(_unsupported);

Future<Map<String, dynamic>?> loadMapProjectFleet(String mapName) async => null;

Future<void> saveProjectSimulationSettings(
  String mapName,
  ProjectSimulationSettings settings,
) async => throw UnsupportedError(_unsupported);

Future<ProjectSimulationSettings> loadProjectSimulationSettings(
  String mapName,
) async => const ProjectSimulationSettings();
