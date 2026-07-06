from __future__ import annotations

import json
import math

import pandas as pd

from pipeline import paths, store
from pipeline.compute.scores import compute_scores, regime_for
from pipeline.ingest import stale_series
from pipeline.registry import Registry


def downsample(s: pd.Series, max_points: int = 1000) -> pd.Series:
    if len(s) <= max_points:
        return s
    step = math.ceil(len(s) / max_points)
    keep = s.iloc[::step]
    if keep.index[-1] != s.index[-1]:
        keep = pd.concat([keep.iloc[: max_points - 1], s.iloc[[-1]]])
    return keep


def _r(x, nd=4):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)


def _series_json(s: pd.Series, max_points: int = 1000) -> dict:
    ds = downsample(s.dropna(), max_points)
    return {"dates": [d.strftime("%Y-%m-%d") for d in ds.index],
            "values": [_r(v) for v in ds.to_numpy()]}


def _atomic_write(fp, obj) -> None:
    fp.parent.mkdir(parents=True, exist_ok=True)
    tmp = fp.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n")
    tmp.replace(fp)


def export_site(reg: Registry, thresholds: dict) -> dict:
    raw = {s.id: store.read_series(s.id) for s in reg.series}
    result = compute_scores(reg, thresholds, raw)
    as_of = max(s.index.max() for s in raw.values() if not s.empty)
    fresh = store.load_freshness()
    # Offline fallback: only backfill when freshness.json is entirely empty
    # (true offline case). When freshness.json exists and is non-empty, use it as-is.
    if not fresh:
        for s in reg.series:
            r = raw.get(s.id)
            fresh[s.id] = {
                "last_obs": r.index.max().strftime("%Y-%m-%d") if r is not None and not r.empty else None,
            }
    stale = set(stale_series(reg, fresh, as_of))

    # ---- latest.json ----
    comp = {}
    for window in ("full", "rolling20y"):
        rows = result.composite[result.composite.window == window]
        comp[window] = None if rows.empty else {
            "date": rows.iloc[-1]["date"].strftime("%Y-%m-%d"),
            "score": _r(rows.iloc[-1]["score"], 2),
            "regime": rows.iloc[-1]["regime"],
        }
    stress_bands = thresholds["stress_bands"]
    stress = {}
    for window in ("full", "rolling20y"):
        rows = result.stress[result.stress.window == window]
        if rows.empty:
            stress[window] = None
            continue
        val = float(rows.sort_values("date").iloc[-1]["score"])
        stress[window] = {"score": _r(val, 2), "label": regime_for(val, stress_bands)}

    pillars = {}
    per_pillar_total = {p: sum(1 for i in reg.indicators if i.pillar == p and i.role != "confirmation")
                        for p in reg.pillar_weights}
    per_pillar_active = {p: 0 for p in reg.pillar_weights}
    for ind in reg.indicators:
        r = result.indicators.get(ind.id)
        if ind.role != "confirmation" and r is not None and not r.froth_full.empty:
            per_pillar_active[ind.pillar] += 1
    for p, w in reg.pillar_weights.items():
        rows = result.pillars[(result.pillars.pillar == p)]
        entry = {"weight": w, "partial": per_pillar_active[p] < per_pillar_total[p]}
        for window in ("full", "rolling20y"):
            wr = rows[rows.window == window].sort_values("date")
            entry[window] = _r(wr.iloc[-1]["score"], 2) if not wr.empty else None
        full_rows = rows[rows.window == "full"].sort_values("date")
        for label, nback in (("delta_1m", 21), ("delta_3m", 63)):
            entry[label] = (
                _r(full_rows.iloc[-1]["score"] - full_rows.iloc[-1 - nback]["score"], 2)
                if len(full_rows) > nback else None
            )
        pillars[p] = entry
    latest = {
        "as_of": as_of.strftime("%Y-%m-%d"),
        "composite": comp,
        "stress": stress,
        "pillars": pillars,
        "analogs": None,
        "sequence": None,
        "freshness": {
            s.id: {"last_obs": (raw[s.id].index.max().strftime("%Y-%m-%d") if not raw[s.id].empty else None),
                    "stale": s.id in stale}
            for s in reg.series
        },
    }

    # ---- history.json (weekly downsample) ----
    history: dict = {
        "episode_peaks": thresholds.get("episode_peaks", []),
        "regime_bands": thresholds["regime_bands"],
    }
    for window in ("full", "rolling20y"):
        cw = result.composite[result.composite.window == window].set_index("date")
        if cw.empty:
            continue
        weekly = cw["score"].resample("W-FRI").last().dropna()
        pw = {}
        for p in reg.pillar_weights:
            rows = result.pillars[(result.pillars.window == window) & (result.pillars.pillar == p)]
            if rows.empty:
                continue
            aligned = rows.set_index("date")["score"].resample("W-FRI").last().reindex(weekly.index)
            pw[p] = [_r(v, 2) for v in aligned.to_numpy()]
        history[window] = {
            "dates": [d.strftime("%Y-%m-%d") for d in weekly.index],
            "composite": [_r(v, 2) for v in weekly.to_numpy()],
            "pillars": pw,
        }
        srows = result.stress[result.stress.window == window]
        if not srows.empty:
            saligned = srows.set_index("date")["score"].resample("W-FRI").last().reindex(weekly.index)
            history[window]["stress"] = [_r(v, 2) for v in saligned.to_numpy()]

    # ---- indicators.json ----
    indicators = {}
    for ind in reg.indicators:
        r = result.indicators.get(ind.id)
        if r is None:
            continue
        backing = ind.series if ind.series is not None else ind.inputs[0]
        indicators[ind.id] = {
            "name": ind.name, "pillar": ind.pillar, "role": ind.role,
            "direction": ind.direction, "frequency": r.frequency,
            "last_obs": r.series.index.max().strftime("%Y-%m-%d"),
            "stale": backing in stale,
            "latest": {
                "value": _r(r.series.iloc[-1]),
                "pct_full": _r(r.froth_full.iloc[-1], 2) if not r.froth_full.empty else None,
                "pct_rolling": _r(r.froth_rolling.iloc[-1], 2) if not r.froth_rolling.empty else None,
                "zscore": _r(r.zscore_latest, 2),
            },
            "series": _series_json(r.series),
            "pct_series": _series_json(r.froth_full),
        }

    _atomic_write(paths.SITE_DATA / "latest.json", latest)
    _atomic_write(paths.SITE_DATA / "history.json", history)
    _atomic_write(paths.SITE_DATA / "indicators.json", indicators)
    return latest


EPISODE_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} - Macro Bubble Monitor</title>
<link rel="stylesheet" href="../assets/style.css"></head>
<body><header><h1><a href="../index.html" style="text-decoration:none;color:inherit">&larr; Macro Bubble Monitor</a></h1></header>
<article class="card">{body}</article>
<footer class="muted">Monitoring context, not a trading signal.</footer>
</body></html>
"""


def render_episodes() -> list[str]:
    import markdown

    outdir = paths.SITE / "episodes"
    names = []
    for md_file in sorted(paths.EPISODES.glob("*.md")):
        text = md_file.read_text()
        title = text.splitlines()[0].lstrip("# ").strip()
        body = markdown.markdown(text)
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / f"{md_file.stem}.html").write_text(
            EPISODE_TEMPLATE.format(title=title, body=body))
        names.append(md_file.stem)
    return names
