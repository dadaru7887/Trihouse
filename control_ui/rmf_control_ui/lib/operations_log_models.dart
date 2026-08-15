/// 운영 분석이 읽는 기록의 모양.
///
/// 설정을 언제 바꿨는지와 그날 무슨 일이 있었는지를 **같은 시간축**에 놓는다.
/// 어제까지 되던 것이 오늘 안 되면, 그 사이에 무엇을 바꿨는지 함께 봐야 한다.
library;

/// 기록의 갈래. 화면에서 색과 이름을 여기서 가져간다.
enum OperationLogKind {
  /// 설정을 바꾼 기록 — 로봇 등록, 플릿 설정, 생성 파일.
  setting,

  /// 작업 — 만들어지고 배차되고 끝난 것.
  task,

  /// 주문.
  order,

  /// 시스템 사건 로그.
  event,

  /// 이상 상황.
  incident,

  /// 재고 이동.
  stock;

  String get label => switch (this) {
    OperationLogKind.setting => '설정',
    OperationLogKind.task => '작업',
    OperationLogKind.order => '주문',
    OperationLogKind.event => '사건',
    OperationLogKind.incident => '이상',
    OperationLogKind.stock => '재고',
  };

  static OperationLogKind parse(String value) => switch (value) {
    'setting' => OperationLogKind.setting,
    'task' => OperationLogKind.task,
    'order' => OperationLogKind.order,
    'incident' => OperationLogKind.incident,
    'stock' => OperationLogKind.stock,
    _ => OperationLogKind.event,
  };
}

/// 한 달치 요약. 달을 고르는 목록에 쓴다.
class OperationMonth {
  const OperationMonth({
    required this.year,
    required this.month,
    required this.counts,
  });

  final int year;
  final int month;

  /// 갈래별 건수.
  final Map<OperationLogKind, int> counts;

  int get total => counts.values.fold(0, (sum, n) => sum + n);

  String get label => '$year년 $month월';

  /// 정렬·비교에 쓰는 키. `2026-08`.
  String get key => '$year-${month.toString().padLeft(2, '0')}';
}

/// 하루치 요약. 달력 띠에 쓴다.
class OperationDay {
  const OperationDay({required this.date, required this.counts});

  final DateTime date;
  final Map<OperationLogKind, int> counts;

  int get total => counts.values.fold(0, (sum, n) => sum + n);
}

/// 기록 한 줄.
class OperationEntry {
  const OperationEntry({
    required this.at,
    required this.kind,
    required this.title,
    required this.detail,
    this.severity,
    this.project,
  });

  final DateTime at;
  final OperationLogKind kind;
  final String title;
  final String detail;

  /// 사건·이상의 등급. 없으면 null.
  final String? severity;

  /// 설정 기록이 속한 맵 프로젝트. 운영 기록은 null.
  final String? project;

  String get timeLabel =>
      '${at.hour.toString().padLeft(2, '0')}:'
      '${at.minute.toString().padLeft(2, '0')}';
}

/// 기록 제목을 사람이 읽는 말로 바꾼다.
///
/// 설정 기록은 `category\taction\ttarget` 으로 실려 온다. 표에 든 값을 그대로
/// 보여 주면 `robot·added·PK-01` 처럼 기계 말이 된다.
String formatEntryTitle(OperationLogKind kind, String raw) {
  if (kind != OperationLogKind.setting) return raw;
  final parts = raw.split('\t');
  if (parts.length < 3) return raw;
  final change = MapProjectChange(
    category: parts[0],
    action: parts[1],
    target: parts[2],
    summary: '',
  );
  return '${change.categoryLabel} ${change.actionLabel} · ${change.target}';
}

/// 저장할 설정 변경 한 건.
class MapProjectChange {
  const MapProjectChange({
    required this.category,
    required this.action,
    required this.target,
    required this.summary,
  });

  /// `robot` · `fleet` · `file` · `project`
  final String category;

  /// `added` · `changed` · `removed`
  final String action;
  final String target;
  final String summary;

  String get actionLabel => switch (action) {
    'added' => '추가',
    'removed' => '삭제',
    _ => '변경',
  };

  String get categoryLabel => switch (category) {
    'robot' => '로봇 등록',
    'fleet' => '플릿 설정',
    'file' => '설정 파일',
    _ => '프로젝트',
  };
}
