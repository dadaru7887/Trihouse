class DatabaseMigrationResult {
  const DatabaseMigrationResult({
    required this.fromVersion,
    required this.toVersion,
    required this.applied,
    this.backupPath,
  });
  final int? fromVersion;
  final int toVersion;
  final List<String> applied;
  final String? backupPath;
  bool get changed => applied.isNotEmpty;
}

List<int> requiredMigrationTargets({
  required int current,
  required int latest,
  required Set<int> availableTargets,
}) {
  if (current > latest) {
    throw StateError('DB 스키마 v$current은 프로그램 지원 버전 v$latest보다 새롭습니다.');
  }
  final targets = <int>[];
  for (var target = current + 1; target <= latest; target++) {
    if (!availableTargets.contains(target)) {
      throw StateError('v${target - 1}→v$target migration SQL이 없습니다.');
    }
    targets.add(target);
  }
  return targets;
}
