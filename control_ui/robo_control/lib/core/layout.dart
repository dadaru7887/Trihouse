import 'dart:collection';
import 'dart:math' as math;
import 'dart:ui' show Offset, Rect;

import 'package:robo_core/models/enums.dart';
import 'package:robo_core/models/warehouse.dart';

/// 물류센터 평면도와 통로 그래프.
///
/// 좌표계는 논리 단위(1 unit ≈ 0.5 m), 폭 120 × 높이 72.
/// 로봇은 임의의 직선이 아니라 통로 그래프 위를 따라 이동한다.
class WarehouseLayout {
  WarehouseLayout._({
    required this.locations,
    required this.stations,
    required this.nodes,
    required this.adjacency,
    required this.rackBars,
  });

  static const double width = 120;
  static const double height = 72;

  /// 수평 통로 y 좌표.
  static const List<double> corridorY = <double>[6, 22, 38, 54, 68];

  /// 수직 통로 x 좌표.
  static const List<double> corridorX = <double>[5, 20, 35, 50, 65, 80, 95, 110];

  /// 랙 열 중심 y 좌표.
  static const List<double> rackRowY = <double>[13, 30, 46, 61];

  final List<StorageLocation> locations;
  final List<Station> stations;
  final List<Offset> nodes;
  final List<List<int>> adjacency;

  /// 지도에 그릴 랙 블록.
  final List<Rect> rackBars;

  late final Map<String, StorageLocation> locationById = <String, StorageLocation>{
    for (final l in locations) l.id: l,
  };

  late final Map<String, Station> stationById = <String, Station>{
    for (final s in stations) s.id: s,
  };

  static TempZone zoneOfX(double x) {
    if (x < 50) return TempZone.ambient;
    if (x < 88) return TempZone.chilled;
    return TempZone.frozen;
  }

  TempZone zoneAt(Offset p) => zoneOfX(p.dx);

  static WarehouseLayout build() {
    final locations = <StorageLocation>[];
    final rackBars = <Rect>[];

    for (var r = 0; r < rackRowY.length; r++) {
      final y = rackRowY[r];
      rackBars.add(Rect.fromLTWH(8, y - 2.6, 108, 5.2));
      for (var c = 0; c < 20; c++) {
        final x = 9.5 + c * 5.6;
        final zone = zoneOfX(x);
        final id = '${zone.code}-${(r + 1).toString().padLeft(2, '0')}'
            '-${(c + 1).toString().padLeft(2, '0')}';
        locations.add(
          StorageLocation(id: id, pos: Offset(x, y), zone: zone, row: r),
        );
      }
    }

    final stations = <Station>[
      Station(
        id: 'IN-1',
        kind: StationKind.inboundDock,
        pos: const Offset(5, 6),
        zone: TempZone.ambient,
      ),
      Station(
        id: 'IN-2',
        kind: StationKind.inboundDock,
        pos: const Offset(5, 22),
        zone: TempZone.ambient,
      ),
      Station(
        id: 'OUT-1',
        kind: StationKind.outboundDock,
        pos: const Offset(5, 54),
        zone: TempZone.ambient,
      ),
      Station(
        id: 'OUT-2',
        kind: StationKind.outboundDock,
        pos: const Offset(5, 68),
        zone: TempZone.ambient,
      ),
      Station(
        id: 'CHG-1',
        kind: StationKind.charger,
        pos: const Offset(20, 68),
        zone: TempZone.ambient,
      ),
      Station(
        id: 'CHG-2',
        kind: StationKind.charger,
        pos: const Offset(35, 68),
        zone: TempZone.ambient,
      ),
      Station(
        id: 'CHG-3',
        kind: StationKind.charger,
        pos: const Offset(65, 68),
        zone: TempZone.chilled,
      ),
      Station(
        id: 'CHG-4',
        kind: StationKind.charger,
        pos: const Offset(95, 68),
        zone: TempZone.frozen,
      ),
      Station(
        id: 'WS-1',
        kind: StationKind.workstation,
        pos: const Offset(35, 38),
        zone: TempZone.ambient,
      ),
      Station(
        id: 'WS-2',
        kind: StationKind.workstation,
        pos: const Offset(65, 38),
        zone: TempZone.chilled,
      ),
      Station(
        id: 'WS-3',
        kind: StationKind.workstation,
        pos: const Offset(95, 38),
        zone: TempZone.frozen,
      ),
      // 적재 스테이션 — 구획마다 하나. 로봇팔이 여기서 로봇에 화물을 싣는다.
      //
      // 좌표는 아무 데나 잡을 수 없다. 팔 받침대는 실물 장애물이므로
      // **세로 통로에서도, 랙 열 진입선(랙 로케이션의 x)에서도 떨어진**
      // 빈 자리여야 한다. 아래 x는 이웃한 랙 열 두 개의 정중앙이면서
      // 세로 통로에서 3 unit 이상 떨어진 지점이다.
      Station(
        id: 'LOAD-A',
        kind: StationKind.loading,
        pos: const Offset(40.3, 38),
        zone: TempZone.ambient,
      ),
      Station(
        id: 'LOAD-C',
        kind: StationKind.loading,
        pos: const Offset(68.3, 38),
        zone: TempZone.chilled,
      ),
      Station(
        id: 'LOAD-F',
        kind: StationKind.loading,
        pos: const Offset(101.9, 38),
        zone: TempZone.frozen,
      ),
      Station(
        id: 'STB-1',
        kind: StationKind.standby,
        pos: const Offset(50, 22),
        zone: TempZone.ambient,
      ),
      Station(
        id: 'STB-2',
        kind: StationKind.standby,
        pos: const Offset(80, 54),
        zone: TempZone.chilled,
      ),
      Station(
        id: 'ASM-1',
        kind: StationKind.assembly,
        pos: const Offset(5, 38),
        zone: TempZone.ambient,
      ),
    ];

    // 통로 교차점 그래프.
    final nodes = <Offset>[];
    final index = <String, int>{};
    for (final y in corridorY) {
      for (final x in corridorX) {
        index['$x:$y'] = nodes.length;
        nodes.add(Offset(x, y));
      }
    }
    final adjacency = List<List<int>>.generate(nodes.length, (_) => <int>[]);
    void link(int a, int b) {
      adjacency[a].add(b);
      adjacency[b].add(a);
    }

    for (var yi = 0; yi < corridorY.length; yi++) {
      for (var xi = 0; xi < corridorX.length; xi++) {
        final me = index['${corridorX[xi]}:${corridorY[yi]}']!;
        if (xi + 1 < corridorX.length) {
          link(me, index['${corridorX[xi + 1]}:${corridorY[yi]}']!);
        }
        if (yi + 1 < corridorY.length) {
          link(me, index['${corridorX[xi]}:${corridorY[yi + 1]}']!);
        }
      }
    }

    return WarehouseLayout._(
      locations: locations,
      stations: stations,
      nodes: nodes,
      adjacency: adjacency,
      rackBars: rackBars,
    );
  }

