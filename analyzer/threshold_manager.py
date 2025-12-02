# analyzer/threshold_manager.py
import asyncio
from typing import Dict, Optional


class ThresholdManager:
    """
    ThresholdManager
    - 동적 상한값(T_a)을 기본으로 하고,
      control_q를 통해 수신된 운영자 수동 임계값을 우선 적용.
    """

    def __init__(self, dynamic_margin: float):
        self.dynamic_margin = dynamic_margin
        self._manual_thresholds: Dict[str, float] = {}

    async def control_loop(self, control_q):
        """
        control_q에서 threshold_update 메시지 수신.
        메시지 형식 예:
          {
            "type": "threshold_update",
            "motor_id": "fan_motor_1",
            "value": 80.0
          }
        """
        while True:
            msg = await control_q.get()
            if not isinstance(msg, dict):
                continue
            if msg.get("type") != "threshold_update":
                continue

            motor_id = msg.get("motor_id")
            value = msg.get("value")
            if motor_id and isinstance(value, (int, float)):
                self._manual_thresholds[motor_id] = float(value)

    def get_effective_threshold(
        self, motor_id: str, dynamic_threshold: float
    ) -> float:
        manual = self._manual_thresholds.get(motor_id)
        if manual is not None:
            return manual
        return dynamic_threshold

