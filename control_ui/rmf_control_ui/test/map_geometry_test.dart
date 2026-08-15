import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/map_geometry.dart';

/// A 1000 x 800 room with a stub wall hanging down from the ceiling at x=500.
const _walls = <Segment>[
  (Offset(0, 0), Offset(1000, 0)),
  (Offset(0, 800), Offset(1000, 800)),
  (Offset(0, 0), Offset(0, 800)),
  (Offset(1000, 0), Offset(1000, 800)),
  (Offset(500, 0), Offset(500, 300)),
];

const _floor = <Offset>[
  Offset(0, 0),
  Offset(1000, 0),
  Offset(1000, 800),
  Offset(0, 800),
];

void main() {
  group('segmentDistance', () {
    test('reports zero for segments that cross', () {
      // Endpoint distances alone would call these 200 px apart.
      expect(
        segmentDistance(
          const Offset(250, 200),
          const Offset(750, 200),
          const Offset(500, 0),
          const Offset(500, 400),
        ),
        0,
      );
    });

    test('measures the gap for segments that miss each other', () {
      expect(
        segmentDistance(
          const Offset(0, 0),
          const Offset(100, 0),
          const Offset(0, 30),
          const Offset(100, 30),
        ),
        closeTo(30, .001),
      );
    });
  });

  group('waypointMoveIssue', () {
    WaypointMoveIssue? issueFor(
      Offset original,
      Offset updated, {
      List<Offset> waypoints = const [],
      List<Segment> lanes = const [],
      double clearance = 40,
    }) => waypointMoveIssue(
      original: original,
      updated: updated,
      waypoints: waypoints.isEmpty ? [original] : waypoints,
      lanes: lanes,
      walls: _walls,
      floorOutline: _floor,
      laneWallClearance: clearance,
    );

    test('allows a move into open floor', () {
      expect(issueFor(const Offset(200, 500), const Offset(300, 500)), isNull);
    });

    test('refuses a drop outside the floor', () {
      expect(
        issueFor(const Offset(200, 500), const Offset(1200, 500)),
        WaypointMoveIssue.outsideFloor,
      );
    });

    test('refuses a drop on top of another waypoint', () {
      expect(
        issueFor(
          const Offset(200, 500),
          const Offset(400, 502),
          waypoints: const [Offset(200, 500), Offset(400, 500)],
        ),
        WaypointMoveIssue.waypointTooClose,
      );
    });

    test('refuses a move that pushes its own lane into a wall', () {
      // The lane would end 10 px from the ceiling; it needs 40.
      expect(
        issueFor(
          const Offset(200, 500),
          const Offset(200, 10),
          waypoints: const [Offset(200, 500), Offset(200, 600)],
          lanes: const [(Offset(200, 500), Offset(200, 600))],
        ),
        WaypointMoveIssue.laneTouchesWall,
      );
    });

    test('refuses a move that drags its own lane across a wall', () {
      expect(
        issueFor(
          // Dragged to the far side of the stub wall, so the lane it carries
          // sweeps straight through that wall.
          const Offset(250, 200),
          const Offset(750, 200),
          waypoints: const [Offset(250, 200), Offset(250, 100)],
          lanes: const [(Offset(250, 200), Offset(250, 100))],
        ),
        WaypointMoveIssue.laneTouchesWall,
      );
    });

    test('ignores lanes elsewhere that already break the clearance', () {
      // A pre-existing lane 10 px from the ceiling used to block every drag on
      // the map, including moves that have nothing to do with it.
      expect(
        issueFor(
          const Offset(200, 500),
          const Offset(300, 500),
          waypoints: const [Offset(200, 500), Offset(700, 10), Offset(900, 10)],
          lanes: const [(Offset(700, 10), Offset(900, 10))],
        ),
        isNull,
      );
    });

    test('keeps checking the lanes attached to the dragged waypoint', () {
      expect(
        issueFor(
          const Offset(200, 500),
          const Offset(200, 10),
          waypoints: const [
            Offset(200, 500),
            Offset(200, 600),
            Offset(700, 10),
            Offset(900, 10),
          ],
          lanes: const [
            (Offset(200, 500), Offset(200, 600)),
            (Offset(700, 10), Offset(900, 10)),
          ],
        ),
        WaypointMoveIssue.laneTouchesWall,
      );
    });
  });

  group('constrainToAxis', () {
    const origin = Offset(100, 100);

    test('가로로 더 많이 끌면 세로는 시작값에 묶인다', () {
      expect(
        constrainToAxis(origin, const Offset(160, 130)),
        const Offset(160, 100),
      );
    });

    test('세로로 더 많이 끌면 가로는 시작값에 묶인다', () {
      expect(
        constrainToAxis(origin, const Offset(130, 160)),
        const Offset(100, 160),
      );
    });

    test('반대 방향으로 끌어도 축은 이동량 크기로 고른다', () {
      expect(
        constrainToAxis(origin, const Offset(40, 80)),
        const Offset(40, 100),
        reason: '가로 60 · 세로 20 이므로 가로가 남는다',
      );
    });

    test('가로·세로 이동량이 같으면 가로를 남긴다', () {
      expect(
        constrainToAxis(origin, const Offset(150, 150)),
        const Offset(150, 100),
      );
    });

    test('움직이지 않았으면 그대로 둔다', () {
      expect(constrainToAxis(origin, origin), origin);
    });
  });

  group('closestPointOnSegment', () {
    test('선분 위로 수직 투영한다', () {
      expect(
        closestPointOnSegment(
          const Offset(50, 10),
          const Offset(0, 0),
          const Offset(100, 0),
        ),
        const Offset(50, 0),
      );
    });

    test('선분 밖이면 가까운 끝점으로 묶는다', () {
      expect(
        closestPointOnSegment(
          const Offset(-30, 5),
          const Offset(0, 0),
          const Offset(100, 0),
        ),
        const Offset(0, 0),
      );
      expect(
        closestPointOnSegment(
          const Offset(130, 5),
          const Offset(0, 0),
          const Offset(100, 0),
        ),
        const Offset(100, 0),
      );
    });

    test('길이가 없는 선분은 시작점을 돌려준다', () {
      expect(
        closestPointOnSegment(
          const Offset(9, 9),
          const Offset(4, 4),
          const Offset(4, 4),
        ),
        const Offset(4, 4),
      );
    });

    test('실제로 문제가 됐던 대기5 좌표를 레인 위로 맞춘다', () {
      // 대기5 는 드랍오프1 — 대기1 레인에서 0.2px 떨어져 있었다. 눈으로는 선
      // 위인데 연결되지 않아 로봇이 지나갈 수 없었다.
      final snapped = closestPointOnSegment(
        const Offset(1539.2180708254127, 264.28777249088154),
        const Offset(1712.1041927469707, 264.3628158493872),
        const Offset(889.5, 262.8),
      );
      expect(
        pointSegmentDistance(
          snapped,
          const Offset(1712.1041927469707, 264.3628158493872),
          const Offset(889.5, 262.8),
        ),
        closeTo(0, .001),
      );
    });
  });
}
