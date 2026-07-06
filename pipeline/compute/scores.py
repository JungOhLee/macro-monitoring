from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from pipeline import paths, store
from pipeline.compute import percentiles as pctmod
from pipeline.compute.derived import asof_align, build_indicator_series
from pipeline.registry import Indicator, Registry

WINDOWS = ("full", "rolling20y")


@dataclass
class IndicatorResult:
    series: pd.Series
    froth_full: pd.Series
    froth_rolling: pd.Series
    zscore_latest: float | None
    frequency: str


@dataclass
class ScoreResult:
    composite: pd.DataFrame
    pillars: pd.DataFrame
    indicators: dict[str, IndicatorResult]


def indicator_frequency(ind: Indicator, reg: Registry) -> str:
    sid = ind.series if ind.series is not None else ind.inputs[0]
    return reg.series_by_id[sid].frequency


def regime_for(score: float, bands: list[dict]) -> str:
    for band in bands[:-1]:
        if score < band["upper"]:
            return band["name"]
    return bands[-1]["name"]


def compute_scores(
    reg: Registry, thresholds: dict, raw: dict[str, pd.Series], now: pd.Timestamp | None = None
) -> ScoreResult:
    if now is None:
        now = max(s.index.max() for s in raw.values() if not s.empty)
    start = pd.Timestamp(thresholds["score_start"])
    daily_index = pd.bdate_range(start, now)

    indicators: dict[str, IndicatorResult] = {}
    froth_daily: dict[str, dict[str, pd.Series]] = {}
    for ind in reg.indicators:
        try:
            series = build_indicator_series(ind, raw).dropna()
        except KeyError:
            continue
        if series.empty:
            continue
        freq = indicator_frequency(ind, reg)
        gate = pctmod.qualifying_mask(series)
        pf = pctmod.froth(pctmod.expanding_percentile(series)[gate], ind.direction)
        pr = pctmod.froth(pctmod.rolling20y_percentile(series, freq).dropna(), ind.direction)
        z = pctmod.expanding_zscore(series)
        indicators[ind.id] = IndicatorResult(
            series=series,
            froth_full=pf,
            froth_rolling=pr,
            zscore_latest=None if z.dropna().empty else float(z.dropna().iloc[-1]),
            frequency=freq,
        )
        if not pf.empty or not pr.empty:
            froth_daily[ind.id] = {
                "full": asof_align(daily_index, pf) if not pf.empty else pd.Series(index=daily_index, dtype=float),
                "rolling20y": asof_align(daily_index, pr) if not pr.empty else pd.Series(index=daily_index, dtype=float),
            }

    bands = thresholds["regime_bands"]
    weights = pd.Series(reg.pillar_weights, dtype=float)
    comp_rows, pillar_rows = [], []
    for window in WINDOWS:
        cols = {}
        for pillar in reg.pillar_weights:
            members = [
                froth_daily[i.id][window]
                for i in reg.indicators
                if i.pillar == pillar and i.id in froth_daily
            ]
            if members:
                cols[pillar] = pd.concat(members, axis=1).mean(axis=1)
        if not cols:
            continue
        pillar_df = pd.DataFrame(cols)
        avail_w = pillar_df.notna().mul(weights[pillar_df.columns], axis=1).sum(axis=1)
        comp = pillar_df.mul(weights[pillar_df.columns], axis=1).sum(axis=1) / avail_w
        comp = comp.dropna()
        for dt, val in comp.items():
            comp_rows.append({"date": dt, "window": window, "score": round(float(val), 2),
                              "regime": regime_for(float(val), bands)})
        stacked = pillar_df.stack().dropna().reset_index()
        stacked.columns = ["date", "pillar", "score"]
        for r in stacked.itertuples(index=False):
            pillar_rows.append({"date": r.date, "window": window, "pillar": r.pillar,
                                "score": round(float(r.score), 2)})

    return ScoreResult(
        composite=pd.DataFrame(comp_rows, columns=["date", "window", "score", "regime"]),
        pillars=pd.DataFrame(pillar_rows, columns=["date", "window", "pillar", "score"]),
        indicators=indicators,
    )


def _append(fp, df: pd.DataFrame, key_cols: list[str]) -> int:
    fp.parent.mkdir(parents=True, exist_ok=True)
    existed = fp.exists()
    if existed:
        existing = pd.read_csv(fp, parse_dates=["date"])
        last = existing["date"].max()
        new = df[df["date"] > last]
    else:
        new = df
    if new.empty:
        return 0
    out = new.copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out.to_csv(fp, mode="a", header=not existed, index=False)
    return len(new)


def append_scores(result: ScoreResult) -> tuple[int, int]:
    n_comp = _append(paths.DATA_SCORES / "composite.csv",
                     result.composite.sort_values(["date", "window"]), ["date", "window"])
    n_pil = _append(paths.DATA_SCORES / "pillars.csv",
                    result.pillars.sort_values(["date", "window", "pillar"]), ["date", "window", "pillar"])
    return n_comp, n_pil
