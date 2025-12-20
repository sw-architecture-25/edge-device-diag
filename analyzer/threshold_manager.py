from typing import Dict, Optional


class ThresholdManager:
    """
    ThresholdManager
    - 동적 상한값(T_a)을 기본으로 하고,
      운영자 수동 임계값(manual_threshold)을 우선 적용함

    주의:
    - DB에 manual_threshold를 저장하는 것만으로는 런타임 판정에 자동 반영되지 않음
      (이 인스턴스의 메모리에 로딩/주입이 필요함)
    """

    def __init__(self, dynamic_margin: float):
        self.dynamic_margin = dynamic_margin
        self._manual_thresholds: Dict[str, float] = {}

    def set_manual_threshold(self, motor_id: str, value: float) -> None:
        """수동 임계값을 런타임 메모리에 즉시 반영함"""
        if not motor_id:
            return
        self._manual_thresholds[motor_id] = float(value)

    def clear_manual_threshold(self, motor_id: str) -> None:
        """특정 motor_id의 수동 임계값을 제거하여 동적 임계값으로 복귀함"""
        if motor_id in self._manual_thresholds:
            del self._manual_thresholds[motor_id]

    def get_manual_threshold(self, motor_id: str) -> Optional[float]:
        return self._manual_thresholds.get(motor_id)

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
                # ✅ 큐로 들어온 수동 임계값을 즉시 반영
                self.set_manual_threshold(motor_id, float(value))

    def get_effective_threshold(self, motor_id: str, dynamic_threshold: float) -> float:
        """
        분석 엔진이 사용할 최종 임계값 반환.
        - manual이 있으면 manual 우선
        - 없으면 dynamic 사용
        """
        manual = self._manual_thresholds.get(motor_id)
        if manual is not None:
            return manual
        return dynamic_threshold
