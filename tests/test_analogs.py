import pandas as pd
import pytest

from pipeline.compute import analogs, scores
from tests.test_scores import TH, make_raw, make_reg


def test_froth_vectors_excludes_context_indicators():
    # froth_vectors() is the shared building block behind both today's live analog
    # vector (export.py) and each backtest month's vector (backtest.py) -- role=context
    # indicators must never appear in its output even though they qualify and compute
    # froth just like any other indicator.
    reg = make_reg(with_context=True)
    res = scores.compute_scores(reg, TH, make_raw(with_context=True))
    fv = analogs.froth_vectors(reg, res)
    assert "i_ctx" not in fv
    assert set(fv) == {"i_up", "i_down"}  # i_young gated out (< 10y history)


def test_cosine_identical_and_orthogonalish():
    a = {"x": 90.0, "y": 10.0, "z": 50.0, "w": 30.0, "v": 70.0, "u": 20.0, "t": 60.0, "s": 40.0}
    # Identical vectors are always cosine 1.0 regardless of demeaning (same direction).
    assert analogs.cosine(a, dict(a)) == pytest.approx(1.0)
    b = {k: 100.0 - v for k, v in a.items()}
    # Hand-recomputed under demeaning (subtract 50.0 from every element before dot/norm):
    #   a - 50: x=40, y=-40, z=0,  w=-20, v=20,  u=-30, t=10,  s=-10
    #   b = 100-a, so b - 50 = 50-a = -(a-50): x=-40, y=40, z=0, w=20, v=-20, u=30, t=-10, s=10
    #   i.e. (b-50) is EXACTLY the negation of (a-50) -> the two demeaned vectors point in
    #   exactly opposite directions -> cosine = -1.0 (not just "less than 1.0" as in the
    #   old all-positive-percentile formulation where both vectors floored near 0.70-1.0).
    #   dot = sum((a-50)_i * (b-50)_i) = sum((a-50)_i * -(a-50)_i) = -sum((a-50)_i^2)
    #       = -(40^2+40^2+0+20^2+20^2+30^2+10^2+10^2) = -(1600+1600+0+400+400+900+100+100) = -5100
    #   |a-50| = |b-50| = sqrt(5100)
    #   cosine = -5100 / (sqrt(5100)*sqrt(5100)) = -5100/5100 = -1.0
    assert analogs.cosine(a, b) == pytest.approx(-1.0)
    assert analogs.cosine(a, b) < analogs.cosine(a, dict(a))


def test_cosine_min_shared():
    a = {"x": 1.0, "y": 2.0}
    assert analogs.cosine(a, a, min_shared=8) is None
    # Identical vectors are cosine 1.0 regardless of demeaning (demeaned: x=-49, y=-48).
    assert analogs.cosine(a, a, min_shared=2) == pytest.approx(1.0)


def test_cosine_neutral_all_50_is_zero_norm():
    # A perfectly-neutral (all-50) vector demeans to an all-zero vector -> zero norm ->
    # cosine is undefined, so the zero-norm guard must return None (not raise / not 0).
    keys = [f"k{i}" for i in range(8)]
    neutral = {k: 50.0 for k in keys}
    other = {k: 80.0 for k in keys}
    assert analogs.cosine(neutral, other) is None
    assert analogs.cosine(neutral, dict(neutral)) is None


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
    # Demonstrates the discrimination fix directly: under the OLD (non-demeaned) cosine,
    # today (all 80s) and the -12 snapshot (all 20s) are both positive scalar multiples of
    # the all-ones vector and would ALSO tie at cosine 1.0 (only the Euclidean tiebreak
    # separated them). Demeaned, today-50=+30 uniform and -12's snap-50=-30 uniform point in
    # exactly opposite directions: cosine = -1.0 -- a real (non-tied) discrimination against
    # today, not a coincidental tiebreak win.
    assert top[1]["offset_months"] == -12
    assert top[1]["similarity"] == pytest.approx(-1.0)


def test_top_analogs_euclidean_tiebreak_still_applies_after_demeaning():
    # Construct a genuine post-demeaning cosine tie: two snapshots whose demeaned vectors
    # are both positive scalar multiples of today's demeaned vector (same direction ->
    # cosine 1.0 for both), differing only in magnitude. The Euclidean tiebreak on raw
    # values must still pick the literally-closer one, since subtracting the same constant
    # (50) from both operands of a Euclidean distance cancels out and does not change it:
    # (today_k - 50) - (vec_k - 50) == today_k - vec_k.
    keys = [f"k{i}" for i in range(8)]
    today = {k: 70.0 for k in keys}   # demeaned: +20 uniform
    rows = []
    for off, scale in ((-6, 60.0), (-12, 90.0)):   # demeaned: +10 (scalar 0.5) and +40 (scalar 2.0)
        for k in keys:
            rows.append({"episode": "gfc", "offset_months": off, "indicator_id": k, "percentile": scale})
    snaps = pd.DataFrame(rows)
    top = analogs.top_analogs(today, snaps, k=2)
    assert top[0]["similarity"] == pytest.approx(1.0)
    assert top[1]["similarity"] == pytest.approx(1.0)
    # Euclidean dist: -6 offset = (70-60)^2*8 = 800; -12 offset = (70-90)^2*8 = 3200.
    assert top[0]["offset_months"] == -6
    assert top[1]["offset_months"] == -12
