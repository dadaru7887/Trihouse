"""Production entrypoint for inference-side recovery delivery.

This process never trains or writes MySQL. Candidate execution remains gated by
operator approval and the robot-side Safety Supervisor.
"""

from __future__ import annotations

import os
from pathlib import Path
import time

from model.vlm_rl.recovery_memory.sender import send_pending


def main() -> None:
    if os.environ.get("VLM_RL_EXECUTION_MODE") != "operator_approved":
        raise RuntimeError("physical recovery inference requires operator_approved mode")
    gateway = os.environ["FMS_GATEWAY_URL"]
    queue_dir = Path(os.environ.get("RECOVERY_QUEUE_DIR", "/var/lib/trihouse/recovery_queue"))
    interval = float(os.environ.get("RECOVERY_RETRY_INTERVAL_SECONDS", "2"))
    while True:
        send_pending(queue_dir, gateway, max_attempts=1)
        time.sleep(interval)


if __name__ == "__main__":
    main()
