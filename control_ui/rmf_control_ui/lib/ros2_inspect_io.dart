/// `ros2` 명령을 실제로 돌린다.
///
/// 앱은 보통 ROS 를 source 하지 않은 셸에서 뜬다. 그래서 `ros2` 를 그대로 부르면
/// 명령을 못 찾는다 — `rmf_runtime_service_io.dart` 와 같은 방식으로 setup.bash 를
/// 먼저 읽는다.
library;

import 'dart:io';

import 'ros2_inspect_models.dart';
import 'workspace_paths_io.dart';

/// ROS 환경을 읽어 들인 뒤 [command] 를 실행하는 셸 한 줄.
String _withRosEnvironment(String command) {
  final rosSetup =
      Platform.environment['ROS_SETUP'] ?? '/opt/ros/jazzy/setup.bash';
  final workspace = bundledRmfWorkspace();
  return 'set +u; '
      '[ -f "$rosSetup" ] && . "$rosSetup"; '
      '[ -f "$workspace/install/setup.bash" ] && . "$workspace/install/setup.bash"; '
      '$command';
}

/// 셸에 넘길 값을 작은따옴표로 감싼다.
///
/// 토픽 이름은 화면에서 고른 것이라 보통 안전하지만, 필터 칸에 사람이 친 것이
/// 그대로 흘러올 수 있는 자리다. 감싸 두면 그 걱정을 없앤다.
String _quote(String value) => "'${value.replaceAll("'", r"'\''")}'";

/// [Ros2Kind] 가 받는 조회 옵션만 붙인다.
List<String> _probeOptions(Ros2Kind kind, Ros2InspectRequest request) {
  if (!kind.takesProbeOptions) return const [];
  return [
    if (request.probe.flag != null) request.probe.flag!,
    '--spin-time',
    '${request.spinSeconds}',
  ];
}

Future<ProcessResult> _run(String command, {Duration? timeout}) => Process.run(
  'bash',
  ['-lc', _withRosEnvironment(command)],
).timeout(timeout ?? const Duration(seconds: 30));

/// 위젯 테스트에서는 프로세스를 띄우지 않는다.
///
/// 진짜 `ros2` 를 부르면 그 프로세스가 테스트보다 오래 살고, 결과도 그 기계에
/// 무엇이 떠 있는지에 따라 달라져 시험이 안 된다.
bool get _inTest => Platform.environment.containsKey('FLUTTER_TEST');

/// 목록을 읽는다.
Future<Ros2ListResult> ros2List(
  Ros2Kind kind,
  Ros2InspectRequest request,
) async {
  final parts = [
    'ros2',
    kind.command,
    'list',
    if (kind.listShowsType) '-t',
    if (request.includeHidden) ?kind.includeHiddenFlag,
    ..._probeOptions(kind, request),
  ];
  final command = parts.join(' ');
  if (_inTest) {
    return Ros2ListResult(
      success: false,
      items: const [],
      message: '테스트에서는 ros2 를 부르지 않습니다.',
      command: command,
    );
  }
  try {
    final result = await _run(
      command,
      // 직접 탐색은 spin-time 만큼 기다린다. 그보다 넉넉하게 둔다.
      timeout: Duration(seconds: 20 + request.spinSeconds * 2),
    );
    if (result.exitCode != 0) {
      final error = result.stderr.toString().trim();
      return Ros2ListResult(
        success: false,
        items: const [],
        message: error.isEmpty ? 'ros2 를 실행하지 못했습니다. ROS 환경을 확인하세요.' : error,
        command: command,
      );
    }
    final items = [
      for (final line in result.stdout.toString().split('\n'))
        ?parseRos2ListLine(line),
    ]..sort((a, b) => a.name.compareTo(b.name));
    return Ros2ListResult(
      success: true,
      items: items,
      message: items.isEmpty
          ? '${kind.label}이 없습니다. 백엔드가 떠 있는지, 조회 방식을 바꿔 보세요.'
          : '${kind.label} ${items.length}개',
      command: command,
    );
  } catch (error) {
    return Ros2ListResult(
      success: false,
      items: const [],
      message: '$error',
      command: command,
    );
  }
}

