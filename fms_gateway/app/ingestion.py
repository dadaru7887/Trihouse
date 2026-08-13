"""Adapter from validated protocol messages to durable repository projections."""

import asyncio

from .repositories import RuntimeContextConflict
from .tcp_protocol import ProcessedMessage, ProtocolRejected


class RepositoryIngestion:
    def __init__(self, repository):
        self.repository = repository

    async def __call__(self, message: ProcessedMessage) -> None:
        try:
            if message.action == "robot_status":
                await asyncio.to_thread(self.repository.ingest_robot_status, message.payload)
            elif message.action == "task_event":
                await asyncio.to_thread(self.repository.ingest_task_event, message.payload)
        except RuntimeContextConflict as error:
            raise ProtocolRejected("TASK_CONTEXT_MISMATCH") from error
