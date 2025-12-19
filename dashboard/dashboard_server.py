import os
import asyncio
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from config import load_config
from messaging import get_queues
from adapters import CSVInputAdapter, InputPort
from analyzer import (
    Preprocessor,
    StatisticsModule,
    ThresholdManager,
    AnomalyDetector,
    ResultPublisher,
)
from storage import DBManager
from watchdog.watchdog_process import WatchdogProcess
from .notifier_view import format_alert


# === 설정 / 공용 객체 초기화 ===
CONFIG_PATH = os.getenv("CONFIG_PATH", "config.yaml")
config = load_config(CONFIG_PATH)
queues = get_queues()

db_manager = DBManager(config["db_path"])

preprocessor = Preprocessor()
stats_module = StatisticsModule(
    window_size=config["window_size"],
    dynamic_margin=config["dynamic_margin"],
)
threshold_manager = ThresholdManager(dynamic_margin=config["dynamic_margin"])
anomaly_detector = AnomalyDetector(stats_module, threshold_manager)
result_publisher = ResultPublisher(db_manager, queues.notify_q)

csv_adapter = CSVInputAdapter(
    csv_path=config["csv_path"],
    motor_id=config["motor_id"],
)
input_port = InputPort(csv_adapter, queues.ingest_q)

watchdog = WatchdogProcess(
    queues=queues,
    db_manager=db_manager,
    interval_sec=config["watchdog_interval_sec"],
    queue_warn_size=config["watchdog_queue_warn_size"],
)

app = FastAPI(
    title="Edge Motor Monitor",
    description="외각 공조기 팬 모터 온도 기반 통계적 이상 탐지 (Version 1)",
    version="1.0.0",
)


class ThresholdUpdateRequest(BaseModel):
    motor_id: str
    # 숫자(float) 또는 "dynamic" 문자열을 허용
    value: object


async def analyzer_loop():
    """
    ingest_q → Preprocessor → AnomalyDetector → ResultPublisher
    QAS2-2: 새 데이터 입력 후 1초 내 통계/임계값 갱신 목표
    """
    while True:
        record = await queues.ingest_q.get()
        cleaned = preprocessor.clean(record)
        if cleaned is None:
            continue

        result = anomaly_detector.analyze(cleaned)
        await result_publisher.publish(result)


async def threshold_control_loop():
    await threshold_manager.control_loop(queues.control_q)


async def input_loop():
    """
    CSV 가상 센서 입력.
    delay_sec=0 으로 두면 파일을 한 번에 재생.
    실제 환경에서는 86400초(1일) 등으로 설정 가능.
    """
    await input_port.run(delay_sec=0.0)


def _preload_manual_thresholds_from_db() -> None:
    """
    ✅ 서버 시작 시 DB에 저장된 수동 임계값을 ThresholdManager 메모리에 로딩함.
    - PUT /thresholds는 DB에 저장되지만, 런타임 분석에 적용되려면 ThresholdManager에 주입 필요
    """
    try:
        rows = db_manager.get_thresholds()
        for r in rows:
            motor_id = r.get("motor_id")
            val = r.get("manual_threshold")
            if motor_id is not None and isinstance(val, (int, float)):
                threshold_manager.set_manual_threshold(motor_id, float(val))
    except Exception:
        # 시작 단계에서 로딩 실패해도 서버는 기동되도록 함 (로그는 운영 환경에서 추가 권장)
        pass


@app.on_event("startup")
async def on_startup():
    """
    Level-2 실행뷰:
    - ingest_q / notify_q / control_q 기반 비동기 파이프라인 실행
    - WatchdogProcess 실행
    """
    _preload_manual_thresholds_from_db()

    loop = asyncio.get_event_loop()
    loop.create_task(input_loop())
    loop.create_task(analyzer_loop())
    loop.create_task(threshold_control_loop())
    loop.create_task(watchdog.run())


@app.get("/status")
async def get_status() -> Dict:
    return db_manager.get_status_summary()


@app.get("/trend")
async def get_trend(limit: int = 100) -> List[Dict]:
    return db_manager.get_trend(limit=limit)


@app.get("/thresholds")
async def get_thresholds() -> List[Dict]:
    return db_manager.get_thresholds()


@app.put("/thresholds")
async def update_threshold(req: ThresholdUpdateRequest):
    """
    PUT /thresholds
    - 임계치 수정 요청
      → DBManager.update_threshold()
      → (즉시) ThresholdManager 메모리 반영
      → control_q 발행(타 컴포넌트/프로세스가 구독할 경우 대비)

    ✅ 확장:
      - value에 "dynamic"을 넣으면 수동 임계값을 해제하고 동적 임계값으로 복귀함
    """
    motor_id = req.motor_id

    # --- dynamic 모드 요청 ---
    if isinstance(req.value, str) and req.value.strip().lower() == "dynamic":
        # 1) DB에 sentinel(-1.0)로 저장 (NOT NULL 제약 회피)
        db_manager.disable_threshold(motor_id)

        # 2) 런타임 메모리에서 제거 → dynamic으로 전환
        if hasattr(threshold_manager, "clear_manual_threshold"):
            threshold_manager.clear_manual_threshold(motor_id)

        # 3) 이벤트 발행
        msg = {"type": "threshold_update", "motor_id": motor_id, "value": "dynamic"}
        await queues.control_q.put(msg)

        return {"status": "ok", "motor_id": motor_id, "mode": "dynamic"}

    # --- manual 모드(숫자) 요청 ---
    try:
        value = float(req.value)
    except Exception:
        raise HTTPException(status_code=400, detail="value must be a number or 'dynamic'")

    if value <= 0:
        raise HTTPException(status_code=400, detail="Threshold must be > 0")

    # 1) DB 영속화
    db_manager.update_threshold(motor_id, value)

    # 2) 런타임 즉시 적용
    if hasattr(threshold_manager, "set_manual_threshold"):
        threshold_manager.set_manual_threshold(motor_id, value)

    # 3) 이벤트 발행
    msg = {"type": "threshold_update", "motor_id": motor_id, "value": value}
    await queues.control_q.put(msg)

    return {"status": "ok", "motor_id": motor_id, "value": value}

@app.get("/notify")
async def get_notify(limit: int = 50) -> List[Dict]:
    alerts = db_manager.get_recent_alerts(limit=limit)
    return [format_alert(a) for a in alerts]
