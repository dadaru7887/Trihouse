import 'dart:async';

import 'package:flutter/material.dart';

import '../../rmf_runtime_models.dart';
import '../../robot_sensor_models.dart';
import '../../robot_telemetry_models.dart';
import '../api/fms_api.dart';
import '../api/fms_models.dart';
import 'shared.dart';

class RobotOperationsPage extends StatefulWidget {
  const RobotOperationsPage({super.key, required this.api});

  final FmsApi api;

  @override
  State<RobotOperationsPage> createState() => _RobotOperationsPageState();
}

class _RobotOperationsPageState extends State<RobotOperationsPage> {
  /// 운영 이벤트가 몰려 올 때 장비 명부를 한 번만 다시 받도록 합친다.
  static const Duration _coalesceWindow = Duration(milliseconds: 400);

  /// 장비 텔레메트리는 `operation_events` 를 만들지 않는다. 이벤트만 기다리면
  /// 배터리와 상태가 job 이 움직일 때까지 낡은 채로 남으므로 주기 조회를 함께 돈다.
  static const Duration _pollInterval = Duration(seconds: 5);

  List<DeviceDto>? _devices;
  Object? _loadFailure;
  bool _loading = false;
  StreamSubscription<OperationsEventDto>? _events;
  Timer? _coalesce;
  Timer? _poll;
  OperationsEventDto? _latest;
  Object? _streamFailure;

  @override
  void initState() {
    super.initState();
    unawaited(_reloadDevices());
    _poll = Timer.periodic(_pollInterval, (_) => unawaited(_reloadDevices()));
    // 구독은 하나만 연다. `operationsEvents()` 는 호출할 때마다 WebSocket 을 새로
    // 열기 때문에, 표시용과 갱신용으로 두 번 부르면 화면 하나가 연결 두 개를 쥔다.
    _events = widget.api.operationsEvents().listen(
      (event) {
        if (!mounted) return;
        setState(() {
          _latest = event;
          _streamFailure = null;
        });
        _coalesce?.cancel();
        _coalesce = Timer(
          _coalesceWindow,
          () => unawaited(_reloadDevices()),
        );
      },
      onError: (Object error) {
        if (mounted) setState(() => _streamFailure = error);
      },
    );
  }

  @override
  void dispose() {
    _coalesce?.cancel();
    _poll?.cancel();
    final subscription = _events;
    _events = null;
    if (subscription != null) unawaited(subscription.cancel());
    super.dispose();
  }

  /// 조회 중에도 직전 명부를 그대로 둔다. 5초마다 목록이 사라지면 못 읽는다.
  Future<void> _reloadDevices() async {
    if (_loading || !mounted) return;
    _loading = true;
    try {
      final next = await widget.api.listDevices();
      if (mounted) {
        setState(() {
          _devices = next;
          _loadFailure = null;
        });
      }
    } catch (error) {
      if (mounted) setState(() => _loadFailure = error);
    } finally {
      _loading = false;
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.all(28),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        PageHeading(
          title: '로봇 운영',
          description: 'Pinky와 설치 로봇의 위치, 연결 상태와 센서 진단을 확인합니다.',
          actions: [LiveBadge(connected: _streamFailure == null)],
        ),
        const SizedBox(height: 18),
        Expanded(
          child: Builder(
            builder: (context) {
              if (_streamFailure != null) {
                return GatewayFailurePanel(error: _streamFailure!);
              }
              final event = _latest;
              final device = event?.deviceId;
              final pose = _poseFrom(event);
              return Row(
                children: [
                  Expanded(
                    flex: 2,
                    child: DashboardPanel(
                      title: '실시간 로봇 맵',
                      icon: Icons.map_outlined,
                      child: CustomPaint(
                        painter: _RobotMapPainter(pose: pose),
                        child: Center(child: Text(device ?? '로봇 운영 이벤트 수신 대기')),
                      ),
                    ),
                  ),
                  const SizedBox(width: 18),
                  Expanded(
                    child: Column(
                      children: [
                        Expanded(
                          child: DashboardPanel(
                            title: '로봇 등록 · 상태',
                            icon: Icons.smart_toy_outlined,
                            child: _DeviceRoster(
                              devices: _devices,
                              failure: _loadFailure,
                              highlighted: device,
                              onRetry: () => unawaited(_reloadDevices()),
                            ),
                          ),
                        ),
                        const SizedBox(height: 18),
                        const Expanded(child: _BrowserDiagnostics()),
                      ],
                    ),
                  ),
                ],
              );
            },
          ),
        ),
      ],
    ),
  );

  RobotPose? _poseFrom(OperationsEventDto? event) {
    final payload = event?.payload;
    final x = payload?['x'];
    final y = payload?['y'];
    if (x is! num || y is! num || event == null) return null;
    return RobotPose(
      x: x.toDouble(),
      y: y.toDouble(),
      heading: (payload?['yaw'] as num?)?.toDouble() ?? 0,
      at: event.occurredAt,
    );
  }
}

