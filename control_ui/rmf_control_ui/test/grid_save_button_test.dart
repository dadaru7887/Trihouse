/// 그리드맵 화면에서 바로 저장할 수 있는지 지킨다.
///
/// 판단은 `grid_map_settings.dart` 가 따로 시험한다. 여기서 보는 것은 그것이
/// **화면에 닿는가** 다 — 고쳤는데 저장 칸이 안 나오면 예전과 똑같다.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/main.dart';

void main() {
  Future<void> openGrid(WidgetTester tester) async {
    tester.view.physicalSize = const Size(1600, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const RmfControlApp());
    await tester.tap(find.text('그리드맵'));
    await tester.pumpAndSettle();
  }

  /// 목표 가로 칸을 고치고 `적용` 을 누른다.
  ///
  /// 타자만 쳐서는 앱 상태가 안 바뀐다. 이 화면은 `적용` 을 눌러야 값을
  /// 넘긴다 — 저장은 그다음 이야기다.
  Future<void> applyWidth(WidgetTester tester, String value) async {
    final field = find.ancestor(
      of: find.textContaining('가로'),
      matching: find.byType(TextField),
    );
    expect(field, findsOneWidget, reason: '목표 가로 칸을 못 찾았다');
    await tester.ensureVisible(field);
    await tester.pumpAndSettle();
    await tester.enterText(field, value);
    await tester.pumpAndSettle();
    final apply = find.widgetWithText(FilledButton, '적용').first;
    await tester.ensureVisible(apply);
    await tester.pumpAndSettle();
    await tester.tap(apply);
    await tester.pumpAndSettle();
  }

  testWidgets('안 고쳤으면 저장 칸이 안 나온다', (tester) async {
    // 늘 켜 두면 눌러야 하는지 아닌지를 화면에서 알 수 없다.
    await openGrid(tester);
    expect(find.text('저장하지 않은 설정이 있습니다'), findsNothing);
    expect(find.text('설정 저장'), findsNothing);
  });

  testWidgets('고치면 저장 칸과 단추가 나온다', (tester) async {
    await openGrid(tester);
    await applyWidth(tester, '1024');
    expect(find.text('저장하지 않은 설정이 있습니다'), findsOneWidget);
    expect(find.text('설정 저장'), findsOneWidget);
  });

  testWidgets('무엇이 바뀌었는지 적는다', (tester) async {
    // 단추만 켜 두면 무엇을 저장하는지 모르는 채로 누르게 된다.
    await openGrid(tester);
    await applyWidth(tester, '1024');
    expect(find.textContaining('1024×'), findsOneWidget);
  });

  testWidgets('프로젝트가 없으면 저장 단추가 눌리지 않는다', (tester) async {
    // 저장할 곳이 없다. 눌리게 두면 눌러 보고서야 알게 된다.
    await openGrid(tester);
    await applyWidth(tester, '1024');
    final button = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, '설정 저장'),
    );
    expect(button.onPressed, isNull);
    expect(find.textContaining('맵 프로젝트가 없어'), findsOneWidget);
  });
}
