import os
from pathlib import Path
import subprocess


SCRIPT = Path(__file__).parents[1] / 'scripts' / 'verify_rtsp.sh'


def make_tool(directory: Path, name: str, exit_code: int = 0):
    tool = directory / name
    tool.write_text(
        '#!/usr/bin/env bash\n'
        f'printf "%s\\n" "$*" > "$CAPTURE_DIR/{name}.args"\n'
        f'exit {exit_code}\n',
        encoding='utf-8',
    )
    tool.chmod(0o755)


def run_script(tmp_path: Path, ffmpeg_exit=0):
    bin_dir = tmp_path / 'bin'
    capture_dir = tmp_path / 'capture'
    bin_dir.mkdir()
    capture_dir.mkdir()
    make_tool(bin_dir, 'ffprobe')
    make_tool(bin_dir, 'ffmpeg', ffmpeg_exit)
    environment = os.environ.copy()
    environment['PATH'] = f'{bin_dir}:{environment["PATH"]}'
    environment['CAPTURE_DIR'] = str(capture_dir)
    result = subprocess.run(
        [str(SCRIPT), 'rtsp://192.168.0.9:8554/pinky_1', '600'],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    return result, capture_dir


def test_forwards_uri_and_duration_to_probe_and_decode_without_output_file(tmp_path):
    result, capture_dir = run_script(tmp_path)

    assert result.returncode == 0
    probe_args = (capture_dir / 'ffprobe.args').read_text(encoding='utf-8')
    ffmpeg_args = (capture_dir / 'ffmpeg.args').read_text(encoding='utf-8')
    assert '-rtsp_transport tcp' in probe_args
    assert probe_args.endswith('rtsp://192.168.0.9:8554/pinky_1\n')
    assert '-xerror' in ffmpeg_args
    assert '-t 600 -f null -' in ffmpeg_args


def test_propagates_decoder_failure(tmp_path):
    result, _capture_dir = run_script(tmp_path, ffmpeg_exit=9)

    assert result.returncode == 9


def test_rejects_non_rtsp_uri_before_running_tools(tmp_path):
    result = subprocess.run(
        [str(SCRIPT), 'http://192.168.0.9/pinky_1', '60'],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert 'rtsp://' in result.stderr
