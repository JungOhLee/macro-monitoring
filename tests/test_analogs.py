import pandas as pd
import pytest

from pipeline.compute import analogs


def test_cosine_identical_and_orthogonalish():
    a = {"x": 90.0, "y": 10.0, "z": 50.0, "w": 30.0, "v": 70.0, "u": 20.0, "t": 60.0, "s": 40.0}
    assert analogs.cosine(a, dict(a)) == pytest.approx(1.0)
    b = {k: 100.0 - v for k, v in a.items()}
    assert analogs.cosine(a, b) < analogs.cosine(a, dict(a))


def test_cosine_min_shared():
    a = {"x": 1.0, "y": 2.0}
    assert analogs.cosine(a, a, min_shared=8) is None
    assert analogs.cosine(a, a, min_shared=2) == pytest.approx(1.0)


def test_top_analogs_prepeak_only_and_sorted():
    keys = [f"k{i}" for i in range(8)]
    today = {k: 80.0 for k in keys}
    rows = []
    for off, scale in ((-6, 80.0), (6, 80.0), (-12, 20.0)):
        for k in keys:
            rows.append({"episode": "gfc", "offset_months": off, "indicator_id": k, "percentile": scale})
    snaps = pd.DataFrame(rows)
    top = analogs.top_analogs(today, snaps, k=3)
    assert all(t["offset_months"] <= 0 for t in top)           # +6 excluded
    assert top[0]["offset_months"] == -6                        # exact match ranks first
    assert top[0]["similarity"] == pytest.approx(1.0)
    assert top[0]["n_shared"] == 8
