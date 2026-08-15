/// 로봇 화면에 보내기 단추가 실제로 걸려 있는지 지킨다.
///
/// 창과 판단은 따로 시험한다. 여기서 보는 것은 **이어져 있는가** 하나다 —
/// 단추가 없거나 아무 데도 안 걸려 있으면, 아래가 다 맞아도 쓸 수가 없다.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/main.dart';

void main() {
  Future<void> openRobotMenu(WidgetTester tester) async {
    tester.view.physicalSize = const Size(1600, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const RmfControlApp());
    await tester.tap(find.text('로봇'));
    await tester.pumpAndSettle();
  }

  Future<void> registerRobot(
    WidgetTester tester, {
    bool workcell = false,
  }) async {
    await tester.tap(find.text('로봇 등록'));
    await tester.pumpAndSettle();
    if (workcell) {
      await tester.tap(find.text('설치 로봇'));
      await tester.pumpAndSettle();
    }
    await tester.tap(find.text('저장'));
    await tester.pumpAndSettle();
  }

  Finder sendButton() =>
      find.widgetWithIcon(IconButton, Icons.near_me_outlined);

  testWidgets('이동 로봇에게는 보내기 단추가 있다', (tester) async {
    await openRobotMenu(tester);
    await registerRobot(tester);
    expect(sendButton(), findsOneWidget);
  });

  testWidgets('설비 로봇에게는 없다', (tester) async {
    // 자리를 못 옮기는 로봇에게 단추를 내밀면, 눌러 보고서야 안 된다는 것을
    // 알게 된다.
    await openRobotMenu(tester);
    await registerRobot(tester, workcell: true);
    expect(sendButton(), findsNothing);
  });

  testWidgets('눌렀을 때 왜 못 보내는지 알려 준다', (tester) async {
    // 지도도 안 붙었고 Open-RMF 도 안 떠 있다. 조용히 아무 일도 안 일어나면
    // 단추가 고장 난 것으로 보인다.
    await openRobotMenu(tester);
    await registerRobot(tester);
    await tester.tap(sendButton());
    await tester.pumpAndSettle();
    expect(find.text('보낼 수 없습니다'), findsOneWidget);
  });
}
