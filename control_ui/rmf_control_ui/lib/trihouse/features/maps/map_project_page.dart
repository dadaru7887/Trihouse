import 'package:flutter/material.dart';

import '../../api/fms_api.dart';
import '../../api/fms_models.dart';
import '../../presentation/map_workspace.dart';
import '../../presentation/shared.dart';
import '../settings/runtime_profile_panel.dart';
import 'map_source_picker.dart';
import 'physical_feature_layer.dart';

typedef MapSourcePicker = Future<MapSourceUploadDto?> Function(String sourceType);

class MapProjectPage extends StatefulWidget {
  const MapProjectPage({
    super.key,
    required this.api,
    this.sourcePicker = pickMapSource,
  });

  final FmsApi api;
  final MapSourcePicker sourcePicker;

  @override
  State<MapProjectPage> createState() => _MapProjectPageState();
}

class _MapProjectPageState extends State<MapProjectPage> {
  late Future<List<MapProjectSummaryDto>> _projects;
  Future<RuntimeProfileDto>? _runtimeProfile;
  MapProjectDraftDto? _draft;
  String? _activeRevision;
  Object? _failure;
  var _busy = false;
  var _dirty = false;
  var _tab = 0;

  @override
  void initState() {
    super.initState();
    _projects = widget.api.listMapProjects();
  }

