import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rmf_control_ui/trihouse/api/fms_api_client.dart';
import 'package:rmf_control_ui/trihouse/api/fms_models.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

class _FakeWebSocketChannel implements WebSocketChannel {
  _FakeWebSocketChannel(this.stream);

  @override
  final Stream<Object?> stream;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Map<String, Object?> _draftJson() => {
  'map_name': 'trihouse_test_01',
  'format_version': 1,
  'draft_revision': 4,
  'source_uuids': {'slam_yaml': 'source-1'},
  'waypoints': [
    {'code': 'PACKING-01-DOCK-01', 'x': 0.351, 'y': -0.490},
  ],
  'features': [
    {'feature_type': 'safety_zone', 'code': 'SAFETY-01'},
  ],
  'runtime_profile_hash': 'profile-sha',
};

Map<String, Object?> _jobJson() => {
  'job_id': 42,
  'job_code': 'OUT-42',
  'operation_type': 'outbound',
  'priority': 'high',
  'state': 'waiting_worker',
  'requested_by': 'W-OP-01',
  'external_reference': 'ORDER-42',
  'source_location_id': null,
  'destination_location_id': 12,
  'due_at': null,
  'context': {'allow_partial_fulfillment': false},
  'created_at': '2026-08-16T03:00:00+09:00',
  'steps': [
    {'job_step_id': 9, 'step_no': 10, 'state': 'succeeded'},
  ],
};

void main() {
  test(
    'listInventory reads inventory lots from the public Gateway route',
    () async {
      late Uri requestedUri;
      final client = FmsApiClient(
        baseUri: Uri.parse('https://gateway.example'),
        httpClient: MockClient((request) async {
          requestedUri = request.url;
          return http.Response(
            jsonEncode([
              {
                'lot_id': 7,
                'lot_code': 'LOT-0007',
                'product_code': 'MILK-1L',
                'item_name': 'Milk',
                'temperature_zone': 'chilled',
                'location_code': 'CHILL-A-01',
                'expiry_date': '2026-08-20',
                'available_qty': 12,
                'reserved_qty': 3,
                'state': 'available',
              },
            ]),
            200,
            headers: {'content-type': 'application/json'},
          );
        }),
      );

      final lots = await client.listInventory();

      expect(requestedUri.path, '/api/v1/inventory/lots');
      expect(requestedUri.path, isNot(contains('/internal/')));
      expect(lots, hasLength(1));
      expect(lots.single.lotId, 7);
      expect(lots.single.availableQty, 12);
    },
  );

  test('all HTTP operations stay on public Gateway contracts', () async {
    final requests = <http.Request>[];
    final client = FmsApiClient(
      baseUri: Uri.parse('https://gateway.example'),
      httpClient: MockClient((request) async {
        requests.add(request);
        final response = switch ((request.method, request.url.path)) {
          ('GET', '/api/v1/map-projects') => [
            {
              'map_name': 'trihouse_test_01',
              'drawing_name': null,
              'format_version': 1,
              'waypoint_count': 8,
              'lane_count': 0,
              'draft_revision': 4,
              'has_building_yaml': false,
              'updated_at': '2026-08-16T03:00:00+09:00',
            },
          ],
          ('POST', '/api/v1/map-projects') => {
            'draft': _draftJson(),
            'open_existing': true,
            'active_revision': 'map-sha',
          },
          ('POST', '/api/v1/map-projects/trihouse_test_01/sources/stage') => {
            'upload_token': 'upload-1',
            'source_type': 'slam_yaml',
            'sha256': 'a' * 64,
            'byte_size': 3,
          },
          ('PUT', '/api/v1/map-projects/trihouse_test_01') => _draftJson(),
          ('DELETE', '/api/v1/map-projects/trihouse_test_01/draft') => null,
          ('POST', '/api/v1/map-projects/trihouse_test_01/validate') => {
            'valid': true,
            'error_codes': <String>[],
          },
          ('POST', '/api/v1/map-projects/trihouse_test_01/publish') => {
            'map_name': 'trihouse_test_01',
            'map_revision': 'map-sha',
            'draft_revision': 4,
            'manifest': {'profile_hash': 'profile-sha'},
          },
          ('POST', '/api/v1/orders') => {
            'job_id': 42,
            'job_code': 'OUT-42',
            'external_reference': 'ORDER-42',
            'state': 'queued',
            'requested_quantity': 2,
            'fulfillable_quantity': 2,
            'outstanding_quantity': 0,
          },
          ('GET', '/api/v1/jobs/42') => _jobJson(),
          ('POST', '/api/v1/jobs/42/worker-completion') => _jobJson(),
          ('POST', '/api/v1/incidents/6/decision') => null,
          _ => throw StateError('${request.method} ${request.url.path}'),
        };
        return http.Response(
          response == null ? '' : jsonEncode(response),
          response == null ? 204 : 200,
          headers: {'content-type': 'application/json'},
        );
      }),
    );
    final draft = MapProjectDraftDto.fromJson(_draftJson());

    expect(await client.listMapProjects(), hasLength(1));
    expect(
      (await client.openMapProject('trihouse_test_01')).openExisting,
      isTrue,
    );
    final staged = await client.stageMapSource(
      'trihouse_test_01',
      MapSourceUploadDto(
        sourceType: 'slam_yaml',
        fileName: 'map.yaml',
        mimeType: 'application/yaml',
        bytes: Uint8List.fromList([1, 2, 3]),
      ),
    );
    expect(staged.uploadToken, 'upload-1');
    expect(
      (await client.saveMapDraft(draft, expectedRevision: 3)).draftRevision,
      4,
    );
    await client.deleteMapDraft('trihouse_test_01');
    expect((await client.validateMapDraft('trihouse_test_01')).valid, isTrue);
    final published = await client.publishMapDraft(
      'trihouse_test_01',
      const PublishMapDto(expectedDraftRevision: 4, publishedBy: 'W-OP-01'),
    );
    expect(published.mapRevision, 'map-sha');
    final order = await client.createOutboundOrder(
      OutboundOrderRequestDto(
        externalReference: 'ORDER-42',
        requester: 'W-OP-01',
        priority: 'high',
        allowPartialFulfillment: false,
        lines: const [
          OutboundOrderLineDto(productCode: 'MILK-1L', quantity: 2),
        ],
      ),
      idempotencyKey: 'order-42',
    );
    expect(order.jobId, 42);
    expect((await client.getJob(42)).jobCode, 'OUT-42');
    final completed = await client.completeJob(
      42,
      WorkerCompletionDto(
        workerId: 'W-OP-01',
        completionNote: 'packed',
        acknowledgedManualItemIds: const [3],
      ),
      idempotencyKey: 'complete-42',
    );
    expect(completed.jobId, 42);
    await client.decideEmergency(
      6,
      const EmergencyDecisionDto(
        workerId: 'W-OP-01',
        decision: EmergencyDecision.continueWork,
        reason: 'area clear',
      ),
      idempotencyKey: 'incident-6',
    );

    expect(requests, hasLength(11));
    expect(
      requests.every((request) => request.url.path.startsWith('/api/v1/')),
      isTrue,
    );
    expect(
      requests.every((request) => !request.url.path.contains('/internal/')),
      isTrue,
    );
    expect(requests[3].headers['If-Match'], '3');
    expect(requests[7].headers['Idempotency-Key'], 'order-42');
    expect(requests[9].headers['Idempotency-Key'], 'complete-42');
    expect(requests[10].headers['Idempotency-Key'], 'incident-6');
  });

  test(
    'operationsEvents connects to the public secure WebSocket route',
    () async {
      late Uri connectedUri;
      final client = FmsApiClient(
        baseUri: Uri.parse('https://gateway.example'),
        httpClient: MockClient((_) async => http.Response('[]', 200)),
        operationsSocketConnector: (uri) {
          connectedUri = uri;
          return _FakeWebSocketChannel(
            Stream.value(
              jsonEncode({
                'event_id': 8,
                'event_uuid': 'event-8',
                'occurred_at': '2026-08-16T03:00:00+09:00',
                'actor_worker_id': null,
                'device_id': 'PK_01',
                'job_id': 42,
                'job_step_id': 9,
                'incident_id': null,
                'severity': 'info',
                'category': 'robot',
                'event_type': 'robot.pose',
                'message': null,
                'payload': {'x': 1.2, 'y': 0.4},
              }),
            ),
          );
        },
      );

      final event = await client.operationsEvents().first;

      expect(
        connectedUri.toString(),
        'wss://gateway.example/api/v1/operations/ws',
      );
      expect(connectedUri.path, isNot(contains('/internal/')));
      expect(event.eventId, 8);
      expect(event.payload, {'x': 1.2, 'y': 0.4});
    },
  );
}
