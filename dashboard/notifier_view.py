# dashboard/notifier_view.py
from typing import Dict


def _threshold_source(dynamic_threshold, final_threshold) -> str:
    try:
        if dynamic_threshold is None or final_threshold is None:
            return "unknown"
        # float 비교 오차 고려
        if abs(float(dynamic_threshold) - float(final_threshold)) > 1e-6:
            return "manual"
        return "dynamic"
    except Exception:
        return "unknown"


def format_alert(alert: Dict) -> Dict:
    """
    알림 렌더링용 포맷터 (UI와 연계 시 확장 가능)

    ✅ 개선:
    - threshold_source: "manual" | "dynamic" | "unknown"
    - dynamic_threshold / final_threshold를 함께 제공하여 사용자가 왜 저 값이 찍혔는지 즉시 확인 가능
    """
    dyn = alert.get("dynamic_threshold")
    fin = alert.get("final_threshold")
    return {
        "id": alert["id"],
        "timestamp": alert["ts"],
        "motor_id": alert["motor_id"],
        "message": alert["message"],
        "severity": alert["severity"],
        "dynamic_threshold": dyn,
        "final_threshold": fin,
        "threshold_source": _threshold_source(dyn, fin),
        "created_at": alert.get("created_at"),
    }
