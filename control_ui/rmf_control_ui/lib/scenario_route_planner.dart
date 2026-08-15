import 'dart:collection';
import 'dart:math' as math;
import 'dart:ui';

import 'map_geometry.dart';

/// A wall as drawn on the floor plan, in image pixel coordinates.
typedef WallSegment = (Offset, Offset);

/// The corridor skeleton the scenario assistant lays down before it assigns
/// operational roles: an outbound row and, when the building is wide enough
/// for two robots to pass, a separate return row.
class ScenarioRoutePlan {
  const ScenarioRoutePlan({
    required this.outbound,
    required this.returnRoute,
    required this.separateRoutes,
  });

  final List<Offset> outbound;
  final List<Offset> returnRoute;
  final bool separateRoutes;
}

/// One stretch of a drafted corridor.
///
/// A wide stretch carries two one-way lanes — an outbound and a returning one
/// — so robots travelling opposite ways never meet head-on. A narrow stretch
/// stays a single shared bidirectional lane, because two lanes would not both
/// fit with the required wall clearance.
class ScenarioCorridorSection {
  const ScenarioCorridorSection.shared(this.shared)
    : outbound = const [],
      inbound = const [];

  const ScenarioCorridorSection.doubled({
    required this.outbound,
    required this.inbound,
  }) : shared = const [];

  /// Bidirectional lane chain; empty when the stretch is doubled.
  final List<Offset> shared;

  /// One-way chain in travel order; empty when the stretch is shared.
  final List<Offset> outbound;

  /// One-way chain running back, already in its own travel order.
  final List<Offset> inbound;

  bool get isDoubled => outbound.length >= 2 && inbound.length >= 2;

  /// The chains this stretch contributes, whichever shape it took.
  List<List<Offset>> get chains => isDoubled ? [outbound, inbound] : [shared];
}

/// Plans scenario draft routes that keep a fixed clearance from every wall.
///
/// The floor is rasterised into cells that are open only when their centre is
/// inside the floor outline, covered by the detected floor mask (when one
/// exists) and at least [clearancePixels] plus a rasterisation margin away
/// from every wall. Routes are then laid out inside a single connected
/// component of that grid, so every lane the planner returns is reachable
/// without ever squeezing a robot against a wall.
///
/// The margin matters: wall distance is 1-Lipschitz, so a straight move
/// between two open cell centres can dip at most half a diagonal below the
/// clearance measured at those centres. Reserving `cell * .75` keeps the whole
/// move safe, and every returned polyline is still verified exactly with
/// [segmentAllowed] before it is handed back.
class ScenarioRoutePlanner {
  ScenarioRoutePlanner({
    required this.walls,
    required this.floorOutline,
    required this.clearancePixels,
    List<Offset> floorMaskPoints = const [],
    int maxCells = 40000,
  }) {
    if (floorOutline.length < 3 || clearancePixels <= 0) {
      cell = 1;
      columns = 0;
      rows = 0;
      origin = Offset.zero;
      _component = const [];
      _mainComponent = -1;
      bestClearancePixels = 0;
      return;
    }
    final bounds = _bounds();
    origin = bounds.topLeft;
    final area = math.max(bounds.width, 1.0) * math.max(bounds.height, 1.0);
    cell = math.max(
      (clearancePixels / 8).clamp(6.0, 24.0),
      math.sqrt(area / maxCells),
    );
    columns = (bounds.width / cell).ceil() + 1;
    rows = (bounds.height / cell).ceil() + 1;
    _buildGrid(floorMaskPoints);
  }

  /// Walls the routes must stay clear of, in image pixel coordinates.
  final List<WallSegment> walls;

  /// Floor boundary polygon; routes never leave it.
  final List<Offset> floorOutline;

  /// Required distance between any lane and any wall, in image pixels.
  final double clearancePixels;

  late final double cell;
  late final int columns;
  late final int rows;
  late final Offset origin;

