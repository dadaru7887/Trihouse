import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

import 'models.dart';

class RmfTrajectoryClient {
  RmfTrajectoryClient({required this.url, required this.token});

  final String url;
  final String token;
  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _subscription;
  Completer<Map<String, dynamic>>? _pending;

  Future<List<RmfTrajectory>> getTrajectories(String level) async {
    if (url.isEmpty) return const [];
    try {
      await _ensureConnected();
      final pending = Completer<Map<String, dynamic>>();
      _pending = pending;
      _channel!.sink.add(
        jsonEncode({
          'request': 'trajectory',
          'param': {'map_name': level, 'duration': 60000, 'trim': true},
          if (token.isNotEmpty) 'token': token,
        }),
      );
      final response = await pending.future.timeout(const Duration(seconds: 2));
      final values = response['values'];
      if (values is! List) return const [];
      final conflicts = response['conflicts'] is List
          ? (response['conflicts'] as List)
                .whereType<List>()
                .expand((e) => e)
                .whereType<num>()
                .map((e) => e.toInt())
                .toSet()
          : <int>{};
      return values.whereType<Map>().map((raw) {
        final json = Map<String, dynamic>.from(raw);
        final id = (json['id'] as num?)?.toInt() ?? -1;
        final segments = json['segments'] is List
            ? (json['segments'] as List)
                  .whereType<Map>()
                  .map((segment) => segment['x'])
                  .whereType<List>()
                  .where((pose) => pose.length >= 2)
                  .map(
                    (pose) => (
                      (pose[0] as num).toDouble(),
                      (pose[1] as num).toDouble(),
                    ),
                  )
                  .toList()
            : <(double, double)>[];
        return RmfTrajectory(
          fleet: json['fleet_name']?.toString() ?? '',
          robot: json['robot_name']?.toString() ?? '',
          level: json['map_name']?.toString() ?? level,
          points: segments,
          conflict: conflicts.contains(id),
        );
      }).toList();
    } catch (_) {
      await _reset();
      return const [];
    }
  }

  Future<void> _ensureConnected() async {
    if (_channel != null) return;
    final channel = WebSocketChannel.connect(Uri.parse(url));
    _channel = channel;
    try {
      // Await the real socket connection so a refused optional trajectory
      // endpoint is caught by getTrajectories instead of escaping to the VM.
      await channel.ready;
    } catch (_) {
      if (identical(_channel, channel)) _channel = null;
      await channel.sink.close();
      rethrow;
    }
    _subscription = channel.stream.listen(
      (event) {
        final decoded = jsonDecode('$event');
        if (decoded is Map && _pending?.isCompleted == false) {
          _pending!.complete(Map<String, dynamic>.from(decoded));
        }
      },
      onError: (_) => unawaited(_reset()),
      onDone: () => unawaited(_reset()),
    );
  }

  Future<void> _reset() async {
    final subscription = _subscription;
    final channel = _channel;
    _pending = null;
    _subscription = null;
    _channel = null;
    await subscription?.cancel();
    try {
      await channel?.sink.close();
    } catch (_) {
      // The socket may already be closed after a connection failure.
    }
  }

  Future<void> close() => _reset();
}
