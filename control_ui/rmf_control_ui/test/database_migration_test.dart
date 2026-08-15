import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/database_migration_models.dart';

void main() {
  test('현재 버전 다음 migration을 최신까지 순서대로 고른다', () {
    expect(
      requiredMigrationTargets(
        current: 8,
        latest: 11,
        availableTargets: {4, 5, 6, 7, 8, 9, 10, 11},
      ),
      [9, 10, 11],
    );
  });

  test('중간 migration 파일이 빠지면 적용 전에 중단한다', () {
    expect(
      () => requiredMigrationTargets(
        current: 8,
        latest: 11,
        availableTargets: {9, 11},
      ),
      throwsStateError,
    );
  });

  test('프로그램보다 새로운 DB는 변경하지 않는다', () {
    expect(
      () => requiredMigrationTargets(
        current: 12,
        latest: 11,
        availableTargets: const {},
      ),
      throwsStateError,
    );
  });
}
