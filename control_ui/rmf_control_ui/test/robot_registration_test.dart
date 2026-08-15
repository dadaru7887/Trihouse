import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/main.dart';

/// `static const _menuXxx = N;` 에서 N 을 읽는다.
int _menuSlot(String source, String name) {
  final match = RegExp('static const $name = (\\d+);').firstMatch(source);
  if (match == null) throw StateError('$name 선언이 없다');
  return int.parse(match.group(1)!);
}

/// 상단 제목 목록을 차례대로 읽는다. 자리 번호로 바로 찾을 수 있게 한다.
List<String> _menuTitles(String source) {
  final start = source.indexOf('title: const [');
  final end = source.indexOf('][_selectedMenu]', start);
  return RegExp(
    "'([^']+)'",
  ).allMatches(source.substring(start, end)).map((m) => m.group(1)!).toList();
}

/// 로봇 메뉴에서 로봇을 등록하고, 등록한 로봇만 스폰되는지 확인한다.
///
/// 등록은 원래 맵 관리의 RMF 설정 창 안에만 있었다. 로봇을 다루러 온 사람이
/// 먼저 찾는 곳은 로봇 메뉴인데 거기에는 스폰 버튼만 있었고, 그 스폰은 등록과
/// 아무 관계 없이 이름만 받아 만들었다. 그래서 Gazebo 에 올라가는 로봇과 지도에
/// 보이는 로봇이 서로 달랐다.
void main() {
  Future<void> openRobotMenu(WidgetTester tester) async {
    tester.view.physicalSize = const Size(1600, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const RmfControlApp());
    await tester.tap(find.text('로봇'));
    await tester.pumpAndSettle();
  }

  testWidgets('로봇 운영 맨 위에 차례가 보인다', (tester) async {
    // 순서가 있는 일인데 그 차례가 화면 어디에도 없었다. `ros2 launch` 는 띄울
    // 때 파일을 한 번만 읽으므로, 백엔드를 먼저 띄우면 그 뒤에 등록한 로봇은
    // 월드에 없다 — 오류도 안 나고 토픽 이름만 보인다.
    await openRobotMenu(tester);

    expect(find.text('로봇을 띄우는 차례'), findsOneWidget);
    expect(find.text('맵 불러오기'), findsOneWidget);
    expect(find.text('로봇 등록하기'), findsOneWidget);
    expect(find.text('RMF 설정 내보내기'), findsOneWidget);
    expect(find.text('백엔드 실행'), findsOneWidget);
    // 왜 순서를 지켜야 하는지도 함께 적는다. 차례만 있으면 건너뛴다.
    expect(find.textContaining('파일을 한 번만 읽습니다'), findsOneWidget);

    // 아직 아무것도 안 했으므로 첫 칸을 짚는다.
    expect(find.textContaining('지금 할 일 — 맵 불러오기'), findsOneWidget);
  });

  testWidgets('로봇을 등록하면 차례가 다음 칸을 짚는다', (tester) async {
    await openRobotMenu(tester);
    await tester.tap(find.text('로봇 등록'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('저장'));
    await tester.pumpAndSettle();

    // 등록 칸은 끝났다. 맵이 없는 화면이라 첫 칸이 아직 남아 있으므로 그것을
    // 짚는다 — 지금 할 일은 늘 못 한 것 중 맨 앞이다.
    expect(find.textContaining('1대'), findsWidgets);
    expect(find.textContaining('지금 할 일 — 맵 불러오기'), findsOneWidget);
  });

  testWidgets('로봇 메뉴에 로봇 등록이 있다', (tester) async {
    await openRobotMenu(tester);

    expect(find.textContaining('로봇 등록 ·'), findsOneWidget);
    expect(find.text('로봇 등록'), findsOneWidget);
    expect(find.text('충전 Waypoint에서 만들기'), findsOneWidget);
    expect(find.textContaining('등록된 로봇이 없습니다'), findsOneWidget);
  });

  testWidgets('등록하기 전에는 Spawn 을 누를 수 없다', (tester) async {
    await openRobotMenu(tester);

    // 눌러도 아무 일이 없으면 왜 안 되는지 알 수 없다. 버튼을 잠그고
    // 툴팁으로 무엇을 먼저 해야 하는지 알린다.
    final spawn = tester.widget<FilledButton>(
      find.ancestor(
        of: find.text('로봇 Spawn'),
        matching: find.byType(FilledButton),
      ),
    );
    expect(spawn.onPressed, isNull);
    expect(
      tester
          .widget<Tooltip>(
            find.ancestor(
              of: find.text('로봇 Spawn'),
              matching: find.byType(Tooltip),
            ),
          )
          .message,
      contains('등록'),
    );
  });

  testWidgets('충전 Waypoint가 없으면 왜 만들 수 없는지 알린다', (tester) async {
    await openRobotMenu(tester);

    await tester.tap(find.text('충전 Waypoint에서 만들기'));
    await tester.pumpAndSettle();

    expect(find.textContaining('충전 카테고리 Waypoint가 없습니다'), findsOneWidget);
    expect(find.text('충전 Waypoint에서 만들기'), findsWidgets);
  });

  testWidgets('등록하면 목록에 나오고 Spawn 이 열린다', (tester) async {
    await openRobotMenu(tester);

    await tester.tap(find.text('로봇 등록'));
    await tester.pumpAndSettle();
    expect(find.text('이동 로봇'), findsOneWidget);
    expect(find.text('설치 로봇'), findsOneWidget);
    // 값이 어디서 오는지도 등록할 때 정한다.
    expect(find.text('값의 출처'), findsOneWidget);

    // 기본값이 채워져 있으므로 그대로 저장한다.
    await tester.tap(find.text('저장'));
    await tester.pumpAndSettle();

    expect(find.text('로봇 등록 · 1대'), findsOneWidget);
    expect(find.textContaining('pinky_01 · PK-01'), findsWidgets);
    // 아직 지도에 올리지는 않았다.
    expect(find.text('대기'), findsOneWidget);

    final spawn = tester.widget<FilledButton>(
      find.ancestor(
        of: find.text('로봇 Spawn'),
        matching: find.byType(FilledButton),
      ),
    );
    expect(spawn.onPressed, isNotNull);
  });

  testWidgets('ID 를 고치면 등록 카드가 새 ID 로 바뀐다', (tester) async {
    // 지도에 올린 로봇도 작업도 등록에서 온 ID 를 들고 있다. 등록만 고치고
    // 나머지가 옛 ID 로 남으면 서로를 못 찾아, 작업이 RMF 로 안 가고 앱
    // 안에서만 돈다 — 화면에서는 일하는 것처럼 보이는데 로봇은 가만히 있는다.
    await openRobotMenu(tester);
    await tester.tap(find.text('로봇 등록'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('저장'));
    await tester.pumpAndSettle();
    expect(find.textContaining('pinky_01 · PK-01'), findsWidgets);

    await tester.tap(find.byTooltip('수정').first);
    await tester.pumpAndSettle();
    await tester.enterText(
      find.ancestor(of: find.text('로봇 ID'), matching: find.byType(TextField)),
      'PK_09',
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('저장'));
    await tester.pumpAndSettle();

    // 등록 카드가 새 ID 로 바뀐다. 정확히 맞춰 본다 — 운영 로그에는
    // `로봇 등록 적용 · pinky_01 · PK-01` 가 그대로 남아야 한다. 지나간 기록을
    // 나중에 고쳐 쓰면 무슨 일이 있었는지 알 수 없다.
    expect(find.text('PK_09 · PK-01'), findsWidgets);
    expect(find.text('pinky_01 · PK-01'), findsNothing);
    expect(find.textContaining('로봇 등록 적용 · pinky_01'), findsWidgets);
  });

  testWidgets('ID 칸에 하이픈을 치면 밑줄로 바뀐다', (tester) async {
    // RMF 가 ID 로 토픽을 만드는데 하이픈은 ROS 2 토픽 이름에 못 들어간다.
    // 막기만 하면 사람이 무엇을 쳐야 하는지 알아내야 하므로 그 자리에서 고친다.
    await openRobotMenu(tester);
    await tester.tap(find.text('로봇 등록'));
    await tester.pumpAndSettle();

    final idField = find.ancestor(
      of: find.text('로봇 ID'),
      matching: find.byType(TextField),
    );
    await tester.enterText(idField, 'PK-07');
    await tester.pumpAndSettle();

    expect(tester.widget<TextField>(idField).controller!.text, 'PK_07');
  });

  testWidgets('등록은 됐지만 맵이 없으면 무엇이 없는지 팝업으로 알린다', (tester) async {
    await openRobotMenu(tester);
    await tester.tap(find.text('로봇 등록').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('저장'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('로봇 Spawn'));
    await tester.pumpAndSettle();

    // 예전에는 대시보드에만 표시되는 경고로 처리해서, 로봇 메뉴에서 누르면
    // 아무 일도 일어나지 않는 것처럼 보였다.
    expect(find.text('로봇 Spawn'), findsWidgets);
    expect(find.textContaining('올릴 Waypoint가 없습니다'), findsOneWidget);
    // 등록은 이미 했으므로 등록하라는 말이 아니어야 한다.
    expect(find.textContaining('등록된 로봇이 없습니다'), findsNothing);
  });

  testWidgets('등록을 지우면 무엇이 함께 사라지는지 알린다', (tester) async {
    await openRobotMenu(tester);
    await tester.tap(find.text('로봇 등록').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('저장'));
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('등록 해제').first);
    await tester.pumpAndSettle();

    expect(find.text('로봇 등록 해제'), findsOneWidget);
    expect(
      find.textContaining('Gazebo 에 올라오지 않고'),
      findsOneWidget,
      reason: '등록을 지우면 실행에서 빠진다는 것을 먼저 알려야 한다',
    );

    await tester.tap(find.text('등록 해제'));
    await tester.pumpAndSettle();
    expect(find.text('로봇 등록 · 0대'), findsOneWidget);
  });

  testWidgets('설치 로봇을 고르면 자리와 모델이 함께 바뀐다', (tester) async {
    await openRobotMenu(tester);
    await tester.tap(find.text('로봇 등록'));
    await tester.pumpAndSettle();

    // 이동 로봇일 때는 충전 Waypoint 에 서고 3온도 구획 자격이 있다.
    expect(find.text('충전 Waypoint'), findsOneWidget);
    expect(find.text('ambient'), findsOneWidget);

    await tester.tap(find.text('설치 로봇'));
    await tester.pumpAndSettle();

    // 설치 로봇은 설비 자리에 붙고 배차를 받지 않는다.
    expect(find.text('설비 Waypoint'), findsOneWidget);
    expect(find.text('충전 Waypoint'), findsNothing);
    expect(
      find.text('ambient'),
      findsNothing,
      reason: '배차 대상이 아니므로 구획 자격이 필요 없다',
    );
    expect(find.textContaining('fleet adapter 에 들어가지 않습니다'), findsOneWidget);
    // 모델은 open_manipulator_description 에 있는 것 중에서 고른다.
    expect(find.text('open_manipulator_x'), findsOneWidget);
  });

  testWidgets('설치 로봇은 등록되어도 이동 로봇과 구분된다', (tester) async {
    await openRobotMenu(tester);
    await tester.tap(find.text('로봇 등록'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('설치 로봇'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('저장'));
    await tester.pumpAndSettle();

    expect(find.text('로봇 등록 · 1대'), findsOneWidget);
    expect(find.textContaining('omx_01 · OMX-01'), findsWidgets);
    expect(find.textContaining('open_manipulator_x'), findsWidgets);
  });

  testWidgets('백엔드가 없으면 띄우는 버튼을 보여 준다', (tester) async {
    await openRobotMenu(tester);
    // 확인이 끝날 때까지 기다린다.
    await tester.pump(const Duration(seconds: 13));
    await tester.pumpAndSettle();

    // 내리는 버튼만 있고 띄우는 버튼이 없으면, 없다는 것만 알려주고 어떻게
    // 하라는 말은 없는 셈이 된다.
    expect(find.text('백엔드 띄우기'), findsOneWidget);
    expect(find.text('백엔드 중지'), findsNothing);

    // 프로젝트가 없으면 띄울 수 없다. 왜인지 툴팁으로 알린다.
    final start = tester.widget<FilledButton>(
      find.ancestor(
        of: find.text('백엔드 띄우기'),
        matching: find.byType(FilledButton),
      ),
    );
    expect(start.onPressed, isNull);
    expect(
      tester
          .widget<Tooltip>(
            find.ancestor(
              of: find.text('백엔드 띄우기'),
              matching: find.byType(Tooltip),
            ),
          )
          .message,
      contains('맵 프로젝트'),
    );
  });

  testWidgets('출처는 로봇마다 정하고 화면 전체 설정은 없다', (tester) async {
    await openRobotMenu(tester);
    // 예전에는 화면 위에 `로봇 실행 방식` 하나가 있었다. 그러면 실물 두 대에
    // Gazebo 한 대 같은 구성을 담을 수 없다.
    expect(find.text('로봇 실행 방식'), findsNothing);

    await tester.tap(find.text('로봇 등록'));
    await tester.pumpAndSettle();
    expect(find.text('값의 출처'), findsOneWidget);
    // 등록만 하고 아무것도 안 고른 로봇을 실행에 밀어 넣으면 안 되므로
    // 기본값은 앱 Mock 이다.
    expect(find.text('앱 Mock 데이터'), findsWidgets);
    expect(find.textContaining('fleet adapter 에도 Gazebo 에도'), findsOneWidget);

    await tester.tap(find.text('저장'));
    await tester.pumpAndSettle();
    // 등록 카드와 위쪽 요약 모두 출처를 드러낸다.
    expect(find.textContaining('앱 Mock 데이터'), findsWidgets);
    expect(find.textContaining('앱 Mock 1'), findsOneWidget);
  });

  /// 등록 창의 `저장` 단추를 집는다.
  FilledButton saveButton(WidgetTester tester) => tester.widget<FilledButton>(
    find.ancestor(of: find.text('저장'), matching: find.byType(FilledButton)),
  );

  testWidgets('Gazebo 로 올릴 로봇은 자리가 비면 무엇이 빈지 알린다', (tester) async {
    // 자리를 안 고르면 spawn 좌표가 없어 지도 원점(0,0)에 놓인다. 그렇게
    // 등록된 이동 로봇과 설치 로봇이 원점에 겹치자, 메시끼리 파고들어 Gazebo 가
    // 스폰 4초 만에 죽었다(collision_trimesh_trimesh.cpp:285, exit 134). 그
    // 뒤로 RMF 와 Nav2 만 살아남아 토픽 이름은 있는데 값은 하나도 안 왔다.
    //
    // 여기에는 맵이 없어 고를 자리 자체가 없다. 그때는 막지 않고 알린다 —
    // 막으면 맵을 그리기 전에는 로봇을 한 대도 등록할 수 없다. 정작 중요한
    // "고를 자리가 있는데 안 골랐다" 는 robot_station_rule_test 에서 본다.
    await openRobotMenu(tester);
    await tester.tap(find.text('로봇 등록'));
    await tester.pumpAndSettle();

    // 기본값인 앱 Mock 은 Gazebo 에 올라가지 않으므로 자리 이야기가 없다.
    expect(saveButton(tester).onPressed, isNotNull);
    expect(find.textContaining('지도 원점'), findsNothing);

    await tester.tap(find.text('값의 출처'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Gazebo 시뮬레이션').last);
    await tester.pumpAndSettle();

    // 올릴 로봇이 되는 순간 자리가 필요해진다.
    expect(find.textContaining('지도 원점(0,0)에 놓입니다'), findsOneWidget);
    expect(saveButton(tester).onPressed, isNotNull);
  });

  testWidgets('자리 맞추기가 로봇 메뉴에 있다', (tester) async {
    await openRobotMenu(tester);

    // 좌표를 맞추는 과정이 눈에 안 보이는 곳에서만 일어나면, 로봇이 건물 밖
    // 허공에 떨어져 있어도 사람이 알 길이 없다.
    expect(find.text('자리 맞추기'), findsOneWidget);
  });

  testWidgets('축척이 없으면 무엇을 먼저 해야 하는지 알린다', (tester) async {
    await openRobotMenu(tester);

    await tester.tap(find.text('자리 맞추기'));
    await tester.pumpAndSettle();

    // 지도도 로봇도 없는 상태다. 빈 창만 띄우면 왜 아무것도 없는지 모른다.
    expect(find.textContaining('맵 관리에서 길이 기준'), findsOneWidget);
    expect(find.textContaining('축척(길이 기준)을 재고 로봇을 등록하면'), findsOneWidget);
    // 맞출 것이 없을 때 버튼을 눌리게 두면 눌러도 아무 일이 없다.
    expect(
      tester
          .widget<FilledButton>(
            find.ancestor(
              of: find.text('맞출 것이 없습니다'),
              matching: find.byType(FilledButton),
            ),
          )
          .onPressed,
      isNull,
    );
  });

  group('메뉴 차례', () {
    // 주요 운영 메뉴는 로봇 등록 → 작업 관리 → ROS2 확인 → 설정 파일이다.
    test('사이드바가 요청한 운영 순서를 따른다', () {
      final source = File('lib/main.dart').readAsStringSync();
      final menu = source.substring(
        source.indexOf("(Icons.grid_view_rounded, '대시보드')"),
        source.indexOf("(Icons.analytics_outlined, '운영 분석')"),
      );
      expect(menu.indexOf('맵 관리'), lessThan(menu.indexOf('로봇')));
      expect(menu.indexOf('로봇'), lessThan(menu.indexOf('작업')));
      expect(menu.indexOf('작업'), lessThan(menu.indexOf('ROS2 확인')));
      expect(menu.indexOf('ROS2 확인'), lessThan(menu.indexOf('설정 파일')));
    });

    test('제목 차례가 사이드바와 같다', () {
      // 어긋나면 설정 파일을 눌렀는데 제목만 작업이라고 나온다.
      final source = File('lib/main.dart').readAsStringSync();
      final titles = source.substring(
        source.indexOf("title: const ["),
        source.indexOf("][_selectedMenu]"),
      );
      expect(titles.indexOf('작업'), lessThan(titles.indexOf('ROS2 확인')));
      expect(titles.indexOf('ROS2 확인'), lessThan(titles.indexOf('설정 파일')));
    });

    test('메뉴 자리마다 이름이 있다', () {
      // 예전에는 화면 번호가 날숫자로 흩어져 있어, 메뉴를 가운데 하나 끼울 때
      // 뒤의 숫자를 전부 밀어야 했다. 한 군데만 놓치면 설정 파일을 눌렀는데
      // 작업이 열린다. 이름을 붙여 그 실수를 없앤다.
      final source = File('lib/main.dart').readAsStringSync();
      expect(source, isNot(contains('_selectedMenu == 0')));
      expect(source, contains('static const _menuDashboard = 0;'));
      expect(source, contains('static const _menuGrid = 2;'));
    });

    test('화면 번호가 제목 차례와 맞는다', () {
      // 번호와 제목이 어긋나 설정 파일을 눌렀는데 작업이 열린 적이 있다.
      final source = File('lib/main.dart').readAsStringSync();
      final titles = _menuTitles(source);
      // 자리 이름 → 그 자리에 떠야 하는 제목과 화면 위젯.
      const expected = {
        '_menuDashboard': ('대시보드', '_MainDashboard'),
        '_menuGrid': ('그리드맵', '_GridMapPage'),
        '_menuRobots': ('로봇', '_RobotManagementPage'),
        '_menuFiles': ('설정 파일', '_ProjectFilesPage'),
        '_menuTasks': ('작업', '_TaskManagementPage'),
        '_menuLog': ('로그 분석', '_ProjectLogPage'),
        '_menuAnalytics': ('운영 분석', '_OperationsAnalyticsPage'),
      };
      for (final entry in expected.entries) {
        final slot = _menuSlot(source, entry.key);
        expect(
          titles[slot],
          entry.value.$1,
          reason: '${entry.key}($slot) 자리의 제목이 어긋났다',
        );
        final branch = source.indexOf('_selectedMenu == ${entry.key}');
        expect(branch, greaterThan(-1), reason: '${entry.key} 분기가 없다');
        expect(
          source.substring(branch, branch + 90),
          contains(entry.value.$2),
          reason: '${entry.key} 자리에 다른 화면이 붙었다',
        );
      }
    });

    test('넘치는 번호로도 터지지 않는다', () {
      // 폴백이 메뉴보다 짧은 목록을 인덱스로 훑어, 메뉴를 하나 늘리면 범위
      // 넘침으로 터졌다.
      final source = File('lib/main.dart').readAsStringSync();
      expect(source, contains('_ComingSoonPage(title:'));
      expect(
        source.substring(source.indexOf('_ComingSoonPage(title:')),
        isNot(startsWith('_ComingSoonPage(title: const [')),
      );
    });
  });

  group('그리드맵 메뉴', () {
    test('맵 관리 바로 뒤에 온다', () {
      // 도면에서 파생되는 산출물이라 맵 다음이 제자리다.
      final source = File('lib/main.dart').readAsStringSync();
      final menu = source.substring(
        source.indexOf("(Icons.grid_view_rounded, '대시보드')"),
        source.indexOf("(Icons.analytics_outlined, '운영 분석')"),
      );
      expect(menu.indexOf('맵 관리'), lessThan(menu.indexOf('그리드맵')));
      expect(menu.indexOf('그리드맵'), lessThan(menu.indexOf('로봇')));
    });

    testWidgets('왼쪽 메뉴에서 바로 열린다', (tester) async {
      // 맵 관리 패널 안에도 같은 단추가 있지만, 도면을 고친 뒤 지도만 다시
      // 굽는 일이 잦아 찾아 들어가지 않아도 되게 꺼내 두었다.
      tester.view.physicalSize = const Size(1600, 1100);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(const RmfControlApp());
      await tester.pumpAndSettle();

      expect(find.text('그리드맵'), findsOneWidget);
      await tester.tap(find.text('그리드맵'));
      await tester.pumpAndSettle();

      expect(find.text('그리드맵 작성'), findsOneWidget);
      // 아무것도 없는 상태에서는 무엇이 모자란지 적어 준다.
      expect(find.text('아직 만들 수 없습니다'), findsOneWidget);
      expect(find.textContaining('도면을 올리세요'), findsOneWidget);
      final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, '그리드맵 만들기'),
      );
      expect(button.onPressed, isNull, reason: '준비가 안 된 채로 누르면 실패 팝업만 뜬다');
    });

    test('못 만들 때는 흐린 단추만 두지 않고 이유를 적는다', () {
      // 흐린 단추만 있으면 왜 안 되는지 알 수 없어, 사람이 배포를 처음부터
      // 다시 돌린다.
      final source = File('lib/main.dart').readAsStringSync();
      final page = source.substring(source.indexOf('class _GridMapPage'));
      expect(page, contains('아직 만들 수 없습니다'));
      expect(page, contains('도면을 올리세요'));
      expect(page, contains('Measurement 로 축척을 잡으세요'));
      expect(page, contains('Floor 자동 생성을 하세요'));
    });
  });

  group('로그 분석 메뉴', () {
    test('설정 파일 뒤에 온다', () {
      final source = File('lib/main.dart').readAsStringSync();
      final menu = source.substring(
        source.indexOf("(Icons.grid_view_rounded, '대시보드')"),
        source.indexOf("(Icons.analytics_outlined, '운영 분석')"),
      );
      expect(menu.indexOf('설정 파일'), lessThan(menu.indexOf('로그 분석')));
    });

    test('설정 파일 다음 자리다', () {
      final source = File('lib/main.dart').readAsStringSync();
      expect(
        _menuSlot(source, '_menuLog'),
        _menuSlot(source, '_menuFiles') + 1,
      );
    });
  });

  group('로그 고르기', () {
    test('여러 줄을 끌어 고를 수 있다', () {
      // 줄마다 SelectableText 를 두면 그 줄 안에서만 골라진다. 여러 줄을
      // 끌려면 SelectionArea 로 감싸고 안은 보통 Text 여야 한다.
      final source = File('lib/main.dart').readAsStringSync();
      final page = source.substring(
        source.indexOf('class _ProjectLogPageState'),
      );
      expect(page, contains('SelectionArea('));
      expect(
        page,
        isNot(
          contains(
            'child: SelectableText(\n                                    line.text',
          ),
        ),
      );
    });

    test('화면 밖 줄도 선택에 들어간다', () {
      // ListView.builder 는 화면 밖 줄을 만들지 않아 스크롤한 부분이 선택에서
      // 빠진다. 50줄뿐이니 통째로 둔다.
      final source = File('lib/main.dart').readAsStringSync();
      final page = source.substring(
        source.indexOf('class _ProjectLogPageState'),
      );
      // 주석에는 남아 있으므로 실제로 쓰는지를 본다.
      expect(page, isNot(contains('child: ListView.builder(')));
      expect(page, contains('for (final line in tail.lines)'));
    });
  });
}
