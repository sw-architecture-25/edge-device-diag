# analyzer/preprocessor.py
from typing import Dict, Optional


class Preprocessor:
    """
    analyzer.Preprocessor
    - 결측·타입 검증 등 기본 전처리
    """

    def clean(self, record: Dict) -> Optional[Dict]:
        # 최소 필드 검증
        required = ["timestamp", "motor_id", "t1"]
        for key in required:
            if key not in record or record[key] is None:
                # 실전에서는 로깅 후 drop
                return None

        try:
            record["t1"] = float(record["t1"])
            if record.get("t2") is not None:
                record["t2"] = float(record["t2"])
        except (TypeError, ValueError):
            return None

        return record


