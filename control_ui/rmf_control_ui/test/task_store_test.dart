import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/map_project_store.dart';
import 'package:rmf_control_ui/task_store.dart';

void main() {
  final enabled = Platform.environment['RUN_MYSQL_INTEGRATION_TEST'] == '1';

  // 작업은 맵 프로젝트에 속하므로 먼저 담을 프로젝트가 있어야 한다.
  const projectA = '작업테스트 창고 A';
  const projectB = '작업테스트 창고 B';

  String mapPayload(String mapName) => jsonEncode({
    'format': 'robosapiens-map-project',
    'version': 2,
    'mapName': mapName,
    'waypoints': const <Object?>[],
    'laneDirections': const <Object?>[],
  });

  Future<String> historyOf(String project, String taskId) async {
    final result = await Process.run(
      'mysql',
      [
        '--batch',
        '--skip-column-names',
        '--host=${Platform.environment['ROBOSAPIENS_DB_HOST']}',
        '--port=${Platform.environment['ROBOSAPIENS_DB_PORT']}',
        '--user=${Platform.environment['ROBOSAPIENS_DB_USER']}',
        Platform.environment['ROBOSAPIENS_DB_NAME']!,
        '--execute='
            'SELECT GROUP_CONCAT(h.event_type ORDER BY h.id) '
            'FROM rmf_ui_task_history h '
            'JOIN map_projects p ON p.id = h.map_project_id '
            "WHERE p.map_name = '$project' AND h.task_id = '$taskId'",
      ],
      environment: {
        ...Platform.environment,
        'MYSQL_PWD': Platform.environment['ROBOSAPIENS_DB_PASSWORD']!,
      },
    );
    expect(result.exitCode, 0, reason: result.stderr as String?);
    return (result.stdout as String).trim();
  }

  group('맵 프로젝트별 작업 저장소', () {
    setUp(() async {
      for (final name in [projectA, projectB]) {
        await deleteMapProject(name);
        await saveMapProject(mapName: name, payloadJson: mapPayload(name));
      }
    });

    tearDown(() async {
      // 프로젝트를 지우면 그 작업과 이력도 FK CASCADE 로 함께 사라진다.
      await deleteMapProject(projectA);
      await deleteMapProject(projectB);
    });

    test('작업 목록과 생성·수정·삭제 이력을 프로젝트 안에 저장한다', () async {
      const created = [
        {
          'id': 'TASK-TEST-001',
          'name': '통합 테스트',
          'status': 'queued',
          'createdAt': '2026-08-07T12:00:00.000000',
          'steps': <Object?>[],
        },
      ];
      await saveTasks(projectA, jsonEncode(created));
      final loaded =
          jsonDecode((await loadSavedTasks(projectA))!) as List<dynamic>;
      expect(loaded.single['name'], '통합 테스트');

      final updated = [
        {...created.single, 'name': '수정된 작업', 'status': 'completed'},
      ];
      await saveTasks(projectA, jsonEncode(updated));
      await saveTasks(projectA, '[]');

      expect(
        await historyOf(projectA, 'TASK-TEST-001'),
        'created,status_changed,deleted',
      );
    });

    test('다른 프로젝트의 작업은 서로 보이지 않는다', () async {
      Object task(String id, String name) => {
        'id': id,
        'name': name,
        'status': 'queued',
        'createdAt': '2026-08-07T12:00:00.000000',
        'steps': const <Object?>[],
      };

      // 두 맵이 같은 작업 번호를 쓰는 경우까지 본다. 번호는 앱이 프로젝트
      // 안에서 매기므로 실제로 겹칠 수 있다.
      await saveTasks(projectA, jsonEncode([task('TASK-0001', 'A동 작업')]));
      await saveTasks(projectB, jsonEncode([task('TASK-0001', 'B동 작업')]));

      final a = jsonDecode((await loadSavedTasks(projectA))!) as List<dynamic>;
      final b = jsonDecode((await loadSavedTasks(projectB))!) as List<dynamic>;
      expect(a.length, 1);
      expect(b.length, 1);
      expect(a.single['name'], 'A동 작업');
      expect(b.single['name'], 'B동 작업');

      // 한쪽을 비워도 다른 쪽은 남는다.
      await saveTasks(projectA, '[]');
      expect(
        (jsonDecode((await loadSavedTasks(projectA))!) as List<dynamic>),
        isEmpty,
      );
      expect(
        (jsonDecode((await loadSavedTasks(projectB))!) as List<dynamic>)
            .single['name'],
        'B동 작업',
      );
    });

    test('프로젝트를 지우면 그 작업도 함께 사라진다', () async {
      await saveTasks(
        projectA,
        jsonEncode([
          {
            'id': 'TASK-0009',
            'name': '삭제될 작업',
            'status': 'queued',
            'createdAt': '2026-08-07T12:00:00.000000',
            'steps': <Object?>[],
          },
        ]),
      );
      expect(
        (jsonDecode((await loadSavedTasks(projectA))!) as List<dynamic>).length,
        1,
      );

      await deleteMapProject(projectA);

      // 프로젝트가 없으면 붙어 있던 작업도 조회되지 않는다.
      expect(
        (jsonDecode((await loadSavedTasks(projectA))!) as List<dynamic>),
        isEmpty,
      );
    });
  }, skip: enabled ? false : 'MySQL 통합 테스트 환경이 설정되지 않았습니다.');
}
