/// 프로젝트 실행 스크립트를 앱에서 띄우고 내린다.
///
/// 앱이 띄운 것만 앱이 내린다. 사용자가 터미널에서 직접 띄운 것을 앱이 종료할
/// 때 같이 죽이면 놀랄 일이다.
///
/// 자식 프로세스를 **자기 프로세스 그룹**으로 띄운다(`setsid`). 그래야 앱이
/// 죽어도 ros2 launch 가 함께 끌려가지 않고, 반대로 내릴 때는 그룹째 한 번에
/// 정리할 수 있다.
library;

import 'dart:io';

import 'package:meta/meta.dart';

import 'rmf_config_export.dart';
import 'simulation_backend.dart';

export 'simulation_backend.dart';

class RmfRunResult {
  const RmfRunResult({required this.success, required this.message});
  final bool success;
  final String message;
}

/// 앱이 띄운 프로젝트. 종료할 때 이것만 정리한다.
///
/// **기억일 뿐 사실이 아니다.** 앱 밖에서 `stop_<맵>.sh` 를 돌리면 프로세스는
/// 사라지는데 이 변수는 그대로 남는다. 예전에는 실행 여부를 이 변수만으로
/// 판단해서, 터미널에서 내린 뒤 앱에서 다시 띄우려 하면 영영 `이미 띄워
/// 두었습니다` 로 막혔다. 앱을 껐다 켜야만 풀렸다.
///
/// 그래서 실제 판단은 늘 [findRunningProjects] 로 한다. 이 변수는 **누가
/// 띄웠는지**만 기억한다 — 앱을 닫을 때 앱이 띄운 것만 정리하기 위해서다.
String? _startedProject;
int? _startedPid;

/// 앱이 지금 띄워 둔 프로젝트 이름. 없으면 null.
///
/// 화면을 그리는 중에 읽으므로 프로세스를 뒤지지 않고 기억만 돌려준다. 낡았을
/// 수 있다 — 버튼을 다시 그리기 전에 [refreshRunningProject] 로 맞춘다.
String? get runningProjectName => _startedProject;

/// 테스트에서만 쓰는 뿌리 경로. 평소에는 null 이다.
///
/// 실행기는 평소 현재 디렉터리에서 위로 올라가며 `rmf_maps` 를 찾는다. 그런데
/// 현재 디렉터리는 프로세스 전체가 공유하는 값이라, 테스트가 그것을 바꾸면 같은
/// 프로세스의 다른 테스트까지 흔든다. 더 나쁜 것은 그러다 **진짜 rmf_maps** 를
/// 찾아 사용자의 배포를 건드릴 수 있다는 점이다.
@visibleForTesting
String? debugProjectRootOverride;

