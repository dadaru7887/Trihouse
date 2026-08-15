/// 그리드맵 화면의 "저장할 것이 남았나" 판단을 지킨다.
///
/// 이 값들은 프로젝트에 저장되지만(`gridResolution`·`useSlamMap`) 그리드맵
/// 화면에는 **저장하는 자리가 없었다.** 고쳐 놓고 다른 화면으로 옮겨 가
/// `프로젝트 저장` 을 눌러야 남았다. 모르면 격자 크기를 맞춰 놓고 프로젝트를
/// 다시 열었을 때 옛 값으로 돌아가 있는데, 그러고도 아무 말이 없다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/grid_map_settings.dart';

void main() {
  const saved = GridMapSettings(
    mode: 'target',
    targetWidth: 800,
    targetHeight: 600,
    padToTarget: true,
    manualResolution: .02,
    useSlamMap: false,
  );

  List<String> changes(GridMapSettings current) =>
      gridSettingChanges(saved: saved, current: current);

  group('안 고쳤으면 저장할 것도 없다', () {
    test('같은 값이면 빈 목록', () {
      expect(changes(saved), isEmpty);
    });

    test('실수를 다시 읽어 미세하게 달라져도 같다고 본다', () {
      // 0.02 를 저장했다 읽으면 0.019999… 가 될 수 있다. 그대로 견주면 아무도
      // 안 고쳤는데 저장 단추가 켜진다.
      const reread = GridMapSettings(
        mode: 'target',
        targetWidth: 800,
        targetHeight: 600,
        padToTarget: true,
        manualResolution: .02 + 1e-12,
        useSlamMap: false,
      );
      expect(changes(reread), isEmpty);
      expect(reread, saved);
      expect(reread.hashCode, saved.hashCode);
    });
  });

  group('무엇이 바뀌었는지 적는다', () {
    test('격자 크기 방식', () {
      final result = changes(
        const GridMapSettings(
          mode: 'manual',
          targetWidth: 800,
          targetHeight: 600,
          padToTarget: true,
          manualResolution: .02,
          useSlamMap: false,
        ),
      );
      expect(result, hasLength(1));
      // 사람이 읽는 이름으로 적는다. `target` 은 화면 어디에도 안 쓰는 말이다.
      expect(result.single, contains('목표 크기'));
      expect(result.single, contains('직접 지정'));
    });

    test('목표 크기는 가로세로를 한 줄로 묶는다', () {
      // 가로만 고쳐도 사람은 "크기를 고쳤다" 고 여긴다. 두 줄로 나오면 무엇을
      // 고쳤는지 오히려 헷갈린다.
      final result = changes(
        const GridMapSettings(
          mode: 'target',
          targetWidth: 1024,
          targetHeight: 600,
          padToTarget: true,
          manualResolution: .02,
          useSlamMap: false,
        ),
      );
      expect(result, hasLength(1));
      expect(result.single, contains('800×600'));
      expect(result.single, contains('1024×600'));
    });

    test('여백 채우기', () {
      final result = changes(
        const GridMapSettings(
          mode: 'target',
          targetWidth: 800,
          targetHeight: 600,
          padToTarget: false,
          manualResolution: .02,
          useSlamMap: false,
        ),
      );
      expect(result.single, contains('여백 채우기 끔'));
    });

    test('한 칸 크기', () {
      final result = changes(
        const GridMapSettings(
          mode: 'target',
          targetWidth: 800,
          targetHeight: 600,
          padToTarget: true,
          manualResolution: .05,
          useSlamMap: false,
        ),
      );
      expect(result.single, contains('0.020m → 0.050m'));
    });

    test('SLAM 지도 사용 여부도 이 화면의 값이다', () {
      final result = changes(
        const GridMapSettings(
          mode: 'target',
          targetWidth: 800,
          targetHeight: 600,
          padToTarget: true,
          manualResolution: .02,
          useSlamMap: true,
        ),
      );
      expect(result.single, contains('SLAM 지도'));
    });

    test('여러 개를 고치면 여러 줄이 나온다', () {
      final result = changes(
        const GridMapSettings(
          mode: 'manual',
          targetWidth: 1024,
          targetHeight: 768,
          padToTarget: false,
          manualResolution: .05,
          useSlamMap: true,
        ),
      );
      expect(result, hasLength(5));
    });
  });
}
