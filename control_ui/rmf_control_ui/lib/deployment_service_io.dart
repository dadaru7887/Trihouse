import 'dart:io';
import 'dart:typed_data';

import 'rmf_project_config.dart' show defaultRosDomainId;

class MapDeploymentResult {
  const MapDeploymentResult({required this.success, required this.output});
  final bool success;
  final String output;
}

Directory? _findProjectRoot() {
  final configuredRoot = Platform.environment['RMF_ROOT'];
  if (configuredRoot != null && configuredRoot.isNotEmpty) {
    final directory = Directory(configuredRoot).absolute;
    if (File('${directory.path}/openrmf/scripts/deploy_map.sh').existsSync() &&
        Directory('${directory.path}/rmf_maps').existsSync()) {
      return directory;
    }
  }
  var directory = Directory.current.absolute;
  for (var i = 0; i < 8; i++) {
    if (File('${directory.path}/openrmf/scripts/deploy_map.sh').existsSync() &&
        Directory('${directory.path}/rmf_maps').existsSync()) {
      return directory;
    }
    final parent = directory.parent;
    if (parent.path == directory.path) break;
    directory = parent;
  }
  return null;
}

Future<MapDeploymentResult> deployMapProject({
  required String mapName,
  required String yaml,
  required String imageName,
  required Uint8List imageBytes,
  int rosDomainId = defaultRosDomainId,
}) async {
  final root = _findProjectRoot();
  if (root == null) {
    return const MapDeploymentResult(
      success: false,
      output: '프로젝트 루트(openrmf/scripts 및 rmf_maps)를 찾을 수 없습니다.',
    );
  }
  final temporary = await Directory.systemTemp.createTemp('robosapiens-map-');
  try {
    final yamlFile = File('${temporary.path}/$mapName.building.yaml');
    final imageFile = File('${temporary.path}/$imageName');
    await yamlFile.writeAsString(yaml, flush: true);
    await imageFile.writeAsBytes(imageBytes, flush: true);
    final result = await Process.run(
      'bash',
      [
        '${root.path}/openrmf/scripts/deploy_map.sh',
        yamlFile.path,
        imageFile.path,
        mapName,
      ],
      workingDirectory: root.path,
      runInShell: false,
      // 도메인을 손으로 넘긴다. 앱은 비대화형 셸로 스크립트를 돌리므로
      // `~/.bashrc` 의 `export ROS_DOMAIN_ID` 를 못 읽는다. 그대로 두면 앱이
      // 띄운 map server 는 0 번 도메인에 혼자 뜨고, 터미널에서 돌고 있는
      // 시뮬레이터는 새 지도를 영영 못 받는다 — 오류는 하나도 안 난다.
      environment: {'ROS_DOMAIN_ID': '$rosDomainId'},
    );
    final output = [result.stdout, result.stderr]
        .map((value) => value.toString().trim())
        .where((value) => value.isNotEmpty)
        .join('\n');
    return MapDeploymentResult(success: result.exitCode == 0, output: output);
  } catch (error) {
    return MapDeploymentResult(success: false, output: error.toString());
  } finally {
    try {
      await temporary.delete(recursive: true);
    } on FileSystemException {
      // The operating system may still be releasing a subprocess handle.
    }
  }
}
