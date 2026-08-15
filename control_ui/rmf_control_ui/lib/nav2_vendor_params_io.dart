/// 벤더의 Nav2 파라미터 원본을 읽는다.
///
/// `pinky_navigation` 은 이 저장소에 함께 두는 벤더 패키지라 커밋되지 않는다.
/// 없을 수도 있으므로 못 찾으면 조용히 null 을 돌려주고, 부르는 쪽이 그 사실을
/// 사람에게 알린다.
library;

import 'dart:io';

/// 환경 변수로 자리를 바꿀 수 있다. 벤더 패키지를 다른 데 두는 사람도 있다.
const String nav2ParamsEnvironmentKey = 'PINKY_NAV2_PARAMS';

const String _defaultRelativePath =
    'robot_model/pinky_pro/pinky_navigation/params/nav2_params.yaml';

Directory? _findProjectRoot() {
  var directory = Directory.current.absolute;
  for (var i = 0; i < 8; i++) {
    if (Directory('${directory.path}/rmf_maps').existsSync()) return directory;
    final parent = directory.parent;
    if (parent.path == directory.path) break;
    directory = parent;
  }
  return null;
}

/// 벤더 파일의 자리. 못 찾으면 null.
String? findVendorNav2ParamsPath() {
  final configured = Platform.environment[nav2ParamsEnvironmentKey];
  if (configured != null && configured.isNotEmpty) {
    return File(configured).existsSync() ? configured : null;
  }
  final root = _findProjectRoot() ?? Directory.current.absolute;
  final path = '${root.path}/$_defaultRelativePath';
  return File(path).existsSync() ? path : null;
}

/// 벤더 파일의 내용. 못 찾으면 null.
String? readVendorNav2Params() {
  final path = findVendorNav2ParamsPath();
  if (path == null) return null;
  try {
    return File(path).readAsStringSync();
  } catch (_) {
    return null;
  }
}
