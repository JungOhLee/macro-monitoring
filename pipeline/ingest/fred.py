from __future__ import annotations

import pandas as pd
import requests

API_URL = "https://api.stlouisfed.org/fred/series/observations"


def fetch_fred(source_id: str, api_key: str) -> pd.Series:
    resp = requests.get(
        API_URL,
        params={
            "series_id": source_id,
            "api_key": api_key,
            "file_type": "json",
            "limit": 100000,
        },
        timeout=30,
    )
    resp.raise_for_status()
    obs = resp.json().get("observations", [])
    dates, values = [], []
    for o in obs:
        if o["value"] == ".":
            continue
        dates.append(o["date"])
        values.append(float(o["value"]))
    if not values:
        raise RuntimeError(f"FRED returned no observations for {source_id}")
    return pd.Series(values, index=pd.to_datetime(dates), name=source_id).sort_index()
