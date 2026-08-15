import 'dart:math' as math;

class RmfAffineImage {
  const RmfAffineImage({
    required this.url,
    required this.xOffset,
    required this.yOffset,
    required this.scale,
  });

  final String url;
  final double xOffset;
  final double yOffset;
  final double scale;

  factory RmfAffineImage.fromJson(Map<String, dynamic> json) => RmfAffineImage(
    url: json['data'] as String? ?? '',
    xOffset: _number(json['x_offset']),
    yOffset: _number(json['y_offset']),
    scale: _number(json['scale'], fallback: 1),
  );
}

class RmfGraphVertex {
  const RmfGraphVertex({required this.x, required this.y, required this.name});

  final double x;
  final double y;
  final String name;

  factory RmfGraphVertex.fromJson(Map<String, dynamic> json) => RmfGraphVertex(
    x: _number(json['x']),
    y: _number(json['y']),
    name: json['name'] as String? ?? '',
  );
}

class RmfGraphEdge {
  const RmfGraphEdge({required this.from, required this.to});

  final int from;
  final int to;

  factory RmfGraphEdge.fromJson(Map<String, dynamic> json) => RmfGraphEdge(
    from: (json['v1_idx'] as num?)?.toInt() ?? 0,
    to: (json['v2_idx'] as num?)?.toInt() ?? 0,
  );
}

class RmfLevel {
  const RmfLevel({
    required this.name,
    required this.image,
    required this.vertices,
    required this.edges,
  });

  final String name;
  final RmfAffineImage? image;
  final List<RmfGraphVertex> vertices;
  final List<RmfGraphEdge> edges;

  List<String> get waypointNames =>
      vertices
          .map((vertex) => vertex.name)
          .where((name) => name.isNotEmpty)
          .toSet()
          .toList()
        ..sort();

  factory RmfLevel.fromJson(Map<String, dynamic> json) {
    final images = _maps(json['images']);
    final graphs = _maps(json['nav_graphs']);
    final vertices = <RmfGraphVertex>[];
    final edges = <RmfGraphEdge>[];
    for (final graph in graphs) {
      final offset = vertices.length;
      vertices.addAll(_maps(graph['vertices']).map(RmfGraphVertex.fromJson));
      edges.addAll(
        _maps(graph['edges'])
            .map(RmfGraphEdge.fromJson)
            .map(
              (edge) =>
                  RmfGraphEdge(from: edge.from + offset, to: edge.to + offset),
            ),
      );
    }
    return RmfLevel(
      name: json['name'] as String? ?? 'unknown',
      image: images.isEmpty ? null : RmfAffineImage.fromJson(images.first),
      vertices: vertices,
      edges: edges,
    );
  }
}

class RmfBuildingMap {
  const RmfBuildingMap({required this.name, required this.levels});

  final String name;
  final List<RmfLevel> levels;

  factory RmfBuildingMap.fromJson(Map<String, dynamic> json) => RmfBuildingMap(
    name: json['name'] as String? ?? 'Open-RMF',
    levels: _maps(json['levels']).map(RmfLevel.fromJson).toList(),
  );
}

class RmfRobot {
  const RmfRobot({
    required this.fleet,
    required this.name,
    required this.status,
    required this.level,
    required this.x,
    required this.y,
    required this.yaw,
    required this.battery,
    required this.taskId,
    required this.issueCount,
    required this.lockedMutexGroups,
    required this.requestingMutexGroups,
  });

  final String fleet;
  final String name;
  final String status;
  final String level;
  final double x;
  final double y;
  final double yaw;
  final double battery;
  final String? taskId;
  final int issueCount;
  final List<String> lockedMutexGroups;
  final List<String> requestingMutexGroups;

  bool get isWorking => status == 'working';

