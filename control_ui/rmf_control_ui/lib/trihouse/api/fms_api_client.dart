import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'fms_api.dart';
import 'fms_models.dart';

typedef OperationsSocketConnector = WebSocketChannel Function(Uri uri);

class FmsApiException implements Exception {
  const FmsApiException({
    required this.method,
    required this.uri,
    required this.statusCode,
    required this.responseBody,
  });

  final String method;
  final Uri uri;
  final int statusCode;
  final String responseBody;

  @override
  String toString() =>
      'FmsApiException($method $uri returned $statusCode: $responseBody)';
}

class FmsApiClient implements FmsApi {
  FmsApiClient({
    required this.baseUri,
    http.Client? httpClient,
    OperationsSocketConnector? operationsSocketConnector,
  }) : _httpClient = httpClient ?? http.Client(),
       _operationsSocketConnector =
           operationsSocketConnector ?? WebSocketChannel.connect;

  final Uri baseUri;
  final http.Client _httpClient;
  final OperationsSocketConnector _operationsSocketConnector;

  Uri _uri(String publicPath) {
    if (!publicPath.startsWith('/api/v1/')) {
      throw ArgumentError.value(publicPath, 'publicPath', 'must use /api/v1/');
    }
    return baseUri.resolve(publicPath);
  }

  Uri _webSocketUri(String publicPath) {
    final httpUri = _uri(publicPath);
    return httpUri.replace(
      scheme: switch (httpUri.scheme) {
        'http' => 'ws',
        'https' => 'wss',
        _ => httpUri.scheme,
      },
    );
  }

  String _mapPath(String mapName, [String suffix = '']) =>
      '/api/v1/map-projects/${Uri.encodeComponent(mapName)}$suffix';

  JsonObject _object(String body) => (jsonDecode(body) as Map<Object?, Object?>)
      .map((key, value) => MapEntry(key as String, value));

  List<JsonObject> _objects(String body) => (jsonDecode(body) as List<Object?>)
      .map(
        (value) => (value as Map<Object?, Object?>).map(
          (key, item) => MapEntry(key as String, item),
        ),
      )
      .toList(growable: false);

  void _requireSuccess(String method, Uri uri, http.BaseResponse response) {
    if (response.statusCode >= 200 && response.statusCode < 300) return;
    throw FmsApiException(
      method: method,
      uri: uri,
      statusCode: response.statusCode,
      responseBody: response is http.Response ? response.body : '',
    );
  }

  Future<http.Response> _sendJson(
    String method,
    String path, {
    JsonObject? body,
    Map<String, String> headers = const {},
  }) async {
    final uri = _uri(path);
    final request = http.Request(method, uri)
      ..headers.addAll({
        'accept': 'application/json',
        if (body != null) 'content-type': 'application/json',
        ...headers,
      });
    if (body != null) request.body = jsonEncode(body);
    final streamed = await _httpClient.send(request);
    final response = await http.Response.fromStream(streamed);
    _requireSuccess(method, uri, response);
    return response;
  }

  @override
  Future<List<InventoryLotDto>> listInventory() async {
    final response = await _sendJson('GET', '/api/v1/inventory/lots');
    return List.unmodifiable(
      _objects(response.body).map(InventoryLotDto.fromJson),
    );
  }

  @override
  Future<List<MapProjectSummaryDto>> listMapProjects() async {
    final response = await _sendJson('GET', '/api/v1/map-projects');
    return List.unmodifiable(
      _objects(response.body).map(MapProjectSummaryDto.fromJson),
    );
  }

  @override
  Future<MapProjectOpenDto> openMapProject(String mapName) async {
    final response = await _sendJson(
      'POST',
      '/api/v1/map-projects',
      body: {'map_name': mapName},
    );
    return MapProjectOpenDto.fromJson(_object(response.body));
  }

  @override
  Future<StagedMapSourceDto> stageMapSource(
    String mapName,
    MapSourceUploadDto source,
  ) async {
    final uri = _uri(_mapPath(mapName, '/sources/stage'));
    final request = http.MultipartRequest('POST', uri)
      ..fields['source_type'] = source.sourceType
      ..files.add(
        http.MultipartFile.fromBytes(
          'source',
          source.bytes,
          filename: source.fileName,
          contentType: MediaType.parse(source.mimeType),
        ),
      );
    final streamed = await _httpClient.send(request);
    final response = await http.Response.fromStream(streamed);
    _requireSuccess('POST', uri, response);
    return StagedMapSourceDto.fromJson(_object(response.body));
  }

  @override
  Future<MapProjectDraftDto> saveMapDraft(
    MapProjectDraftDto draft, {
    int? expectedRevision,
  }) async {
    final response = await _sendJson(
      'PUT',
      _mapPath(draft.mapName),
      body: draft.toJson(),
      headers: {if (expectedRevision != null) 'If-Match': '$expectedRevision'},
    );
    return MapProjectDraftDto.fromJson(_object(response.body));
  }

  @override
  Future<void> deleteMapDraft(String mapName) async {
    await _sendJson('DELETE', _mapPath(mapName, '/draft'));
  }

  @override
  Future<MapValidationDto> validateMapDraft(String mapName) async {
    final response = await _sendJson('POST', _mapPath(mapName, '/validate'));
    return MapValidationDto.fromJson(_object(response.body));
  }

  @override
  Future<PublishedMapDto> publishMapDraft(
    String mapName,
    PublishMapDto request,
  ) async {
    final response = await _sendJson(
      'POST',
      _mapPath(mapName, '/publish'),
      body: request.toJson(),
    );
    return PublishedMapDto.fromJson(_object(response.body));
  }

  @override
  Future<OutboundOrderDto> createOutboundOrder(
    OutboundOrderRequestDto request, {
    required String idempotencyKey,
  }) async {
    final response = await _sendJson(
      'POST',
      '/api/v1/orders',
      body: request.toJson(),
      headers: {'Idempotency-Key': idempotencyKey},
    );
    return OutboundOrderDto.fromJson(_object(response.body));
  }

  @override
  Future<JobDetailDto> getJob(int jobId) async {
    final response = await _sendJson('GET', '/api/v1/jobs/$jobId');
    return JobDetailDto.fromJson(_object(response.body));
  }

  @override
  Future<JobDetailDto> completeJob(
    int jobId,
    WorkerCompletionDto request, {
    required String idempotencyKey,
  }) async {
    final response = await _sendJson(
      'POST',
      '/api/v1/jobs/$jobId/worker-completion',
      body: request.toJson(),
      headers: {'Idempotency-Key': idempotencyKey},
    );
    return JobDetailDto.fromJson(_object(response.body));
  }

  @override
  Stream<OperationsEventDto> operationsEvents() {
    final channel = _operationsSocketConnector(
      _webSocketUri('/api/v1/operations/ws'),
    );
    return channel.stream.map((message) {
      final text = switch (message) {
        String value => value,
        List<int> value => utf8.decode(value),
        _ => throw FormatException(
          'Unsupported operations event payload: ${message.runtimeType}',
        ),
      };
      return OperationsEventDto.fromJson(_object(text));
    });
  }

  @override
  Future<void> decideEmergency(
    int incidentId,
    EmergencyDecisionDto request, {
    required String idempotencyKey,
  }) async {
    await _sendJson(
      'POST',
      '/api/v1/incidents/$incidentId/decision',
      body: request.toJson(),
      headers: {'Idempotency-Key': idempotencyKey},
    );
  }
}
