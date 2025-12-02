# dashboard/notifier_view.py
from typing import Dict


def format_alert(alert: Dict) -> Dict:
    """
    알림 렌더링용 포맷터 (UI와 연계 시 확장 가능)
    """
    return {
        "id": alert["id"],
        "timestamp": alert["ts"],
        "motor_id": alert["motor_id"],
        "message": alert["message"],
        "severity": alert["severity"],
    }

