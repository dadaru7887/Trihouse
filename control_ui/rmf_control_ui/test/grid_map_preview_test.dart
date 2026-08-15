import 'dart:async';
import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/occupancy_grid.dart';

/// 그리드맵을 굽는 동안 무엇이 보이고, 끝나면 무엇이 보이는지 지킨다.
///
/// 예전에는 단추를 눌러도 화면이 그대로였다. 격자 굽기가 UI 스레드에서 도니까
/// 사람 눈에는 앱이 멈춘 것과 구분되지 않았고, 다 된 뒤에도 그림이 없어서 벽이
/// 제대로 잡혔는지는 파일을 열어 봐야 알 수 있었다.
void main() {
  group('격자를 그림으로', () {
    test('셀 값이 그대로 회색조 픽셀이 된다', () async {
      // 사람이 보는 그림과 `map_server` 가 읽는 PGM 이 어긋나면 안 된다.
      // 벽 0(검정) · 바닥 254(흰) · 모름 205(회색).
      final cells = Uint8List.fromList([
        OccupancyGrid.occupied,
        OccupancyGrid.free,
        OccupancyGrid.unknown,
        OccupancyGrid.free,
      ]);
      final image = await _gridImage(cells, 2, 2);
      addTearDown(image.dispose);

      final read = await image.toByteData(format: ui.ImageByteFormat.rawRgba);
      final bytes = read!.buffer.asUint8List();
      expect(bytes[0], OccupancyGrid.occupied, reason: '벽은 검어야 한다');
      expect(bytes[4], OccupancyGrid.free, reason: '바닥은 희어야 한다');
      expect(bytes[8], OccupancyGrid.unknown, reason: '모름은 회색이어야 한다');
      expect(bytes[3], 0xFF, reason: '불투명해야 한다');
      expect(image.width, 2);
      expect(image.height, 2);
    });

    test('첫 줄이 위쪽이다 — PGM 과 같은 방향', () async {
      // 위아래가 뒤집히면 화면의 벽과 로봇이 보는 벽이 어긋난다.
      final cells = Uint8List.fromList([
        OccupancyGrid.occupied, OccupancyGrid.occupied, // 윗줄: 벽
        OccupancyGrid.free, OccupancyGrid.free, // 아랫줄: 바닥
      ]);
      final image = await _gridImage(cells, 2, 2);
      addTearDown(image.dispose);

      final read = await image.toByteData(format: ui.ImageByteFormat.rawRgba);
      final bytes = read!.buffer.asUint8List();
      // rawRgba 도 첫 줄이 위다.
      expect(bytes[0], OccupancyGrid.occupied);
      expect(bytes[2 * 4], OccupancyGrid.free, reason: '아랫줄이 바닥이어야 한다');
    });
  });

  group('작성 중 표시', () {
    late final String source = File('lib/main.dart').readAsStringSync();
    late final String page = source.substring(
      source.indexOf('class _GridMapPage'),
    );

    test('굽는 동안 커서가 바뀐다', () {
      // 화면이 멈춘 것과 일하고 있는 것을 사람이 구분할 수 있어야 한다.
      expect(page, contains('SystemMouseCursors.progress'));
    });

    test('굽는 동안 무엇을 하는지 글자로 알린다', () {
      expect(page, contains('그리드 이미지 작성 중…'));
      expect(page, contains('도면의 벽과 바닥을 칸으로 옮기고 있습니다'));
    });

    test('굽는 동안 또 누르지 못한다', () {
      expect(page, contains('ready && !generating'));
    });

    test('한 프레임을 내주고 나서 굽는다', () {
      // 이걸 안 하면 `작성 중` 이 그려지기 전에 UI 스레드가 막혀, 기다리는
      // 동안 아무 표시가 없다.
      final start = source.indexOf('Future<void> _generateGridMap()');
      expect(start, greaterThan(-1));
      final body = source.substring(start, start + 2400);
      final flag = body.indexOf('_isGeneratingGrid = true');
      final frame = body.indexOf('await WidgetsBinding.instance.endOfFrame');
      final build = body.indexOf('_buildOccupancyGrid()');
      expect(flag, greaterThan(-1));
      expect(frame, greaterThan(flag), reason: '깃발을 세운 뒤 프레임을 내줘야 한다');
      expect(build, greaterThan(frame), reason: '프레임을 내준 뒤에 구워야 한다');
    });

    test('실패해도 작성 중에서 빠져나온다', () {
      // finally 가 없으면 한 번 실패한 뒤로 단추가 영원히 잠긴다.
      final start = source.indexOf('Future<void> _generateGridMap()');
      final body = source.substring(start, start + 2400);
      final tryAt = body.indexOf('try {');
      final finallyAt = body.indexOf('} finally {');
      final cleared = body.indexOf('_isGeneratingGrid = false');
      expect(tryAt, greaterThan(-1));
      expect(finallyAt, greaterThan(tryAt));
      expect(cleared, greaterThan(finallyAt), reason: 'finally 안에서 풀어야 한다');
    });
  });

  group('완성된 그리드 이미지', () {
    late final String source = File('lib/main.dart').readAsStringSync();

    test('그림과 칸 수·한 칸 크기를 함께 보여 준다', () {
      final preview = source.substring(source.indexOf('class _GridMapPreview'));
      expect(preview, contains('RawImage('));
      // 칸이 뭉개지면 벽이 이어져 보인다.
      expect(preview, contains('FilterQuality.none'));
      expect(preview, contains('만든 그리드맵'));
      expect(preview, contains('칸 · 한 칸'));
      // 흰 바닥이 흰 카드에 묻히지 않게 회색 판을 깐다.
      expect(preview, contains('0xFFE2E8F0'));
    });

    test('벽·바닥·모름 범례를 숫자와 함께 보여 준다', () {
      final preview = source.substring(source.indexOf('class _GridMapPreview'));
      expect(preview, contains('벽 \${g.occupiedCells}칸'));
      expect(preview, contains('바닥 \${g.freeCells}칸'));
      expect(preview, contains('모름 \${g.unknownCells}칸'));
    });

    test('새로 구울 때 옛 그림을 먼저 지운다', () {
      // 남겨 두면 굽는 동안 옛 지도를 보며 다 됐다고 여긴다.
      final start = source.indexOf('Future<void> _generateGridMap()');
      final body = source.substring(start, start + 2400);
      final flag = body.indexOf('_isGeneratingGrid = true');
      final cleared = body.indexOf('_gridPreview = null');
      expect(cleared, greaterThan(flag));
    });

    test('미리보기 이미지를 정리한다', () {
      // ui.Image 는 GPU 자원이라 놔두면 안 돌아온다.
      expect(source, contains('_gridPreview?.dispose()'));
      final dispose = source.substring(source.indexOf('  void dispose() {'));
      expect(dispose.substring(0, 400), contains('_gridPreview?.dispose()'));
    });
  });
}

/// `_occupancyGridImage` 와 같은 방식으로 셀을 그림으로 만든다.
Future<ui.Image> _gridImage(Uint8List cells, int width, int height) {
  final rgba = Uint8List(cells.length * 4);
  for (var i = 0; i < cells.length; i++) {
    final value = cells[i];
    rgba[i * 4] = value;
    rgba[i * 4 + 1] = value;
    rgba[i * 4 + 2] = value;
    rgba[i * 4 + 3] = 0xFF;
  }
  final completer = Completer<ui.Image>();
  ui.decodeImageFromPixels(
    rgba,
    width,
    height,
    ui.PixelFormat.rgba8888,
    completer.complete,
  );
  return completer.future;
}
