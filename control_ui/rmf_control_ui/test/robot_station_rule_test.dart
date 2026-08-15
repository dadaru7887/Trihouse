/// 로봇을 등록할 때 자리 Waypoint 를 반드시 고르게 하는 규칙.
///
/// 화면을 띄우지 않고 규칙만 확인한다. 위젯 테스트에는 맵이 없어 고를 자리도
/// 없으므로, 정작 중요한 "고를 자리가 있는데 안 골랐다" 를 거기서는 만들 수
/// 없다. 규칙을 화면에서 떼어 둔 이유가 이것이다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_project_config.dart';
import 'package:rmf_control_ui/robot_station_rule.dart';

void main() {
  RmfProjectRobot robot({
    required String id,
    String? station,
    RobotDataSource source = RobotDataSource.gazebo,
    RmfRobotKind kind = RmfRobotKind.mobile,
  }) => RmfProjectRobot(
    robotId: id,
    displayName: id,
    model: 'PINKY-GZ',
    kind: kind,
    dataSource: source,
    gzName: id.toLowerCase(),
    zones: const [],
    chargerWaypoint: station,
  );

  group('자리 Waypoint 규칙', () {
    test('Mock 로봇은 자리가 필요 없다', () {
      // Gazebo 에도 RMF 플릿에도 들어가지 않는다. 올릴 것이 없으니 올릴 자리도
      // 없다. 여기까지 막으면 맵을 그리기 전에는 아무것도 못 한다.
      final rule = checkStationRequirement(
        usesTopics: false,
        station: null,
        stationsAvailable: true,
      );
      expect(rule, StationRequirement.notNeeded);
      expect(canSaveRobot(rule), isTrue);
      expect(stationRequirementMessage(rule, '충전'), isNull);
    });

    test('고를 자리가 있는데 안 고르면 저장을 막는다', () {
      // project1 이 이 경우였다. 맵에 충전1 도 설비1 도 있었는데 둘 다 안 골라
      // 이동 로봇과 설치 로봇이 지도 원점에 겹쳤고, Gazebo 가 스폰 4초 만에
      // 죽었다.
      final rule = checkStationRequirement(
        usesTopics: true,
        station: null,
        stationsAvailable: true,
      );
      expect(rule, StationRequirement.missing);
      expect(canSaveRobot(rule), isFalse);
      expect(stationRequirementMessage(rule, '충전'), contains('자리를 골라야'));
    });

    test('빈 문자열은 고른 것이 아니다', () {
      final rule = checkStationRequirement(
        usesTopics: true,
        station: '   ',
        stationsAvailable: true,
      );
      expect(rule, StationRequirement.missing);
      expect(canSaveRobot(rule), isFalse);
    });

    test('골랐으면 통과한다', () {
      final rule = checkStationRequirement(
        usesTopics: true,
        station: '충전1',
        stationsAvailable: true,
      );
      expect(rule, StationRequirement.satisfied);
      expect(canSaveRobot(rule), isTrue);
      expect(stationRequirementMessage(rule, '충전'), isNull);
    });

    test('고를 자리가 하나도 없으면 막지 않고 알린다', () {
      // 맵을 아직 안 불러왔을 수 있다. 여기서 막으면 맵을 그리기 전에는 로봇을
      // 한 대도 등록할 수 없다. 대신 지금 저장하면 원점에 놓인다고 밝힌다.
      final rule = checkStationRequirement(
        usesTopics: true,
        station: null,
        stationsAvailable: false,
      );
      expect(rule, StationRequirement.unavailable);
      expect(canSaveRobot(rule), isTrue);
      final message = stationRequirementMessage(rule, '설비');
      expect(message, contains('설비'));
      expect(message, contains('원점'));
    });

    test('자리를 골랐으면 목록이 비어 있어도 통과한다', () {
      // 맵을 안 열어 목록이 비었을 뿐, 이미 고른 자리는 그대로다. 여기서
      // 되돌리면 멀쩡한 등록이 자리를 잃는다.
      final rule = checkStationRequirement(
        usesTopics: true,
        station: '충전1',
        stationsAvailable: false,
      );
      expect(rule, StationRequirement.satisfied);
      expect(canSaveRobot(rule), isTrue);
    });
  });

  group('배포 검사', () {
    test('자리 없는 Gazebo 로봇이 있으면 내보내지 않는다', () {
      // 등록에서 못 막은 것이 여기서 걸린다. 산출물이 만들어지는 순간 좌표가
      // 파일에 박히므로, 파일을 쓰기 전이 마지막 기회다.
      final robots = [
        robot(id: 'PK-01'),
        robot(id: 'OMX-01', kind: RmfRobotKind.workcell),
      ];
      expect(robotsMissingStation(robots).map((r) => r.robotId), [
        'PK-01',
        'OMX-01',
      ]);
      final message = deployBlockedMessage(robots);
      expect(message, isNotNull);
      // 어느 로봇이 왜 걸렸는지 이름으로 짚는다. 목록만 막고 이유를 안 적으면
      // 사람이 로봇을 하나씩 열어 봐야 한다.
      expect(message, contains('PK-01'));
      expect(message, contains('OMX-01'));
      expect(message, contains('충전 Waypoint 미지정'));
      expect(message, contains('설비 Waypoint 미지정'));
    });

    test('Mock 로봇은 자리가 없어도 막지 않는다', () {
      // 산출물에 올릴 것이 없다. 여기서 막으면 Mock 으로만 짜 둔 프로젝트를
      // 영영 내보낼 수 없다.
      final robots = [robot(id: 'PK-01', source: RobotDataSource.mock)];
      expect(robotsMissingStation(robots), isEmpty);
      expect(deployBlockedMessage(robots), isNull);
    });

    test('실물 로봇도 자리가 필요하다', () {
      // Gazebo 에 안 올라가도 RMF 는 charger 를 쓴다. 비어 있으면 fleet adapter
      // 가 복귀할 곳을 못 찾는다.
      final robots = [robot(id: 'PK-09', source: RobotDataSource.real)];
      expect(robotsMissingStation(robots).map((r) => r.robotId), ['PK-09']);
    });

    test('빈 문자열도 미지정으로 본다', () {
      expect(robotsMissingStation([robot(id: 'PK-01', station: '  ')]), [
        isA<RmfProjectRobot>(),
      ]);
    });

    test('다 골랐으면 통과한다', () {
      final robots = [
        robot(id: 'PK-01', station: '충전1'),
        robot(id: 'OMX-01', station: '설비1', kind: RmfRobotKind.workcell),
        robot(id: 'MOCK-01', source: RobotDataSource.mock),
      ];
      expect(robotsMissingStation(robots), isEmpty);
      expect(deployBlockedMessage(robots), isNull);
    });

    test('로봇이 없으면 막지 않는다', () {
      expect(deployBlockedMessage(const []), isNull);
    });
  });
}