  /// Component id per cell, or -1 when the cell is blocked.
  late final List<int> _component;
  late final int _mainComponent;

  /// Widest wall clearance found anywhere on the floor. Reported to the user
  /// when no corridor is wide enough, so the robot width or the localization
  /// margin can be adjusted with a concrete number instead of a guess.
  late final double bestClearancePixels;

  bool get hasFreeSpace => _mainComponent >= 0;

  int _index(int column, int row) => row * columns + column;

  bool _inGrid(int column, int row) =>
      column >= 0 && row >= 0 && column < columns && row < rows;

  bool isOpen(int column, int row) =>
      _mainComponent >= 0 &&
      _inGrid(column, row) &&
      _component[_index(column, row)] == _mainComponent;

  Offset center(int column, int row) =>
      Offset(origin.dx + (column + .5) * cell, origin.dy + (row + .5) * cell);

  (int, int) cellOf(Offset point) => (
    ((point.dx - origin.dx) / cell).floor(),
    ((point.dy - origin.dy) / cell).floor(),
  );

  Rect _bounds() {
    var left = floorOutline.first.dx;
    var top = floorOutline.first.dy;
    var right = left;
    var bottom = top;
    for (final point in floorOutline.skip(1)) {
      left = math.min(left, point.dx);
      top = math.min(top, point.dy);
      right = math.max(right, point.dx);
      bottom = math.max(bottom, point.dy);
    }
    return Rect.fromLTRB(left, top, right, bottom);
  }

  void _buildGrid(List<Offset> floorMaskPoints) {
    final maskCells = <int>{};
    for (final point in floorMaskPoints) {
      final (column, row) = cellOf(point);
      if (_inGrid(column, row)) maskCells.add(_index(column, row));
    }
    final useMask = maskCells.isNotEmpty;
    final margin = cell * .75;
    final open = List<bool>.filled(columns * rows, false);
    var best = 0.0;
    for (var row = 0; row < rows; row++) {
      for (var column = 0; column < columns; column++) {
        final index = _index(column, row);
        if (useMask && !maskCells.contains(index)) continue;
        final point = center(column, row);
        if (!insideFloor(point)) continue;
        final clearance = pointClearance(point);
        best = math.max(best, clearance);
        if (clearance >= clearancePixels + margin) open[index] = true;
      }
    }
    bestClearancePixels = best;
    _component = _labelComponents(open);
  }

  List<int> _labelComponents(List<bool> open) {
    final component = List<int>.filled(open.length, -1);
    final sizes = <int>[];
    final queue = Queue<int>();
    for (var start = 0; start < open.length; start++) {
      if (!open[start] || component[start] >= 0) continue;
      final id = sizes.length;
      component[start] = id;
      queue.add(start);
      var size = 0;
      while (queue.isNotEmpty) {
        final index = queue.removeFirst();
        size++;
        final column = index % columns;
        final row = index ~/ columns;
        for (var dc = -1; dc <= 1; dc++) {
          for (var dr = -1; dr <= 1; dr++) {
            if (dc == 0 && dr == 0) continue;
            final nc = column + dc;
            final nr = row + dr;
            if (!_inGrid(nc, nr)) continue;
            final neighbor = _index(nc, nr);
            if (!open[neighbor] || component[neighbor] >= 0) continue;
            // Refuse diagonal moves that cut a wall corner.
            if (dc != 0 &&
                dr != 0 &&
                !(open[_index(nc, row)] && open[_index(column, nr)])) {
              continue;
            }
            component[neighbor] = id;
            queue.add(neighbor);
          }
        }
      }
      sizes.add(size);
    }
    var main = -1;
    for (var id = 0; id < sizes.length; id++) {
      if (main < 0 || sizes[id] > sizes[main]) main = id;
    }
    _mainComponent = main;
    return component;
  }

