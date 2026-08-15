/// 보내기 창이 고른 자리를 그대로 돌려주는지 지킨다.
///
/// 창은 이름만 돌려준다. 실제로 보내는 일과 막는 일은
/// `robot_move_command.dart` 가 하고, 그쪽은 따로 시험한다.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/main.dart' as app;
import 'package:rmf_control_ui/rmf_project_config.dart';

void main() {
  const pinky = RmfProjectRobot(
    robotId: 'PK_01',
    displayName: '핑키 1호',
    model: 'PINKY-GZ',
    gzName: 'pinky_01',
    zones: ['ambient'],
    chargerWaypoint: '충전1',
    dataSource: RobotDataSource.gazebo,
  );

  /// 창을 띄우고 사용자가 고른 값을 받아 둔다.
  Future<List<String?>> open(
    WidgetTester tester, {
    List<String> waypoints = const ['충전1', '대기1', '픽업1'],
    String? here = '충전1',
  }) async {
    final picked = <String?>[];
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => TextButton(
            onPressed: () async {
              picked.add(
                await showDialog<String>(
                  context: context,
                  builder: (_) => app.debugRobotMoveDialog(
                    robot: pinky,
                    waypoints: waypoints,
                    currentWaypoint: here,
                  ),
                ),
              );
            },
            child: const Text('열기'),
          ),
        ),
      ),
    );
    await tester.tap(find.text('열기'));
    await tester.pumpAndSettle();
    return picked;
  }

  testWidgets('고른 Waypoint 이름을 돌려준다', (tester) async {
    final picked = await open(tester);
    await tester.tap(find.text('픽업1'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('보내기'));
    await tester.pumpAndSettle();
    expect(picked, ['픽업1']);
  });

  testWidgets('아무것도 안 고르면 보낼 수 없다', (tester) async {
    await open(tester);
    final button = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, '보내기'),
    );
    expect(button.onPressed, isNull);
  });

  testWidgets('취소하면 아무것도 안 돌려준다', (tester) async {
    final picked = await open(tester);
    await tester.tap(find.text('취소'));
    await tester.pumpAndSettle();
    expect(picked, [null]);
  });

  testWidgets('지금 서 있는 자리는 고를 수 없다', (tester) async {
    // 있는 자리로 보내는 것은 아무 일도 아닌데, RMF 는 그것도 받아 성공이라고
    // 답한다. 그러면 로봇이 안 움직이는데 성공이라고 나온다.
    await open(tester);
    expect(find.text('지금 이 자리입니다'), findsOneWidget);
    final tile = tester.widget<ListTile>(
      find.ancestor(of: find.text('충전1'), matching: find.byType(ListTile)),
    );
    expect(tile.enabled, isFalse);
  });

  testWidgets('작업 목록과 다르다는 것을 밝힌다', (tester) async {
    // 작업으로 쌓이는 줄 알고 여러 번 누르면, 아무 데도 안 남는 것을 보고 안
    // 먹었다고 여긴다.
    await open(tester);
    expect(find.textContaining('작업 목록에 남지 않습니다'), findsOneWidget);
    expect(find.textContaining('입찰 없음'), findsOneWidget);
  });

  testWidgets('한글 이름이면 RViz 와 달라 보이는 이유를 적는다', (tester) async {
    await open(tester);
    expect(find.textContaining('RViz 라벨에는 한글이 빠지고'), findsOneWidget);
  });

  testWidgets('ASCII 이름뿐이면 그 안내는 안 낸다', (tester) async {
    await open(tester, waypoints: const ['CHG1', 'PICK1'], here: 'CHG1');
    expect(find.textContaining('RViz 라벨에는'), findsNothing);
  });

  testWidgets('많으면 찾는 칸이 나온다', (tester) async {
    await open(
      tester,
      waypoints: List.generate(12, (index) => 'WP${index + 1}'),
      here: null,
    );
    expect(find.byType(TextField), findsOneWidget);
    await tester.enterText(find.byType(TextField), 'WP11');
    await tester.pumpAndSettle();
    // 목록만 본다. 찾는 칸에도 같은 글자가 들어 있어서 그냥 세면 둘이 잡힌다.
    expect(find.widgetWithText(ListTile, 'WP11'), findsOneWidget);
    expect(find.widgetWithText(ListTile, 'WP2'), findsNothing);
  });

  testWidgets('적으면 찾는 칸을 안 낸다', (tester) async {
    await open(tester);
    expect(find.byType(TextField), findsNothing);
  });
}
