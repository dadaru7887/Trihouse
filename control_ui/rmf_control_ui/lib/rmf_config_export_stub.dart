/// 웹 빌드용 대체 구현. 브라우저에서는 파일을 쓸 수 없다.
library;

import 'dart:typed_data';

import 'map_project_models.dart';

class RmfConfigExportResult {
  const RmfConfigExportResult({
    required this.success,
    required this.directory,
    required this.written,
    required this.message,
  });
  final bool success;
  final String directory;
  final List<String> written;
  final String message;
}

String safeMapDirectoryName(String mapName) => mapName;

Future<RmfConfigExportResult> exportProjectConfigFiles({
  required String mapName,
  required List<MapProjectFile> files,
}) async => const RmfConfigExportResult(
  success: false,
  directory: '',
  written: [],
  message: '웹 빌드에서는 설정 파일을 내보낼 수 없습니다. Linux 데스크톱 앱에서 실행하세요.',
);

/// 브라우저에서는 파일을 쓸 수 없다. 도면은 MySQL 에만 남는다.
Future<String?> exportProjectDrawing({
  required String mapName,
  required String fileName,
  required Uint8List bytes,
}) async => null;

bool projectRunScriptExists(String mapDirectory, String mapName) => false;
