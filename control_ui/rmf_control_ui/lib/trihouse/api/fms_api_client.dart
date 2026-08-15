import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'browser_http_client.dart';
import 'fms_api.dart';
import 'fms_models.dart';

typedef OperationsSocketConnector = WebSocketChannel Function(Uri uri);
typedef BrowserHttpClientFactory =
    http.Client Function({required bool withCredentials});

enum GatewayCredentialMode {
  sameOriginSessionCookie,
  credentialedCrossOriginSessionCookie,
}

enum FmsApiErrorKind {
  configuration,
  invalidRequest,
  authentication,
  authorization,
  notFound,
  conflict,
  validation,
  server,
  network,
  invalidResponse,
  webSocket,
}

class FmsApiException implements Exception {
  const FmsApiException({
    required this.kind,
    required this.operation,
    required this.diagnosticDetail,
    this.uri,
    this.statusCode,
    this.cause,
  });

  final FmsApiErrorKind kind;
  final String operation;
  final Uri? uri;
  final int? statusCode;
  final String diagnosticDetail;
  final Object? cause;

  String get responseBody => diagnosticDetail;

  String get safeMessage => switch (kind) {
    FmsApiErrorKind.configuration => 'Gateway 연결 설정을 확인하세요.',
    FmsApiErrorKind.invalidRequest => '요청 내용을 확인하세요.',
    FmsApiErrorKind.authentication => '세션이 만료되었습니다. 다시 로그인하세요.',
    FmsApiErrorKind.authorization => '이 작업을 수행할 권한이 없습니다.',
    FmsApiErrorKind.notFound => '요청한 운영 정보를 찾을 수 없습니다.',
    FmsApiErrorKind.conflict => '다른 변경과 충돌했습니다. 새로고침 후 다시 시도하세요.',
    FmsApiErrorKind.validation => 'Gateway가 요청 내용을 승인하지 않았습니다.',
    FmsApiErrorKind.server => 'Gateway가 요청을 처리하지 못했습니다.',
    FmsApiErrorKind.network => 'Gateway에 연결할 수 없습니다.',
    FmsApiErrorKind.invalidResponse => 'Gateway 응답 형식을 확인할 수 없습니다.',
    FmsApiErrorKind.webSocket => '실시간 운영 연결을 확인할 수 없습니다.',
  };

  @override
  String toString() {
    final target = uri == null ? '' : ' $uri';
    final status = statusCode == null ? '' : ' status=$statusCode';
    return 'FmsApiException(${kind.name} $operation$target$status: '
        '$diagnosticDetail)';
  }
}

String fmsApiUserMessage(Object error) => switch (error) {
  FmsApiException failure => failure.safeMessage,
  _ => '요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.',
};

class GatewayClientConfiguration {
  const GatewayClientConfiguration._({
    required this.baseUri,
    required this.credentialMode,
  });

  factory GatewayClientConfiguration.resolve({
    required Uri pageUri,
    String? configuredBaseUrl,
    bool allowCredentialedCrossOrigin = false,
  }) {
    _validateHttpUri(pageUri, operation: 'configure page origin');
    final configured = configuredBaseUrl?.trim() ?? '';
    final candidate = configured.isEmpty
        ? _origin(pageUri)
        : Uri.parse(configured);
    _validateHttpUri(candidate, operation: 'configure Gateway');
    if (candidate.userInfo.isNotEmpty) {
      throw const FmsApiException(
        kind: FmsApiErrorKind.configuration,
        operation: 'configure Gateway',
        diagnosticDetail: 'Gateway URI must not embed user information',
      );
    }
    if (candidate.hasQuery || candidate.hasFragment) {
      throw const FmsApiException(
        kind: FmsApiErrorKind.configuration,
        operation: 'configure Gateway',
        diagnosticDetail: 'Gateway URI must not contain query or fragment',
      );
    }
    if (candidate.path.isNotEmpty && candidate.path != '/') {
      throw const FmsApiException(
        kind: FmsApiErrorKind.configuration,
        operation: 'configure Gateway',
        diagnosticDetail: 'Gateway URI must be an origin without a path',
      );
    }
    final baseUri = _origin(candidate);
    final crossOrigin = !_sameOrigin(pageUri, baseUri);
    if (crossOrigin && !allowCredentialedCrossOrigin) {
      throw FmsApiException(
        kind: FmsApiErrorKind.configuration,
        operation: 'configure Gateway',
        uri: baseUri,
        diagnosticDetail:
            'Cross-origin Gateway requires explicit credentialed cookie mode',
      );
    }
    if (crossOrigin && baseUri.scheme != 'https') {
      throw FmsApiException(
        kind: FmsApiErrorKind.configuration,
        operation: 'configure Gateway',
        uri: baseUri,
        diagnosticDetail:
            'Credentialed cross-origin session cookies require HTTPS',
      );
    }
    return GatewayClientConfiguration._(
      baseUri: baseUri,
      credentialMode: crossOrigin
          ? GatewayCredentialMode.credentialedCrossOriginSessionCookie
          : GatewayCredentialMode.sameOriginSessionCookie,
    );
  }

