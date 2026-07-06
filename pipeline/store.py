from __future__ import annotations

import json

import pandas as pd

from pipeline import paths


def read_series(series_id: str) -> pd.Series:
    fp = paths.DATA_RAW / f"{series_id}.csv"
    if not fp.exists():
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]), name=series_id)
    df = pd.read_csv(fp, parse_dates=["date"])
    idx = pd.DatetimeIndex(df["date"].values)
    s = pd.Series(df["value"].to_numpy(dtype=float), index=idx, name=series_id)
    return s.sort_index()


def write_series(series_id: str, s: pd.Series) -> None:
    paths.DATA_RAW.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({"date": s.index.strftime("%Y-%m-%d"), "value": s.to_numpy()})
    df.to_csv(paths.DATA_RAW / f"{series_id}.csv", index=False)


def merge_observations(
    existing: pd.Series, fetched: pd.Series, revision_window_days: int
) -> tuple[pd.Series, int]:
    """Append-mostly merge. New dates are appended; dates within
    revision_window_days of the last stored observation may be rewritten;
    older stored values are kept even if the source restates them.
    Stored rows are never deleted."""
    fetched = fetched.dropna().sort_index()
    if existing.empty:
        fetched = fetched.copy()
        fetched.name = existing.name or fetched.name
        return fetched, len(fetched)
    cutoff = existing.index.max() - pd.Timedelta(days=revision_window_days)
    merged = existing.copy()
    changed = 0
    for dt, val in fetched.items():
        if dt in merged.index:
            if dt >= cutoff and merged[dt] != val:
                merged[dt] = val
                changed += 1
        elif dt > existing.index.max() or dt >= cutoff:
            merged[dt] = val
            changed += 1
        # dates older than cutoff and not stored: ignored (history is frozen)
    merged = merged.sort_index()
    merged.name = existing.name or fetched.name
    return merged, changed


def load_freshness() -> dict:
    fp = paths.DATA_STATE / "freshness.json"
    if not fp.exists():
        return {}
    return json.loads(fp.read_text())


def save_freshness(d: dict) -> None:
    paths.DATA_STATE.mkdir(parents=True, exist_ok=True)
    (paths.DATA_STATE / "freshness.json").write_text(json.dumps(d, indent=1, sort_keys=True) + "\n")
