# analyzer/statistics_module.py
from collections import defaultdict, deque
from statistics import mean
from typing import Dict, Tuple


class StatisticsModule:
    """
    StatisticsModule
    - 이동평균(μ), 온도 차(ΔT), 동적 상한값(T_a) 계산
    """

    def __init__(self, window_size: int = 30, dynamic_margin: float = 5.0):
        self.window_size = window_size
        self.dynamic_margin = dynamic_margin
        self._buffers: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self.window_size)
        )

    def update_and_compute(
        self, motor_id: str, current_temp: float
    ) -> Tuple[float, float, float]:
        buf = self._buffers[motor_id]
        buf.append(current_temp)

        if len(buf) == 0:
            mu = current_temp
        else:
            mu = mean(buf)

        delta_t = current_temp - mu
        dynamic_threshold = mu + self.dynamic_margin
        return mu, delta_t, dynamic_threshold

