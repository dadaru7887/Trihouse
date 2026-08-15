import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('로봇 등록을 다시 저장해도 별도 Spawn 위치를 충전소로 덮어쓰지 않는다', () {
    final source = File('lib/main.dart').readAsStringSync();
    final editor = source.indexOf('Future<RmfProjectRobot?> _editFleetRobot');
    final end = source.indexOf('Future<void> _registerFleetRobot', editor);
    final body = source.substring(editor, end);

    expect(body, contains('final stationChanged ='));
    expect(body, contains('charger != existing.chargerWaypoint'));
    expect(body, contains('existing?.spawnX ?? spawn?.dx'));
    expect(body, contains('existing?.spawnY ?? spawn?.dy'));
  });
}
