import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/map_project_store.dart';

/// 지도 이름으로 프로젝트를 가르는 저장소의 계약을 확인한다.
///
/// 실제 MySQL이 필요하다. 다음처럼 켠다:
///   RUN_MYSQL_MAP_PROJECT_TEST=1 ROBOSAPIENS_DB_HOST=127.0.0.1 \
///   ROBOSAPIENS_DB_PORT=3306 ROBOSAPIENS_DB_USER=root \
///   ROBOSAPIENS_DB_NAME=robosapiens ROBOSAPIENS_DB_PASSWORD=robosapiens \
///   flutter test test/map_project_store_test.dart
void main() {
  final enabled = Platform.environment['RUN_MYSQL_MAP_PROJECT_TEST'] == '1';

  // 도면 원본이 전용 열까지 흘러가는지 보려면 실제 바이트가 있어야 한다.
  const drawingBytes = 512;
  final fakeImage = base64Encode(
    List<int>.generate(drawingBytes, (i) => (i * 7 + 3) % 256),
  );

  String payload(String mapName, int waypointCount) => jsonEncode({
    'format': 'robosapiens-map-project',
    'version': 2,
    'mapName': mapName,
    'drawing': {
      'name': '$mapName.png',
      'extension': 'png',
      'size': drawingBytes,
      'bytes': fakeImage,
      'pixelWidth': 2000,
      'pixelHeight': 1200,
    },
    'waypoints': [
      for (var i = 0; i < waypointCount; i++)
        {
          'point': [i * 3.0, i * 1.5],
          'name': i.isEven ? '홈${i ~/ 2 + 1}' : '대기${i ~/ 2 + 1}',
          'category': i.isEven ? '주차' : '대기',
        },
    ],
    'laneDirections': [
      for (var i = 0; i < waypointCount - 1; i++)
        {
          'start': [i * 3.0, i * 1.5],
          'end': [(i + 1) * 3.0, (i + 1) * 1.5],
          'direction': '양방향',
        },
    ],
  });

  group('맵 프로젝트 저장소', () {
    const first = '테스트 창고 A';
    const second = '테스트 창고 B';

    setUp(() async {
      await deleteMapProject(first);
      await deleteMapProject(second);
    });

    tearDown(() async {
      await deleteMapProject(first);
      await deleteMapProject(second);
    });

    test('지도 이름으로 프로젝트를 구분해 저장하고 되읽는다', () async {
      await saveMapProject(mapName: first, payloadJson: payload(first, 6));
      await saveMapProject(mapName: second, payloadJson: payload(second, 3));

      expect(await mapProjectExists(first), isTrue);
      expect(await mapProjectExists(second), isTrue);
      expect(await mapProjectExists('있을 리 없는 맵'), isFalse);

      final loaded =
          jsonDecode((await loadMapProject(first))!) as Map<String, dynamic>;
      expect(loaded['mapName'], first);
      expect((loaded['waypoints'] as List).length, 6);

      final summaries = {
        for (final project in await listMapProjects()) project.mapName: project,
      };
      expect(summaries[first]!.waypointCount, 6);
      expect(summaries[first]!.laneCount, 5);
      expect(summaries[second]!.waypointCount, 3);
      expect(summaries[second]!.laneCount, 2);
    });

    test('같은 이름으로 저장하면 새로 만들지 않고 그 프로젝트를 덮어쓴다', () async {
      await saveMapProject(mapName: first, payloadJson: payload(first, 6));
      await saveMapProject(mapName: first, payloadJson: payload(first, 2));

      // 전체 개수가 아니라 이 이름의 개수를 센다. 데이터베이스에는 다른 테스트
      // 파일과 사용자가 만든 프로젝트도 함께 있다.
      final mine = (await listMapProjects())
          .where((project) => project.mapName == first)
          .toList();
      expect(mine.length, 1, reason: '같은 이름이 두 벌 생기면 안 된다');
      // 조회용 사본은 증분이 아니라 통째로 다시 만든다. 줄어든 Waypoint 수가
      // 그대로 반영돼야 예전 지점이 남아 도는 일이 없다.
      expect(mine.single.waypointCount, 2);
      expect(mine.single.laneCount, 1);
    });

    test('중간 설정만 바꿔 다시 저장하면 그 값이 곧바로 반영된다', () async {
      String withSafety(double width) => jsonEncode({
        ...jsonDecode(payload(first, 3)) as Map<String, dynamic>,
        'robotSafety': {
          'widthMeters': width,
          'turningRadiusMeters': 0.15,
          'localizationMarginMeters': 0.05,
        },
      });

      await saveMapProject(mapName: first, payloadJson: withSafety(0.6));
      // 로봇 안전 기준 창에서 `기준 저장`을 누른 순간에 해당한다. 프로젝트
      // 저장을 따로 누르지 않아도 열린 프로젝트에 그대로 덮어써야 한다.
      await saveMapProject(mapName: first, payloadJson: withSafety(0.2));

      final back =
          jsonDecode((await loadMapProject(first))!) as Map<String, dynamic>;
      expect((back['robotSafety'] as Map)['widthMeters'], 0.2);
      expect(
        (await listMapProjects())
            .where((project) => project.mapName == first)
            .length,
        1,
        reason: '중간 저장이 프로젝트를 새로 만들면 안 된다',
      );
    });

    test('도면 원본과 building.yaml 을 함께 보관한다', () async {
      const yaml = 'name: "테스트 창고 A"\nlevels:\n  L1:\n    elevation: 0\n';
      await saveMapProject(
        mapName: first,
        payloadJson: payload(first, 4),
        buildingYaml: yaml,
        buildingYamlName: '테스트_창고_A.building.yaml',
      );

      expect(await loadMapProjectYaml(first), yaml);
      final summary = (await listMapProjects()).firstWhere(
        (project) => project.mapName == first,
      );
      expect(summary.hasBuildingYaml, isTrue);

      // 도면은 payload 안 base64 를 SQL 이 풀어 전용 열에 담는다. 관제가 JSON을
      // 파싱하지 않고 이미지만 꺼낼 수 있어야 한다.
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
              'SELECT COALESCE(LENGTH(drawing_bytes), -1), '
              'COALESCE(drawing_extension, \'\'), COALESCE(drawing_width, -1) '
              "FROM map_projects WHERE map_name = '$first'",
        ],
        environment: {
          ...Platform.environment,
          'MYSQL_PWD': Platform.environment['ROBOSAPIENS_DB_PASSWORD']!,
        },
      );
      expect(result.exitCode, 0, reason: result.stderr as String?);
      final columns = (result.stdout as String).trim().split(RegExp(r'\s+'));
      expect(int.parse(columns[0]), drawingBytes, reason: '도면 바이트 수 일치');
      expect(columns[1], 'png');
      expect(int.parse(columns[2]), 2000);
    });

    test('YAML 없이 저장하면 없음으로 남는다', () async {
      await saveMapProject(mapName: second, payloadJson: payload(second, 2));
      expect(await loadMapProjectYaml(second), isNull);
      final summary = (await listMapProjects()).firstWhere(
        (project) => project.mapName == second,
      );
      expect(summary.hasBuildingYaml, isFalse);
    });

    test('삭제한 프로젝트는 목록과 조회에서 사라진다', () async {
      await saveMapProject(mapName: first, payloadJson: payload(first, 4));
      await saveMapProject(mapName: second, payloadJson: payload(second, 4));

      await deleteMapProject(first);

      expect(await mapProjectExists(first), isFalse);
      expect(await loadMapProject(first), isNull);
      expect(await mapProjectExists(second), isTrue, reason: '다른 프로젝트는 남는다');
    });
  }, skip: enabled ? false : 'MySQL 맵 프로젝트 테스트 환경이 설정되지 않았습니다.');
}
