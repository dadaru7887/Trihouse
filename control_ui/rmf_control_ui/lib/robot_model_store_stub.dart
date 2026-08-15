class RobotModelInfo {
  const RobotModelInfo({
    required this.name,
    required this.path,
    required this.packageCount,
    required this.isGitRepository,
  });

  final String name;
  final String path;
  final int packageCount;
  final bool isGitRepository;
}

const _unsupported = '웹에서는 로봇 모델 폴더를 관리할 수 없습니다. Linux 앱을 사용하세요.';

Future<List<RobotModelInfo>> listRobotModels() async => const [];

Future<RobotModelInfo> importRobotModelFromGit(String url, {String? name}) =>
    throw UnsupportedError(_unsupported);

Future<RobotModelInfo> importRobotModelFromZip(
  String zipPath, {
  String? name,
}) => throw UnsupportedError(_unsupported);
