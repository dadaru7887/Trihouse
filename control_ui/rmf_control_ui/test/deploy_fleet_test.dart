/// 맵 배포가 남의 데모 플릿을 띄우지 않는지 지킨다.
///
/// 예전에는 배포 6단계가 `rmf_demos_fleet_adapter` 를 rmf_demos 의 **office 데모
/// 설정**(`tinyRobot_config.yaml`)으로 띄웠다. 이 프로젝트의 로봇도 이 맵의
/// 설정도 아니었고, 매번 이렇게 죽었다 —
///
///   AssertionError: Failed to parse config file [.../office/tinyRobot_config.yaml]
///
/// 그 위에 그 어댑터는 slotcar 전용이라, 토픽으로 도는 핑키에게는 상대가 없다.
/// 설령 떴어도 배차만 받고 로봇은 가만히 있는다.
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_project_config.dart';

void main() {
  late final String script = File(
    '../openrmf/scripts/deploy_map.sh',
  ).readAsStringSync();

  /// 주석은 빼고 실제로 도는 줄만 본다. 왜 안 띄우는지는 주석에 남겨 두므로,
  /// 파일 전체에서 이름을 찾으면 주석에 걸린다.
  late final String code = script
      .split('\n')
      .where((line) => !line.trimLeft().startsWith('#'))
      .join('\n');

  group('배포는 플릿을 띄우지 않는다', () {
    test('office 데모 설정을 쓰지 않는다', () {
      expect(code, isNot(contains('tinyRobot_config.yaml')));
      expect(code, isNot(contains('RMF_FLEET_CONFIG')));
    });

    test('slotcar 어댑터를 launch 하지 않는다', () {
      expect(code, isNot(contains('rmf_demos_fleet_adapter')));
      expect(code, isNot(contains('fleet_adapter.launch.xml')));
    });

    test('플릿 프로세스를 죽이지도 않는다', () {
      // 우리가 안 띄운 것을 배포가 죽이면, 아무도 다시 안 띄운다.
      expect(code, isNot(contains('fleet_manager')));
      expect(code, isNot(contains('fleet_adapter.pid')));
    });

    test('지도를 까는 일은 그대로 한다', () {
      // 배포가 하는 일 자체는 줄지 않았다.
      for (final step in const [
        'building_map_generator nav',
        'building_map_generator gazebo',
        'apply_wall_height',
        'building_map_server',
        '/get_building_map',
      ]) {
        expect(code, contains(step), reason: '배포에서 \$step 이 사라졌다');
      }
    });

    test('단계 수가 맞는다', () {
      // 6단계로 줄었다. 표시와 실제가 어긋나면 어디서 멈췄는지 못 짚는다.
      expect(code, contains(r'log_step() { echo "[$1/6] $2"; }'));
      for (var step = 1; step <= 6; step++) {
        expect(code, contains('log_step $step '), reason: '$step 단계가 없다');
      }
      expect(code, isNot(contains('log_step 7 ')));
    });
  });

  group('이미 떠 있는 것', () {
    test('다시 띄우라고 알린다', () {
      // 떠 있는 것은 뜰 때 읽은 nav graph 를 그대로 들고 있다. 지도만 바꾸면
      // 로봇은 옛 지도로 다니는데 오류는 안 난다.
      expect(script, contains('뜰 때 읽은 nav graph 를 그대로 씁니다'));
      expect(script, contains(r'stop_$MAP_NAME.sh'));
      expect(script, contains(r'run_$MAP_NAME.sh'));
    });
  });

  group('중지가 남은 토픽 다리를 쓸어낸다', () {
    // `/clock` 하나만 잇는 parameter_bridge 는 인자에 맵 경로가 없어 다른
    // 그물에 하나도 안 걸린다. 부모마저 systemd 로 바뀌면 프로세스 그룹으로도
    // 못 잡는다. 남으면 다음 실행에서 /clock 을 두 곳이 내고, 시각이 앞뒤로
    // 튀어 AMCL 이 위치추정을 잃는다 — 로봇은 멀쩡한데 가만히 선다.
    final stopScript = buildProjectStopScript(
      mapName: 'project1',
      mapDirectory: '/maps/project1',
    );

    test('parameter_bridge 를 이름으로 찾는다', () {
      expect(stopScript, contains('sweep_bridges'));
      expect(stopScript, contains('ros_gz_bridge/parameter_bridge'));
    });

    test('실제로 부른다', () {
      // 함수만 있고 안 부르면 아무 일도 안 일어난다.
      expect(
        RegExp(r'^sweep_bridges\s*$', multiLine: true).hasMatch(stopScript),
        isTrue,
      );
    });

    test('왜 잡아야 하는지 남긴다', () {
      expect(stopScript, contains('jump back in time'));
    });
  });
}
