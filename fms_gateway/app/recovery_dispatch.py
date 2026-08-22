"""Deliver approved recovery commands from the durable outbox to connected robots."""

from __future__ import annotations

import asyncio
import logging


logger = logging.getLogger(__name__)

# TRIHOUSE EXTENSION — EN: The original dev_driving code had no durable device downlink.
# TRIHOUSE 확장 — KO: 원본 dev_driving에는 영속적인 장비 명령 하향 경로가 없었다.

async def dispatch_pending_once(repository, links) -> int:
    """Send one batch and acknowledge only successful socket writes.

    EN: A disconnected robot must leave its command durable for the next retry.
    KO: 로봇 연결이 끊겼으면 명령을 지우지 않고 다음 재시도를 위해 보존한다.
    """
    commands = await asyncio.to_thread(repository.list_pending_commands)
    delivered = 0
    for command in commands:
        if not await links.push(command["device_id"], command["payload"]):
            continue
        await asyncio.to_thread(repository.mark_command_sent, command["command_id"])
        delivered += 1
    return delivered


async def dispatch_loop(repository, links, *, interval_seconds: float = 0.5) -> None:
    """Continuously drain the outbox while allowing clean task cancellation."""
    while True:
        try:
            await dispatch_pending_once(repository, links)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("recovery command dispatch failed")
        await asyncio.sleep(interval_seconds)
