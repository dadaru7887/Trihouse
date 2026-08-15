/// 배포된 위치추정 지도와 주행 그래프를 디스크에서 읽는다.
///
/// 정합을 따지려면 **실제로 실행에 들어가는 파일**을 봐야 한다. 앱이 들고 있는
/// 값이 아니라 디스크의 것이다 — 내보내기를 안 했으면 둘이 다르고, 어긋난 채로
/// 도는 것은 디스크 쪽이다.
///
/// 판단은 [nav2_map_alignment] 가 한다. 여기서는 숫자만 꺼낸다.
library;

import 'dart:io';

import 'nav2_map_alignment.dart';

/// `map_server` 가 읽는 yaml 과 그 옆의 pgm 에서 덮는 범위를 낸다.
///
/// 못 읽으면 null 이다. 파일이 아직 없다는 뜻이지 어긋났다는 뜻이 아니라,
/// 부르는 쪽이 그 둘을 갈라 다뤄야 한다.
MapExtentMeters? readNav2MapExtent(String yamlPath) {
  final yaml = File(yamlPath);
  if (!yaml.existsSync()) return null;
  final text = yaml.readAsStringSync();

  double? number(String key) {
    final match = RegExp(
      '^\\s*$key:\\s*([-\\d.eE+]+)',
      multiLine: true,
    ).firstMatch(text);
    return match == null ? null : double.tryParse(match.group(1)!);
  }

  final resolution = number('resolution');
  final originMatch = RegExp(
    r'^\s*origin:\s*\[\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)',
    multiLine: true,
  ).firstMatch(text);
  final image = RegExp(r'^\s*image:\s*(\S+)', multiLine: true).firstMatch(text);
  if (resolution == null || originMatch == null || image == null) return null;

  // 그림은 yaml 옆에 있다. 경로가 적혀 있으면 그대로 쓴다.
  final imageName = image.group(1)!;
  final pgm = File(
    imageName.startsWith('/') ? imageName : '${yaml.parent.path}/$imageName',
  );
  final size = readPgmSize(pgm);
  if (size == null) return null;

  return MapExtentMeters.fromOrigin(
    originX: double.parse(originMatch.group(1)!),
    originY: double.parse(originMatch.group(2)!),
    resolution: resolution,
    widthCells: size.$1,
    heightCells: size.$2,
  );
}

/// PGM 머리글에서 칸 수를 읽는다. `(가로, 세로)`. 못 읽으면 null.
///
/// 파일 전체를 안 읽는다 — 이 그림이 수십만 바이트라 머리글만 필요한데 통째로
/// 올릴 이유가 없다. 주석(`#`) 줄은 어디에나 낄 수 있어서 함께 걷어낸다.
(int, int)? readPgmSize(File pgm) {
  if (!pgm.existsSync()) return null;
  final RandomAccessFile handle;
  try {
    handle = pgm.openSync();
  } on FileSystemException {
    return null;
  }
  try {
    final head = handle.readSync(256);
    final text = String.fromCharCodes(head);
    if (!text.startsWith('P5') && !text.startsWith('P2')) return null;
    final tokens = <String>[];
    for (final line in text.split('\n').skip(1)) {
      if (line.trimLeft().startsWith('#')) continue;
      tokens.addAll(
        line.trim().split(RegExp(r'\s+')).where((t) => t.isNotEmpty),
      );
      if (tokens.length >= 2) break;
    }
    if (tokens.length < 2) return null;
    final width = int.tryParse(tokens[0]);
    final height = int.tryParse(tokens[1]);
    if (width == null || height == null) return null;
    return (width, height);
  } finally {
    handle.closeSync();
  }
}

/// 배포된 nav graph 에서 Waypoint 이름과 월드 좌표를 읽는다.
///
/// `0.yaml` 은 `building_map_generator nav` 가 만든 것이라 모양이 정해져 있다.
/// 꼭짓점 한 줄이 `- - x` / `  - y` / `  - {name: ...}` 세 줄로 온다.
Map<String, ({double x, double y})> readNavGraphWaypoints(String path) {
  final file = File(path);
  if (!file.existsSync()) return const {};
  final result = <String, ({double x, double y})>{};
  // 이름 없는 꼭짓점은 뺀다. RMF 가 이름으로 자리를 찾으므로 보낼 수 없는
  // 자리이고, 정합을 따질 대상도 아니다.
  final pattern = RegExp(
    r'^\s*-\s*-\s*([-\d.eE+]+)\s*\n'
    r'\s*-\s*([-\d.eE+]+)\s*\n'
    r'\s*-\s*\{(.*)\}\s*$',
    multiLine: true,
  );
  for (final match in pattern.allMatches(file.readAsStringSync())) {
    final props = match.group(3)!;
    final name = RegExp("name:\\s*'?([^,'}]+)").firstMatch(props);
    if (name == null) continue;
    final x = double.tryParse(match.group(1)!);
    final y = double.tryParse(match.group(2)!);
    if (x == null || y == null) continue;
    result[name.group(1)!.trim()] = (x: x, y: y);
  }
  return result;
}
