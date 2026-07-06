from __future__ import annotations

import pandas as pd

from pipeline import paths
from pipeline.compute.scores import compute_scores
from pipeline.registry import Registry, context_ids


def build_snapshots(reg: Registry, thresholds: dict, raw: dict, epi_cfg: dict) -> pd.DataFrame:
    result = compute_scores(reg, thresholds, raw)
    ctx = context_ids(reg)
    rows = []
    for ep in epi_cfg["episodes"]:
        if ep.get("library") is False:
            continue
        peak = pd.Timestamp(ep["peak"])
        for off in epi_cfg["offsets_months"]:
            snap_date = peak + pd.DateOffset(months=off)
            for ind_id, ir in result.indicators.items():
                if ind_id in ctx:
                    continue  # context (display-only) indicators never enter the episode library
                if ir.froth_full.empty:
                    continue
                val = ir.froth_full.asof(snap_date)
                if pd.isna(val):
                    continue  # exclusion, never zero-fill
                rows.append({"episode": ep["id"], "offset_months": off,
                             "indicator_id": ind_id, "percentile": round(float(val), 2)})
    return pd.DataFrame(rows, columns=["episode", "offset_months", "indicator_id", "percentile"])


def pillar_scores_from_snapshots(reg: Registry, snaps: pd.DataFrame) -> pd.DataFrame:
    roles = {i.id: i.role for i in reg.indicators}
    pillars = {i.id: i.pillar for i in reg.indicators}
    df = snaps[snaps.indicator_id.map(roles).ne("confirmation")].copy()
    df["pillar"] = df.indicator_id.map(pillars)
    out = (df.groupby(["episode", "offset_months", "pillar"])["percentile"]
             .mean().round(2).reset_index().rename(columns={"percentile": "score"}))
    return out


def firing_timeline(snaps: pd.DataFrame, level: float = 80) -> pd.DataFrame:
    hot = snaps[snaps.percentile >= level]
    out = (hot.groupby(["episode", "indicator_id"])["offset_months"]
              .min().reset_index().rename(columns={"offset_months": "first_offset"}))
    return out.sort_values(["first_offset", "indicator_id"]).reset_index(drop=True)


def save_snapshots(snaps: pd.DataFrame) -> None:
    fp = paths.DATA / "snapshots" / "episode_snapshots.csv"
    fp.parent.mkdir(parents=True, exist_ok=True)
    snaps.to_csv(fp, index=False)


def load_snapshots() -> pd.DataFrame:
    fp = paths.DATA / "snapshots" / "episode_snapshots.csv"
    if not fp.exists():
        return pd.DataFrame(columns=["episode", "offset_months", "indicator_id", "percentile"])
    return pd.read_csv(fp)
