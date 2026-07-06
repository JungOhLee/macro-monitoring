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
TH = {"regime_bands": BANDS, "score_start": "2011-01-01", "alerts": {"pillar_extreme_level": 90, "cooldown_days": 7},
      "stress_bands": [{"name": "quiet", "upper": 40}, {"name": "elevated", "upper": 70},
                        {"name": "confirming", "upper": 100}]}


def make_reg(with_confirmation=False, with_context=False):
    series = [
        Series("up", "fred", "UP", "monthly", 45, 0, 1),
        Series("down", "fred", "DOWN", "monthly", 45, 0, 1),
        Series("young", "fred", "YOUNG", "monthly", 45, 0, 1),
    ]
    indicators = [
        Indicator("i_up", "Up", "valuation", "magnitude", "normal", 1, series="up"),
        Indicator("i_down", "Down", "leverage", "timing", "invert", 1, series="down"),
        Indicator("i_young", "Young", "sentiment", "timing", "normal", 1, series="young"),
    ]
    if with_confirmation:
        series.append(Series("conf", "fred", "CONF", "monthly", 45, 0, 1))
        indicators.append(
            Indicator("i_conf", "Conf", "valuation", "confirmation", "normal", 1, series="conf"))
    if with_context:
        series.append(Series("ctx", "fred", "CTX", "monthly", 45, 0, 1))
        indicators.append(
            Indicator("i_ctx", "Ctx", "context", "context", "normal", 1, series="ctx"))
    return Registry(series=series, indicators=indicators,
                    pillar_weights={"valuation": 0.5, "leverage": 0.3, "sentiment": 0.2})


def make_raw(with_confirmation=False, with_context=False):
    idx = pd.date_range("2000-01-31", "2012-12-31", freq="ME")
    up = pd.Series(np.arange(1.0, len(idx) + 1), index=idx)
    down = pd.Series(-np.arange(1.0, len(idx) + 1), index=idx)
    young = pd.Series([1.0, 2.0], index=pd.to_datetime(["2012-11-30", "2012-12-31"]))
    raw = {"up": up, "down": down, "young": young}
    if with_confirmation:
        raw["conf"] = pd.Series(np.arange(1.0, len(idx) + 1), index=idx)  # always at max -> froth 100
    if with_context:
        raw["ctx"] = pd.Series(np.arange(1.0, len(idx) + 1) * 2.0, index=idx)  # always at max -> froth 100
    return raw


def test_regime_for():
    assert scores.regime_for(10.0, BANDS) == "cool"
    assert scores.regime_for(40.0, BANDS) == "warm"
    assert scores.regime_for(84.9, BANDS) == "frothy"
    assert scores.regime_for(99.0, BANDS) == "bubble_risk"


def test_regime_for_production_bands_calibrated_edges():
    # Pins the production regime_bands (config/thresholds.yaml) recalibrated to
    # the 1975-2026 full-window composite quantiles: cool<64 (50th=64.09),
    # warm<76 (85th=76.33), frothy<83 (95th=82.96), else bubble_risk.
    from pipeline.registry import load_thresholds

    bands = load_thresholds()["regime_bands"]
    assert scores.regime_for(63.99, bands) == "cool"
    assert scores.regime_for(64.0, bands) == "warm"
    assert scores.regime_for(75.99, bands) == "warm"
    assert scores.regime_for(76.0, bands) == "frothy"
    assert scores.regime_for(82.99, bands) == "frothy"
    assert scores.regime_for(83.0, bands) == "bubble_risk"


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


def test_confirmation_excluded_from_composite_and_pillars():
    reg = make_reg(with_confirmation=True)
    res = scores.compute_scores(reg, TH, make_raw(with_confirmation=True))
    # i_conf froth is ~100 and sits in the valuation pillar; if it leaked in,
    # valuation would exceed the i_up-only value. It must equal the i_up-only pillar.
    res_no_conf = scores.compute_scores(make_reg(), TH, make_raw())
    last = lambda r, p: r.pillars[(r.pillars.window == "full") & (r.pillars.pillar == p)].iloc[-1]["score"]
    assert last(res, "valuation") == pytest.approx(last(res_no_conf, "valuation"))
    comp = lambda r: r.composite[r.composite.window == "full"].iloc[-1]["score"]
    assert comp(res) == pytest.approx(comp(res_no_conf))


