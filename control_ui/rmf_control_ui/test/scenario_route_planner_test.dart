import 'dart:math' as math;
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/scenario_route_planner.dart';

/// Walls of the map that made the scenario assistant give up with
/// "확보 171.3px / 필요 173.9px": the outer shell plus the interior rooms.
const _gwangheeWalls = <WallSegment>[
  (Offset(71.5, 93.5), Offset(71.5, 2326.5)),
  (Offset(71.5, 93.5), Offset(1925, 93.5)),
  (Offset(1925, 93.5), Offset(1925, 1666.5)),
  (Offset(1389.5, 1183.6), Offset(1947, 1183.6)),
  (Offset(71.5, 2326.5), Offset(1287, 2326.5)),
  (Offset(753.5, 418), Offset(753.5, 1210)),
  (Offset(55, 1210), Offset(753.5, 1210)),
  (Offset(1287, 1666.5), Offset(1287, 2326.5)),
  (Offset(1287, 1666.5), Offset(1925, 1666.5)),
  (Offset(753.5, 1573), Offset(753.5, 2013)),
];

/// 0.2 m robot + 0.1 m localization margin over a 2.11 m / 1834.6 px scale.
const _gwangheeClearance = 173.89482685424784;

List<Offset> _convexHull(Iterable<Offset> points) {
  final sorted = points.toList()
    ..sort((a, b) {
      final x = a.dx.compareTo(b.dx);
      return x != 0 ? x : a.dy.compareTo(b.dy);
    });
  double cross(Offset origin, Offset a, Offset b) =>
      (a.dx - origin.dx) * (b.dy - origin.dy) -
      (a.dy - origin.dy) * (b.dx - origin.dx);
  final lower = <Offset>[];
  for (final point in sorted) {
    while (lower.length >= 2 &&
        cross(lower[lower.length - 2], lower.last, point) <= 0) {
      lower.removeLast();
    }
    lower.add(point);
  }
  final upper = <Offset>[];
  for (final point in sorted.reversed) {
    while (upper.length >= 2 &&
        cross(upper[upper.length - 2], upper.last, point) <= 0) {
      upper.removeLast();
    }
    upper.add(point);
  }
  return [...lower.take(lower.length - 1), ...upper.take(upper.length - 1)];
}

List<Offset> _outlineOf(List<WallSegment> walls) => _convexHull([
  for (final wall in walls) ...[wall.$1, wall.$2],
]);

ScenarioRoutePlanner _plannerFor(
  List<WallSegment> walls, {
  required double clearance,
}) => ScenarioRoutePlanner(
  walls: walls,
  floorOutline: _outlineOf(walls),
  clearancePixels: clearance,
);

/// Every consecutive pair of a returned route must be a lane the map editor
/// would accept: on the floor and clear of every wall.
void _expectRouteIsSafe(ScenarioRoutePlanner planner, List<Offset> route) {
  expect(route.length, greaterThanOrEqualTo(2));
  for (var index = 0; index < route.length - 1; index++) {
    final start = route[index];
    final end = route[index + 1];
    expect(
      planner.segmentClearance(start, end),
      greaterThanOrEqualTo(planner.clearancePixels - .01),
      reason: 'segment $start -> $end runs too close to a wall',
    );
    expect(planner.insideFloor(start), isTrue);
    expect(planner.insideFloor(end), isTrue);
  }
}

