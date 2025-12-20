import asyncio
from dataclasses import dataclass


@dataclass
class QueueManager:
    ingest_q: asyncio.Queue
    notify_q: asyncio.Queue
    control_q: asyncio.Queue


queue_manager = QueueManager(
    ingest_q=asyncio.Queue(),
    notify_q=asyncio.Queue(),
    control_q=asyncio.Queue(),
)


def get_queues() -> QueueManager:
    return queue_manager
