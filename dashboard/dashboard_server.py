# dashboard/dashboard_server.py
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
config = load_config()
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

# === Pydantic 모델 ===


class ThresholdUpdateRequest(BaseModel):
    motor_id: str
    value: float


# === 백그라운드 태스크 ===


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


@app.on_event("startup")
async def on_startup():
    """
    Level-2 실행뷰:
    - ingest_q / notify_q / control_q 기반 비동기 파이프라인 실행
    - WatchdogProcess 실행
    """
    loop = asyncio.get_event_loop()
    loop.create_task(input_loop())
    loop.create_task(analyzer_loop())
    loop.create_task(threshold_control_loop())
    loop.create_task(watchdog.run())


# === REST API 구현 (ADD71) ===


@app.get("/status")
async def get_status() -> Dict:
    """
    GET /status
    - 최근 이상 판정 요약 조회
    - 정상/이상 개수, 최근 시각 등
    """
    return db_manager.get_status_summary()


@app.get("/trend")
async def get_trend(limit: int = 100) -> List[Dict]:
    """
    GET /trend
    - μ, ΔT, T_a, 최종 임계값, 이상 비율 등 시계열 데이터
    """
    return db_manager.get_trend(limit=limit)


@app.get("/thresholds")
async def get_thresholds() -> List[Dict]:
    """
    GET /thresholds
    - 현재 적용 중인 수동 임계값 목록 조회
    (YAML에서 기본 설정, thresholds 테이블에서 수동 변경)
    """
    return db_manager.get_thresholds()


@app.put("/thresholds")
async def update_threshold(req: ThresholdUpdateRequest):
    """
    PUT /thresholds
    - 임계치 수정 요청
      → DBManager.update_threshold()
      → control_q 발행
      → ThresholdManager에 반영
    """
    if req.value <= 0:
        raise HTTPException(status_code=400, detail="Threshold must be > 0")

    db_manager.update_threshold(req.motor_id, req.value)

    msg = {
        "type": "threshold_update",
        "motor_id": req.motor_id,
        "value": req.value,
    }
    await queues.control_q.put(msg)

    return {"status": "ok", "motor_id": req.motor_id, "value": req.value}


@app.get("/notify")
async def get_notify(limit: int = 50) -> List[Dict]:
    """
    GET /notify
    - 최근 알림 이벤트 조회
    - 단순 폴링 방식 (SSE로 확장 가능)
    """
    alerts = db_manager.get_recent_alerts(limit=limit)
    return [format_alert(a) for a in alerts]

