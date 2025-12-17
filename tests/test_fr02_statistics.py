from conftest import add_json

def test_fr02_statistics(stats, request):
    mu, delta, th = stats.update_and_compute("M1", 40.0)
    mu2, delta2, th2 = stats.update_and_compute("M1", 50.0)

    add_json(request, "FR-02 Statistics Snapshot", {
        "step1": {"mu": mu, "delta_t": delta, "dynamic_threshold": th},
        "step2": {"mu": mu2, "delta_t": delta2, "dynamic_threshold": th2},
        "window_size": stats.window_size,
        "dynamic_margin": stats.dynamic_margin,
    })

    assert mu == 40.0
    assert delta == 0.0
    assert th == 45.0
    assert mu2 == 45.0
    assert th2 == 50.0

