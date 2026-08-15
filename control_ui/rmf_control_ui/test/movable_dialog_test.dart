import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/movable_dialog.dart';

/// 팝업 맨 위의 이동 손잡이.
final handle = find.byKey(MovableDialog.handleKey);

/// 팝업은 언제나 옆으로 치울 수 있어야 한다. 화면 한가운데 고정되면 그 아래의
/// 지도나 목록을 보면서 고칠 수가 없다.
void main() {
  Future<void> openDialog(
    WidgetTester tester, {
    VoidCallback? onPressed,
  }) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => TextButton(
              onPressed: () => showMovableDialog<void>(
                context: context,
                builder: (_) => AlertDialog(
                  title: const Text('제목'),
                  content: const SizedBox(
                    width: 300,
                    height: 120,
                    child: Text('본문'),
                  ),
                  actions: [
                    TextButton(onPressed: onPressed, child: const Text('확인')),
                  ],
                ),
              ),
              child: const Text('열기'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('열기'));
    await tester.pumpAndSettle();
  }

  testWidgets('손잡이를 끌면 팝업이 그만큼 따라 움직인다', (tester) async {
    await openDialog(tester);

    final before = tester.getCenter(find.byType(AlertDialog));
    await tester.drag(handle, const Offset(-160, -120));
    await tester.pumpAndSettle();
    final moved = tester.getCenter(find.byType(AlertDialog)) - before;

    // Offset 은 부동소수점이라 그대로 견주면 눈에 같아 보여도 어긋난다.
    expect(moved.dx, closeTo(-160, .01));
    expect(moved.dy, closeTo(-120, .01));
  });

  testWidgets('여러 번 끌면 이동이 누적된다', (tester) async {
    await openDialog(tester);

    final before = tester.getCenter(find.byType(AlertDialog));
    await tester.drag(handle, const Offset(40, 30));
    await tester.pumpAndSettle();
    await tester.drag(handle, const Offset(20, 10));
    await tester.pumpAndSettle();

    final moved = tester.getCenter(find.byType(AlertDialog)) - before;
    expect(moved.dx, closeTo(60, .01));
    expect(moved.dy, closeTo(40, .01));
  });

  testWidgets('화면 밖으로 완전히 나가지 않는다', (tester) async {
    await openDialog(tester);

    final screen = tester.view.physicalSize / tester.view.devicePixelRatio;
    final before = tester.getCenter(find.byType(AlertDialog));
    // 화면 크기의 몇 배로 끌어도 절반까지만 밀린다. 다시 잡을 수 없게 되면
    // 팝업을 닫지도 못한다.
    await tester.drag(handle, Offset(screen.width * 3, 0));
    await tester.pumpAndSettle();

    final moved = tester.getCenter(find.byType(AlertDialog)).dx - before.dx;
    expect(moved, lessThanOrEqualTo(screen.width / 2 + .01));
    expect(find.byType(AlertDialog), findsOneWidget);
  });

  testWidgets('끄는 자리가 팝업 위에 있다', (tester) async {
    // 예전에는 손잡이가 화면 맨 위에 그려져 팝업에서 82px 떨어져 있었다.
    // 아무도 잡을 수 없었고, 테스트가 키로 직접 끌었던 탓에 드러나지 않았다.
    await openDialog(tester);

    final grab = tester.getRect(handle);
    final box = tester.getRect(
      find
          .descendant(
            of: find.byType(AlertDialog),
            matching: find.byType(Material),
          )
          .first,
    );

    expect(box.contains(grab.center), isTrue, reason: '손잡이가 팝업 상자 안에 있어야 한다');
    expect(grab.top, closeTo(box.top, .01), reason: '팝업 위쪽에 붙어야 한다');
    expect(grab.width, closeTo(box.width, .01), reason: '상자 너비만큼 잡을 수 있어야 한다');
  });

  testWidgets('팝업 밖(가림막)을 끌어도 팝업은 안 움직인다', (tester) async {
    // 표면 전체를 먹어 버리면 가림막을 눌러 닫지도 못한다.
    await openDialog(tester);

    final before = tester.getCenter(find.byType(AlertDialog));
    await tester.dragFrom(const Offset(10, 10), const Offset(120, 90));
    await tester.pumpAndSettle();

    expect(tester.getCenter(find.byType(AlertDialog)), before);
  });

  testWidgets('안의 목록은 그대로 스크롤된다', (tester) async {
    // 팝업 이동이 안쪽 스크롤을 빼앗으면 긴 내용을 읽을 수 없다.
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => TextButton(
            onPressed: () => showMovableDialog<void>(
              context: context,
              builder: (_) => AlertDialog(
                content: SizedBox(
                  width: 300,
                  height: 200,
                  child: ListView(
                    children: [
                      for (var i = 0; i < 40; i++)
                        SizedBox(height: 40, child: Text('줄 $i')),
                    ],
                  ),
                ),
              ),
            ),
            child: const Text('열기'),
          ),
        ),
      ),
    );
    await tester.tap(find.text('열기'));
    await tester.pumpAndSettle();

    final dialogBefore = tester.getCenter(find.byType(AlertDialog));
    await tester.drag(find.text('줄 1'), const Offset(0, -200));
    await tester.pumpAndSettle();

    expect(find.text('줄 0'), findsNothing, reason: '목록이 스크롤되어야 한다');
    expect(
      tester.getCenter(find.byType(AlertDialog)),
      dialogBefore,
      reason: '스크롤이 팝업을 끌고 다니면 안 된다',
    );
  });

  testWidgets('옮길 수 있어도 안의 버튼은 그대로 눌린다', (tester) async {
    var taps = 0;
    await openDialog(tester, onPressed: () => taps++);

    await tester.drag(handle, const Offset(50, 50));
    await tester.pumpAndSettle();
    await tester.tap(find.text('확인'));
    await tester.pumpAndSettle();

    expect(taps, 1, reason: '옮긴 뒤에도 버튼이 동작해야 한다');
  });
}
