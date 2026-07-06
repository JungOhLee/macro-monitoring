import json

import numpy as np
import pandas as pd
import pytest

from pipeline.compute import sequencer as seq

ASOF = pd.Timestamp("2026-07-01")
CFG = {
    "engaged_min_stages": 2, "lapse_days": 92, "reset_drawdown_pct": 20,
    "stages": {
        "3": {"rule": "curve_resteepen", "series": "t10y3m", "lookback_days": 548,
               "min_inverted_days": 21, "resteepen_level": 0.25},
        "4": {"rule": "spread_widening", "series": "baa10y", "low_lookback_days": 365, "widen": 0.60},
        "6": {"rule": "price_confirmation", "index": "spx", "dma_days": 200,
               "sahm_series": "sahmrealtime", "sahm_level": 0.5,
               "vix_series": "vixcls", "vix_level": 30},
    },
}


def days(n, end=ASOF):
    return pd.date_range(end=end, periods=n, freq="B")


def test_curve_resteepen_fires_after_inversion():
    idx = days(400)
    vals = np.full(len(idx), 1.0)
    vals[100:160] = -0.3          # inverted ~60 business days, within lookback
    vals[-30:] = 0.30             # re-steepened above 0.25
    raw = {"t10y3m": pd.Series(vals, index=idx)}
    fired = seq._stage_curve_resteepen(CFG["stages"]["3"], raw, ASOF)
    assert fired is True
    # never inverted -> False
    raw2 = {"t10y3m": pd.Series(np.full(len(idx), 1.0), index=idx)}
    assert seq._stage_curve_resteepen(CFG["stages"]["3"], raw2, ASOF) is False


def test_spread_widening():
    idx = days(300)
    vals = np.full(len(idx), 1.50)
    vals[-5:] = 2.30              # 12m low 1.50, now +0.80 -> fired
    raw = {"baa10y": pd.Series(vals, index=idx)}
    assert seq._stage_spread_widening(CFG["stages"]["4"], raw, ASOF) is True
    vals[-5:] = 1.80              # only +0.30 -> not fired
    raw = {"baa10y": pd.Series(vals, index=idx)}
    assert seq._stage_spread_widening(CFG["stages"]["4"], raw, ASOF) is False


def test_price_confirmation_needs_both_conditions():
    idx = days(300)
    spx = pd.Series(np.linspace(5000, 4000, len(idx)), index=idx)   # below its 200dma
    vix_hot = {"spx": spx, "vixcls": pd.Series([35.0], index=[ASOF]),
               "sahmrealtime": pd.Series([0.1], index=[ASOF - pd.Timedelta(days=40)])}
    assert seq._stage_price_confirmation(CFG["stages"]["6"], vix_hot, ASOF) is True
    calm = {"spx": spx, "vixcls": pd.Series([12.0], index=[ASOF]),
            "sahmrealtime": pd.Series([0.1], index=[ASOF - pd.Timedelta(days=40)])}
    assert seq._stage_price_confirmation(CFG["stages"]["6"], calm, ASOF) is False


def test_missing_data_returns_none():
    assert seq._stage_spread_widening(CFG["stages"]["4"], {}, ASOF) is None


def test_stage_pillar_above():
    cfg = {"level": 80, "min_days": 100}
    # pinned above the level for 200 business days -> True
    idx = days(200)
    s = pd.Series(85.0, index=idx)
    assert seq._stage_pillar_above(cfg, s, ASOF) is True
    # only the most recent 50 days sit above the level; the 75 before that are below it -> False
    idx2 = days(125)
    vals = np.concatenate([np.full(75, 60.0), np.full(50, 85.0)])
    s2 = pd.Series(vals, index=idx2)
    assert seq._stage_pillar_above(cfg, s2, ASOF) is False
    # history shorter than min_days -> None (not enough data to judge)
    idx3 = days(60)
    s3 = pd.Series(85.0, index=idx3)
    assert seq._stage_pillar_above(cfg, s3, ASOF) is None