  static List<RmfRobot> fromFleetList(List<dynamic> json) {
    final result = <RmfRobot>[];
    for (final rawFleet in json.whereType<Map>()) {
      final fleet = Map<String, dynamic>.from(rawFleet);
      final fleetName = fleet['name'] as String? ?? 'unknown';
      final robots = fleet['robots'];
      if (robots is! Map) continue;
      for (final entry in robots.entries) {
        if (entry.value is! Map) continue;
        final state = Map<String, dynamic>.from(entry.value as Map);
        final location = state['location'] is Map
            ? Map<String, dynamic>.from(state['location'] as Map)
            : const <String, dynamic>{};
        final mutex = state['mutex_groups'] is Map
            ? Map<String, dynamic>.from(state['mutex_groups'] as Map)
            : const <String, dynamic>{};
        result.add(
          RmfRobot(
            fleet: fleetName,
            name: state['name'] as String? ?? entry.key.toString(),
            status: state['status'] as String? ?? 'uninitialized',
            level: location['map'] as String? ?? '',
            x: _number(location['x']),
            y: _number(location['y']),
            yaw: _number(location['yaw']),
            battery: _number(state['battery']).clamp(0, 1),
            taskId: _nullableText(state['task_id']),
            issueCount: state['issues'] is List
                ? (state['issues'] as List).length
                : 0,
            lockedMutexGroups: _textList(mutex['locked']),
            requestingMutexGroups: _textList(mutex['requesting']),
          ),
        );
      }
    }
    return result;
  }
}

class RmfTrajectory {
  const RmfTrajectory({
    required this.fleet,
    required this.robot,
    required this.level,
    required this.points,
    required this.conflict,
  });

  final String fleet;
  final String robot;
  final String level;
  final List<(double, double)> points;
  final bool conflict;
}

class RmfTask {
  const RmfTask({
    required this.id,
    required this.category,
    required this.status,
    required this.fleet,
    required this.robot,
    required this.requestedAt,
    required this.startedAt,
    required this.finishedAt,
    required this.requester,
    required this.detail,
  });

  final String id;
  final String category;
  final String status;
  final String? fleet;
  final String? robot;
  final DateTime? requestedAt;
  final DateTime? startedAt;
  final DateTime? finishedAt;
  final String? requester;
  final Map<String, dynamic> detail;

  bool get isActive =>
      const {'queued', 'pending', 'underway', 'active'}.contains(status);

  bool get isCanceled =>
      const {'canceled', 'cancelled', 'killed'}.contains(status.toLowerCase());

  factory RmfTask.fromJson(Map<String, dynamic> json) {
    final booking = json['booking'] is Map
        ? Map<String, dynamic>.from(json['booking'] as Map)
        : const <String, dynamic>{};
    final assigned = json['assigned_to'] is Map
        ? Map<String, dynamic>.from(json['assigned_to'] as Map)
        : const <String, dynamic>{};
    final millis = booking['unix_millis_request_time'] as num?;
    return RmfTask(
      id: booking['id'] as String? ?? '-',
      category: _rootText(json['category']) ?? 'unknown',
      status: json['status'] as String? ?? 'uninitialized',
      fleet: _nullableText(assigned['group']),
      robot: _nullableText(assigned['name']),
      requestedAt: millis == null
          ? null
          : DateTime.fromMillisecondsSinceEpoch(millis.toInt()),
      startedAt: _dateFromMillis(json['unix_millis_start_time']),
      finishedAt: _dateFromMillis(json['unix_millis_finish_time']),
      requester: _nullableText(booking['requester']),
      detail: Map<String, dynamic>.from(json),
    );
  }
}

class RmfDoor {
  const RmfDoor({required this.name, required this.mode, required this.detail});

  final String name;
  final int mode;
  final Map<String, dynamic> detail;

  String get stateLabel => switch (mode) {
    0 => '닫힘',
    1 => '이동 중',
    2 => '열림',
    _ => '알 수 없음',
  };

  factory RmfDoor.fromJson(
    Map<String, dynamic> descriptor,
    Map<String, dynamic>? state,
  ) {
    final data = state ?? descriptor;
    return RmfDoor(
      name:
          _nullableText(data['door_name']) ??
          _nullableText(descriptor['name']) ??
          '-',
      mode: _integer(data['current_mode'], fallback: -1),
      detail: Map<String, dynamic>.from(data),
    );
  }
}

class RmfLift {
  const RmfLift({
    required this.name,
    required this.currentFloor,
    required this.destinationFloor,
    required this.availableFloors,
    required this.doorState,
    required this.motionState,
    required this.currentMode,
    required this.sessionId,
    required this.detail,
  });

