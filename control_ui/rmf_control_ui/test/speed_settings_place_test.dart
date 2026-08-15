/// 주행 속도를 고치는 자리가 한 곳인지 지킨다.
///
/// 예전에는 **로봇 등록 창**에 있었다. 값은 플릿 하나인데 로봇 창에 있으니
/// PK_01 에서 고친 것이 PK_02 에도 걸렸고, 로봇마다 정하는 것처럼 보였다.
/// 정작 찾을 때는 `로봇 안전 기준` 부터 뒤지게 됐다 — footprint·vicinity 같은
/// 다른 플릿 값이 거기 있기 때문이다. 실제로 못 찾았다.
///
/// 그래서 안전 기준으로 옮기고 로봇 창에서는 뺐다. 한 값은 한 자리에만 둔다.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/main.dart';

void main() {
  Future<void> openApp(WidgetTester tester) async {
    tester.view.physicalSize = const Size(1600, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const RmfControlApp());
    await tester.pumpAndSettle();
  }

  Future<void> openSafety(WidgetTester tester) async {
    await tester.tap(find.text('맵 관리').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('로봇 안전 기준'));
    await tester.pumpAndSettle();
  }

  Finder fieldByLabel(String label) =>
      find.ancestor(of: find.text(label), matching: find.byType(TextField));

  group('로봇 안전 기준', () {
    testWidgets('주행 한계 네 칸이 여기 있다', (tester) async {
      await openApp(tester);
      await openSafety(tester);
      expect(find.text('주행 한계'), findsOneWidget);
      for (final label in const ['직진 속도', '직진 가속도', '회전 속도', '회전 가속도']) {
        expect(fieldByLabel(label), findsOneWidget, reason: '$label 칸이 없다');
      }
    });

    testWidgets('벤더 값을 불러올 수 있다', (tester) async {
      // 이 숫자의 근거가 벤더 Nav2 파일이다. 아무 데서도 못 보면 무엇을 기준으로
      // 정할지 알 수 없다.
      await openApp(tester);
      await openSafety(tester);
      expect(find.text('벤더 값 불러오기'), findsOneWidget);
    });

    testWidgets('고친 속도가 남는다', (tester) async {
      await openApp(tester);
      await openSafety(tester);
      final field = fieldByLabel('직진 속도');
      await tester.ensureVisible(field);
      await tester.pumpAndSettle();
      await tester.enterText(field, '1.20');
      await tester.pumpAndSettle();
      await tester.tap(find.text('기준 저장'));
      await tester.pumpAndSettle();

      await openSafety(tester);
      expect(
        tester.widget<TextField>(fieldByLabel('직진 속도')).controller?.text,
        '1.20',
      );
    });
  });

  group('너무 느린 속도', () {
    testWidgets('Nav2 가 끼었다고 볼 속도면 그 자리에서 알린다', (tester) async {
      // 요구 거리는 내보낼 때 속도에 맞춰 낮춰 주지만 바닥이 있다. 그 아래로
      // 내려가면 값을 맞춰도 소용없으니 저장하기 전에 알려야 한다.
      await openApp(tester);
      await openSafety(tester);
      final field = fieldByLabel('직진 속도');
      await tester.ensureVisible(field);
      await tester.pumpAndSettle();
      await tester.enterText(field, '0.004');
      await tester.pumpAndSettle();
      expect(find.textContaining('끼었다고'), findsOneWidget);
    });

    testWidgets('쓸 만한 속도에서는 안 나온다', (tester) async {
      await openApp(tester);
      await openSafety(tester);
      final field = fieldByLabel('직진 속도');
      await tester.ensureVisible(field);
      await tester.pumpAndSettle();
      await tester.enterText(field, '0.20');
      await tester.pumpAndSettle();
      expect(find.textContaining('끼었다고'), findsNothing);
    });
  });

  group('로봇 등록 창', () {
    testWidgets('속도 칸이 더는 없다', (tester) async {
      await openApp(tester);
      await tester.tap(find.text('로봇').first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('로봇 등록'));
      await tester.pumpAndSettle();
      // 창은 SingleChildScrollView 라 화면 밖 칸도 다 만들어진다. 그래서
      // 안 보이는 것이 아니라 정말 없어야 이 검사가 통과한다.
      expect(find.text('직진 속도'), findsNothing);
      expect(find.text('RMF 속도 한계'), findsNothing);
      expect(find.text('벤더 값 불러오기'), findsNothing);
    });
  });
}