  /// Distance from [point] to the nearest wall.
  double pointClearance(Offset point) {
    var clearance = double.infinity;
    for (final wall in walls) {
      clearance = math.min(
        clearance,
        pointSegmentDistance(point, wall.$1, wall.$2),
      );
    }
    return clearance;
  }

  /// Distance from the segment [start]-[end] to the nearest wall.
  double segmentClearance(Offset start, Offset end) {
    var clearance = double.infinity;
    for (final wall in walls) {
      clearance = math.min(
        clearance,
        segmentDistance(start, end, wall.$1, wall.$2),
      );
    }
    return clearance;
  }

  /// True when a lane may run straight from [start] to [end]: both ends sit on
  /// the floor and the whole segment keeps the required wall clearance.
  bool segmentAllowed(Offset start, Offset end) =>
      insideFloor(start) &&
      insideFloor(end) &&
      segmentClearance(start, end) >= clearancePixels - .01;

  bool insideFloor(Offset point) {
    if (floorOutline.length < 3) return false;
    for (var index = 0; index < floorOutline.length; index++) {
      if (pointSegmentDistance(
            point,
            floorOutline[index],
            floorOutline[(index + 1) % floorOutline.length],
          ) <=
          .5) {
        return true;
      }
    }
    var inside = false;
    for (
      var i = 0, j = floorOutline.length - 1;
      i < floorOutline.length;
      j = i++
    ) {
      final a = floorOutline[i];
      final b = floorOutline[j];
      final crosses =
          (a.dy > point.dy) != (b.dy > point.dy) &&
          point.dx < (b.dx - a.dx) * (point.dy - a.dy) / (b.dy - a.dy) + a.dx;
      if (crosses) inside = !inside;
    }
    return inside;
  }

  /// Nearest open cell to [point], searched outwards for a few rings so a
  /// waypoint that sits just inside a blocked cell still connects.
  (int, int)? _snap(Offset point, {int maxRings = 4}) {
    final (column, row) = cellOf(point);
    if (isOpen(column, row)) return (column, row);
    for (var ring = 1; ring <= maxRings; ring++) {
      (int, int)? best;
      var bestDistance = double.infinity;
      for (var dc = -ring; dc <= ring; dc++) {
        for (var dr = -ring; dr <= ring; dr++) {
          if (dc.abs() != ring && dr.abs() != ring) continue;
          final nc = column + dc;
          final nr = row + dr;
          if (!isOpen(nc, nr)) continue;
          final distance = (center(nc, nr) - point).distance;
          if (distance < bestDistance) {
            bestDistance = distance;
            best = (nc, nr);
          }
        }
      }
      if (best != null) return best;
    }
    return null;
  }

  /// Distance either side of a corridor centre line where the two one-way
  /// lanes of a doubled corridor run. Both lanes still owe every wall the full
  /// [clearancePixels], and they are `2 * clearancePixels` apart from each
  /// other, so a corridor must be four clearances wide to be doubled.
  double get lanePairOffsetPixels => clearancePixels;

  /// Whether a wide-corridor round trip fits along [start]-[end]: both one-way
  /// centre lines stay on the floor and keep the full wall clearance for the
  /// whole stretch.
  bool supportsLanePair(Offset start, Offset end) {
    final vector = end - start;
    final length = vector.distance;
    if (length <= .01) return false;
    final tangent = vector / length;
    final normal = Offset(-tangent.dy, tangent.dx);
    final steps = math.max(2, (length / math.max(cell, 1)).ceil());
    for (var step = 0; step <= steps; step++) {
      final point = start + vector * (step / steps);
      for (final side in const [1.0, -1.0]) {
        final shifted = point + normal * (lanePairOffsetPixels * side);
        if (!insideFloor(shifted)) return false;
        if (pointClearance(shifted) < clearancePixels - .01) return false;
      }
    }
    return true;
  }

