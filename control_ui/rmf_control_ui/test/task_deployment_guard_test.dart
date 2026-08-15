import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('로봇 작업 생성 전에 현재 프로젝트의 배포 여부를 확인한다', () {
    final source = File('lib/main.dart').readAsStringSync();
    final createTask = source.indexOf('Future<void> _createMockTask()');
    final editor = source.indexOf(
      'showMovableDialog<_TaskEditorResult>',
      createTask,
    );
    final guard = source.indexOf(
      'if (!_isDeployed && !loadedOperationalMap)',
      createTask,
    );

    expect(createTask, greaterThanOrEqualTo(0));
    expect(guard, greaterThan(createTask));
    expect(guard, lessThan(editor));
    expect(source, contains('먼저 맵을 배포하세요'));
    expect(source, contains('맵 관리에서 `배포하기`를 완료하세요.'));
  });
}
