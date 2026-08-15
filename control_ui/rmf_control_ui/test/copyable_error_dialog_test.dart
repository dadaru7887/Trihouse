import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/main.dart';

/// Waypoint를 찍다 난 오류를 보여 주는 팝업의 계약을 확인한다.
///
/// 스낵바로는 긴 진단 문구를 다 읽기 전에 사라지고 값을 옮겨 적을 수도 없어서
/// 팝업으로 바꿨다. 그 팝업이 실제로 남아 있고, 복사되고, 넓어지는지 본다.
void main() {
  const message =
      '벽에 너무 가까워 Lane을 만들 수 없습니다. 필요 여유 349px(0.40m), '
      '실제 120px(0.14m). 로봇 폭 0.60m · 위치 오차 여유 0.10m · '
      '축척 873px/m 기준입니다.';

  /// 오류 팝업을 띄운 화면을 만든다.
  Future<void> pumpDialog(WidgetTester tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => TextButton(
              onPressed: () => showWaypointErrorDialog(
                context,
                title: 'Waypoint · Lane 오류',
                message: message,
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

  testWidgets('오류 내용을 그대로 보여 주고 닫기 전에는 사라지지 않는다', (tester) async {
    await pumpDialog(tester);

    expect(find.text('Waypoint · Lane 오류'), findsOneWidget);
    expect(find.text(message), findsOneWidget);

    // 스낵바와 달리 시간이 지나도 남아 있어야 한다.
    await tester.pump(const Duration(seconds: 30));
    expect(find.text(message), findsOneWidget);

    await tester.tap(find.text('닫기'));
    await tester.pumpAndSettle();
    expect(find.text(message), findsNothing);
  });

  testWidgets('복사 버튼이 오류 전문을 클립보드에 넣는다', (tester) async {
    String? copied;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (call) async {
        if (call.method == 'Clipboard.setData') {
          copied = (call.arguments as Map)['text'] as String?;
        }
        return null;
      },
    );
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        null,
      ),
    );

    await pumpDialog(tester);
    await tester.tap(find.text('복사'));
    await tester.pumpAndSettle();

    expect(copied, message, reason: '잘리지 않은 전문이 복사돼야 한다');
    expect(find.text('오류 내용을 클립보드에 복사했습니다.'), findsOneWidget);
  });

  testWidgets('모서리를 끌면 팝업이 커진다', (tester) async {
    await pumpDialog(tester);

    Size bodySize() => tester.getSize(
      find
          .ancestor(
            of: find.byIcon(Icons.open_in_full),
            matching: find.byType(SizedBox),
          )
          .first,
    );

    final before = bodySize();
    await tester.drag(find.byIcon(Icons.open_in_full), const Offset(120, 90));
    await tester.pumpAndSettle();
    final after = bodySize();

    expect(after.width, greaterThan(before.width));
    expect(after.height, greaterThan(before.height));
  });
}