Directory? _findProjectRoot() {
  final override = debugProjectRootOverride;
  if (override != null) return Directory(override).absolute;
  final configured = Platform.environment['RMF_ROOT'];
  if (configured != null && configured.isNotEmpty) {
    final directory = Directory(configured).absolute;
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

String? _mapDirectory(String mapName) {
  final root = _findProjectRoot();
  if (root == null) return null;
  return '${root.path}/rmf_maps/${safeMapDirectoryName(mapName)}';
}

/// 실행 스크립트가 남긴 프로세스 그룹 파일. 이것이 실행 여부의 근거다.
///
/// `run_<맵>.sh` 가 뜨면서 제 PGID 를 여기 적고, `stop_<맵>.sh` 가 내리면서
/// 지운다. 앱이 띄웠든 터미널에서 띄웠든 같은 파일이라, 누가 띄웠는지와 무관하게
/// 지금 도는지를 알 수 있다.
File _pgidFile(String directory, String mapName) =>
    File('$directory/.$mapName.pgid');

/// 파일에 적힌 프로세스 그룹이 살아 있으면 그 번호를, 아니면 null 을 준다.
///
/// 죽어 있으면 파일을 지운다. 프로세스가 이미 없는데 파일만 남아 있으면 다음
/// 실행이 또 막힌다 — 사용자가 손으로 지워야 풀리는 상태를 만들지 않는다.
/// 지우기가 실패해도(권한·경합) 살아 있지 않다는 답은 그대로 준다.
///
/// 다만 **빈 파일은 건드리지 않는다.** 실행 스크립트는 `ps ... > 파일` 로
/// 적는데, 셸이 파일을 먼저 만들고 그 다음에 쓴다. 그 찰나에 우리가 지우면
/// 스크립트의 쓰기는 이름 없는 inode 로 흘러가 **그룹 번호가 영영 사라진다.**
/// 그러면 중지할 때 무엇을 끊어야 할지 알 수 없다.
Future<int?> _pgidIfAlive(File file) async {
  if (!file.existsSync()) return null;
  final text = (await file.readAsString()).trim();
  if (text.isEmpty) return null;
  final pgid = int.tryParse(text);
  // 음수는 프로세스 그룹. 시그널 0 은 죽이지 않고 살아 있는지만 본다.
  if (pgid != null) {
    final alive = await Process.run('kill', ['-0', '--', '-$pgid']);
    if (alive.exitCode == 0) return pgid;
  }
  try {
    if (file.existsSync()) await file.delete();
  } on FileSystemException {
    // 지우지 못해도 살아 있지 않다는 판단은 바뀌지 않는다.
  }
  return null;
}

/// 그 프로젝트가 지금 실제로 도는지 본다. 돌면 프로세스 그룹 번호.
Future<int?> _runningPgid(String mapName) async {
  final directory = _mapDirectory(mapName);
  if (directory == null) return null;
  return _pgidIfAlive(_pgidFile(directory, mapName));
}

/// `run_<맵이름>.sh` 를 띄운다.
///
/// [gazeboGui] 와 [rviz] 는 창을 띄울지 말지다. 실행 스크립트가 같은 이름의
/// 환경 변수로 받는다. 기본은 둘 다 안 띄우는 것이다 — 창이 없어도 라이다·
/// 카메라는 돌고, 창 두 개를 함께 띄우면 시뮬레이션이 눈에 띄게 느려진다.
Future<RmfRunResult> startProject(
  String mapName, {
  SimulationBackend backend = SimulationBackend.gazebo,
  bool gazeboGui = false,
  bool rviz = false,
}) async {
  // 앱의 기억이 아니라 지금 도는 프로세스를 본다. 터미널에서 내린 것을 앱은
  // 모르므로, 기억만 믿으면 그 뒤로 영영 `이미 띄워 두었습니다` 가 된다.
  final running = await findRunningProjects();
  if (running.isNotEmpty) {
    // 요청한 맵이 도는 중이면 그것을 짚어 준다. 다른 맵이면 그것을 짚는다 —
    // 한 번에 하나만 띄운다. 두 벌이 같은 도메인에 뜨면 schedule node 가
    // 부딪혀 엉뚱한 오류로 나타난다.
    final blocking = running.firstWhere(
      (project) => project.mapName == mapName,
      orElse: () => running.first,
    );
    final byApp = blocking.mapName == _startedProject;
    return RmfRunResult(
      success: false,
      message:
          '`${blocking.mapName}` 이(가) 이미 돌고 있습니다 '
          '(프로세스 그룹 ${blocking.pgid}).\n'
          '${byApp ? '먼저 중지하세요.' : '앱이 띄운 것이 아닙니다. 터미널에서 stop_${blocking.mapName}.sh 를 돌리거나 '
                    '로봇 운영 화면에서 정리하세요.'}',
    );
  }
  // 여기까지 왔으면 도는 것이 없다. 기억이 남아 있었다면 그것이 낡은 것이다.
  _startedProject = null;
  _startedPid = null;

  final directory = _mapDirectory(mapName);
  if (directory == null) {
    return const RmfRunResult(
      success: false,
      message: 'rmf_maps 디렉터리를 찾을 수 없습니다. RMF_ROOT 를 지정하세요.',
    );
  }
  final script = File('$directory/run_$mapName.sh');
  if (!script.existsSync()) {
    return RmfRunResult(
      success: false,
      message:
          '${script.path} 가 없습니다.\n'
          '설정 파일 메뉴에서 `디스크로 내보내기`를 먼저 누르세요.',
    );
  }
  // 예전에 내보낸 스크립트는 HEADLESS 하나로 둘을 함께 껐다. 그것에 대고
  // GAZEBO_GUI 를 넘겨 봐야 아무 일도 일어나지 않는다. 조용히 넘기면 "창을
  // 골랐는데 안 뜬다" 가 되고, 원인이 디스크의 낡은 파일이라는 것은 어디에도
  // 안 보인다. 창을 달라고 했을 때만 막는다 — 안 띄우는 것은 예전 스크립트도
  // 결과가 같다.
  final scriptContents = script.readAsStringSync();
  if ((gazeboGui || rviz) && !scriptContents.contains('GAZEBO_GUI')) {
    return RmfRunResult(
      success: false,
      message:
          '${script.path} 는 창을 따로 고를 수 없는 예전 판입니다.\n'
          '설정 파일 메뉴에서 `디스크로 내보내기`를 한 번 눌러 다시 만든 뒤 '
          '실행하세요.\n\n'
          '창 없이 띄우는 것은 지금 그대로도 됩니다.',
    );
  }
  if (backend != SimulationBackend.gazebo &&
      !scriptContents.contains('SIM_BACKEND')) {
    return RmfRunResult(
      success: false,
      message:
          '${script.path} 는 Gazebo만 지원하는 예전 판입니다.\n'
          '설정 파일 메뉴에서 `디스크로 내보내기`를 한 번 눌러 다시 만든 뒤 '
          '실행하세요.',
    );
  }
  try {
    // detached 로 띄우면 Dart 가 새 세션을 만들어 주므로 앱이 죽어도 함께
    // 끌려가지 않는다. 다만 여기서 받는 pid 는 그룹 리더가 아니다 — 그룹 정리는
    // 실행 스크립트가 남긴 PGID 파일을 보고 중지 스크립트가 한다.
    //
    // stdio 를 물리지 않는다. detachedWithStdio 로 띄우면 파이프가 생기는데
    // 앱이 그것을 읽지 않아, 64KB 가 차는 순간 Gazebo 가 write 에서 영원히
    // 멈춘다. 물리가 돌지 않아 모델도 안 올라오고 토픽에 값도 오지 않았다.
    // 출력은 실행 스크립트가 제 로그 파일로 보낸다.
    final process = await Process.start(
      'bash',
      [script.path],
      workingDirectory: directory,
      // 스크립트가 고른 값을 그대로 읽는다. 인자가 아니라 환경 변수인 것은,
      // 터미널에서 직접 띄울 때와 같은 방법이라야 앱 밖에서도 재현되기
      // 때문이다.
      environment: {
        'SIM_BACKEND': backend.storageValue,
        'GAZEBO_GUI': '$gazeboGui',
        'SIMULATOR_GUI': '$gazeboGui',
        'RVIZ': '$rviz',
      },
      mode: ProcessStartMode.detached,
    );
    _startedProject = mapName;
    _startedPid = process.pid;
    final shown = [
      if (gazeboGui && backend != SimulationBackend.none) '${backend.label} 창',
      if (rviz) 'RViz',
    ];
    return RmfRunResult(
      success: true,
      message:
          '`$mapName` 을 ${backend.label} 백엔드로 띄웠습니다 (pid $_startedPid).\n'
          '${shown.isEmpty ? '창 없이 띄웁니다.' : '${shown.join(' · ')} 을(를) 함께 띄웁니다.'}',
    );
  } catch (error) {
    return RmfRunResult(success: false, message: '$error');
  }
}

/// `stop_<맵이름>.sh` 로 내린다. [mapName] 을 주지 않으면 앱이 띄운 것을 내린다.
Future<RmfRunResult> stopProject([String? mapName]) async {
  // 기억이 낡았을 수 있다. 내릴 대상을 정하기 전에 실제와 맞춘다.
  final target = mapName ?? await refreshRunningProject();
  if (target == null) {
    // 앱이 띄운 것은 없지만 다른 것이 돌 수 있다. 그냥 `없습니다` 로 끝내면
    // 무엇이 실행 버튼을 막고 있는지 화면에서 알 길이 없다.
    final running = await findRunningProjects();
    if (running.isEmpty) {
      return const RmfRunResult(success: false, message: '앱이 띄워 둔 프로젝트가 없습니다.');
    }
    return RmfRunResult(
      success: false,
      message:
          '앱이 띄워 둔 프로젝트는 없습니다.\n'
          '다만 아직 도는 것이 있습니다 — '
          '${running.map((p) => '${p.mapName} (그룹 ${p.pgid})').join(', ')}.\n'
          '로봇 운영 화면에서 정리하세요.',
    );
  }
  final directory = _mapDirectory(target);
  if (directory == null) {
    return const RmfRunResult(
      success: false,
      message: 'rmf_maps 디렉터리를 찾을 수 없습니다.',
    );
  }
  final buffer = StringBuffer();
  final script = File('$directory/stop_$target.sh');
  if (script.existsSync()) {
    try {
      final result = await Process.run('bash', [
        script.path,
      ], workingDirectory: directory).timeout(const Duration(seconds: 60));
      buffer.writeln(result.stdout.toString().trim());
      final error = result.stderr.toString().trim();
      if (error.isNotEmpty) buffer.writeln(error);
    } catch (error) {
      buffer.writeln('중지 스크립트 실패: $error');
    }
  } else {
    buffer.writeln('${script.path} 가 없습니다. 프로세스 그룹만 정리합니다.');
  }
  // 중지 스크립트가 없거나 놓친 것이 있으면 여기서 마무리한다.
  //
  // 그룹 번호는 실행 스크립트가 남긴 파일에서 읽는다. Process.start 가 돌려준
  // pid 는 그룹 리더가 아니라서 그 번호로 그룹을 끊으면 엉뚱한 곳을 건드린다.
  final pgidFile = _pgidFile(directory, target);
  if (pgidFile.existsSync()) {
    final pgid = int.tryParse((await pgidFile.readAsString()).trim());
    if (pgid != null) {
      final alive = await Process.run('kill', ['-0', '--', '-$pgid']);
      if (alive.exitCode == 0) {
        await Process.run('kill', ['-INT', '--', '-$pgid']);
        await Future<void>.delayed(const Duration(seconds: 3));
        await Process.run('kill', ['-TERM', '--', '-$pgid']);
        buffer.writeln('프로세스 그룹 $pgid 를 정리했습니다.');
      }
    }
    if (pgidFile.existsSync()) await pgidFile.delete();
  }
  _startedProject = null;
  _startedPid = null;
  return RmfRunResult(success: true, message: buffer.toString().trim());
}

/// 지난 실행에서 정리되지 않고 남은 프로젝트.
class OrphanedProject {
  const OrphanedProject({required this.mapName, required this.pgid});

  final String mapName;
  final int pgid;
}

/// 지금 실제로 도는 프로젝트를 모두 찾는다. 누가 띄웠는지는 가리지 않는다.
///
/// 실행 스크립트가 남긴 `.<맵이름>.pgid` 를 훑어 그 프로세스 그룹이 아직 살아
/// 있는지 본다. 이것이 실행 여부의 유일한 근거다 — 앱의 기억은 앱 밖에서 벌어진
/// 일을 모른다.
///
/// 프로세스가 이미 없는 파일은 조용히 지운다. 남지도 않은 것을 두고 알릴 일은
/// 아니다.
Future<List<OrphanedProject>> findRunningProjects() async {
  final root = _findProjectRoot();
  if (root == null) return const [];
  final maps = Directory('${root.path}/rmf_maps');
  if (!maps.existsSync()) return const [];
  final found = <OrphanedProject>[];
  for (final entry in maps.listSync()) {
    if (entry is! Directory) continue;
    for (final file in entry.listSync()) {
      if (file is! File) continue;
      final name = file.uri.pathSegments.last;
      if (!name.startsWith('.') || !name.endsWith('.pgid')) continue;
      final mapName = name.substring(1, name.length - '.pgid'.length);
      final pgid = await _pgidIfAlive(file);
      if (pgid == null) continue;
      found.add(OrphanedProject(mapName: mapName, pgid: pgid));
    }
  }
  found.sort((a, b) => a.mapName.compareTo(b.mapName));
  return found;
}

/// 강제 종료로 남은 프로젝트를 찾는다. 앱이 띄워 둔 것은 뺀다.
///
/// 앱이 강제로 죽으면(kill -9·전원) 종료 훅이 돌지 않아 프로세스가 그대로
/// 남는다. 그것을 시작할 때 알아채고 정리하라고 알린다.
Future<List<OrphanedProject>> findOrphanedProjects() async {
  final running = await findRunningProjects();
  // 도는 것이 없으면 앱의 기억도 낡은 것이다. 여기서 같이 털어 낸다.
  if (!running.any((project) => project.mapName == _startedProject)) {
    _startedProject = null;
    _startedPid = null;
  }
  return running
      .where((project) => project.mapName != _startedProject)
      .toList(growable: false);
}

/// [runningProjectName] 을 실제 프로세스와 맞춘다. 맞춘 뒤의 값을 돌려준다.
///
/// 앱 밖에서 내린 프로젝트를 앱이 계속 띄워 둔 것으로 알고 있으면, 실행 버튼
/// 대신 중지 버튼이 남아 다시 띄울 길이 없어진다. 화면을 그리기 전에 부른다.
///
/// 앱이 띄우지 않은 것은 여기서 제 것으로 삼지 않는다. 그랬다가는 앱을 닫을 때
/// 사용자가 터미널에서 띄운 것까지 함께 내린다.
Future<String?> refreshRunningProject() async {
  final started = _startedProject;
  if (started == null) return null;
  if (await _runningPgid(started) != null) return started;
  _startedProject = null;
  _startedPid = null;
  return null;
}
