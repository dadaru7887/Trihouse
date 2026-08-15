import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/map_ai_service.dart';

void main() {
  test('Codex map proposal JSON을 구조화된 결과로 읽는다', () {
    final proposal = MapAiProposal.fromJson({
      'provider': 'Codex',
      'summary': '벽 우회 경로',
      'waypoints': [
        {'id': 'ai_1', 'x': 10, 'y': 20, 'name': '홈1', 'category': '홈'},
      ],
      'lanes': [
        {'startId': 'existing_0', 'endId': 'ai_1', 'direction': '정방향'},
      ],
      'warnings': ['현장 검증 필요'],
    });

    expect(proposal.provider, 'Codex');
    expect(proposal.waypoints.single['id'], 'ai_1');
    expect(proposal.lanes.single['direction'], '정방향');
    expect(proposal.warnings, ['현장 검증 필요']);
  });
}
