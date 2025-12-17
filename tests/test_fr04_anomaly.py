# tests/test_fr04_anomaly.py

from conftest import add_text, add_json, add_image
import matplotlib.pyplot as plt

def test_fr04_anomaly_detection(anomaly_detector, request, tmp_path):
    base = {"timestamp": "2024-01-01", "motor_id": "M1", "t2": 10.0}

    temps = [40.0, 41.0, 42.0, 43.0, 60.0]
    outs = []
    logs = []

    for t in temps:
        out = anomaly_detector.analyze(dict(base, t1=t))
        outs.append(out)
        logs.append(
            f"t1={t:.1f} | mu={out['mu']:.3f} | dyn={out['dynamic_threshold']:.3f} "
            f"| final={out['final_threshold']:.3f} | anomaly={out['is_anomaly']}"
        )

    # 텍스트 로그 첨부
    add_text(request, "FR-04 Decision Log", "\n".join(logs))

    # 마지막 결과(JSON) 첨부
    last = outs[-1]
    add_json(request, "FR-04 Last Decision JSON", {
        k: last[k] for k in ["t1","mu","delta_t","dynamic_threshold","final_threshold","is_anomaly"]
    })

    # 그래프(Threshold line 포함) 첨부
    xs = list(range(len(temps)))
    ys = [o["t1"] for o in outs]
    finals = [o["final_threshold"] for o in outs]

    plt.figure()
    plt.plot(xs, ys, marker="o", label="T1 (motor temp)")
    plt.plot(xs, finals, linestyle="--", label="Final threshold")
    plt.xticks(xs, [str(t) for t in temps])
    plt.legend()
    plt.title("FR-04 Anomaly Decision Trace")

    img_path = tmp_path / "fr04_anomaly_trace.png"
    plt.savefig(img_path)
    plt.close()

    add_image(request, "FR-04 Plot", str(img_path))

    assert last["is_anomaly"] is True

