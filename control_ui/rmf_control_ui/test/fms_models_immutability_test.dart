import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/trihouse/api/fms_models.dart';

void main() {
  test('source upload bytes are copied and exposed read-only', () {
    final original = Uint8List.fromList([1, 2, 3]);
    final upload = MapSourceUploadDto(
      sourceType: 'slam_image',
      fileName: 'map.pgm',
      mimeType: 'image/x-portable-graymap',
      bytes: original,
    );

    original[0] = 9;

    expect(upload.bytes, [1, 2, 3]);
    expect(() => upload.bytes[0] = 7, throwsUnsupportedError);
  });

  test('draft source selections and nested geometry are deeply immutable', () {
    final sourceUuids = {'saved': 'source-1'};
    final stagedTokens = {'slam_image': 'upload-1'};
    final waypoints = <JsonObject>[
      {
        'code': 'PACKING-01-DOCK-01',
        'pose': {
          'xy': [0.351, -0.490],
        },
      },
    ];
    final features = <JsonObject>[
      {
        'code': 'BOTTLENECK-01',
        'geometry': {
          'coordinates': [
            [1.0, 2.0],
          ],
        },
      },
    ];
    final draft = MapProjectDraftDto(
      mapName: 'trihouse_test_01',
      formatVersion: 1,
      draftRevision: 4,
      sourceUuids: sourceUuids,
      stagedSourceTokens: stagedTokens,
      waypoints: waypoints,
      features: features,
      runtimeProfileHash: 'profile-sha',
    );

    sourceUuids['saved'] = 'changed';
    stagedTokens['slam_image'] = 'changed';
    ((waypoints.single['pose'] as Map<String, Object?>)['xy']
            as List<Object?>)[0] =
        99.0;
    (((features.single['geometry'] as Map<String, Object?>)['coordinates']
                    as List<Object?>)
                .single
            as List<Object?>)[0] =
        99.0;

    expect(draft.sourceUuids, {'saved': 'source-1'});
    expect(draft.stagedSourceTokens, {'slam_image': 'upload-1'});
    expect(
      ((draft.waypoints.single['pose'] as Map<String, Object?>)['xy']
          as List<Object?>),
      [0.351, -0.490],
    );
    expect(
      () =>
          ((draft.waypoints.single['pose'] as Map<String, Object?>)['xy']
                  as List<Object?>)[0] =
              7,
      throwsUnsupportedError,
    );
    expect(
      () =>
          (((draft.features.single['geometry']
                              as Map<String, Object?>)['coordinates']
                          as List<Object?>)
                      .single
                  as List<Object?>)[0] =
              7,
      throwsUnsupportedError,
    );
  });

  test('response JSON in manifests jobs and events is deeply immutable', () {
    final manifest = <String, Object?>{
      'artifacts': [
        {
          'name': 'map.yaml',
          'hashes': ['sha-1'],
        },
      ],
    };
    final published = PublishedMapDto(
      mapName: 'trihouse_test_01',
      mapRevision: 'map-sha',
      draftRevision: 4,
      manifest: manifest,
    );
    final job = JobDetailDto.fromJson({
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
      'context': {
        'reservation': {
          'lots': [7, 8],
        },
      },
      'created_at': '2026-08-16T03:00:00+09:00',
      'steps': [
        {
          'job_step_id': 9,
          'metadata': {
            'devices': ['PK_01'],
          },
        },
      ],
    });
    final event = OperationsEventDto.fromJson({
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
      'payload': {
        'pose': [1.2, 0.4],
      },
    });
    final publishedHashes =
        (((published.manifest['artifacts'] as List<Object?>).single
                as Map<String, Object?>)['hashes'])
            as List<Object?>;
    final jobLots =
        ((job.context['reservation'] as Map<String, Object?>)['lots'])
            as List<Object?>;
    final jobDevices =
        ((job.steps.single['metadata'] as Map<String, Object?>)['devices'])
            as List<Object?>;
    final eventPose = event.payload!['pose'] as List<Object?>;

    ((manifest['artifacts'] as List<Object?>).single
            as Map<String, Object?>)['name'] =
        'changed';

    expect(() => publishedHashes[0] = 'changed', throwsUnsupportedError);
    expect(() => jobLots[0] = 99, throwsUnsupportedError);
    expect(() => jobDevices[0] = 'changed', throwsUnsupportedError);
    expect(() => eventPose[0] = 99, throwsUnsupportedError);
    expect(
      ((published.manifest['artifacts'] as List<Object?>).single
          as Map<String, Object?>)['name'],
      'map.yaml',
    );
  });
}
