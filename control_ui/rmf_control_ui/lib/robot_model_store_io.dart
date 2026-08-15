library;

import 'dart:io';

class RobotModelInfo {
  const RobotModelInfo({
    required this.name,
    required this.path,
    required this.packageCount,
    required this.isGitRepository,
  });

  final String name;
  final String path;
  final int packageCount;
  final bool isGitRepository;
}

Directory _projectRoot() {
  var directory = Directory.current.absolute;
  for (var i = 0; i < 8; i++) {
    if (Directory('${directory.path}/rmf_maps').existsSync() &&
        Directory('${directory.path}/rmf_control_ui').existsSync()) {
      return directory;
    }
    final parent = directory.parent;
    if (parent.path == directory.path) break;
    directory = parent;
  }
  throw StateError('robosapiens 프로젝트 루트를 찾지 못했습니다.');
}

Directory _modelRoot() => Directory('${_projectRoot().path}/robot_model');

String _validName(String value) {
  final name = value.trim();
  if (name.isEmpty ||
      !RegExp(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$').hasMatch(name) ||
      name == '.' ||
      name == '..') {
    throw const FormatException(
      '모델 이름은 영문·숫자로 시작하고 영문·숫자·점·밑줄·하이픈만 사용할 수 있습니다.',
    );
  }
  return name;
}

String _nameFromSource(String source) {
  var name = source.replaceAll('\\', '/').split('/').last.trim();
  if (name.endsWith('.git')) name = name.substring(0, name.length - 4);
  if (name.toLowerCase().endsWith('.zip')) {
    name = name.substring(0, name.length - 4);
  }
  return _validName(name);
}

Future<int> _packageCount(Directory directory) async {
  var count = 0;
  await for (final entity in directory.list(
    recursive: true,
    followLinks: false,
  )) {
    if (entity is File && entity.uri.pathSegments.last == 'package.xml') {
      count++;
    }
  }
  return count;
}

Future<RobotModelInfo> _describe(Directory directory) async => RobotModelInfo(
  name: directory.uri.pathSegments.where((part) => part.isNotEmpty).last,
  path: directory.path,
  packageCount: await _packageCount(directory),
  isGitRepository: Directory('${directory.path}/.git').existsSync(),
);

Future<List<RobotModelInfo>> listRobotModels() async {
  final root = _modelRoot();
  if (!root.existsSync()) await root.create(recursive: true);
  final models = <RobotModelInfo>[];
  await for (final entity in root.list(followLinks: false)) {
    if (entity is Directory || entity is Link) {
      final directory = Directory(entity.path);
      if (directory.existsSync()) models.add(await _describe(directory));
    }
  }
  models.sort((a, b) => a.name.compareTo(b.name));
  return models;
}

Future<void> _ensureAvailable(Directory destination) async {
  if (await destination.exists() || await Link(destination.path).exists()) {
    throw StateError('`${destination.path}` 모델이 이미 있습니다. 기존 모델은 덮어쓰지 않았습니다.');
  }
}

Future<RobotModelInfo> importRobotModelFromGit(
  String url, {
  String? name,
}) async {
  final source = url.trim();
  if (source.isEmpty) throw const FormatException('Git 저장소 주소를 입력하세요.');
  final root = _modelRoot();
  await root.create(recursive: true);
  final modelName = _validName(
    name?.trim().isNotEmpty == true ? name! : _nameFromSource(source),
  );
  final destination = Directory('${root.path}/$modelName');
  await _ensureAvailable(destination);
  final result = await Process.run('git', [
    'clone',
    '--depth',
    '1',
    '--',
    source,
    destination.path,
  ]);
  if (result.exitCode != 0) {
    if (await destination.exists()) await destination.delete(recursive: true);
    throw StateError(
      'Git 모델 가져오기 실패: ${(result.stderr as Object).toString().trim()}',
    );
  }
  return _describe(destination);
}

Future<RobotModelInfo> importRobotModelFromZip(
  String zipPath, {
  String? name,
}) async {
  final archive = File(zipPath);
  if (!await archive.exists()) throw StateError('ZIP 파일을 찾지 못했습니다.');
  final modelName = _validName(
    name?.trim().isNotEmpty == true ? name! : _nameFromSource(zipPath),
  );
  final root = _modelRoot();
  await root.create(recursive: true);
  final destination = Directory('${root.path}/$modelName');
  await _ensureAvailable(destination);

  // 압축을 풀기 전에 모든 이름을 검사한다. ../ 또는 절대 경로를 허용하면
  // robot_model 밖의 파일을 덮어쓸 수 있다(Zip Slip).
  final listing = await Process.run('unzip', ['-Z1', '--', archive.path]);
  if (listing.exitCode != 0) {
    throw StateError('ZIP 목록을 읽지 못했습니다: ${listing.stderr}');
  }
  final entries = '${listing.stdout}'
      .split('\n')
      .where((line) => line.isNotEmpty);
  for (final entry in entries) {
    final normalized = entry.replaceAll('\\', '/');
    if (normalized.startsWith('/') ||
        RegExp(r'^[a-zA-Z]:/').hasMatch(normalized) ||
        normalized.split('/').contains('..')) {
      throw FormatException('안전하지 않은 ZIP 경로가 있습니다: $entry');
    }
  }
  final detailedListing = await Process.run('unzip', [
    '-Z',
    '-l',
    '--',
    archive.path,
  ]);
  if (detailedListing.exitCode != 0) {
    throw StateError('ZIP 속성을 읽지 못했습니다: ${detailedListing.stderr}');
  }
  if (RegExp(
    r'^l[-rwx]{9}\s',
    multiLine: true,
  ).hasMatch('${detailedListing.stdout}')) {
    throw const FormatException('심볼릭 링크가 포함된 ZIP은 안전을 위해 가져올 수 없습니다.');
  }

  final temporary = await Directory.systemTemp.createTemp('robosapiens-model-');
  try {
    final extraction = await Process.run('unzip', [
      '-q',
      '--',
      archive.path,
      '-d',
      temporary.path,
    ]);
    if (extraction.exitCode != 0) {
      throw StateError('ZIP 압축 해제 실패: ${extraction.stderr}');
    }
    final visible = await temporary
        .list(followLinks: false)
        .where((entity) => !entity.uri.pathSegments.last.startsWith('.'))
        .toList();
    final source = visible.length == 1 && visible.single is Directory
        ? visible.single as Directory
        : temporary;
    await source.rename(destination.path);
    return _describe(destination);
  } finally {
    if (await temporary.exists()) await temporary.delete(recursive: true);
  }
}