  final String name;
  final String currentFloor;
  final String destinationFloor;
  final List<String> availableFloors;
  final int doorState;
  final int motionState;
  final int currentMode;
  final String sessionId;
  final Map<String, dynamic> detail;

  factory RmfLift.fromJson(
    Map<String, dynamic> descriptor,
    Map<String, dynamic>? state,
  ) {
    final data = state ?? descriptor;
    return RmfLift(
      name:
          _nullableText(data['lift_name']) ??
          _nullableText(descriptor['name']) ??
          '-',
      currentFloor: _nullableText(data['current_floor']) ?? '-',
      destinationFloor: _nullableText(data['destination_floor']) ?? '',
      availableFloors: data['available_floors'] is List
          ? (data['available_floors'] as List).map((e) => '$e').toList()
          : const [],
      doorState: _integer(data['door_state'], fallback: -1),
      motionState: _integer(data['motion_state'], fallback: -1),
      currentMode: _integer(data['current_mode'], fallback: -1),
      sessionId: _nullableText(data['session_id']) ?? '',
      detail: Map<String, dynamic>.from(data),
    );
  }
}

class RmfWorkcell {
  const RmfWorkcell({
    required this.id,
    required this.kind,
    required this.mode,
    required this.queue,
    required this.detail,
  });

  final String id;
  final String kind;
  final int mode;
  final int queue;
  final Map<String, dynamic> detail;

  factory RmfWorkcell.fromJson(String kind, Map<String, dynamic> data) =>
      RmfWorkcell(
        id: _nullableText(data['guid']) ?? _nullableText(data['id']) ?? '-',
        kind: kind,
        mode: _integer(data['mode'], fallback: -1),
        queue: data['request_guid_queue'] is List
            ? (data['request_guid_queue'] as List).length
            : 0,
        detail: Map<String, dynamic>.from(data),
      );
}

class RmfAlert {
  const RmfAlert({
    required this.id,
    required this.title,
    required this.subtitle,
    required this.message,
    required this.tier,
    required this.responses,
    required this.taskId,
    required this.createdAt,
  });

  final String id;
  final String title;
  final String subtitle;
  final String message;
  final String tier;
  final List<String> responses;
  final String? taskId;
  final DateTime? createdAt;

  factory RmfAlert.fromJson(Map<String, dynamic> json) => RmfAlert(
    id: _nullableText(json['id']) ?? '-',
    title: _nullableText(json['title']) ?? 'RMF 알림',
    subtitle: _nullableText(json['subtitle']) ?? '',
    message: _nullableText(json['message']) ?? '',
    tier: _nullableText(json['tier']) ?? 'info',
    responses: json['responses_available'] is List
        ? (json['responses_available'] as List).map((e) => '$e').toList()
        : const [],
    taskId: _nullableText(json['task_id']),
    createdAt: _dateFromMillis(json['unix_millis_alert_time']),
  );
}

double _number(Object? value, {double fallback = 0}) =>
    value is num && value.isFinite ? value.toDouble() : fallback;

int _integer(Object? value, {int fallback = 0}) {
  if (value is num && value.isFinite) return value.toInt();
  if (value is Map) {
    return _integer(value['value'] ?? value['root'], fallback: fallback);
  }
  return fallback;
}

List<Map<String, dynamic>> _maps(Object? value) => value is List
    ? value.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList()
    : const [];

List<String> _textList(Object? value) =>
    value is List ? value.map((e) => '$e').toList() : const [];

String? _nullableText(Object? value) {
  final text = value?.toString().trim() ?? '';
  return text.isEmpty ? null : text;
}

String? _rootText(Object? value) {
  if (value is String) return _nullableText(value);
  if (value is Map) return _nullableText(value['root']);
  return null;
}

DateTime? _dateFromMillis(Object? value) =>
    value is num ? DateTime.fromMillisecondsSinceEpoch(value.toInt()) : null;

double normalizeAngle(double angle) {
  var result = angle;
  while (result > math.pi) {
    result -= math.pi * 2;
  }
  while (result < -math.pi) {
    result += math.pi * 2;
  }
  return result;
}
