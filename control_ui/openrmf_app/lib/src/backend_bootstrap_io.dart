import 'dart:async';
import 'dart:convert';
import 'dart:io';

abstract class BackendSupervisor {
  List<String> get history;
  Stream<String> get logStream;
  Future<void> stop();
}

class _ProcessBackendSupervisor implements BackendSupervisor {
  _ProcessBackendSupervisor(this.process, this._history, this._logController);

  final Process process;
  final List<String> _history;
  final StreamController<String> _logController;
  bool _stopped = false;

  @override
  List<String> get history => List.unmodifiable(_history);

  @override
  Stream<String> get logStream => _logController.stream;

  @override
  Future<void> stop() async {
    if (_stopped) return;
    _stopped = true;
    process.kill(ProcessSignal.sigint);
    try {
      await process.exitCode.timeout(const Duration(seconds: 15));
    } on TimeoutException {
      process.kill(ProcessSignal.sigterm);
    }
    await _logController.close();
  }
}

Future<BackendSupervisor?> bootstrapBackend({
  required String apiUrl,
  bool autoStart = true,
}) async {
  if (!autoStart || !Platform.isLinux || await _apiOnline(apiUrl)) return null;

  final script = _findLauncher();
  if (script == null) {
    throw StateError(
      'openrmf 실행 스크립트를 찾을 수 없습니다. '
      'RMF_ROOT 환경 변수에 robosapiens 경로를 지정하세요.',
    );
  }

  final process = await Process.start(
    script.path,
    const ['--backend-only'],
    workingDirectory: script.parent.parent.parent.path,
    environment: {
      ...Platform.environment,
      'RMF_API_URL': apiUrl,
      'RMF_PARENT_PID': '$pid',
      'RMF_HEADLESS': Platform.environment['RMF_HEADLESS'] ?? 'true',
    },
  );
  final history = <String>[];
  final logController = StreamController<String>.broadcast();
  void addLog(String line) {
    history.add(line);
    if (history.length > 1000) history.removeAt(0);
    logController.add(line);
  }

  final supervisor = _ProcessBackendSupervisor(process, history, logController);
  final ready = Completer<void>();
  final errorLines = <String>[];

  process.stdout.transform(utf8.decoder).transform(const LineSplitter()).listen(
    (line) {
      final formatted = '[openrmf] $line';
      stdout.writeln(formatted);
      addLog(formatted);
      if (line == 'RMF_BACKEND_READY' && !ready.isCompleted) ready.complete();
    },
  );
  process.stderr.transform(utf8.decoder).transform(const LineSplitter()).listen(
    (line) {
      final formatted = '[openrmf] $line';
      stderr.writeln(formatted);
      addLog(formatted);
      errorLines.add(line);
      if (errorLines.length > 12) errorLines.removeAt(0);
    },
  );
  unawaited(
    process.exitCode.then((code) {
      if (!ready.isCompleted) {
        ready.completeError(
          StateError(
            'Open-RMF 백엔드가 준비 전에 종료됐습니다 ($code).\n'
            '${errorLines.join('\n')}',
          ),
        );
      }
    }),
  );

  try {
    await ready.future.timeout(const Duration(seconds: 180));
    return supervisor;
  } catch (_) {
    await supervisor.stop();
    rethrow;
  }
}

Future<bool> _apiOnline(String apiUrl) async {
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 2);
  try {
    final base = Uri.parse(apiUrl.replaceFirst(RegExp(r'/$'), ''));
    final request = await client.getUrl(base.resolve('/time'));
    final response = await request.close().timeout(const Duration(seconds: 2));
    await response.drain<void>();
    return response.statusCode >= 200 && response.statusCode < 300;
  } catch (_) {
    return false;
  } finally {
    client.close(force: true);
  }
}

File? _findLauncher() {
  final candidates = <Directory>[];
  final configured = Platform.environment['RMF_ROOT'];
  if (configured != null && configured.isNotEmpty) {
    candidates.add(Directory(configured));
  }
  candidates.addAll(_ancestors(Directory.current));
  candidates.addAll(_ancestors(File(Platform.resolvedExecutable).parent));

  for (final root in candidates) {
    final script = File(
      '${root.path}${Platform.pathSeparator}openrmf'
      '${Platform.pathSeparator}scripts'
      '${Platform.pathSeparator}run_office_flutter.sh',
    );
    if (script.existsSync()) return script;
  }
  return null;
}

Iterable<Directory> _ancestors(Directory start) sync* {
  var current = start.absolute;
  for (var i = 0; i < 12; i++) {
    yield current;
    final parent = current.parent;
    if (parent.path == current.path) break;
    current = parent;
  }
}
