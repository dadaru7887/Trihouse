import 'package:flutter/material.dart';

/// Event-driven camera wall.
///
/// P0 registers six camera fixtures but does not connect six physical cameras
/// and never decodes all six at once. Exactly the cameras an event needs are
/// opened; Pinky video is never used as OMX load evidence.

@immutable
class CameraFixture {
  const CameraFixture({
    required this.cameraId,
    required this.role,
    required this.mediamtxPath,
    this.attachedTo,
    this.status = 'registered',
  });

  final String cameraId;
  final String role;
  final String mediamtxPath;
  final String? attachedTo;
  final String status;
}

const cameraFixtures = <CameraFixture>[
  CameraFixture(
    cameraId: 'CAM-PK-01',
    role: 'pinky_travel',
    attachedTo: 'PK_01',
    mediamtxPath: 'fixtures/pinky_01_travel',
  ),
  CameraFixture(
    cameraId: 'CAM-PK-02',
    role: 'pinky_travel',
    attachedTo: 'PK_02',
    mediamtxPath: 'fixtures/pinky_02_travel',
  ),
  CameraFixture(
    cameraId: 'CAM-OMX-01-WRIST',
    role: 'omx_wrist',
    attachedTo: 'OMX_01',
    mediamtxPath: 'fixtures/omx_01_wrist',
  ),
  CameraFixture(
    cameraId: 'CAM-OMX-02-WRIST',
    role: 'omx_wrist',
    attachedTo: 'OMX_02',
    mediamtxPath: 'fixtures/omx_02_wrist',
  ),
  CameraFixture(
    cameraId: 'CAM-FIXED-01',
    role: 'warehouse_fixed',
    mediamtxPath: 'fixtures/warehouse_fixed_01',
  ),
  CameraFixture(
    cameraId: 'CAM-FIXED-02',
    role: 'warehouse_fixed',
    mediamtxPath: 'fixtures/warehouse_fixed_02',
  ),
];

const _pinkyCamera = {'PK_01': 'CAM-PK-01', 'PK_02': 'CAM-PK-02'};
const _omxWristCamera = {
  'OMX_01': 'CAM-OMX-01-WRIST',
  'OMX_02': 'CAM-OMX-02-WRIST',
};
const _fixedCameraByArea = {
  'WH-AMB-01': 'CAM-FIXED-01',
  'WH-CHL-01': 'CAM-FIXED-01',
  'WH-FRZ-01': 'CAM-FIXED-02',
  'PACKING-01': 'CAM-FIXED-02',
};

@immutable
class CameraSelection {
  const CameraSelection(this.cameraIds, {required this.autoCloseOnSuccess});

  final List<String> cameraIds;
  final bool autoCloseOnSuccess;
}

/// Mirrors the Control Tower selection rule so the UI opens the same cameras.
CameraSelection selectEventCameras({
  required String kind,
  String robotId = '',
  String omxId = '',
  String locationId = '',
}) {
  switch (kind) {
    case 'PINKY_FALL':
    case 'MANUAL_TRAVEL_VIEW':
      final camera = _pinkyCamera[robotId];
      return CameraSelection(
        camera == null ? const [] : [camera],
        autoCloseOnSuccess: kind == 'MANUAL_TRAVEL_VIEW',
      );
    case 'WAREHOUSE_FALL':
      final camera = _fixedCamera(locationId);
      return CameraSelection(
        camera == null ? const [] : [camera],
        autoCloseOnSuccess: false,
      );
    case 'OMX_QR':
    case 'OMX_PICK':
    case 'OMX_LOAD':
      final wrist = _omxWristCamera[omxId];
      final fixed = _fixedCamera(locationId);
      return CameraSelection([?wrist, ?fixed], autoCloseOnSuccess: true);
    default:
      return const CameraSelection([], autoCloseOnSuccess: true);
  }
}

String? _fixedCamera(String locationId) {
  for (final entry in _fixedCameraByArea.entries) {
    if (locationId == entry.key || locationId.startsWith('${entry.key}-')) {
      return entry.value;
    }
  }
  return null;
}

/// Overlay facts drawn on top of an opened stream.
@immutable
class CameraOverlay {
  const CameraOverlay({
    this.qrValue = '',
    this.markerId,
    this.actStage = '',
    this.actVersion = '',
    this.attemptNo = 0,
    this.gripperState = '',
    this.safetyGate = '',
    this.loadOutcome = '',
  });

  final String qrValue;
  final int? markerId;
  final String actStage;
  final String actVersion;
  final int attemptNo;
  final String gripperState;
  final String safetyGate;
  final String loadOutcome;

  List<String> get lines => [
    if (qrValue.isNotEmpty) 'QR $qrValue',
    if (markerId != null) 'ArUco $markerId',
    if (actStage.isNotEmpty) 'ACT $actStage $actVersion #$attemptNo',
    if (gripperState.isNotEmpty) '그리퍼 $gripperState',
    if (safetyGate.isNotEmpty) '안전 게이트 $safetyGate',
    if (loadOutcome.isNotEmpty) '적재 $loadOutcome',
  ];
}

class CameraWall extends StatelessWidget {
  const CameraWall({
    super.key,
    required this.openCameraIds,
    this.overlays = const {},
  });

  final List<String> openCameraIds;
  final Map<String, CameraOverlay> overlays;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const Text('카메라', style: TextStyle(fontWeight: FontWeight.w800)),
      const SizedBox(height: 8),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          for (final camera in cameraFixtures)
            _CameraCard(
              fixture: camera,
              open: openCameraIds.contains(camera.cameraId),
              overlay: overlays[camera.cameraId],
            ),
        ],
      ),
    ],
  );
}

class _CameraCard extends StatelessWidget {
  const _CameraCard({
    required this.fixture,
    required this.open,
    required this.overlay,
  });

  final CameraFixture fixture;
  final bool open;
  final CameraOverlay? overlay;

  @override
  Widget build(BuildContext context) => Container(
    key: Key('${fixture.cameraId}-status'),
    width: 210,
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: open ? const Color(0xFFEFF6FF) : Colors.white,
      borderRadius: BorderRadius.circular(10),
      border: Border.all(
        color: open ? const Color(0xFF2563EB) : const Color(0xFFE2E8F0),
      ),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          fixture.cameraId,
          style: const TextStyle(fontWeight: FontWeight.w700),
        ),
        Text(fixture.role, style: const TextStyle(color: Color(0xFF64748B))),
        // Only an opened camera is decoded; the rest stay registered-only.
        if (open) ...[
          const SizedBox(height: 8),
          Container(
            key: Key('${fixture.cameraId}-live'),
            height: 64,
            alignment: Alignment.center,
            color: const Color(0xFF0F172A),
            child: Text(
              fixture.mediamtxPath,
              style: const TextStyle(color: Colors.white, fontSize: 11),
            ),
          ),
          for (final line in overlay?.lines ?? const <String>[])
            Text(line, style: const TextStyle(fontSize: 11)),
        ] else
          const Padding(
            padding: EdgeInsets.only(top: 8),
            child: Text('등록됨 · 미디코딩', style: TextStyle(fontSize: 11)),
          ),
      ],
    ),
  );
}
