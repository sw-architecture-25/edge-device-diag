# tests/conftest.py
import asyncio
import json
import pytest
from html import escape

from analyzer.statistics_module import StatisticsModule
from analyzer.anomaly_detector import AnomalyDetector
from storage.db_manager import DBManager


class DummyQueues:
    def __init__(self):
        self.ingest_q = asyncio.Queue()
        self.notify_q = asyncio.Queue()
        self.control_q = asyncio.Queue()


@pytest.fixture
def queues():
    return DummyQueues()


@pytest.fixture
def db_manager(tmp_path):
    return DBManager(str(tmp_path / "test.db"))


@pytest.fixture
def stats():
    return StatisticsModule(window_size=5, dynamic_margin=5.0)


@pytest.fixture
def anomaly_detector(stats, db_manager):
    # ThresholdManager는 실제 threshold DB 연동
    from analyzer.threshold_manager import ThresholdManager
    tm = ThresholdManager(db_manager)
    return AnomalyDetector(stats, tm)


REQ_MAP = {
    "test_fr01_input.py": "FR-01 / UR-01 (CSV 입력 수신/표준화)",
    "test_fr02_statistics.py": "FR-02 (이동평균/ΔT/동적상한 계산)",
    "test_fr03_threshold.py": "FR-03 / QA3 (수동 임계치 DB 반영)",
    "test_fr04_anomaly.py": "FR-04 (임계치 기반 이상 판정)",
    "test_fr05_alert.py": "FR-05 (이상 시 alert 생성/저장)",
    "test_fr06_storage.py": "FR-06 (관측/추세 조회로 영속화 확인)",
    "test_qa2_performance.py": "QA2 (성능: 1초 SLA 근사 검증)",
    "test_qa4_watchdog.py": "QA4 (워치독 루프/DB 헬스체크 동작)",
}


# =========================
# ✅ 1) 테스트에서 "첨부물"을 item.extra에 dict로 저장하는 헬퍼
#   - pytest-html extras를 쓰지 않음 (버전/훅 충돌 회피)
# =========================
def _ensure_item_extra(item):
    if not hasattr(item, "extra") or item.extra is None:
        item.extra = []


def add_text(request, name: str, text: str):
    _ensure_item_extra(request.node)
    request.node.extra.append({"type": "text", "name": name, "content": text})


def add_json(request, name: str, obj):
    _ensure_item_extra(request.node)
    request.node.extra.append({"type": "json", "name": name, "content": obj})


def add_image(request, name: str, path: str):
    """
    path: report.html과 같은 디렉토리 기준 상대경로나,
          절대경로 file:// 를 쓰지 말고 파일경로를 그대로 넣는 것을 권장.
          (self-contained-html이어도 브라우저가 로컬 파일 접근을 막을 수 있음)
    """
    _ensure_item_extra(request.node)
    request.node.extra.append({"type": "image", "name": name, "path": str(path)})


# =========================
# ✅ 2) pytest-html row 아래에 HTML을 "강제 렌더링"하는 훅
# =========================
def pytest_html_results_table_html(report, data):
    extra_html = getattr(report, "_extra_html", "")
    if extra_html:
        data.append(extra_html)


# =========================
# ✅ 3) PASS/FAIL 요구사항 출력 + (call 단계) 첨부물 HTML 생성
# =========================
@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()

    # call 단계(테스트 본문)에서만 출력/HTML 생성
    if rep.when != "call":
        return

    # 파일명에서 요구사항 설명 찾기
    path = str(item.fspath)
    file = path.split("/")[-1].split("\\")[-1]
    req = REQ_MAP.get(file, "REQ-UNKNOWN")

    # 콘솔 요구사항 PASS/FAIL 출력
    if rep.passed:
        print(f"[PASS] {req} :: {item.name}")
    elif rep.failed:
        print(f"[FAIL] {req} :: {item.name}")

    # item.extra에 저장된 첨부물을 HTML로 만들어 report에 심기
    extras_list = list(getattr(item, "extra", []))

    blocks = []
    for ex in extras_list:
        if not isinstance(ex, dict):
            continue

        typ = ex.get("type")
        name = escape(str(ex.get("name", "extra")))

        if typ == "text":
            txt = escape(str(ex.get("content", "")))
            blocks.append(f"<h4 style='margin:8px 0 4px 0'>{name}</h4><pre>{txt}</pre>")

        elif typ == "json":
            payload = ex.get("content", {})
            js = escape(json.dumps(payload, ensure_ascii=False, indent=2))
            blocks.append(f"<h4 style='margin:8px 0 4px 0'>{name}</h4><pre>{js}</pre>")

        elif typ == "image":
            img_path = escape(str(ex.get("path", "")))
            # 로컬 파일 접근 정책 때문에 img src가 안 뜨는 경우가 있어 링크도 같이 제공
            blocks.append(
                f"<h4 style='margin:8px 0 4px 0'>{name}</h4>"
                f"<div style='margin-bottom:8px'>"
                f"<div><a href='{img_path}' target='_blank'>open image</a></div>"
                f"<img src='{img_path}' style='max-width:800px; border:1px solid #ddd; padding:4px'/>"
                f"</div>"
            )

    if blocks:
        rep._extra_html = (
            "<div style='padding:10px 0'>"
            f"<div style='font-size:12px; color:#666; margin-bottom:6px;'>"
            f"<b>Requirement:</b> {escape(req)}"
            f"</div>"
            + "".join(blocks)
            + "</div>"
        )
    else:
        rep._extra_html = (
            "<div style='padding:10px 0; font-size:12px; color:#888;'>"
            f"<b>Requirement:</b> {escape(req)}<br/>"
            "No extra artifacts attached for this test."
            "</div>"
        )

