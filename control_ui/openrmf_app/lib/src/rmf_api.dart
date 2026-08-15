import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'models.dart';

class RmfApiException implements Exception {
  const RmfApiException(this.message);
  final String message;

  @override
  String toString() => message;
}

class RmfApi {
  RmfApi({required String baseUrl, required this.token, http.Client? client})
    : baseUri = Uri.parse(baseUrl.replaceFirst(RegExp(r'/$'), '')),
      _client = client ?? http.Client();

  final Uri baseUri;
  final String token;
  final http.Client _client;
  Map<String, String> get _headers =>
      token.isEmpty ? const {} : {'Authorization': 'Bearer $token'};

  Future<RmfBuildingMap> getBuildingMap() async =>
      RmfBuildingMap.fromJson(await _getObject('/building_map'));

  Future<void> checkConnection() async {
    final uri = baseUri.resolve('/time');
    try {
      final response = await _client
          .get(uri)
          .timeout(const Duration(seconds: 5));
      _check(response, uri);
    } on RmfApiException {
      rethrow;
    } catch (exception) {
      throw RmfApiException(
        'rmf-web API에 연결할 수 없습니다: ${baseUri.host}:${baseUri.port}',
      );
    }
  }

  Future<List<RmfRobot>> getRobots() async =>
      RmfRobot.fromFleetList(await _getList('/fleets'));

  Future<List<RmfTask>> getTasks() async =>
      (await _getList('/tasks'))
          .whereType<Map>()
          .map((json) => RmfTask.fromJson(Map<String, dynamic>.from(json)))
          .toList()
        ..sort((a, b) {
          final left = a.requestedAt ?? DateTime.fromMillisecondsSinceEpoch(0);
          final right = b.requestedAt ?? DateTime.fromMillisecondsSinceEpoch(0);
          return right.compareTo(left);
        });

  Future<List<RmfDoor>> getDoors() async {
    final descriptors = await _getOptionalList('/doors');
    return Future.wait(
      descriptors.whereType<Map>().map((raw) async {
        final descriptor = Map<String, dynamic>.from(raw);
        final name = descriptor['name']?.toString() ?? '';
        final state = name.isEmpty
            ? null
            : await _getOptionalObject(
                '/doors/${Uri.encodeComponent(name)}/state',
              );
        return RmfDoor.fromJson(descriptor, state);
      }),
    );
  }

  Future<List<RmfLift>> getLifts() async {
    final descriptors = await _getOptionalList('/lifts');
    return Future.wait(
      descriptors.whereType<Map>().map((raw) async {
        final descriptor = Map<String, dynamic>.from(raw);
        final name = descriptor['name']?.toString() ?? '';
        final state = name.isEmpty
            ? null
            : await _getOptionalObject(
                '/lifts/${Uri.encodeComponent(name)}/state',
              );
        return RmfLift.fromJson(descriptor, state);
      }),
    );
  }

  Future<List<RmfWorkcell>> getWorkcells() async {
    final result = <RmfWorkcell>[];
    for (final entry in const {
      'dispenser': '/dispensers',
      'ingestor': '/ingestors',
    }.entries) {
      final descriptors = await _getOptionalList(entry.value);
      for (final raw in descriptors.whereType<Map>()) {
        final descriptor = Map<String, dynamic>.from(raw);
        final id = descriptor['guid']?.toString() ?? '';
        final state = id.isEmpty
            ? null
            : await _getOptionalObject(
                '${entry.value}/${Uri.encodeComponent(id)}/state',
              );
        result.add(RmfWorkcell.fromJson(entry.key, state ?? descriptor));
      }
    }
    return result;
  }

  Future<List<RmfAlert>> getAlerts() async =>
      (await _getOptionalList('/alerts/unresponded_requests'))
          .whereType<Map>()
          .map((e) => RmfAlert.fromJson(Map<String, dynamic>.from(e)))
          .toList();

  Future<List<Map<String, dynamic>>> getScheduledTasks() async {
    final now = DateTime.now().toUtc();
    final start = now.add(const Duration(days: 366));
    final until = now.subtract(const Duration(days: 366));
    final data = await _getOptionalList(
      '/scheduled_tasks?start_before=${Uri.encodeQueryComponent(start.toIso8601String())}'
      '&until_after=${Uri.encodeQueryComponent(until.toIso8601String())}'
      '&limit=100&offset=0',
    );
    return data
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
  }

  Future<Map<String, dynamic>?> getTaskLog(String taskId) =>
      _getOptionalObject('/tasks/${Uri.encodeComponent(taskId)}/log');

  Future<void> dispatchTask(Map<String, dynamic> request) => _post(
    '/tasks/dispatch_task',
    {'type': 'dispatch_task_request', 'request': request},
  );

  Future<void> scheduleTask(
    Map<String, dynamic> request,
    String period,
    String at,
  ) => _post('/scheduled_tasks', {
    'task_request': request,
    'schedules': [
      {'period': period, 'at': at},
    ],
    'except_dates': <String>[],
  });

  Future<void> cancelTask(String taskId) => _post('/tasks/cancel_task', {
    'type': 'cancel_task_request',
    'task_id': taskId,
    'labels': ['app=openrmf_app'],
  });

  Future<void> requestDoor(String name, int mode) =>
      _post('/doors/${Uri.encodeComponent(name)}/request', {'mode': mode});