/// 등록된 장비 전체를 원장에서 받아 보여 준다. 이전에는 마지막 운영 이벤트에
/// 실린 장비 **하나만** 보여서, 두 대가 도는지 한 대가 도는지 알 수 없었다.
class _DeviceRoster extends StatelessWidget {
  const _DeviceRoster({
    required this.devices,
    required this.failure,
    required this.highlighted,
    required this.onRetry,
  });

  final List<DeviceDto>? devices;
  final Object? failure;
  final String? highlighted;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final data = devices;
    if (data == null) {
      if (failure != null) {
        return Padding(
          padding: const EdgeInsets.all(14),
          child: GatewayFailurePanel(error: failure!, onRetry: onRetry),
        );
      }
      return const Center(child: CircularProgressIndicator());
    }
    if (data.isEmpty) {
      return const Center(child: Text('등록된 로봇 없음'));
    }
    return ListView(
        padding: const EdgeInsets.all(14),
        children: [
          for (final robot in data)
            ListTile(
              key: Key('device-${robot.deviceId}'),
              selected: robot.deviceId == highlighted,
              leading: CircleAvatar(
                backgroundColor: robot.isOperational
                    ? const Color(0xFFDCFCE7)
                    : const Color(0xFFFEE2E2),
                child: Icon(
                  robot.isMobile
                      ? Icons.smart_toy_outlined
                      : Icons.precision_manufacturing_outlined,
                  color: robot.isOperational
                      ? const Color(0xFF16A34A)
                      : const Color(0xFFDC2626),
                ),
              ),
              title: Text('${robot.deviceId} · ${robot.name}'),
              subtitle: Text(
                '${robot.state ?? '상태 미상'} · ${robot.health ?? '건강 미상'}'
                ' · ${robot.controlMode}',
              ),
              trailing: Text(
                robot.batteryPct == null
                    ? '—'
                    : '${robot.batteryPct!.toStringAsFixed(0)}%',
              ),
            ),
        ],
    );
  }
}

class _BrowserDiagnostics extends StatelessWidget {
  const _BrowserDiagnostics();

  @override
  Widget build(BuildContext context) {
    const runtime = RmfRuntimeStatus.unknown;
    const sensors = RobotSensors();
    return DashboardPanel(
      title: '브라우저 진단 모델',
      icon: Icons.monitor_heart_outlined,
      child: ListView(
        padding: const EdgeInsets.all(14),
        children: [
          _DiagnosticLine(
            icon: Icons.hub_outlined,
            label: 'RMF runtime',
            value: runtime.message,
          ),
          _DiagnosticLine(
            icon: Icons.radar,
            label: 'LiDAR',
            value: sensors.scan == null ? '운영 이벤트 수신 대기' : '수신 중',
          ),
          _DiagnosticLine(
            icon: Icons.videocam_outlined,
            label: 'Camera',
            value: sensors.camera == null ? '운영 이벤트 수신 대기' : '수신 중',
          ),
        ],
      ),
    );
  }
}

class _DiagnosticLine extends StatelessWidget {
  const _DiagnosticLine({
    required this.icon,
    required this.label,
    required this.value,
  });

  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => ListTile(
    dense: true,
    leading: Icon(icon, color: controlBlue),
    title: Text(label),
    subtitle: Text(value),
  );
}

class _RobotMapPainter extends CustomPainter {
  const _RobotMapPainter({required this.pose});

  final RobotPose? pose;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(
      Offset.zero & size,
      Paint()..color = const Color(0xFFF8FAFC),
    );
    final grid = Paint()..color = const Color(0xFFE2E8F0);
    for (var x = 0.0; x < size.width; x += 36) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), grid);
    }
    for (var y = 0.0; y < size.height; y += 36) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }
    final value = pose;
    if (value == null) return;
    final point = Offset(
      size.width / 2 + value.x * 35,
      size.height / 2 - value.y * 35,
    );
    canvas.drawCircle(point, 10, Paint()..color = controlBlue);
    canvas.drawLine(
      point,
      point + Offset.fromDirection(-value.heading - 1.5708, 24),
      Paint()
        ..color = controlNavy
        ..strokeWidth = 3,
    );
  }

  @override
  bool shouldRepaint(covariant _RobotMapPainter oldDelegate) =>
      oldDelegate.pose != pose;
}