  Future<void> _open(String mapName) async {
    setState(() {
      _busy = true;
      _failure = null;
    });
    try {
      final opened = await widget.api.openMapProject(mapName);
      if (!mounted) return;
      setState(() {
        _draft = opened.draft;
        _activeRevision = opened.activeRevision;
        _dirty = false;
      });
    } catch (error) {
      if (mounted) setState(() => _failure = error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<bool> _confirmDiscard() async {
    if (!_dirty) return true;
    return await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('저장되지 않은 변경'),
            content: const Text('마지막 저장 이후 변경을 버리고 계속하시겠습니까?'),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('취소'),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('버리기'),
              ),
            ],
          ),
        ) ??
        false;
  }

  Future<void> _requestOpen(String mapName) async {
    if (!await _confirmDiscard() || !mounted) return;
    if (_dirty) setState(() => _dirty = false);
    await _open(mapName);
  }

  Future<void> _requestPop() async {
    if (!await _confirmDiscard() || !mounted) return;
    if (_dirty) setState(() => _dirty = false);
    Navigator.of(context).pop();
  }

  MapProjectDraftDto _copyDraft({
    Map<String, String>? sourceUuids,
    Map<String, String>? stagedSourceTokens,
    List<JsonObject>? waypoints,
    List<JsonObject>? features,
  }) {
    final draft = _draft!;
    return MapProjectDraftDto(
      mapName: draft.mapName,
      formatVersion: draft.formatVersion,
      draftRevision: draft.draftRevision,
      sourceUuids: sourceUuids ?? draft.sourceUuids,
      stagedSourceTokens: stagedSourceTokens ?? draft.stagedSourceTokens,
      waypoints: waypoints ?? draft.waypoints,
      features: features ?? draft.features,
      runtimeProfileHash: draft.runtimeProfileHash,
    );
  }

  Future<void> _upload(String sourceType) async {
    final draft = _draft;
    if (draft == null) return;
    final picked = await widget.sourcePicker(sourceType);
    if (picked == null || !mounted) return;
    setState(() => _busy = true);
    try {
      final staged = await widget.api.stageMapSource(draft.mapName, picked);
      final tokens = {...draft.stagedSourceTokens, sourceType: staged.uploadToken};
      final sourceUuids = {...draft.sourceUuids}..remove(sourceType);
      final manualWaypoints = draft.waypoints
          .where((value) => value['origin'] == 'manual')
          .toList(growable: false);
      setState(() {
        _draft = _copyDraft(
          sourceUuids: sourceUuids,
          stagedSourceTokens: tokens,
          waypoints: sourceType == 'physical_features_import'
              ? [...staged.waypoints, ...manualWaypoints]
              : null,
          features: sourceType == 'physical_features_import'
              ? staged.features
              : null,
        );
        _dirty = true;
      });
    } catch (error) {
      if (mounted) setState(() => _failure = error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _save() async {
    final draft = _draft;
    if (draft == null) return;
    setState(() => _busy = true);
    try {
      final saved = await widget.api.saveMapDraft(
        draft,
        expectedRevision: draft.draftRevision,
      );
      if (mounted) {
        setState(() {
          _draft = saved;
          _dirty = false;
        });
      }
    } catch (error) {
      if (mounted) setState(() => _failure = error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _delete() async {
    final draft = _draft;
    if (draft == null) return;
    setState(() => _busy = true);
    try {
      await widget.api.deleteMapDraft(draft.mapName);
      if (mounted) {
        setState(() {
          _draft = null;
          _activeRevision = null;
          _dirty = false;
          _projects = widget.api.listMapProjects();
        });
      }
    } catch (error) {
      if (mounted) setState(() => _failure = error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _publish() async {
    final draft = _draft;
    if (draft == null) return;
    setState(() => _busy = true);
    try {
      final validation = await widget.api.validateMapDraft(draft.mapName);
      if (!validation.valid) throw StateError(validation.errorCodes.join(', '));
      final published = await widget.api.publishMapDraft(
        draft.mapName,
        PublishMapDto(
          expectedDraftRevision: draft.draftRevision,
          publishedBy: 'browser-session',
        ),
      );
      if (mounted) setState(() => _activeRevision = published.mapRevision);
    } catch (error) {
      if (mounted) setState(() => _failure = error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  List<MapWaypointPresentation> _waypointPresentations() => [
    for (final waypoint in _draft?.waypoints ?? const <JsonObject>[])
      if (waypoint['code'] is String &&
          waypoint['x'] is num &&
          waypoint['y'] is num)
        MapWaypointPresentation(
          code: waypoint['code']! as String,
          position: Offset(
            360 + (waypoint['x']! as num).toDouble() * 80,
            300 - (waypoint['y']! as num).toDouble() * 80,
          ),
          yaw: (waypoint['yaw'] as num?)?.toDouble() ?? 0,
          draggable: waypoint['origin'] == 'manual',
        ),
  ];

  void _waypointMoved(MapWaypointPresentation moved) {
    final draft = _draft;
    if (draft == null) return;
    final movedWaypoint = draft.waypoints.firstWhere(
      (value) => value['code'] == moved.code,
    );
    if (movedWaypoint['origin'] != 'manual') return;
    final updated = [
      for (final waypoint in draft.waypoints)
        if (waypoint['code'] == moved.code)
          {
            ...waypoint,
            'x': (moved.position.dx - 360) / 80,
            'y': (300 - moved.position.dy) / 80,
          }
        else
          waypoint,
    ];
    setState(() {
      _draft = _copyDraft(waypoints: updated);
      _dirty = true;
    });
  }

  Future<void> _addWaypoint() async {
    if (_draft == null) return;
    final code = TextEditingController();
    final x = TextEditingController();
    final y = TextEditingController();
    final yaw = TextEditingController();
    final added = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Waypoint 추가'),
        content: SizedBox(
          width: 360,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(controller: code, decoration: const InputDecoration(labelText: '코드')),
              TextField(controller: x, decoration: const InputDecoration(labelText: 'x (m)')),
              TextField(controller: y, decoration: const InputDecoration(labelText: 'y (m)')),
              TextField(controller: yaw, decoration: const InputDecoration(labelText: 'yaw (rad)')),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('취소')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('추가')),
        ],
      ),
    );
    if (added != true || !mounted) return;
    final parsedX = double.tryParse(x.text);
    final parsedY = double.tryParse(y.text);
    final parsedYaw = double.tryParse(yaw.text);
    if (code.text.trim().isEmpty || parsedX == null || parsedY == null || parsedYaw == null) {
      setState(() => _failure = const FormatException('Waypoint point+yaw 값을 확인하세요.'));
      return;
    }
    setState(() {
      _draft = _copyDraft(
        waypoints: [
          ..._draft!.waypoints,
          {
            'code': code.text.trim(),
            'display_name': code.text.trim(),
            'x': parsedX,
            'y': parsedY,
            'yaw': parsedYaw,
            'origin': 'manual',
          },
        ],
      );
      _dirty = true;
    });
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !_dirty,
    onPopInvokedWithResult: (didPop, result) {
      if (!didPop && _dirty) _requestPop();
    },
    child: Padding(
      padding: const EdgeInsets.all(28),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          PageHeading(
            title: '맵 프로젝트',
            description: 'SLAM 지도와 실측 Feature를 명시적으로 저장한 뒤 검증·배포합니다.',
            actions: [
              OutlinedButton.icon(
                onPressed: _draft == null || _busy ? null : _delete,
                icon: const Icon(Icons.delete_outline),
                label: const Text('삭제'),
              ),
              const SizedBox(width: 8),
              OutlinedButton.icon(
                onPressed: _draft == null || _busy ? null : _save,
                icon: const Icon(Icons.save_outlined),
                label: const Text('저장'),
              ),
              const SizedBox(width: 8),
              FilledButton.icon(
                onPressed: _draft == null || _busy ? null : _publish,
                icon: const Icon(Icons.rocket_launch_outlined),
                label: const Text('배포'),
              ),
            ],
          ),
          if (_failure != null) ...[
            const SizedBox(height: 10),
            GatewayFailurePanel(error: _failure!),
          ],
          if (_draft != null) ...[
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                if (_activeRevision != null)
                  const Chip(
                    avatar: Icon(Icons.info_outline, size: 17),
                    label: Text('배포된 이름입니다. 기존 프로젝트를 열었습니다.'),
                  ),
                if (_dirty)
                  const Chip(
                    avatar: Icon(Icons.edit_outlined, size: 17),
                    label: Text('저장되지 않은 변경'),
                  ),
                OutlinedButton.icon(
                  onPressed: _busy ? null : () => _upload('slam_yaml'),
                  icon: const Icon(Icons.upload_file),
                  label: const Text('SLAM YAML 업로드'),
                ),
                OutlinedButton.icon(
                  onPressed: _busy ? null : () => _upload('slam_image'),
                  icon: const Icon(Icons.image_outlined),
                  label: const Text('SLAM 이미지 업로드'),
                ),
                OutlinedButton.icon(
                  onPressed: _busy
                      ? null
                      : () => _upload('physical_features_import'),
                  icon: const Icon(Icons.straighten_outlined),
                  label: const Text('실측 JSONL 업로드'),
                ),
                OutlinedButton.icon(
                  onPressed: _busy ? null : _addWaypoint,
                  icon: const Icon(Icons.add_location_alt_outlined),
                  label: const Text('Waypoint 추가'),
                ),
              ],
            ),
          ],
          const SizedBox(height: 12),
          SegmentedButton<int>(
            segments: const [
              ButtonSegment(value: 0, label: Text('지도 편집')),
              ButtonSegment(value: 1, label: Text('실측 Feature')),
              ButtonSegment(value: 2, label: Text('설정 파일')),
            ],
            selected: {_tab},
            onSelectionChanged: (value) => setState(() {
              _tab = value.single;
              if (_tab == 2) {
                _runtimeProfile ??= widget.api.getRuntimeProfile();
              }
            }),
          ),
          const SizedBox(height: 12),
          Expanded(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                SizedBox(
                  width: 270,
                  child: _ProjectList(
                    projects: _projects,
                    onOpen: _requestOpen,
                  ),
                ),
                const SizedBox(width: 18),
                Expanded(
                  child: Stack(
                    children: [
                      Positioned.fill(child: _tabContent()),
                      if (_busy)
                        const Positioned.fill(
                          child: ColoredBox(
                            color: Color(0x33000000),
                            child: Center(child: CircularProgressIndicator()),
                          ),
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    ),
  );

  Widget _tabContent() => switch (_tab) {
    0 => MapWorkspace(
      waypoints: _waypointPresentations(),
      onWaypointMoved: _waypointMoved,
    ),
    1 => PhysicalFeatureLayer(
      waypoints: _draft?.waypoints ?? const [],
      features: _draft?.features ?? const [],
    ),
    _ => RuntimeProfilePanel(
      profile: _runtimeProfile ??= widget.api.getRuntimeProfile(),
    ),
  };
}

class _ProjectList extends StatelessWidget {
  const _ProjectList({required this.projects, required this.onOpen});

  final Future<List<MapProjectSummaryDto>> projects;
  final ValueChanged<String> onOpen;

  @override
  Widget build(BuildContext context) => Container(
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: const Color(0xFFE2E8F0)),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Padding(
          padding: EdgeInsets.all(16),
          child: Text('프로젝트 목록', style: TextStyle(fontWeight: FontWeight.w800)),
        ),
        const Divider(height: 1),
        Expanded(
          child: FutureBuilder<List<MapProjectSummaryDto>>(
            future: projects,
            builder: (context, snapshot) {
              if (snapshot.hasError) {
                return Padding(
                  padding: const EdgeInsets.all(12),
                  child: GatewayFailurePanel(error: snapshot.error!),
                );
              }
              if (!snapshot.hasData) return const Center(child: CircularProgressIndicator());
              return ListView(
                children: [
                  for (final project in snapshot.data!)
                    Material(
                      color: Colors.transparent,
                      child: ListTile(
                        onTap: () => onOpen(project.mapName),
                        leading: const Icon(Icons.map_outlined),
                        title: Text(project.mapName),
                        subtitle: Text(
                          'Waypoint ${project.waypointCount} · Draft ${project.draftRevision}',
                        ),
                        trailing: const Icon(Icons.chevron_right),
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
}
