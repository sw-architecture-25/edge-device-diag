# watchdog/watchdog_process.py
import asyncio
from datetime import datetime


class WatchdogProcess:
    """
    WatchdogProcess (ADD72 / AS32)
    - ingest_q, notify_q, control_q 및 DB 연결 상태를 주기적으로 점검
    - 이 프로토타입에서는 이상 시 로그만 남기고,
      실제 재기동 로직은 TODO로 남김.
    """

    def __init__(self, queues, db_manager, interval_sec: int, queue_warn_size: int):
        self.queues = queues
        self.db_manager = db_manager
        self.interval_sec = interval_sec
        self.queue_warn_size = queue_warn_size

    async def run(self):
        while True:
            await asyncio.sleep(self.interval_sec)
            now = datetime.utcnow().isoformat()

            ingest_size = self.queues.ingest_q.qsize()
            notify_size = self.queues.notify_q.qsize()
            control_size = self.queues.control_q.qsize()

            if ingest_size > self.queue_warn_size:
                print(
                    f"[{now}] Watchdog WARN: ingest_q size={ingest_size} "
                    f"> warn_size={self.queue_warn_size}"
                )

            if control_size > self.queue_warn_size:
                print(
                    f"[{now}] Watchdog WARN: control_q size={control_size} "
                    f"> warn_size={self.queue_warn_size}"
                )

            # DB 헬스체크 (간단한 SELECT 1)
            try:
                self.db_manager.conn.execute("SELECT 1")
            except Exception as e:
                print(f"[{now}] Watchdog ERROR: DB health check failed: {e}")
                # TODO: DB 재연결 및 Analyzer 재기동 로직 추가

