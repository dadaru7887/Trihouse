/// 로봇을 등록할 때 자리 Waypoint 를 반드시 고르게 하는 규칙.
///
/// 자리를 안 고르면 spawn 좌표가 없고, 좌표 없는 로봇은 지도 원점(0,0)에
/// 놓인다. project1 에서 이동 로봇과 설치 로봇이 둘 다 원점에 놓이자, 메시
/// 충돌 도형끼리 파고들어 Gazebo 가 스폰 4초 만에 죽었다:
///
///   ODE INTERNAL ERROR 1: assertion ... failed in UpdateArbitraryContactInNode()
///     [collision_trimesh_trimesh.cpp:285]
///   [ERROR] [gazebo-1]: process has died ... exit code 134
///
/// 그 맵에는 `충전1` 도 `설비1` 도 있었다. 고를 자리가 없어서가 아니라 고르지
/// 않아서 생긴 일이다. 그래서 고를 수 있을 때는 반드시 고르게 한다.
///
/// 판정을 화면에서 떼어 둔 것은 [RobotLink] 와 같은 이유다 — 규칙은 눌러 보지
/// 않고도 확인할 수 있어야 한다.
library;

import 'rmf_project_config.dart';

/// 자리를 안 고른 로봇을 어떻게 다룰지.
enum StationRequirement {
  /// 자리가 필요 없다. Mock 로봇은 Gazebo 에도 RMF 플릿에도 들어가지 않는다.
  notNeeded,

  /// 골랐다.
  satisfied,

  /// 골라야 하는데 안 골랐다. 고를 자리가 있으므로 저장을 막는다.
  missing,

  /// 골라야 하는데 고를 자리가 하나도 없다.
  ///
  /// 맵을 아직 안 불러왔거나, 맵에 그 카테고리 Waypoint 가 없다. 여기서 막으면
  /// 맵을 그리기 전에는 로봇을 한 대도 등록할 수 없다. 대신 무엇이 빠졌는지
  /// 알리고 저장은 시킨다 — 자리 이름만 나중에 채우면 좌표는 맵을 열 때 따라
  /// 붙는다.
  unavailable,
}

/// 이 등록에 자리가 필요한지, 필요하다면 채워졌는지 본다.
///
/// [usesTopics] 는 이 로봇의 값이 토픽에서 오는가다. Gazebo·실물이면 참이고
/// 앱 Mock 이면 거짓이다.
/// [station] 은 지금 고른 자리 이름, [stationsAvailable] 은 고를 자리가 하나라도
/// 있는가다.
StationRequirement checkStationRequirement({
  required bool usesTopics,
  required String? station,
  required bool stationsAvailable,
}) {
  if (!usesTopics) return StationRequirement.notNeeded;
  if ((station ?? '').trim().isNotEmpty) return StationRequirement.satisfied;
  return stationsAvailable
      ? StationRequirement.missing
      : StationRequirement.unavailable;
}

/// 저장을 시킬 수 있는가.
bool canSaveRobot(StationRequirement requirement) =>
    requirement != StationRequirement.missing;

/// 사람에게 보여 줄 한 줄. 필요 없으면 null.
///
/// 흐린 단추만 두면 사람이 다른 칸을 뒤진다. 무엇이 빠졌고 그것이 어디에 쓰이는지
/// 그 자리에서 밝힌다.
String? stationRequirementMessage(
  StationRequirement requirement,
  String category,
) => switch (requirement) {
  StationRequirement.notNeeded => null,
  StationRequirement.satisfied => null,
  StationRequirement.missing =>
    '자리를 골라야 저장할 수 있습니다. 이 자리는 RMF 충전 복귀 지점이며, '
        '새 로봇의 Gazebo Spawn · AMCL 초기 자세 기본값으로 사용됩니다. '
        '등록 후에는 별도의 시작 Waypoint를 선택할 수 있습니다.',
  StationRequirement.unavailable =>
    '맵에 $category 카테고리 Waypoint 가 없어 자리를 고를 수 없습니다. '
        '지금 저장하면 이 로봇은 지도 원점(0,0)에 놓입니다 — 맵을 불러온 뒤 '
        '자리를 정해 주세요.',
};

/// 배포를 막아야 하는 로봇들.
///
/// 등록 창은 "고를 자리가 하나도 없을 때"는 막지 않는다. 맵을 그리기 전에도
/// 로봇 목록은 짤 수 있어야 하기 때문이다. 그래서 자리 없는 로봇이 프로젝트에
/// 남을 수 있다.
///
/// 배포는 다르다. 여기까지 왔으면 맵은 이미 있고, 산출물이 만들어지는 순간
/// 좌표가 파일에 박힌다 — `spawn.launch.xml` 의 `-x -y`, `nav2_params.yaml` 의
/// AMCL 초기 자세, fleet 설정의 `charger`. 자리가 없으면 그 자리에 0 이
/// 들어가고, 두 대만 그래도 Gazebo 가 죽는다. 그러니 파일을 만들기 전에 막는다.
///
/// 예전에 자리 없이 저장된 로봇도 여기서 함께 걸린다.
///
/// Mock 로봇은 세지 않는다. 산출물에 올릴 것이 없다.
List<RmfProjectRobot> robotsMissingStation(List<RmfProjectRobot> robots) => [
  for (final robot in robots)
    if (robot.dataSource.usesTopics &&
        (robot.chargerWaypoint ?? '').trim().isEmpty)
      robot,
];

/// 배포를 막는 이유. 막을 것이 없으면 null.
String? deployBlockedMessage(List<RmfProjectRobot> robots) {
  final missing = robotsMissingStation(robots);
  if (missing.isEmpty) return null;
  final lines = [
    for (final robot in missing)
      '  · ${robot.robotId} · ${robot.displayName} — '
          '${robot.kind.waypointCategory} Waypoint 미지정',
  ];
  return '자리를 안 고른 로봇이 있어 내보내지 않았습니다.\n\n'
      '${lines.join('\n')}\n\n'
      '자리가 없으면 spawn 좌표가 0,0 이 됩니다. 두 대가 원점에 겹치면 '
      '메시끼리 파고들어 Gazebo 가 뜨자마자 죽습니다 — 그런데 RMF 와 Nav2 는 '
      '그대로 남아 토픽 이름만 보이고 값은 하나도 안 옵니다.\n\n'
      '로봇 등록에서 자리 Waypoint 를 고른 뒤 다시 내보내세요.';
}
