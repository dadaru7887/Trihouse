/// 프로젝트 로그의 끝부분을 읽어 온다.
///
/// 지금까지 무엇이 잘못됐는지 알려면 터미널에서 로그를 뒤져야 했다. 로그는
/// 커서 그대로 읽으면 안 된다 — ODE 경고 한 줄이 시간당 1.8GB 씩 찼던 파일이다.
/// 끝에서 필요한 만큼만 잘라 온다.
library;

import 'dart:convert';
import 'dart:io';

/// 한 번에 읽어 들일 최대 바이트. 끝에서 이만큼만 본다.
const int _tailBytes = 512 * 1024;

/// 로그 한 줄. 어느 노드가 무슨 등급으로 말했는지 갈라 둔다.
class ProjectLogLine {
  const ProjectLogLine({
    required this.text,
    required this.level,
    required this.node,
  });

  final String text;

  /// `ERROR` · `WARN` · `INFO` 중 하나. 못 가리면 빈 문자열.
  final String level;

  /// `[gazebo-1]` 같은 launch 접두사에서 뽑은 이름.
  final String node;

  bool get isError => level == 'ERROR';
  bool get isWarning => level == 'WARN';

  static final RegExp _node = RegExp(r'^\[([^\]]+)\]');
  static final RegExp _level = RegExp(r'\[(ERROR|WARN|INFO|DEBUG|FATAL)\]');

  factory ProjectLogLine.parse(String raw) {
    final level = _level.firstMatch(raw)?.group(1) ?? '';
    return ProjectLogLine(
      text: raw,
      level: level == 'FATAL' ? 'ERROR' : level,
      node: _node.firstMatch(raw)?.group(1) ?? '',
    );
  }
}

/// 읽어 온 결과. 파일이 없으면 왜 없는지도 함께 준다.
class ProjectLogTail {
  const ProjectLogTail({
    required this.lines,
    required this.path,
    required this.sizeBytes,
    required this.modifiedAt,
    this.message,
  });

  final List<ProjectLogLine> lines;
  final String path;
  final int sizeBytes;
  final DateTime? modifiedAt;

  /// 못 읽었을 때의 사유. 읽었으면 null.
  final String? message;

  bool get isEmpty => lines.isEmpty;
}

/// [path] 의 마지막 [count] 줄을 읽는다.
///
/// 파일 전체를 메모리에 올리지 않는다. 3GB 짜리 로그가 실제로 있었다.
ProjectLogTail readLogTail(String path, {int count = 50}) {
  final file = File(path);
  if (!file.existsSync()) {
    return ProjectLogTail(
      lines: const [],
      path: path,
      sizeBytes: 0,
      modifiedAt: null,
      message:
          '아직 로그가 없습니다.\n'
          '백엔드를 한 번 띄우면 여기에 쌓입니다.',
    );
  }
  try {
    final length = file.lengthSync();
    final handle = file.openSync();
    try {
      final from = length > _tailBytes ? length - _tailBytes : 0;
      handle.setPositionSync(from);
      final bytes = handle.readSync(length - from);
      // 잘린 첫 줄은 버린다. 가운데부터 시작한 글자는 뜻이 없다.
      final text = utf8.decode(bytes, allowMalformed: true);
      final all = text.split('\n');
      if (from > 0 && all.isNotEmpty) all.removeAt(0);
      final kept = [
        for (final line in all)
          if (line.trim().isNotEmpty) line,
      ];
      final tail = kept.length > count
          ? kept.sublist(kept.length - count)
          : kept;
      return ProjectLogTail(
        lines: [for (final line in tail) ProjectLogLine.parse(line)],
        path: path,
        sizeBytes: length,
        modifiedAt: file.lastModifiedSync(),
      );
    } finally {
      handle.closeSync();
    }
  } catch (error) {
    return ProjectLogTail(
      lines: const [],
      path: path,
      sizeBytes: 0,
      modifiedAt: null,
      message: '$error',
    );
  }
}

/// 이 프로젝트의 실행 로그와 오류 로그.
({ProjectLogTail run, ProjectLogTail errors}) readProjectLogs({
  required String mapDirectory,
  required String mapName,
  int count = 50,
}) => (
  run: readLogTail('$mapDirectory/$mapName.log', count: count),
  errors: readLogTail('$mapDirectory/$mapName.err.log', count: count),
);

/// 로그를 비운다. **지우지 않는다.**
///
/// `rm` 으로 지우면 Gazebo 가 그 파일을 열고 있는 동안 자리가 안 돌아온다.
/// `ls` 에도 `du` 에도 안 보이는데 `df` 는 그대로다 — 실측 1.05GB 가 그렇게
/// 잡혀 있었다. 길이를 0으로 만들면 열려 있는 채로 자리가 돌아온다.
String? truncateLog(String path) {
  final file = File(path);
  if (!file.existsSync()) return null;
  try {
    file.openSync(mode: FileMode.write).closeSync();
    return null;
  } catch (error) {
    return '$error';
  }
}
