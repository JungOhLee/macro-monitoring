from __future__ import annotations

import json

import pandas as pd

from pipeline import paths

STAGE_IDS = (1, 2, 3, 4, 5, 6)


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
    return bool(w.iloc[-1] >= w.min() + cfg["widen"])


def _stage_breadth_divergence(cfg, raw: dict, breadth_raw: pd.Series | None, asof) -> bool | None:
    idx_s = raw.get(cfg["index"])
    if idx_s is None or idx_s.empty or breadth_raw is None or breadth_raw.empty:
        return None
    w = _win(idx_s, asof, cfg["high_lookback_days"])
    b = _win(breadth_raw, asof, cfg["breadth_low_days"])
    if w.empty or b.empty:
        return None
    near_high = w.iloc[-1] >= w.max() * (1 - cfg["near_high_pct"] / 100.0)
    breadth_at_low = b.iloc[-1] <= b.min() + 1e-9
    return bool(near_high and breadth_at_low)


def _stage_price_confirmation(cfg, raw: dict, asof) -> bool | None:
    idx_s = raw.get(cfg["index"])
    if idx_s is None or len(idx_s[idx_s.index <= asof]) < cfg["dma_days"]:
        return None
    upto = idx_s[idx_s.index <= asof]
    below_dma = upto.iloc[-1] < upto.rolling(cfg["dma_days"]).mean().iloc[-1]
    sahm = raw.get(cfg["sahm_series"])
    vix = raw.get(cfg["vix_series"])
    sahm_hot = (sahm is not None and not sahm[sahm.index <= asof].empty
                and sahm[sahm.index <= asof].iloc[-1] >= cfg["sahm_level"])
    vix_hot = (vix is not None and not vix[vix.index <= asof].empty
               and vix[vix.index <= asof].iloc[-1] >= cfg["vix_level"])
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
    state["engaged"] = len(early) >= cfg["engaged_min_stages"]
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
