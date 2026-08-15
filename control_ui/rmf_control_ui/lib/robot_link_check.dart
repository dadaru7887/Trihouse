/// 로봇 하나가 실제로 값을 보내기까지 이어져야 하는 고리들.
///
/// Gazebo 로 등록했는데 화면에 앱 Mock 이라고 나올 때, 원인은 늘 넷 중 하나다.
/// 그런데 어느 것인지는 어디에도 안 보여서, 그때마다 로그를 뒤졌다.
///
/// 여기서는 고리를 순서대로 세워 두고 **처음 끊긴 곳 하나만** 짚는다. 순서가
/// 있는 일이라 아래를 먼저 손대 봐야 소용이 없다 — 월드가 없는데 로봇을
/// 올리면 `create` 가 월드 이름을 영영 기다린다.
library;

/// 고리 하나의 상태.
enum RobotLinkState {
  /// 이어져 있다.
  ok,

  /// 여기서 끊겼다.
  broken,

  /// 앞이 끊겨서 볼 수 없었다. 모르는 것을 모른다고 해야 한다.
  unknown,
}

/// 끊긴 고리를 잇는 데 필요한 행동.
enum RobotLinkAction {
  /// 로봇 등록에서 자리 Waypoint 를 고른다.
  chooseStation,

  /// 프로젝트 백엔드를 띄운다. Gazebo 월드가 여기서 올라온다.
  startBackend,

  /// 이 로봇만 월드에 올린다. `robots/<ID>/spawn.launch.xml`.
  spawnRobot,

  /// 이 로봇 몫 토픽 다리를 띄운다. `robots/<ID>/bridge.yaml`.
  startBridge,

  /// 앱이 다시 구독하게 한다.
  resubscribe,
}

extension RobotLinkActionLabel on RobotLinkAction {
  String get label => switch (this) {
    RobotLinkAction.chooseStation => '자리 고르기',
    RobotLinkAction.startBackend => '백엔드 다시 띄우기',
    RobotLinkAction.spawnRobot => '이 로봇만 올리기',
    RobotLinkAction.startBridge => '다리만 잇기',
    RobotLinkAction.resubscribe => '다시 구독하기',
  };

  /// 누르면 무엇이 일어나는지. 누르기 전에 알아야 한다.
  String get detail => switch (this) {
    RobotLinkAction.chooseStation =>
      '로봇 등록에서 자리 Waypoint 를 고릅니다. 그 자리가 spawn 좌표가 됩니다.',
    RobotLinkAction.startBackend =>
      '이 프로젝트의 실행 스크립트를 띄웁니다. Gazebo 월드와 RMF 가 함께 올라옵니다.',
    RobotLinkAction.spawnRobot =>
      '이미 떠 있는 월드에 이 로봇만 올립니다. robots/<로봇>/spawn.launch.xml.',
    RobotLinkAction.startBridge =>
      '이 로봇 몫의 토픽 다리만 띄웁니다. robots/<로봇>/bridge.yaml.',
    RobotLinkAction.resubscribe => '앱이 이 로봇의 토픽을 다시 구독합니다.',
  };
}

/// 고리 하나.
class RobotLink {
  const RobotLink({
    required this.title,
    required this.state,
    required this.detail,
    this.action,
  });

  final String title;
  final RobotLinkState state;

  /// 무엇을 보고 그렇게 판정했는지. 값이 있으면 값을 적는다.
  final String detail;

  /// 끊긴 고리에만 붙는다.
  final RobotLinkAction? action;
}

/// 지금 무엇을 알고 있는지 모아 둔 것.
///
/// 전부 이미 앱이 읽고 있는 값이다. 새로 물어보는 것은 월드 안에 있는지 하나뿐.
class RobotLinkFacts {
  const RobotLinkFacts({
    required this.usesTopics,
    required this.hasStation,
    required this.stationName,
    required this.spawnX,
    required this.spawnY,
    required this.backendRunning,
    this.staleBackendDetail,
    required this.nodesUp,
    required this.topicFlowing,
    required this.topicSeen,
    required this.receiving,
    this.lastPoseAgeSeconds,
  });

  /// 값의 출처가 Gazebo 나 실물인가. Mock 이면 이 검사 자체가 뜻이 없다.
  final bool usesTopics;

  final bool hasStation;
  final String? stationName;
  final double? spawnX;
  final double? spawnY;

  /// 이 프로젝트의 백엔드가 떠 있는가.
  final bool backendRunning;

  /// 배포가 백엔드보다 나중인가.
  ///
  /// `ros2 launch` 는 파일을 띄울 때 한 번만 읽는다. 나중에 배포해도 이미 뜬
  /// 월드에는 안 들어간다. 로봇 0대이던 시절의 Gazebo 가 34분째 돌면서, 토픽
  /// 이름만 있고 값은 하나도 안 온 일이 있었다.
  final String? staleBackendDetail;

  /// 이 로봇의 노드가 떠 있는가 (`/<네임스페이스>/robot_state_publisher`).
  /// 확인 못 했으면 null. spawn launch 가 돌았는지를 말해 준다.
  final bool? nodesUp;

  /// 토픽에 값이 실제로 흐르는가. 확인 못 했으면 null.
  ///
  /// 이름이 보이는 것과 값이 오는 것은 다르다. 다리는 모델이 없어도 토픽을
  /// 만들어 놓는다 — 이름은 있는데 영영 아무것도 안 오는 것이 이 경우다.
  final bool? topicFlowing;

