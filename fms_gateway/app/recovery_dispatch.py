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


async def expire_stale_proposals_once(repository) -> int:
    """Close proposals nobody decided before their deadline.

    Autonomous operation produces tier C proposals on purpose, and the 5080
    runtime forms no new judgement while one proposal is still open. Without this
    sweep a single undecided proposal parks that robot forever.
    """
    expired = await asyncio.to_thread(repository.expire_stale_proposals)
    if expired:
        logger.info("expired %d undecided recovery proposals", len(expired))
    return len(expired)


async def expiry_loop(repository, *, interval_seconds: float = 10.0) -> None:
    while True:
        try:
            await expire_stale_proposals_once(repository)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("recovery proposal expiry sweep failed")
        await asyncio.sleep(interval_seconds)
