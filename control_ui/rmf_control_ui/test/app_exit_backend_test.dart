import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('창 X와 Ctrl+X가 같은 종료 훅에서 모든 백엔드를 정지한다', () {
    final source = File('lib/main.dart').readAsStringSync();
    final handler = source.indexOf(
      'Future<ui.AppExitResponse> _handleExitRequest()',
    );
    final shortcut = source.indexOf(
      'SingleActivator(LogicalKeyboardKey.keyX, control: true)',
    );

    expect(handler, greaterThanOrEqualTo(0));
    expect(source, contains('onExitRequested: _handleExitRequest'));
    expect(shortcut, greaterThanOrEqualTo(0));
    expect(source, contains('exitApplication(ui.AppExitType.cancelable)'));
    expect(source, contains('await findRunningProjects()'));
    expect(source, contains('await stopProject(mapName)'));
    expect(source, contains('ProcessSignal.sigint.watch()'));
    expect(source, contains('await _handleExitRequest()'));
    expect(source, contains('exit(0)'));
  });
}