  /// 토픽 이름이 목록에 보이는가. 확인 못 했으면 null.
  ///
  /// 이름이 보이는 것과 값이 오는 것은 다르다. 다리가 만들어 놓기만 해도
  /// 이름은 생긴다.
  final bool? topicSeen;

  /// 앱이 실제로 값을 받고 있는가.
  final bool receiving;

  /// 마지막으로 값을 받은 지 몇 초 됐는가.
  final double? lastPoseAgeSeconds;
}

/// 고리를 순서대로 세우고 처음 끊긴 곳까지만 판정한다.
///
/// 처음 끊긴 곳 **뒤는 전부 `unknown`** 이다. 앞이 끊겼으면 뒤는 볼 수 없고,
/// 볼 수 없는 것을 끊겼다고 적으면 엉뚱한 데를 고치게 된다.
List<RobotLink> checkRobotLinks(RobotLinkFacts facts) {
  if (!facts.usesTopics) {
    return const [
      RobotLink(
        title: '값의 출처',
        state: RobotLinkState.ok,
        detail: '앱 Mock 입니다. 토픽을 쓰지 않으므로 볼 고리가 없습니다.',
      ),
    ];
  }

  final links = <RobotLink>[];
  var broken = false;

  void add(
    String title, {
    required bool? good,
    required String okDetail,
    required String badDetail,
    RobotLinkAction? action,
  }) {
    if (broken || good == null) {
      links.add(
        RobotLink(
          title: title,
          state: RobotLinkState.unknown,
          detail: broken ? '앞이 끊겨 확인하지 못했습니다.' : '확인하지 못했습니다.',
        ),
      );
      return;
    }
    if (good) {
      links.add(
        RobotLink(title: title, state: RobotLinkState.ok, detail: okDetail),
      );
      return;
    }
    broken = true;
    links.add(
      RobotLink(
        title: title,
        state: RobotLinkState.broken,
        detail: badDetail,
        action: action,
      ),
    );
  }

  final spawnText = facts.spawnX == null || facts.spawnY == null
      ? ''
      : ' (${facts.spawnX!.toStringAsFixed(3)}, '
            '${facts.spawnY!.toStringAsFixed(3)})';
  add(
    '자리',
    good: facts.hasStation && facts.spawnX != null && facts.spawnY != null,
    okDetail: '${facts.stationName}$spawnText',
    badDetail: facts.hasStation
        ? '${facts.stationName} 을 지금 맵에서 찾지 못해 spawn 좌표가 없습니다.'
        : '자리를 고르지 않아 spawn 좌표가 없습니다. 지도 원점에 놓입니다.',
    action: RobotLinkAction.chooseStation,
  );

  add(
    'Gazebo',
    // 떠 있어도 옛날 설정으로 뜬 것이면 없는 것과 같다. 이름만 있고 값이
    // 안 오는 상태가 되어, 아래 고리를 아무리 봐도 원인이 안 나온다.
    good: facts.backendRunning && facts.staleBackendDetail == null,
    okDetail: '월드가 떠 있습니다.',
    // 인자는 먼저 계산된다. 끊기지 않았을 때도 이 값이 만들어지므로 `!` 를
    // 쓰면 안 된다.
    badDetail: facts.staleBackendDetail ?? '월드가 안 떠 있습니다. 올릴 곳이 없습니다.',
    action: RobotLinkAction.startBackend,
  );

  add(
    '이 로봇 노드',
    good: facts.nodesUp,
    okDetail: '이 로봇의 노드가 떠 있습니다.',
    badDetail: '이 로봇을 올리는 launch 가 안 돌았습니다.',
    action: RobotLinkAction.spawnRobot,
  );

  add(
    '토픽 다리',
    good: facts.topicSeen,
    okDetail: '토픽 이름이 보입니다.',
    badDetail: '토픽 이름조차 없습니다. 다리가 안 떠 있습니다.',
    action: RobotLinkAction.startBridge,
  );

  add(
    '토픽에 값',
    good: facts.topicFlowing,
    okDetail: '값이 흐릅니다.',
    // 이름은 다리가 만들어 놓는다. 값이 없다는 것은 월드에 모델이 없다는 뜻이다.
    badDetail: '이름은 있는데 값이 안 옵니다. 월드에 이 로봇이 없습니다.',
    action: RobotLinkAction.spawnRobot,
  );

  final age = facts.lastPoseAgeSeconds;
  add(
    '앱 수신',
    good: facts.receiving,
    okDetail: age == null
        ? '값을 받고 있습니다.'
        : '${age.toStringAsFixed(1)}초 전에 받았습니다.',
    badDetail: '토픽은 있는데 앱에 값이 안 옵니다.',
    action: RobotLinkAction.resubscribe,
  );

  return links;
}

/// 처음 끊긴 고리. 다 이어져 있으면 null.
RobotLink? firstBrokenLink(List<RobotLink> links) =>
    links.where((link) => link.state == RobotLinkState.broken).firstOrNull;

/// 한 줄 요약. 카드 접힌 상태에서 보여 준다.
String robotLinkSummary(List<RobotLink> links) {
  final broken = firstBrokenLink(links);
  if (broken != null) return '${broken.title}에서 끊겼습니다 — ${broken.detail}';
  final unknown = links.where((link) => link.state == RobotLinkState.unknown);
  if (unknown.isNotEmpty) return '아직 다 확인하지 못했습니다.';
  return '다 이어져 있습니다.';
}