  final Uri baseUri;
  final GatewayCredentialMode credentialMode;

  bool get includeCrossOriginCredentials =>
      credentialMode ==
      GatewayCredentialMode.credentialedCrossOriginSessionCookie;

  static Uri _origin(Uri uri) => Uri(
    scheme: uri.scheme,
    host: uri.host,
    port: uri.hasPort ? uri.port : null,
    path: '/',
  );

  static bool _sameOrigin(Uri first, Uri second) =>
      first.scheme == second.scheme &&
      first.host == second.host &&
      first.port == second.port;
}

void _validateHttpUri(Uri uri, {required String operation}) {
  if ((uri.scheme != 'http' && uri.scheme != 'https') || uri.host.isEmpty) {
    throw FmsApiException(
      kind: FmsApiErrorKind.configuration,
      operation: operation,
      uri: uri,
      diagnosticDetail: 'Only absolute http(s) Gateway URIs are supported',
    );
  }
}

class FmsApiClient implements FmsApi {
  FmsApiClient({
    required Uri baseUri,
    http.Client? httpClient,
    OperationsSocketConnector? operationsSocketConnector,
  }) : baseUri = _checkedBaseUri(baseUri),
       _httpClient = httpClient ?? http.Client(),
       _operationsSocketConnector =
           operationsSocketConnector ?? WebSocketChannel.connect;

  factory FmsApiClient.forBrowser({
    required GatewayClientConfiguration configuration,
    BrowserHttpClientFactory? browserHttpClientFactory,
    OperationsSocketConnector? operationsSocketConnector,
  }) {
    final factory = browserHttpClientFactory ?? createBrowserHttpClient;
    return FmsApiClient(
      baseUri: configuration.baseUri,
      httpClient: factory(
        withCredentials: configuration.includeCrossOriginCredentials,
      ),
      operationsSocketConnector: operationsSocketConnector,
    );
  }

  final Uri baseUri;
  final http.Client _httpClient;
  final OperationsSocketConnector _operationsSocketConnector;

  static Uri _checkedBaseUri(Uri uri) {
    _validateHttpUri(uri, operation: 'construct FmsApiClient');
    return uri;
  }

  Uri _uri(String publicPath) {
    if (!publicPath.startsWith('/api/v1/')) {
      throw FmsApiException(
        kind: FmsApiErrorKind.invalidRequest,
        operation: 'build public Gateway URI',
        diagnosticDetail: 'Path must use /api/v1/: $publicPath',
      );
    }
    return baseUri.resolve(publicPath);
  }

  Uri _webSocketUri(String publicPath) {
    final httpUri = _uri(publicPath);
    return httpUri.replace(scheme: httpUri.scheme == 'https' ? 'wss' : 'ws');
  }

