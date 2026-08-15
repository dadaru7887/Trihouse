import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'map_ai_service_models.dart';

String get _endpoint =>
    (Platform.environment['ROBOSAPIENS_CODEX_MAP_ENDPOINT'] ?? '').trim();

bool get isMapAiConfigured => _endpoint.isNotEmpty;

Future<MapAiProposal?> requestMapAiProposal(
  Map<String, dynamic> request,
) async {
  if (!isMapAiConfigured) return null;
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 8);
  try {
    final httpRequest = await client.postUrl(Uri.parse(_endpoint));
    httpRequest.headers.contentType = ContentType.json;
    httpRequest.headers.set('Accept', 'application/json');
    httpRequest.write(jsonEncode(request));
    final response = await httpRequest.close().timeout(
      const Duration(seconds: 45),
    );
    final body = await utf8.decoder.bind(response).join();
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw HttpException(
        'Codex map endpoint returned ${response.statusCode}',
        uri: Uri.parse(_endpoint),
      );
    }
    return MapAiProposal.fromJson(jsonDecode(body) as Map<String, dynamic>);
  } finally {
    client.close(force: true);
  }
}
