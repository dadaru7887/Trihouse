"""Time-axis checks on 1-second labelled frames, through the runtime FallMonitor.

    pytest vision_ai/tests/worker/test_fall_sequence.py
"""

from vision_ai.models.perception.trainer.fall_sequence import (
    _escalations, confirm_summary, monitor_config, tracks,
)
from vision_ai.robot.perception.fall_monitor import MonitorConfig

CONFIG = MonitorConfig(fall_confirm_seconds=1.0, immobile_seconds=5.0)


def _row(t: int, fallen: bool, called: bool, box=(0.1, 0.1, 0.3, 0.6), episode="20260822_100000"):
    return {"image": f"test/images/dataset_video_{episode}_t{t:04d}-00s_jpg.rf.x{t}.jpg",
            "episode": episode, "split": "test", "fallen": fallen, "box": list(box),
            "called": called}


def _called(row):
    return row["called"]


def test_the_robot_timings_are_read_from_realtime_yaml():
    config = monitor_config()
    assert (config.fall_confirm_seconds, config.immobile_seconds) == (1.0, 5.0)


def test_a_gap_longer_than_a_second_ends_the_track():
    rows = [_row(0, False, False), _row(1, False, False), _row(4, False, False)]
    assert [len(t) for t in tracks(rows)] == [2, 1]


def test_two_people_are_kept_apart_by_box_overlap():
    left, right = (0.0, 0.0, 0.2, 0.5), (0.7, 0.0, 0.9, 0.5)
    rows = [_row(0, False, False, left), _row(0, True, True, right),
            _row(1, True, True, right), _row(1, False, False, left)]
    linked = tracks(rows)
    assert sorted([r["fallen"] for r in t] for t in linked) == [[False, False], [True, True]]


def test_a_one_frame_false_alarm_is_removed_by_the_one_second_confirm():
    rows = [_row(0, False, False), _row(1, False, True), _row(2, False, False),
            _row(3, False, True), _row(4, False, True)]
    out = confirm_summary(tracks(rows), _called, CONFIG)
    assert (out["frame_fp"], out["confirmed_fp"], out["false_confirmations"]) == (3, 1, 1)


def test_a_long_still_fall_escalates_and_a_short_one_is_not_counted():
    rows = ([_row(t, False, False) for t in range(0, 2)]
            + [_row(t, True, True) for t in range(2, 10)]      # 8 frames: t0 + 7 s
            + [_row(t, False, False) for t in range(10, 12)]
            + [_row(t, True, True) for t in range(12, 15)])    # 3 frames: too short
    out = _escalations(tracks(rows), _called, CONFIG)
    assert (out["eligible_events"], out["reached"], out["short_fall_runs"]) == (1, 1, 1)
    assert out["latency_seconds"] == [7.0] and out["false_alarms"] == 0


def test_a_long_standing_misfire_is_a_false_alarm():
    rows = [_row(t, False, True) for t in range(10)]
    out = _escalations(tracks(rows), _called, CONFIG)
    assert (out["false_alarms"], out["standing_seconds"]) == (1, 10)