  /// Splits a planned corridor into stretches that carry a separate outbound
  /// and return lane where the passage is wide enough, and a single shared
  /// lane where it is not. Junction points are shared between neighbouring
  /// stretches, so the chain stays connected end to end.
  List<ScenarioCorridorSection> splitCorridor(List<Offset> path) {
    if (path.length < 2) return const [];
    final wide = [
      for (var index = 0; index < path.length - 1; index++)
        supportsLanePair(path[index], path[index + 1]),
    ];
    final sections = <ScenarioCorridorSection>[];
    var start = 0;
    while (start < wide.length) {
      var end = start;
      while (end + 1 < wide.length && wide[end + 1] == wide[start]) {
        end++;
      }
      final run = path.sublist(start, end + 2);
      final pair = wide[start] ? _lanePair(run) : null;
      sections.add(
        pair == null
            ? ScenarioCorridorSection.shared(run)
            : ScenarioCorridorSection.doubled(
                outbound: pair.$1,
                inbound: pair.$2,
              ),
      );
      start = end + 1;
    }
    return sections;
  }

  /// Outbound and return chains for a wide stretch, or null when splitting it
  /// would not pay off or either lane cannot be drawn safely.
  (List<Offset>, List<Offset>)? _lanePair(List<Offset> run) {
    var length = 0.0;
    for (var index = 0; index < run.length - 1; index++) {
      length += (run[index + 1] - run[index]).distance;
    }
    // Too short to be worth splitting: the robots would spend the whole
    // stretch merging in and out again.
    if (length < lanePairOffsetPixels * 4) return null;
    final outbound = _offsetChain(run, 1);
    final inbound = _offsetChain(run, -1);
    if (outbound == null || inbound == null) return null;
    return (outbound, inbound.reversed.toList());
  }

  /// The centre line shifted by [side] * [lanePairOffsetPixels], rejoining the
  /// original junction points at both ends. Returns null if any part of the
  /// shifted chain would break the clearance.
  List<Offset>? _offsetChain(List<Offset> run, double side) {
    Offset? normalOf(int index) {
      final vector = run[index + 1] - run[index];
      final length = vector.distance;
      if (length <= .01) return null;
      return Offset(-vector.dy / length, vector.dx / length);
    }

    final offset = lanePairOffsetPixels * side;
    final chain = <Offset>[run.first];
    final firstNormal = normalOf(0);
    final lastNormal = normalOf(run.length - 2);
    if (firstNormal == null || lastNormal == null) return null;
    final entryTangent = (run[1] - run.first) / (run[1] - run.first).distance;
    final exitTangent =
        (run.last - run[run.length - 2]) /
        (run.last - run[run.length - 2]).distance;
    final entryGap = math.min(
      lanePairOffsetPixels,
      (run[1] - run.first).distance * .4,
    );
    final exitGap = math.min(
      lanePairOffsetPixels,
      (run.last - run[run.length - 2]).distance * .4,
    );
    chain.add(run.first + entryTangent * entryGap + firstNormal * offset);
    for (var index = 1; index < run.length - 1; index++) {
      final before = normalOf(index - 1);
      final after = normalOf(index);
      if (before == null || after == null) return null;
      final miter = before + after;
      final miterLength = miter.distance;
      if (miterLength <= .01) return null;
      final direction = miter / miterLength;
      final scale = (direction.dx * before.dx + direction.dy * before.dy);
      if (scale <= .1) return null;
      chain.add(
        run[index] +
            direction *
                (lanePairOffsetPixels / scale).clamp(
                  lanePairOffsetPixels,
                  lanePairOffsetPixels * 2,
                ) *
                side,
      );
    }
    chain.add(run.last - exitTangent * exitGap + lastNormal * offset);
    chain.add(run.last);
    final trimmed = <Offset>[chain.first];
    for (final point in chain.skip(1)) {
      if ((trimmed.last - point).distance > .01) trimmed.add(point);
    }
    if (trimmed.length < 2) return null;
    for (var index = 0; index < trimmed.length - 1; index++) {
      if (!segmentAllowed(trimmed[index], trimmed[index + 1])) return null;
    }
    return trimmed;
  }

