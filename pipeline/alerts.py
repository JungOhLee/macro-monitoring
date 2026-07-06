from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

import pandas as pd

from pipeline import paths, store
from pipeline.ingest import stale_series
from pipeline.registry import Registry


@dataclass
class Alert:
    label: str
    title: str
    body: str


def _last_two(df: pd.DataFrame, value_col: str) -> tuple:
    d = df.sort_values("date")
    if len(d) < 2:
        return (None, None)
    return d.iloc[-2][value_col], d.iloc[-1][value_col]


def evaluate_alerts(reg: Registry, thresholds: dict, now: pd.Timestamp) -> list[Alert]:
    out: list[Alert] = []
    comp_fp = paths.DATA_SCORES / "composite.csv"
    pil_fp = paths.DATA_SCORES / "pillars.csv"
    level = thresholds["alerts"]["pillar_extreme_level"]

    if comp_fp.exists():
        comp = pd.read_csv(comp_fp, parse_dates=["date"])
        comp = comp[comp.window == "full"]
        prev, cur = _last_two(comp, "regime")
        if prev is not None and prev != cur:
            score = comp.sort_values("date").iloc[-1]["score"]
            out.append(Alert(
                "alert:regime",
                f"Regime change: {prev} -> {cur} (composite {score})",
                f"Full-window composite moved from **{prev}** to **{cur}** "
                f"(score {score}). Dashboard: https://jungohlee.github.io/macro-monitoring/",
            ))

    if pil_fp.exists():
        pil = pd.read_csv(pil_fp, parse_dates=["date"])
        pil = pil[pil.window == "full"]
        for pillar, grp in pil.groupby("pillar"):
            prev, cur = _last_two(grp, "score")
            if prev is not None and prev <= level < cur:
                out.append(Alert(
                    f"alert:pillar-{pillar}",
                    f"Pillar extreme: {pillar} crossed {level} (now {cur})",
                    f"The **{pillar}** pillar score crossed above {level}: {prev} -> {cur}.",
                ))

    freshness = store.load_freshness()
    stale = stale_series(reg, freshness, now)
    total = len(freshness)
    ok = sum(1 for rec in freshness.values() if rec.get("fetch_ok"))
    fetch_failed: list[str] = []
    if total and ok / total < 0.8:
        fetch_failed = sorted(sid for sid, rec in freshness.items() if not rec.get("fetch_ok"))

    if stale or fetch_failed:
        title_parts, body_parts = [], []
        if stale:
            title_parts.append(f"{len(stale)} stale series")
            body_parts.append("Series past their staleness budget: " + ", ".join(stale))
        if fetch_failed:
            title_parts.append(f"only {ok}/{total} fetch attempts succeeded")
            body_parts.append(
                f"Data health: only {ok}/{total} fetch attempts succeeded. "
                "Failed series: " + ", ".join(fetch_failed)
            )
        out.append(Alert(
            "data-health",
            "Data health: " + "; ".join(title_parts),
            "\n".join(body_parts),
        ))
    return out


def deliver(alerts: list[Alert], cooldown_days: int) -> int:
    in_ci = bool(os.environ.get("GITHUB_ACTIONS"))
    since = (pd.Timestamp.now(tz="UTC").tz_localize(None) - pd.Timedelta(days=cooldown_days)).strftime("%Y-%m-%d")
    failed = 0
    for a in alerts:
        if not in_ci:
            print(f"[alert] {a.label}: {a.title}\n        {a.body}")
            continue
        listed = subprocess.run(
            ["gh", "issue", "list", "--label", a.label, "--state", "all",
             "--search", f"created:>={since}", "--json", "number"],
            capture_output=True, text=True, check=False,
        )
        # Fail-closed: if list fails or JSON parse fails, skip create
        if listed.returncode != 0:
            print(f"[alert] cooldown check failed for {a.label}, skipping create (fail-closed)")
            continue
        try:
            recent = json.loads(listed.stdout or "[]")
        except json.JSONDecodeError:
            print(f"[alert] cooldown check failed for {a.label}, skipping create (fail-closed)")
            continue
        if recent:
            print(f"[alert] cooldown active for {a.label}, skipping")
            continue
        result = subprocess.run(
            ["gh", "issue", "create", "--title", a.title, "--body", a.body, "--label", a.label],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            print(f"[alert] FAILED to create issue for {a.label}: {result.stderr.strip()[:200]}")
            failed += 1
        else:
            print(f"[alert] issue created: {a.label}: {a.title}")
    return failed if in_ci else 0
