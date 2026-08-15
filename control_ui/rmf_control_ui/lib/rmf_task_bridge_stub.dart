/// 웹 빌드용 대체 구현. 브라우저에서는 `ros2` 도 `python3` 도 실행할 수 없다.
library;

import 'dart:async';

import 'rmf_task_models.dart';

export 'rmf_task_models.dart';

class RmfTaskBridge {
  RmfTaskBridge._();

  static final RmfTaskBridge instance = RmfTaskBridge._();

  Stream<RmfTaskProgress> get progress => const Stream.empty();

  bool get watching => false;

  String? get watchedFleet => null;

  Future<RmfTaskSubmission> submit({
    required String mapDirectory,
    required String mapName,
    required String requestJson,
  }) async => const RmfTaskSubmission(
    accepted: false,
    message: '웹에서는 RMF 에 작업을 넣을 수 없습니다.',
  );

  Future<void> watch(String fleetName) async {}

  Future<void> stop() async {}
}
