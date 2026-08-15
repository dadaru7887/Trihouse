import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_project_config.dart';

/// launch 가 어느 지도를 띄우는지.
///
/// 예전에는 `nav2_map/<맵>.yaml` 을 못박고 있었다. 그래서 SLAM 지도를 올려도
/// `map_server` 는 계속 도면 지도를 띄웠고, 올리기가 아무 일도 하지 않았다.
void main() {
  const robots = <RmfProjectRobot>[];

  group('Nav2 launch 의 지도', () {
    test('기본은 도면에서 만든 지도다', () {
      final xml = buildProjectNav2LaunchXml(
        mapName: 'gwanghee',
        robots: robots,
      );
      expect(xml, contains('nav2_map/gwanghee.yaml'));
      expect(xml, isNot(contains('gwanghee_slam.yaml')));
      expect(xml, contains('도면에서 만든 것이라 원점이 RMF 월드에 정확히 맞는다'));
    });

    test('SLAM 지도를 고르면 그것을 띄운다', () {
      final xml = buildProjectNav2LaunchXml(
        mapName: 'gwanghee',
        robots: robots,
        mapYamlName: 'gwanghee_slam.yaml',
      );
      expect(xml, contains('nav2_map/gwanghee_slam.yaml'));
      expect(xml, isNot(contains('nav2_map/gwanghee.yaml')));
      // 원점이 사람 손을 거쳤다는 것을 파일에 남긴다.
      expect(xml, contains('SLAM 으로 뜬 지도다'));
      expect(xml, contains('원점을 사람이 RMF 월드에 맞춰'));
    });

    test('빈 이름은 도면 지도로 떨어진다', () {
      // 실수로 빈 문자열이 흘러와도 지도 없이 뜨지 않게 한다.
      for (final name in ['', '   ']) {
        final xml = buildProjectNav2LaunchXml(
          mapName: 'gwanghee',
          robots: robots,
          mapYamlName: name,
        );
        expect(xml, contains('nav2_map/gwanghee.yaml'));
      }
    });
  });

  group('선택을 프로젝트에 저장한다', () {
    late final String source = File('lib/main.dart').readAsStringSync();

    test('payload 에 들어간다', () {
      // 안 저장하면 앱을 다시 켤 때 조용히 도면 지도로 돌아간다.
      expect(source, contains("'useSlamMap': _useSlamMap"));
    });

    test('프로젝트를 열 때 되살린다', () {
      expect(source, contains("data['useSlamMap'] as bool? ?? false"));
    });

    test('launch 를 만들 때 넘긴다', () {
      expect(
        source,
        contains('mapYamlName: _useSlamMap ? slamYamlName(mapName) : null'),
      );
    });

    test('프로젝트를 바꾸면 앞 프로젝트의 SLAM 지도를 내린다', () {
      // 남겨 두면 다른 창고의 지도를 보며 원점을 맞추게 된다.
      final start = source.indexOf('Future<void> _switchOpenProject');
      final body = source.substring(start, start + 1200);
      expect(body, contains('_slamMap = null'));
      expect(body, contains('_loadStoredSlam(mapName)'));
    });
  });
}
