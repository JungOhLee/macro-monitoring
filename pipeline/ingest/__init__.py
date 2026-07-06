from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from pipeline import store
from pipeline.ingest.fred import fetch_fred
from pipeline.ingest.shiller import fetch_shiller
from pipeline.ingest.yahoo import fetch_yahoo
from pipeline.registry import Registry


def run_ingest(reg: Registry, api_key: str, now: pd.Timestamp | None = None) -> dict:
    now = now or pd.Timestamp(datetime.now(timezone.utc).date())
    fresh = store.load_freshness()
    for s in reg.series:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if s.source == "manual":
            stored = store.read_series(s.id)
            fresh[s.id] = {
                "last_fetch": stamp, "fetch_ok": True,
                "last_obs": stored.index.max().strftime("%Y-%m-%d") if not stored.empty else None,
                "error": None,
            }
            continue
        try:
            if s.source == "fred":
                fetched = fetch_fred(s.source_id, api_key)
            elif s.source == "yahoo":
                fetched = fetch_yahoo(s.source_id)
            else:
                fetched = fetch_shiller(s.source_id)
            existing = store.read_series(s.id)
            merged, changed = store.merge_observations(existing, fetched, s.revision_window_days)
            if changed:
                store.write_series(s.id, merged)
            fresh[s.id] = {
                "last_fetch": stamp,
                "fetch_ok": True,
                "last_obs": merged.index.max().strftime("%Y-%m-%d"),
                "error": None,
            }
        except Exception as exc:  # per-series isolation: one failure never aborts the run
            err = f"{type(exc).__name__}: {exc}"
            if api_key:
                # freshness.json is committed to a public repo — never persist the key
                err = err.replace(api_key, "***")
            prev = fresh.get(s.id, {})
            try:
                stored = store.read_series(s.id)
                fallback = stored.index.max().strftime("%Y-%m-%d") if not stored.empty else None
            except Exception:
                fallback = None
            fresh[s.id] = {
                "last_fetch": stamp,
                "fetch_ok": False,
                "last_obs": prev.get("last_obs") or fallback,
                "error": err,
            }
    store.save_freshness(fresh)
    return fresh


def stale_series(reg: Registry, freshness: dict, now: pd.Timestamp) -> list[str]:
    out = []
    for s in reg.series:
        rec = freshness.get(s.id)
        if rec is None or rec["last_obs"] is None:
            out.append(s.id)
            continue
        age = (now - pd.Timestamp(rec["last_obs"])).days
        if age > s.staleness_budget_days:
            out.append(s.id)
    return out