  int nearestNode(Offset p) {
    var best = 0;
    var bestD = double.infinity;
    for (var i = 0; i < nodes.length; i++) {
      final d = (nodes[i] - p).distanceSquared;
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    }
    return best;
  }

  /// 통로 그래프를 이용한 최단 경로. 시작·종료 지점은 가장 가까운
  /// 교차점에 스냅해 접속한다.
  List<Offset> route(Offset from, Offset to) {
    if ((from - to).distance < 1.0) return <Offset>[to];
    final a = nearestNode(from);
    final b = nearestNode(to);
    final path = <Offset>[];
    if (a == b) {
      path.add(nodes[a]);
    } else {
      final dist = List<double>.filled(nodes.length, double.infinity);
      final prev = List<int>.filled(nodes.length, -1);
      dist[a] = 0;
      final queue = SplayTreeSet<int>((p, q) {
        final c = dist[p].compareTo(dist[q]);
        return c != 0 ? c : p.compareTo(q);
      });
      queue.add(a);
      while (queue.isNotEmpty) {
        final u = queue.first;
        queue.remove(u);
        if (u == b) break;
        for (final v in adjacency[u]) {
          final nd = dist[u] + (nodes[u] - nodes[v]).distance;
          if (nd < dist[v] - 1e-9) {
            queue.remove(v);
            dist[v] = nd;
            prev[v] = u;
            queue.add(v);
          }
        }
      }
      var cur = b;
      final rev = <Offset>[];
      while (cur != -1) {
        rev.add(nodes[cur]);
        if (cur == a) break;
        cur = prev[cur];
      }
      path.addAll(rev.reversed);
    }
    path.add(to);
    return path;
  }

  /// 경로 길이(스케줄러의 동선 비용 계산에 사용).
  double routeLength(Offset from, Offset to) {
    final path = route(from, to);
    var total = 0.0;
    var cur = from;
    for (final p in path) {
      total += (p - cur).distance;
      cur = p;
    }
    return total;
  }

  Station nearest(StationKind kind, Offset from, {bool freeOnly = false}) {
    final candidates = stations.where(
      (s) => s.kind == kind && (!freeOnly || s.occupiedBy == null),
    );
    final pool = candidates.isEmpty
        ? stations.where((s) => s.kind == kind)
        : candidates;
    return pool.reduce(
      (a, b) => (a.pos - from).distance <= (b.pos - from).distance ? a : b,
    );
  }

  List<StorageLocation> locationsIn(TempZone zone) =>
      locations.where((l) => l.zone == zone).toList();

  /// 구획별 적재 스테이션(로봇팔이 설치된 자리).
  ///
  /// 로봇은 랙에서 집품한 화물을 이 자리에서 팔에게 실어 받은 뒤 도크로 간다.
  /// 구획마다 정확히 하나씩 있다.
  Station loadingStation(TempZone zone) => stations.firstWhere(
    (s) => s.kind == StationKind.loading && s.zone == zone,
    orElse: () => stationById['LOAD-A']!,
  );

  static double manhattanish(Offset a, Offset b) =>
      (a.dx - b.dx).abs() + (a.dy - b.dy).abs();

  static double clampX(double x) => x.clamp(1.0, width - 1);

  static double clampY(double y) => y.clamp(1.0, height - 1);

  static Offset lerp(Offset a, Offset b, double t) =>
      Offset(a.dx + (b.dx - a.dx) * t, a.dy + (b.dy - a.dy) * t);

  static double headingOf(Offset from, Offset to) =>
      math.atan2(to.dy - from.dy, to.dx - from.dx);
}
