import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/main.dart';

/// 프로젝트 이름이 도면 파일 이름에서 떨어져 나온 것을 지킨다.
///
/// 예전에는 프로젝트 이름이 도면 파일 이름에서 파생되고, 도면을 올릴 때마다
/// 사람이 정한 이름을 지웠다. 그래서 같은 `warehouse.png` 로는 늘 `warehouse`
/// 프로젝트가 되어, 같은 도면으로 다른 버전을 만들려면 저장 단계의 이름 충돌
/// 팝업을 거쳐야 했다. 이름을 먼저 정하는 길을 두고 그 파생을 끊었다.
///
/// DB 를 건드리지 않는 선까지만 본다 — 이름 팝업은 `만들기` 를 눌러야 저장소로
/// 간다. 여기서는 늘 취소한다.
void main() {
  Future<void> openMapMenu(WidgetTester tester) async {
    tester.view.physicalSize = const Size(1600, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(const RmfControlApp());
    await tester.tap(find.text('맵 관리').first);
    await tester.pumpAndSettle();
  }

  group('새 프로젝트', () {
    testWidgets('맵 관리에 단추가 있고 프로젝트 열기보다 앞에 온다', (tester) async {
      await openMapMenu(tester);

      final newProject = find.text('새 프로젝트');
      final open = find.text('프로젝트 열기');
      expect(newProject, findsOneWidget);
      expect(open, findsOneWidget);
      // 이름을 먼저 정하고 도면을 올리는 것이 제 차례다.
      expect(
        tester.getTopLeft(newProject).dx,
        lessThan(tester.getTopLeft(open).dx),
      );
    });

    testWidgets('누르면 이름을 먼저 묻는다', (tester) async {
      await openMapMenu(tester);
      await tester.tap(find.text('새 프로젝트'));
      await tester.pumpAndSettle();

      expect(find.text('새 프로젝트'), findsWidgets);
      expect(find.text('만들기'), findsOneWidget);
      // 도면 이름을 기본값으로 채우지 않는다. 그것이 예전 문제의 뿌리였다.
      final field = tester.widget<TextField>(find.byType(TextField).first);
      expect(field.controller?.text ?? '', isEmpty);
      // 같은 도면으로도 별개가 된다는 것을 그 자리에서 알려 준다.
      expect(find.textContaining('같은 도면으로도'), findsOneWidget);

      // 취소하면 저장소로 가지 않는다.
      await tester.tap(find.text('취소'));
      await tester.pumpAndSettle();
      expect(find.text('만들기'), findsNothing);
    });
  });

  group('이름과 도면의 분리', () {
    test('도면을 올려도 사람이 정한 이름을 지우지 않는다', () {
      // 이 한 줄이 문제의 원인이었다. 도면 올리기 setState 안에서 이름을
      // null 로 되돌려, 도면 파일 이름으로 다시 흘러가게 만들었다.
      final source = File('lib/main.dart').readAsStringSync();
      expect(source, isNot(contains('_mapNameOverride')));
      expect(source, contains('String? _projectName;'));
      final upload = source.substring(
        source.indexOf('_drawing = UploadedDrawing('),
      );
      expect(
        upload.substring(0, 400),
        isNot(contains('_projectName = null')),
        reason: '도면을 갈아 끼워도 프로젝트는 그대로여야 한다',
      );
    });

    test('올린 도면을 열린 프로젝트에 바로 저장한다', () {
      final source = File('lib/main.dart').readAsStringSync();
      expect(source, contains('도면을 프로젝트에 저장'));
      expect(source, contains('프로젝트에 저장했습니다.'));
    });

    test('도면을 프로젝트 디렉터리에도 남긴다', () {
      // 원장은 MySQL 이지만 배포 스크립트와 building.yaml 은 파일을 본다.
      final source = File('lib/main.dart').readAsStringSync();
      expect(source, contains('exportProjectDrawing('));
      final export = File('lib/rmf_config_export_io.dart').readAsStringSync();
      expect(export, contains('Future<String?> exportProjectDrawing('));
      expect(export, contains('rmf_maps/\${safeMapDirectoryName(mapName)}'));
    });

    test('열린 프로젝트에 저장할 때는 덮어쓸지 묻지 않는다', () {
      // `새 프로젝트` 는 이름을 받는 즉시 레코드를 만든다. 이 가드가 없으면
      // 첫 저장부터 "이미 있는 이름입니다" 가 떠서 제 프로젝트를 덮어쓸지
      // 고르게 된다.
      final source = File('lib/main.dart').readAsStringSync();
      final save = source.indexOf('Future<void> _saveProjectToDatabase()');
      expect(save, greaterThan(-1));
      final body = source.substring(save, save + 1600);
      final guard = body.indexOf('mapName == _openProjectName');
      final exists = body.indexOf('mapProjectExists(mapName)');
      expect(guard, greaterThan(-1), reason: '열린 프로젝트 가드가 없다');
      expect(guard, lessThan(exists), reason: '있는지 확인하기 전에 내 프로젝트인지 먼저 봐야 한다');
    });
  });
}
