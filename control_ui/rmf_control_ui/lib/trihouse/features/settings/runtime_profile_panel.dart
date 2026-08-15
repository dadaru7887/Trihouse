import 'package:flutter/material.dart';

import '../../api/fms_models.dart';

class RuntimeProfilePanel extends StatelessWidget {
  const RuntimeProfilePanel({super.key, required this.profile});

  final Future<RuntimeProfileDto> profile;

  @override
  Widget build(BuildContext context) => Container(
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: const Color(0xFFE2E8F0)),
    ),
    child: FutureBuilder<RuntimeProfileDto>(
      future: profile,
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return Center(child: Text('Runtime profile 오류: ${snapshot.error}'));
        }
        final value = snapshot.data;
        if (value == null) {
          return const Center(child: CircularProgressIndicator());
        }
        return SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
            Text(
              value.profileName,
              style: Theme.of(context).textTheme.titleLarge?.copyWith(
                fontWeight: FontWeight.w800,
              ),
            ),
            const SizedBox(height: 6),
            const Text('P0 읽기 전용 · 변경은 후속 범위입니다.'),
            const SizedBox(height: 12),
            SelectableText('profile_hash: ${value.profileHash}'),
            const SizedBox(height: 18),
            _ProfileSection('Controller', value.controller),
            _ProfileSection('Planner', value.planner),
            _ProfileSection('Local costmap', value.localCostmap),
            _ProfileSection('Global costmap', value.globalCostmap),
            _ProfileSection('Footprint / robot dimensions', value.robot),
            _ProfileSection('Max speeds', value.maxSpeeds),
            _ProfileSection('Goal tolerances', value.goalTolerances),
            _ProfileSection('Progress tolerances', value.progressTolerances),
            _ProfileSection('Wheel parameters', value.wheelParameters),
            const SizedBox(height: 8),
            const Text('Source files', style: TextStyle(fontWeight: FontWeight.w800)),
            for (final source in value.sourceFiles) SelectableText(source),
            ],
          ),
        );
      },
    ),
  );
}

class _ProfileSection extends StatelessWidget {
  const _ProfileSection(this.title, this.values);

  final String title;
  final JsonObject values;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 16),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: const TextStyle(fontWeight: FontWeight.w800)),
        const SizedBox(height: 4),
        for (final entry in values.entries)
          SelectableText(
            '${entry.key}: ${_display(entry.value)}',
            style: const TextStyle(height: 1.45),
          ),
      ],
    ),
  );
}

String _display(Object? value) => value == null ? 'unavailable' : '$value';
