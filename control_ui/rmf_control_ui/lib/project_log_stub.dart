/// 웹 빌드용 대체 구현. 브라우저에는 읽을 파일이 없다.
library;

class ProjectLogLine {
  const ProjectLogLine({
    required this.text,
    required this.level,
    required this.node,
  });

  final String text;
  final String level;
  final String node;

  bool get isError => level == 'ERROR';
  bool get isWarning => level == 'WARN';

  factory ProjectLogLine.parse(String raw) =>
      ProjectLogLine(text: raw, level: '', node: '');
}

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
  final String? message;

  bool get isEmpty => lines.isEmpty;
}

ProjectLogTail readLogTail(String path, {int count = 50}) => ProjectLogTail(
  lines: const [],
  path: path,
  sizeBytes: 0,
  modifiedAt: null,
  message: '웹에서는 로그를 읽을 수 없습니다.',
);

({ProjectLogTail run, ProjectLogTail errors}) readProjectLogs({
  required String mapDirectory,
  required String mapName,
  int count = 50,
}) => (
  run: readLogTail('$mapDirectory/$mapName.log', count: count),
  errors: readLogTail('$mapDirectory/$mapName.err.log', count: count),
);

String? truncateLog(String path) => '웹에서는 로그를 비울 수 없습니다.';
