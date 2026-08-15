/// 실행 중인지를 앱의 기억이 아니라 실제 프로세스로 판단하는지 지킨다.
///
/// 예전에는 `startProject` 가 성공하면 켜지고 `stopProject` 가 끄는 변수 하나로
/// 실행 여부를 판단했다. 토글이라 앱 밖에서 벌어진 일을 몰랐다 —
///
///   1. 앱에서 띄운다        → 기억 = project1
///   2. 터미널에서 stop 한다  → 프로세스는 사라지는데 기억은 그대로
///   3. 앱에서 다시 띄운다    → `이미 project1 를 띄워 두었습니다`
///
/// 아무것도 안 도는데 영영 막혔고, 앱을 껐다 켜야만 풀렸다.
///
/// 근거는 실행 스크립트가 남기는 `.<맵>.pgid` 다. 앱이 띄웠든 터미널에서
/// 띄웠든 같은 파일이라, 누가 띄웠는지와 무관하게 지금 도는지를 알 수 있다.
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_project_runner.dart';

void main() {
  late Directory root;
  late Directory mapDir;

  const mapName = 'project1';

  File pgidFile() => File('${mapDir.path}/.$mapName.pgid');

  /// 살아 있는 프로세스 그룹 번호. 이 테스트 프로세스 자신의 것을 쓴다.
  int livePgid() {
    final result = Process.runSync('ps', ['-o', 'pgid=', '-p', '$pid']);
    return int.parse(result.stdout.toString().trim());
  }

  /// 아무도 쓰지 않는 프로세스 그룹 번호.
  ///
  /// 임의의 큰 수를 찍으면 언젠가 진짜 프로세스와 겹친다. 하나 띄웠다가 죽여서
  /// 확실히 빈 번호를 얻는다. 리눅스는 pid 를 순서대로 주므로 방금 비운 번호가
  /// 몇 초 안에 다시 쓰이지는 않는다.
  Future<int> deadPgid() async {
    final process = await Process.start('sleep', [
      '30',
    ], mode: ProcessStartMode.detached);
    // detached 는 새 세션을 만든다. 그래서 pid 가 곧 그룹 번호다.
    process.kill(ProcessSignal.sigkill);
    for (var i = 0; i < 100; i++) {
      final alive = await Process.run('kill', ['-0', '--', '-${process.pid}']);
      if (alive.exitCode != 0) return process.pid;
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }
    fail('테스트용 프로세스가 죽지 않았습니다 (pid ${process.pid})');
  }

  /// 실행 스크립트 시늉. 진짜와 같은 자리에 제 PGID 를 남기고 기다린다.
  ///
  /// `GAZEBO_GUI` 는 실행기가 낡은 스크립트를 걸러내려고 찾는 글자다. 없으면
  /// 창을 달라고 했을 때 `예전 판입니다` 로 막힌다.
  void writeRunScript() {
    File('${mapDir.path}/run_$mapName.sh').writeAsStringSync('''
#!/usr/bin/env bash
# GAZEBO_GUI RVIZ
ps -o pgid= -p \$\$ | tr -d ' ' > "${mapDir.path}/.$mapName.pgid"
sleep 300
''');
  }

  /// 파일에 실제로 번호가 적혔는지. 셸은 파일을 먼저 만들고 그 다음에 쓴다.
  bool pgidWritten() =>
      pgidFile().existsSync() &&
      pgidFile().readAsStringSync().trim().isNotEmpty;

  /// 실행 스크립트가 pgid 를 남길 때까지 기다린다.
  ///
  /// 넉넉히 준다. 전체 테스트를 함께 돌리면 기계가 바빠 bash 가 뜨는 데만 몇 초
  /// 걸린다. 짧게 잡았더니 파일 하나로 이 시험이 들쭉날쭉했다.
  Future<void> waitForPgid() async {
    for (var i = 0; i < 750 && !pgidWritten(); i++) {
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }
    expect(pgidWritten(), isTrue, reason: '실행 스크립트가 pgid 를 안 남겼다');
  }

  /// 터미널에서 `stop_<맵>.sh` 를 돌린 것과 같은 상태로 만든다.
  ///
  /// 우리 자신의 그룹 번호는 건드리지 않는다. 살아 있는 그룹이 필요한 시험은
  /// 이 프로세스의 번호를 쓰는데, 그것에 KILL 을 보내면 테스트 러너가 죽는다.
  Future<void> stopFromTerminal() async {
    final pgid = int.tryParse(pgidFile().readAsStringSync().trim());
    if (pgid != null && pgid != livePgid()) {
      await Process.run('kill', ['-KILL', '--', '-$pgid']);
    }
    if (pgidFile().existsSync()) pgidFile().deleteSync();
  }

  setUp(() {
    root = Directory.systemTemp.createTempSync('rmf_run_state');
    mapDir = Directory('${root.path}/rmf_maps/$mapName')
      ..createSync(recursive: true);
    // 현재 디렉터리는 건드리지 않는다. 프로세스 전체가 공유하는 값이라 같이
    // 도는 다른 테스트까지 흔들고, 잘못하면 진짜 rmf_maps 를 집는다.
    debugProjectRootOverride = root.path;
  });

  tearDown(() async {
    // 테스트가 띄운 것이 남지 않게 한다.
    if (pgidFile().existsSync()) await stopFromTerminal();
    debugProjectRootOverride = null;
    root.deleteSync(recursive: true);
  });

  group('실행 여부는 프로세스로 판단한다', () {
    test('pgid 파일이 없으면 도는 것이 없다', () async {
      expect(await findRunningProjects(), isEmpty);
    });

    test('살아 있는 그룹이면 도는 것으로 본다', () async {
      pgidFile().writeAsStringSync('${livePgid()}\n');
      final running = await findRunningProjects();
      expect(running.map((p) => p.mapName), [mapName]);
      expect(running.single.pgid, livePgid());
    });

    test('죽은 그룹이면 도는 것이 아니고 파일도 지운다', () async {
      // 남겨 두면 다음 실행이 또 막힌다. 손으로 지워야 풀리는 상태를 만들지
      // 않는다.
      pgidFile().writeAsStringSync('${await deadPgid()}\n');
      expect(await findRunningProjects(), isEmpty);
      expect(pgidFile().existsSync(), isFalse);
    });

    test('내용이 깨진 파일도 지운다', () async {
      pgidFile().writeAsStringSync('nonsense\n');
      expect(await findRunningProjects(), isEmpty);
      expect(pgidFile().existsSync(), isFalse);
    });

    test('빈 파일은 지우지 않는다', () async {
      // 실행 스크립트는 `ps ... > 파일` 로 적는데, 셸이 파일을 먼저 만들고 그
      // 다음에 쓴다. 그 찰나에 지우면 스크립트의 쓰기가 이름 없는 inode 로
      // 흘러가 그룹 번호가 영영 사라진다 — 그러면 중지할 수단이 없어진다.
      pgidFile().writeAsStringSync('');
      expect(await findRunningProjects(), isEmpty);
      expect(pgidFile().existsSync(), isTrue);
    });
  });

  group('터미널에서 내린 뒤 앱에서 다시 띄운다', () {
    test('막히지 않는다', () async {
      writeRunScript();

      final first = await startProject(mapName);
      expect(first.success, isTrue, reason: first.message);
      await waitForPgid();
      expect(runningProjectName, mapName);

      // 도는 중에는 막는다. 두 벌이 같은 도메인에 뜨면 schedule node 가 부딪힌다.
      final again = await startProject(mapName);
      expect(again.success, isFalse);
      expect(again.message, contains('이미 돌고 있습니다'));

      // 앱은 모르는 채로 밖에서 내려간다.
      await stopFromTerminal();

      // 여기가 예전에 막히던 자리다.
      final second = await startProject(mapName);
      expect(
        second.success,
        isTrue,
        reason: '터미널에서 내린 뒤에도 막혔다: ${second.message}',
      );
    });

    test('refreshRunningProject 가 기억을 실제와 맞춘다', () async {
      writeRunScript();
      expect((await startProject(mapName)).success, isTrue);
      await waitForPgid();
      expect(await refreshRunningProject(), mapName);

      await stopFromTerminal();
      // 화면이 `중지` 버튼을 계속 보여 주면 다시 띄울 길이 사라진다.
      expect(await refreshRunningProject(), isNull);
      expect(runningProjectName, isNull);
    });
  });

  group('앱이 띄우지 않은 것', () {
    test('돌고 있으면 새로 띄우지 않고, 앱 것이 아니라고 알린다', () async {
      writeRunScript();
      pgidFile().writeAsStringSync('${livePgid()}\n');

      final result = await startProject(mapName);
      expect(result.success, isFalse);
      expect(result.message, contains('앱이 띄운 것이 아닙니다'));
      expect(result.message, contains('stop_$mapName.sh'));
    });

    test('제 것으로 삼지 않는다', () async {
      // 삼았다가는 앱을 닫을 때 사용자가 터미널에서 띄운 것까지 함께 내린다.
      pgidFile().writeAsStringSync('${livePgid()}\n');
      expect(await refreshRunningProject(), isNull);
      expect(runningProjectName, isNull);
      // 대신 정리 대상으로는 보인다.
      expect((await findOrphanedProjects()).map((p) => p.mapName), [mapName]);
    });
  });
}
