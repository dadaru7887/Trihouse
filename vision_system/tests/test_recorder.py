"""H.264 recorder 명령과 카탈로그 hand-off 테스트."""

import unittest

from vision_system.recording_server.recorder import (
    FfmpegRecorderRunner,
    RecorderConfig,
    RecorderState,
    RecordingSession,
    build_ffmpeg_segment_command,
)


class RecorderCommandTest(unittest.TestCase):
    def test_rtsp_is_copied_into_one_minute_h264_segments(self) -> None:
        """Recording must not decode/re-encode frames or depend on UI playback."""
        command = build_ffmpeg_segment_command(
            RecorderConfig(camera_id='cam-01', input_uri='rtsp://vision.local:8554/cam-01', output_root='/srv/recordings')
        )
        self.assertIn('-c:v', command)
        self.assertEqual('copy', command[command.index('-c:v') + 1])
        self.assertEqual('60', command[command.index('-segment_time') + 1])
        self.assertEqual('/srv/recordings/cam-01/%Y%m%dT%H%M%S.h264', command[-1])

    def test_invalid_camera_id_or_non_rtsp_input_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecorderConfig(camera_id='../cam', input_uri='rtsp://vision.local/cam', output_root='/srv/recordings')
        with self.assertRaises(ValueError):
            RecorderConfig(camera_id='cam-1', input_uri='https://vision.local/cam', output_root='/srv/recordings')


class RecordingSessionTest(unittest.TestCase):
    def test_finished_segment_is_catalogued_then_safe_for_retention(self) -> None:
        """The process lifecycle records only complete files as removable evidence."""
        session = RecordingSession(capacity_bytes=100, output_root='/srv/recordings')
        session.process_started()
        segment = session.segment_opened(camera_id='cam-01', minute_start_s=120, size_bytes=120)
        self.assertEqual(RecorderState.RECORDING, session.state)
        self.assertEqual('/srv/recordings/cam-01/120.h264', session.catalog.recording_path(segment))
        removed = session.segment_finished(segment.segment_id)
        self.assertEqual(('cam-01:120',), removed)
        self.assertIsNone(session.catalog.get(segment.segment_id))

    def test_process_exit_marks_recorder_unhealthy_without_deleting_active_segment(self) -> None:
        session = RecordingSession(capacity_bytes=1000, output_root='/srv/recordings')
        session.process_started()
        active = session.segment_opened(camera_id='cam-01', minute_start_s=120, size_bytes=10)
        session.process_exited('ffmpeg exited with 1')
        self.assertEqual(RecorderState.DISCONNECTED, session.state)
        self.assertIsNotNone(session.catalog.get(active.segment_id))


class _FakeProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout: float) -> int:
        self.returncode = 0
        return self.returncode


class RecorderRunnerTest(unittest.TestCase):
    def test_runner_executes_validated_argv_without_a_shell_and_reports_exit(self) -> None:
        captured: list[list[str]] = []
        process = _FakeProcess()

        def popen(argv: list[str]) -> _FakeProcess:
            captured.append(argv)
            return process

        runner = FfmpegRecorderRunner(
            RecorderConfig(camera_id='cam-01', input_uri='rtsp://vision.local/cam-01', output_root='/srv/recordings'),
            session=RecordingSession(capacity_bytes=1000, output_root='/srv/recordings'),
            popen=popen,
        )
        runner.start()
        self.assertEqual('ffmpeg', captured[0][0])
        process.returncode = 1
        runner.poll()
        self.assertEqual(RecorderState.DISCONNECTED, runner.session.state)
        self.assertEqual('ffmpeg exited with 1', runner.session.last_error)


if __name__ == '__main__':
    unittest.main()
