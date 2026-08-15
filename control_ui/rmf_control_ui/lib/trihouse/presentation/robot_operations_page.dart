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
  late final Stream<OperationsEventDto> _events;

  @override
  void initState() {
    super.initState();
    _events = widget.api.operationsEvents();
  }

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.all(28),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const PageHeading(
          title: '로봇 운영',
          description: 'Pinky와 설치 로봇의 위치, 연결 상태와 센서 진단을 확인합니다.',
        ),
        const SizedBox(height: 18),
        Expanded(
          child: StreamBuilder<OperationsEventDto>(
            stream: _events,
            builder: (context, snapshot) {
              if (snapshot.hasError) {
                return GatewayFailurePanel(error: snapshot.error!);
              }
              final event = snapshot.data;
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
                            child: ListView(
                              padding: const EdgeInsets.all(14),
                              children: [
                                ListTile(
                                  leading: const CircleAvatar(
                                    child: Icon(Icons.smart_toy_outlined),
                                  ),
                                  title: Text(device ?? '등록된 로봇 없음'),
                                  subtitle: Text(
                                    event == null
                                        ? 'Gateway 운영 스트림 대기'
                                        : '${event.eventType} · ${event.severity}',
                                  ),
                                ),
                              ],
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
