import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/main.dart';

/// ROS2 확인 화면.
///
/// 탭마다 **목록만** 보여 주고, 하나를 누르면 자세한 내용을 움직일 수 있는 팝업에
/// 띄운다. 테스트에서는 `ros2` 를 부르지 않으므로 목록은 비어 있고, 그때 왜
/// 비었는지 알려 주는지를 본다.
void main() {
  Future<void> openRos2(WidgetTester tester) async {
    tester.view.physicalSize = const Size(1600, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const RmfControlApp());
    await tester.pumpAndSettle();
    await tester.tap(find.text('ROS2 확인'));
    await tester.pumpAndSettle();
  }

  testWidgets('작업 관리와 설정 파일 사이에 있다', (tester) async {
    tester.view.physicalSize = const Size(1600, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const RmfControlApp());
    await tester.pumpAndSettle();

    // 사이드바에서 작업 → ROS2 확인 → 설정 파일 순서다.
    final files = tester.getTopLeft(find.text('설정 파일')).dy;
    final ros2 = tester.getTopLeft(find.text('ROS2 확인')).dy;
    final tasks = tester.getTopLeft(find.text('작업').first).dy;
    expect(tasks, lessThan(ros2));
    expect(ros2, lessThan(files));
  });

  testWidgets('네 탭이 있다', (tester) async {
    await openRos2(tester);
    // 탭 이름에 ros2 하위 명령을 함께 적어 무엇을 부르는지 보인다.
    expect(find.text('노드 (node)'), findsOneWidget);
    expect(find.text('토픽 (topic)'), findsOneWidget);
    expect(find.text('서비스 (service)'), findsOneWidget);
    expect(find.text('액션 (action)'), findsOneWidget);
  });

  testWidgets('목록이 비면 왜 비었는지 알려 준다', (tester) async {
    await openRos2(tester);
    // 테스트에서는 ros2 를 안 부른다. 그 사실을 화면이 숨기지 않아야 한다.
    expect(find.textContaining('ros2 를 부르지 않습니다'), findsWidgets);
  });

  testWidgets('돌릴 명령을 복사할 수 있다', (tester) async {
    // 터미널에서 그대로 재현할 수 있어야 원인을 짚는다.
    await openRos2(tester);
    expect(find.text('명령 복사'), findsOneWidget);
  });

  testWidgets('조회 방식을 골라 견줄 수 있다', (tester) async {
    // 데몬과 직접 탐색의 결과가 서로 다르게 나오는 일을 겪었다.
    await openRos2(tester);
    expect(find.text('데몬'), findsOneWidget);
    expect(find.text('직접 탐색'), findsOneWidget);

    await tester.tap(find.text('직접 탐색'));
    await tester.pumpAndSettle();
    // 직접 탐색일 때만 탐색 시간을 고른다.
    expect(find.text('탐색 시간'), findsOneWidget);
  });

  testWidgets('액션 탭에서는 탐색 시간을 묻지 않는다', (tester) async {
    // ros2 action 은 --no-daemon 도 --spin-time 도 받지 않는다.
    await openRos2(tester);
    await tester.tap(find.text('직접 탐색'));
    await tester.pumpAndSettle();
    expect(find.text('탐색 시간'), findsOneWidget);

    await tester.tap(find.text('액션 (action)'));
    await tester.pumpAndSettle();
    expect(find.text('탐색 시간'), findsNothing);
  });

  testWidgets('걸러내기 칸이 있다', (tester) async {
    await openRos2(tester);
    expect(find.text('이름·형식으로 걸러내기'), findsOneWidget);
  });

  testWidgets('숨은 것 보기는 액션 탭에만 없다', (tester) async {
    await openRos2(tester);
    expect(find.text('숨은 것까지'), findsOneWidget);
    await tester.tap(find.text('액션 (action)'));
    await tester.pumpAndSettle();
    expect(find.text('숨은 것까지'), findsNothing);
  });
}
