# analyzer/result_publisher.py
from typing import Dict


class ResultPublisher:
    """
    ResultPublisher
    - DBManager에 저장 요청
    - 이상 발생 시 notify_q로 알림 이벤트 전송
    """

    def __init__(self, db_manager, notify_q):
        self.db_manager = db_manager
        self.notify_q = notify_q

    async def publish(self, result: Dict):
        obs_id, alert = self.db_manager.save_observation(result)
        if alert is not None:
            await self.notify_q.put(alert)

