# tests/test_fr05_alert.py

from conftest import add_json

def test_fr05_alert_generated(db_manager, request):
    result = {
        "timestamp": "2024-01-01",
        "motor_id": "M1",
        "t1": 100.0,
        "t2": 10.0,
        "mu": 50.0,
        "delta_t": 50.0,
        "dynamic_threshold": 55.0,
        "final_threshold": 55.0,
        "is_anomaly": True,
    }

    obs_id, alert = db_manager.save_observation(result)

    add_json(request, "FR-05 Alert JSON", {
        "observation_id": obs_id,
        "alert": alert,
    })

    assert obs_id is not None
    assert alert is not None
    assert alert["severity"] == "HIGH"

