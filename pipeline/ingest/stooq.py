from __future__ import annotations

import io
from urllib.parse import quote

import pandas as pd
import requests

BASE = "https://stooq.com/q/d/l/?s={sym}&i=d"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) macro-monitor/0.1"}


def fetch_stooq(source_id: str) -> pd.Series:
    url = BASE.format(sym=quote(source_id))
    resp = requests.get(url, headers=UA, timeout=30)
    resp.raise_for_status()
    text = resp.text
    if not text.startswith("Date,"):
        raise RuntimeError(f"Stooq returned no data for {source_id}: {text[:80]!r}")
    df = pd.read_csv(io.StringIO(text), parse_dates=["Date"])
    s = pd.Series(df["Close"].to_numpy(dtype=float), index=pd.DatetimeIndex(df["Date"]), name=source_id)
    return s.dropna().sort_index()
