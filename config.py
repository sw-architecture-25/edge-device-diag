from pathlib import Path
from typing import Any, Dict

try:
    import yaml
except ImportError:
    yaml = None


DEFAULT_CONFIG: Dict[str, Any] = {
    "window_size": 30,
    "dynamic_margin": 5.0,
    "db_path": "edge_data.db",
    "csv_path": "data/motor_temps.csv",
    "motor_id": "fan_motor_1",
    "watchdog_interval_sec": 10,
    "watchdog_queue_warn_size": 100,
    "sla_update_sec": 1,
    "sla_alert_sec": 3,
}


def load_config(path: str = "config.yaml") -> Dict[str, Any]:
    cfg = DEFAULT_CONFIG.copy()
    p = Path(path)
    if p.exists() and yaml is not None:
        with p.open("r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        cfg.update(user_cfg)
    return cfg
