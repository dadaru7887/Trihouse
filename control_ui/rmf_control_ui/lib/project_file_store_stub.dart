import 'dart:typed_data';

import 'project_file_store_models.dart';

export 'project_file_store_models.dart';

String? debugProjectFileRootOverride;

Never _unsupported() =>
    throw UnsupportedError('웹에서는 로컬 project 디렉터리를 사용할 수 없습니다.');

String projectFileName(String mapName) {
  final normalized = mapName.trim().replaceAll(
    RegExp(r'[^a-zA-Z0-9가-힣_-]'),
    '_',
  );
  if (normalized.isEmpty) throw ArgumentError('프로젝트 이름이 비어 있습니다.');
  return '$normalized.rmfproject';
}

Future<String> saveProjectFile(String mapName, Uint8List bytes) async =>
    _unsupported();

Future<List<StoredProjectFile>> listProjectFiles() async => const [];

Future<Uint8List> readProjectFile(String fileName) async => _unsupported();
