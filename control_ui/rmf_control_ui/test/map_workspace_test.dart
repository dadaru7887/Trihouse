import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/trihouse/presentation/map_workspace.dart';

void main() {
  testWidgets(
    'Team A map Waypoint handle wins drag and tracks pointer exactly',
    (tester) async {
      final controller = TransformationController();
      MapWaypointPresentation? moved;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 800,
              height: 700,
              child: MapWorkspace(
                transformationController: controller,
                waypoints: const [
                  MapWaypointPresentation(
                    code: 'PACKING-01-DOCK-01',
                    position: Offset(300, 260),
                    yaw: 1.57,
                  ),
                ],
                onWaypointMoved: (waypoint) => moved = waypoint,
              ),
            ),
          ),
        ),
      );

      await tester.drag(
        find.byKey(const Key('waypoint-PACKING-01-DOCK-01')),
        const Offset(60, 40),
      );
      await tester.pumpAndSettle();

      expect(moved?.position, const Offset(360, 300));
      expect(controller.value, Matrix4.identity());
    },
  );

  testWidgets('map workspace keeps Team A editor controls without Lane tools', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: MapWorkspace(waypoints: [], onWaypointMoved: _ignoreWaypoint),
        ),
      ),
    );

    expect(find.text('도면 작업 영역'), findsOneWidget);
    expect(find.text('Waypoint 편집'), findsOneWidget);
    expect(find.byTooltip('축소'), findsOneWidget);
    expect(find.byTooltip('확대'), findsOneWidget);
    expect(find.byTooltip('화면 맞춤'), findsOneWidget);
    expect(find.textContaining('Lane'), findsNothing);
  });
}

void _ignoreWaypoint(MapWaypointPresentation waypoint) {}
