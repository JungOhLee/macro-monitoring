import numpy as np
import pandas as pd
import pytest

from pipeline import store
from pipeline.compute import scores
from pipeline.registry import Indicator, Registry, Series

BANDS = [
    {"name": "cool", "upper": 40},
    {"name": "warm", "upper": 70},
    {"name": "frothy", "upper": 85},
    {"name": "bubble_risk", "upper": 100},
]
TH = {"regime_bands": BANDS, "score_start": "2011-01-01", "alerts": {"pillar_extreme_level": 90, "cooldown_days": 7}}


def make_reg():
    return Registry(
        series=[
            Series("up", "fred", "UP", "monthly", 45, 0, 1),
            Series("down", "fred", "DOWN", "monthly", 45, 0, 1),
            Series("young", "fred", "YOUNG", "monthly", 45, 0, 1),
        ],
        indicators=[
            Indicator("i_up", "Up", "valuation", "magnitude", "normal", 1, series="up"),
            Indicator("i_down", "Down", "leverage", "timing", "invert", 1, series="down"),
            Indicator("i_young", "Young", "sentiment", "timing", "normal", 1, series="young"),
        ],
        pillar_weights={"valuation": 0.5, "leverage": 0.3, "sentiment": 0.2},
    )


def make_raw():
    # 12+ years monthly, ending 2012-12-31
    idx = pd.date_range("2000-01-31", "2012-12-31", freq="ME")
    up = pd.Series(np.arange(1.0, len(idx) + 1), index=idx)      # always at its max -> pct 100
    down = pd.Series(-np.arange(1.0, len(idx) + 1), index=idx)   # always at its min -> pct ~0, inverted -> ~100
    young = pd.Series([1.0, 2.0], index=pd.to_datetime(["2012-11-30", "2012-12-31"]))  # <10y: excluded
    return {"up": up, "down": down, "young": young}


def test_regime_for():
    assert scores.regime_for(10.0, BANDS) == "cool"
    assert scores.regime_for(40.0, BANDS) == "warm"
    assert scores.regime_for(84.9, BANDS) == "frothy"
    assert scores.regime_for(99.0, BANDS) == "bubble_risk"


def test_compute_scores_math_and_gating():
    res = scores.compute_scores(make_reg(), TH, make_raw())
    comp_full = res.composite[res.composite.window == "full"].set_index("date")
    last = comp_full.iloc[-1]
    # i_up froth = 100, i_down froth = 100 - small; sentiment pillar absent (young gated out)
    # composite = (0.5*100 + 0.3*~99.4) / 0.8  -> > 99
    assert last["score"] > 99.0
    assert last["regime"] == "bubble_risk"
    pil = res.pillars[(res.pillars.window == "full")]
    assert set(pil.pillar.unique()) == {"valuation", "leverage"}  # sentiment never qualifies
    assert "i_young" not in res.indicators or res.indicators["i_young"].froth_full.empty
    # rolling window rows exist too
    assert (res.composite.window == "rolling20y").any()


def test_composite_reweights_missing_pillars():
    reg = make_reg()
    raw = make_raw()
    res = scores.compute_scores(reg, TH, raw)
    comp = res.composite[res.composite.window == "full"].iloc[-1]["score"]
    # equals weighted mean over available pillars only
    pil = res.pillars[(res.pillars.window == "full") & (res.pillars.date == res.composite.date.max())]
    by = dict(zip(pil.pillar, pil.score))
    expected = (0.5 * by["valuation"] + 0.3 * by["leverage"]) / 0.8
    assert comp == pytest.approx(expected, abs=0.01)


def test_append_scores_is_append_only(tmp_path, monkeypatch):
    monkeypatch.setattr(store.paths, "DATA_SCORES", tmp_path)
    res = scores.compute_scores(make_reg(), TH, make_raw())
    n1, _ = scores.append_scores(res)
    assert n1 > 0
    n2, m2 = scores.append_scores(res)  # idempotent second run
    assert n2 == 0 and m2 == 0
    df = pd.read_csv(tmp_path / "composite.csv", parse_dates=["date"])
    assert list(df.columns) == ["date", "window", "score", "regime"]
    assert df.duplicated(subset=["date", "window"]).sum() == 0
