# analyzer/anomaly_detector.py
from typing import Dict

from .statistics_module import StatisticsModule
from .threshold_manager import ThresholdManager


class AnomalyDetector:
    """
    AnomalyDetector
    - 통계치 계산 + 임계치 적용 + 이상 여부 판정
    """

    def __init__(
        self, stats: StatisticsModule, threshold_manager: ThresholdManager
    ):
        self.stats = stats
        self.threshold_manager = threshold_manager

    def analyze(self, record: Dict) -> Dict:
        motor_id = record["motor_id"]
        current_temp = record["t1"]

        mu, delta_t, dyn_th = self.stats.update_and_compute(
            motor_id, current_temp
        )
        final_threshold = self.threshold_manager.get_effective_threshold(
            motor_id, dyn_th
        )
        is_anomaly = current_temp >= final_threshold

        enriched = dict(record)
        enriched.update(
            {
                "mu": mu,
                "delta_t": delta_t,
                "dynamic_threshold": dyn_th,
                "final_threshold": final_threshold,
                "is_anomaly": is_anomaly,
            }
        )
        return enriched

