/// 앱의 연속 작업을 Open-RMF 가 아는 작업 요청으로 바꾼다.
///
/// 지금까지 연속 작업은 앱 안에서만 돌았다. 단계마다 `durationSeconds` 를 세어
/// 3초가 지나면 다음으로 넘어갔다. Mock 로봇은 앱이 좌표까지 직접 옮기므로
/// 화면에서는 움직이지만, Gazebo 나 실물 로봇에게는 **가라고 말하는 쪽이
/// 없었다.** 앱은 ROS 를 읽기만 했다.
///
/// 여기서 만든 JSON 을 `task_api_requests` 에 실으면 RMF 가 주인이 된다.
/// 경로는 RMF 가 Lane 그래프에서 고르고, 단계 진행도 RMF 가 알린다. 앱은
/// 무엇을 할지만 정하고 언제 끝났는지는 묻는다.
///
/// 화면과 저장 형식은 그대로 둔다. 여기는 내보낼 때만 지나가는 자리다.
library;

import 'dart:convert';

/// 매니퓰레이터 적재 단계를 RMF 에 알리는 이름.
///
/// 플릿 설정의 `actions:` 목록에도 같은 이름이 있어야 한다. 다르면 RMF 가
/// `Fleet not configured to perform this action` 이라며 작업을 통째로
/// 거절한다 — 단계 하나가 아니라 작업 전체가 안 들어간다.
const String rmfArmLoadAction = 'armLoad';

/// 작업 하나를 이루는 낱개 동작.
///
/// RMF 의 `compose` 작업은 activity 를 순서대로 늘어놓은 것이다. 앱의 단계와
/// 하나씩 맞는다.
class RmfTaskActivity {
  const RmfTaskActivity._(this.category, this.description);

  /// Waypoint 로 간다. RMF 가 Lane 을 따라 경로를 만든다.
  ///
  /// [place] 는 nav graph 의 Waypoint 이름이다. 좌표가 아니다 — 좌표를 주면
  /// RMF 가 그 자리를 그래프에서 못 찾는다.
  const RmfTaskActivity.goToPlace(String place) : this._('go_to_place', place);

  /// 플릿이 따로 맡은 동작. 어댑터의 `execute_action` 이 받는다.
  ///
  /// RMF 는 이 동작이 무엇인지 모른다. 얼마나 걸릴지만 알려 주면 배차 계산에
  /// 쓴다. 끝났다고 알려 주는 것은 어댑터 몫이다.
  ///
  /// 걸리는 시간을 **두 군데**에 적는다. 바깥
  /// `unix_millis_action_duration_estimate` 는 RMF 가 배차를 계산할 때 보고,
  /// 안쪽 `seconds` 는 어댑터가 본다. RMF 는 `execute_action` 에 안쪽
  /// `description` 만 넘겨 주므로 바깥 값은 어댑터까지 닿지 않는다 — 실제로
  /// 5초짜리 동작이 1초 만에 끝난 일이 있었다.
  RmfTaskActivity.performAction(
    String category, {
    Map<String, Object?> description = const {},
    double durationSeconds = 60,
  }) : this._('perform_action', {
         'unix_millis_action_duration_estimate': (durationSeconds * 1000)
             .round(),
         'category': category,
         'description': {...description, 'seconds': durationSeconds},
       });

  /// 그 자리에서 기다린다.
  RmfTaskActivity.waitFor(double seconds)
    : this._('wait_for', {'duration': seconds});

  final String category;
  final Object? description;

  Map<String, Object?> toJson() => {
    'category': category,
    'description': description,
  };
}

/// 만들어진 요청 하나. 보내기 전에 무엇을 보내는지 볼 수 있어야 한다.
class RmfTaskRequest {
  const RmfTaskRequest({
    required this.json,
    required this.robotId,
    required this.fleetName,
    required this.activityCount,
  });

  /// `task_api_requests` 의 `json_msg` 에 그대로 들어갈 문자열.
  final String json;

  /// 이 요청을 맡길 로봇. 비어 있으면 RMF 가 플릿에서 고른다.
  final String? robotId;
  final String fleetName;
  final int activityCount;

  Map<String, Object?> get decoded => jsonDecode(json) as Map<String, Object?>;
}