  String _validatedMapName(String mapName) {
    if (mapName == '.' || mapName == '..') {
      throw FmsApiException(
        kind: FmsApiErrorKind.invalidRequest,
        operation: 'build map project request',
        diagnosticDetail:
            'Map name must not be an HTTP path dot segment: $mapName',
      );
    }
    return mapName;
  }

  String _mapPath(String mapName, [String suffix = '']) =>
      '/api/v1/map-projects/'
      '${Uri.encodeComponent(_validatedMapName(mapName))}$suffix';

  FmsApiException _invalidResponse(String operation, Uri uri, Object error) =>
      FmsApiException(
        kind: FmsApiErrorKind.invalidResponse,
        operation: operation,
        uri: uri,
        diagnosticDetail: '$error',
        cause: error,
      );

  JsonObject _object(http.Response response, String operation) {
    final uri = response.request?.url ?? baseUri;
    try {
      return (jsonDecode(response.body) as Map<Object?, Object?>).map(
        (key, value) => MapEntry(key as String, value),
      );
    } catch (error) {
      throw _invalidResponse(operation, uri, error);
    }
  }

  List<JsonObject> _objects(http.Response response, String operation) {
    final uri = response.request?.url ?? baseUri;
    try {
      return (jsonDecode(response.body) as List<Object?>)
          .map(
            (value) => (value as Map<Object?, Object?>).map(
              (key, item) => MapEntry(key as String, item),
            ),
          )
          .toList(growable: false);
    } catch (error) {
      throw _invalidResponse(operation, uri, error);
    }
  }

  FmsApiErrorKind _statusKind(int statusCode) => switch (statusCode) {
    401 => FmsApiErrorKind.authentication,
    403 => FmsApiErrorKind.authorization,
    404 => FmsApiErrorKind.notFound,
    409 || 412 => FmsApiErrorKind.conflict,
    400 || 422 => FmsApiErrorKind.validation,
    _ => FmsApiErrorKind.server,
  };

  void _requireSuccess(String method, Uri uri, http.BaseResponse response) {
    if (response.statusCode >= 200 && response.statusCode < 300) return;
    throw FmsApiException(
      kind: _statusKind(response.statusCode),
      operation: method,
      uri: uri,
      statusCode: response.statusCode,
      diagnosticDetail: response is http.Response ? response.body : '',
    );
  }

  FmsApiException _networkFailure(String operation, Uri uri, Object error) =>
      FmsApiException(
        kind: FmsApiErrorKind.network,
        operation: operation,
        uri: uri,
        diagnosticDetail: '$error',
        cause: error,
      );

  Future<http.Response> _sendJson(
    String method,
    String path, {
    JsonObject? body,
    Map<String, String> headers = const {},
  }) async {
    final uri = _uri(path);
    try {
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
    } on FmsApiException {
      rethrow;
    } catch (error) {
      throw _networkFailure(method, uri, error);
    }
  }

  String _idempotencyKey(String value, String operation) {
    if (value.trim().isEmpty) {
      throw FmsApiException(
        kind: FmsApiErrorKind.invalidRequest,
        operation: operation,
        diagnosticDetail: 'Idempotency-Key must not be empty',
      );
    }
    return value;
  }

  @override
  Future<List<InventoryLotDto>> listInventory() async {
    const operation = 'GET inventory lots';
    final response = await _sendJson('GET', '/api/v1/inventory/lots');
    try {
      return List.unmodifiable(
        _objects(response, operation).map(InventoryLotDto.fromJson),
      );
    } on FmsApiException {
      rethrow;
    } catch (error) {
      throw _invalidResponse(
        operation,
        response.request?.url ?? baseUri,
        error,
      );
    }
  }

  @override
  Future<List<MapProjectSummaryDto>> listMapProjects() async {
    const operation = 'GET map projects';
    final response = await _sendJson('GET', '/api/v1/map-projects');
    try {
      return List.unmodifiable(
        _objects(response, operation).map(MapProjectSummaryDto.fromJson),
      );
    } on FmsApiException {
      rethrow;
    } catch (error) {
      throw _invalidResponse(
        operation,
        response.request?.url ?? baseUri,
        error,
      );
    }
  }

