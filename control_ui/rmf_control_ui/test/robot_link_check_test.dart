/// 로봇이 값을 보내기까지의 고리 판정.
///
/// Gazebo 로 등록했는데 앱 Mock 이라고 나올 때, 원인은 넷 중 하나인데 어느
/// 것인지 어디에도 안 보였다. 그때마다 로그를 뒤졌다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/robot_link_check.dart';

void main() {
  RobotLinkFacts facts({
    bool usesTopics = true,
    bool hasStation = true,
    String? stationName = '충전1',
    double? spawnX = 1.761,
    double? spawnY = -1.025,
    bool backendRunning = true,
    String? staleBackend,
    bool? nodesUp = true,
    bool? topicSeen = true,
    bool? topicFlowing = true,
    bool receiving = true,
    double? age = 0.2,
  }) => RobotLinkFacts(
    usesTopics: usesTopics,
    hasStation: hasStation,
    stationName: stationName,
    spawnX: spawnX,
    spawnY: spawnY,
    backendRunning: backendRunning,
    staleBackendDetail: staleBackend,
    nodesUp: nodesUp,
    topicSeen: topicSeen,
    topicFlowing: topicFlowing,
    receiving: receiving,
    lastPoseAgeSeconds: age,
  );

  group('다 이어져 있을 때', () {
    test('다섯 고리가 모두 ok', () {
      final links = checkRobotLinks(facts());
      expect(links, hasLength(6));
      expect(links.every((l) => l.state == RobotLinkState.ok), isTrue);
      expect(firstBrokenLink(links), isNull);
      expect(robotLinkSummary(links), '다 이어져 있습니다.');
    });

    test('자리 이름과 좌표를 함께 보여 준다', () {
      final links = checkRobotLinks(facts());
      expect(links.first.detail, '충전1 (1.761, -1.025)');
    });
  });

  group('처음 끊긴 곳 하나만 짚는다', () {
    test('자리가 없으면 그 뒤는 전부 모른다고 한다', () {
      // 순서가 있는 일이다. 자리가 없는데 "월드에 없다" 까지 함께 빨갛게
      // 만들면 엉뚱한 데를 고치게 된다.
      final links = checkRobotLinks(
        facts(hasStation: false, stationName: null, spawnX: null, spawnY: null),
      );
      expect(links[0].state, RobotLinkState.broken);
      expect(links[0].action, RobotLinkAction.chooseStation);
      expect(
        links.skip(1).every((l) => l.state == RobotLinkState.unknown),
        isTrue,
      );
      expect(links[1].detail, contains('앞이 끊겨'));
    });

    test('백엔드가 없으면 백엔드만 짚는다', () {
      final links = checkRobotLinks(facts(backendRunning: false));
      expect(links[0].state, RobotLinkState.ok);
      expect(links[1].state, RobotLinkState.broken);
      expect(links[1].action, RobotLinkAction.startBackend);
      expect(links[2].state, RobotLinkState.unknown);
    });

    test('이 로봇 노드가 없으면 이 로봇만 올리라고 한다', () {
      final links = checkRobotLinks(facts(nodesUp: false));
      expect(links[2].state, RobotLinkState.broken);
      expect(links[2].action, RobotLinkAction.spawnRobot);
    });

    test('이름은 있는데 값이 없으면 월드에 없는 것으로 본다', () {
      // 다리는 모델이 없어도 토픽을 만들어 놓는다. 이름이 보이는 것과 값이
      // 오는 것은 다르다 — 이 착각으로 하루를 썼다.
      final links = checkRobotLinks(facts(topicFlowing: false));
      expect(links[4].state, RobotLinkState.broken);
      expect(links[4].action, RobotLinkAction.spawnRobot);
      expect(links[4].detail, contains('이름은 있는데'));
    });

    test('토픽 이름조차 없으면 다리를 짚는다', () {
      final links = checkRobotLinks(facts(topicSeen: false));
      expect(links[3].state, RobotLinkState.broken);
      expect(links[3].action, RobotLinkAction.startBridge);
    });

    test('토픽은 있는데 앱만 조용하면 다시 구독하라고 한다', () {
      // 백엔드를 내렸다 올리면 `ros2 topic echo` 가 죽는데, 앱이 그것을 모른
      // 채로 있었다. 등록도 토픽도 멀쩡한데 화면만 조용했다.
      final links = checkRobotLinks(facts(receiving: false, age: null));
      expect(links[5].state, RobotLinkState.broken);
      expect(links[5].action, RobotLinkAction.resubscribe);
      expect(robotLinkSummary(links), contains('앱 수신에서 끊겼습니다'));
    });
  });

  group('모르는 것은 모른다고 한다', () {
    test('확인 못 한 고리를 끊겼다고 하지 않는다', () {
      final links = checkRobotLinks(facts(nodesUp: null));
      expect(links[2].state, RobotLinkState.unknown);
      expect(firstBrokenLink(links), isNull);
      expect(robotLinkSummary(links), contains('아직 다 확인하지 못했습니다'));
    });
  });

  group('Mock 로봇', () {
    test('볼 고리가 없다고 한 줄로 끝낸다', () {
      final links = checkRobotLinks(facts(usesTopics: false));
      expect(links, hasLength(1));
      expect(links.single.state, RobotLinkState.ok);
      expect(links.single.detail, contains('토픽을 쓰지 않으므로'));
    });
  });

  group('버튼', () {
    test('누르면 무엇이 일어나는지 적혀 있다', () {
      for (final action in RobotLinkAction.values) {
        expect(action.label, isNotEmpty);
        expect(action.detail, isNotEmpty);
      }
      expect(RobotLinkAction.spawnRobot.detail, contains('이미 떠 있는 월드에'));
    });
  });

  group('옛날 설정으로 뜬 백엔드', () {
    test('떠 있어도 끊긴 것으로 본다', () {
      // ros2 launch 는 띄울 때 한 번만 파일을 읽는다. 로봇 0대이던 시절의
      // Gazebo 가 34분째 돌면서, 토픽 이름만 있고 값은 하나도 안 왔다.
      final links = checkRobotLinks(
        facts(staleBackend: '06:05 에 뜬 월드입니다. 배포는 06:39'),
      );
      expect(links[1].state, RobotLinkState.broken);
      expect(links[1].detail, contains('06:39'));
      expect(links[1].action, RobotLinkAction.startBackend);
      // 뒤는 볼 수 없다. 엉뚱한 데를 고치게 하면 안 된다.
      expect(links[2].state, RobotLinkState.unknown);
    });

    test('버튼 이름이 다시 띄우라고 말한다', () {
      expect(RobotLinkAction.startBackend.label, '백엔드 다시 띄우기');
    });
  });
}