  /// A clearance-respecting polyline from [from] to [to], or null when no such
  /// route exists. Both endpoints are kept exactly as given, so a lane can be
  /// attached to an existing waypoint.
  List<Offset>? planPath(Offset from, Offset to) {
    if ((from - to).distance <= .01) return null;
    if (segmentAllowed(from, to)) return [from, to];
    if (!hasFreeSpace) return null;
    final start = _snap(from);
    final goal = _snap(to);
    if (start == null || goal == null) return null;
    final cells = _search(start, goal);
    if (cells == null) return null;
    final raw = <Offset>[from];
    for (final (column, row) in cells) {
      final point = center(column, row);
      if ((raw.last - point).distance > .01) raw.add(point);
    }
    if ((raw.last - to).distance > .01) raw.add(to);
    final path = _shortcut(raw);
    for (var index = 0; index < path.length - 1; index++) {
      if (!segmentAllowed(path[index], path[index + 1])) return null;
    }
    return path.length < 2 ? null : path;
  }

  List<(int, int)>? _search((int, int) start, (int, int) goal) {
    final startIndex = _index(start.$1, start.$2);
    final goalIndex = _index(goal.$1, goal.$2);
    final cameFrom = <int, int>{};
    final costs = <int, double>{startIndex: 0};
    final queue = HeapPriorityQueue();
    queue.add(startIndex, 0);
    var found = startIndex == goalIndex;
    while (queue.isNotEmpty && !found) {
      final current = queue.removeFirst();
      if (current == goalIndex) {
        found = true;
        break;
      }
      final column = current % columns;
      final row = current ~/ columns;
      for (var dc = -1; dc <= 1; dc++) {
        for (var dr = -1; dr <= 1; dr++) {
          if (dc == 0 && dr == 0) continue;
          final nc = column + dc;
          final nr = row + dr;
          if (!isOpen(nc, nr)) continue;
          if (dc != 0 && dr != 0 && !(isOpen(nc, row) && isOpen(column, nr))) {
            continue;
          }
          final neighbor = _index(nc, nr);
          final cost = costs[current]! + (dc != 0 && dr != 0 ? 1.4142 : 1);
          if (costs.containsKey(neighbor) && costs[neighbor]! <= cost) continue;
          costs[neighbor] = cost;
          cameFrom[neighbor] = current;
          final heuristic = math.sqrt(
            math.pow(nc - goal.$1, 2) + math.pow(nr - goal.$2, 2),
          );
          queue.add(neighbor, cost + heuristic);
        }
      }
    }
    if (!found) return null;
    final path = <(int, int)>[];
    var cursor = goalIndex;
    while (true) {
      path.add((cursor % columns, cursor ~/ columns));
      if (cursor == startIndex) break;
      final previous = cameFrom[cursor];
      if (previous == null) return null;
      cursor = previous;
    }
    return path.reversed.toList();
  }

  /// Collapses the grid path into the fewest straight lanes that still keep
  /// the clearance, checked exactly rather than on the raster.
  List<Offset> _shortcut(List<Offset> points) {
    final result = <Offset>[points.first];
    var index = 0;
    while (index < points.length - 1) {
      var next = points.length - 1;
      while (next > index + 1 && !segmentAllowed(points[index], points[next])) {
        next--;
      }
      result.add(points[next]);
      index = next;
    }
    return result;
  }

