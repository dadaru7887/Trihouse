/// 충돌 반경·접근 금지 반경·Lane 표시 폭을 사람이 직접 넣을 수 있는지 지킨다.
///
/// 셋 다 원래는 로봇 폭에서 계산만 했다. 계산은 로봇을 **원으로 본 어림**이라,
/// 적재물이나 범퍼가 튀어나오면 실제 몸이 그 원보다 크다. RMF 는 그만큼을
/// 모르는 채로 두 로봇을 붙인다. Lane 표시 폭은 반대 문제였다 — RMF 기본값
/// 0.5m 가 창고용이라 2~3m 짜리 실험실 도면에서는 Lane 스무 개가 겹쳐
/// 덩어리로 보였다.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/main.dart';
import 'package:rmf_control_ui/rmf_project_config.dart';

void main() {
  group('직접 넣은 값이 계산을 이긴다', () {
    const base = RmfFleetSettings();

    test('안 넣으면 로봇 폭에서 계산한다', () {
      final fleet = base.withRobotSafety(
        widthMeters: .6,
        localizationMarginMeters: .1,
      );
      expect(fleet.footprintRadius, closeTo(.3, 1e-9));
      expect(fleet.vicinityRadius, closeTo(.4, 1e-9));
    });

    test('넣은 값은 폭을 고쳐도 그대로다', () {
      // 재서 넣은 값을 폭 수정이 덮어쓰면, 사람이 넣은 사실 자체가 사라진다.
      final fleet = base
          .copyWith(manualFootprintRadius: .45, manualVicinityRadius: .8)
          .withRobotSafety(widthMeters: .6, localizationMarginMeters: .1);
      expect(fleet.footprintRadius, closeTo(.45, 1e-9));
      expect(fleet.vicinityRadius, closeTo(.8, 1e-9));

      final wider = fleet.withRobotSafety(
        widthMeters: 1.2,
        localizationMarginMeters: .2,
      );
      expect(wider.footprintRadius, closeTo(.45, 1e-9));
      expect(wider.vicinityRadius, closeTo(.8, 1e-9));
    });

    test('한쪽만 넣으면 나머지는 계산한다', () {
      final fleet = base
          .copyWith(manualFootprintRadius: .45)
          .withRobotSafety(widthMeters: .6, localizationMarginMeters: .1);
      expect(fleet.footprintRadius, closeTo(.45, 1e-9));
      expect(fleet.vicinityRadius, closeTo(.4, 1e-9), reason: '안 넣은 쪽은 자동이다');
    });

    test('지우면 다시 계산으로 돌아간다', () {
      // copyWith 의 null 은 `안 바꿈` 이라, 깃발이 없으면 지운 값이 되살아난다.
      final fleet = base
          .copyWith(manualFootprintRadius: .45, manualVicinityRadius: .8)
          .copyWith(clearManualProfile: true)
          .withRobotSafety(widthMeters: .6, localizationMarginMeters: .1);
      expect(fleet.footprintRadius, closeTo(.3, 1e-9));
      expect(fleet.vicinityRadius, closeTo(.4, 1e-9));
    });

    test('프로젝트에 남고 다시 읽힌다', () {
      final fleet = base.copyWith(
        manualFootprintRadius: .45,
        manualVicinityRadius: .8,
      );
      final read = RmfFleetSettings.fromJson(fleet.toJson());
      expect(read.manualFootprintRadius, closeTo(.45, 1e-9));
      expect(read.manualVicinityRadius, closeTo(.8, 1e-9));
      // 안 넣은 상태도 그대로 남아야 한다. 계산값이 적히면 폭을 고쳐도
      // 안 따라온다.
      final auto = RmfFleetSettings.fromJson(base.toJson());
      expect(auto.manualFootprintRadius, isNull);
      expect(auto.manualVicinityRadius, isNull);
    });
  });

  group('Lane 표시 폭', () {
    test('안 넣으면 로봇 폭으로 그린다', () {
      // `이 Lane 을 이 로봇이 지난다` 가 그림 그대로 보이는 것이 어림값보다 낫다.
      expect(navGraphLaneWidth(robotWidthMeters: .2), closeTo(.2, 1e-9));
    });

    test('넣으면 그 값으로 그린다', () {
      expect(
        navGraphLaneWidth(robotWidthMeters: .2, manual: .35),
        closeTo(.35, 1e-9),
      );
    });

    test('시각화 노드가 못 받는 값은 미리 깎는다', () {
      // NavGraphVisualizer 가 std::max(0.1, lane_width) 로 깎는다.
      expect(
        navGraphLaneWidth(robotWidthMeters: .02),
        closeTo(minNavGraphLaneWidth, 1e-9),
      );
      expect(navGraphLaneWidth(robotWidthMeters: 0), defaultNavGraphLaneWidth);
    });
  });

  group('launch 로 나가는 값', () {
    String launchWith(double laneWidth) => buildProjectLaunchXml(
      mapName: 'gwanghee',
      fleetName: 'gwanghee_pinky',
      mapDirectory: '/maps/gwanghee',
      buildingYamlName: 'gwanghee.building.yaml',
      laneWidth: laneWidth,
    );

    test('Lane 굵기가 시각화까지 간다', () {
      // rmf_demos 의 common.launch.xml 은 이 값을 넘기지 않는다. 그래서 그
      // 파일을 include 하지 않고 우리가 편다 — 안 그러면 0.5m 로 그려진다.
      final xml = launchWith(.2);
      expect(xml, contains('<arg name="lane_width" default="0.200"/>'));
      expect(
        xml,
        contains(r'<arg name="lane_width" value="$(var lane_width)"/>'),
      );
      expect(xml, contains('rmf_visualization)/visualization.launch.xml'));
      // 파일 안의 주석은 그 파일을 가리켜도 된다. 막는 것은 `include` 다 —
      // include 하면 Lane 굵기를 못 넘긴다.
      expect(
        xml,
        isNot(
          contains(
            r'<include file="$(find-pkg-share rmf_demos)/common.launch.xml"',
          ),
        ),
      );
    });

    test('RViz 는 우리 설정으로 띄운다', () {
      final xml = launchWith(.2);
      // 상류 include 안의 rviz2 는 끈다. rmf.rviz 는 office 데모를 보고 있어
      // 우리 도면이 화면 밖이고, 바닥 그림 토픽 이름도 어긋나 있다.
      expect(xml, contains('<arg name="headless" value="true"/>'));
      expect(xml, contains(r'args="-d $(var map_dir)/gwanghee.rviz"'));
      // sim 시간을 안 주면 Gazebo 시간의 라이다·TF 가 안 그려진다.
      final rviz = xml.substring(xml.indexOf('exec="rviz2"'));
      expect(rviz, contains(r'<param name="use_sim_time"'));
    });
  });

  group('로봇 안전 기준 창', () {
    Future<void> openDialog(WidgetTester tester) async {
      tester.view.physicalSize = const Size(1600, 1200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(const RmfControlApp());
      await tester.tap(find.text('맵 관리').first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('로봇 안전 기준'));
      await tester.pumpAndSettle();
    }

    Finder fieldByLabel(String label) =>
        find.ancestor(of: find.text(label), matching: find.byType(TextField));

    testWidgets('세 칸이 있고 비우면 자동이라고 알린다', (tester) async {
      await openDialog(tester);
      expect(find.text('직접 지정 (비우면 위 값에서 계산)'), findsOneWidget);
      expect(fieldByLabel('충돌 반경 footprint (m)'), findsOneWidget);
      expect(fieldByLabel('접근 금지 반경 vicinity (m)'), findsOneWidget);
      expect(fieldByLabel('Lane 표시 폭 · RViz (m)'), findsOneWidget);
    });

    testWidgets('접근 금지 반경이 충돌 반경보다 작으면 막는다', (tester) async {
      // 작으면 다른 로봇이 몸 안까지 들어와도 된다는 말이 된다.
      await openDialog(tester);
      await tester.enterText(fieldByLabel('충돌 반경 footprint (m)'), '0.40');
      await tester.enterText(fieldByLabel('접근 금지 반경 vicinity (m)'), '0.20');
      await tester.tap(find.text('기준 저장'));
      await tester.pumpAndSettle();

      expect(find.textContaining('보다 작을 수 없습니다'), findsOneWidget);
      expect(find.text('기준 저장'), findsOneWidget, reason: '창이 열려 있어야 한다');
    });

    testWidgets('너무 가는 Lane 은 그대로 받지 않는다', (tester) async {
      await openDialog(tester);
      await tester.enterText(fieldByLabel('Lane 표시 폭 · RViz (m)'), '0.02');
      await tester.tap(find.text('기준 저장'));
      await tester.pumpAndSettle();

      expect(find.textContaining('가늘게는'), findsOneWidget);
    });

    testWidgets('숫자가 아니면 비우라고 알린다', (tester) async {
      await openDialog(tester);
      await tester.enterText(fieldByLabel('충돌 반경 footprint (m)'), '0.4m');
      await tester.tap(find.text('기준 저장'));
      await tester.pumpAndSettle();

      expect(find.text('숫자로 입력하세요. 비우면 자동입니다.'), findsOneWidget);
    });
  });
}
