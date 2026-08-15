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
  'staged_source_tokens': {'slam_image': 'upload-1'},
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
  test('runtime profile is read only through the public Gateway route', () async {
    late http.Request captured;
    final client = FmsApiClient(
      baseUri: Uri.parse('https://gateway.example'),
      httpClient: MockClient((request) async {
        captured = request;
        return http.Response(
          jsonEncode({
            'profile_name': 'pinky_pro simulation profile',
            'profile_hash': 'a' * 64,
            'source_files': [
              'pinky_pro/pinky_navigation/params/nav2_params.yaml',
              'pinky_pro/pinky_bringup/config/pinky_params.yaml',
            ],
            'controller': {'plugin': 'RegulatedPurePursuitController'},
            'planner': {'plugin': 'NavfnPlanner'},
            'local_costmap': {'resolution': 0.05},
            'global_costmap': {'resolution': 0.05},
            'robot': {'robot_radius_m': null},
            'max_speeds': {'linear_mps': 0.25},
            'goal_tolerances': {'xy_m': 0.25},
            'progress_tolerances': {'required_movement_radius_m': 0.5},
            'wheel_parameters': {'wheel_radius_m': 0.027},
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      }),
    );

    final profile = await client.getRuntimeProfile();

    expect(captured.method, 'GET');
    expect(
      captured.url.path,
      '/api/v1/runtime-profiles/pinky-pro-simulation',
    );
    expect(captured.url.path, isNot(contains('/internal/')));
    expect(profile.profileName, 'pinky_pro simulation profile');
    expect(profile.robot['robot_radius_m'], isNull);
  });

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

  test('stage token is carried into the exact draft save body', () async {
    late http.Request saveRequest;
    final client = FmsApiClient(
      baseUri: Uri.parse('https://gateway.example'),
      httpClient: MockClient((request) async {
        if (request.url.path.endsWith('/sources/stage')) {
          return http.Response(
            jsonEncode({
              'upload_token': 'upload-1',
              'source_type': 'slam_image',
              'sha256': 'a' * 64,
              'byte_size': 3,
            }),
            200,
          );
        }
        saveRequest = request;
        return http.Response(jsonEncode(_draftJson()), 200);
      }),
    );

    final staged = await client.stageMapSource(
      'trihouse_test_01',
      MapSourceUploadDto(
        sourceType: 'slam_image',
        fileName: 'map.pgm',
        mimeType: 'image/x-portable-graymap',
        bytes: Uint8List.fromList([1, 2, 3]),
      ),
    );
    final draft = MapProjectDraftDto(
      mapName: 'trihouse_test_01',
      formatVersion: 1,
      draftRevision: 4,
      sourceUuids: const {'slam_yaml': 'source-1'},
      stagedSourceTokens: {'slam_image': staged.uploadToken},
      waypoints: const [],
      features: const [],
      runtimeProfileHash: 'profile-sha',
    );

    await client.saveMapDraft(draft, expectedRevision: 4);

    expect(jsonDecode(saveRequest.body), {
      'map_name': 'trihouse_test_01',
      'format_version': 1,
      'draft_revision': 4,
      'source_uuids': {'slam_yaml': 'source-1'},
      'staged_source_tokens': {'slam_image': 'upload-1'},
      'waypoints': <Object?>[],
      'features': <Object?>[],
      'runtime_profile_hash': 'profile-sha',
    });
  });

  test(
    'multipart staging preserves fields filename MIME bytes and URI escaping',
    () async {
      late http.BaseRequest stagedRequest;
      late List<int> stagedBody;
      final client = FmsApiClient(
        baseUri: Uri.parse('https://gateway.example'),
        httpClient: MockClient.streaming((request, bodyStream) async {
          stagedRequest = request;
          stagedBody = await bodyStream.toBytes();
          return http.StreamedResponse(
            Stream.value(
              utf8.encode(
                jsonEncode({
                  'upload_token': 'upload-1',
                  'source_type': 'slam_image',
                  'sha256': 'a' * 64,
                  'byte_size': 3,
                }),
              ),
            ),
            200,
          );
        }),
      );

      await client.stageMapSource(
        'floor/a b',
        MapSourceUploadDto(
          sourceType: 'slam_image',
          fileName: 'map.pgm',
          mimeType: 'image/x-portable-graymap',
          bytes: Uint8List.fromList([0, 255, 10]),
        ),
      );

      final printable = latin1.decode(stagedBody, allowInvalid: true);
      expect(
        stagedRequest.url.toString(),
        'https://gateway.example/api/v1/map-projects/floor%2Fa%20b/sources/stage',
      );
      expect(
        stagedRequest.headers['content-type'],
        startsWith('multipart/form-data; boundary='),
      );
      expect(printable, contains('name="source_type"\r\n\r\nslam_image'));
      expect(printable, contains('name="source"; filename="map.pgm"'));
      expect(
        printable.toLowerCase(),
        contains('content-type: image/x-portable-graymap'),
      );
      expect(_containsBytes(stagedBody, const [0, 255, 10]), isTrue);
    },
  );

  test('dot-segment map names fail before every map route transport', () async {
    var sends = 0;
    final client = FmsApiClient(
      baseUri: Uri.parse('https://gateway.example'),
      httpClient: MockClient((request) async {
        sends++;
        return http.Response('{}', 200);
      }),
    );
    final operations = <Future<void> Function(String)>[
      (mapName) async {
        await client.openMapProject(mapName);
      },
      (mapName) async {
        await client.stageMapSource(
          mapName,
          MapSourceUploadDto(
            sourceType: 'slam_image',
            fileName: 'map.pgm',
            mimeType: 'image/x-portable-graymap',
            bytes: Uint8List.fromList([1, 2, 3]),
          ),
        );
      },
      (mapName) async {
        await client.saveMapDraft(
          MapProjectDraftDto(
            mapName: mapName,
            formatVersion: 1,
            draftRevision: 4,
            sourceUuids: const {},
            stagedSourceTokens: const {},
            waypoints: const [],
            features: const [],
            runtimeProfileHash: 'profile-sha',
          ),
          expectedRevision: 4,
        );
      },
      (mapName) async => client.deleteMapDraft(mapName),
      (mapName) async {
        await client.validateMapDraft(mapName);
      },
      (mapName) async {
        await client.publishMapDraft(
          mapName,
          const PublishMapDto(expectedDraftRevision: 4, publishedBy: 'W-OP-01'),
        );
      },
    ];

    for (final mapName in ['.', '..']) {
      for (final operation in operations) {
        await expectLater(
          operation(mapName),
          throwsA(
            isA<FmsApiException>().having(
              (error) => error.kind,
              'kind',
              FmsApiErrorKind.invalidRequest,
            ),
          ),
          reason: mapName,
        );
      }
    }

    expect(sends, 0);
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

  test(
    'state-changing JSON bodies match the public Gateway wire contract',
    () async {
      final bodies = <String, Object?>{};
      final client = FmsApiClient(
        baseUri: Uri.parse('https://gateway.example'),
        httpClient: MockClient((request) async {
          bodies[request.url.path] = request.body.isEmpty
              ? null
              : jsonDecode(request.body);
          final body = switch (request.url.path) {
            '/api/v1/map-projects' => {
              'draft': _draftJson(),
              'open_existing': false,
              'active_revision': null,
            },
            '/api/v1/map-projects/trihouse_test_01/publish' => {
              'map_name': 'trihouse_test_01',
              'map_revision': 'map-sha',
              'draft_revision': 4,
              'manifest': <String, Object?>{},
            },
            '/api/v1/orders' => {
              'job_id': 42,
              'job_code': 'OUT-42',
              'external_reference': 'ORDER-42',
              'state': 'queued',
              'requested_quantity': 2,
              'fulfillable_quantity': 2,
              'outstanding_quantity': 0,
            },
            '/api/v1/jobs/42/worker-completion' => _jobJson(),
            '/api/v1/incidents/6/decision' => null,
            _ => throw StateError(request.url.path),
          };
          return http.Response(
            body == null ? '' : jsonEncode(body),
            body == null ? 204 : 200,
          );
        }),
      );

      await client.openMapProject('trihouse_test_01');
      await client.publishMapDraft(
        'trihouse_test_01',
        const PublishMapDto(expectedDraftRevision: 4, publishedBy: 'W-OP-01'),
      );
      await client.createOutboundOrder(
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
      await client.completeJob(
        42,
        WorkerCompletionDto(
          workerId: 'W-OP-01',
          completionNote: 'packed',
          acknowledgedManualItemIds: const [3, 4],
        ),
        idempotencyKey: 'complete-42',
      );
      await client.decideEmergency(
        6,
        const EmergencyDecisionDto(
          workerId: 'W-OP-01',
          decision: EmergencyDecision.raiseAlarm,
          reason: 'unsafe aisle',
        ),
        idempotencyKey: 'incident-6',
      );

      expect(bodies['/api/v1/map-projects'], {'map_name': 'trihouse_test_01'});
      expect(bodies['/api/v1/map-projects/trihouse_test_01/publish'], {
        'expected_draft_revision': 4,
        'published_by': 'W-OP-01',
      });
      expect(bodies['/api/v1/orders'], {
        'external_reference': 'ORDER-42',
        'requested_by': 'W-OP-01',
        'priority': 'high',
        'allow_partial_fulfillment': false,
        'items': [
          {'product_code': 'MILK-1L', 'quantity': 2},
        ],
      });
      expect(bodies['/api/v1/jobs/42/worker-completion'], {
        'worker_id': 'W-OP-01',
        'completion_note': 'packed',
        'acknowledged_manual_item_ids': [3, 4],
      });
      expect(bodies['/api/v1/incidents/6/decision'], {
        'worker_id': 'W-OP-01',
        'decision': 'RAISE_ALARM',
        'reason': 'unsafe aisle',
      });
    },
  );
}

bool _containsBytes(List<int> haystack, List<int> needle) {
  for (var start = 0; start <= haystack.length - needle.length; start++) {
    var matches = true;
    for (var index = 0; index < needle.length; index++) {
      if (haystack[start + index] != needle[index]) {
        matches = false;
        break;
      }
    }
    if (matches) return true;
  }
  return false;
}