void main() {
  group('ScenarioRoutePlanner', () {
    test('plans a two-corridor loop on the map that used to fail', () {
      final planner = _plannerFor(
        _gwangheeWalls,
        clearance: _gwangheeClearance,
      );
      expect(planner.hasFreeSpace, isTrue);

      final plan = planner.planRoutes(waypointTarget: 12);
      expect(plan, isNotNull);
      expect(plan!.separateRoutes, isTrue);
      _expectRouteIsSafe(planner, plan.outbound);
      _expectRouteIsSafe(planner, plan.returnRoute);

      // The two corridors must be far enough apart for robots to pass.
      final outboundY = plan.outbound.first.dy;
      final returnY = plan.returnRoute.first.dy;
      expect(
        (outboundY - returnY).abs(),
        greaterThanOrEqualTo(planner.clearancePixels * 2),
      );

      // The upper hall is wide, so its corridor is drawn as an outbound and a
      // return one-way lane rather than one shared bidirectional lane.
      final upperHall = planner.splitCorridor([
        plan.outbound.first,
        plan.outbound.last,
      ]);
      expect(upperHall.single.isDoubled, isTrue);
      for (final chain in upperHall.single.chains) {
        _expectRouteIsSafe(planner, chain);
      }

      // The closing connectors are what the greedy detour search could not
      // find: outbound end -> return start and return end -> outbound start.
      for (final link in [
        (plan.outbound.last, plan.returnRoute.first),
        (plan.returnRoute.last, plan.outbound.first),
      ]) {
        final path = planner.planPath(link.$1, link.$2);
        expect(path, isNotNull, reason: 'no connector for $link');
        _expectRouteIsSafe(planner, path!);
        expect(path.first, link.$1);
        expect(path.last, link.$2);
      }
    });

    test('routes around a wall instead of cutting through it', () {
      const clearance = 40.0;
      const walls = <WallSegment>[
        (Offset(0, 0), Offset(1000, 0)),
        (Offset(0, 800), Offset(1000, 800)),
        (Offset(0, 0), Offset(0, 800)),
        (Offset(1000, 0), Offset(1000, 800)),
        (Offset(500, 0), Offset(500, 600)),
      ];
      final planner = _plannerFor(walls, clearance: clearance);
      final path = planner.planPath(
        const Offset(250, 200),
        const Offset(750, 200),
      );
      expect(path, isNotNull);
      _expectRouteIsSafe(planner, path!);
      // The straight line is blocked, so the route has to dip below the wall.
      expect(path.length, greaterThan(2));
      expect(path.map((point) => point.dy).reduce(math.max), greaterThan(600));
    });

    test('refuses to link a waypoint parked against a wall', () {
      const clearance = 40.0;
      const walls = <WallSegment>[
        (Offset(0, 0), Offset(1000, 0)),
        (Offset(0, 800), Offset(1000, 800)),
        (Offset(0, 0), Offset(0, 800)),
        (Offset(1000, 0), Offset(1000, 800)),
      ];
      final planner = _plannerFor(walls, clearance: clearance);
      expect(
        planner.planPath(const Offset(500, 400), const Offset(300, 400)),
        isNotNull,
      );
      // 10 px from the top wall: no lane can reach it with 40 px of clearance.
      expect(
        planner.planPath(const Offset(500, 10), const Offset(300, 400)),
        isNull,
      );
    });

    test('reports the widest clearance when no corridor fits', () {
      const walls = <WallSegment>[
        (Offset(0, 0), Offset(400, 0)),
        (Offset(0, 200), Offset(400, 200)),
        (Offset(0, 0), Offset(0, 200)),
        (Offset(400, 0), Offset(400, 200)),
      ];
      final planner = _plannerFor(walls, clearance: 300);
      expect(planner.hasFreeSpace, isFalse);
      expect(planner.planRoutes(waypointTarget: 8), isNull);
      // Half the short side of the room, so the user can size the robot.
      expect(planner.bestClearancePixels, closeTo(100, 12));
    });

    test('falls back to one shared corridor in a narrow building', () {
      const clearance = 40.0;
      const walls = <WallSegment>[
        (Offset(0, 0), Offset(1200, 0)),
        (Offset(0, 130), Offset(1200, 130)),
        (Offset(0, 0), Offset(0, 130)),
        (Offset(1200, 0), Offset(1200, 130)),
      ];
      final planner = _plannerFor(walls, clearance: clearance);
      final plan = planner.planRoutes(waypointTarget: 8);
      expect(plan, isNotNull);
      expect(plan!.separateRoutes, isFalse);
      expect(plan.returnRoute, isEmpty);
      _expectRouteIsSafe(planner, plan.outbound);
      // The one corridor runs down the middle of the passage.
      expect(plan.outbound.first.dy, closeTo(65, planner.cell));
    });

    test('splits a wide corridor into an outbound and a return lane', () {
      const clearance = 40.0;
      // 400 px wide hall: ten times the clearance, so two one-way lanes fit.
      const walls = <WallSegment>[
        (Offset(0, 0), Offset(2000, 0)),
        (Offset(0, 400), Offset(2000, 400)),
        (Offset(0, 0), Offset(0, 400)),
        (Offset(2000, 0), Offset(2000, 400)),
      ];
      final planner = _plannerFor(walls, clearance: clearance);
      final sections = planner.splitCorridor(const [
        Offset(200, 200),
        Offset(1800, 200),
      ]);
      expect(sections, hasLength(1));
      expect(sections.single.isDoubled, isTrue);

      final outbound = sections.single.outbound;
      final inbound = sections.single.inbound;
      _expectRouteIsSafe(planner, outbound);
      _expectRouteIsSafe(planner, inbound);
      // Both lanes start and end on the shared junction points, and run in
      // opposite directions.
      expect(outbound.first, const Offset(200, 200));
      expect(outbound.last, const Offset(1800, 200));
      expect(inbound.first, const Offset(1800, 200));
      expect(inbound.last, const Offset(200, 200));
      // The two lanes are one full robot width plus margins apart.
      final outboundY = outbound[1].dy;
      final inboundY = inbound[1].dy;
      expect((outboundY - inboundY).abs(), closeTo(clearance * 2, .01));
    });

    test('keeps a narrow corridor as one shared lane', () {
      const clearance = 40.0;
      // 130 px wide: one robot fits with clearance, two lanes do not.
      const walls = <WallSegment>[
        (Offset(0, 0), Offset(2000, 0)),
        (Offset(0, 130), Offset(2000, 130)),
        (Offset(0, 0), Offset(0, 130)),
        (Offset(2000, 0), Offset(2000, 130)),
      ];
      final planner = _plannerFor(walls, clearance: clearance);
      expect(
        planner.supportsLanePair(const Offset(200, 65), const Offset(1800, 65)),
        isFalse,
      );
      final sections = planner.splitCorridor(const [
        Offset(200, 65),
        Offset(1800, 65),
      ]);
      expect(sections, hasLength(1));
      expect(sections.single.isDoubled, isFalse);
      _expectRouteIsSafe(planner, sections.single.shared);
    });

    test('doubles only the wide half of a corridor that narrows', () {
      const clearance = 40.0;
      // Left half is a 400 px hall, right half a 140 px passage on the same
      // centre line.
      const walls = <WallSegment>[
        (Offset(0, 0), Offset(1000, 0)),
        (Offset(1000, 0), Offset(1000, 130)),
        (Offset(1000, 130), Offset(2000, 130)),
        (Offset(0, 400), Offset(1000, 400)),
        (Offset(1000, 400), Offset(1000, 270)),
        (Offset(1000, 270), Offset(2000, 270)),
        (Offset(0, 0), Offset(0, 400)),
        (Offset(2000, 130), Offset(2000, 270)),
      ];
      final planner = _plannerFor(walls, clearance: clearance);
      final sections = planner.splitCorridor(const [
        Offset(200, 200),
        Offset(900, 200),
        Offset(1800, 200),
      ]);
      expect(sections.map((section) => section.isDoubled), [true, false]);
      // The stretches meet at the junction the split was made on.
      expect(sections.first.outbound.last, const Offset(900, 200));
      expect(sections.first.inbound.first, const Offset(900, 200));
      expect(sections.last.shared.first, const Offset(900, 200));
      for (final section in sections) {
        for (final chain in section.chains) {
          _expectRouteIsSafe(planner, chain);
        }
      }
    });

    test('gives a wide hall room for an outbound and a return lane', () {
      const clearance = 40.0;
      // 400 px tall: ten clearances, so the corridors must not hug the walls.
      const walls = <WallSegment>[
        (Offset(0, 0), Offset(2000, 0)),
        (Offset(0, 400), Offset(2000, 400)),
        (Offset(0, 0), Offset(0, 400)),
        (Offset(2000, 0), Offset(2000, 400)),
      ];
      final planner = _plannerFor(walls, clearance: clearance);
      final plan = planner.planRoutes(waypointTarget: 8);
      expect(plan, isNotNull);
      expect(plan!.separateRoutes, isTrue);
      expect(
        (plan.outbound.first.dy - plan.returnRoute.first.dy).abs(),
        greaterThanOrEqualTo(clearance * 2),
      );
      for (final row in [plan.outbound, plan.returnRoute]) {
        // Centred in its half of the hall, not pinned against a wall.
        final middle = Offset((row.first.dx + row.last.dx) / 2, row.first.dy);
        expect(
          planner.pointClearance(middle),
          greaterThanOrEqualTo(clearance * 2),
        );
        expect(planner.supportsLanePair(row.first, row.last), isTrue);
      }
    });

    test('does not split a stretch too short to merge back out of', () {
      const clearance = 40.0;
      const walls = <WallSegment>[
        (Offset(0, 0), Offset(2000, 0)),
        (Offset(0, 400), Offset(2000, 400)),
        (Offset(0, 0), Offset(0, 400)),
        (Offset(2000, 0), Offset(2000, 400)),
      ];
      final planner = _plannerFor(walls, clearance: clearance);
      // 120 px long, under the four clearances a split needs to pay off.
      final sections = planner.splitCorridor(const [
        Offset(900, 200),
        Offset(1020, 200),
      ]);
      expect(sections.single.isDoubled, isFalse);
    });

    test('keeps every waypoint of a drafted row clear of the walls', () {
      final planner = _plannerFor(
        _gwangheeWalls,
        clearance: _gwangheeClearance,
      );
      final plan = planner.planRoutes(waypointTarget: 16)!;
      for (final point in [...plan.outbound, ...plan.returnRoute]) {
        expect(
          planner.pointClearance(point),
          greaterThanOrEqualTo(_gwangheeClearance),
          reason: '$point is too close to a wall',
        );
      }
    });
  });
}
