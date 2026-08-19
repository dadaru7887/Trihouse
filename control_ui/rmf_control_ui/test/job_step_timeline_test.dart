import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/trihouse/api/fms_api.dart';
import 'package:rmf_control_ui/trihouse/api/fms_models.dart';
import 'package:rmf_control_ui/trihouse/features/orders/job_detail_page.dart';

/// 2026-08-19 실제 원장에서 그대로 옮긴 job 2 의 7단계.
/// step 10·20 은 끝났고 30 은 게이트에서 멈춰 있다.
JobDetailDto _stalledAtLoadGate() => JobDetailDto.fromJson({
  'job_id': 2,
  'job_code': 'OUT-ba9a469d67e15b5e98b0c7a6',
  'operation_type': 'outbound',
  'priority': 'normal',
  'state': 'assigned',
  'requested_by': 'W-OP-01',
  'external_reference': null,
  'source_location_id': null,
  'destination_location_id': 28,
  'due_at': null,
  'context': {
    'assignment': {
      'mobile_id': 'PK_01',
      'omx_id': 'OMX_01',
      'packing_dock_code': 'PACKING-01-DOCK-01',
      'revision': 1,
    },
  },
  'created_at': '2026-08-19T14:15:14.977823+09:00',
  'items': const <Object?>[],
  'steps': [
    {
      'job_step_id': 2,
      'step_no': 10,
      'executor_type': 'arm',
      'assigned_device_id': 'OMX_01',
      'action_type': 'pick',
      'state': 'succeeded',
      'rmf_task_id': null,
      'input': {'dependencies': <Object?>[]},
      'result': {'outcome': 'succeeded', 'reason_code': 'PICK_CONFIRMED'},
    },
    {
      'job_step_id': 3,
      'step_no': 20,
      'executor_type': 'mobile',
      'assigned_device_id': 'PK_01',
      'action_type': 'navigate',
      'state': 'succeeded',
      'rmf_task_id': 'compose.dispatch-d1d3067c3d',
      'input': {'dependencies': <Object?>[]},
      'result': null,
    },
    {
      'job_step_id': 4,
      'step_no': 30,
      'executor_type': 'fms',
      'assigned_device_id': null,
      'action_type': 'load',
      'state': 'pending',
      'rmf_task_id': null,
      'input': {
        'gate': 'PINKY_READY+OMX_READY',
        'branch': 'readiness_load_gate',
        'dependencies': [10, 20],
      },
      'result': null,
    },
    {
      'job_step_id': 5,
      'step_no': 40,
      'executor_type': 'mobile',
      'assigned_device_id': 'PK_01',
      'action_type': 'navigate',
      'state': 'pending',
      'rmf_task_id': null,
      'input': {'dependencies': [30]},
      'result': null,
    },
  ],
});

class _StepApi implements FmsApi {
  int getJobCalls = 0;

  @override
  Future<JobDetailDto> getJob(int jobId) async {
    getJobCalls += 1;
    return _stalledAtLoadGate();
  }

  @override
  Stream<OperationsEventDto> operationsEvents() =>
      const Stream<OperationsEventDto>.empty();

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<void> _pumpDetail(WidgetTester tester, _StepApi api) async {
  tester.view.physicalSize = const Size(1100, 1400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: JobDetailPage(api: api, jobId: 2, workerId: 'W-OP-01'),
      ),
    ),
  );
  await tester.pump();
  await tester.pump();
}

void main() {
  testWidgets('실행 단계를 원장 값 그대로 7단계로 보여 준다', (tester) async {
    final api = _StepApi();
    await _pumpDetail(tester, api);

    expect(find.text('실행 단계'), findsOneWidget);
    expect(find.text('2/4 완료'), findsOneWidget);

    // executor/action 과 담당 장비를 가공하지 않고 그대로 적는다.
    expect(find.text('arm/pick  ·  OMX_01'), findsOneWidget);
    expect(find.text('mobile/navigate  ·  PK_01'), findsWidgets);
    // fms 단계는 담당 장비가 없다.
    expect(find.text('fms/load'), findsOneWidget);

    // 원장이 적어 둔 판정 사유를 그대로 보여 준다.
    expect(find.text('PICK_CONFIRMED'), findsOneWidget);
    expect(find.text('RMF compose.dispatch-d1d3067c3d'), findsOneWidget);

    for (final stepNo in [10, 20, 30, 40]) {
      expect(find.byKey(Key('job-step-$stepNo')), findsOneWidget);
    }

    await tester.pumpAndSettle(const Duration(milliseconds: 100));
  });

  testWidgets('선행이 끝났는데 못 넘어간 단계만 이유와 함께 짚어 준다', (tester) async {
    final api = _StepApi();
    await _pumpDetail(tester, api);

    // step 30 은 선행 10·20 이 succeeded 인데도 pending 이다. 여기가 막힌 곳이다.
    expect(
      find.byKey(const Key('job-step-30-gate')),
      findsOneWidget,
      reason: '게이트에서 멈춘 단계를 짚지 못하면 화면을 봐도 원인을 알 수 없다',
    );
    expect(
      find.text('게이트 PINKY_READY+OMX_READY 대기 중 · 선행 10, 20 완료'),
      findsOneWidget,
    );

    // step 40 은 선행(30)이 아직이라 막힌 것이 아니다. 같이 강조하면 안 된다.
    expect(find.byKey(const Key('job-step-40-gate')), findsNothing);

    await tester.pumpAndSettle(const Duration(milliseconds: 100));
  });
}
