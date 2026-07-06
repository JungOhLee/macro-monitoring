from __future__ import annotations

import pandas as pd
import requests

API_URL = "https://api.stlouisfed.org/fred/series/observations"


def fetch_fred(source_id: str, api_key: str) -> pd.Series:
    failure = None
    resp = None
    try:
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
    except requests.RequestException as exc:
        failure = f"FRED request failed for {source_id}: {type(exc).__name__}"
    if failure is None and resp.status_code != 200:
        failure = f"FRED HTTP {resp.status_code} for {source_id}"
    payload = None
    if failure is None:
        try:
            payload = resp.json()
        except ValueError:
            failure = f"FRED returned non-JSON body for {source_id}"
    if failure is not None:
        raise RuntimeError(failure)
    obs = payload.get("observations", [])
    dates, values = [], []
    for o in obs:
        if o["value"] == ".":
            continue
        dates.append(o["date"])
        values.append(float(o["value"]))
    if not values:
        raise RuntimeError(f"FRED returned no observations for {source_id}")
    return pd.Series(values, index=pd.to_datetime(dates), name=source_id).sort_index()
