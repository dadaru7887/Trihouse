import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rmf_control_ui/trihouse/api/fms_api_client.dart';
import 'package:rmf_control_ui/trihouse/api/fms_models.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

class _ErrorWebSocketChannel implements WebSocketChannel {
  _ErrorWebSocketChannel(this.stream);

  @override
  final Stream<Object?> stream;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  test('HTTP status failures have stable kinds and safe messages', () async {
    final client = FmsApiClient(
      baseUri: Uri.parse('https://gateway.example'),
      httpClient: MockClient(
        (_) async => http.Response('private session diagnostic', 401),
      ),
    );

    late FmsApiException failure;
    try {
      await client.listInventory();
      fail('request should fail');
    } on FmsApiException catch (error) {
      failure = error;
    }

    expect(failure.kind, FmsApiErrorKind.authentication);
    expect(failure.statusCode, 401);
    expect(failure.diagnosticDetail, contains('private session diagnostic'));
    expect(failure.safeMessage, isNot(contains('private session diagnostic')));
    expect(fmsApiUserMessage(failure), failure.safeMessage);
  });

  test('network failures are wrapped without losing diagnostics', () async {
    final client = FmsApiClient(
      baseUri: Uri.parse('https://gateway.example'),
      httpClient: MockClient((request) async {
        throw http.ClientException('connection refused', request.url);
      }),
    );

    await expectLater(
      client.listInventory(),
      throwsA(
        isA<FmsApiException>()
            .having((error) => error.kind, 'kind', FmsApiErrorKind.network)
            .having(
              (error) => error.diagnosticDetail,
              'diagnostic',
              contains('connection refused'),
            ),
      ),
    );
  });

  test('malformed successful JSON is an invalid-response failure', () async {
    final client = FmsApiClient(
      baseUri: Uri.parse('https://gateway.example'),
      httpClient: MockClient((_) async => http.Response('{not-json', 200)),
    );

    await expectLater(
      client.listInventory(),
      throwsA(
        isA<FmsApiException>().having(
          (error) => error.kind,
          'kind',
          FmsApiErrorKind.invalidResponse,
        ),
      ),
    );
  });

  test('empty idempotency keys fail before transport', () async {
    var sends = 0;
    final client = FmsApiClient(
      baseUri: Uri.parse('https://gateway.example'),
      httpClient: MockClient((_) async {
        sends++;
        return http.Response(jsonEncode({}), 200);
      }),
    );

    await expectLater(
      client.createOutboundOrder(
        OutboundOrderRequestDto(
          externalReference: null,
          requester: 'W-OP-01',
          priority: 'normal',
          allowPartialFulfillment: false,
          lines: const [
            OutboundOrderLineDto(productCode: 'MILK-1L', quantity: 1),
          ],
        ),
        idempotencyKey: '   ',
      ),
      throwsA(
        isA<FmsApiException>().having(
          (error) => error.kind,
          'kind',
          FmsApiErrorKind.invalidRequest,
        ),
      ),
    );
    await expectLater(
      client.completeJob(
        42,
        WorkerCompletionDto(
          workerId: 'W-OP-01',
          completionNote: null,
          acknowledgedManualItemIds: const [],
        ),
        idempotencyKey: '',
      ),
      throwsA(isA<FmsApiException>()),
    );
    await expectLater(
      client.decideEmergency(
        6,
        const EmergencyDecisionDto(
          workerId: 'W-OP-01',
          decision: EmergencyDecision.raiseAlarm,
          reason: 'unsafe',
        ),
        idempotencyKey: '',
      ),
      throwsA(isA<FmsApiException>()),
    );

    expect(sends, 0);
  });

  test('multipart validation errors use the invalid-request kind', () async {
    var sends = 0;
    final client = FmsApiClient(
      baseUri: Uri.parse('https://gateway.example'),
      httpClient: MockClient((_) async {
        sends++;
        return http.Response('{}', 200);
      }),
    );

    await expectLater(
      client.stageMapSource(
        'trihouse_test_01',
        MapSourceUploadDto(
          sourceType: 'slam_image',
          fileName: 'map.pgm',
          mimeType: 'not a mime',
          bytes: Uint8List.fromList([1]),
        ),
      ),
      throwsA(
        isA<FmsApiException>().having(
          (error) => error.kind,
          'kind',
          FmsApiErrorKind.invalidRequest,
        ),
      ),
    );
    expect(sends, 0);
  });

  test(
    'successful staging decode and DTO schema failures are invalid responses',
    () async {
      for (final responseBody in ['{not-json', '{}']) {
        final client = FmsApiClient(
          baseUri: Uri.parse('https://gateway.example'),
          httpClient: MockClient((_) async => http.Response(responseBody, 200)),
        );

        await expectLater(
          client.stageMapSource(
            'trihouse_test_01',
            MapSourceUploadDto(
              sourceType: 'slam_image',
              fileName: 'map.pgm',
              mimeType: 'image/x-portable-graymap',
              bytes: Uint8List.fromList([1, 2, 3]),
            ),
          ),
          throwsA(
            isA<FmsApiException>().having(
              (error) => error.kind,
              'kind',
              FmsApiErrorKind.invalidResponse,
            ),
          ),
          reason: responseBody,
        );
      }
    },
  );

  test(
    'WebSocket connection and event decode errors use stable kinds',
    () async {
      final connectionFailure = FmsApiClient(
        baseUri: Uri.parse('https://gateway.example'),
        httpClient: MockClient((_) async => http.Response('[]', 200)),
        operationsSocketConnector: (_) => throw StateError('handshake failed'),
      );
      final decodeFailure = FmsApiClient(
        baseUri: Uri.parse('https://gateway.example'),
        httpClient: MockClient((_) async => http.Response('[]', 200)),
        operationsSocketConnector: (_) =>
            _ErrorWebSocketChannel(Stream.value('{not-json')),
      );

      await expectLater(
        connectionFailure.operationsEvents().first,
        throwsA(
          isA<FmsApiException>().having(
            (error) => error.kind,
            'kind',
            FmsApiErrorKind.webSocket,
          ),
        ),
      );
      await expectLater(
        decodeFailure.operationsEvents().first,
        throwsA(
          isA<FmsApiException>().having(
            (error) => error.kind,
            'kind',
            FmsApiErrorKind.invalidResponse,
          ),
        ),
      );
    },
  );
}