/// 하나를 자세히 본다.
Future<Ros2DetailResult> ros2Detail(
  Ros2Kind kind,
  String name,
  Ros2InspectRequest request,
) async {
  final parts = [
    'ros2',
    kind.command,
    'info',
    if (kind == Ros2Kind.topic) '--verbose',
    if (kind == Ros2Kind.action) '-t',
    if (kind == Ros2Kind.node && request.includeHidden) '--include-hidden',
    ..._probeOptions(kind, request),
    _quote(name),
  ];
  final command = parts.join(' ');
  if (_inTest) {
    return Ros2DetailResult(
      success: false,
      text: '테스트에서는 ros2 를 부르지 않습니다.',
      command: command,
    );
  }
  try {
    final result = await _run(
      command,
      timeout: Duration(seconds: 20 + request.spinSeconds * 2),
    );
    final out = result.stdout.toString().trimRight();
    final err = result.stderr.toString().trim();
    if (result.exitCode != 0) {
      return Ros2DetailResult(
        success: false,
        text: err.isEmpty ? 'ros2 가 실패했습니다.' : err,
        command: command,
      );
    }
    // 성공했는데 출력이 비는 경우가 있다. 그때도 무슨 일인지 적어 준다.
    return Ros2DetailResult(
      success: true,
      text: out.isEmpty
          ? (err.isEmpty ? '돌려준 내용이 없습니다.' : err)
          : (err.isEmpty ? out : '$out\n\n--- stderr ---\n$err'),
      command: command,
    );
  } catch (error) {
    return Ros2DetailResult(success: false, text: '$error', command: command);
  }
}

/// 토픽에서 값 한 건을 읽는다.
///
/// 발행자가 없는 토픽은 아무것도 오지 않는다. 그때 영원히 기다리면 화면이
/// 멎으므로 [waitSeconds] 로 끊는다. 끊긴 것과 실패한 것을 갈라 알린다 —
/// 목록에는 있어도 발행자가 없는 토픽이 흔하다.
Future<Ros2ValueResult> ros2TopicValue(
  String topic,
  Ros2InspectRequest request, {
  int waitSeconds = 5,
}) async {
  final parts = [
    'ros2',
    'topic',
    'echo',
    '--once',
    '--timeout',
    '$waitSeconds',
    ..._probeOptions(Ros2Kind.topic, request),
    _quote(topic),
  ];
  final command = parts.join(' ');
  if (_inTest) {
    return Ros2ValueResult(
      state: Ros2ValueState.failed,
      text: '테스트에서는 ros2 를 부르지 않습니다.',
      command: command,
    );
  }
  try {
    final result = await _run(
      command,
      timeout: Duration(seconds: waitSeconds + 20 + request.spinSeconds * 2),
    );
    final out = result.stdout.toString().trimRight();
    final err = result.stderr.toString().trim();
    if (out.isNotEmpty) {
      return Ros2ValueResult(
        state: Ros2ValueState.received,
        text: out,
        command: command,
      );
    }
    if (result.exitCode != 0) {
      return Ros2ValueResult(
        state: Ros2ValueState.failed,
        text: err.isEmpty ? 'ros2 가 실패했습니다.' : err,
        command: command,
      );
    }
    return Ros2ValueResult(
      state: Ros2ValueState.empty,
      text: err.isEmpty
          ? '$waitSeconds초 안에 값이 오지 않았습니다. 발행자가 없거나 '
                '이 토픽이 뜸하게 나옵니다.'
          : err,
      command: command,
    );
  } catch (error) {
    return Ros2ValueResult(
      state: Ros2ValueState.failed,
      text: '$error',
      command: command,
    );
  }
}
