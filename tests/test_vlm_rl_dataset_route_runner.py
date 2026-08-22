import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


RUNNER = Path(__file__).with_name("run_vlm_rl_dataset_route.py")


class _GatewayHandler(BaseHTTPRequestHandler):
    records: list[tuple[str, object]] = []
    job_states: dict[int, list[str]] = {}
    next_job_id = 1

    def log_message(self, *_args):
        return

    def _json(self, status: int, body: object):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/ready":
            self.records.append(("ready", None))
            return self._json(200, {"status": "ready"})
        job_id = int(self.path.rsplit("/", 1)[-1])
        states = self.job_states[job_id]
        state = states.pop(0) if len(states) > 1 else states[0]
        self.records.append(("poll", job_id))
        self._json(200, {"job_id": job_id, "state": state, "steps": []})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/internal/v1/jobs":
            job_id = self.next_job_id
            type(self).next_job_id += 1
            self.records.append(("create", body))
            return self._json(
                201,
                {
                    "job_id": job_id,
                    "job_code": body["job_code"],
                    "state": "queued",
                    "steps": [{"job_step_id": job_id * 10, "state": "pending"}],
                },
            )
        step_id = int(self.path.split("/")[-2])
        self.records.append(("dispatch", {"step_id": step_id, "body": body}))
        self._json(
            200,
            {"channel": "rmf", "message_type": "dispatch_task_request", "state": "pending"},
        )


def _run(*args: str, base_url: str | None = None):
    command = [sys.executable, str(RUNNER), *args]
    if base_url:
        command.extend(["--api-base-url", base_url])
    return subprocess.run(command, text=True, capture_output=True, timeout=10)


def _gateway(states: dict[int, list[str]]):
    _GatewayHandler.records = []
    _GatewayHandler.job_states = states
    _GatewayHandler.next_job_id = 1
    server = ThreadingHTTPServer(("127.0.0.1", 0), _GatewayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_dry_run_prints_one_destination_without_contacting_gateway():
    result = _run("--target-location-id", "12")

    assert result.returncode == 0, result.stderr
    assert "DRY-RUN" in result.stdout
    assert "12" in result.stdout


def test_single_destination_creates_dispatches_and_waits_for_completion():
    server = _gateway({1: ["running", "completed"]})
    try:
        result = _run(
            "--target-location-id", "12",
            "--execute", "--confirm-motion", "PK_01",
            "--poll-seconds", "0.01", "--timeout-seconds", "2",
            base_url=f"http://127.0.0.1:{server.server_port}",
        )
    finally:
        server.shutdown()

    assert result.returncode == 0, result.stderr
    assert [kind for kind, _ in _GatewayHandler.records] == [
        "ready", "create", "dispatch", "poll", "poll"
    ]
    created = _GatewayHandler.records[1][1]
    assert created["destination_location_id"] == 12
    assert created["steps"][0]["target_location_id"] == 12
    assert created["context"]["device_id"] == "PK_01"


def test_batch_waits_for_success_before_creating_next_job():
    server = _gateway({1: ["completed"], 2: ["completed"]})
    try:
        result = _run(
            "--location-ids", "12,15",
            "--execute", "--confirm-motion", "PK_01",
            "--poll-seconds", "0.01", "--timeout-seconds", "2",
            base_url=f"http://127.0.0.1:{server.server_port}",
        )
    finally:
        server.shutdown()

    assert result.returncode == 0, result.stderr
    assert [kind for kind, _ in _GatewayHandler.records] == [
        "ready", "create", "dispatch", "poll", "create", "dispatch", "poll"
    ]


def test_batch_stops_after_failed_job():
    server = _gateway({1: ["failed"]})
    try:
        result = _run(
            "--location-ids", "12,15",
            "--execute", "--confirm-motion", "PK_01",
            "--poll-seconds", "0.01", "--timeout-seconds", "2",
            base_url=f"http://127.0.0.1:{server.server_port}",
        )
    finally:
        server.shutdown()

    assert result.returncode != 0
    assert [kind for kind, _ in _GatewayHandler.records] == [
        "ready", "create", "dispatch", "poll"
    ]
    assert "failed" in result.stderr


def test_execute_requires_explicit_robot_confirmation():
    result = _run("--target-location-id", "12", "--execute")

    assert result.returncode != 0
    assert "--confirm-motion PK_01" in result.stderr


def test_all_uses_each_database_location_once_in_location_id_order(tmp_path):
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        "#!/bin/sh\nprintf '15\\tPACK-02\\t1.0\\t2.0\\n12\\tPACK-01\\t0.0\\t1.0\\n15\\tPACK-02\\t1.0\\t2.0\\n'\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    result = _run("--all", "--docker-bin", str(fake_docker))

    assert result.returncode == 0, result.stderr
    assert "route=12,15" in result.stdout


def test_list_prints_database_locations_without_dispatching(tmp_path):
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        "#!/bin/sh\nprintf '12\\tPACK-01\\t0.0\\t1.0\\n'\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    result = _run("--list", "--docker-bin", str(fake_docker))

    assert result.returncode == 0, result.stderr
    assert "12\tPACK-01\t0.0\t1.0" in result.stdout
