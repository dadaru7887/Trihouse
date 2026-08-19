import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/trihouse/api/fms_api.dart';
import 'package:rmf_control_ui/trihouse/api/fms_models.dart';
import 'package:rmf_control_ui/trihouse/features/orders/job_detail_page.dart';

class _CompletionApi implements FmsApi {
  final calls = <({int jobId, WorkerCompletionDto request, String key})>[];

  JobDetailDto _job({int completedQty = 0}) => JobDetailDto.fromJson({
    'job_id': 42,
    'job_code': 'OUT-42',
    'operation_type': 'outbound',
    'priority': 'normal',
    'state': 'running',
    'requested_by': 'W-OP-01',
    'external_reference': 'ORDER-42',
    'source_location_id': null,
    'destination_location_id': 9,
    'due_at': null,
    'context': {
      'assignment': {
        'mobile_id': 'PK_01',
        'omx_id': 'OMX_01',
        'packing_dock_code': 'PACKING-01-DOCK-01',
        'charger_code': 'TRIHOUSE-TEST-01-CHG-01',
        'revision': 1,
      },
    },
    'created_at': '2026-08-16T09:00:00+09:00',
    'items': [
      {
        'job_item_id': 12,
        'product_code': 'SKU-MANDARIN',
        'requested_qty': 1,
        'completed_qty': completedQty,
        'lot_id': 3,
        'verification_state': 'manual_review',
        'metadata': {'fulfillment_state': 'MANUAL_FULFILLMENT_REQUIRED'},
      },
      {
        'job_item_id': 13,
        'product_code': 'SKU-MILK',
        'requested_qty': 1,
        'completed_qty': completedQty,
        'lot_id': 4,
        'verification_state': 'matched',
        'metadata': <String, Object?>{},
      },
    ],
    'steps': [
      {
        'job_step_id': 20,
        'step_no': 80,
        'action_type': 'wait',
        'state': 'running',
      },
    ],
  });

  @override
  Future<JobDetailDto> getJob(int jobId) async => _job();

  @override
  Future<JobDetailDto> completeJob(
    int jobId,
    WorkerCompletionDto request, {
    required String idempotencyKey,
  }) async {
    calls.add((jobId: jobId, request: request, key: idempotencyKey));
    return _job(completedQty: 1);
  }

  // 작업 상세가 원장 변화를 실시간으로 따라가려고 구독한다.
  @override
  Stream<OperationsEventDto> operationsEvents() =>
      const Stream<OperationsEventDto>.empty();

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  testWidgets('manual-required items must be acknowledged before completion', (
    tester,
  ) async {
    final api = _CompletionApi();
    await tester.pumpWidget(
      MaterialApp(
        home: JobDetailPage(api: api, jobId: 42, workerId: 'W-OP-01'),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('SKU-MANDARIN'), findsOneWidget);
    expect(find.text('포장대에서 처리 확인 필요'), findsOneWidget);
    expect(find.textContaining('경로'), findsNothing);
    expect(find.textContaining('로봇 선택'), findsNothing);
    expect(
      tester
          .widget<FilledButton>(find.byKey(const Key('worker-complete-button')))
          .onPressed,
      isNull,
    );

    await tester.tap(find.byKey(const Key('manual-item-12')));
    await tester.pump();
    expect(
      tester
          .widget<FilledButton>(find.byKey(const Key('worker-complete-button')))
          .onPressed,
      isNotNull,
    );
  });

  testWidgets('completion posts through FmsApi with a stable idempotency key', (
    tester,
  ) async {
    final api = _CompletionApi();
    await tester.pumpWidget(
      MaterialApp(
        home: JobDetailPage(api: api, jobId: 42, workerId: 'W-OP-01'),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('manual-item-12')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('worker-complete-button')));
    await tester.pumpAndSettle();

    expect(api.calls, hasLength(1));
    expect(api.calls.single.jobId, 42);
    expect(api.calls.single.request.acknowledgedManualItemIds, [12]);
    expect(
      api.calls.single.key,
      startsWith('control-ui-worker-completion-42-'),
    );
    expect(find.text('완료 처리됨'), findsOneWidget);
  });
}