  @override
  Future<MapProjectOpenDto> openMapProject(String mapName) async {
    const operation = 'POST open map project';
    _validatedMapName(mapName);
    final response = await _sendJson(
      'POST',
      '/api/v1/map-projects',
      body: {'map_name': mapName},
    );
    try {
      return MapProjectOpenDto.fromJson(_object(response, operation));
    } on FmsApiException {
      rethrow;
    } catch (error) {
      throw _invalidResponse(
        operation,
        response.request?.url ?? baseUri,
        error,
      );
    }
  }

  @override
  Future<StagedMapSourceDto> stageMapSource(
    String mapName,
    MapSourceUploadDto source,
  ) async {
    final uri = _uri(_mapPath(mapName, '/sources/stage'));
    const operation = 'POST stage map source';
    late http.MultipartRequest request;
    try {
      request = http.MultipartRequest('POST', uri)
        ..fields['source_type'] = source.sourceType
        ..files.add(
          http.MultipartFile.fromBytes(
            'source',
            source.bytes,
            filename: source.fileName,
            contentType: MediaType.parse(source.mimeType),
          ),
        );
    } on FormatException catch (error) {
      throw FmsApiException(
        kind: FmsApiErrorKind.invalidRequest,
        operation: operation,
        uri: uri,
        diagnosticDetail: '$error',
        cause: error,
      );
    }

    late http.Response response;
    try {
      final streamed = await _httpClient.send(request);
      response = await http.Response.fromStream(streamed);
      _requireSuccess('POST', uri, response);
    } on FmsApiException {
      rethrow;
    } catch (error) {
      throw _networkFailure(operation, uri, error);
    }

    try {
      return StagedMapSourceDto.fromJson(_object(response, operation));
    } on FmsApiException {
      rethrow;
    } catch (error) {
      throw _invalidResponse(operation, uri, error);
    }
  }

  @override
  Future<MapProjectDraftDto> saveMapDraft(
    MapProjectDraftDto draft, {
    int? expectedRevision,
  }) async {
    const operation = 'PUT map draft';
    final response = await _sendJson(
      'PUT',
      _mapPath(draft.mapName),
      body: draft.toJson(),
      headers: {if (expectedRevision != null) 'If-Match': '$expectedRevision'},
    );
    try {
      return MapProjectDraftDto.fromJson(_object(response, operation));
    } on FmsApiException {
      rethrow;
    } catch (error) {
      throw _invalidResponse(
        operation,
        response.request?.url ?? baseUri,
        error,
      );
    }
  }

  @override
  Future<void> deleteMapDraft(String mapName) async {
    await _sendJson('DELETE', _mapPath(mapName, '/draft'));
  }

  @override
  Future<MapValidationDto> validateMapDraft(String mapName) async {
    const operation = 'POST validate map draft';
    final response = await _sendJson('POST', _mapPath(mapName, '/validate'));
    try {
      return MapValidationDto.fromJson(_object(response, operation));
    } on FmsApiException {
      rethrow;
    } catch (error) {
      throw _invalidResponse(
        operation,
        response.request?.url ?? baseUri,
        error,
      );
    }
  }

  @override
  Future<PublishedMapDto> publishMapDraft(
    String mapName,
    PublishMapDto request,
  ) async {
    const operation = 'POST publish map draft';
    final response = await _sendJson(
      'POST',
      _mapPath(mapName, '/publish'),
      body: request.toJson(),
    );
    try {
      return PublishedMapDto.fromJson(_object(response, operation));
    } on FmsApiException {
      rethrow;
    } catch (error) {
      throw _invalidResponse(
        operation,
        response.request?.url ?? baseUri,
        error,
      );
    }
  }

  @override
  Future<RuntimeProfileDto> getRuntimeProfile() async {
    const operation = 'GET pinky runtime profile';
    final response = await _sendJson(
      'GET',
      '/api/v1/runtime-profiles/pinky-pro-simulation',
    );
    try {
      return RuntimeProfileDto.fromJson(_object(response, operation));
    } on FmsApiException {
      rethrow;
    } catch (error) {
      throw _invalidResponse(
        operation,
        response.request?.url ?? baseUri,
        error,
      );
    }
  }

