import 'package:flutter_test/flutter_test.dart';
import 'package:openrmf_app/src/models.dart';

void main() {
  test('parses rmf-web fleet state', () {
    final robots = RmfRobot.fromFleetList([
      {
        'name': 'tinyRobot',
        'robots': {
          'tinyRobot1': {
            'name': 'tinyRobot1',
            'status': 'working',
            'battery': 0.73,
            'task_id': 'delivery-1',
            'location': {'map': 'L1', 'x': 1.2, 'y': -3.4, 'yaw': 0.5},
            'issues': [],
          },
        },
      },
    ]);

    expect(robots, hasLength(1));
    expect(robots.single.fleet, 'tinyRobot');
    expect(robots.single.name, 'tinyRobot1');
    expect(robots.single.level, 'L1');
    expect(robots.single.battery, 0.73);
    expect(robots.single.isWorking, isTrue);
    expect(robots.single.lockedMutexGroups, isEmpty);
  });

  test('parses root-wrapped task category', () {
    final task = RmfTask.fromJson({
      'booking': {'id': 'task-1', 'unix_millis_request_time': 1000},
      'category': {'root': 'delivery'},
      'status': 'underway',
      'assigned_to': {'group': 'tinyRobot', 'name': 'tinyRobot2'},
    });

    expect(task.id, 'task-1');
    expect(task.category, 'delivery');
    expect(task.robot, 'tinyRobot2');
  });

  test('recognizes canceled task status variants', () {
    for (final status in ['canceled', 'cancelled', 'killed']) {
      final task = RmfTask.fromJson({
        'booking': {'id': 'task-$status'},
        'category': 'patrol',
        'status': status,
      });
      expect(task.isCanceled, isTrue);
    }
  });

  test('parses Jazzy door mode wrapper', () {
    final door = RmfDoor.fromJson(
      {'name': 'main_door'},
      {
        'door_name': 'main_door',
        'current_mode': {'value': 2},
      },
    );

    expect(door.name, 'main_door');
    expect(door.mode, 2);
    expect(door.stateLabel, '열림');
  });
}
