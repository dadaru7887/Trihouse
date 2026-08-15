/// 로그 읽기.
///
/// 로그는 커서 그대로 읽으면 안 된다. ODE 경고 한 줄이 시간당 1.8GB 씩 찼고
/// 실측 3.4GB 짜리가 남아 있었다.
@TestOn('vm')
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/project_log.dart';

void main() {
  late Directory dir;

  setUp(() => dir = Directory.systemTemp.createTempSync('logtail'));
  tearDown(() => dir.deleteSync(recursive: true));

  test('달라는 만큼만 준다', () {
    final file = File('${dir.path}/m.log')
      ..writeAsStringSync([for (var i = 1; i <= 200; i++) '줄 $i'].join('\n'));
    final tail = readLogTail(file.path, count: 30);
    expect(tail.lines, hasLength(30));
    expect(tail.lines.first.text, '줄 171');
    expect(tail.lines.last.text, '줄 200');
  });

  test('화면이 쓰는 값은 30줄이다', () {
    final source = File('lib/main.dart').readAsStringSync();
    expect(source, contains('static const int _count = 30;'));
    expect(source, contains("'마지막 30줄'"));
    // 화면을 다 먹지 않게 높이를 묶어 둔다.
    final page = source.substring(source.indexOf('class _ProjectLogPageState'));
    expect(page, contains('maxHeight: 360'));
  });

  test('모자라면 있는 만큼만', () {
    File('${dir.path}/m.log').writeAsStringSync('한 줄\n두 줄\n');
    expect(readLogTail('${dir.path}/m.log').lines, hasLength(2));
  });

  test('큰 파일도 끝만 읽는다', () async {
    // 전체를 메모리에 올리면 3GB 짜리에서 앱이 죽는다.
    final file = File('${dir.path}/big.log');
    final sink = file.openWrite();
    for (var i = 0; i < 40000; i++) {
      sink.writeln('${'x' * 60} 줄 $i');
    }
    await sink.close();
    expect(file.lengthSync(), greaterThan(512 * 1024));
    final tail = readLogTail(file.path, count: 30);
    expect(tail.lines, hasLength(30));
    expect(tail.lines.last.text, endsWith('줄 39999'));
    // 잘린 첫 줄은 버린다. 가운데부터 시작한 글자는 뜻이 없다.
    expect(tail.lines.first.text, startsWith('x'));
  });

  test('등급과 노드를 갈라 둔다', () {
    final line = ProjectLogLine.parse(
      '[fleet_adapter-14] [ERROR] [1786.2] [node]: Connection lost',
    );
    expect(line.level, 'ERROR');
    expect(line.isError, isTrue);
    expect(line.node, 'fleet_adapter-14');
  });

  test('FATAL 도 오류로 본다', () {
    expect(ProjectLogLine.parse('[x] [FATAL] 죽음').isError, isTrue);
  });

  test('없는 파일은 무엇을 하면 되는지 알린다', () {
    final tail = readLogTail('${dir.path}/없다.log');
    expect(tail.isEmpty, isTrue);
    expect(tail.message, contains('백엔드를 한 번 띄우면'));
  });

  test('실행 로그와 오류 로그를 함께 읽는다', () {
    File('${dir.path}/gwanghee.log').writeAsStringSync('보통 줄\n');
    File('${dir.path}/gwanghee.err.log').writeAsStringSync('[ERROR] 나쁨\n');
    final logs = readProjectLogs(mapDirectory: dir.path, mapName: 'gwanghee');
    expect(logs.run.lines.single.text, '보통 줄');
    expect(logs.errors.lines.single.isError, isTrue);
  });

  group('로그 비우기', () {
    test('지우지 않고 길이를 0으로 만든다', () {
      // rm 으로 지우면 Gazebo 가 열고 있는 동안 자리가 안 돌아온다. 실측
      // 1.05GB 가 ls 에도 du 에도 안 보이는 채로 잡혀 있었다.
      final file = File('${dir.path}/m.log')..writeAsStringSync('가득\n' * 100);
      expect(file.lengthSync(), greaterThan(0));
      expect(truncateLog(file.path), isNull);
      expect(file.existsSync(), isTrue, reason: '파일은 남아 있어야 한다');
      expect(file.lengthSync(), 0);
    });

    test('없는 파일은 조용히 넘어간다', () {
      expect(truncateLog('${dir.path}/없다.log'), isNull);
    });

    test('비운 뒤에는 읽을 줄이 없다', () {
      File('${dir.path}/m.log').writeAsStringSync('한 줄\n');
      truncateLog('${dir.path}/m.log');
      expect(readLogTail('${dir.path}/m.log').lines, isEmpty);
    });
  });
}
