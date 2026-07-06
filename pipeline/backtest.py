from __future__ import annotations

import pandas as pd

from pipeline import paths, store
from pipeline.compute.analogs import top_analogs
from pipeline.compute.episodes import load_snapshots
from pipeline.compute.scores import compute_scores
from pipeline.compute.sequencer import evaluate_stages, new_state, update_state

REPLAY_START = "1987-01-30"

# Recalibrated 2026-07-06 (Phase 4 Task 4 -- demeaned analog cosine, see
# docs/superpowers/specs/2026-07-05-macro-monitor-design.md): the old 0.8 threshold
# predated demeaning `analogs.cosine` on the neutral (50th-percentile) midpoint. Under
# the OLD, non-demeaned cosine, all 474/474 replay months scored >=0.8 (the all-positive
# percentile vectors floor cosine near that range regardless of actual similarity) --
# the threshold discriminated nothing. Demeaning alone drops that to 300/474 months
# (103 inside pre-crisis windows, 197 outside) at the same 0.8 cut, still a weak signal.
# The new threshold is anchored to the empirical distribution instead of another guess:
# `monthly_top1_similarities()` over the full 1987-2026 replay (n=474 months) has
# median=0.8433, p75=0.9475, p90=0.9819 -- rounded to 2dp, its 90th percentile is 0.98.
ANALOG_HIGH_SIM_THRESHOLD = 0.98


def apply_lag(s: pd.Series, lag_days: int) -> pd.Series:
    out = s.copy()
    out.index = out.index + pd.Timedelta(days=lag_days)
    return out


def evaluate_criteria(stage: pd.Series, engaged: pd.Series, episodes: list[dict]) -> list[dict]:
    crits = []
    for ep in episodes:
        if ep.get("criterion") is False:
            continue
        peak = pd.Timestamp(ep["peak"])
        if ep.get("control"):
            window = engaged[(engaged.index >= "2019-01-01") & (engaged.index <= "2019-12-31")]
            ok = bool((~window).all()) if not window.empty else False
            crits.append({"name": "quiet through 2019 (covid control)", "pass": ok,
                          "detail": f"{int(window.sum())} engaged months in 2019"})
            continue
        pre = stage[(stage.index >= peak - pd.DateOffset(months=18)) & (stage.index <= peak)]
        ok = bool((pre >= 4).any()) if not pre.empty else False
        crits.append({"name": f"stage>=4 before {ep['id']} peak", "pass": ok,
                      "detail": f"max stage {int(pre.max()) if not pre.empty else -1} in T-18m..T"})
    return crits


def replay_monthly(reg, thresholds, raw, start: str = REPLAY_START):
    """Lag-shift `raw` to simulate publication-lag-adjusted history, compute scores
    once against the lagged series, then replay the sequencer monthly from `start`
    through the last available month-end. Returns (months, stage_s, engaged_s, state,
    result, lagged) where `state` is the final sequencer state after the last month
    in the replay."""
    lagged = {}
    lag_by_id = {s.id: s.lag_days for s in reg.series}
    for sid, s in raw.items():
        lagged[sid] = apply_lag(s, lag_by_id.get(sid, 0)) if not s.empty else s
    months = pd.date_range(start, max(s.index.max() for s in raw.values() if not s.empty), freq="BME")
    state = new_state()
    stages, engaged = [], []
    result = compute_scores(reg, thresholds, lagged)
    for m in months:
        fired = evaluate_stages(reg, thresholds, lagged, result, m)
        state = update_state(state, fired, m, lagged.get("spx"), thresholds["sequencer"])
        stages.append(state["current_stage"])
        engaged.append(state["engaged"])
    stage_s = pd.Series(stages, index=months)
    engaged_s = pd.Series(engaged, index=months)
    return months, stage_s, engaged_s, state, result, lagged


def monthly_top1_similarities(months, snaps: pd.DataFrame, froth: dict) -> list[float | None]:
    """For each month, the top-1 analog similarity (demeaned cosine, see
    `pipeline.compute.analogs.top_analogs`) against `snaps`; None where no analog
    qualifies that month (e.g. fewer than `min_shared` indicators available). Shared
    plumbing for both the base-rate count in `run_backtest` and, ad hoc, for deriving
    `ANALOG_HIGH_SIM_THRESHOLD` from the resulting distribution's quantiles."""
    sims: list[float | None] = []
    for m in months:
        vec = {i: float(f.asof(m)) for i, f in froth.items() if not pd.isna(f.asof(m))}
        top = top_analogs(vec, snaps, k=1)
        sims.append(top[0]["similarity"] if top else None)
    return sims


def run_backtest(reg, thresholds, raw, epi_cfg, start: str = REPLAY_START) -> dict:
    months, stage_s, engaged_s, _state, result, _lagged = replay_monthly(reg, thresholds, raw, start)

    comp = pd.read_csv(paths.DATA_SCORES / "composite.csv", parse_dates=["date"])
    comp = comp[comp.window == "full"].set_index("date")["score"]
    comp_m = comp.resample("BME").last().reindex(months)
    spx = raw["spx"].resample("BME").last().reindex(months)

    snaps = load_snapshots()
    n_high_out, n_high_in = 0, 0
    peaks = [pd.Timestamp(e["peak"]) for e in epi_cfg["episodes"] if not e.get("control")]
    if not snaps.empty:
        froth = {i: r.froth_full for i, r in result.indicators.items() if not r.froth_full.empty}
        sims = monthly_top1_similarities(months, snaps, froth)
        for m, sim in zip(months, sims):
            if sim is not None and sim >= ANALOG_HIGH_SIM_THRESHOLD:
                inside = any(p - pd.DateOffset(months=24) <= m <= p for p in peaks)
                n_high_in += inside
                n_high_out += not inside
    return {
        "months": [m.strftime("%Y-%m-%d") for m in months],
        "stage": [int(x) for x in stage_s],
        "engaged": [bool(x) for x in engaged_s],
        "composite": [None if pd.isna(v) else round(float(v), 2) for v in comp_m],
        "spx": [None if pd.isna(v) else round(float(v), 2) for v in spx],
        "episodes": epi_cfg["episodes"],
        "criteria": evaluate_criteria(stage_s, engaged_s, epi_cfg["episodes"]),
        "base_rate": {"threshold": ANALOG_HIGH_SIM_THRESHOLD, "n_high_outside": int(n_high_out),
                       "n_high_inside": int(n_high_in), "n_months": len(months)},
    }
