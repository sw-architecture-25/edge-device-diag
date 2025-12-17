# tests/test_fr03_threshold.py
def test_fr03_manual_threshold(db_manager):
    db_manager.update_threshold("M1", 60.0)
    ths = db_manager.get_thresholds()
    assert ths[0]["manual_threshold"] == 60.0

