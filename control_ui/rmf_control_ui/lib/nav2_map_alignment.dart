/// 위치추정 지도와 주행 그래프가 같은 자리에 있는지 본다 — **지도 정합**.
///
/// 로봇이 길을 찾는 데는 두 가지가 함께 쓰인다.
///
///   위치추정 지도 (`nav2_map/*.yaml`)  — AMCL 이 라이다 스캔을 맞출 점유격자
///   주행 그래프  (`nav_graphs/0.yaml`) — RMF 가 길을 고를 Waypoint 와 Lane
///
/// 둘이 **같은 월드 좌표**에 있어야 한다. 어긋나면 RMF 는 `픽업1` 로 보내는데
/// AMCL 은 로봇이 딴 데 있다고 여긴다. 오류는 안 난다 — 로봇이 엉뚱한 데로
/// 갈 뿐이다.
///
/// 도면에서 구운 격자는 그래프와 같은 도면에서 나오므로 어긋날 수가 없다.
/// 문제는 **SLAM 지도**다. 그 원점은 사람이 손으로 맞추는 값이라 틀리기 쉽다.
///
/// 실제로 이렇게 어긋나 있었다 —
///
///   주행 그래프 :  x +0.405 … +1.924   y -1.964 … -0.282
///   SLAM 지도  :  x -0.214 … +1.936   y **-1.523 … +1.127**
///
/// 지도는 건물이 없는 위쪽을 덮고, 건물 아래쪽 0.44m 는 지도 밖이었다. AMCL 이
/// 자리를 못 잡아 `map→odom` 이 46도까지 틀어졌다.
library;

/// 점유격자가 덮는 월드 범위 [m].
class MapExtentMeters {
  const MapExtentMeters({
    required this.minX,
    required this.maxX,
    required this.minY,
    required this.maxY,
  });

  /// `map_server` 가 읽는 값에서 만든다.
  ///
  /// 원점은 격자의 **왼쪽 아래** 모서리다. 위가 아니다 — 여기를 뒤집으면 y 가
  /// 통째로 반대편으로 간다.
  factory MapExtentMeters.fromOrigin({
    required double originX,
    required double originY,
    required double resolution,
    required int widthCells,
    required int heightCells,
  }) => MapExtentMeters(
    minX: originX,
    maxX: originX + widthCells * resolution,
    minY: originY,
    maxY: originY + heightCells * resolution,
  );

  final double minX;
  final double maxX;
  final double minY;
  final double maxY;

  bool contains(double x, double y) =>
      x >= minX && x <= maxX && y >= minY && y <= maxY;
}

/// 정합 결과.
class Nav2MapAlignment {
  const Nav2MapAlignment({
    required this.covered,
    required this.outsideWaypoints,
    required this.marginMeters,
  });

  /// 그래프의 모든 Waypoint 가 지도 안에 있는가.
  final bool covered;

  /// 지도 밖으로 나간 Waypoint 이름.
  final List<String> outsideWaypoints;

  /// 지도 가장자리까지 남은 여유 중 가장 좁은 것 [m].
  ///
  /// 음수면 그만큼 밖으로 나갔다는 뜻이다. 양수라도 너무 얇으면 로봇이 그
  /// Waypoint 근처에서 지도 밖을 보게 되어 위치추정이 흔들린다.
  final double marginMeters;

  bool get isAligned => covered && marginMeters >= minAlignmentMargin;
}

/// Waypoint 가 지도 가장자리에서 이만큼은 떨어져 있어야 한다 [m].
///
/// 로봇은 Waypoint 위에 점으로 서지 않는다. 몸통과 라이다 시야가 있어서, 자리
/// 자체는 지도 안이어도 가장자리에 바짝 붙으면 스캔의 절반이 미지 영역을 향한다.
const double minAlignmentMargin = .3;

/// 주행 그래프가 위치추정 지도 안에 들어 있는지 본다.
///
/// [waypoints] 는 이름과 월드 좌표다. 그래프 쪽을 기준으로 삼는 이유는, 로봇이
/// 실제로 가야 하는 자리가 그것이기 때문이다. 지도가 아무리 넓어도 갈 곳이
/// 밖이면 소용없다.
Nav2MapAlignment checkNav2MapAlignment({
  required MapExtentMeters map,
  required Map<String, ({double x, double y})> waypoints,
}) {
  if (waypoints.isEmpty) {
    // 견줄 것이 없다. 어긋났다고 말할 근거도 없다.
    return const Nav2MapAlignment(
      covered: true,
      outsideWaypoints: [],
      marginMeters: double.infinity,
    );
  }
  final outside = <String>[];
  var worst = double.infinity;
  for (final entry in waypoints.entries) {
    final x = entry.value.x;
    final y = entry.value.y;
    if (!map.contains(x, y)) outside.add(entry.key);
    // 네 변까지의 거리 중 가장 가까운 것. 밖이면 음수가 된다.
    final margin = [
      x - map.minX,
      map.maxX - x,
      y - map.minY,
      map.maxY - y,
    ].reduce((a, b) => a < b ? a : b);
    if (margin < worst) worst = margin;
  }
  outside.sort();
  return Nav2MapAlignment(
    covered: outside.isEmpty,
    outsideWaypoints: outside,
    marginMeters: worst,
  );
}
