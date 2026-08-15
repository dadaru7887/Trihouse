/// 이미 떠 있는 Open-RMF 백엔드의 상태.
library;

/// `ros2 node list` 로 확인한 RMF 노드 현황.
class RmfRuntimeStatus {
  const RmfRuntimeStatus({
    required this.available,
    required this.nodes,
    required this.message,
  });

  /// ROS 환경을 찾아 조회에 성공했는지. false 면 [nodes] 는 비어 있고
  /// [message] 가 이유를 담는다 — 노드가 없는 것과 확인하지 못한 것은 다르다.
  final bool available;

  /// 떠 있는 RMF 관련 노드 이름.
  final List<String> nodes;

  /// 사용자에게 보여 줄 설명. 조회 실패 사유 또는 요약.
  final String message;

  bool get isRunning => nodes.isNotEmpty;

  static const RmfRuntimeStatus unknown = RmfRuntimeStatus(
    available: false,
    nodes: [],
    message: '아직 확인하지 않았습니다.',
  );
}

/// 백엔드 중지 스크립트 실행 결과.
class RmfStopResult {
  const RmfStopResult({required this.success, required this.output});
  final bool success;
  final String output;
}

/// `/fleet_states` 를 한 번 읽은 결과.
class RmfFleetSnapshot {
  const RmfFleetSnapshot({
    required this.reachable,
    required this.robots,
    this.message,
  });

  /// 토픽을 읽었는가.
  ///
  /// false 는 **모른다**는 뜻이다. 로봇이 없다는 뜻이 아니다. 둘을 뭉뚱그리면
  /// 확인 못 한 것이 고장으로 읽힌다.
  final bool reachable;

  /// 플릿에 붙은 로봇 이름.
  final Set<String> robots;

  /// 못 읽었을 때 그 까닭.
  final String? message;
}

/// `ros2 topic echo /fleet_states --once` 의 출력에서 로봇 이름만 뽑는다.
///
/// FleetState 는 이렇게 생겼다 —
///
///     name: project1_pinky      ← 플릿 이름. 로봇이 아니다
///     robots:
///     - name: PK_01             ← 이것만 센다
///       model: project1_pinky
///       location:
///         level_name: L1
///
/// `robots:` 아래의 목록 항목만 본다. 그 위의 플릿 이름과 항목 **안쪽**의 다른
/// `name` 은 세지 않는다 — 안 그러면 없는 로봇이 붙은 것으로 보인다.
///
/// `--field robots` 로 부르지 않는 이유는 [probeFleetStates] 에 적어 두었다.
/// 그렇게 부르면 YAML 이 아니라 파이썬 repr 이 나와 이 규칙이 하나도 안 맞는다.
///
/// YAML 파서를 들이지 않는다. 필요한 것이 한 줄이고, 이 출력은 우리가 부른
/// 명령의 것이라 모양이 정해져 있다.
Set<String> parseFleetStateRobots(String stdout) {
  final names = <String>{};
  final entry = RegExp(r'^-\s*name:\s*(.+)$');
  var inRobots = false;
  for (final raw in stdout.split('\n')) {
    final line = raw.trimRight();
    // `robots:` 부터가 목록이다. 그 뒤에 들여쓰기 없는 다른 키가 나오면 끝난다.
    if (RegExp(r'^robots:').hasMatch(line)) {
      inRobots = true;
      continue;
    }
    if (line.isNotEmpty &&
        !line.startsWith(' ') &&
        !line.startsWith('-') &&
        !line.startsWith('---')) {
      inRobots = false;
      continue;
    }
    if (!inRobots) continue;
    final match = entry.firstMatch(line);
    if (match == null) continue;
    final name = match
        .group(1)!
        .trim()
        .replaceAll(RegExp('^[\'"]|[\'"]\$'), '');
    if (name.isNotEmpty) names.add(name);
  }
  return names;
}

/// `/fleet_states` 한 덩어리에서 로봇별 **map 좌표**를 뽑는다.
///
/// 앱은 지금까지 `/<로봇>/odom` 을 읽어 spawn 을 더해 월드 좌표를 만들었다.
/// 그것은 AMCL 이 보정하지 않을 때만 맞다. 로봇이 미끄러지거나 복구 회전을
/// 돌면 `map→odom` 이 틀어지는데 앱은 그것을 모른다 — 실제로 46도가 틀어져
/// 앱 화면과 RViz 의 로봇 위치가 1m 넘게 어긋났다.
///
/// 이 토픽은 RMF 가 내는 map 좌표라 RViz 가 그리는 것과 같은 값이다.
///
/// `location:` 블록 안의 x·y·yaw 만 본다. `path:` 에도 같은 이름이 들어 있어서
/// 그냥 세면 로봇이 아니라 **가려는 곳**의 좌표를 위치로 그리게 된다.
Map<String, ({double x, double y, double yaw})> parseFleetStatePoses(
  String block,
) {
  final poses = <String, ({double x, double y, double yaw})>{};
  final entry = RegExp(r'^(\s*)-\s*name:\s*(.+)$');
  final field = RegExp(r'^(\s*)([a-z_]+):\s*(.*)$');

  String? robot;
  var itemIndent = 0;
  var inLocation = false;
  var locationIndent = 0;
  double? x;
  double? y;
  double? yaw;

  void flush() {
    final name = robot;
    final px = x;
    final py = y;
    if (name != null && px != null && py != null) {
      poses[name] = (x: px, y: py, yaw: yaw ?? 0);
    }
    x = null;
    y = null;
    yaw = null;
  }

  var inRobots = false;
  for (final raw in block.split('\n')) {
    final line = raw.trimRight();
    if (line.isEmpty || line.startsWith('---')) continue;
    if (RegExp(r'^robots:').hasMatch(line)) {
      inRobots = true;
      continue;
    }
    if (!inRobots) continue;

    final item = entry.firstMatch(line);
    if (item != null) {
      // 목록 항목의 시작. 로봇 항목인지 path 안쪽인지는 들여쓰기로 가린다.
      if (robot == null || item.group(1)!.length <= itemIndent) {
        flush();
        robot = item.group(2)!.trim().replaceAll(RegExp('^[\'"]|[\'"]\$'), '');
        itemIndent = item.group(1)!.length;
        inLocation = false;
      }
      continue;
    }
    if (robot == null) continue;

    final match = field.firstMatch(line);
    if (match == null) continue;
    final indent = match.group(1)!.length;
    final key = match.group(2)!;

    if (key == 'location') {
      inLocation = true;
      locationIndent = indent;
      continue;
    }
    // location 블록은 더 깊은 들여쓰기까지다. 같거나 얕은 키가 나오면 끝난다.
    if (inLocation && indent <= locationIndent) inLocation = false;
    if (!inLocation) continue;
    // t: 아래의 sec·nanosec 은 한 칸 더 깊다. x·y·yaw 는 location 바로 아래다.
    if (indent != locationIndent + 2) continue;
    final value = double.tryParse(match.group(3)!.trim());
    if (value == null) continue;
    switch (key) {
      case 'x':
        x = value;
      case 'y':
        y = value;
      case 'yaw':
        yaw = value;
    }
  }
  flush();
  return poses;
}
