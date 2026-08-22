#!/usr/bin/env python3
"""Run isolated clean frozen-order cycles and preserve evidence for every run."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path(__file__).with_name("frozen_cycle.yaml")
EXPECTED_STEPS = (10, 20, 30, 40, 50, 60, 70)
TERMINAL_JOB_STATES = {"completed", "failed", "cancelled"}


def load_cycle_config(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    simulation = document.get("simulation") or {}
    if simulation.get("ros_domain_id") != 0:
        raise ValueError("simulation.ros_domain_id must be 0")
    if not simulation.get("map_name"):
        raise ValueError("simulation.map_name is required")
    order = document.get("order") or {}
    if not order.get("items"):
        raise ValueError("order.items is required")
    workers = document.get("packing_worker_by_dock") or {}
    if not workers:
        raise ValueError("packing_worker_by_dock is required")
    return document


def build_cycle_environment(
    source: Mapping[str, str], *, domain_id: int
) -> dict[str, str]:
    environment = dict(source)
    environment["ROS_DOMAIN_ID"] = str(domain_id)
    environment["P0_ROS_DOMAIN_ID"] = str(domain_id)
    return environment


def select_worker_id(job: Mapping[str, Any], mapping: Mapping[str, str]) -> str:
    assignment = (job.get("context") or {}).get("assignment") or {}
    dock_code = assignment.get("packing_dock_code")
    worker_id = mapping.get(str(dock_code)) if dock_code else None
    if not worker_id:
        raise ValueError(f"packing worker is not configured for dock {dock_code!r}")
    return worker_id


def evaluate_cycle(
    job: Mapping[str, Any] | None, *, latest_safety_detail: str | None
) -> dict[str, Any]:
    if job is not None:
        steps = {int(step["step_no"]): step for step in job.get("steps", [])}
        all_succeeded = set(steps) == set(EXPECTED_STEPS) and all(
            steps[number].get("state") == "succeeded" for number in EXPECTED_STEPS
        )
        if job.get("state") == "completed" and all_succeeded:
            return {"passed": True, "reason_code": "COMPLETED"}

    safety_reason = {
        "swept_stop": "SWEPT_STOP",
        "front_stop": "FRONT_STOP",
        "sensor_timeout": "SENSOR_TIMEOUT",
        "control_link_lost": "CONTROL_LINK_LOST",
        "keep_out": "KEEP_OUT",
        "emergency_latched": "EMERGENCY_LATCHED",
    }.get(latest_safety_detail or "")
    if safety_reason:
        return {"passed": False, "reason_code": safety_reason}

    if job is not None:
        for step in job.get("steps", []):
            if step.get("state") in {"failed", "cancelled"}:
                result = step.get("result") or {}
                return {
                    "passed": False,
                    "reason_code": result.get("reason_code")
                    or f"STEP_{step.get('step_no')}_{str(step.get('state')).upper()}",
                }
        if job.get("state") in {"failed", "cancelled"}:
            return {
                "passed": False,
                "reason_code": f"JOB_{str(job.get('state')).upper()}",
            }
    return {"passed": False, "reason_code": "CYCLE_TIMEOUT"}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _request_json(
    method: str,
    url: str,
    *,
    payload: Mapping[str, Any] | None = None,
    idempotency_key: str | None = None,
    timeout_s: float = 10.0,
) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except HTTPError as error:
        raw = error.read().decode("utf-8")
        return error.code, json.loads(raw) if raw else {}
    except URLError as error:
        raise RuntimeError(f"gateway request failed: {error.reason}") from error


def _run_logged(
    command: list[str], *, environment: Mapping[str, str], log_path: Path
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as stream:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=dict(environment),
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}"
        )


def _start_safety_recorder(
    path: Path, *, environment: Mapping[str, str]
) -> tuple[subprocess.Popen[str], Any]:
    stream = path.open("w", encoding="utf-8")
    command = (
        "source /opt/ros/jazzy/setup.bash && "
        f"source {ROOT / 'install/setup.bash'} && "
        "exec ros2 topic echo /pinky_01/trihouse/safety/state"
    )
    process = subprocess.Popen(
        ["bash", "-lc", command],
        cwd=ROOT,
        env=dict(environment),
        stdout=stream,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    return process, stream


def _stop_recorder(process: subprocess.Popen[str], stream: Any) -> None:
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
    stream.close()


def _latest_safety_detail(path: Path) -> str | None:
    latest = None
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("detail:"):
            latest = stripped.split(":", 1)[1].strip()
    return latest


def _append_timeline(path: Path, job: Mapping[str, Any]) -> None:
    record = {
        "observed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "job_id": job.get("job_id"),
        "job_state": job.get("state"),
        "steps": [
            {
                "step_no": step.get("step_no"),
                "action_type": step.get("action_type"),
                "state": step.get("state"),
                "reason_code": (step.get("result") or {}).get("reason_code"),
            }
            for step in sorted(job.get("steps", []), key=lambda item: item["step_no"])
        ],
    }
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def _complete_worker_step(
    base_url: str,
    job: Mapping[str, Any],
    worker_mapping: Mapping[str, str],
    *,
    run_id: str,
) -> dict[str, Any]:
    worker_id = select_worker_id(job, worker_mapping)
    payload = {
        "worker_id": worker_id,
        "completion_note": "clean simulation cycle",
        "acknowledged_manual_item_ids": [],
    }
    status, response = _request_json(
        "POST",
        f"{base_url}/api/v1/jobs/{job['job_id']}/worker-completion",
        payload=payload,
        idempotency_key=f"{run_id}-worker-completion",
    )
    detail = response.get("detail") or {}
    if status == 409 and detail.get("code") == "MANUAL_ACKNOWLEDGEMENT_REQUIRED":
        payload["acknowledged_manual_item_ids"] = detail.get("item_ids") or []
        status, response = _request_json(
            "POST",
            f"{base_url}/api/v1/jobs/{job['job_id']}/worker-completion",
            payload=payload,
            idempotency_key=f"{run_id}-worker-completion-ack",
        )
    if status != 200:
        raise RuntimeError(f"worker completion failed: HTTP {status} {response}")
    return response


def run_cycle(
    index: int,
    *,
    config: Mapping[str, Any],
    environment: Mapping[str, str],
    run_dir: Path,
    timeout_s: float,
) -> dict[str, Any]:
    cycle_dir = run_dir / f"cycle_{index:03d}"
    cycle_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    job: dict[str, Any] | None = None
    safety_process = None
    safety_stream = None
    error: str | None = None
    safety_path = cycle_dir / "safety_events.log"
    simulation = config["simulation"]
    base_url = str(simulation["gateway_url"]).rstrip("/")
    poll_interval = float(simulation["poll_interval_s"])
    run_id = f"clean-sim-{index}-{uuid4().hex}"

    try:
        # EN: Reset before every order so DB reservations, RMF tasks and robot
        # ownership from a failed cycle cannot contaminate the next result.
        # KO: 매 주문 전에 초기화해 실패 회차의 DB 예약·RMF task·로봇 점유가
        # 다음 결과를 오염시키지 못하게 한다.
        _run_logged(
            ["scripts/p0_reset.sh", str(simulation["map_name"])],
            environment=environment,
            log_path=cycle_dir / "reset.log",
        )
        _run_logged(
            ["scripts/p0_up.sh"],
            environment=environment,
            log_path=cycle_dir / "up.log",
        )
        safety_process, safety_stream = _start_safety_recorder(
            safety_path, environment=environment
        )

        order = dict(config["order"])
        order["external_reference"] = run_id
        status, created = _request_json(
            "POST",
            f"{base_url}/api/v1/orders",
            payload=order,
            idempotency_key=f"{run_id}-order",
        )
        write_json(cycle_dir / "order.json", created)
        if status not in {200, 201} or "job_id" not in created:
            raise RuntimeError(f"order creation failed: HTTP {status} {created}")

        job_id = int(created["job_id"])
        deadline = time.monotonic() + timeout_s
        completion_sent = False
        previous_signature = None
        while time.monotonic() < deadline:
            status, current = _request_json(
                "GET", f"{base_url}/api/v1/jobs/{job_id}"
            )
            if status != 200:
                raise RuntimeError(f"job poll failed: HTTP {status} {current}")
            job = current
            signature = (
                job.get("state"),
                tuple((step["step_no"], step["state"]) for step in job["steps"]),
            )
            if signature != previous_signature:
                _append_timeline(cycle_dir / "step_timeline.jsonl", job)
                previous_signature = signature

            wait_step = next(
                (step for step in job["steps"] if int(step["step_no"]) == 60),
                None,
            )
            if (
                wait_step is not None
                and wait_step.get("state") == "running"
                and not completion_sent
            ):
                response = _complete_worker_step(
                    base_url,
                    job,
                    config["packing_worker_by_dock"],
                    run_id=run_id,
                )
                write_json(cycle_dir / "worker_completion.json", response)
                completion_sent = True

            if job.get("state") in TERMINAL_JOB_STATES:
                break
            time.sleep(poll_interval)
    except (RuntimeError, ValueError) as exc:
        error = str(exc)
    finally:
        if safety_process is not None and safety_stream is not None:
            _stop_recorder(safety_process, safety_stream)
        if Path("/tmp/sim.log").is_file():
            shutil.copy2("/tmp/sim.log", cycle_dir / "sim.log")
        if job is not None:
            write_json(cycle_dir / "job_final.json", job)

    evaluation = evaluate_cycle(
        job, latest_safety_detail=_latest_safety_detail(safety_path)
    )
    result = {
        "cycle": index,
        **evaluation,
        "job_id": None if job is None else job.get("job_id"),
        "job_state": None if job is None else job.get("state"),
        "latest_safety_detail": _latest_safety_detail(safety_path),
        "duration_s": round(time.monotonic() - started, 3),
        "ros_domain_id": int(config["simulation"]["ros_domain_id"]),
        "error": error,
    }
    if error and result["reason_code"] == "CYCLE_TIMEOUT":
        result["reason_code"] = "RUNNER_ERROR"
    write_json(cycle_dir / "result.json", result)
    return result


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=_positive_int, default=1)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--keep-last",
        action="store_true",
        help="leave the final simulation running for RViz inspection",
    )
    parser.add_argument("--artifacts", type=Path, default=ROOT / "artifacts" / "simulation_cycles")
    args = parser.parse_args(argv)

    config = load_cycle_config(args.config.resolve())
    simulation = config["simulation"]
    timeout_s = float(args.timeout or simulation["cycle_timeout_s"])
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    run_dir = args.artifacts.resolve() / stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    environment = build_cycle_environment(
        os.environ, domain_id=int(simulation["ros_domain_id"])
    )
    write_json(run_dir / "config.snapshot.json", config)

    results = []
    try:
        for index in range(1, args.count + 1):
            print(f"[cycle {index}/{args.count}] clean reset부터 시작합니다", flush=True)
            result = run_cycle(
                index,
                config=config,
                environment=environment,
                run_dir=run_dir,
                timeout_s=timeout_s,
            )
            results.append(result)
            print(
                f"[cycle {index}/{args.count}] {result['reason_code']} "
                f"job={result['job_id']} duration={result['duration_s']}s",
                flush=True,
            )
    finally:
        if not args.keep_last:
            subprocess.run(
                ["scripts/sim_teardown.sh"],
                cwd=ROOT,
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

    summary = {
        "run_dir": str(run_dir),
        "count": len(results),
        "passed": sum(1 for result in results if result["passed"]),
        "failed": sum(1 for result in results if not result["passed"]),
        "results": results,
    }
    write_json(run_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
