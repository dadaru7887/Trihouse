/// 로봇 ID 는 ROS 2 이름 규칙을 지켜야 한다.
///
/// RMF 는 플릿에 붙은 로봇마다 토픽을 하나 만든다:
///
///   rmf/dynamic_event/begin/<플릿 이름>/<로봇 이름>
///
/// ROS 2 토픽 이름에는 영문·숫자·밑줄만 쓸 수 있다. **하이픈은 못 쓴다.** 그래서
/// `PK-01` 같은 ID 를 가진 로봇을 플릿에 붙이는 순간 fleet adapter 가 죽는다:
///
///   terminate called after throwing an instance of
///     'rclcpp::exceptions::InvalidTopicNameError'
///   what():  Invalid topic name: ... 'rmf/dynamic_event/begin/project1_pinky/PK-02'
///                                                                          ^
///
/// 죽는 것은 adapter 하나뿐이고 Gazebo·Nav2·RMF core 는 멀쩡히 남는다. 그래서
/// 토픽은 잘 오는데 주문만 안 먹는 상태가 된다 — `RMF 가 답하지 않았습니다`.
///
/// 앱이 만들던 기본 ID 가 `PK-01`·`OMX-01` 이었으므로, 기본값대로 만든 이동
/// 로봇은 반드시 이 크래시를 겪었다. 사람이 고칠 일이 아니라 앱이 안 만들어야
/// 하는 이름이다.
library;

import 'rmf_project_config.dart';

/// ROS 2 이름 한 토막. 첫 글자는 숫자일 수 없다.
final RegExp _validRobotId = RegExp(r'^[A-Za-z_][A-Za-z0-9_]*$');

/// 이 ID 를 그대로 써도 되는가.
bool isValidRobotId(String id) => _validRobotId.hasMatch(id.trim());

/// 사람이 친 것을 쓸 수 있는 ID 로 바꾼다.
///
/// 막기만 하면 사람이 무엇을 쳐야 하는지 알아내야 한다. 대신 칠 때마다 고쳐
/// 준다 — `PK-01` 을 치면 `PK_01` 이 된다.
///
/// 쓸 수 없는 글자는 밑줄로 바꾼다. 한글도 마찬가지다 — 토픽 이름에 못 들어간다.
/// 보여 줄 이름은 따로 있으므로(`displayName`) 여기서 뜻을 잃지 않는다.
String normalizeRobotId(String id) {
  final trimmed = id.trim();
  if (trimmed.isEmpty) return '';
  var normalized = trimmed.replaceAll(RegExp(r'[^A-Za-z0-9_]'), '_');
  // 숫자로 시작하면 토픽 이름이 될 수 없다. 앞에 R 을 붙여 살린다.
  if (RegExp(r'^[0-9]').hasMatch(normalized)) normalized = 'R$normalized';
  return normalized;
}

/// 이 ID 가 왜 못 쓰는지. 쓸 수 있으면 null.
String? robotIdProblem(String id) {
  final trimmed = id.trim();
  if (trimmed.isEmpty) return 'ID 를 적어야 합니다.';
  if (isValidRobotId(trimmed)) return null;
  if (RegExp(r'^[0-9]').hasMatch(trimmed)) {
    return 'ID 는 숫자로 시작할 수 없습니다. RMF 가 이 이름으로 토픽을 만듭니다.';
  }
  return 'ID 에는 영문·숫자·밑줄만 쓸 수 있습니다. RMF 가 이 이름으로 토픽을 '
      '만드는데(rmf/dynamic_event/begin/<플릿>/<로봇>), 하이픈이 들어가면 '
      'fleet adapter 가 뜨자마자 죽습니다.';
}

/// 지도 위 로봇의 ID 가 등록에 없을 때 보여 줄 말. 멀쩡하면 null.
///
/// 지도에 올린 로봇은 등록에서 온다. 그런데 등록을 지우거나 **ID 를 고치면**
/// 지도와 작업에는 옛 ID 가 남는다. 그 상태로 작업을 돌리면 `_isRmfDriven` 이
/// 그 ID 를 못 찾아 거짓을 돌려주고, 앱은 RMF 에 넘기지 않은 채 저 혼자 단계를
/// 센다. 화면에서는 로봇이 일하는 것처럼 보이는데 실제 로봇은 가만히 있는다.
///
/// 하이픈 ID(`PK-01`)를 밑줄(`PK_01`)로 바꾸게 되면서 이 어긋남이 반드시
/// 생긴다. 조용히 Mock 으로 돌지 않고 여기서 멈춰 세운다.
String? unregisteredRobotMessage(List<RmfProjectRobot> robots, String robotId) {
  if (robots.any((robot) => robot.robotId == robotId)) return null;
  final known = robots.map((robot) => robot.robotId).toList()..sort();
  final buffer = StringBuffer()
    ..writeln('등록된 로봇 ID 가 없습니다: $robotId')
    ..writeln()
    ..writeln(
      known.isEmpty ? '등록된 로봇이 하나도 없습니다.' : '지금 등록된 ID: ${known.join(', ')}',
    )
    ..writeln()
    ..writeln(
      '지도에 올린 로봇은 등록에서 옵니다. 등록을 지웠거나 ID 를 고치면 '
      '지도와 작업에는 옛 ID 가 남습니다.',
    )
    ..writeln()
    ..writeln(
      '이대로 두면 RMF 가 이 로봇을 모르므로 작업이 앱 안에서만 돕니다 — '
      '화면에서는 일하는 것처럼 보이는데 로봇은 가만히 있습니다.',
    )
    ..writeln()
    ..write('로봇 등록을 확인한 뒤 `로봇 Spawn` 으로 지도에 다시 올려 주세요.');
  return buffer.toString();
}

/// 배포를 막아야 하는 로봇들 — ID 를 토픽 이름으로 쓸 수 없는 것.
///
/// RMF 플릿에 들어가는 로봇만 본다. 설치 로봇은 플릿에 안 들어가므로 dynamic
/// event 토픽도 안 만들어진다 — gwanghee 의 `OMX-01` 이 하이픈인데도 멀쩡했던
/// 이유다. 멀쩡한 등록에 이름을 바꾸라고 시킬 이유는 없다.
List<RmfProjectRobot> robotsWithInvalidId(List<RmfProjectRobot> robots) => [
  for (final robot in robots)
    if (robot.isMobile &&
        robot.isManagedByRmf &&
        !isValidRobotId(robot.robotId))
      robot,
];

/// 배포를 막는 이유. 막을 것이 없으면 null.
String? deployBlockedByRobotId(List<RmfProjectRobot> robots) {
  final bad = robotsWithInvalidId(robots);
  if (bad.isEmpty) return null;
  final lines = [
    for (final robot in bad)
      '  · ${robot.robotId} → ${normalizeRobotId(robot.robotId)} 로 바꾸세요',
  ];
  return 'ROS 2 가 쓸 수 없는 ID 가 있어 내보내지 않았습니다.\n\n'
      '${lines.join('\n')}\n\n'
      'RMF 는 플릿 로봇마다 '
      '`rmf/dynamic_event/begin/<플릿>/<로봇>` 토픽을 만듭니다. 토픽 이름에는 '
      '영문·숫자·밑줄만 쓸 수 있어서, 하이픈이 들어가면 로봇을 플릿에 붙이는 '
      '순간 fleet adapter 가 죽습니다. Gazebo 와 Nav2 는 그대로 살아 있어 '
      '토픽은 오는데 주문만 안 먹는 상태가 됩니다.\n\n'
      '로봇 등록에서 ID 를 고친 뒤 다시 내보내세요.';
}