  /// Lays out the draft corridors inside the widest connected free area.
  ///
  /// [waypointTarget] is the total number of route waypoints the scenario
  /// needs; it is split across both rows when the floor is wide enough for a
  /// separate outbound and return corridor.
  ScenarioRoutePlan? planRoutes({required int waypointTarget}) {
    if (!hasFreeSpace) return null;
    var minRow = rows;
    var maxRow = -1;
    for (var row = 0; row < rows; row++) {
      for (var column = 0; column < columns; column++) {
        if (!isOpen(column, row)) continue;
        minRow = math.min(minRow, row);
        maxRow = math.max(maxRow, row);
        break;
      }
    }
    if (maxRow < minRow) return null;
    final runs = <int, (int, int, int)>{};
    for (var row = minRow; row <= maxRow; row++) {
      final run = _longestRun(row);
      if (run != null) runs[row] = run;
    }
    if (runs.isEmpty) return null;
    final height = maxRow - minRow;
    final topLimit = (minRow + height * .45).floor();
    final bottomLimit = (maxRow - height * .45).ceil();
    final topBand = runs.keys.where((row) => row <= topLimit);
    final bottomBand = runs.keys.where((row) => row >= bottomLimit);
    final minRunCells = math.max(3, (clearancePixels / cell).ceil());
    final pickedTop = _pickRow(runs, topBand, preferFar: false);
    final pickedBottom = _pickRow(runs, bottomBand, preferFar: true);
    // Each corridor is centred inside its own half of the floor, so the two
    // stay far apart while both gain room for a second lane.
    final top = pickedTop == null
        ? null
        : _centeredRun(pickedTop, runs[pickedTop]!, minRow, topLimit);
    final bottom = pickedBottom == null
        ? null
        : _centeredRun(pickedBottom, runs[pickedBottom]!, bottomLimit, maxRow);
    final separated =
        top != null &&
        bottom != null &&
        top.$1 != bottom.$1 &&
        top.$2.$1 >= minRunCells &&
        bottom.$2.$1 >= minRunCells &&
        (bottom.$1 - top.$1) * cell >= clearancePixels * 2;
    if (separated) {
      final perRow = math.max(2, (waypointTarget / 2).ceil());
      return ScenarioRoutePlan(
        outbound: _rowPoints(top.$1, top.$2, perRow),
        returnRoute: _rowPoints(bottom.$1, bottom.$2, perRow).reversed.toList(),
        separateRoutes: true,
      );
    }
    final widest = runs.keys.reduce(
      (a, b) => runs[a]!.$1 >= runs[b]!.$1 ? a : b,
    );
    final centered = _centeredRun(widest, runs[widest]!, minRow, maxRow);
    final points = _rowPoints(
      centered.$1,
      centered.$2,
      math.max(2, waypointTarget),
    );
    if (points.length < 2) return null;
    return ScenarioRoutePlan(
      outbound: points,
      returnRoute: const [],
      separateRoutes: false,
    );
  }

  /// Slides [row] to the middle of the band of rows where the corridor still
  /// runs at nearly its full length, keeping it inside [minRow]..[maxRow].
  ///
  /// A row found by scanning is wherever the passage happened to be widest,
  /// usually right beside a wall. Centring it in its band is what leaves room
  /// for a second lane, and it keeps a single corridor off the walls too.
  (int, (int, int, int)) _centeredRun(
    int row,
    (int, int, int) run,
    int minRow,
    int maxRow,
  ) {
    final centerColumn = (run.$2 + run.$3) ~/ 2;
    final minLength = math.max(3, (run.$1 * .7).floor());
    (int, int, int)? runAt(int candidate) {
      if (candidate < minRow || candidate > maxRow) return null;
      if (!isOpen(centerColumn, candidate)) return null;
      var from = centerColumn;
      while (from - 1 >= 0 && isOpen(from - 1, candidate)) {
        from--;
      }
      var to = centerColumn;
      while (to + 1 < columns && isOpen(to + 1, candidate)) {
        to++;
      }
      final length = to - from + 1;
      return length >= minLength ? (length, from, to) : null;
    }

    var top = row;
    while (runAt(top - 1) != null) {
      top--;
    }
    var bottom = row;
    while (runAt(bottom + 1) != null) {
      bottom++;
    }
    final middle = (top + bottom) ~/ 2;
    return (middle, runAt(middle) ?? run);
  }

