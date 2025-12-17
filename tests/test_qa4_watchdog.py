# tests/test_qa4_watchdog.py
import asyncio
import pytest
from watchdog.watchdog_process import WatchdogProcess

@pytest.mark.asyncio
async def test_qas4_watchdog_runs(queues, db_manager):
    wd = WatchdogProcess(
        queues=queues,
        db_manager=db_manager,
        interval_sec=0.1,
        queue_warn_size=0,
    )

    task = asyncio.create_task(wd.run())
    await asyncio.sleep(0.3)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert task.cancelled()