/// 앱 작업 하나를 RMF 요청으로 바꾼다.
///
/// [robotId] 를 주면 `robot_task_request` 가 되어 그 로봇에게 바로 간다. 앱의
/// 연속 작업은 로봇을 이미 정해 두므로 보통 이쪽이다. 비우면
/// `dispatch_task_request` 가 되어 RMF 가 플릿에서 입찰로 고른다.
///
/// [category] 는 화면에 보일 이름이다. RMF 는 이것으로 작업을 분류만 한다.
RmfTaskRequest buildRmfTaskRequest({
  required String fleetName,
  required List<RmfTaskActivity> activities,
  String? robotId,
  String category = 'compose',
  String requester = 'rmf_control_ui',
  int earliestStartMillis = 0,
}) {
  if (activities.isEmpty) {
    throw ArgumentError('보낼 동작이 없습니다. 단계가 하나는 있어야 합니다.');
  }
  final request = <String, Object?>{
    'category': 'compose',
    'description': {
      'category': category,
      'phases': [
        {
          'activity': {
            'category': 'sequence',
            'description': {
              'activities': [
                for (final activity in activities) activity.toJson(),
              ],
            },
          },
        },
      ],
    },
    'unix_millis_earliest_start_time': earliestStartMillis,
    'requester': requester,
  };
  final id = robotId?.trim();
  final payload = id == null || id.isEmpty
      ? <String, Object?>{
          'type': 'dispatch_task_request',
          'request': {...request, 'fleet_name': fleetName},
        }
      : <String, Object?>{
          'type': 'robot_task_request',
          'robot': id,
          'fleet': fleetName,
          'request': request,
        };
  return RmfTaskRequest(
    json: jsonEncode(payload),
    robotId: id == null || id.isEmpty ? null : id,
    fleetName: fleetName,
    activityCount: activities.length,
  );
}

/// 앱 단계 하나를 옮길 때 쓰는 중간 표현.
///
/// `main.dart` 의 `_MockTaskStep` 을 그대로 넘기면 이 파일이 화면 코드에
/// 얽힌다. 필요한 것만 추린다.
class RmfTaskStepInput {
  const RmfTaskStepInput({
    required this.kind,
    this.placeName,
    this.durationSeconds = 0,
    this.policyId = 'policy_1',
  });

  /// `navigate` · `returnHome` · `armLoad` · `wait` 중 하나.
  final String kind;

  /// 이동 단계의 목적지 Waypoint 이름.
  final String? placeName;
  final double durationSeconds;

  /// 워크셀이 실행할 물품별 가상 정책. DispenserRequest item type으로 전달된다.
  final String policyId;
}

/// 옮기면서 버린 것. 조용히 버리면 화면과 실제가 어긋난다.
class RmfTaskConversion {
  const RmfTaskConversion({required this.activities, required this.skipped});

  final List<RmfTaskActivity> activities;

  /// RMF 로 못 넘긴 단계와 그 이유.
  final List<String> skipped;

  bool get isEmpty => activities.isEmpty;
}

/// 앱 단계 목록을 RMF activity 목록으로 옮긴다.
///
/// 이동 단계에 목적지 이름이 없으면 버린다 — 좌표만 있는 단계는 RMF 가 갈
/// 곳을 정할 수 없다. 버린 것은 [RmfTaskConversion.skipped] 에 남긴다.
RmfTaskConversion convertTaskSteps(
  List<RmfTaskStepInput> steps, {
  String? homePlaceName,
  String armLoadCategory = rmfArmLoadAction,
}) {
  final activities = <RmfTaskActivity>[];
  final skipped = <String>[];
  String? lastPlace;
  for (var index = 0; index < steps.length; index++) {
    final step = steps[index];
    final number = index + 1;
    switch (step.kind) {
      case 'navigate':
        final place = step.placeName?.trim();
        if (place == null || place.isEmpty) {
          skipped.add('$number번째 이동 — 목적지 Waypoint 이름이 없습니다');
          continue;
        }
        activities.add(RmfTaskActivity.goToPlace(place));
        lastPlace = place;
      case 'returnHome':
        final place = (step.placeName?.trim().isNotEmpty ?? false)
            ? step.placeName!.trim()
            : homePlaceName?.trim();
        if (place == null || place.isEmpty) {
          skipped.add('$number번째 홈 복귀 — 돌아갈 자리가 정해지지 않았습니다');
          continue;
        }
        activities.add(RmfTaskActivity.goToPlace(place));
        lastPlace = place;
      case 'armLoad':
        if (lastPlace == null) {
          skipped.add('$number번째 로봇팔 적재 — 먼저 픽업 위치로 이동해야 합니다');
          continue;
        }
        activities.add(
          RmfTaskActivity.performAction(
            armLoadCategory,
            description: {
              'target_guid': lastPlace,
              'item_type': step.policyId,
              'quantity': 1,
            },
            durationSeconds: step.durationSeconds > 0
                ? step.durationSeconds
                : 60,
          ),
        );
      case 'wait':
        activities.add(RmfTaskActivity.waitFor(step.durationSeconds));
      default:
        skipped.add('$number번째 ${step.kind} — RMF 가 모르는 단계입니다');
    }
  }
  return RmfTaskConversion(activities: activities, skipped: skipped);
}

/// 돌고 있는 RMF 작업을 취소하는 요청.
///
/// RMF 의 task API 는 `dispatch_task_request` 를 넣던 그 토픽으로 취소도 받는다.
/// 그래서 작업 다리(`<맵>_task_bridge.py`)를 그대로 쓴다 — 보내는 JSON 만 다르다.
///
/// [taskId] 는 RMF 가 돌려준 것이어야 한다. 앱이 붙인 작업 번호(`T-0007`)가
/// 아니다. 둘을 헷갈리면 RMF 는 모르는 작업이라고 답한다.
String buildCancelTaskRequest(String taskId) =>
    jsonEncode({'type': 'cancel_task', 'task_id': taskId});
