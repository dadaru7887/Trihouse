/// SLAM 지도를 프로젝트의 `nav2_map/` 에 넣고 다시 읽는다.
///
/// 도면에서 만든 격자(`<맵>.yaml`)와 **나란히** 둔다. 덮어쓰지 않는다 — 두
/// 지도를 겹쳐 보며 원점을 맞춰야 하므로 둘 다 있어야 한다.
library;

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'occupancy_grid_export.dart' show occupancyGridDirectoryName;
import 'rmf_config_export.dart' show safeMapDirectoryName;
import 'slam_map.dart';

/// SLAM 지도를 넣거나 읽은 결과.
class SlamMapStoreResult {
  const SlamMapStoreResult({
    required this.success,
    required this.message,
    this.map,
    this.directory = '',
    this.written = const [],
  });

  final bool success;
  final String message;

  /// 읽어 들인 지도. 실패하면 null.
  final SlamMap? map;
  final String directory;
  final List<String> written;
}

Directory? _findProjectRoot() {
  final configured = Platform.environment['RMF_ROOT'];
  if (configured != null && configured.isNotEmpty) {
    final directory = Directory(configured).absolute;
    if (Directory('${directory.path}/rmf_maps').existsSync()) return directory;
  }
  var directory = Directory.current.absolute;
  for (var i = 0; i < 8; i++) {
    if (Directory('${directory.path}/rmf_maps').existsSync()) return directory;
    final parent = directory.parent;
    if (parent.path == directory.path) break;
    directory = parent;
  }
  return null;
}

String _mapDirectory(Directory root, String mapName) =>
    '${root.path}/rmf_maps/${safeMapDirectoryName(mapName)}/'
    '$occupancyGridDirectoryName';

/// 이 프로젝트에서 SLAM 지도가 쓰는 파일 이름. 도면 지도와 겹치지 않는다.
String slamYamlName(String mapName) =>
    '${safeMapDirectoryName(mapName)}_slam.yaml';
String slamImageName(String mapName) =>
    '${safeMapDirectoryName(mapName)}_slam.pgm';

/// [yamlPath] 와 그 옆의 `.pgm` 을 읽어 [SlamMap] 으로 만든다. 아직 안 옮긴다.
///
/// 먼저 읽어서 보여 주고, 사람이 원점을 확인한 뒤에 넣는다. 곧바로 넣으면
/// 못 읽는 파일이 프로젝트에 들어앉는다.
Future<SlamMapStoreResult> readSlamMapFrom(String yamlPath) async {
  final yamlFile = File(yamlPath);
  if (!await yamlFile.exists()) {
    return SlamMapStoreResult(
      success: false,
      message: 'yaml 파일이 없습니다: $yamlPath',
    );
  }
  try {
    final header = parseSlamMapYaml(await yamlFile.readAsString());
    // `image:` 는 yaml 옆에 있는 파일을 가리킨다.
    final imagePath = '${yamlFile.parent.path}/${header.imageName}';
    final imageFile = File(imagePath);
    if (!await imageFile.exists()) {
      return SlamMapStoreResult(
        success: false,
        message:
            'yaml 이 가리키는 그림이 없습니다: ${header.imageName}\n\n'
            '`map_saver` 는 yaml 과 그림(`.pgm` 또는 `.png`)을 함께 냅니다. '
            'yaml 만 옮겨 오면 그림이 없어 지도를 만들 수 없습니다.\n\n'
            '두 파일을 같은 디렉터리에 함께 두고, `.yaml` 을 다시 고르세요.',
      );
    }
    final pgm = await _readMapImage(await imageFile.readAsBytes());
    return SlamMapStoreResult(
      success: true,
      message: '읽었습니다.',
      map: SlamMap(
        imageName: header.imageName,
        width: pgm.width,
        height: pgm.height,
        resolution: header.resolution,
        originX: header.originX,
        originY: header.originY,
        originYaw: header.originYaw,
        cells: pgm.cells,
        occupiedThreshold: header.occupiedThreshold,
        freeThreshold: header.freeThreshold,
        negate: header.negate,
      ),
    );
  } on SlamMapParseError catch (error) {
    return SlamMapStoreResult(success: false, message: error.message);
  } catch (error) {
    return SlamMapStoreResult(
      success: false,
      message: 'SLAM 지도를 읽지 못했습니다: $error',
    );
  }
}

