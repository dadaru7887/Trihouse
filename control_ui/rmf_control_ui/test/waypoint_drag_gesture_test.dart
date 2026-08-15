import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// The map canvas sits inside an `InteractiveViewer` that pans the drawing and
/// the Waypoint drag handles sit on top of it, so both want the same drag.
/// This pins down what the drag relies on: the handle wins the gesture, the map
/// stays put underneath, and the Waypoint tracks the pointer one to one.
///
/// The last part needs `DragStartBehavior.down`. With the default `start` the
/// distance the recognizer swallows before it accepts the drag is never
/// reported, so a grabbed Waypoint arrives short of the cursor.
void main() {
  Widget canvas({
    required DragStartBehavior dragStartBehavior,
    required TransformationController controller,
    required void Function(DragStartDetails) onStart,
    required void Function(DragUpdateDetails) onUpdate,
    void Function(DragEndDetails)? onEnd,
  }) => MaterialApp(
    home: Scaffold(
      body: Center(
        child: SizedBox(
          width: 400,
          height: 400,
          child: InteractiveViewer(
            transformationController: controller,
            child: Stack(
              children: [
                const Positioned.fill(
                  child: ColoredBox(color: Color(0xFFFFFFFF)),
                ),
                Positioned(
                  left: 182,
                  top: 182,
                  width: 36,
                  height: 36,
                  child: GestureDetector(
                    key: const Key('handle'),
                    behavior: HitTestBehavior.opaque,
                    dragStartBehavior: dragStartBehavior,
                    onPanStart: onStart,
                    onPanUpdate: onUpdate,
                    onPanEnd: onEnd,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );

  testWidgets('a drag handle over the map wins over the viewer pan', (
    tester,
  ) async {
    final controller = TransformationController();
    var moved = Offset.zero;
    var releases = 0;

    await tester.pumpWidget(
      canvas(
        dragStartBehavior: DragStartBehavior.down,
        controller: controller,
        onStart: (_) => moved = Offset.zero,
        onUpdate: (details) => moved += details.delta,
        onEnd: (_) => releases++,
      ),
    );
    await tester.drag(find.byKey(const Key('handle')), const Offset(60, 40));
    await tester.pumpAndSettle();

    expect(releases, 1);
    // The Waypoint lands exactly where the pointer was released.
    expect(moved, const Offset(60, 40));
    // The drawing underneath did not scroll away with it.
    expect(controller.value, Matrix4.identity());
  });

  testWidgets('the default drag start behavior would lag behind the cursor', (
    tester,
  ) async {
    final controller = TransformationController();
    var moved = Offset.zero;

    await tester.pumpWidget(
      canvas(
        dragStartBehavior: DragStartBehavior.start,
        controller: controller,
        onStart: (_) => moved = Offset.zero,
        onUpdate: (details) => moved += details.delta,
      ),
    );
    await tester.drag(find.byKey(const Key('handle')), const Offset(60, 40));
    await tester.pumpAndSettle();

    expect(moved, isNot(const Offset(60, 40)));
  });
}
