import 'dart:io';

import 'workspace_paths_io.dart';

/// 상용 배포에서 요구하는 고정 디렉터리 구조를 검사한다.
///
/// 실행 환경이 달라져도 ROS 작업공간이 사용자 홈 여기저기에 흩어지지 않도록
/// 모두 `~/robosapiens` 아래에 둔다. 링크는 원본 위치를 숨겨 패키징할 때 파일이
/// 빠질 수 있으므로 허용하지 않는다.
Future<List<String>> workspaceLayoutWarnings({
  String? homePath,
  String? detectedRootPath,
}) async {
  final home = homePath ?? Platform.environment['HOME'];
  if (home == null || home.isEmpty) {
    return const ['HOME 환경 변수가 없어 ~/robosapiens 구조를 확인할 수 없습니다.'];
  }

  final expectedRoot = '$home/robosapiens';
  final detectedRoot = detectedRootPath ?? robosapiensRoot().absolute.path;
  final warnings = <String>[];
  if (Directory(expectedRoot).absolute.path !=
      Directory(detectedRoot).absolute.path) {
    warnings.add('프로그램 루트가 $expectedRoot가 아닙니다: $detectedRoot');
  }

  void requireDirectory(String relative, {String? marker}) {
    final path = '$expectedRoot/$relative';
    final type = FileSystemEntity.typeSync(path, followLinks: false);
    if (type == FileSystemEntityType.link) {
      warnings.add('$path 는 심볼릭 링크입니다. 실제 디렉터리를 이 위치로 옮겨주세요.');
      return;
    }
    if (type != FileSystemEntityType.directory) {
      warnings.add('필수 디렉터리가 없습니다: $path');
      return;
    }
    if (marker != null && !File('$path/$marker').existsSync()) {
      warnings.add('$path 의 구조가 올바르지 않습니다. 누락: $marker');
    }
  }

  final rootType = FileSystemEntity.typeSync(expectedRoot, followLinks: false);
  if (rootType == FileSystemEntityType.link) {
    warnings.add('$expectedRoot 는 심볼릭 링크입니다. 실제 프로그램 디렉터리를 이 위치에 두세요.');
  } else if (rootType != FileSystemEntityType.directory) {
    warnings.add('RoboSapiens 프로그램 루트가 없습니다: $expectedRoot');
  }

  // 자식 작업공간이 실제 디렉터리여도 부모인 robot_model 자체가 링크일 수 있다.
  // 각 작업공간만 검사하면 이 우회를 놓치므로 상위 경로도 별도로 확인한다.
  requireDirectory('robot_model');
  requireDirectory('rmf_ws', marker: 'install/setup.bash');
  requireDirectory(
    'robot_model/pinky_pro',
    marker: 'pinky_description/package.xml',
  );
  requireDirectory(
    'robot_model/open_manipulator',
    marker: 'src/open_manipulator/open_manipulator_description/package.xml',
  );

  for (final legacy in [
    '$home/rmf_ws',
    '$expectedRoot/pinky_pro',
    '$expectedRoot/open_manipulator',
  ]) {
    if (FileSystemEntity.typeSync(legacy, followLinks: false) !=
        FileSystemEntityType.notFound) {
      warnings.add('이전 위치를 사용하지 마세요: $legacy');
    }
  }
  return warnings;
}
