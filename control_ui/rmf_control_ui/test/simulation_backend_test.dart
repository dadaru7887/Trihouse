import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_project_config.dart';
import 'package:rmf_control_ui/simulation_backend.dart';

void main() {
  test('저장값을 실행 백엔드로 복원한다', () {
    expect(SimulationBackend.parse('gazebo'), SimulationBackend.gazebo);
    expect(SimulationBackend.parse('isaac_sim'), SimulationBackend.isaacSim);
    expect(SimulationBackend.parse('none'), SimulationBackend.none);
    expect(SimulationBackend.parse('unknown'), SimulationBackend.gazebo);
  });

  test('실행 스크립트가 Gazebo Isaac Sim 없음으로 분기한다', () async {
    final script = buildProjectRunScript(
      mapName: 'demo',
      mapDirectory: '/maps/demo',
    );
    expect(script, contains(r'SIM_BACKEND="${SIM_BACKEND:-gazebo}"'));
    expect(script, contains('gazebo|isaac_sim|none'));
    expect(script, contains(r'$MAP_DIR/isaac/start_demo.py'));
    expect(script, contains(r'$MAP_DIR/isaac/demo.usd'));
    expect(script, contains('물리 시뮬레이터 없이 RMF/RViz만 시작합니다.'));
    final directory = Directory.systemTemp.createTempSync('sim_backend_script');
    addTearDown(() => directory.deleteSync(recursive: true));
    final file = File('${directory.path}/run_demo.sh')
      ..writeAsStringSync(script);
    final syntax = await Process.run('bash', ['-n', file.path]);
    expect(syntax.exitCode, 0, reason: syntax.stderr.toString());
  });

  test('schema v12와 순차 migration이 함께 있다', () {
    final schema = File('../db/schema.sql').readAsStringSync();
    final migration = File('../db/migrate_v11_to_v12.sql').readAsStringSync();
    expect(schema, contains('VALUES (1, 12, NOW(6))'));
    expect(schema, contains('map_project_simulation_settings'));
    expect(schema, contains('map_project_robot_simulation'));
    expect(migration, contains('VALUES (1, 12, NOW(6))'));
  });
}
