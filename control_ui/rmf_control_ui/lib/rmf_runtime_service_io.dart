/// 이미 떠 있는 Open-RMF 백엔드를 확인하고 내린다.
///
/// 남아 있는 노드를 모르고 새 백엔드를 띄우면 schedule node 와 fleet adapter 가
/// 서로 부딪혀 엉뚱한 오류로 나타난다. 화면에서 먼저 보고 정리할 수 있어야 한다.
library;

import 'dart:io';

import 'rmf_config_export.dart';
import 'rmf_runtime_models.dart';
import 'workspace_paths_io.dart';

/// 노드 이름이 이 조각을 담고 있으면 RMF 백엔드로 본다.
///
/// `ros2 node list` 에는 이 앱이 띄운 Gazebo 브리지 같은 것도 함께 나오므로,
/// 내려야 할 대상만 골라낸다.
const List<String> _rmfNodeHints = [
  'rmf',
  'fleet_adapter',
  'fleet_manager',
  'building_map_server',
  'traffic_schedule',
  'door_supervisor',
  'lift_supervisor',
  'dispatcher',
];

/// 프로젝트 루트. `rmf_maps` 가 있는 곳을 기준으로 찾는다.
///
/// 예전에는 `openrmf/scripts/stop_office.sh` 가 있는 곳을 찾았다. office 데모를
/// 받지 않은 곳에서는 루트를 아예 못 찾아 중지가 통째로 실패했다. 실행도 중지도
/// 이제 프로젝트별이므로 데모와 상관이 없다.
Directory? _findProjectRoot() {
  final configuredRoot = Platform.environment['RMF_ROOT'];
  if (configuredRoot != null && configuredRoot.isNotEmpty) {
    final directory = Directory(configuredRoot).absolute;
    if (Directory('${directory.path}/rmf_maps').existsSync()) return directory;
  }
  var directory = Directory.current.absolute;
  for (var i = 0; i < 8; i++) {
    if (Directory('${directory.path}/rmf_maps').existsSync()) return directory;
    final parent = directory.parent;
    if (parent.path == directory.path) break;
    directory = parent;
  }
  return null;
}

/// 지금 프로세스가 돌고 있는 맵 프로젝트 이름.
///
/// 맵 디렉터리 경로를 인자로 물고 있으면 그 프로젝트가 띄운 것이다. 앱이 띄운
/// 것이든 터미널에서 띄운 것이든 똑같이 잡힌다.
///
/// 중지 스크립트 자신은 세지 않는다 — 그 경로에도 맵 디렉터리가 들어 있다.
Future<List<String>> runningBackendProjects() async {
  // 위젯 테스트에서는 프로세스를 뒤지지 않는다. 진짜 pgrep 을 띄우면 그
  // 프로세스가 테스트보다 오래 살고, 확인하는 것도 없다.
  if (Platform.environment.containsKey('FLUTTER_TEST')) return const [];
  final root = _findProjectRoot();
  if (root == null) return const [];
  final maps = Directory('${root.path}/rmf_maps');
  if (!maps.existsSync()) return const [];
  final running = <String>[];
  for (final entry in maps.listSync()) {
    if (entry is! Directory) continue;
    final name = entry.uri.pathSegments
        .where((segment) => segment.isNotEmpty)
        .last;
    try {
      final found = await Process.run('bash', [
        '-lc',
        'pgrep -u "\$(id -u)" -af ${_shellQuote(entry.path)} 2>/dev/null '
            "| grep -cv 'stop_' || true",
      ]).timeout(const Duration(seconds: 10));
      final count = int.tryParse(found.stdout.toString().trim()) ?? 0;
      if (count > 0) running.add(name);
    } catch (_) {
      // 한 프로젝트를 못 봐도 나머지는 봐야 한다.
    }
  }
  running.sort();
  return running;
}

