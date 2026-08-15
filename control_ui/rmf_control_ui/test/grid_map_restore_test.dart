/// 구운 그리드맵이 프로젝트에 남고, 프로젝트를 열면 다시 올라오는지 지킨다.
///
/// 예전에는 격자가 파일로는 남았는데 화면이 그 사실을 몰랐다. 프로젝트를 열면
/// 그리드맵 화면이 늘 비어 있어서, 이미 구워 배포까지 한 지도를 사람이 다시
/// 구웠다. 파일이 있으면 화면에도 있어야 한다.
library;

import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/occupancy_grid.dart';
import 'package:rmf_control_ui/occupancy_grid_export.dart';

void main() {
  group(
    '저장한 격자를 다시 읽는다',
    () {
      late Directory root;
      late String previousCurrent;

      setUp(() {
        // `rmf_maps` 를 가진 디렉터리를 프로젝트 뿌리로 삼는다. 저장소가 뿌리를
        // 찾는 방식과 같다 — 진짜 rmf_maps 를 건드리지 않으려고 옮겨 놓는다.
        root = Directory.systemTemp.createTempSync('grid_restore');
        Directory('${root.path}/rmf_maps').createSync();
        previousCurrent = Directory.current.path;
        Directory.current = root;
      });

      tearDown(() {
        Directory.current = previousCurrent;
        root.deleteSync(recursive: true);
      });

      test('쓴 격자와 읽은 격자가 같다', () async {
        final grid = _sampleGrid();
        final written = await exportOccupancyGrid(mapName: '2층창고', grid: grid);
        expect(written.success, isTrue, reason: written.message);

        final stored = await loadStoredOccupancyGrid('2층창고');
        expect(stored, isNotNull, reason: '방금 쓴 격자를 못 읽으면 화면이 비어 보인다');
        final read = stored!.grid;
        expect(read.width, grid.width);
        expect(read.height, grid.height);
        expect(read.resolution, closeTo(grid.resolution, 1e-6));
        // 원점이 틀리면 로봇이 `픽업1로 가라`는 명령을 받고 엉뚱한 데로 간다.
        expect(read.originX, closeTo(grid.originX, 1e-6));
        expect(read.originY, closeTo(grid.originY, 1e-6));
        expect(read.cells, orderedEquals(grid.cells));
        expect(stored.directory, written.directory);
      });

      test('벽·바닥·모름이 그대로다', () async {
        final grid = _sampleGrid();
        await exportOccupancyGrid(mapName: '2층창고', grid: grid);
        final read = (await loadStoredOccupancyGrid('2층창고'))!.grid;
        expect(read.occupiedCells, grid.occupiedCells);
        expect(read.freeCells, grid.freeCells);
        expect(read.unknownCells, grid.unknownCells);
      });

      test('아직 안 구운 프로젝트는 null 이다', () async {
        // 없는 것은 오류가 아니다. 프로젝트 열기를 막으면 안 된다.
        expect(await loadStoredOccupancyGrid('아직없음'), isNull);
      });

      test('yaml 만 있고 그림이 없으면 null 이다', () async {
        final written = await exportOccupancyGrid(
          mapName: '2층창고',
          grid: _sampleGrid(),
        );
        File(
          '${written.directory}/${occupancyGridImageName('2층창고')}',
        ).deleteSync();
        expect(await loadStoredOccupancyGrid('2층창고'), isNull);
      });

      test('SLAM 지도를 격자로 잘못 읽지 않는다', () async {
        // 같은 디렉터리에 `<맵>_slam.*` 가 나란히 산다. 이름이 겹치면 도면에서
        // 만든 격자 대신 SLAM 지도가 올라온다.
        expect(occupancyGridYamlName('2층창고'), isNot(contains('_slam')));
        expect(occupancyGridImageName('2층창고'), isNot(contains('_slam')));
      });

      test('언제 만든 것인지 함께 준다', () async {
        // 도면을 그 뒤에 고쳤을 수 있다. 시각이 없으면 최신인 줄 안다.
        await exportOccupancyGrid(mapName: '2층창고', grid: _sampleGrid());
        final stored = await loadStoredOccupancyGrid('2층창고');
        expect(
          DateTime.now().difference(stored!.savedAt).inMinutes.abs(),
          lessThan(5),
        );
      });
      // RMF_ROOT 가 정해져 있으면 저장소가 그쪽을 뿌리로 잡는다. 임시 디렉터리로
      // 옮겨 놓을 수 없으므로, 진짜 rmf_maps 에 쓰느니 건너뛴다.
    },
    skip: (Platform.environment['RMF_ROOT'] ?? '').isEmpty
        ? null
        : 'RMF_ROOT 가 정해져 있어 임시 뿌리를 쓸 수 없습니다',
  );

  group('프로젝트를 열 때', () {
    late final String source = File('lib/main.dart').readAsStringSync();
    late final String body = source.substring(
      source.indexOf('Future<void> _switchOpenProject('),
      source.indexOf('bool _triggerMatches('),
    );

    test('저장된 격자를 올린다', () {
      expect(body, contains('_loadStoredGrid('));
    });

    test('앞 프로젝트의 격자를 먼저 지운다', () {
      // 남겨 두면 새로 연 프로젝트에 지도가 이미 있는 것으로 보인다.
      expect(body, contains('_gridPreview = null'));
      expect(body, contains('_gridPreview?.dispose()'));
    });

    test('올리는 사이 프로젝트가 바뀌면 버린다', () {
      final loader = source.substring(
        source.indexOf('Future<void> _loadStoredGrid('),
      );
      final head = loader.substring(0, 1200);
      expect(head, contains('_openProjectName != mapName'));
      // 굽는 중에 옛 파일로 덮으면 방금 한 일이 없던 것이 된다.
      expect(head, contains('_isGeneratingGrid'));
      expect(head, contains('image.dispose()'));
    });
  });
}

/// 벽 한 줄, 바닥 한 줄, 모름 한 줄짜리 작은 격자.
OccupancyGrid _sampleGrid() {
  const width = 4;
  const height = 3;
  final cells = Uint8List(width * height);
  for (var col = 0; col < width; col++) {
    cells[col] = OccupancyGrid.occupied;
    cells[width + col] = OccupancyGrid.free;
    cells[2 * width + col] = OccupancyGrid.unknown;
  }
  return OccupancyGrid(
    width: width,
    height: height,
    resolution: .025,
    originX: -1.25,
    originY: -3.5,
    cells: cells,
  );
}
