from __future__ import annotations

import time

import pandas as pd
import requests

API_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def fetch_yahoo(source_id: str) -> pd.Series:
    resp = requests.get(
        API_URL.format(sym=source_id),
        params={"period1": "-2208988800", "period2": str(int(time.time())), "interval": "1d"},
        headers=UA,
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Yahoo HTTP {resp.status_code} for {source_id}")
    try:
        result = resp.json()["chart"]["result"][0]
        ts = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise RuntimeError(f"Yahoo returned unexpected payload for {source_id}")
    idx = pd.to_datetime(ts, unit="s", utc=True).tz_localize(None).normalize()
    s = pd.Series(closes, index=idx, dtype=float, name=source_id).dropna()
    if s.empty:
        raise RuntimeError(f"Yahoo returned no data for {source_id}")
    return s[~s.index.duplicated(keep="last")].sort_index()
