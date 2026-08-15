import 'package:flutter/material.dart';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/main.dart';

void main() {
  testWidgets('대시보드와 주요 운영 화면을 표시한다', (tester) async {
    tester.view.physicalSize = const Size(1600, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(const RmfControlApp());

    expect(find.text('운영 대시보드'), findsOneWidget);
    expect(find.text('실시간 운영 맵'), findsOneWidget);
    expect(find.text('최근 작업 활동'), findsOneWidget);
    expect(find.text('빠른 실행'), findsOneWidget);

    await tester.tap(find.text('맵 관리').first);
    await tester.pumpAndSettle();

    expect(find.text('새 창고 맵 만들기'), findsOneWidget);
    expect(find.text('도면 올리기'), findsOneWidget);
    expect(find.text('다른 이름으로 저장'), findsOneWidget);
    expect(find.text('현재 작업: '), findsOneWidget);
    expect(find.text('warehouse.building.yaml'), findsOneWidget);
    expect(find.text('로봇 안전 기준'), findsOneWidget);
    expect(find.text('시나리오 맵 자동 완성'), findsOneWidget);
    expect(find.text('오류 검증'), findsOneWidget);
    expect(find.text('경로 추천'), findsOneWidget);
    expect(find.text('창고 도면을 올려주세요'), findsOneWidget);
    expect(find.text('맵 생성 설정'), findsOneWidget);

    await tester.tap(find.text('사용법'));
    await tester.pumpAndSettle();
    expect(find.text('맵 관리 사용법'), findsOneWidget);
    expect(find.textContaining('왜 필요한가:'), findsWidgets);
    await tester.tap(find.text('확인'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('로봇'));
    await tester.pumpAndSettle();

    expect(find.text('로봇 운영'), findsOneWidget);
    expect(find.text('불러온 맵: '), findsOneWidget);
    expect(find.text('warehouse.building.yaml'), findsOneWidget);
    expect(find.text('로봇 Spawn'), findsOneWidget);
    expect(find.text('배포 맵 불러오기'), findsOneWidget);
    // 실행 방식은 화면 전체가 아니라 로봇마다 정한다. 등록이 없으면 표시할
    // 구성도 없다.
    expect(find.text('로봇 실행 방식'), findsNothing);
    expect(find.textContaining('로봇 등록 ·'), findsOneWidget);

    await tester.tap(find.text('사용법'));
    await tester.pumpAndSettle();
    expect(find.text('로봇 운영 사용법'), findsOneWidget);
    await tester.tap(find.text('확인'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('배포 맵 불러오기'));
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('배포된 맵 불러오기'), findsOneWidget);
    await tester.tap(find.text('취소'));
    await tester.pump(const Duration(milliseconds: 400));

    await tester.tap(find.text('작업'));
    await tester.pumpAndSettle();

    expect(find.text('작업 관리'), findsOneWidget);
    expect(find.text('불러온 맵: '), findsOneWidget);
    expect(find.text('warehouse.building.yaml'), findsOneWidget);
    expect(find.text('현재 운영 맵'), findsOneWidget);
    expect(find.text('새 작업'), findsOneWidget);
    // 로봇을 Spawn 하기 전에는 되돌릴 대상이 없어 눌리지 않는다.
    expect(find.text('로봇 원위치'), findsOneWidget);
    expect(
      tester
          .widget<OutlinedButton>(
            find.ancestor(
              of: find.text('로봇 원위치'),
              matching: find.byType(OutlinedButton),
            ),
          )
          .onPressed,
      isNull,
    );
    expect(find.text('생성된 작업이 없습니다.'), findsOneWidget);
    expect(find.text('1단계: 배포 맵을 불러오세요.'), findsOneWidget);

    await tester.tap(find.text('사용법'));
    await tester.pumpAndSettle();
    expect(find.text('작업 관리 사용법'), findsOneWidget);
    await tester.tap(find.text('확인'));
    await tester.pumpAndSettle();

    // 작업은 맵 프로젝트에 속한다. 프로젝트를 열거나 저장하기 전에는 어느 맵의
    // Waypoint를 목적지로 삼을지 정해지지 않으므로 만들 수 없다.
    await tester.tap(find.text('새 작업'));
    await tester.pumpAndSettle();
    expect(find.text('먼저 맵 프로젝트를 저장하세요'), findsOneWidget);
    await tester.tap(find.text('확인'));
    await tester.pumpAndSettle();
  });
}
