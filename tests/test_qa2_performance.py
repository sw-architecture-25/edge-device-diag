# tests/test_qa2_performance.py
from conftest import add_text
import time

def test_qas2_stats_under_1s(stats, request):
    start = time.perf_counter()
    for i in range(1000):
        stats.update_and_compute("M1", float(i))
    elapsed = time.perf_counter() - start

    add_text(request, "QA2 Perf Timing", f"1000 updates elapsed={elapsed:.6f}s")

    assert elapsed < 1.0

