/// 로봇 운영 화면의 지도와 Spawn 목록이 맵 관리의 지도 크기로 나오는지 지킨다.
///
/// 예전에는 이 화면이 창에 든 만큼만 쓰고, 지도는 남는 자리를 가져갔다. 위쪽
/// 카드(차례·등록·백엔드 상태)가 자리를 다 먹으면 지도가 띠처럼 눌려, 같은
/// 도면인데도 맵 관리에서 보던 것과 딴판이었다. 로봇이 어느 Waypoint 에 서
/// 있는지 눈으로 짚을 수 없었다.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/main.dart';

void main() {
  Future<void> openRobotMenu(WidgetTester tester, {Size? size}) async {
    tester.view.physicalSize = size ?? const Size(1600, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const RmfControlApp());
    await tester.tap(find.text('로봇'));
    await tester.pumpAndSettle();
  }

  /// 도면이 없을 때 지도 칸이 띄우는 안내. 이 글자로 지도 칸을 찾는다.
  final mapCardText = find.text('맵 관리에서 이미지 도면과 Lane을 먼저 작성하세요.');

  Size mapCardSize(WidgetTester tester) => tester.getSize(
    find.ancestor(of: mapCardText, matching: find.byType(Container)).first,
  );

  testWidgets('지도 칸이 맵 관리와 같은 높이다', (tester) async {
    await openRobotMenu(tester);
    expect(mapCardText, findsOneWidget);
    expect(mapCardSize(tester).height, mapWorkspaceHeight);
  });

  testWidgets('창이 낮아도 지도는 안 눌린다', (tester) async {
    // 남는 자리에 맞추면 낮은 창에서 지도가 띠가 된다. 대신 화면을 스크롤한다.
    await openRobotMenu(tester, size: const Size(1600, 760));
    expect(mapCardSize(tester).height, mapWorkspaceHeight);
  });

  testWidgets('화면이 스크롤된다', (tester) async {
    // 지도가 창보다 크므로, 스크롤이 없으면 아래쪽이 잘려 못 본다.
    await openRobotMenu(tester, size: const Size(1600, 760));
    final before = tester.getTopLeft(mapCardText).dy;

    // 창 위쪽의 제목을 끌어 페이지를 올린다. 지도 칸은 이미 화면 밖이라
    // 거기서는 끌 수 없다.
    await tester.drag(find.text('로봇 운영'), const Offset(0, -300));
    await tester.pumpAndSettle();

    expect(
      tester.getTopLeft(mapCardText).dy,
      lessThan(before),
      reason: '스크롤되어야 지도 아래쪽을 볼 수 있다',
    );
    // 스크롤해도 지도 크기는 그대로여야 한다. 줄어들면 자리에 맞춘 것이다.
    expect(mapCardSize(tester).height, mapWorkspaceHeight);
  });

  testWidgets('Spawn 목록도 지도와 같은 높이로 커진다', (tester) async {
    // 로봇이 여러 대일 때 목록 안에서 또 스크롤하지 않아도 되게 한다.
    await openRobotMenu(tester);
    final list = find
        .ancestor(of: find.text('Spawn 로봇'), matching: find.byType(Container))
        .first;
    expect(tester.getSize(list).height, mapWorkspaceHeight);
  });
}
