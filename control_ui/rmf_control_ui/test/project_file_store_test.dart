import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/project_file_store.dart';

void main() {
  late Directory root;

  setUp(() {
    root = Directory.systemTemp.createTempSync('rmf_project_files');
    debugProjectFileRootOverride = root.path;
  });

  tearDown(() {
    debugProjectFileRootOverride = null;
    root.deleteSync(recursive: true);
  });

  test('project 디렉터리를 자동 생성해 그 안에만 저장한다', () async {
    final path = await saveProjectFile('warehouse', Uint8List.fromList([1, 2]));

    expect(path, '${root.path}/project/warehouse.rmfproject');
    expect(File(path).readAsBytesSync(), [1, 2]);
    expect(await listProjectFiles(), hasLength(1));
  });

  test('같은 프로젝트 이름은 새 버전을 만들지 않고 같은 파일을 교체한다', () async {
    await saveProjectFile('warehouse', Uint8List.fromList([1]));
    await saveProjectFile('warehouse', Uint8List.fromList([2, 3]));

    final projects = await listProjectFiles();
    expect(projects, hasLength(1));
    expect(projects.single.fileName, 'warehouse.rmfproject');
    expect(await readProjectFile(projects.single.fileName), [2, 3]);
    expect(Directory('${root.path}/project').listSync(), hasLength(1));
  });

  test('project 디렉터리 밖의 파일 이름은 읽지 않는다', () async {
    await expectLater(
      readProjectFile('../outside.rmfproject'),
      throwsA(isA<ArgumentError>()),
    );
  });

  test('프로젝트 목록은 최근 저장 순서로 보여 준다', () async {
    await saveProjectFile('old', Uint8List.fromList([1]));
    await Future<void>.delayed(const Duration(milliseconds: 10));
    await saveProjectFile('new', Uint8List.fromList([2]));

    expect((await listProjectFiles()).map((p) => p.projectName), [
      'new',
      'old',
    ]);
  });

  test('UI 저장과 불러오기는 FilePicker 대신 고정 저장소를 쓴다', () {
    final source = File('lib/main.dart').readAsStringSync();
    final saveStart = source.indexOf('Future<bool> _writeProject(');
    final saveEnd = source.indexOf('Future<void> _saveProject()', saveStart);
    final loadStart = source.indexOf('Future<void> _loadProject()');
    final loadEnd = source.indexOf('void _applyProjectData(', loadStart);

    expect(saveStart, greaterThanOrEqualTo(0));
    expect(loadStart, greaterThanOrEqualTo(0));
    expect(loadEnd, greaterThan(loadStart));
    expect(
      source.substring(saveStart, saveEnd),
      contains('saveProjectFile(mapName, bytes)'),
    );
    expect(source.substring(saveStart, saveEnd), isNot(contains('FilePicker')));
    expect(
      source.substring(loadStart, loadEnd),
      contains('listProjectFiles()'),
    );
    expect(
      source.substring(loadStart, loadEnd),
      contains('readProjectFile(fileName)'),
    );
    expect(source.substring(loadStart, loadEnd), isNot(contains('FilePicker')));
  });
}
