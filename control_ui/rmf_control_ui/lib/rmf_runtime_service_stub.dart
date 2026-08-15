/// 웹 빌드용 대체 구현. 브라우저에서는 ros2 나 셸 스크립트를 실행할 수 없다.
library;

import 'rmf_runtime_models.dart';

Future<RmfRuntimeStatus> probeRmfRuntime() async => const RmfRuntimeStatus(
  available: false,
  nodes: [],
  message: '웹 빌드에서는 ROS 노드를 확인할 수 없습니다. Linux 데스크톱 앱에서 실행하세요.',
);

Future<RmfStopResult> stopRmfBackend({String? mapName}) async =>
    const RmfStopResult(success: false, output: '웹 빌드에서는 백엔드를 내릴 수 없습니다.');

Future<List<String>> runningBackendProjects() async => const [];

Future<List<String>> gazeboRunningProjects() async => const [];

Future<String> sweepOrphanBackends(String rootPath) async =>
    '웹 빌드에서는 프로세스를 쓸어낼 수 없습니다.';

Future<RmfFleetSnapshot> probeFleetStates({
  required int rosDomainId,
  Duration timeout = const Duration(seconds: 8),
}) async => const RmfFleetSnapshot(
  reachable: false,
  robots: {},
  message: '웹 빌드에서는 ROS 토픽을 읽을 수 없습니다.',
);

Future<int?> probeClockPublishers({
  required int rosDomainId,
  Duration timeout = const Duration(seconds: 12),
}) async => null;
