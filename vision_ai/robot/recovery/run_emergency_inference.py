"""Run VLM prompt inference and approved recovery-policy proposal delivery.

This is intentionally a thin entrypoint: the production implementation lives
in ``vision_ai.robot.recovery.runtime`` and never publishes raw ``/cmd_vel``.
Nav2 and the robot-side Safety Supervisor remain the execution authorities.
"""

from __future__ import annotations

from vision_ai.robot.recovery.runtime import main


if __name__ == "__main__":
    main()

