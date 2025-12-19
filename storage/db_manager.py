# storage/db_manager.py
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class DBManager:
    """
    MDBManager / LocalRepository
    - raw/stat/judge/event 영속화
    - threshold 관리
    """

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        cur = self.conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                motor_id TEXT NOT NULL,
                t1 REAL NOT NULL,
                t2 REAL,
                mu REAL,
                delta_t REAL,
                dynamic_threshold REAL,
                final_threshold REAL,
                is_anomaly INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
        """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                observation_id INTEGER,
                ts TEXT NOT NULL,
                motor_id TEXT NOT NULL,
                message TEXT NOT NULL,
                severity TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(observation_id) REFERENCES observations(id)
            );
        """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS thresholds (
                motor_id TEXT PRIMARY KEY,
                manual_threshold REAL NOT NULL,
                updated_at TEXT NOT NULL
            );
        """
        )

        self.conn.commit()

    def save_observation(self, result: Dict) -> Tuple[int, Optional[Dict]]:
        """
        result는 analyzer.AnomalyDetector에서 enrich된 dict.
        - observations에 저장
        - 이상이면 alerts에 기록, alert dict 반환
        """
        ts = result["timestamp"]
        if isinstance(ts, datetime):
            ts_str = ts.isoformat()
        else:
            ts_str = str(ts)

        created_at = datetime.utcnow().isoformat()

        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO observations (
                ts, motor_id, t1, t2,
                mu, delta_t, dynamic_threshold, final_threshold,
                is_anomaly, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                ts_str,
                result["motor_id"],
                result["t1"],
                result.get("t2"),
                result.get("mu"),
                result.get("delta_t"),
                result.get("dynamic_threshold"),
                result.get("final_threshold"),
                1 if result.get("is_anomaly") else 0,
                created_at,
            ),
        )
        obs_id = cur.lastrowid

        alert_dict: Optional[Dict] = None
        if result.get("is_anomaly"):
            message = f"Anomaly detected: T1={result['t1']:.2f} >= threshold={result['final_threshold']:.2f}"
            severity = "HIGH"
            cur.execute(
                """
                INSERT INTO alerts (
                    observation_id, ts, motor_id, message, severity, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    obs_id,
                    ts_str,
                    result["motor_id"],
                    message,
                    severity,
                    created_at,
                ),
            )
            alert_id = cur.lastrowid
            alert_dict = {
                "id": alert_id,
                "observation_id": obs_id,
                "timestamp": ts_str,
                "motor_id": result["motor_id"],
                "message": message,
                "severity": severity,
            }

        self.conn.commit()
        return obs_id, alert_dict

    # === Threshold 관리 (FR-03 지원) ===

    def update_threshold(self, motor_id: str, value: float):
        now = datetime.utcnow().isoformat()
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO thresholds (motor_id, manual_threshold, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(motor_id) DO UPDATE SET
                manual_threshold=excluded.manual_threshold,
                updated_at=excluded.updated_at
        """,
            (motor_id, value, now),
        )
        self.conn.commit()

    def disable_threshold(self, motor_id: str):
        """manual_threshold를 비활성화하여 dynamic 모드로 전환.
        thresholds.manual_threshold가 NOT NULL이므로 -1.0을 sentinel로 사용함.
        """
        now = datetime.utcnow().isoformat()
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO thresholds (motor_id, manual_threshold, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(motor_id) DO UPDATE SET manual_threshold=excluded.manual_threshold, updated_at=excluded.updated_at
            """,
            (motor_id, -1.0, now),
        )
        self.conn.commit()

    def get_thresholds(self) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT motor_id, manual_threshold, updated_at FROM thresholds")
        rows = cur.fetchall()
        return [dict(row) for row in rows]

    # === Dashboard용 조회 API ===

    def get_status_summary(self) -> Dict[str, Any]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN is_anomaly = 1 THEN 1 ELSE 0 END) as anomalies
            FROM observations
        """
        )
        row = cur.fetchone()
        total = row["total"] or 0
        anomalies = row["anomalies"] or 0

        cur.execute(
            """
            SELECT ts, motor_id, t1, final_threshold, is_anomaly
            FROM observations
            ORDER BY ts DESC
            LIMIT 1
        """
        )
        last = cur.fetchone()
        last_dict = dict(last) if last else None

        return {
            "total_observations": total,
            "total_anomalies": anomalies,
            "last_observation": last_dict,
        }

    def get_trend(self, limit: int = 100) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT ts, motor_id, t1, t2, mu, delta_t,
                   dynamic_threshold, final_threshold, is_anomaly
            FROM observations
            ORDER BY ts DESC
            LIMIT ?
        """,
            (limit,),
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]

    def get_recent_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        # ✅ 정렬 기준을 ts(관측 시각) 대신 created_at(생성 시각)으로 변경
        #   - CSV 과거 데이터 재생 시 ts가 과거로 고정되어, 운영자가 최근에 임계값을 바꿔도
        #     notify 목록이 '관측 시각' 기준으로 뒤섞여 보이는 문제를 방지함
        # ✅ observation과 조인하여 dynamic/final threshold를 함께 반환 (UI에서 source 표시용)
        cur.execute(
            """
            SELECT
                a.id, a.observation_id, a.ts, a.motor_id, a.message, a.severity, a.created_at,
                o.dynamic_threshold, o.final_threshold
            FROM alerts a
            LEFT JOIN observations o ON a.observation_id = o.id
            ORDER BY a.created_at DESC, a.id DESC
            LIMIT ?
        """,
            (limit,),
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]

