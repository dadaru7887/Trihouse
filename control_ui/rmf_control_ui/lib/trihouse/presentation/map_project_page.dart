import 'package:flutter/material.dart';

import '../api/fms_api.dart';
import '../api/fms_models.dart';
import 'map_workspace.dart';
import 'shared.dart';

class MapProjectPage extends StatefulWidget {
  const MapProjectPage({super.key, required this.api});

  final FmsApi api;

  @override
  State<MapProjectPage> createState() => _MapProjectPageState();
}

class _MapProjectPageState extends State<MapProjectPage> {
  late Future<List<MapProjectSummaryDto>> _projects;
  MapProjectDraftDto? _draft;
  Object? _failure;
  bool _busy = false;

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
      final project = await widget.api.openMapProject(mapName);
      if (mounted) setState(() => _draft = project.draft);
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
      if (mounted) setState(() => _draft = saved);
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
      if (mounted) setState(() => _draft = null);
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
      if (!validation.valid) {
        throw StateError(validation.errorCodes.join(', '));
      }
      await widget.api.publishMapDraft(
        draft.mapName,
        PublishMapDto(
          expectedDraftRevision: draft.draftRevision,
          publishedBy: 'browser-session',
        ),
      );
    } catch (error) {
      if (mounted) setState(() => _failure = error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  List<MapWaypointPresentation> _waypoints() {
    final draft = _draft;
    if (draft == null) return const [];
    return [
      for (final waypoint in draft.waypoints)
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
          ),
    ];
  }

  void _waypointMoved(MapWaypointPresentation moved) {
    final draft = _draft;
    if (draft == null) return;
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
      _draft = MapProjectDraftDto(
        mapName: draft.mapName,
        formatVersion: draft.formatVersion,
        draftRevision: draft.draftRevision,
        sourceUuids: draft.sourceUuids,
        stagedSourceTokens: draft.stagedSourceTokens,
        waypoints: updated,
        features: draft.features,
        runtimeProfileHash: draft.runtimeProfileHash,
      );
    });
  }

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.all(28),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        PageHeading(
          title: '맵 프로젝트',
          description: 'SLAM 좌표에서 Waypoint와 운영 시설을 작성하고 Gateway Draft로 저장합니다.',
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
          const SizedBox(height: 14),
          GatewayFailurePanel(error: _failure!),
        ],
        const SizedBox(height: 18),
        Expanded(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SizedBox(
                width: 270,
                child: _ProjectList(projects: _projects, onOpen: _open),
              ),
              const SizedBox(width: 18),
              Expanded(
                child: Stack(
                  children: [
                    Positioned.fill(
                      child: MapWorkspace(
                        waypoints: _waypoints(),
                        onWaypointMoved: _waypointMoved,
                      ),
                    ),
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
  );
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
              if (!snapshot.hasData) {
                return const Center(child: CircularProgressIndicator());
              }
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
