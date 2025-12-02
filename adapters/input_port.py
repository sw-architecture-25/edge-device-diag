# adapters/input_port.py
import asyncio
import csv
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Dict, Optional


class CSVInputAdapter:
    """
    AS11 / ADD03
    - CSV 기반 가상 센서 어댑터
    - 이후 실센서 드라이버로 교체 가능(인터페이스 유지)
    """

    def __init__(self, csv_path: str, motor_id: str):
        self.csv_path = Path(csv_path)
        self.motor_id = motor_id

    async def stream_records(self, delay_sec: float = 0.0) -> AsyncIterator[Dict]:
        """
        CSV 파일을 한 줄씩 읽어 ingest_q로 publish 할 수 있도록 generator 형태 제공.
        delay_sec > 0 으로 두면 실시간(1일 1회) 비슷하게 지연을 줄 수 있음.
        CSV 컬럼 예시:
          timestamp, t1, t2
        """
        if not self.csv_path.exists():
            raise FileNotFoundError(f"CSV not found: {self.csv_path}")

        loop = asyncio.get_event_loop()
        # blocking I/O는 executor에 맡김
        def _read_all_rows():
            with self.csv_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                return list(reader)

        rows = await loop.run_in_executor(None, _read_all_rows)

        for row in rows:
            ts_raw = row.get("timestamp")
            t1_raw = row.get("t1")
            t2_raw = row.get("t2")

            try:
                ts = datetime.fromisoformat(ts_raw)
            except Exception:
                # 기본 포맷이 다르면 필요시 수정
                ts = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S")

            record = {
                "timestamp": ts,
                "motor_id": self.motor_id,
                "t1": float(t1_raw),
                "t2": float(t2_raw) if t2_raw is not None else None,
                "source": "csv",
            }
            yield record

            if delay_sec > 0:
                await asyncio.sleep(delay_sec)


class InputPort:
    """
    MInputPort (LInputPort)
    - 센서/CSV 입력 표준화 → ingest_q로 전달
    """

    def __init__(self, adapter: CSVInputAdapter, ingest_q):
        self.adapter = adapter
        self.ingest_q = ingest_q

    async def run(self, delay_sec: float = 0.0):
        async for record in self.adapter.stream_records(delay_sec=delay_sec):
            await self.ingest_q.put(record)