def test_stress_series_from_confirmation_only():
    reg = make_reg(with_confirmation=True)
    res = scores.compute_scores(reg, TH, make_raw(with_confirmation=True))
    st = res.stress[res.stress.window == "full"]
    assert not st.empty
    assert st.iloc[-1]["score"] == pytest.approx(100.0, abs=0.5)  # single conf indicator at max
    # no confirmation indicators -> empty stress frame with the right columns
    res2 = scores.compute_scores(make_reg(), TH, make_raw())
    assert list(res2.stress.columns) == ["date", "window", "score"]
    assert res2.stress.empty


def test_context_indicator_computed_but_pillars_and_composite_untouched():
    # A context indicator's pillar ("context") is deliberately outside pillar_weights, so
    # it must never surface in pillars/composite -- registries with and without it must
    # yield byte-identical scored output (the honesty-gate regression this mirrors).
    reg_ctx = make_reg(with_context=True)
    res_ctx = scores.compute_scores(reg_ctx, TH, make_raw(with_context=True))
    res_base = scores.compute_scores(make_reg(), TH, make_raw())

    # it IS computed: present in result.indicators with both raw series and froth.
    assert "i_ctx" in res_ctx.indicators
    assert not res_ctx.indicators["i_ctx"].froth_full.empty
    assert not res_ctx.indicators["i_ctx"].series.empty

    # but it never contributes a pillar (pillar "context" is not in pillar_weights)...
    pil_ctx = res_ctx.pillars[res_ctx.pillars.window == "full"]
    pil_base = res_base.pillars[res_base.pillars.window == "full"]
    assert "context" not in set(pil_ctx.pillar.unique())
    assert set(pil_ctx.pillar.unique()) == set(pil_base.pillar.unique())
    pd.testing.assert_frame_equal(
        pil_ctx.reset_index(drop=True), pil_base.reset_index(drop=True))

    # ...and the composite is identical with or without it.
    comp_ctx = res_ctx.composite[res_ctx.composite.window == "full"].reset_index(drop=True)
    comp_base = res_base.composite[res_base.composite.window == "full"].reset_index(drop=True)
    pd.testing.assert_frame_equal(comp_ctx, comp_base)


def test_context_indicator_excluded_from_stress():
    # role=context must never leak into the confirmation-stress gauge (which aggregates
    # role=confirmation only) -- adding a max-froth context indicator alongside a real
    # confirmation indicator must not move the stress score at all.
    reg_ctx = make_reg(with_confirmation=True, with_context=True)
    raw_ctx = make_raw(with_confirmation=True, with_context=True)
    res_ctx = scores.compute_scores(reg_ctx, TH, raw_ctx)

    reg_base = make_reg(with_confirmation=True)
    raw_base = make_raw(with_confirmation=True)
    res_base = scores.compute_scores(reg_base, TH, raw_base)

    st_ctx = res_ctx.stress[res_ctx.stress.window == "full"].reset_index(drop=True)
    st_base = res_base.stress[res_base.stress.window == "full"].reset_index(drop=True)
    pd.testing.assert_frame_equal(st_ctx, st_base)


def test_append_scores_is_append_only(tmp_path, monkeypatch):
    monkeypatch.setattr(store.paths, "DATA_SCORES", tmp_path)
    res = scores.compute_scores(make_reg(with_confirmation=True), TH, make_raw(with_confirmation=True))
    n1, _, s1 = scores.append_scores(res)
    assert n1 > 0
    n2, m2, s2 = scores.append_scores(res)  # idempotent second run
    assert n2 == 0 and m2 == 0 and s2 == 0
    df = pd.read_csv(tmp_path / "composite.csv", parse_dates=["date"])
    assert list(df.columns) == ["date", "window", "score", "regime"]
    assert df.duplicated(subset=["date", "window"]).sum() == 0
    assert (tmp_path / "stress.csv").exists()