/// [map] 을 이 프로젝트의 `nav2_map/` 에 `<맵>_slam.{pgm,yaml}` 로 쓴다.
///
/// 그림 이름을 우리 규칙으로 갈아 끼운다. `map_saver` 가 낸 이름이 다른
/// 프로젝트의 것과 같을 수 있고, 그러면 어느 지도인지 알 수 없다.
Future<SlamMapStoreResult> writeSlamMap({
  required String mapName,
  required SlamMap map,
  String? note,
}) async {
  final root = _findProjectRoot();
  if (root == null) {
    return const SlamMapStoreResult(
      success: false,
      message:
          'rmf_maps 디렉터리를 찾을 수 없습니다. '
          'RMF_ROOT 환경 변수로 프로젝트 위치를 지정하세요.',
    );
  }
  final target = Directory(_mapDirectory(root, mapName));
  final image = slamImageName(mapName);
  final yaml = slamYamlName(mapName);
  try {
    await target.create(recursive: true);
    await File('${target.path}/$image').writeAsBytes(_toPgm(map), flush: true);
    final stored = SlamMap(
      imageName: image,
      width: map.width,
      height: map.height,
      resolution: map.resolution,
      originX: map.originX,
      originY: map.originY,
      originYaw: map.originYaw,
      cells: map.cells,
      occupiedThreshold: map.occupiedThreshold,
      freeThreshold: map.freeThreshold,
      negate: map.negate,
    );
    await File(
      '${target.path}/$yaml',
    ).writeAsString(stored.toYaml(note: note), flush: true);
    return SlamMapStoreResult(
      success: true,
      message: 'SLAM 지도를 넣었습니다.',
      map: stored,
      directory: target.path,
      written: [image, yaml],
    );
  } catch (error) {
    return SlamMapStoreResult(
      success: false,
      message: 'SLAM 지도를 쓰지 못했습니다: $error',
    );
  }
}

/// 이 프로젝트에 이미 넣어 둔 SLAM 지도를 읽는다. 없으면 null.
Future<SlamMap?> loadStoredSlamMap(String mapName) async {
  final root = _findProjectRoot();
  if (root == null) return null;
  final path = '${_mapDirectory(root, mapName)}/${slamYamlName(mapName)}';
  if (!await File(path).exists()) return null;
  final result = await readSlamMapFrom(path);
  return result.map;
}

/// 지도 그림을 읽어 회색조 칸으로 만든다.
///
/// `map_saver` 는 `--fmt` 와 모드에 따라 **PGM 도 PNG 도** 냅니다(scale 모드는
/// PNG 가 기본이다). 그래서 확장자나 한 형식만 믿으면 안 되고, 앞 바이트로 갈라
/// 각자 방식으로 읽는다. PGM 은 우리가 직접 읽고(가볍다), 나머지는 엔진에 맡긴다.
Future<({int width, int height, Uint8List cells})> _readMapImage(
  Uint8List bytes,
) async {
  final format = mapImageFormat(bytes);
  if (format == MapImageFormat.pgm) return parsePgm(bytes);
  if (format == MapImageFormat.unknown) {
    throw const SlamMapParseError(
      '읽을 수 있는 지도 그림이 아닙니다.\n\n'
      'PGM · PNG · BMP · JPEG 를 읽습니다. `map_saver` 가 낸 파일이 맞는지, '
      'yaml 의 `image:` 가 그 파일을 가리키는지 확인하세요.',
    );
  }

  // PNG·BMP·JPEG. 엔진으로 풀어 회색조로 옮긴다.
  final codec = await ui.instantiateImageCodec(bytes);
  try {
    final frame = await codec.getNextFrame();
    final image = frame.image;
    try {
      final data = await image.toByteData(format: ui.ImageByteFormat.rawRgba);
      if (data == null) {
        throw const SlamMapParseError('지도 그림의 픽셀을 읽지 못했습니다.');
      }
      final rgba = data.buffer.asUint8List();
      final count = image.width * image.height;
      final cells = Uint8List(count);
      for (var i = 0; i < count; i++) {
        // 지도 그림은 회색조라 R·G·B 가 같다. R 을 그대로 쓰면 `모름`(205)
        // 같은 값이 한 눈금도 안 틀어진다. 밝기로 환산하면 반올림에서 205 가
        // 204 나 206 이 되어 free/occupied 문턱과 어긋난다.
        cells[i] = rgba[i * 4];
      }
      return (width: image.width, height: image.height, cells: cells);
    } finally {
      image.dispose();
    }
  } finally {
    codec.dispose();
  }
}

/// 회색 PGM(P5) 한 장.
///
/// **주석(`#`)을 넣지 않는다.** `occupancy_grid.dart` 의 `toPgm` 과 같은 이유다 —
/// 어떤 도구는 첫 줄 뒤의 주석을 못 읽는다. 이 파일을 실제로 읽는 것은 우리
/// 파서가 아니라 `map_server` 이므로, 우리가 읽을 수 있다는 것은 근거가 되지
/// 않는다. 이게 어디서 온 지도인지는 옆 yaml 의 주석에 적는다.
///
/// 머리글은 아스키로 굳혀 쓴다. `codeUnits` 로 쓰면 주석에 한글이 섞였을 때
/// UTF-8 멀티바이트가 머리글에 들어가 칸 수가 어긋난다.
Uint8List _toPgm(SlamMap map) {
  final header = ascii.encode('P5\n${map.width} ${map.height}\n255\n');
  return Uint8List(header.length + map.cells.length)
    ..setRange(0, header.length, header)
    ..setRange(header.length, header.length + map.cells.length, map.cells);
}
