abstract class BackendSupervisor {
  List<String> get history;
  Stream<String> get logStream;
  Future<void> stop();
}

Future<BackendSupervisor?> bootstrapBackend({
  required String apiUrl,
  bool autoStart = true,
}) async {
  if (autoStart) {
    throw UnsupportedError(
      '웹(Chrome)에서는 보안상 Open-RMF 프로세스를 자동 실행할 수 없습니다. '
      'flutter run 실행 후 Linux 장치를 선택하거나 '
      'flutter run -d linux를 사용하세요.',
    );
  }
  return null;
}
