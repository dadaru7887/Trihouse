/// 로봇 하나를 Waypoint 하나로 바로 보낸다.
///
/// 작업 목록을 거치지 않는다. 작업은 단계를 엮고 저장하고 진행을 좇는 물건인데,
/// "저 로봇 저기로" 하나 시키자고 그것을 다 만드는 것은 과하다. 자리 확인,
/// 충전대 복귀, 막힌 Lane 시험 같은 일은 대부분 이 한 번이 전부다.
///
/// RMF 에게는 `robot_task_request` 로 간다. 입찰(`dispatch_task_request`)이
/// 아니다 — 사람이 로봇을 이미 골랐는데 RMF 가 다른 로봇을 뽑으면 시킨 것과
/// 다른 일이 벌어진다.
///
/// 다만 **경로는 여전히 RMF 가 만든다.** Nav2 에 좌표를 바로 던지지 않는다.
/// 그러면 traffic schedule 밖에서 움직이는 로봇이 생겨, 다른 로봇이 그 자리를
/// 비어 있다고 여기고 들어온다.
library;

import 'rmf_project_config.dart';
import 'rmf_task_request.dart';

/// 이 명령에 붙일 이름. RMF 는 분류에만 쓰고, 화면에는 그대로 보인다.
const String robotMoveCategory = '이동 지시';

/// 지도에서 고를 수 있는 Waypoint 이름을 추린다.
///
/// 이름 없는 Waypoint 는 뺀다. RMF 는 좌표가 아니라 **이름**으로 자리를 찾으므로
/// 이름이 없으면 보낼 수단이 없다.
///
/// 가나다순으로 준다. 지도에 놓인 순서는 사람에게 아무 뜻이 없어서, 목록이 길어
/// 지면 찾던 것이 어디 있는지 모른다.
List<String> movableWaypointNames(Map<Object, String> waypointNames) {
  final names = <String>{
    for (final name in waypointNames.values)
      if (name.trim().isNotEmpty) name.trim(),
  }.toList();
  names.sort();
  return names;
}

/// 보낼 수 없는 까닭. 보낼 수 있으면 null.
///
/// 보내기 전에 막는다. 그냥 보내면 RMF 가 조용히 무시하거나
/// `Failed to find a robot` 같은 말로 거절하는데, 그 말만 보고는 무엇을 고쳐야
/// 하는지 알 수 없다.
String? robotMoveBlocker({
  required RmfProjectRobot? robot,
  required bool backendRunning,
  required List<String> waypoints,
  String? mapName,
}) {
  if (robot == null) {
    return '이 로봇은 프로젝트에 등록되어 있지 않습니다.\n'
        'RMF 는 등록된 로봇만 압니다 — 로봇 화면에서 먼저 등록하세요.';
  }
  if (!robot.isMobile) {
    return '${robot.displayName} 은(는) 설비 로봇입니다. 자리를 옮길 수 없습니다.';
  }
  if (mapName == null || mapName.trim().isEmpty) {
    return '어느 맵인지 모릅니다. 로봇 화면에서 배포 맵 불러오기를 먼저 하세요.';
  }
  if (waypoints.isEmpty) {
    return '보낼 Waypoint 가 없습니다.\n'
        '이름이 붙은 Waypoint 가 있어야 합니다 — RMF 는 좌표가 아니라 이름으로 '
        '자리를 찾습니다.';
  }
  if (!backendRunning) {
    return 'Open-RMF 가 떠 있지 않습니다.\n'
        '지시를 받을 쪽이 없어서 보내도 아무 일도 일어나지 않습니다. '
        '프로젝트를 먼저 실행하세요.';
  }
  return null;
}

/// 로봇 하나를 Waypoint 하나로 보내는 요청을 만든다.
///
/// 동작은 `go_to_place` 하나뿐이다. 도착하면 그것으로 끝이고, RMF 는 그 로봇을
/// 다시 대기 상태로 돌린다.
RmfTaskRequest buildRobotMoveRequest({
  required String fleetName,
  required String robotId,
  required String waypoint,
}) {
  final place = waypoint.trim();
  if (place.isEmpty) {
    throw ArgumentError('목적지 Waypoint 이름이 비어 있습니다.');
  }
  final id = robotId.trim();
  if (id.isEmpty) {
    // 비우면 buildRmfTaskRequest 가 입찰 요청을 만든다. 사람이 로봇을 골랐는데
    // RMF 가 다른 로봇을 뽑는 일은 없어야 한다.
    throw ArgumentError('로봇을 지정해야 합니다. 이 명령은 입찰이 아닙니다.');
  }
  return buildRmfTaskRequest(
    fleetName: fleetName,
    robotId: id,
    activities: [RmfTaskActivity.goToPlace(place)],
    category: robotMoveCategory,
  );
}
