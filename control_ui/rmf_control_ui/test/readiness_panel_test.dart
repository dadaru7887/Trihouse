/// 작업 화면의 준비 확인표가 화면에 늘 보이는지 지킨다.
///
/// 판단은 `readiness_check.dart` 가 따로 시험한다. 여기서 보는 것은 그 판단이
/// **화면에 닿는가** 다 — 맞게 판단해도 안 보이면 쓸 수가 없다.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/main.dart';

void main() {
  Future<void> openTasks(WidgetTester tester) async {
    tester.view.physicalSize = const Size(1600, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const RmfControlApp());
    await tester.tap(find.text('작업'));
    await tester.pumpAndSettle();
  }

  testWidgets('작업 화면을 열면 확인표가 바로 보인다', (tester) async {
    // 눌러야 나오면 무엇이 막혔는지 모른 채 작업부터 만들게 된다.
    await openTasks(tester);
    expect(find.byIcon(Icons.error_outline), findsWidgets);
  });

  testWidgets('안 됐을 때는 단계를 펼쳐 보여 준다', (tester) async {
    // 아무것도 안 띄운 상태다. 접어 두면 요약 한 줄만 보여 원인을 못 짚는다.
    await openTasks(tester);
    // 요약 줄에도 같은 글이 한 번 더 나온다 — 맨 앞에 손댈 곳을 짚어 주기
    // 때문이다. 그래서 하나만 세지 않는다.
    expect(find.textContaining('지도와 Waypoint'), findsWidgets);
    expect(find.textContaining('Open-RMF 실행'), findsOneWidget);
    expect(find.textContaining('RMF↔Nav2 어댑터'), findsOneWidget);
    expect(find.textContaining('로봇이 RMF 에 붙음'), findsOneWidget);
  });

  testWidgets('무엇을 하면 되는지까지 적는다', (tester) async {
    // 이유만 있으면 화면을 보고도 다음 손이 안 나간다.
    await openTasks(tester);
    expect(find.textContaining('Waypoint 를 놓고'), findsWidgets);
  });

  testWidgets('지금 다시 확인할 수 있다', (tester) async {
    await openTasks(tester);
    expect(find.byTooltip('지금 다시 확인'), findsOneWidget);
    await tester.tap(find.byTooltip('지금 다시 확인'));
    await tester.pumpAndSettle();
    // 눌러도 화면이 살아 있어야 한다.
    expect(find.textContaining('Open-RMF 실행'), findsOneWidget);
  });

  testWidgets('센 단계 수를 보여 준다', (tester) async {
    await openTasks(tester);
    expect(find.textContaining('/8'), findsOneWidget);
  });
}
