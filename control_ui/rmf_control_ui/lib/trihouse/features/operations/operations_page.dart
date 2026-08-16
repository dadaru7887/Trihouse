import 'dart:async';

import 'package:flutter/material.dart';

import '../../api/fms_api.dart';
import '../../api/fms_models.dart';
import '../../presentation/shared.dart';
import 'camera_wall.dart';
import 'map_layers.dart';

/// Live operations screen.
///
/// It draws the actual Nav2 paths first, opens exactly the cameras an event
/// needs, and offers the two operator decisions for an emergency. Closing the
/// dialog does nothing at all.
class OperationsPage extends StatefulWidget {
  const OperationsPage({super.key, required this.api, this.workerId = 'W-1'});

  final FmsApi api;
  final String workerId;

  @override
  State<OperationsPage> createState() => _OperationsPageState();
}

class _OperationsPageState extends State<OperationsPage> {
  StreamSubscription<OperationsEventDto>? _subscription;
  final Map<String, RobotPath> _paths = {};
  final Map<String, RobotPose> _robots = {};
  final Map<String, CameraOverlay> _overlays = {};
  List<String> _openCameraIds = const [];
  bool _showRmfDiagnostics = false;
  int? _incidentId;
  String _incidentKind = '';
  Object? _error;

  @override
  void initState() {
    super.initState();
    _subscription = widget.api.operationsEvents().listen(
      _apply,
      onError: (Object error) => setState(() => _error = error),
    );
  }

  @override
  void dispose() {
    _subscription?.cancel();
    super.dispose();
  }

  void _apply(OperationsEventDto event) {
    final payload = event.payload ?? const <String, Object?>{};
    setState(() {
      switch (event.eventType) {
        case 'PATH_UPDATED':
        case 'PATH_SCHEDULE_MISMATCH':
          final path = RobotPath.fromJson({
            ...payload,
            'held': event.eventType == 'PATH_SCHEDULE_MISMATCH',
            'hold_reason_code': event.eventType == 'PATH_SCHEDULE_MISMATCH'
                ? 'PATH_SCHEDULE_MISMATCH'
                : '',
          });
          _paths[path.robotId] = path;
        case 'ROBOT_UPDATED':
          final robotId = payload['robot_id'] as String;
          _robots[robotId] = RobotPose(
            robotId: robotId,
            x: (payload['x'] as num?)?.toDouble() ?? 0,
            y: (payload['y'] as num?)?.toDouble() ?? 0,
            yaw: (payload['yaw'] as num?)?.toDouble() ?? 0,
            batteryPercent:
                (payload['battery_percent'] as num?)?.toDouble() ?? 0,
            safetyState: (payload['safety_state'] as String?) ?? '',
            jobId: (payload['job_id'] as String?) ?? '',
          );
        case 'PINKY_FALL':
        case 'WAREHOUSE_FALL':
          _openFor(event, payload);
          _incidentId = event.incidentId;
          _incidentKind = event.eventType;
        case 'OMX_QR':
        case 'OMX_PICK':
        case 'OMX_LOAD':
        case 'MANUAL_TRAVEL_VIEW':
          _openFor(event, payload);
      }
    });
  }

  void _openFor(OperationsEventDto event, Map<String, Object?> payload) {
    final selection = selectEventCameras(
      kind: event.eventType,
      robotId: (payload['robot_id'] as String?) ?? '',
      omxId: (payload['omx_id'] as String?) ?? '',
      locationId: (payload['location_id'] as String?) ?? '',
    );
    final outcome = (payload['load_outcome'] as String?) ?? '';
    // Success closes the view; retry, drop, uncertain and emergency keep it open.
    if (selection.autoCloseOnSuccess && outcome == 'LOAD_CONFIRMED') {
      _openCameraIds = const [];
      return;
    }
    _openCameraIds = selection.cameraIds;
    for (final cameraId in selection.cameraIds) {
      _overlays[cameraId] = CameraOverlay(
        qrValue: (payload['qr'] as String?) ?? '',
        markerId: payload['marker_id'] as int?,
        actStage: (payload['act_stage'] as String?) ?? '',
        actVersion: (payload['act_version'] as String?) ?? '',
        attemptNo: (payload['attempt_no'] as int?) ?? 0,
        gripperState: (payload['gripper_state'] as String?) ?? '',
        safetyGate: (payload['safety_gate'] as String?) ?? '',
        loadOutcome: outcome,
      );
    }
  }

  Future<void> _decide(EmergencyDecision decision) async {
    final incidentId = _incidentId;
    if (incidentId == null) return;
    try {
      await widget.api.decideEmergency(
        incidentId,
        EmergencyDecisionDto(
          workerId: widget.workerId,
          decision: decision,
          reason: _incidentKind,
        ),
        idempotencyKey: 'emergency-$incidentId-${decision.name}',
      );
      setState(() => _incidentId = null);
    } catch (error) {
      setState(() => _error = error);
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.all(24),
    child: SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          PageHeading(
            title: '운영 현황',
            description: 'Nav2가 계산한 실제 경로와 이동 궤적을 먼저 보여줍니다.',
            actions: [
              Row(
                children: [
                  const Text('RMF 진단'),
                  Switch(
                    key: const Key('rmf-diagnostics-toggle'),
                    value: _showRmfDiagnostics,
                    onChanged: (value) =>
                        setState(() => _showRmfDiagnostics = value),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 16),
          if (_error != null) ...[
            GatewayFailurePanel(error: _error!),
            const SizedBox(height: 16),
          ],
          // An open incident outranks everything else on the screen.
          if (_incidentId != null) ...[
            _EmergencyDecisionPanel(
              onRaiseAlarm: () => _decide(EmergencyDecision.raiseAlarm),
              onContinueWork: () => _decide(EmergencyDecision.continueWork),
              onDismiss: () => setState(() => _incidentId = null),
            ),
            const SizedBox(height: 20),
          ],
          OperationsMapView(
            paths: _paths.values.toList(growable: false),
            robots: _robots.values.toList(growable: false),
            showRmfDiagnostics: _showRmfDiagnostics,
          ),
          const SizedBox(height: 20),
          CameraWall(openCameraIds: _openCameraIds, overlays: _overlays),
        ],
      ),
    ),
  );
}

class _EmergencyDecisionPanel extends StatelessWidget {
  const _EmergencyDecisionPanel({
    required this.onRaiseAlarm,
    required this.onContinueWork,
    required this.onDismiss,
  });

  final VoidCallback onRaiseAlarm;
  final VoidCallback onContinueWork;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) => Container(
    key: const Key('emergency-decision'),
    padding: const EdgeInsets.all(18),
    decoration: BoxDecoration(
      color: const Color(0xFFFEF2F2),
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: const Color(0xFFFECACA)),
    ),
    child: Row(
      children: [
        const Expanded(child: Text('비상 상황을 확인했습니다. 영향받은 작업은 보류 중입니다.')),
        FilledButton(
          key: const Key('raise-alarm'),
          onPressed: onRaiseAlarm,
          child: const Text('비상경보 발령'),
        ),
        const SizedBox(width: 8),
        OutlinedButton(
          key: const Key('continue-work'),
          onPressed: onContinueWork,
          child: const Text('작업 계속 진행'),
        ),
        const SizedBox(width: 8),
        // Closing does nothing: no decision is recorded and the hold stays.
        IconButton(
          key: const Key('dismiss-emergency'),
          onPressed: onDismiss,
          icon: const Icon(Icons.close),
        ),
      ],
    ),
  );
}
