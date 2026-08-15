/// 웹 빌드용 대체 구현. 브라우저에서는 프로세스를 띄울 수 없다.
library;

import 'simulation_backend.dart';

export 'simulation_backend.dart';

class RmfRunResult {
  const RmfRunResult({required this.success, required this.message});
  final bool success;
  final String message;
}

String? get runningProjectName => null;

String? debugProjectRootOverride;

Future<String?> refreshRunningProject() async => null;

Future<RmfRunResult> startProject(
  String mapName, {
  SimulationBackend backend = SimulationBackend.gazebo,
  bool gazeboGui = false,
  bool rviz = false,
}) async => const RmfRunResult(
  success: false,
  message: '웹 빌드에서는 프로젝트를 띄울 수 없습니다. Linux 데스크톱 앱에서 실행하세요.',
);

Future<RmfRunResult> stopProject([String? mapName]) async =>
    const RmfRunResult(success: false, message: '웹 빌드에서는 중지할 것이 없습니다.');

class OrphanedProject {
  const OrphanedProject({required this.mapName, required this.pgid});
  final String mapName;
  final int pgid;
}

Future<List<OrphanedProject>> findOrphanedProjects() async => const [];

Future<List<OrphanedProject>> findRunningProjects() async => const [];