/// Gazebo 서버가 실제로 돌고 있는 맵 프로젝트 이름.
///
/// [runningBackendProjects] 는 맵 디렉터리 경로를 물고 있는 프로세스를 전부
/// 센다. 그래서 **Gazebo 가 죽어도 RMF 와 Nav2 가 남아 있으면 떠 있다고 답한다.**
///
/// 실제로 그랬다. Gazebo 가 스폰 4초 만에 죽었는데(ODE 메시 충돌 어서션,
/// exit 134) 실행 스크립트가 그것을 안 보고 RMF 와 Nav2 를 그 위에 띄웠다.
/// 프로세스는 15개가 30분 넘게 살아 있었고 `ros2 topic list` 에도 이름이 다
/// 나왔지만 — 이름은 다리와 구독자가 남기는 것이다 — 발행자는 0개였다.
/// 그동안 로봇 상세의 `Gazebo` 고리는 초록이었고, 사람은 엉뚱한 데를 뒤졌다.
///
/// 그래서 물리를 돌리는 프로세스 하나만 센다. 월드 파일 경로를 물고 있는
/// `gz sim` 이다.
Future<List<String>> gazeboRunningProjects() async {
  if (Platform.environment.containsKey('FLUTTER_TEST')) return const [];
  final root = _findProjectRoot();
  if (root == null) return const [];
  final maps = Directory('${root.path}/rmf_maps');
  if (!maps.existsSync()) return const [];
  String listing;
  try {
    // 한 번만 묻고 맵마다 갈라 본다. 맵 수만큼 pgrep 을 띄우면 프로젝트가
    // 여럿일 때 화면이 눈에 띄게 늦어진다.
    final found = await Process.run('bash', [
      '-lc',
      'pgrep -u "\$(id -u)" -af "gz sim" 2>/dev/null || true',
    ]).timeout(const Duration(seconds: 10));
    listing = found.stdout.toString();
  } catch (_) {
    // 못 물어봤으면 아무것도 모른다. 없다고 답하는 편이 안전하다 — 떠 있다고
    // 잘못 답하면 그 아래 고리를 아무리 봐도 원인이 안 나온다.
    return const [];
  }
  // 월드 파일을 물고 있는 줄만 남긴다.
  //
  // `pgrep -af "gz sim"` 은 그 글자를 명령줄에 담은 것을 전부 잡는다 — 이
  // 검사를 띄운 셸 자신도 걸린다. 그래서 줄마다 월드 파일까지 확인한다.
  // 실제로 도는 서버의 명령줄은 이렇게 생겼다:
  //
  //   gz sim -r -s -v2 --headless-rendering /…/rmf_maps/project1/project1.world
  final worldLines = listing
      .split('\n')
      .where((line) => line.contains('gz sim') && line.contains('.world'))
      .toList();
  final running = <String>[];
  for (final entry in maps.listSync()) {
    if (entry is! Directory) continue;
    final name = entry.uri.pathSegments
        .where((segment) => segment.isNotEmpty)
        .last;
    // 디렉터리 경로째로 찾는다. 맵 이름만 보면 `gwanghee` 가 `gwanghee2` 의
    // 월드에도 걸린다.
    if (worldLines.any((line) => line.contains('${entry.path}/'))) {
      running.add(name);
    }
  }
  running.sort();
  return running;
}

/// 셸에 넘길 문자열을 작은따옴표로 감싼다. 맵 이름에 공백이 들어갈 수 있다.
String _shellQuote(String value) => "'${value.replaceAll("'", r"'\''")}'";

/// 프로젝트 중지 스크립트로 못 잡은 백엔드 프로세스를 쓸어낸다.
///
/// 프로젝트 스크립트는 제 맵 디렉터리를 문 것만 고른다. 그런데 백엔드에는
/// 어느 맵 프로젝트에도 속하지 않는 것이 있다 — office 데모(`tinyRobot`)가
/// 그렇고, launch 가 죽고 재부모화된 RMF core 도 그렇다.
///
/// 게다가 프로젝트가 하나도 안 잡히면 스크립트를 아예 안 돌린다. 그때는 무엇을
/// 눌러도 아무것도 안 죽었다 — 백엔드를 내렸는데 `/tinyRobot_fleet_manager` 가
/// 그대로 떠 있던 것이 이 경우다. 그래서 이 쓸어내기는 **언제나** 돈다.
///
/// 대상은 이 저장소와 RMF workspace 로만 좁힌다. 남의 ROS 작업은 건드리지
/// 않는다.
///
/// rmf-web API 컨테이너(`docker stop`)는 여기서 내리지 않는다. 그것은 프로세스가
/// 아니라 붙어 있는 서비스이고, 맵 프로젝트 launch 가
/// `server_uri:=ws://127.0.0.1:8000/_internal` 로 그것을 쓴다.
Future<String> sweepOrphanBackends(String rootPath) async {
  // 위젯 테스트에서는 진짜로 죽이지 않는다. 이 함수는 개발자 기계에서 도는
  // 프로세스를 실제로 끊으므로, 테스트가 무심코 부르면 하던 작업이 날아간다.
  if (Platform.environment.containsKey('FLUTTER_TEST')) {
    return '테스트에서는 쓸어내지 않습니다.';
  }
  final rmfWorkspace =
      Platform.environment['RMF_WS'] ?? '$rootPath/rmf_ws';
  try {
    final result = await Process.run('bash', [
      '-c',
      _sweepScript,
      'sweep',
      rootPath,
      rmfWorkspace,
    ]).timeout(const Duration(seconds: 90));
    return [result.stdout, result.stderr]
        .map((value) => value.toString().trim())
        .where((value) => value.isNotEmpty)
        .join('\n');
  } catch (error) {
    return '남은 프로세스를 쓸어내지 못했습니다: $error';
  }
}