  Future<void> requestLift({
    required String name,
    required String destination,
    required int requestType,
    required int doorMode,
  }) => _post('/lifts/${Uri.encodeComponent(name)}/request', {
    'destination': destination,
    'request_type': requestType,
    'door_mode': doorMode,
    'additional_session_ids': <String>[],
  });

  Future<void> decommissionRobot(
    RmfRobot robot, {
    required bool reassignTasks,
    required bool allowIdleBehavior,
  }) => _post(
    '/fleets/${Uri.encodeComponent(robot.fleet)}/decommission'
    '?robot_name=${Uri.encodeQueryComponent(robot.name)}'
    '&reassign_tasks=$reassignTasks'
    '&allow_idle_behavior=$allowIdleBehavior',
    null,
  );

  Future<void> recommissionRobot(RmfRobot robot) => _post(
    '/fleets/${Uri.encodeComponent(robot.fleet)}/recommission'
    '?robot_name=${Uri.encodeQueryComponent(robot.name)}',
    null,
  );

  Future<void> respondToAlert(String id, String response) => _post(
    '/alerts/request/${Uri.encodeComponent(id)}/respond'
    '?response=${Uri.encodeQueryComponent(response)}',
    null,
  );

  Future<void> unlockMutex(RmfRobot robot, String group) => _post(
    '/fleets/${Uri.encodeComponent(robot.fleet)}/unlock_mutex_group'
    '?robot_name=${Uri.encodeQueryComponent(robot.name)}'
    '&mutex_group=${Uri.encodeQueryComponent(group)}',
    null,
  );

  Future<void> deleteScheduledTask(int id) => _delete('/scheduled_tasks/$id');

  Future<Uint8List> getBytes(String location) async {
    final uri = resolve(location);
    final response = await _client
        .get(uri, headers: _headers)
        .timeout(const Duration(seconds: 5));
    _check(response, uri);
    return response.bodyBytes;
  }

  Uri resolve(String location) {
    final parsed = Uri.parse(location);
    if (parsed.hasScheme) {
      if (parsed.host == 'localhost' || parsed.host == '127.0.0.1') {
        return parsed.replace(host: baseUri.host, port: baseUri.port);
      }
      return parsed;
    }
    return baseUri.resolve(location);
  }

  Future<Map<String, dynamic>> _getObject(String path) async {
    final uri = baseUri.resolve(path);
    late final http.Response response;
    try {
      response = await _client
          .get(uri, headers: _headers)
          .timeout(const Duration(seconds: 5));
    } catch (exception) {
      throw RmfApiException(
        'rmf-web API에 연결할 수 없습니다: ${baseUri.host}:${baseUri.port}',
      );
    }
    _check(response, uri);
    final decoded = jsonDecode(utf8.decode(response.bodyBytes));
    if (decoded is! Map) throw RmfApiException('$path 응답 형식이 올바르지 않습니다.');
    return Map<String, dynamic>.from(decoded);
  }

  Future<List<dynamic>> _getList(String path) async {
    final uri = baseUri.resolve(path);
    late final http.Response response;
    try {
      response = await _client
          .get(uri, headers: _headers)
          .timeout(const Duration(seconds: 5));
    } catch (exception) {
      throw RmfApiException(
        'rmf-web API에 연결할 수 없습니다: ${baseUri.host}:${baseUri.port}',
      );
    }
    _check(response, uri);
    final decoded = jsonDecode(utf8.decode(response.bodyBytes));
    if (decoded is! List) throw RmfApiException('$path 응답 형식이 올바르지 않습니다.');
    return decoded;
  }

  Future<List<dynamic>> _getOptionalList(String path) async {
    try {
      return await _getList(path);
    } on RmfApiException catch (exception) {
      if (exception.message.contains('(404)')) return const [];
      rethrow;
    }
  }

  Future<Map<String, dynamic>?> _getOptionalObject(String path) async {
    try {
      return await _getObject(path);
    } on RmfApiException catch (exception) {
      if (exception.message.contains('(404)')) return null;
      rethrow;
    }
  }

  Future<void> _post(String path, Object? body) async {
    final uri = baseUri.resolve(path);
    late final http.Response response;
    try {
      response = await _client
          .post(
            uri,
            headers: {
              ..._headers,
              if (body != null) 'Content-Type': 'application/json',
            },
            body: body == null ? null : jsonEncode(body),
          )
          .timeout(const Duration(seconds: 10));
    } catch (_) {
      throw RmfApiException('rmf-web API 요청을 전송할 수 없습니다.');
    }
    _check(response, uri);
  }

  Future<void> _delete(String path) async {
    final uri = baseUri.resolve(path);
    late final http.Response response;
    try {
      response = await _client
          .delete(uri, headers: _headers)
          .timeout(const Duration(seconds: 10));
    } catch (_) {
      throw RmfApiException('rmf-web API 요청을 전송할 수 없습니다.');
    }
    _check(response, uri);
  }

  void _check(http.Response response, Uri uri) {
    if (response.statusCode >= 200 && response.statusCode < 300) return;
    if (response.statusCode == 401) {
      throw const RmfApiException('rmf-web 인증에 실패했습니다. RMF_API_TOKEN을 확인하세요.');
    }
    if (response.statusCode == 404 && uri.path == '/building_map') {
      throw const RmfApiException(
        'API는 연결됐지만 building map이 없습니다. office launch를 먼저 실행하세요.',
      );
    }
    throw RmfApiException('${uri.path} 요청 실패 (${response.statusCode})');
  }

  void close() => _client.close();
}
