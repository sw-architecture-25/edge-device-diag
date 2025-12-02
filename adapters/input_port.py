# adapters/input_port.py
import asyncio
import csv
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Dict, Optional, List


class CSVInputAdapter:
    """
    AS11 / ADD03
    - CSV 기반 가상 센서 어댑터
    - 이후 실센서 드라이버로 교체 가능(인터페이스 유지)

    기대하는 CSV 헤더 예시:
      date, ave_temp, min_temp, max_temp, motor_actual

    매핑:
      date          -> timestamp
      motor_actual  -> t1 (모터 외피 온도, T1)
      ave_temp      -> t2 (현재 외기 평균 온도, T2)
      min_temp/max_temp 은 env_min/env_max 로 record 에 포함 (옵션)
    """

    def __init__(self, csv_path: str, motor_id: str):
        self.csv_path = Path(csv_path)
        self.motor_id = motor_id

    def _read_all_rows(self) -> List[Dict]:
        with self.csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)

    @staticmethod
    def _parse_date(s: str) -> datetime:
        """
        date 컬럼 파싱용 유틸.
        2024-01-01 / 2024/01/01 / 2024-01-01 00:00:00 정도만 처리.
        필요하면 형식 더 추가.
        """
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        # 실패하면 그냥 fromisoformat 시도
        return datetime.fromisoformat(s)

    async def stream_records(self, delay_sec: float = 0.0) -> AsyncIterator[Dict]:
        """
        CSV 파일을 한 줄씩 읽어 ingest_q 로 publish 할 수 있도록 generator 형태 제공.
        delay_sec > 0 으로 두면 pseudo-real-time 재생 가능.
        """
        if not self.csv_path.exists():
            raise FileNotFoundError(f"CSV not found: {self.csv_path}")

        loop = asyncio.get_event_loop()
        rows = await loop.run_in_executor(None, self._read_all_rows)

        for row in rows:
            date_raw = row.get("date")
            ave_temp_raw = row.get("ave_temp")
            min_temp_raw = row.get("min_temp")
            max_temp_raw = row.get("max_temp")
            motor_actual_raw = row.get("motor_actual")

            if date_raw is None or motor_actual_raw is None:
                # 필수값 없으면 스킵 (실제에선 로그 추천)
                continue

            # 날짜 파싱
            try:
                ts = self._parse_date(date_raw)
            except Exception:
                # 형식을 전혀 모를 경우 스킵
                continue

            try:
                motor_temp = float(motor_actual_raw)
            except (TypeError, ValueError):
                continue

            # ave_temp 가 없으면 T2 는 None 으로 둠
            try:
                ave_temp = float(ave_temp_raw) if ave_temp_raw not in (None, "") else None
            except (TypeError, ValueError):
                ave_temp = None

            # min/max 는 있으면 같이 넣어둔다 (현재 분석에는 직접 사용하지 않음)
            env_min = None
            env_max = None
            try:
                if min_temp_raw not in (None, ""):
                    env_min = float(min_temp_raw)
            except (TypeError, ValueError):
                env_min = None

            try:
                if max_temp_raw not in (None, ""):
                    env_max = float(max_temp_raw)
            except (TypeError, ValueError):
                env_max = None

            record = {
                "timestamp": ts,
                "motor_id": self.motor_id,
                # 설계서 상 T1, T2 에 해당
                "t1": motor_temp,   # 모터 외피 온도
                "t2": ave_temp,     # 외기 평균 온도(옵션)
                # 참고용 추가 필드
                "env_min": env_min,
                "env_max": env_max,
                "source": "csv",
            }
            yield record

            if delay_sec > 0:
                await asyncio.sleep(delay_sec)


class InputPort:
    """
    MInputPort (LInputPort)
    - 센서/CSV 입력 표준화 → ingest_q 로 전달
    """

    def __init__(self, adapter: CSVInputAdapter, ingest_q):
        self.adapter = adapter
        self.ingest_q = ingest_q

    async def run(self, delay_sec: float = 0.0):
        async for record in self.adapter.stream_records(delay_sec=delay_sec):
            await self.ingest_q.put(record)

