/// 벽 높이를 사람이 넣고, 그 값이 Gazebo 월드까지 가는지 지킨다.
///
/// 도면은 위에서 내려다본 그림이라 높이가 없다. 그래서 안 넣으면 생성기 기본값
/// 2.5m 로 서는데, 실험실 책상 위의 0.3m 세트가 사람 키보다 높은 벽으로 나와
/// 시뮬레이터 그림이 실제와 딴판이 됐다.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/main.dart';
import 'package:rmf_control_ui/wall_height.dart';

void main() {
  group('넣을 수 있는 높이', () {
    test('숫자가 아니면 받지 않는다', () {
      expect(wallHeightError(null), isNotNull);
      expect(wallHeightError(double.nan), isNotNull);
      expect(wallHeightError(double.infinity), isNotNull);
    });

    test('0 이하는 벽이 아니다', () {
      expect(wallHeightError(0), isNotNull);
      expect(wallHeightError(-.3), isNotNull);
    });

    test('실험실 세트 높이와 건물 벽 높이를 받는다', () {
      expect(wallHeightError(.3), isNull);
      expect(wallHeightError(defaultWallHeight), isNull);
    });

    test('너무 낮거나 너무 높으면 막는다', () {
      // 손이 미끄러져 0 을 하나 더 친 것에 가깝다.
      expect(wallHeightError(minWallHeight - .01), isNotNull);
      expect(wallHeightError(maxWallHeight + .01), isNotNull);
      expect(wallHeightError(minWallHeight), isNull);
      expect(wallHeightError(maxWallHeight), isNull);
    });
  });

  group('라이다보다 낮은 벽', () {
    test('라이다 아래면 알린다', () {
      // 라이다가 벽을 넘겨다보면 Gazebo 에서는 아무것도 안 맞히는데 지도에는
      // 벽이 있다. AMCL 이 위치를 잃고, 사람 눈에는 로봇이 헤매는 것만 보인다.
      final warning = wallHeightWarning(.08);
      expect(warning, isNotNull);
      expect(warning, contains('라이다'));
    });

    test('라이다보다 높으면 조용하다', () {
      expect(wallHeightWarning(.3), isNull);
      expect(wallHeightWarning(laserHeightPinky), isNull);
    });

    test('로봇이 바뀌면 기준도 바뀐다', () {
      expect(wallHeightWarning(.3, laserHeight: .5), isNotNull);
    });

    test('핑키 라이다 높이는 urdf 를 따라간다', () {
      // 바퀴 반지름 0.030 + lidar_mount 0.052 + laser_link 0.020.
      expect(laserHeightPinky, closeTo(.102, 1e-9));
    });
  });

  group('맵 관리 화면', () {
    Future<void> openDialog(WidgetTester tester) async {
      tester.view.physicalSize = const Size(1600, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(const RmfControlApp());
      await tester.tap(find.text('맵 관리').first);
      await tester.pumpAndSettle();
      await tester.tap(find.textContaining('벽 높이 '));
      await tester.pumpAndSettle();
    }

    Finder fieldByLabel(String label) =>
        find.ancestor(of: find.text(label), matching: find.byType(TextField));

    testWidgets('단추에 지금 높이가 적혀 있다', (tester) async {
      // 도면 어디에도 안 보이는 값이라, 열어 보지 않으면 2.5m 인 줄 모른다.
      tester.view.physicalSize = const Size(1600, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(const RmfControlApp());
      await tester.tap(find.text('맵 관리').first);
      await tester.pumpAndSettle();
      expect(find.text('벽 높이 2.50m'), findsOneWidget);
    });

    testWidgets('넣은 높이가 단추에 남는다', (tester) async {
      await openDialog(tester);
      await tester.enterText(fieldByLabel('벽 높이 (m)'), '0.3');
      await tester.tap(find.text('높이 저장'));
      await tester.pumpAndSettle();

      expect(find.text('벽 높이'), findsNothing, reason: '창이 닫혀야 한다');
      expect(find.text('벽 높이 0.30m'), findsOneWidget);
    });

    testWidgets('해석할 수 없으면 까닭을 보여 주고 닫지 않는다', (tester) async {
      await openDialog(tester);
      await tester.enterText(fieldByLabel('벽 높이 (m)'), '0.3m');
      await tester.tap(find.text('높이 저장'));
      await tester.pumpAndSettle();

      expect(find.text('숫자로 입력하세요.'), findsOneWidget);
      expect(find.text('높이 저장'), findsOneWidget, reason: '창이 열려 있어야 한다');
    });

    testWidgets('라이다보다 낮으면 저장하기 전에 알린다', (tester) async {
      await openDialog(tester);
      await tester.enterText(fieldByLabel('벽 높이 (m)'), '0.06');
      await tester.pumpAndSettle();

      expect(find.textContaining('라이다'), findsWidgets);
    });
  });

  group('building.yaml', () {
    late final String source = File('lib/main.dart').readAsStringSync();

    test('벽마다 넣은 높이를 적는다', () {
      // 2.5 를 그대로 박아 두면 화면에서 무엇을 넣든 월드는 2.5m 로 선다.
      expect(source, contains(r'texture_height: [3, $height]'));
      expect(source, isNot(contains('texture_height: [3, 2.5]')));
    });

    test('프로젝트에 남기고 다시 읽는다', () {
      // 안 남기면 열 때마다 2.5m 로 돌아가고, 배포한 월드의 벽 높이가 조용히
      // 바뀐다.
      expect(source, contains("'wallHeightMeters': _wallHeightMeters"));
      expect(source, contains("data['wallHeightMeters']"));
      // 예전 프로젝트에는 이 값이 없다. 그때 배포한 월드가 2.5m 였다.
      expect(source, contains('?? defaultWallHeight'));
    });

    test('바꾸면 다시 배포해야 한다고 표시한다', () {
      final dialog = source.substring(
        source.indexOf('Future<void> _showWallHeightSettings()'),
      );
      expect(dialog.substring(0, 6000), contains('_isDeployed = false'));
    });
  });

  group('배포 스크립트', () {
    late final String script = File(
      '../openrmf/scripts/deploy_map.sh',
    ).readAsStringSync();

    test('생성된 벽 메시의 높이를 고쳐 준다', () {
      // yaml 의 texture_height 는 텍스처 높이일 뿐이라 기하에 안 들어간다.
      // 생성기는 벽을 늘 2.5m 로 세운다.
      expect(script, contains('apply_wall_height'));
      expect(script, contains("-name 'wall_*.obj'"));
    });

    test('world 를 만든 뒤에 고친다', () {
      final generate = script.indexOf('building_map_generator gazebo');
      final patch = script.indexOf('apply_wall_height "\$STAGING_DIR');
      expect(generate, greaterThan(-1));
      expect(patch, greaterThan(generate), reason: '만들기 전에 고칠 수는 없다');
    });

    test('맵 디렉터리로 옮기기 전에 고친다', () {
      // 옮긴 뒤에 고치면 배포된 지도를 손대는 셈이라, 실패하면 반쯤 고쳐진
      // 지도가 남는다.
      final patch = script.indexOf('apply_wall_height "\$STAGING_DIR');
      final install = script.indexOf('mv "\$STAGING_DIR" "\$TARGET_DIR"');
      expect(install, greaterThan(patch));
    });

    test('벽마다 높이가 다르면 건드리지 않는다', () {
      // 어느 메시가 어느 벽인지 알 수 없다. 잘못 고치느니 그대로 둔다.
      expect(script, contains('벽 높이가 여럿입니다'));
    });
  });
}