def test_stage_froth_rollover():
    cfg = {"level": 85, "lookback_days": 365, "decline_obs": 2}
    # froth peaks at 90 then the last 3 observations decline -> True
    idx = days(60)
    vals = np.concatenate([np.linspace(50, 90, 57), [88.0, 85.0, 80.0]])
    s = pd.Series(vals, index=idx)
    assert seq._stage_froth_rollover(cfg, s, ASOF) is True
    # still rising into the close (like today's margin debt froth) -> False
    idx2 = days(60)
    s2 = pd.Series(np.linspace(50, 90, 60), index=idx2)
    assert seq._stage_froth_rollover(cfg, s2, ASOF) is False
    # no data -> None
    assert seq._stage_froth_rollover(cfg, pd.Series(dtype=float), ASOF) is None


def test_stage_breadth_divergence():
    cfg = {"index": "spx", "near_high_pct": 2.0, "high_lookback_days": 365, "breadth_low_days": 126}
    idx = days(300)
    spx = pd.Series(np.linspace(4000, 5000, len(idx)), index=idx)  # at its 52wk high at asof
    breadth_at_low = pd.Series(np.linspace(60, 10, len(idx)), index=idx)  # at its 126d low at asof
    raw = {"spx": spx}
    assert seq._stage_breadth_divergence(cfg, raw, breadth_at_low, ASOF) is True
    # breadth well off its low -> False
    breadth_off_low = pd.Series(
        np.concatenate([np.linspace(60, 10, len(idx) - 5), np.full(5, 20.0)]), index=idx)
    assert seq._stage_breadth_divergence(cfg, raw, breadth_off_low, ASOF) is False


def test_evaluate_stages_wiring():
    from pipeline.compute.scores import compute_scores
    from tests.test_scores import TH as SCORES_TH, make_raw, make_reg

    reg = make_reg()
    raw = make_raw()
    result = compute_scores(reg, SCORES_TH, raw)
    th = {
        "sequencer": {
            "stages": {
                "1": {"pillar": "valuation", "level": 80, "min_days": 5},
                "2": {"indicator": "missing_indicator", "level": 85, "lookback_days": 365, "decline_obs": 2},
                "3": {"series": "missing_series", "lookback_days": 548,
                      "min_inverted_days": 21, "resteepen_level": 0.25},
                "4": {"series": "missing_series", "low_lookback_days": 365, "widen": 0.60},
                "5": {"index": "missing_series", "breadth": "missing_indicator", "near_high_pct": 2.0,
                      "high_lookback_days": 365, "breadth_low_days": 126},
                "6": {"index": "missing_series", "dma_days": 200, "sahm_series": "missing_series",
                      "sahm_level": 0.5, "vix_series": "missing_series", "vix_level": 30},
            }
        }
    }
    asof = raw["up"].index.max()
    fired = seq.evaluate_stages(reg, th, raw, result, asof)
    assert set(fired.keys()) == {1, 2, 3, 4, 5, 6}
    assert fired[2] is None  # margin_debt_yoy-style indicator absent from this synthetic registry


def test_update_state_fire_lapse_and_engage():
    spx = pd.Series(np.full(300, 5000.0), index=days(300))
    state = seq.new_state()
    fired = {1: True, 2: None, 3: True, 4: False, 5: False, 6: False}
    state = seq.update_state(state, fired, ASOF, spx, CFG)
    assert state["engaged"] is True                     # stages 1+3 of 1-3 fired
    assert state["current_stage"] == 3
    assert state["stages"]["1"]["fired"] is True
    assert state["stages"]["2"]["fired"] is None        # no data
    # condition goes false long enough -> lapse
    later = ASOF + pd.Timedelta(days=120)
    fired_off = {1: False, 2: None, 3: False, 4: False, 5: False, 6: False}
    state = seq.update_state(state, fired_off, later, spx, CFG)
    assert state["stages"]["1"]["lapsed"] is True
    assert state["engaged"] is False


def test_update_state_reset_on_drawdown():
    idx = days(300)
    vals = np.full(len(idx), 5000.0)
    vals[-10:] = 3800.0                                  # >20% below post-engagement high
    spx = pd.Series(vals, index=idx)
    state = seq.new_state()
    state = seq.update_state(state, {1: True, 2: True, 3: True, 4: True, 5: True, 6: True}, ASOF, spx, CFG)
    assert state["engaged"] is False                     # reset: crisis realized
    assert state["current_stage"] == 0