/// [sweepOrphanBackends] 가 돌리는 셸.
///
/// `$1` 은 저장소 루트, `$2` 는 RMF workspace 다. Dart 쪽 `$` 이스케이프를 피하려고
/// 값은 인자로 넘긴다.
const String _sweepScript = r'''
set -uo pipefail
ROOT="$1"
RMF_WS="$2"
SELF=$$

# INT -> TERM -> KILL 로 올려 가며 내린다. rclpy 노드는 TERM 만으로는 종료 중에
# 굳는 일이 있고, 거기서 멈추면 다음 실행에서 이름이 겹친다.
stop_pids() {
  local pids=("$@") remaining=() pid signal
  ((${#pids[@]} == 0)) && return
  for signal in INT TERM KILL; do
    remaining=()
    for pid in "${pids[@]}"; do
      if kill -0 "$pid" 2>/dev/null &&
         [[ "$(ps -o stat= -p "$pid" 2>/dev/null)" != *Z* ]]; then
        remaining+=("$pid")
      fi
    done
    ((${#remaining[@]} == 0)) && return
    kill "-$signal" "${remaining[@]}" 2>/dev/null || true
    sleep 3
  done
}

# 무엇을 백엔드로 볼지. 확인할 때도 같은 목록을 다시 쓴다 — 죽인 무늬와 확인한
# 무늬가 다르면 확인이 아무 뜻이 없다.
#
# 대상은 이 저장소와 RMF workspace 로만 좁힌다. 남의 ROS 작업은 건드리지 않는다.
# office 데모는 설치 경로 끝의 실행 파일 이름까지 적는다 —
# `rmf_demos_fleet_adapter` 는 디렉터리 이름이기도 해서, 넓게 잡으면
# fleet_manager 가 fleet_adapter 로도 걸려 한 대가 두 대로 보인다.
LABELS=(
  "office 데모 launch"
  "office fleet manager"
  "office fleet adapter"
  "office Gazebo"
  "맵 프로젝트 잔여"
  "RMF core"
)
PATTERNS=(
  "ros2 launch $ROOT/openrmf/launch/"
  "/rmf_demos_fleet_adapter/fleet_manager"
  "/rmf_demos_fleet_adapter/fleet_adapter"
  "gz sim.*rmf_demos_maps"
  "$ROOT/rmf_maps/"
  "$RMF_WS/install/rmf_"
)

FOUND=()
declare -A CLAIMED=()
# 한 프로세스는 맨 처음 걸린 이름으로만 적는다. 뒤의 넓은 무늬가 앞의 것을 다시
# 잡으므로, 그대로 두면 fleet manager 한 대가 세 줄로 나와 세 대처럼 보인다.
collect() {
  local label="$1" pattern="$2" pid found=()
  while read -r pid; do
    [[ -z "$pid" || "$pid" == "$SELF" || "$pid" == "$PPID" ]] && continue
    [[ -n "${CLAIMED[$pid]:-}" ]] && continue
    CLAIMED[$pid]=1
    found+=("$pid")
  done < <(pgrep -u "$(id -u)" -f "$pattern" 2>/dev/null || true)
  if ((${#found[@]} == 0)); then
    echo "$label: 남은 것 없음"
    return
  fi
  echo "$label 중지: ${found[*]}"
  FOUND+=("${found[@]}")
}

for i in "${!PATTERNS[@]}"; do
  collect "${LABELS[$i]}" "${PATTERNS[$i]}"
done

if ((${#FOUND[@]} == 0)); then
  echo "쓸어낼 것이 없었습니다."
else
  stop_pids "${FOUND[@]}"
fi

# 정말 없어졌는지 같은 무늬로 다시 물어 확인한다.
#
# `ros2 node list` 는 쓰지 않는다. ros2 데몬과 DDS 는 사라진 참가자를 곧바로
# 지우지 않아서, 방금 죽인 노드가 십몇 초 동안 목록에 그대로 남는다 — 멀쩡히
# 죽였는데 못 죽였다고 읽게 된다. 프로세스가 즉시 참인 유일한 신호다.
LEFT=()
for i in "${!PATTERNS[@]}"; do
  while read -r pid; do
    [[ -z "$pid" || "$pid" == "$SELF" || "$pid" == "$PPID" ]] && continue
    [[ "$(ps -o stat= -p "$pid" 2>/dev/null)" == *Z* ]] && continue
    LEFT+=("${LABELS[$i]} (pid $pid)")
  done < <(pgrep -u "$(id -u)" -f "${PATTERNS[$i]}" 2>/dev/null || true)
done
if ((${#LEFT[@]} == 0)); then
  echo "확인: 남은 백엔드 프로세스 없음"
else
  echo "확인: 아직 남아 있습니다 —"
  printf '  %s\n' "${LEFT[@]}"
  exit 1
fi
''';

