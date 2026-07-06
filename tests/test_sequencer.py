import json

import numpy as np
import pandas as pd
import pytest

from pipeline.compute import sequencer as seq

ASOF = pd.Timestamp("2026-07-01")
CFG = {
    "engaged_min_stages": 2, "lapse_days": 92, "reset_drawdown_pct": 20, "credit_path": True,
    "stages": {
        "3": {"rule": "curve_resteepen", "series": "t10y3m", "lookback_days": 548,
               "min_inverted_days": 21, "resteepen_level": 0.25},
        "4": {"rule": "spread_widening", "series": "baa10y", "low_lookback_days": 365, "widen": 0.60},
        "6": {"rule": "price_confirmation", "index": "spx", "dma_days": 200,
               "sahm_series": "sahmrealtime", "sahm_level": 0.5,
               "vix_series": "vixcls", "vix_level": 30},
    },
}
CFG_NO_CREDIT_PATH = json.loads(json.dumps(CFG)) | {"credit_path": False}


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


def test_spread_widening_intra_window_fires_on_mid_window_graze_that_retraces():
    # GFC forensic shape: the spread grazes +0.70 off its trailing low mid-window,
    # then retraces back down before the window's final (month-end) observation.
    # A last-value-only check would miss this; the intra-window cummin check must not.
    idx = days(300)
    vals = np.full(len(idx), 1.50)
    vals[100] = 1.00                     # establishes the trailing 12m low mid-window
    vals[110:115] = 1.70                 # mid-window spike: 1.00 + 0.70 >= widen(0.60)
    vals[115:] = 1.05                    # retraces back down by the final (asof) observation
    raw = {"baa10y": pd.Series(vals, index=idx)}
    # last-value-vs-window-min (the old mechanism) would say False: 1.05 < 1.00 + 0.60
    assert vals[-1] < vals.min() + CFG["stages"]["4"]["widen"]
    assert seq._stage_spread_widening(CFG["stages"]["4"], raw, ASOF) is True


def test_spread_widening_float_precision_at_exact_boundary():
    # Real forensic values from the GFC graze: low 1.53 (2007-02-24), spike to 2.13
    # (2007-09-11). 2.13 - 1.53 is exactly +0.60 in the source data, but IEEE-754
    # float64 subtraction yields 0.5999999999999999 -- a naive `>=` comparison would
    # (wrongly) miss this real crossing. The epsilon tolerance must catch it.
    assert repr(2.13 - 1.53) == "0.5999999999999999"
    idx = days(300)
    vals = np.full(len(idx), 1.53)
    vals[-5] = 2.13
    vals[-4:] = 1.90                     # retraces, but still above the low
    raw = {"baa10y": pd.Series(vals, index=idx)}
    assert seq._stage_spread_widening(CFG["stages"]["4"], raw, ASOF) is True


def test_spread_widening_does_not_fire_when_the_high_precedes_the_low():
    # Ordering matters, not just range: the series falls steadily from a high to its
    # low (high-before-low) and never rebounds. The window's max-min range (1.20) far
    # exceeds widen(0.60), but since the widening never follows a trough, this must
    # NOT fire -- distinguishing the rule from a naive "range >= widen" check.
    idx = days(300)
    vals = np.linspace(2.20, 1.00, len(idx))     # strictly declining, low at asof
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


def test_price_confirmation_stale_sahm_treated_as_not_hot():
    idx = days(300)
    spx = pd.Series(np.linspace(5000, 4000, len(idx)), index=idx)   # below its 200dma
    # sahm reading is hot (>= level) but 80 days stale (> 75d bound) -> must be ignored;
    # vix is calm -> overall not fired despite the hot-looking sahm value.
    stale_sahm = {"spx": spx, "vixcls": pd.Series([12.0], index=[ASOF]),
                  "sahmrealtime": pd.Series([0.9], index=[ASOF - pd.Timedelta(days=80)])}
    assert seq._stage_price_confirmation(CFG["stages"]["6"], stale_sahm, ASOF) is False
    # same sahm value but fresh (74 days old, within the 75d bound) -> now counts as hot
    fresh_sahm = {"spx": spx, "vixcls": pd.Series([12.0], index=[ASOF]),
                  "sahmrealtime": pd.Series([0.9], index=[ASOF - pd.Timedelta(days=74)])}
    assert seq._stage_price_confirmation(CFG["stages"]["6"], fresh_sahm, ASOF) is True


def test_price_confirmation_stale_vix_treated_as_not_hot():
    idx = days(300)
    spx = pd.Series(np.linspace(5000, 4000, len(idx)), index=idx)   # below its 200dma
    # vix reading is hot but 15 days stale (> 10d bound) -> ignored; sahm calm -> False.
    stale_vix = {"spx": spx, "vixcls": pd.Series([35.0], index=[ASOF - pd.Timedelta(days=15)]),
                 "sahmrealtime": pd.Series([0.1], index=[ASOF - pd.Timedelta(days=40)])}
    assert seq._stage_price_confirmation(CFG["stages"]["6"], stale_vix, ASOF) is False
    # same vix value but fresh (9 days old, within the 10d bound) -> now counts as hot
    fresh_vix = {"spx": spx, "vixcls": pd.Series([35.0], index=[ASOF - pd.Timedelta(days=9)]),
                 "sahmrealtime": pd.Series([0.1], index=[ASOF - pd.Timedelta(days=40)])}
    assert seq._stage_price_confirmation(CFG["stages"]["6"], fresh_vix, ASOF) is True


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


