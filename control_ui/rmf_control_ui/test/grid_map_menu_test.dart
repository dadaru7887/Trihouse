import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/main.dart';

/// 그리드맵은 배포하기 안에 묻혀 있었다.
///
/// 그런데 이것 하나만 없어도 로봇이 아예 못 움직인다 — map_server 가
/// unconfigured 에서 멈추고, AMCL 이 "Waiting for map" 만 되풀이하고, 위치를
/// 모르니 fleet adapter 가 로봇을 등록하지 못한다. 그때 사람이 보는 말은
/// "RMF 가 답하지 않습니다. fleet adapter 가 떠 있는지 확인하세요" 라서 원인에서
/// 네 단계 떨어져 있다. 그래서 맵 메뉴에서 따로 부를 수 있어야 한다.
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

  testWidgets('맵 메뉴에 그리드맵 작성이 있다', (tester) async {
    await openMapMenu(tester);

    final tile = find.text('그리드맵 작성');
    await tester.scrollUntilVisible(tile, 120);
    await tester.pumpAndSettle();

    expect(tile, findsOneWidget);
    expect(
      find.textContaining('점유격자'),
      findsWidgets,
      reason: '무엇을 만드는 것인지 알 수 있어야 한다',
    );
  });

  testWidgets('배포하기와 따로 있다', (tester) async {
    // 배포 전체를 돌리지 않고 지도만 다시 만들 수 있어야 한다.
    await openMapMenu(tester);

    await tester.scrollUntilVisible(find.text('그리드맵 작성'), 120);
    await tester.pumpAndSettle();

    expect(find.text('그리드맵 작성'), findsOneWidget);
    expect(find.textContaining('배포'), findsWidgets);
  });

  testWidgets('도면이 없으면 눌리지 않는다', (tester) async {
    // 그리드맵은 도면의 바닥과 벽에서 만들어진다. 도면도 없이 누르게 두면
    // 빈 격자가 만들어지고, 그것을 들고 AMCL 이 아무 데도 못 잡는다.
    await openMapMenu(tester);

    await tester.scrollUntilVisible(find.text('그리드맵 작성'), 120);
    await tester.pumpAndSettle();

    final tile = tester.widget<InkWell>(
      find
          .ancestor(of: find.text('그리드맵 작성'), matching: find.byType(InkWell))
          .first,
    );
    expect(tile.onTap, isNull, reason: '도면 전에는 비활성이어야 한다');

    // 눌러도 아무 창이 뜨지 않아야 한다 — 조용히 지나가는 것이 맞다.
    await tester.tap(find.text('그리드맵 작성'), warnIfMissed: false);
    await tester.pumpAndSettle();
    expect(find.byType(AlertDialog), findsNothing);
  });
}
