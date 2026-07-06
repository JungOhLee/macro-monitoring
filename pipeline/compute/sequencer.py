from __future__ import annotations

import json

import pandas as pd

from pipeline import paths

STAGE_IDS = (1, 2, 3, 4, 5, 6)

RECENT_OBS_DAYS = 21     # "within the past month" per design §8b -- ~1 trading month of observations
SAHM_MAX_AGE_DAYS = 75   # Sahm real-time updates ~monthly; beyond this the reading is stale -> not-hot
VIX_MAX_AGE_DAYS = 10    # VIX should refresh ~daily; beyond this the reading is stale -> not-hot


def _win(s: pd.Series, asof: pd.Timestamp, days: int) -> pd.Series:
    s = s[s.index <= asof]
    return s[s.index >= asof - pd.Timedelta(days=days)]


def _stage_pillar_above(cfg, pillars_full: pd.Series, asof) -> bool | None:
    """pillars_full: daily full-window score series for the configured pillar."""
    if pillars_full is None or pillars_full.empty:
        return None
    w = _win(pillars_full, asof, cfg["min_days"] * 2)
    if len(w) < cfg["min_days"]:
        return None
    return bool((w.tail(cfg["min_days"]) > cfg["level"]).all())


def _stage_froth_rollover(cfg, froth: pd.Series, asof) -> bool | None:
    if froth is None or froth.empty:
        return None
    w = _win(froth, asof, cfg["lookback_days"])
    if w.empty:
        return None
    if w.max() <= cfg["level"]:
        return False
    tail = w.tail(cfg["decline_obs"] + 1)
    if len(tail) < cfg["decline_obs"] + 1:
        return False
    return bool(tail.is_monotonic_decreasing and tail.iloc[-1] < w.max())


def _stage_curve_resteepen(cfg, raw: dict, asof) -> bool | None:
    s = raw.get(cfg["series"])
    if s is None or s.empty:
        return None
    w = _win(s, asof, cfg["lookback_days"])
    if w.empty:
        return None
    inverted_days = int((w < 0).sum())
    now = w.iloc[-1]
    return bool(inverted_days >= cfg["min_inverted_days"] and now > cfg["resteepen_level"])


def _stage_spread_widening(cfg, raw: dict, asof) -> bool | None:
    s = raw.get(cfg["series"])
    if s is None or s.empty:
        return None
    w = _win(s, asof, cfg["low_lookback_days"])
    if w.empty:
        return None
    # Intra-window, order-aware: fire if at ANY point in the window the series has
    # widened >= `widen` off its running (cumulative) minimum-to-date -- a trough
    # followed by a later spike -- evaluated across all observations in the window,
    # not just the final one. Forensic basis: GFC's Baa-10Y spread crossed +60bp off
    # its trailing low intra-month on 2007-09-10/11, then narrowed back before the
    # month-end snapshot; a last-value-vs-window-min check misses that graze entirely.
    # Ordering matters, not just range: a value preceding the window's eventual low
    # does not count, since `cummin` only reflects the minimum seen so far.
    # 1e-9 epsilon guards the boundary against float subtraction noise (e.g. the
    # real 2007-09-11 GFC graze is 2.13 - 1.53, exactly +0.60 in the source data,
    # but represents as 0.5999999999999999 in IEEE-754 float64) -- same pattern
    # already used for the breadth-divergence low-tie check below.
    m = w.cummin()
    return bool(((w - m) >= cfg["widen"] - 1e-9).any())


def _stage_breadth_divergence(cfg, raw: dict, breadth_raw: pd.Series | None, asof) -> bool | None:
    idx_s = raw.get(cfg["index"])
    if idx_s is None or idx_s.empty or breadth_raw is None or breadth_raw.empty:
        return None
    w = _win(idx_s, asof, cfg["high_lookback_days"])
    b = _win(breadth_raw, asof, cfg["breadth_low_days"])
    if w.empty or b.empty:
        return None
    # design §8b: "within 2% of 52-week high in past month" -- test the past
    # RECENT_OBS_DAYS observations against the lookback max, not just the asof close,
    # so a pullback into the final observation doesn't erase a real divergence.
    recent = w.tail(RECENT_OBS_DAYS)
    near_high = bool((recent >= w.max() * (1 - cfg["near_high_pct"] / 100.0)).any())
    breadth_at_low = b.iloc[-1] <= b.min() + 1e-9
    return bool(near_high and breadth_at_low)


def _stage_price_confirmation(cfg, raw: dict, asof) -> bool | None:
    idx_s = raw.get(cfg["index"])
    if idx_s is None or len(idx_s[idx_s.index <= asof]) < cfg["dma_days"]:
        return None
    upto = idx_s[idx_s.index <= asof]
    below_dma = upto.iloc[-1] < upto.rolling(cfg["dma_days"]).mean().iloc[-1]

    def _fresh_and_hot(s: pd.Series | None, level: float, max_age_days: int) -> bool:
        # Staleness bound: an input older than its max age at asof carries no current
        # signal -- treated as not-hot (not as missing/None), so a stalled Sahm or VIX
        # feed can't silently keep confirming a stage-6 "hot" condition indefinitely.
        if s is None:
            return False
        s = s[s.index <= asof]
        if s.empty:
            return False
        age_days = (asof - s.index[-1]).days
        if age_days > max_age_days:
            return False
        return bool(s.iloc[-1] >= level)

    sahm_hot = _fresh_and_hot(raw.get(cfg["sahm_series"]), cfg["sahm_level"], SAHM_MAX_AGE_DAYS)
    vix_hot = _fresh_and_hot(raw.get(cfg["vix_series"]), cfg["vix_level"], VIX_MAX_AGE_DAYS)
    return bool(below_dma and (sahm_hot or vix_hot))