def test_stage_breadth_divergence_near_high_within_past_month_not_just_today():
    # design §8b: "in past month" -- a pullback into the final observation shouldn't
    # erase a real divergence that was visible earlier within the last ~21 obs.
    cfg = {"index": "spx", "near_high_pct": 2.0, "high_lookback_days": 365, "breadth_low_days": 126}
    idx = days(300)
    vals = np.linspace(4000, 5000, len(idx))
    vals[-10:] = np.linspace(5000, 4700, 10)   # pulls back off the high in the final 10 obs
    spx = pd.Series(vals, index=idx)
    breadth_at_low = pd.Series(np.linspace(60, 10, len(idx)), index=idx)  # at its 126d low at asof
    raw = {"spx": spx}
    # asof (last) close is NOT within near_high_pct of the window max -- the old
    # "today only" check would return False here.
    assert vals[-1] < vals.max() * (1 - cfg["near_high_pct"] / 100.0)
    assert seq._stage_breadth_divergence(cfg, raw, breadth_at_low, ASOF) is True


def test_stage_breadth_divergence_near_high_too_long_ago_does_not_fire():
    # the near-high observation sits well outside the past-month (21 obs) recency
    # window -- must not fire even though the lookback-window max is technically real.
    cfg = {"index": "spx", "near_high_pct": 2.0, "high_lookback_days": 365, "breadth_low_days": 126}
    idx = days(300)
    vals = np.full(len(idx), 4000.0)
    vals[100] = 5000.0            # the 52wk high, ~200 obs before asof -- outside past month
    vals[-30:] = 4200.0           # last month sits well off that high
    spx = pd.Series(vals, index=idx)
    breadth_at_low = pd.Series(np.linspace(60, 10, len(idx)), index=idx)  # at its 126d low at asof
    raw = {"spx": spx}
    assert seq._stage_breadth_divergence(cfg, raw, breadth_at_low, ASOF) is False


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


def test_update_state_credit_path_engages_on_stages_3_and_4():
    # 1990-shape fixture: credit-led bear where only stages 3+4 fire, never reaching
    # the 2-of-1-3 gate. credit_path: true must engage via the stage-3-AND-4 path.
    spx = pd.Series(np.full(300, 5000.0), index=days(300))
    state = seq.new_state()
    fired = {1: False, 2: None, 3: True, 4: True, 5: False, 6: False}
    state = seq.update_state(state, fired, ASOF, spx, CFG)
    assert state["engaged"] is True
    assert state["current_stage"] == 4


def test_update_state_stage4_only_does_not_engage():
    spx = pd.Series(np.full(300, 5000.0), index=days(300))
    state = seq.new_state()
    fired = {1: False, 2: None, 3: False, 4: True, 5: False, 6: False}
    state = seq.update_state(state, fired, ASOF, spx, CFG)
    assert state["engaged"] is False
    assert state["current_stage"] == 0


def test_update_state_credit_path_gated_off_by_config():
    # same 3+4 shape as above, but credit_path: false -> the alternate gate must not apply.
    spx = pd.Series(np.full(300, 5000.0), index=days(300))
    state = seq.new_state()
    fired = {1: False, 2: None, 3: True, 4: True, 5: False, 6: False}
    state = seq.update_state(state, fired, ASOF, spx, CFG_NO_CREDIT_PATH)
    assert state["engaged"] is False


def test_update_state_credit_path_requires_concurrent_firing_not_residual_state():
    # 2019-shape fixture: stage 4 (Q4-2018 credit widening) sits in un-lapsed *residual*
    # state -- last_true exactly 92 days before asof (the lapse rule only lapses on
    # `> 92`, so this residue is technically still "active") -- but is NOT raw-true at
    # today's checkpoint. Stage 3 (curve resteepen) is freshly raw-true today. The old
    # fired-and-not-lapsed credit path would engage on this residual combination (the
    # actual Dec-2019 bug); the narrowed rule requires stages 3 AND 4 to be
    # *concurrently raw-true* at the same checkpoint, so this must NOT engage.
    spx = pd.Series(np.full(300, 5000.0), index=days(300))
    prev = seq.new_state()
    prev["stages"]["4"] = {
        "fired": True, "fired_date": "2018-11-30", "lapsed": False,
        "last_true": (ASOF - pd.Timedelta(days=92)).strftime("%Y-%m-%d"),
    }
    prev["stages"]["3"] = {
        "fired": True, "fired_date": "2019-06-30", "lapsed": False,
        "last_true": (ASOF - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
    }
    fired = {1: False, 2: False, 3: True, 4: False, 5: False, 6: False}
    state = seq.update_state(prev, fired, ASOF, spx, CFG)
    assert state["engaged"] is False
    assert state["current_stage"] == 0


def test_update_state_reset_on_drawdown():
    idx = days(300)
    vals = np.full(len(idx), 5000.0)
    vals[-10:] = 3800.0                                  # >20% below post-engagement high
    spx = pd.Series(vals, index=idx)
    state = seq.new_state()
    state = seq.update_state(state, {1: True, 2: True, 3: True, 4: True, 5: True, 6: True}, ASOF, spx, CFG)
    assert state["engaged"] is False                     # reset: crisis realized
    assert state["current_stage"] == 0
