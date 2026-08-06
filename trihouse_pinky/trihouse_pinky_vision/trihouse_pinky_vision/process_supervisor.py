"""Lifecycle supervision for the camera and RTSP publisher processes."""

from collections import deque
from dataclasses import dataclass
import os
import signal
import subprocess
import threading
import time
from typing import Sequence

from .process_metrics import FfmpegProgressParser, ProgressSample


@dataclass(frozen=True)
class SupervisorSnapshot:
    processes_alive: bool
    progress: ProgressSample | None
    total_encoded_bytes: int | None
    exit_reason: str
    restart_delay: float | None


class RestartBackoff:
    def __init__(self, delays: Sequence[float], reset_after: float = 30.0) -> None:
        if not delays or any(delay <= 0 for delay in delays):
            raise ValueError('restart delays must be positive')
        self._delays = tuple(delays)
        self._reset_after = reset_after
        self._index = 0
        self._healthy_since: float | None = None

    def record_failure(self, _now: float) -> float:
        self._healthy_since = None
        delay = self._delays[min(self._index, len(self._delays) - 1)]
        self._index = min(self._index + 1, len(self._delays) - 1)
        return delay

    def record_healthy(self, now: float) -> None:
        if self._healthy_since is None:
            self._healthy_since = now
        elif now - self._healthy_since >= self._reset_after:
            self._index = 0


class ProcessSupervisor:
    def __init__(
        self,
        camera_command: Sequence[str],
        publisher_command: Sequence[str],
        restart_delays: Sequence[float] = (1, 2, 4, 8, 16, 30),
        sigint_timeout: float = 3.0,
        sigterm_timeout: float = 2.0,
    ) -> None:
        self._camera_command = list(camera_command)
        self._publisher_command = list(publisher_command)
        self._sigint_timeout = sigint_timeout
        self._sigterm_timeout = sigterm_timeout
        self._camera: subprocess.Popen[bytes] | None = None
        self._publisher: subprocess.Popen[bytes] | None = None
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._progress: ProgressSample | None = None
        self._diagnostics: deque[str] = deque(maxlen=50)
        self._backoff = RestartBackoff(restart_delays)
        self._next_restart_at: float | None = None

    @property
    def child_pids(self) -> tuple[int, ...]:
        return tuple(
            process.pid for process in (self._camera, self._publisher)
            if process is not None
        )

    @property
    def diagnostics(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._diagnostics)

    def start(self) -> None:
        if self._camera is not None or self._publisher is not None:
            raise RuntimeError('streaming processes are already started')
        self._progress = None
        self._camera = subprocess.Popen(
            self._camera_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        assert self._camera.stdout is not None
        try:
            self._publisher = subprocess.Popen(
                self._publisher_command,
                stdin=self._camera.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except BaseException:
            self._camera.terminate()
            self._camera.wait()
            self._camera = None
            raise
        self._camera.stdout.close()
        self._threads = [
            self._reader_thread(self._camera.stderr, False, 'camera-stderr'),
            self._reader_thread(self._publisher.stderr, True, 'publisher-stderr'),
        ]
        for thread in self._threads:
            thread.start()

    def poll(self, now: float) -> SupervisorSnapshot:
        camera_code = self._camera.poll() if self._camera is not None else None
        publisher_code = self._publisher.poll() if self._publisher is not None else None
        alive = (
            self._camera is not None and camera_code is None
            and self._publisher is not None and publisher_code is None
        )
        exit_reason = ''
        if not alive:
            if publisher_code is not None:
                exit_reason = f'publisher_exit:{publisher_code}'
            elif camera_code is not None:
                exit_reason = f'camera_exit:{camera_code}'
            else:
                exit_reason = 'not_started'
            if self._next_restart_at is None:
                delay = self._backoff.record_failure(now)
                self._next_restart_at = now + delay

        with self._lock:
            progress = self._progress
        delay_remaining = None
        if self._next_restart_at is not None:
            delay_remaining = max(0.0, self._next_restart_at - now)
        return SupervisorSnapshot(
            processes_alive=alive,
            progress=progress,
            total_encoded_bytes=self._read_written_bytes(),
            exit_reason=exit_reason,
            restart_delay=delay_remaining,
        )

    def restart_due(self, now: float) -> bool:
        return self._next_restart_at is not None and now >= self._next_restart_at

    def schedule_restart(self, now: float) -> None:
        if self._next_restart_at is None:
            delay = self._backoff.record_failure(now)
            self._next_restart_at = now + delay

    def restart(self) -> None:
        self.stop()
        self._next_restart_at = None
        self.start()

    def mark_healthy(self, now: float) -> None:
        self._backoff.record_healthy(now)

    def stop(self) -> None:
        processes = [process for process in (self._publisher, self._camera) if process is not None]
        self._signal_alive(processes, signal.SIGINT)
        self._wait_until(processes, self._sigint_timeout)
        self._signal_alive(processes, signal.SIGTERM)
        self._wait_until(processes, self._sigterm_timeout)
        self._signal_alive(processes, signal.SIGKILL)
        for process in processes:
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
        for thread in self._threads:
            thread.join(timeout=1.0)
        self._threads.clear()
        self._publisher = None
        self._camera = None

    def _reader_thread(self, stream, parse_progress: bool, name: str) -> threading.Thread:
        def read() -> None:
            if stream is None:
                return
            parser = FfmpegProgressParser()
            for raw_line in iter(stream.readline, b''):
                line = raw_line.decode('utf-8', errors='replace').rstrip()
                if parse_progress:
                    sample = parser.feed(line)
                    if sample is not None:
                        with self._lock:
                            self._progress = sample
                        continue
                if line:
                    with self._lock:
                        self._diagnostics.append(f'{name}:{line}')

        return threading.Thread(target=read, name=name, daemon=True)

    def _read_written_bytes(self) -> int | None:
        if self._camera is None:
            return None
        try:
            with open(f'/proc/{self._camera.pid}/io', encoding='utf-8') as handle:
                for line in handle:
                    if line.startswith('wchar:'):
                        return int(line.split(':', 1)[1].strip())
        except (FileNotFoundError, PermissionError, ValueError):
            return None
        return None

    @staticmethod
    def _signal_alive(processes: Sequence[subprocess.Popen[bytes]], signum: int) -> None:
        for process in processes:
            if process.poll() is None:
                try:
                    process.send_signal(signum)
                except ProcessLookupError:
                    pass

    @staticmethod
    def _wait_until(processes: Sequence[subprocess.Popen[bytes]], timeout: float) -> None:
        deadline = time.monotonic() + timeout
        for process in processes:
            remaining = max(0.0, deadline - time.monotonic())
            if process.poll() is None:
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    pass
