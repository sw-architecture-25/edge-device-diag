# tests/test_fr06_storage.py

from conftest import add_json

def test_fr06_storage_persistence(db_manager, request):
    rows = db_manager.get_trend(limit=10)
    add_json(request, "FR-06 Trend Snapshot", rows)
    assert isinstance(rows, list)

