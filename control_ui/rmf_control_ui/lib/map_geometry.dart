import 'dart:math' as math;
import 'dart:ui';

/// A wall or a lane: two points in image pixel coordinates.
typedef Segment = (Offset, Offset);

/// Distance from [point] to the segment [start]-[end].
double pointSegmentDistance(Offset point, Offset start, Offset end) {
  final vector = end - start;
  final lengthSquared = vector.dx * vector.dx + vector.dy * vector.dy;
  if (lengthSquared <= .0001) return (point - start).distance;
  final ratio =
      (((point.dx - start.dx) * vector.dx + (point.dy - start.dy) * vector.dy) /
              lengthSquared)
          .clamp(0.0, 1.0);
  return (point - (start + vector * ratio)).distance;
}

/// Whether two segments touch or cross, including endpoint contact and
/// overlapping collinear segments.
bool segmentsCross(Offset a, Offset b, Offset c, Offset d) {
  double side(Offset p, Offset q, Offset r) =>
      (q.dx - p.dx) * (r.dy - p.dy) - (q.dy - p.dy) * (r.dx - p.dx);
  bool onSegment(Offset p, Offset q, Offset r) =>
      q.dx >= math.min(p.dx, r.dx) - .01 &&
      q.dx <= math.max(p.dx, r.dx) + .01 &&
      q.dy >= math.min(p.dy, r.dy) - .01 &&
      q.dy <= math.max(p.dy, r.dy) + .01;
  final abC = side(a, b, c);
  final abD = side(a, b, d);
  final cdA = side(c, d, a);
  final cdB = side(c, d, b);
  if (((abC > .01 && abD < -.01) || (abC < -.01 && abD > .01)) &&
      ((cdA > .01 && cdB < -.01) || (cdA < -.01 && cdB > .01))) {
    return true;
  }
  if (abC.abs() <= .01 && onSegment(a, c, b)) return true;
  if (abD.abs() <= .01 && onSegment(a, d, b)) return true;
  if (cdA.abs() <= .01 && onSegment(c, a, d)) return true;
  if (cdB.abs() <= .01 && onSegment(c, b, d)) return true;
  return false;
}

/// Distance between two segments.
///
/// Endpoint distances alone read as "far apart" for two segments that cross,
/// so a crossing is detected first and reported as zero.
double segmentDistance(Offset a, Offset b, Offset c, Offset d) {
  if (segmentsCross(a, b, c, d)) return 0;
  return [
    pointSegmentDistance(a, c, d),
    pointSegmentDistance(b, c, d),
    pointSegmentDistance(c, a, b),
    pointSegmentDistance(d, a, b),
  ].reduce(math.min);
}

/// Distance from the segment [start]-[end] to the nearest of [walls].
double segmentWallClearance(Offset start, Offset end, List<Segment> walls) {
  var clearance = double.infinity;
  for (final wall in walls) {
    clearance = math.min(
      clearance,
      segmentDistance(start, end, wall.$1, wall.$2),
    );
  }
  return clearance;
}

/// Whether [point] is inside [polygon], counting points on the edge as inside.
bool insidePolygon(
  Offset point,
  List<Offset> polygon, {
  double edgeTolerance = .5,
}) {
  if (polygon.length < 3) return false;
  for (var index = 0; index < polygon.length; index++) {
    if (pointSegmentDistance(
          point,
          polygon[index],
          polygon[(index + 1) % polygon.length],
        ) <=
        edgeTolerance) {
      return true;
    }
  }
  var inside = false;
  for (var i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    final a = polygon[i];
    final b = polygon[j];
    final crosses =
        (a.dy > point.dy) != (b.dy > point.dy) &&
        point.dx < (b.dx - a.dx) * (point.dy - a.dy) / (b.dy - a.dy) + a.dx;
    if (crosses) inside = !inside;
  }
  return inside;
}

/// Why a dragged Waypoint may not be dropped where it was released.
enum WaypointMoveIssue {
  /// The drop point is outside the Floor polygon.
  outsideFloor,

  /// Another Waypoint already sits on the drop point.
  waypointTooClose,

  /// A Lane attached to the dragged Waypoint would run into a wall.
  laneTouchesWall,
}

/// Checks whether [original] may be dropped at [updated].
///
/// Only Lanes attached to the dragged Waypoint are checked. Lanes elsewhere on
/// the map keep whatever state they were already in — a Lane that is too close
/// to a wall somewhere else is a problem to fix there, not a reason to freeze
/// every Waypoint on the map in place.
WaypointMoveIssue? waypointMoveIssue({
  required Offset original,
  required Offset updated,
  required List<Offset> waypoints,
  required List<Segment> lanes,
  required List<Segment> walls,
  required List<Offset> floorOutline,
  required double laneWallClearance,
  double waypointGap = 4,
}) {
  if (!insidePolygon(updated, floorOutline)) {
    return WaypointMoveIssue.outsideFloor;
  }
  for (final point in waypoints) {
    if ((point - original).distance <= .01) continue;
    if ((point - updated).distance < waypointGap) {
      return WaypointMoveIssue.waypointTooClose;
    }
  }
  for (final lane in lanes) {
    final startMoves = (lane.$1 - original).distance <= .01;
    final endMoves = (lane.$2 - original).distance <= .01;
    if (!startMoves && !endMoves) continue;
    final start = startMoves ? updated : lane.$1;
    final end = endMoves ? updated : lane.$2;
    if (segmentWallClearance(start, end, walls) < laneWallClearance - .01) {
      return WaypointMoveIssue.laneTouchesWall;
    }
  }
  return null;
}

/// [point] 를 [origin] 기준 가로 또는 세로 한 방향으로 묶는다.
///
/// Waypoint 를 Shift 와 함께 끌 때 쓴다. 더 많이 끈 축을 남기고 다른 축은
/// 시작값으로 되돌리므로, 통로를 따라 일직선으로 늘어놓을 때 눈대중으로 맞추지
/// 않아도 된다. 가로·세로 이동량이 같으면 가로를 남긴다.
Offset constrainToAxis(Offset origin, Offset point) {
  final delta = point - origin;
  return delta.dx.abs() >= delta.dy.abs()
      ? Offset(point.dx, origin.dy)
      : Offset(origin.dx, point.dy);
}

/// [point] 에서 가장 가까운 [start]-[end] 선분 위의 점.
///
/// Waypoint 를 레인 위에 얹을 때 좌표를 선 위로 맞추는 데 쓴다. 눈으로는 선
/// 위에 놓았는데 몇 픽셀 떨어져 있으면, 그 Waypoint 는 레인에 끼워 넣을 수
/// 없어 로봇이 지나갈 수 없는 외딴 지점이 된다.
Offset closestPointOnSegment(Offset point, Offset start, Offset end) {
  final vector = end - start;
  final lengthSquared = vector.dx * vector.dx + vector.dy * vector.dy;
  if (lengthSquared <= .0001) return start;
  final ratio =
      (((point.dx - start.dx) * vector.dx + (point.dy - start.dy) * vector.dy) /
              lengthSquared)
          .clamp(0.0, 1.0);
  return start + vector * ratio;
}
