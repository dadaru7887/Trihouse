"""검증된 TCP 메시지를 영속 Repository 갱신으로 연결하는 어댑터."""

import asyncio

from .repositories import RuntimeContextConflict
from .tcp_protocol import ProcessedMessage, ProtocolRejected


class RepositoryIngestion:
    """프로토콜 계층을 DB 구현과 분리하고 동기 SQL을 worker thread에서 실행한다."""
    def __init__(self, repository):
        self.repository = repository

    async def __call__(self, message: ProcessedMessage) -> None:
        """상태는 최신 장치 projection으로, 이벤트는 작업 상태 전이로 반영한다."""
        try:
            if message.action == "robot_status":
                await asyncio.to_thread(self.repository.ingest_robot_status, message.payload)
            elif message.action == "task_event":
                await asyncio.to_thread(self.repository.ingest_task_event, message.payload)
        except RuntimeContextConflict as error:
            # 내부 도메인 예외를 로봇이 처리할 수 있는 안정적인 프로토콜 코드로 바꾼다.
            raise ProtocolRejected("TASK_CONTEXT_MISMATCH") from error
