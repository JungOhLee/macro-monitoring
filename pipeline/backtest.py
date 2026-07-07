from __future__ import annotations

import pandas as pd

from pipeline import paths, store
from pipeline.compute.analogs import froth_vectors, top_analogs
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


def forward_returns(spx_m: pd.Series, horizon_months: int) -> list[float | None]:
    """Simple S&P price return over the next `horizon_months` entries of a monthly
    (BME-indexed) series, as percent x100 rounded to 2dp; None where the horizon runs
    past the end of the data or either endpoint is missing. Positional shift, not
    calendar arithmetic -- the input is already one row per month-end."""
    arr = spx_m.to_numpy(dtype=float)
    out: list[float | None] = []
    for i in range(len(arr)):
        j = i + horizon_months
        if j >= len(arr) or pd.isna(arr[i]) or pd.isna(arr[j]):
            out.append(None)
        else:
            out.append(round((arr[j] / arr[i] - 1.0) * 100.0, 2))
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


def _months_between(a: pd.Timestamp, b: pd.Timestamp) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def build_report_card(stage: pd.Series, engaged: pd.Series, spx_m: pd.Series,
                      episodes: list[dict]) -> list[dict]:
    """One JSON-ready row per scored episode: when the tracker first engaged / first
    reached stage 4 inside the peak-24m..peak window, the lead time that gave, and what
    the market then did (peak-to-trough on monthly closes, trough within 36 months).
    The covid control row reports engaged-months-in-2019 instead of lead times.
    Episodes with criterion: false are excluded, same rule as evaluate_criteria."""
    rows = []
    for ep in episodes:
        if ep.get("criterion") is False:
            continue
        peak = pd.Timestamp(ep["peak"])
        base = {"episode": ep["id"], "name": ep.get("name", ep["id"]), "peak": ep["peak"],
                "control": bool(ep.get("control", False)), "first_engaged": None,
                "first_stage4": None, "lead_months": None, "max_drawdown_pct": None,
                "months_to_trough": None, "engaged_months": None,
                "note": ep.get("report_note", "")}
        if ep.get("control"):
            window = engaged[(engaged.index >= "2019-01-01") & (engaged.index <= "2019-12-31")]
            base["engaged_months"] = int(window.sum())
            rows.append(base)
            continue
        in_win = (stage.index >= peak - pd.DateOffset(months=24)) & (stage.index <= peak)
        eng_dates = engaged.index[in_win & engaged.to_numpy(dtype=bool)]
        st4_dates = stage.index[in_win & (stage.to_numpy() >= 4)]
        if len(eng_dates):
            base["first_engaged"] = eng_dates[0].strftime("%Y-%m-%d")
        if len(st4_dates):
            base["first_stage4"] = st4_dates[0].strftime("%Y-%m-%d")
            base["lead_months"] = _months_between(st4_dates[0], peak)
        at_peak = spx_m[spx_m.index <= peak].dropna()
        after = spx_m[(spx_m.index > peak) & (spx_m.index <= peak + pd.DateOffset(months=36))].dropna()
        if not at_peak.empty and not after.empty:
            level = float(at_peak.iloc[-1])
            trough_date = after.idxmin()
            base["max_drawdown_pct"] = round((float(after.min()) / level - 1.0) * 100.0, 1)
            base["months_to_trough"] = _months_between(peak, trough_date)
        rows.append(base)
    return rows


def run_backtest(reg, thresholds, raw, epi_cfg, start: str = REPLAY_START) -> dict:
    months, stage_s, engaged_s, _state, result, _lagged = replay_monthly(reg, thresholds, raw, start)

    comp = pd.read_csv(paths.DATA_SCORES / "composite.csv", parse_dates=["date"])
    comp = comp[comp.window == "full"].set_index("date")["score"]
    comp_m = comp.resample("BME").last().reindex(months)
    spx = raw["spx"].resample("BME").last().reindex(months)

    ff = raw.get("fedfunds")
    ff_m = (ff.resample("BME").last().reindex(months)
            if ff is not None and not ff.empty else pd.Series(index=months, dtype=float))

    snaps = load_snapshots()
    n_high_out, n_high_in = 0, 0
    peaks = [pd.Timestamp(e["peak"]) for e in epi_cfg["episodes"] if not e.get("control")]
    if not snaps.empty:
        # context (display-only) indicators are excluded from every monthly analog
        # vector, same as from episode snapshots and today's live vector.
        froth = froth_vectors(reg, result)
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
        "regime_bands": thresholds["regime_bands"],
        "fedfunds": [None if pd.isna(v) else round(float(v), 2) for v in ff_m],
        "fwd_6m": forward_returns(spx, 6),
        "fwd_12m": forward_returns(spx, 12),
        "fwd_24m": forward_returns(spx, 24),
        "base_rate": {"threshold": ANALOG_HIGH_SIM_THRESHOLD, "n_high_outside": int(n_high_out),
                       "n_high_inside": int(n_high_in), "n_months": len(months)},
        "report_card": build_report_card(stage_s, engaged_s, spx, epi_cfg["episodes"]),
    }