/// ROS 환경을 읽어 들인 뒤 [command] 를 실행하는 셸 한 줄.
///
/// 앱은 보통 ROS 를 source 하지 않은 셸에서 실행된다. 그대로 `ros2` 를 부르면
/// 명령을 찾지 못하므로 setup.bash 를 먼저 읽는다. 경로는 환경 변수로 바꿀 수
/// 있게 두었다 — 배포마다 workspace 위치가 다르다.
String _withRosEnvironment(String command) {
  final rosSetup =
      Platform.environment['ROS_SETUP'] ?? '/opt/ros/jazzy/setup.bash';
  final workspace = bundledRmfWorkspace();
  return 'set +u; '
      '[ -f "$rosSetup" ] && . "$rosSetup"; '
      '[ -f "$workspace/install/setup.bash" ] && . "$workspace/install/setup.bash"; '
      '$command';
}

/// 떠 있는 RMF 노드를 확인한다.
Future<RmfRuntimeStatus> probeRmfRuntime() async {
  try {
    final result = await Process.run('bash', [
      '-lc',
      _withRosEnvironment('ros2 node list'),
    ]).timeout(const Duration(seconds: 12));
    if (result.exitCode != 0) {
      final error = result.stderr.toString().trim();
      return RmfRuntimeStatus(
        available: false,
        nodes: const [],
        message: error.isEmpty
            ? 'ros2 명령을 실행하지 못했습니다. ROS 환경을 확인하세요.'
            : 'ros2 node list 실패: $error',
      );
    }
    final nodes =
        result.stdout
            .toString()
            .split('\n')
            .map((line) => line.trim())
            .where((line) => line.isNotEmpty)
            .where(
              (line) => _rmfNodeHints.any(
                (hint) => line.toLowerCase().contains(hint),
              ),
            )
            .toList()
          ..sort();
    return RmfRuntimeStatus(
      available: true,
      nodes: nodes,
      message: nodes.isEmpty
          ? '떠 있는 Open-RMF 백엔드가 없습니다.'
          : 'Open-RMF 백엔드가 이미 떠 있습니다.',
    );
  } on ProcessException catch (error) {
    return RmfRuntimeStatus(
      available: false,
      nodes: const [],
      message: 'ros2 명령을 찾을 수 없습니다: ${error.message}',
    );
  } catch (error) {
    return RmfRuntimeStatus(
      available: false,
      nodes: const [],
      message: '확인하지 못했습니다: $error',
    );
  }
}

