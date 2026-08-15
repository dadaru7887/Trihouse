import 'package:flutter/material.dart';

import '../../api/fms_models.dart';

class PhysicalFeatureLayer extends StatelessWidget {
  const PhysicalFeatureLayer({
    super.key,
    required this.waypoints,
    required this.features,
  });

  final List<JsonObject> waypoints;
  final List<JsonObject> features;

  @override
  Widget build(BuildContext context) {
    final importedWaypoints = waypoints
        .where((value) => value['origin'] == 'physical_features_import')
        .toList(growable: false);
    final bottlenecks = features
        .where((value) => value['type'] == 'bottleneck')
        .toList(growable: false);
    final markers = features
        .where((value) => value['type'] == 'fiducial_binding')
        .toList(growable: false);
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.all(18),
            child: Wrap(
              spacing: 10,
              runSpacing: 8,
              children: [
                Chip(label: Text('Waypoint ${importedWaypoints.length}')),
                Chip(label: Text('Bottleneck ${bottlenecks.length}')),
                Chip(label: Text('Marker pose ${markers.length}')),
              ],
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                const _SectionTitle('Waypoint / yaw'),
                for (final waypoint in importedWaypoints)
                  _RecordTile(
                    icon: Icons.location_on_outlined,
                    title: '${waypoint['display_name']}',
                    detail:
                        '(${_fixed(waypoint['x'])}, ${_fixed(waypoint['y'])}, ${_fixed(waypoint['yaw'])})',
                  ),
                const SizedBox(height: 18),
                const _SectionTitle('Bottleneck'),
                for (final feature in bottlenecks)
                  _RecordTile(
                    icon: Icons.adjust,
                    title: '${feature['display_name']}',
                    detail:
                        '(${_fixed(feature['x'])}, ${_fixed(feature['y'])}) · radius ${_fixed(feature['radius_m'], digits: 2)} m',
                  ),
                const SizedBox(height: 18),
                const _SectionTitle('Marker recognition pose'),
                for (final feature in markers)
                  _RecordTile(
                    icon: Icons.qr_code_2,
                    title:
                        'marker ${feature['marker_id']} · (${_fixed(feature['x'])}, ${_fixed(feature['y'])}, ${_fixed(feature['yaw'])})',
                    detail:
                        '${feature['dictionary']} · ${feature['target_location_code']}',
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

String _fixed(Object? value, {int digits = 3}) =>
    (value as num).toDouble().toStringAsFixed(digits);

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.label);

  final String label;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Text(label, style: const TextStyle(fontWeight: FontWeight.w800)),
  );
}

class _RecordTile extends StatelessWidget {
  const _RecordTile({
    required this.icon,
    required this.title,
    required this.detail,
  });

  final IconData icon;
  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) => ListTile(
    dense: true,
    contentPadding: EdgeInsets.zero,
    leading: Icon(icon, size: 20),
    title: Text(title),
    subtitle: Text(detail),
  );
}
