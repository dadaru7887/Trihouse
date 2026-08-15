import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';

import 'models.dart';
import 'rmf_api.dart';
import 'trajectory_client.dart';
import 'backend_bootstrap.dart';

class RmfController extends ChangeNotifier {
  RmfController({
    required String apiUrl,
    required String apiToken,
    required String trajectoryUrl,
    BackendSupervisor? backend,
  }) : _api = RmfApi(baseUrl: apiUrl, token: apiToken),
       _trajectory = RmfTrajectoryClient(url: trajectoryUrl, token: apiToken),
       _backend = backend {
    if (backend != null) {
      appLogs.addAll(backend.history);
      _backendLogSubscription = backend.logStream.listen(addLog);
    }
  }

  final RmfApi _api;
  final RmfTrajectoryClient _trajectory;
  final BackendSupervisor? _backend;
  StreamSubscription<String>? _backendLogSubscription;
  Timer? _timer;
  bool _refreshing = false;
  final Set<String> _dismissedTaskIds = {};

  RmfBuildingMap? building;
  List<RmfRobot> robots = const [];
  List<RmfTask> tasks = const [];
  List<RmfDoor> doors = const [];
  List<RmfLift> lifts = const [];
  List<RmfWorkcell> workcells = const [];
  List<RmfAlert> alerts = const [];
  List<RmfTrajectory> trajectories = const [];
  List<Map<String, dynamic>> scheduledTasks = const [];
  Uint8List? mapBytes;
  ui.Image? decodedMap;
  String? error;
  DateTime? lastUpdated;
  String? selectedRobot;
  int selectedLevel = 0;
  bool commandInProgress = false;
  String? notice;
  final List<String> appLogs = [];

  String get apiUrl => _api.baseUri.toString();
  bool get connected => error == null && lastUpdated != null;
  RmfLevel? get level {
    final levels = building?.levels ?? const <RmfLevel>[];
    if (levels.isEmpty) return null;
    return levels[selectedLevel.clamp(0, levels.length - 1)];
  }

  Iterable<RmfRobot> get visibleRobots {
    final currentLevel = level?.name.trim().toLowerCase();
    if (currentLevel == null) return const [];
    final matched = robots
        .where((robot) => robot.level.trim().toLowerCase() == currentLevel)
        .toList();
    if (matched.isNotEmpty || (building?.levels.length ?? 0) > 1) {
      return matched;
    }
    // Some fleet adapters omit or vary the map name. For a single-level
    // building there is no ambiguity, so keep the robots visible.
    return robots;
  }

