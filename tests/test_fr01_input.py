# tests/test_fr01_input.py
import pytest
from adapters.input_port import CSVInputAdapter

@pytest.mark.asyncio
async def test_fr01_receive_csv_input(tmp_path):
    csv = tmp_path / "input.csv"
    csv.write_text(
        "date,ave_temp,min_temp,max_temp,motor_actual\n"
        "2024-01-01,10,5,15,40\n"
    )

    adapter = CSVInputAdapter(str(csv), motor_id="M1")

    records = []
    async for r in adapter.stream_records():
        records.append(r)

    assert len(records) == 1
    r = records[0]
    assert r["motor_id"] == "M1"
    assert r["t1"] == 40.0
    assert r["t2"] == 10.0

