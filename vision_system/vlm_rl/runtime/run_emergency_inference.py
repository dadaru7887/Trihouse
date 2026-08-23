"""Run VLM prompt inference and approved recovery-policy proposal delivery.

This is intentionally a thin entrypoint: the production implementation lives
in ``model.vlm_rl.inference.runtime`` and never publishes raw ``/cmd_vel``.
Nav2 and the robot-side Safety Supervisor remain the execution authorities.
"""

from __future__ import annotations

from model.vlm_rl.inference.runtime import main


if __name__ == "__main__":
    main()