def evaluate_stages(reg, thresholds, raw, result, asof) -> dict[int, bool | None]:
    cfg = thresholds["sequencer"]["stages"]
    pillars_full = None
    if result is not None:
        pf = result.pillars[(result.pillars.window == "full")
                            & (result.pillars.pillar == cfg["1"]["pillar"])]
        if not pf.empty:
            pillars_full = pf.set_index("date")["score"]
    froth = None
    if result is not None and cfg["2"]["indicator"] in result.indicators:
        froth = result.indicators[cfg["2"]["indicator"]].froth_full
    breadth = None
    if result is not None and cfg["5"]["breadth"] in result.indicators:
        breadth = result.indicators[cfg["5"]["breadth"]].series
    return {
        1: _stage_pillar_above(cfg["1"], pillars_full, asof),
        2: _stage_froth_rollover(cfg["2"], froth, asof),
        3: _stage_curve_resteepen(cfg["3"], raw, asof),
        4: _stage_spread_widening(cfg["4"], raw, asof),
        5: _stage_breadth_divergence(cfg["5"], raw, breadth, asof),
        6: _stage_price_confirmation(cfg["6"], raw, asof),
    }


def new_state() -> dict:
    return {"as_of": None, "engaged": False, "current_stage": 0,
            "stages": {str(n): {"fired": None, "fired_date": None, "lapsed": False, "last_true": None}
                        for n in STAGE_IDS}}


def update_state(prev: dict, fired: dict[int, bool | None], asof: pd.Timestamp,
                 spx: pd.Series, cfg: dict) -> dict:
    state = json.loads(json.dumps(prev))  # deep copy
    date_s = asof.strftime("%Y-%m-%d")
    state["as_of"] = date_s
    for n in STAGE_IDS:
        st = state["stages"][str(n)]
        f = fired.get(n)
        if f is True:
            if st["fired"] is not True or st["lapsed"]:
                st["fired"], st["fired_date"], st["lapsed"] = True, date_s, False
            st["last_true"] = date_s
        elif f is False:
            if st["fired"] is None:
                st["fired"] = False
            if st["fired"] is True and st["last_true"]:
                gap = (asof - pd.Timestamp(st["last_true"])).days
                if gap > cfg["lapse_days"]:
                    st["lapsed"] = True
        # f is None -> leave state untouched (no data)
    active = [n for n in STAGE_IDS
              if state["stages"][str(n)]["fired"] is True and not state["stages"][str(n)]["lapsed"]]
    early = [n for n in active if n <= 3]
    # Credit path (design §8a/8b amendment, 2026-07-06): credit-led bears can satisfy
    # stage 3 (curve resteepen) AND stage 4 (credit spread widening) without ever
    # tripping the "2 of stages 1-3" gate. Requires stages 3 and 4 to be CONCURRENTLY
    # raw-true at the same checkpoint (the `fired` dict), not merely fired-and-not-lapsed
    # state -- 1990 evidence: concurrent Jan-Apr 1990 (stage 4 live since May 1989).
    # Un-lapsed *residual* state was rejected as the trigger: it let the Q4-2018 spread
    # widening's residue (exactly-92-day gap vs. the >92 lapse rule) combine with the
    # one-month Dec-2019 curve resteepen to falsely engage. Consequence: credit-path
    # engagement persists only while both conditions stay live, not merely un-lapsed.
    credit_engaged = bool(cfg.get("credit_path")) and fired.get(3) is True and fired.get(4) is True
    state["engaged"] = (len(early) >= cfg["engaged_min_stages"]) or credit_engaged
    state["current_stage"] = max(active) if state["engaged"] and active else 0
    # reset: crisis realized (drawdown from 12m high beyond threshold)
    if state["engaged"] and spx is not None and not spx.empty:
        w = _win(spx, asof, 365)
        if not w.empty and w.iloc[-1] <= w.max() * (1 - cfg["reset_drawdown_pct"] / 100.0):
            for n in STAGE_IDS:
                state["stages"][str(n)]["lapsed"] = True
            state["engaged"] = False
            state["current_stage"] = 0
    return state


def load_state() -> dict:
    fp = paths.DATA_STATE / "sequence_state.json"
    if not fp.exists():
        return new_state()
    return json.loads(fp.read_text())


def save_state(state: dict) -> None:
    paths.DATA_STATE.mkdir(parents=True, exist_ok=True)
    (paths.DATA_STATE / "sequence_state.json").write_text(json.dumps(state, indent=1) + "\n")
