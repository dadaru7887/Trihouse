/// 프로젝트의 설정 파일을 디스크로 내보낸다.
///
/// 설정은 MySQL 이 원장이지만 `ros2 launch` 는 파일만 읽는다. 실행 직전에 그
/// 프로젝트의 파일을 배포 디렉터리로 풀어 놓아야 한다.
///
/// 맵마다 디렉터리가 따로이므로(`rmf_maps/<맵이름>`) 프로젝트를 바꿔도 서로
/// 덮어쓰지 않는다.
library;

import 'dart:io';
import 'dart:typed_data';

import 'package:meta/meta.dart';

import 'map_project_models.dart';

@visibleForTesting
String? debugRmfConfigRootOverride;

class RmfConfigExportResult {
  const RmfConfigExportResult({
    required this.success,
    required this.directory,
    required this.written,
    required this.message,
  });

  final bool success;

  /// 실제로 쓴 디렉터리. 실패하면 빈 문자열.
  final String directory;

  /// 쓴 파일 이름.
  final List<String> written;
  final String message;
}

Directory? _findProjectRoot() {
  final override = debugRmfConfigRootOverride;
  if (override != null) return Directory(override).absolute;
  final configuredRoot = Platform.environment['RMF_ROOT'];
  if (configuredRoot != null && configuredRoot.isNotEmpty) {
    final directory = Directory(configuredRoot).absolute;
    if (Directory('${directory.path}/rmf_maps').existsSync()) return directory;
  }
  var directory = Directory.current.absolute;
  for (var i = 0; i < 8; i++) {
    if (Directory('${directory.path}/rmf_maps').existsSync()) return directory;
    final parent = directory.parent;
    if (parent.path == directory.path) break;
    directory = parent;
  }
  return null;
}

/// 파일 이름으로 쓸 수 없는 글자를 걷어낸다. 지도 이름에 공백이나 슬래시가
/// 들어가면 디렉터리가 엉뚱한 곳에 생긴다.
String safeMapDirectoryName(String mapName) {
  final safe = mapName.replaceAll(RegExp(r'[^a-zA-Z0-9가-힣_-]'), '_');
  return safe.isEmpty ? 'map' : safe;
}

/// 저장된 파일 이름을 내보낼 상대 경로로 바꾼다. 나갈 수 없으면 null.
///
/// 로봇마다 제 디렉터리를 쓰므로(`robots/PK-01/spawn.launch.xml`) 하위 경로를
/// 허용해야 한다. 다만 `..` 이 섞이면 배포 디렉터리 밖으로 나가므로 막는다.
/// 파일 이름은 로봇 ID 에서 만들어지고 로봇 ID 는 사람이 타자로 친다.
String? safeExportRelativePath(String fileName) {
  final segments = fileName
      .split(RegExp(r'[/\\]'))
      .map((segment) => segment.trim())
      .where((segment) => segment.isNotEmpty)
      .toList();
  if (segments.isEmpty) return null;
  if (segments.any((segment) => segment == '.' || segment == '..')) return null;
  return segments.join('/');
}

/// 도면 이미지를 `rmf_maps/<프로젝트이름>/` 아래에 쓴다.
///
/// 원장은 MySQL 의 `drawing_bytes` 다. 그런데도 디스크에 한 장 남기는 이유는
/// 셋이다. 배포 스크립트가 파일 경로로 이미지를 받고, `building.yaml` 의
/// `drawing.filename` 이 이 파일을 가리키고, 프로젝트 디렉터리만 열어 봐도
/// 어느 도면으로 만든 창고인지 알 수 있어야 한다.
///
/// 같은 도면으로 만든 다른 프로젝트는 디렉터리가 다르므로 서로 덮어쓰지 않는다.
Future<String?> exportProjectDrawing({
  required String mapName,
  required String fileName,
  required Uint8List bytes,
}) async {
  final safeName = safeExportRelativePath(fileName);
  if (safeName == null) return null;
  final root = _findProjectRoot();
  if (root == null) return null;
  final target = Directory(
    '${root.path}/rmf_maps/${safeMapDirectoryName(mapName)}',
  );
  await target.create(recursive: true);
  final file = File('${target.path}/$safeName');
  await file.writeAsBytes(bytes, flush: true);
  return file.path;
}