/// 떠 있는 백엔드를 **전부** 내린다.
///
/// 두 단계다. 먼저 프로젝트마다 제 중지 스크립트를 돌리고, 그다음
/// [sweepOrphanBackends] 로 남은 것을 쓸어낸다.
///
/// 쓸어내기는 프로젝트가 하나도 안 잡혀도 반드시 돈다. 예전에는 프로젝트별로만
/// 다뤄서, 잡힌 프로젝트가 없으면 스크립트를 아예 안 돌렸고 그러면 아무것도 안
/// 죽었다. office 데모의 `/tinyRobot_fleet_manager` 는 어느 맵 프로젝트에도
/// 속하지 않으므로 늘 그 경우였다 — 백엔드를 내렸는데 그대로 떠 있었다.
///
/// office 데모의 중지 스크립트(`stop_office.sh`)는 여전히 부르지 않는다. 그것은
/// rmf-web API 컨테이너까지 `docker stop` 하는데, 맵 프로젝트 launch 가
/// `server_uri:=ws://127.0.0.1:8000/_internal` 로 그 API 를 쓰기 때문이다.
/// 데모의 **프로세스** 는 쓸어내기가 직접 잡는다.
///
/// [mapName] 을 주면 그 프로젝트를 먼저 내린다. 그 밖에 프로세스가 돌고 있는
/// 프로젝트도 함께 찾아 내린다.
Future<RmfStopResult> stopRmfBackend({String? mapName}) async {
  final root = _findProjectRoot();
  if (root == null) {
    return const RmfStopResult(
      success: false,
      output:
          '프로젝트 위치를 찾을 수 없습니다. '
          'RMF_ROOT 환경 변수로 지정하세요.',
    );
  }
  final buffer = StringBuffer();
  var success = true;

  Future<void> run(String label, String script, String workingDirectory) async {
    if (!File(script).existsSync()) return;
    buffer.writeln('[$label] $script');
    try {
      final result = await Process.run(
        'bash',
        [script],
        workingDirectory: workingDirectory,
        runInShell: false,
      ).timeout(const Duration(seconds: 90));
      final output = [result.stdout, result.stderr]
          .map((value) => value.toString().trim())
          .where((value) => value.isNotEmpty)
          .join('\n');
      if (output.isNotEmpty) buffer.writeln(output);
      if (result.exitCode != 0) success = false;
    } catch (error) {
      success = false;
      buffer.writeln('실패: $error');
    }
    buffer.writeln();
  }

  // 열린 프로젝트를 먼저, 그다음 프로세스가 돌고 있는 다른 프로젝트를.
  final targets = <String>{?mapName, ...await runningBackendProjects()};
  for (final name in targets) {
    final directory = '${root.path}/rmf_maps/${safeMapDirectoryName(name)}';
    await run(name, '$directory/stop_$name.sh', directory);
  }
  if (buffer.isEmpty) {
    // 스크립트를 하나도 못 돌린 이유를 남긴다. 쓸어내기는 그래도 돈다.
    buffer.writeln(
      targets.isEmpty
          ? '내릴 맵 프로젝트를 찾지 못했습니다. 남은 것만 쓸어냅니다.'
          : '${targets.join(', ')} 의 중지 스크립트가 디스크에 없습니다.\n'
                '`설정 파일` 에서 `디스크로 내보내기` 를 한 번 누르면 함께 '
                '생깁니다. 남은 것만 쓸어냅니다.',
    );
    buffer.writeln();
  }

  // 프로젝트 스크립트로 못 잡은 것을 마지막에 쓸어낸다. **언제나** 돈다.
  buffer.writeln('[남은 것 쓸어내기]');
  buffer.writeln(await sweepOrphanBackends(root.path));

  return RmfStopResult(success: success, output: buffer.toString().trim());
}