  void start() {
    addLog('[app] Open-RMF 관제 앱을 시작합니다.');
    refresh();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) => refresh());
  }

  Future<void> refresh() async {
    if (_refreshing) return;
    _refreshing = true;
    try {
      await _api.checkConnection();
      final coreResults = await Future.wait([
        _api.getBuildingMap(),
        _api.getRobots(),
        _api.getTasks(),
      ]);
      final nextBuilding = coreResults[0] as RmfBuildingMap;
      final nextImage = nextBuilding.levels.isEmpty
          ? null
          : nextBuilding
                .levels[selectedLevel.clamp(0, nextBuilding.levels.length - 1)]
                .image;
      final imageChanged =
          nextImage?.url.isNotEmpty == true &&
          nextImage?.url != level?.image?.url;
      building = nextBuilding;
      robots = coreResults[1] as List<RmfRobot>;
      final receivedTasks = coreResults[2] as List<RmfTask>;
      tasks = receivedTasks
          .where((task) => !_dismissedTaskIds.contains(task.id))
          .toList();
      addLog(
        '[api] 지도 ${nextBuilding.name}, 로봇 ${robots.length}대, '
        '태스크 ${tasks.length}건',
        deduplicate: true,
      );
      error = null;
      lastUpdated = DateTime.now();
      notifyListeners();

      doors = await _optional(_api.getDoors, doors);
      lifts = await _optional(_api.getLifts, lifts);
      workcells = await _optional(_api.getWorkcells, workcells);
      alerts = await _optional(_api.getAlerts, alerts);
      scheduledTasks = await _optional(_api.getScheduledTasks, scheduledTasks);
      if (nextBuilding.levels.isNotEmpty) {
        trajectories = await _trajectory.getTrajectories(
          nextBuilding
              .levels[selectedLevel.clamp(0, nextBuilding.levels.length - 1)]
              .name,
        );
      }
      if ((mapBytes == null || imageChanged) && nextImage != null) {
        await _loadMap(nextImage.url);
      }
    } catch (exception) {
      error = exception.toString();
      addLog('[error] $exception', deduplicate: true);
    } finally {
      _refreshing = false;
      notifyListeners();
    }
  }

  Future<List<T>> _optional<T>(
    Future<List<T>> Function() request,
    List<T> previous,
  ) async {
    try {
      return await request();
    } catch (exception) {
      debugPrint('Optional RMF endpoint failed: $exception');
      return previous;
    }
  }

  Future<void> _loadMap(String url) async {
    final bytes = await _api.getBytes(url);
    final codec = await ui.instantiateImageCodec(bytes);
    final frame = await codec.getNextFrame();
    codec.dispose();
    final image = frame.image;
    decodedMap?.dispose();
    mapBytes = bytes;
    decodedMap = image;
  }

  void selectRobot(String? robot) {
    selectedRobot = robot;
    notifyListeners();
  }

  Future<void> dispatchTask(Map<String, dynamic> request) =>
      _command('태스크를 요청했습니다.', () => _api.dispatchTask(request));

  Future<void> scheduleTask(
    Map<String, dynamic> request,
    String period,
    String at,
  ) =>
      _command('반복 태스크를 예약했습니다.', () => _api.scheduleTask(request, period, at));

  Future<void> cancelTask(String taskId) =>
      _command('태스크 취소를 요청했습니다.', () => _api.cancelTask(taskId));

  void dismissCanceledTask(RmfTask task) {
    if (!task.isCanceled) return;
    _dismissedTaskIds.add(task.id);
    tasks = tasks.where((item) => item.id != task.id).toList();
    notice = '취소된 태스크를 목록에서 삭제했습니다.';
    addLog('[command] 취소 태스크 ${task.id}을(를) 목록에서 삭제했습니다.');
    notifyListeners();
  }

  Future<void> setDoor(RmfDoor door, int mode) => _command(
    '${door.name} 도어 제어를 요청했습니다.',
    () => _api.requestDoor(door.name, mode),
  );

  Future<void> callLift(
    RmfLift lift,
    String floor, {
    int requestType = 1,
    int doorMode = 2,
  }) => _command(
    '${lift.name} 리프트를 $floor 층으로 요청했습니다.',
    () => _api.requestLift(
      name: lift.name,
      destination: floor,
      requestType: requestType,
      doorMode: doorMode,
    ),
  );

  Future<void> decommissionRobot(
    RmfRobot robot, {
    bool reassignTasks = true,
    bool allowIdleBehavior = true,
  }) => _command(
    '${robot.name} 운행 제외를 요청했습니다.',
    () => _api.decommissionRobot(
      robot,
      reassignTasks: reassignTasks,
      allowIdleBehavior: allowIdleBehavior,
    ),
  );

  Future<void> recommissionRobot(RmfRobot robot) => _command(
    '${robot.name} 운행 복귀를 요청했습니다.',
    () => _api.recommissionRobot(robot),
  );

  Future<void> respondToAlert(RmfAlert alert, String response) =>
      _command('알림에 응답했습니다.', () => _api.respondToAlert(alert.id, response));

  Future<void> unlockMutex(RmfRobot robot, String group) => _command(
    '$group mutex group 해제를 요청했습니다.',
    () => _api.unlockMutex(robot, group),
  );

  Future<void> deleteScheduledTask(int id) =>
      _command('예약 태스크를 삭제했습니다.', () => _api.deleteScheduledTask(id));

  Future<Map<String, dynamic>?> getTaskLog(String taskId) =>
      _api.getTaskLog(taskId);

  Future<void> _command(
    String successMessage,
    Future<void> Function() operation,
  ) async {
    if (commandInProgress) return;
    commandInProgress = true;
    notice = null;
    notifyListeners();
    try {
      addLog('[command] 요청을 전송합니다.');
      await operation();
      notice = successMessage;
      addLog('[command] $successMessage');
      await refresh();
    } catch (exception) {
      notice = '요청 실패: $exception';
      addLog('[error] $notice');
    } finally {
      commandInProgress = false;
      notifyListeners();
    }
  }

  void clearNotice() {
    notice = null;
    notifyListeners();
  }

  void addLog(String line, {bool deduplicate = false}) {
    final timestamp = DateTime.now().toLocal().toIso8601String().substring(
      11,
      19,
    );
    final entry = '$timestamp $line';
    if (deduplicate &&
        appLogs.isNotEmpty &&
        appLogs.last.replaceFirst(RegExp(r'^\d{2}:\d{2}:\d{2} '), '') == line) {
      return;
    }
    appLogs.add(entry);
    if (appLogs.length > 1000) appLogs.removeAt(0);
    notifyListeners();
  }

  void clearLogs() {
    appLogs.clear();
    addLog('[app] 로그를 지웠습니다.');
  }

  Future<void> selectLevel(int index) async {
    if (index == selectedLevel) return;
    selectedLevel = index;
    mapBytes = null;
    decodedMap?.dispose();
    decodedMap = null;
    notifyListeners();
    await refresh();
  }

  @override
  void dispose() {
    _timer?.cancel();
    decodedMap?.dispose();
    _api.close();
    _trajectory.close();
    _backendLogSubscription?.cancel();
    _backend?.stop();
    super.dispose();
  }
}
