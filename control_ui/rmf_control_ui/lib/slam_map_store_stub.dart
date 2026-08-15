/// 웹 빌드용 대체 구현. 브라우저에서는 파일을 읽고 쓸 수 없다.
library;

import 'slam_map.dart';

class SlamMapStoreResult {
  const SlamMapStoreResult({
    required this.success,
    required this.message,
    this.map,
    this.directory = '',
    this.written = const [],
  });

  final bool success;
  final String message;
  final SlamMap? map;
  final String directory;
  final List<String> written;
}

const String _unsupported = '웹 빌드에서는 SLAM 지도를 넣을 수 없습니다. Linux 데스크톱 앱에서 실행하세요.';

String slamYamlName(String mapName) => '${mapName}_slam.yaml';
String slamImageName(String mapName) => '${mapName}_slam.pgm';

Future<SlamMapStoreResult> readSlamMapFrom(String yamlPath) async =>
    const SlamMapStoreResult(success: false, message: _unsupported);

Future<SlamMapStoreResult> writeSlamMap({
  required String mapName,
  required SlamMap map,
  String? note,
}) async => const SlamMapStoreResult(success: false, message: _unsupported);

Future<SlamMap?> loadStoredSlamMap(String mapName) async => null;