/// `/fleet_states` 를 한 번 읽어 RMF 에 붙은 로봇을 본다.
///
/// 이 토픽을 내는 것은 fleet adapter(`FleetUpdateHandle`) 하나뿐이다. 그래서 이
/// 한 번의 확인이 두 가지를 함께 알려 준다 — 어댑터가 살아 있는가, 그리고 어느
/// 로봇이 실제로 플릿에 붙었는가.
///
/// [rosDomainId] 를 반드시 넘긴다. 앱은 ROS 를 source 하지 않은 셸에서 도는데,
/// 도메인이 다르면 토픽이 있어도 하나도 안 보인다 — 오류는 안 난다.
///
/// 못 읽으면 [RmfFleetSnapshot.reachable] 이 false 다. 빈 목록을 "로봇이 하나도
/// 안 붙었다" 로 읽으면 안 된다. 모른다는 뜻이다.
Future<RmfFleetSnapshot> probeFleetStates({
  required int rosDomainId,
  Duration timeout = const Duration(seconds: 8),
}) async {
  // 발행자가 없으면 `topic echo` 는 영원히 기다린다. Process.run 의 timeout 은
  // 프로세스를 죽이지 않으므로 셸의 timeout 으로 끊는다.
  final seconds = timeout.inSeconds.clamp(2, 60);
  try {
    final result = await Process.run('bash', [
      '-lc',
      _withRosEnvironment(
        // `--field robots` 를 쓰지 않는다. 그렇게 부르면 ros2 가 YAML 이 아니라
        // **파이썬 repr** 을 한 줄로 뱉는다 —
        //
        //   [rmf_fleet_msgs.msg.RobotState(name='PK_01', model=..., ...)]
        //
        // 그 안의 `level_name='L1'` 까지 이름처럼 보여서 골라내기도 위험하다.
        // 통째로 받으면 제대로 된 YAML 이라 목록 항목이 `- name:` 로 온다.
        'export ROS_DOMAIN_ID=$rosDomainId; '
        'timeout $seconds ros2 topic echo /fleet_states --once',
      ),
    ]).timeout(timeout + const Duration(seconds: 4));
    if (result.exitCode != 0) {
      return const RmfFleetSnapshot(
        reachable: false,
        robots: {},
        message: '/fleet_states 를 읽지 못했습니다.',
      );
    }
    return RmfFleetSnapshot(
      reachable: true,
      robots: parseFleetStateRobots(result.stdout.toString()),
    );
  } catch (error) {
    return RmfFleetSnapshot(
      reachable: false,
      robots: const {},
      message: '$error',
    );
  }
}

/// `/clock` 을 내는 곳이 몇 군데인지 센다. 못 세면 null.
///
/// **하나여야 한다.** 둘이면 언제나 잘못된 상태다 — 이전 실행에서 남은
/// `parameter_bridge` 가 살아 있다는 뜻이고, 두 시계가 번갈아 나오니 시각이
/// 앞뒤로 튄다. tf2 가 `Detected jump back in time` 으로 버퍼를 비우고, AMCL 은
/// 위치추정을 잃고, Nav2 는 명령을 멈춘다.
///
/// 로봇은 멀쩡한데 가만히 서 있고, 원인이 한 시간 전에 남은 프로세스라는 것은
/// 어디에도 안 보인다. 실제로 그렇게 39번 튀었다.
Future<int?> probeClockPublishers({
  required int rosDomainId,
  // 탐색에 3초를 쓰므로 그보다 넉넉해야 한다.
  Duration timeout = const Duration(seconds: 15),
}) async {
  final seconds = timeout.inSeconds.clamp(2, 60);
  try {
    final result = await Process.run('bash', [
      '-lc',
      _withRosEnvironment(
        // `--no-daemon` 을 쓴다. 데몬은 CLI 가 빠르라고 두는 **캐시**라, 죽은
        // 발행자를 한동안 살아 있다고 답한다. 유령 다리를 죽인 직후에도
        // "2곳" 이 남아 확인표가 거짓말을 한다.
        //
        // 대신 탐색 시간을 늘려야 한다. 기본값으로 그냥 부르면 멀쩡히 도는
        // Gazebo 를 못 보고 0 을 돌려준다 — 실측: spin-time 1 → 0, 3 → 1,
        // 5 → 1. 0 은 `Gazebo 가 죽었다` 로 읽히므로 낡은 값보다 나쁘다.
        'export ROS_DOMAIN_ID=$rosDomainId; '
        'timeout $seconds ros2 topic info /clock --no-daemon --spin-time 3',
      ),
    ]).timeout(timeout + const Duration(seconds: 4));
    if (result.exitCode != 0) return null;
    final match = RegExp(
      r'Publisher count:\s*(\d+)',
    ).firstMatch(result.stdout.toString());
    return match == null ? null : int.tryParse(match.group(1)!);
  } catch (_) {
    return null;
  }
}
