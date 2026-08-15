/// `ros2` 를 불러 노드·토픽·서비스·액션을 들여다본다.
///
/// 지금까지 이런 확인은 터미널에서 손으로 했다. 그런데 백엔드가 떠 있는지,
/// 값이 실제로 오는지는 원인을 짚을 때마다 필요한 것이라, 화면에 두는 것이 맞다.
///
/// **조회 방식을 고를 수 있게 둔다.** `ros2` 는 보통 백그라운드 데몬에 대신
/// 물어보는데, 그 데몬과 직접 탐색(`--no-daemon`)의 결과가 서로 다르게 나오는
/// 일을 실제로 겪었다. 어느 쪽이 맞는지 화면에서 견줄 수 있어야 한다.
///
/// 명령마다 받는 옵션이 다르다 — **`ros2 action` 은 `--no-daemon` 도
/// `--spin-time` 도 받지 않는다.** 그래서 종류별로 갈라 붙인다.
library;

/// 들여다볼 대상.
enum Ros2Kind {
  node('노드', 'node'),
  topic('토픽', 'topic'),
  service('서비스', 'service'),
  action('액션', 'action');

  const Ros2Kind(this.label, this.command);

  /// 화면에 쓰는 이름.
  final String label;

  /// `ros2 <command> …` 의 그 자리.
  final String command;

  /// 이 종류가 `--no-daemon` 과 `--spin-time` 을 받나.
  ///
  /// `ros2 action list` 와 `ros2 action info` 는 `-t`·`-c` 만 받는다. 안 받는
  /// 옵션을 붙이면 usage 오류로 죽는다.
  bool get takesProbeOptions => this != Ros2Kind.action;

  /// 목록에 형식을 함께 달라고 할 수 있나.
  bool get listShowsType => this != Ros2Kind.node;

  /// `list` 에서 숨은 것까지 달라고 하는 옵션. 없으면 null.
  ///
  /// 종류마다 이름이 다르다 — 노드는 `-a`, 토픽·서비스는
  /// `--include-hidden-…` 이고 `ros2 action list` 는 아예 없다. 안 받는 옵션을
  /// 붙이면 usage 오류로 죽으므로 실제 이름을 그대로 적어 둔다.
  String? get includeHiddenFlag => switch (this) {
    Ros2Kind.node => '-a',
    Ros2Kind.topic => '--include-hidden-topics',
    Ros2Kind.service => '--include-hidden-services',
    Ros2Kind.action => null,
  };
}

/// 조회 방식.
enum Ros2Probe {
  /// 기본. `ros2` 가 백그라운드 데몬에 물어본다. 빠르지만 데몬이 어긋나면
  /// 조용히 빈 목록이 온다.
  daemon('데몬', null),

  /// 매번 직접 탐색한다. 느리지만 데몬을 거치지 않는다. 탐색 창이 짧으면
  /// 오히려 덜 보일 수 있어서 [Ros2InspectRequest.spinSeconds] 로 늘린다.
  direct('직접 탐색', '--no-daemon');

  const Ros2Probe(this.label, this.flag);
  final String label;
  final String? flag;
}

/// 무엇을 어떻게 물어볼지.
class Ros2InspectRequest {
  const Ros2InspectRequest({
    this.probe = Ros2Probe.daemon,
    this.spinSeconds = 3,
    this.includeHidden = false,
  });

  final Ros2Probe probe;

  /// 직접 탐색할 때 얼마나 기다릴지. 짧으면 덜 보인다.
  final int spinSeconds;

  /// 숨은 노드·토픽까지 볼지.
  final bool includeHidden;
}

/// 목록 한 줄.
class Ros2Item {
  const Ros2Item({required this.name, this.type});

  final String name;

  /// `list -t` 로 함께 온 형식. 노드에는 없다.
  final String? type;
}

/// 목록 조회 결과.
class Ros2ListResult {
  const Ros2ListResult({
    required this.success,
    required this.items,
    required this.message,
    this.command = '',
  });

  final bool success;
  final List<Ros2Item> items;

  /// 사람이 읽을 결과. 실패 이유나 왜 비었는지가 들어간다.
  final String message;

  /// 실제로 돌린 명령. 화면에 적어 두면 터미널에서 그대로 재현할 수 있다.
  final String command;
}

/// 자세히 보기 결과.
class Ros2DetailResult {
  const Ros2DetailResult({
    required this.success,
    required this.text,
    this.command = '',
  });

  final bool success;
  final String text;
  final String command;
}

/// 토픽에서 값 한 건을 읽은 결과.
class Ros2ValueResult {
  const Ros2ValueResult({
    required this.state,
    required this.text,
    this.command = '',
  });

  final Ros2ValueState state;
  final String text;
  final String command;
}

/// 값을 읽어 본 결과가 무엇인가.
enum Ros2ValueState {
  /// 값이 왔다.
  received,

  /// 명령은 됐지만 정해 둔 시간 안에 아무것도 안 왔다. 발행자가 없거나
  /// 그 토픽이 뜸하게 나오는 것이다.
  empty,

  /// 명령 자체가 실패했다.
  failed,
}

/// `list -t` 출력 한 줄을 이름과 형식으로 가른다.
///
/// `/clock [rosgraph_msgs/msg/Clock]` 처럼 온다. 형식이 없으면 이름만 돌려준다.
/// `ros2 topic list -v` 처럼 머리글이 섞인 출력은 여기 넣지 않는다.
Ros2Item? parseRos2ListLine(String raw) {
  final line = raw.trim();
  if (line.isEmpty) return null;
  // 머리글(`Published topics:`)이나 안내문은 이름이 아니다.
  if (!line.startsWith('/')) return null;
  final open = line.indexOf('[');
  if (open < 0) return Ros2Item(name: line);
  final close = line.lastIndexOf(']');
  final name = line.substring(0, open).trim();
  if (name.isEmpty) return null;
  if (close <= open) return Ros2Item(name: name);
  final type = line.substring(open + 1, close).trim();
  return Ros2Item(name: name, type: type.isEmpty ? null : type);
}
