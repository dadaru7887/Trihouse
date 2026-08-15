/// 설비 로봇과 그 로봇이 맡을 Waypoint 를 짝지운다.
///
/// RMF 는 픽업·드랍오프 Waypoint 에 **워크셀 이름**을 적어 둔다. nav graph 를
/// 보면 이렇게 생겼다.
///
///     픽업2    {'pickup_dispenser': '픽업2'}
///     드랍오프2 {'dropoff_ingestor': '드랍오프2'}
///
/// 로봇이 그 자리에 닿으면 RMF 가 `/dispenser_requests` 에
/// `target_guid: 픽업2` 를 낸다. **그 이름으로 답하는 노드가 있어야** 다음
/// 단계로 넘어간다. 없으면 RMF 는 영원히 기다린다 — 오류는 안 난다.
///
/// 그런데 등록에는 그 짝이 없다. 설비 로봇에는 `station: 설비2` 만 적혀 있고,
/// 그것은 nav graph 에 없는 이름이다. 그래서 **자리로 짝을 짓는다** — 설비를
/// 그 Waypoint 옆에 세워 두는 것이 애초에 그 일을 시키려는 뜻이기 때문이다.
library;

import 'dart:math' as math;

import 'rmf_project_config.dart';

/// 설비가 이 거리 안에 있어야 그 자리를 맡는다고 본다 [m].
///
/// 팔이 닿는 거리다. OpenMANIPULATOR-X 의 작업 반경이 0.38m 쯤이고, 로봇이
/// Waypoint 한가운데 정확히 서지도 않으므로 여유를 얹었다.
///
/// 넉넉히 잡으면 안 된다. 엉뚱한 설비가 남의 자리를 맡겠다고 나서면, 오지도
/// 않을 팔을 RMF 가 기다린다.
const double workcellReachMeters = .8;

/// Gazebo 설비에 자동으로 붙이는 기본 물품 정책.
///
/// 생성되는 workcell 노드의 `POLICY_MOTIONS`와 같은 이름이어야 한다. 사용자가
/// 설비를 Gazebo 방식으로 등록하면 별도 설정 없이 이 정책들이 작업 편집기에
/// 나타난다.
const List<String> gazeboWorkcellPolicies = [
  'policy_1',
  'policy_2',
  'policy_3',
  'policy_4',
  'policy_5',
];

/// 등록된 설비로부터 픽업 단계에서 고를 수 있는 policy를 만든다.
///
/// Mock 설비는 앱이 직접 armLoad를 흉내 내므로 policy가 필요 없다. 실제 설비도
/// 아직 등록된 policy가 없다면 일반 armLoad를 쓸 수 있어야 한다. Gazebo 설비가
/// 하나라도 있으면 생성되는 workcell 노드가 제공하는 기본 policy를 노출한다.
List<String> workcellPoliciesFor(List<RmfProjectRobot> robots) {
  final hasGazeboWorkcell = robots.any(
    (robot) => !robot.isMobile && robot.dataSource == RobotDataSource.gazebo,
  );
  return hasGazeboWorkcell ? gazeboWorkcellPolicies : const <String>[];
}

/// 짝지어진 설비 하나.
class WorkcellPairing {
  const WorkcellPairing({
    required this.robot,
    required this.dispensers,
    required this.ingestors,
  });

  final RmfProjectRobot robot;

  /// 이 설비가 맡는 픽업 자리 이름. RMF 의 `target_guid` 가 이것이다.
  final List<String> dispensers;

  /// 맡는 드랍오프 자리 이름.
  final List<String> ingestors;

  bool get isEmpty => dispensers.isEmpty && ingestors.isEmpty;
}

/// 짝짓기 결과 전체.
class WorkcellPairingResult {
  const WorkcellPairingResult({
    required this.pairings,
    required this.unservedWaypoints,
    required this.idleWorkcells,
  });

  final List<WorkcellPairing> pairings;

  /// 맡을 설비가 없는 픽업·드랍오프 자리.
  ///
  /// **조용히 넘기면 안 된다.** 그 자리로 보내는 작업은 RMF 가 영원히 기다린다.
  final List<String> unservedWaypoints;

  /// 맡은 자리가 없는 설비 로봇.
  final List<String> idleWorkcells;
}

/// 자리 하나. 이름과 월드 좌표, 그리고 어느 종류인지.
class WorkcellStation {
  const WorkcellStation({
    required this.name,
    required this.x,
    required this.y,
    required this.isDispenser,
  });

  final String name;
  final double x;
  final double y;

  /// 픽업(dispenser)이면 true, 드랍오프(ingestor)면 false.
  final bool isDispenser;
}

/// 설비 로봇과 자리를 자리로 짝지운다.
///
/// 자리마다 **가장 가까운 설비 하나**를 고른다. 반대로 하지 않는 이유는, 설비
/// 하나가 픽업과 드랍오프를 함께 맡는 일은 있어도 한 자리를 둘이 맡는 일은
/// 없기 때문이다.
WorkcellPairingResult pairWorkcells({
  required List<RmfProjectRobot> robots,
  required List<WorkcellStation> stations,
  double reachMeters = workcellReachMeters,
}) {
  final workcells = robots
      .where((robot) => !robot.isMobile && robot.isManagedByRmf)
      .where((robot) => robot.spawnX != null && robot.spawnY != null)
      .toList(growable: false);

  final dispensers = <String, List<String>>{};
  final ingestors = <String, List<String>>{};
  final unserved = <String>[];

  for (final station in stations) {
    RmfProjectRobot? nearest;
    var best = double.infinity;
    for (final robot in workcells) {
      final distance = math.sqrt(
        math.pow(robot.spawnX! - station.x, 2) +
            math.pow(robot.spawnY! - station.y, 2),
      );
      if (distance < best) {
        best = distance;
        nearest = robot;
      }
    }
    if (nearest == null || best > reachMeters) {
      unserved.add(station.name);
      continue;
    }
    final bucket = station.isDispenser ? dispensers : ingestors;
    (bucket[nearest.robotId] ??= <String>[]).add(station.name);
  }

  final pairings = <WorkcellPairing>[];
  final idle = <String>[];
  for (final robot in workcells) {
    final pairing = WorkcellPairing(
      robot: robot,
      dispensers: dispensers[robot.robotId] ?? const [],
      ingestors: ingestors[robot.robotId] ?? const [],
    );
    if (pairing.isEmpty) {
      idle.add(robot.robotId);
      continue;
    }
    pairings.add(pairing);
  }
  unserved.sort();
  idle.sort();
  return WorkcellPairingResult(
    pairings: pairings,
    unservedWaypoints: unserved,
    idleWorkcells: idle,
  );
}