/// [files] 를 `rmf_maps/<맵이름>/` 아래에 쓴다.
///
/// 배포 산출물(`nav_graphs/0.yaml`, `*.world`)이 이미 그 디렉터리에 있으므로
/// 설정도 같은 곳에 두면 launch 가 한 경로만 가리키면 된다.
Future<RmfConfigExportResult> exportProjectConfigFiles({
  required String mapName,
  required List<MapProjectFile> files,
}) async {
  if (files.isEmpty) {
    return const RmfConfigExportResult(
      success: false,
      directory: '',
      written: [],
      message: '내보낼 설정 파일이 없습니다. 먼저 프로젝트를 저장하세요.',
    );
  }
  final root = _findProjectRoot();
  if (root == null) {
    return const RmfConfigExportResult(
      success: false,
      directory: '',
      written: [],
      message:
          'rmf_maps 디렉터리를 찾을 수 없습니다. '
          'RMF_ROOT 환경 변수로 프로젝트 위치를 지정하세요.',
    );
  }
  final target = Directory(
    '${root.path}/rmf_maps/${safeMapDirectoryName(mapName)}',
  );
  try {
    await target.create(recursive: true);
    final expectedRobotDirectories = <String>{
      for (final file in files)
        if (safeExportRelativePath(file.fileName) case final name?)
          if (name.startsWith('robots/') && name.split('/').length >= 3)
            name.split('/')[1],
    };
    final robotsDirectory = Directory('${target.path}/robots');
    if (robotsDirectory.existsSync()) {
      await for (final entry in robotsDirectory.list()) {
        if (entry is! Directory) continue;
        final name = entry.uri.pathSegments
            .where((segment) => segment.isNotEmpty)
            .last;
        if (expectedRobotDirectories.contains(name)) continue;
        // 사용자가 만든 디렉터리는 보존하고 앱 생성물만 정리한다.
        final spawn = File('${entry.path}/spawn.launch.xml');
        if (!spawn.existsSync()) continue;
        final generated = await spawn.readAsString();
        if (!generated.contains('rmf_control_ui 가 맵 프로젝트에서 생성했다')) {
          continue;
        }
        await entry.delete(recursive: true);
      }
    }
    final written = <String>[];
    for (final file in files) {
      final name = safeExportRelativePath(file.fileName);
      if (name == null) continue;
      final path = '${target.path}/$name';
      final separator = name.lastIndexOf('/');
      if (separator > 0) {
        await Directory(
          '${target.path}/${name.substring(0, separator)}',
        ).create(recursive: true);
      }
      await File(path).writeAsString(file.content, flush: true);
      // .sh 는 실행 권한이 없으면 그대로 돌릴 수 없다.
      if (file.executable) {
        await Process.run('chmod', ['+x', path]);
      }
      written.add(file.executable ? '$name (실행 가능)' : name);
    }
    written.sort();
    return RmfConfigExportResult(
      success: true,
      directory: target.path,
      written: written,
      message: '${written.length}개 파일을 ${target.path} 에 썼습니다.',
    );
  } catch (error) {
    return RmfConfigExportResult(
      success: false,
      directory: target.path,
      written: const [],
      message: '$error',
    );
  }
}

/// 이 맵의 실행 스크립트가 디스크에 있는가.
///
/// `ros2 launch` 는 앱이 아니라 **파일**을 읽는다. MySQL 에 설정이 다 들어 있어도
/// 내보내기를 안 했으면 띄울 것이 없다. 그 상태로 실행을 누르면 `파일이
/// 없습니다` 하나만 보이는데, 무엇을 먼저 눌러야 하는지는 안 나온다.
bool projectRunScriptExists(String mapDirectory, String mapName) {
  if (mapDirectory.trim().isEmpty || mapName.trim().isEmpty) return false;
  return File('$mapDirectory/run_$mapName.sh').existsSync();
}