  /// Adds vertices so no lane of [chain] is longer than [spacing], keeping the
  /// original corners. Draft routes need waypoints along the way, and they must
  /// sit on the lane rather than on the corridor centre it was offset from.
  List<Offset> densify(List<Offset> chain, double spacing) {
    if (chain.length < 2 || spacing <= 0) return chain;
    final dense = <Offset>[chain.first];
    for (var index = 0; index < chain.length - 1; index++) {
      final start = chain[index];
      final end = chain[index + 1];
      final steps = math.max(1, ((end - start).distance / spacing).ceil());
      for (var step = 1; step <= steps; step++) {
        dense.add(start + (end - start) * (step / steps));
      }
    }
    return dense;
  }

  /// (length, firstColumn, lastColumn) of the longest open span on [row].
  (int, int, int)? _longestRun(int row) {
    (int, int, int)? best;
    var length = 0;
    var start = 0;
    for (var column = 0; column <= columns; column++) {
      if (column < columns && isOpen(column, row)) {
        if (length == 0) start = column;
        length++;
        if (best == null || length > best.$1) best = (length, start, column);
      } else {
        length = 0;
      }
    }
    return best;
  }

  /// The longest row in [band]; among rows within 70% of that length, the one
  /// furthest from the opposite corridor so the two rows cover more floor.
  int? _pickRow(
    Map<int, (int, int, int)> runs,
    Iterable<int> band, {
    required bool preferFar,
  }) {
    var longest = 0;
    for (final row in band) {
      longest = math.max(longest, runs[row]!.$1);
    }
    if (longest <= 0) return null;
    int? picked;
    for (final row in band) {
      if (runs[row]!.$1 < longest * .7) continue;
      if (picked == null || (preferFar ? row > picked : row < picked)) {
        picked = row;
      }
    }
    return picked;
  }

  List<Offset> _rowPoints(int row, (int, int, int) run, int target) {
    final left = center(run.$2, row).dx;
    final right = center(run.$3, row).dx;
    final y = center(0, row).dy;
    final spacing = math.max(clearancePixels, cell * 2);
    final capacity = ((right - left) / spacing).floor() + 1;
    final count = math.max(2, math.min(target, capacity));
    if (right - left <= .01) return [Offset(left, y)];
    return [
      for (var index = 0; index < count; index++)
        Offset(left + (right - left) * index / (count - 1), y),
    ];
  }
}

/// Minimal binary heap keyed by priority; the A* frontier is the only user.
class HeapPriorityQueue {
  final List<(int, double)> _items = [];

  bool get isNotEmpty => _items.isNotEmpty;

  void add(int value, double priority) {
    _items.add((value, priority));
    var child = _items.length - 1;
    while (child > 0) {
      final parent = (child - 1) ~/ 2;
      if (_items[parent].$2 <= _items[child].$2) break;
      final swap = _items[parent];
      _items[parent] = _items[child];
      _items[child] = swap;
      child = parent;
    }
  }

  int removeFirst() {
    final first = _items.first.$1;
    final last = _items.removeLast();
    if (_items.isNotEmpty) {
      _items[0] = last;
      var parent = 0;
      while (true) {
        final left = parent * 2 + 1;
        final right = left + 1;
        var smallest = parent;
        if (left < _items.length && _items[left].$2 < _items[smallest].$2) {
          smallest = left;
        }
        if (right < _items.length && _items[right].$2 < _items[smallest].$2) {
          smallest = right;
        }
        if (smallest == parent) break;
        final swap = _items[parent];
        _items[parent] = _items[smallest];
        _items[smallest] = swap;
        parent = smallest;
      }
    }
    return first;
  }
}