  @override
  Future<OutboundOrderDto> createOutboundOrder(
    OutboundOrderRequestDto request, {
    required String idempotencyKey,
  }) async {
    const operation = 'POST outbound order';
    final key = _idempotencyKey(idempotencyKey, operation);
    final response = await _sendJson(
      'POST',
      '/api/v1/orders',
      body: request.toJson(),
      headers: {'Idempotency-Key': key},
    );
    try {
      return OutboundOrderDto.fromJson(_object(response, operation));
    } on FmsApiException {
      rethrow;
    } catch (error) {
      throw _invalidResponse(
        operation,
        response.request?.url ?? baseUri,
        error,
      );
    }
  }

  @override
  Future<JobDetailDto> getJob(int jobId) async {
    const operation = 'GET job';
    final response = await _sendJson('GET', '/api/v1/jobs/$jobId');
    try {
      return JobDetailDto.fromJson(_object(response, operation));
    } on FmsApiException {
      rethrow;
    } catch (error) {
      throw _invalidResponse(
        operation,
        response.request?.url ?? baseUri,
        error,
      );
    }
  }

  @override
  Future<JobDetailDto> completeJob(
    int jobId,
    WorkerCompletionDto request, {
    required String idempotencyKey,
  }) async {
    const operation = 'POST worker completion';
    final key = _idempotencyKey(idempotencyKey, operation);
    final response = await _sendJson(
      'POST',
      '/api/v1/jobs/$jobId/worker-completion',
      body: request.toJson(),
      headers: {'Idempotency-Key': key},
    );
    try {
      return JobDetailDto.fromJson(_object(response, operation));
    } on FmsApiException {
      rethrow;
    } catch (error) {
      throw _invalidResponse(
        operation,
        response.request?.url ?? baseUri,
        error,
      );
    }
  }

  @override
  Stream<OperationsEventDto> operationsEvents() {
    const operation = 'CONNECT operations WebSocket';
    final uri = _webSocketUri('/api/v1/operations/ws');
    late WebSocketChannel channel;
    try {
      channel = _operationsSocketConnector(uri);
    } catch (error) {
      return Stream.error(
        FmsApiException(
          kind: FmsApiErrorKind.webSocket,
          operation: operation,
          uri: uri,
          diagnosticDetail: '$error',
          cause: error,
        ),
      );
    }
    return channel.stream.transform(
      StreamTransformer<Object?, OperationsEventDto>.fromHandlers(
        handleData: (message, sink) {
          try {
            final text = switch (message) {
              String value => value,
              List<int> value => utf8.decode(value),
              _ => throw FormatException(
                'Unsupported operations event payload: '
                '${message.runtimeType}',
              ),
            };
            final decoded = jsonDecode(text) as Map<Object?, Object?>;
            sink.add(
              OperationsEventDto.fromJson(
                decoded.map((key, value) => MapEntry(key as String, value)),
              ),
            );
          } catch (error) {
            sink.addError(_invalidResponse(operation, uri, error));
          }
        },
        handleError: (error, stackTrace, sink) {
          sink.addError(
            error is FmsApiException
                ? error
                : FmsApiException(
                    kind: FmsApiErrorKind.webSocket,
                    operation: operation,
                    uri: uri,
                    diagnosticDetail: '$error',
                    cause: error,
                  ),
            stackTrace,
          );
        },
      ),
    );
  }

  @override
  Future<void> decideEmergency(
    int incidentId,
    EmergencyDecisionDto request, {
    required String idempotencyKey,
  }) async {
    const operation = 'POST emergency decision';
    final key = _idempotencyKey(idempotencyKey, operation);
    await _sendJson(
      'POST',
      '/api/v1/incidents/$incidentId/decision',
      body: request.toJson(),
      headers: {'Idempotency-Key': key},
    );
  }
}
