class MapAiProposal {
  const MapAiProposal({
    required this.provider,
    required this.summary,
    required this.waypoints,
    required this.lanes,
    required this.warnings,
  });

  factory MapAiProposal.fromJson(Map<String, dynamic> json) => MapAiProposal(
    provider: json['provider'] as String? ?? 'Codex',
    summary: json['summary'] as String? ?? '',
    waypoints: (json['waypoints'] as List<dynamic>? ?? const [])
        .map((value) => Map<String, dynamic>.from(value as Map))
        .toList(),
    lanes: (json['lanes'] as List<dynamic>? ?? const [])
        .map((value) => Map<String, dynamic>.from(value as Map))
        .toList(),
    warnings: (json['warnings'] as List<dynamic>? ?? const [])
        .map((value) => value.toString())
        .toList(),
  );

  final String provider;
  final String summary;
  final List<Map<String, dynamic>> waypoints;
  final List<Map<String, dynamic>> lanes;
  final List<String> warnings;
}
