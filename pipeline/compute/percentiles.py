from __future__ import annotations

import pandas as pd

MIN_HISTORY_DAYS = 3652  # 10 years

WINDOW_20Y = {"daily": 5040, "weekly": 1040, "monthly": 240, "quarterly": 80}
MIN_OBS_10Y = {"daily": 2520, "weekly": 520, "monthly": 120, "quarterly": 40}


def expanding_percentile(s: pd.Series) -> pd.Series:
    return s.expanding().rank(pct=True) * 100.0


def rolling20y_percentile(s: pd.Series, frequency: str) -> pd.Series:
    return s.rolling(WINDOW_20Y[frequency], min_periods=MIN_OBS_10Y[frequency]).rank(pct=True) * 100.0


def qualifying_mask(s: pd.Series) -> pd.Series:
    if s.empty:
        return pd.Series(dtype=bool)
    return pd.Series((s.index - s.index[0]).days >= MIN_HISTORY_DAYS, index=s.index)


def froth(pct: pd.Series, direction: str) -> pd.Series:
    return pct if direction == "normal" else 100.0 - pct


def expanding_zscore(s: pd.Series) -> pd.Series:
    mean = s.expanding().mean()
    std = s.expanding().std(ddof=1)
    return (s - mean) / std
