import 'dart:io';
import 'dart:typed_data';

import 'project_file_store_models.dart';

export 'project_file_store_models.dart';

String? debugProjectFileRootOverride;

Directory _packageRoot() {
  final override = debugProjectFileRootOverride;
  if (override != null && override.isNotEmpty) {
    return Directory(override).absolute;
  }
  final repositoryRoot = Platform.environment['RMF_ROOT'];
  if (repositoryRoot != null && repositoryRoot.isNotEmpty) {
    final package = Directory('$repositoryRoot/rmf_control_ui').absolute;
    if (File('${package.path}/pubspec.yaml').existsSync()) return package;
  }
  var directory = Directory.current.absolute;
  for (var i = 0; i < 8; i++) {
    if (File('${directory.path}/pubspec.yaml').existsSync() &&
        Directory('${directory.path}/lib').existsSync()) {
      return directory;
    }
    final nested = Directory('${directory.path}/rmf_control_ui');
    if (File('${nested.path}/pubspec.yaml').existsSync()) return nested;
    if (directory.parent.path == directory.path) break;
    directory = directory.parent;
  }
  throw StateError('rmf_control_ui 프로젝트 루트를 찾지 못했습니다.');
}

Directory projectFileDirectory() => Directory('${_packageRoot().path}/project');

String projectFileName(String mapName) {
  final normalized = mapName.trim().replaceAll(
    RegExp(r'[^a-zA-Z0-9가-힣_-]'),
    '_',
  );
  if (normalized.isEmpty) throw ArgumentError('프로젝트 이름이 비어 있습니다.');
  return '$normalized.rmfproject';
}

Future<String> saveProjectFile(String mapName, Uint8List bytes) async {
  final directory = projectFileDirectory();
  await directory.create(recursive: true);
  final target = File('${directory.path}/${projectFileName(mapName)}');
  final temporary = File('${target.path}.tmp');
  final backup = File('${target.path}.bak');
  await temporary.writeAsBytes(bytes, flush: true);
  if (await backup.exists()) await backup.delete();
  if (await target.exists()) await target.rename(backup.path);
  try {
    await temporary.rename(target.path);
    if (await backup.exists()) await backup.delete();
  } catch (_) {
    if (await target.exists()) await target.delete();
    if (await backup.exists()) await backup.rename(target.path);
    rethrow;
  }
  return target.path;
}

Future<List<StoredProjectFile>> listProjectFiles() async {
  final directory = projectFileDirectory();
  await directory.create(recursive: true);
  final projects = <StoredProjectFile>[];
  await for (final entity in directory.list(followLinks: false)) {
    if (entity is! File || !entity.path.toLowerCase().endsWith('.rmfproject')) {
      continue;
    }
    final stat = await entity.stat();
    projects.add(
      StoredProjectFile(
        fileName: entity.uri.pathSegments.last,
        modifiedAt: stat.modified,
        size: stat.size,
      ),
    );
  }
  projects.sort((a, b) => b.modifiedAt.compareTo(a.modifiedAt));
  return projects;
}

Future<Uint8List> readProjectFile(String fileName) async {
  if (fileName !=
      projectFileName(fileName.replaceFirst(RegExp(r'\.rmfproject$'), ''))) {
    throw ArgumentError('올바르지 않은 프로젝트 파일 이름입니다.');
  }
  final file = File('${projectFileDirectory().path}/$fileName');
  if (!await file.exists()) throw StateError('$fileName 프로젝트가 없습니다.');
  return file.readAsBytes();
}
