from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.registry import Indicator


def asof_align(target_index: pd.DatetimeIndex, s: pd.Series) -> pd.Series:
    """Last known value of s at each target date (NaN before s starts)."""
    return s.sort_index().reindex(target_index, method="ffill")


def _ratio(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a / asof_align(a.index, b)).dropna()


def _yoy(s: pd.Series) -> pd.Series:
    s = s.sort_index()
    prior_dates = s.index - pd.DateOffset(years=1)
    prior = s.reindex(s.index.union(prior_dates)).sort_index().ffill().reindex(prior_dates)
    out = (s.to_numpy() / prior.to_numpy() - 1.0) * 100.0
    result = pd.Series(out, index=s.index)
    # drop points with no observation at/before one year earlier
    valid = prior_dates >= s.index[0]
    return result[valid].dropna()


def _net_liquidity(walcl: pd.Series, tga: pd.Series, rrp: pd.Series) -> pd.Series:
    tga_a = asof_align(walcl.index, tga).fillna(0.0)
    rrp_a = asof_align(walcl.index, rrp).fillna(0.0)
    return (walcl / 1000.0 - tga_a - rrp_a).dropna()


def _real_rate(ff: pd.Series, cpi: pd.Series) -> pd.Series:
    return (ff - asof_align(ff.index, _yoy(cpi))).dropna()


def _dma_distance(s: pd.Series) -> pd.Series:
    ma = s.rolling(200, min_periods=200).mean()
    return ((s / ma - 1.0) * 100.0).dropna()


def _ratio_dma_distance(a: pd.Series, b: pd.Series) -> pd.Series:
    joined = pd.concat([a, b], axis=1, join="inner")
    return _dma_distance(joined.iloc[:, 0] / joined.iloc[:, 1])


def _splice(primary: pd.Series, donor: pd.Series) -> pd.Series:
    primary, donor = primary.sort_index(), donor.sort_index()
    overlap = donor.index.intersection(primary.index)
    if overlap.empty:
        raise ValueError("splice: no overlapping dates between primary and donor")
    anchor = overlap[0]
    factor = primary[anchor] / donor[anchor]
    pre = donor[donor.index < primary.index[0]] * factor
    return pd.concat([pre, primary]).sort_index()


FORMULAS = {
    "ratio": _ratio,
    "yoy": _yoy,
    "net_liquidity": _net_liquidity,
    "real_rate": _real_rate,
    "dma_distance": _dma_distance,
    "ratio_dma_distance": _ratio_dma_distance,
    "splice": _splice,
}


def build_indicator_series(ind: Indicator, raw: dict[str, pd.Series]) -> pd.Series:
    if ind.series is not None:
        return raw[ind.series]
    args = [raw[i] for i in ind.inputs]
    out = FORMULAS[ind.formula](*args)
    out.name = ind.id
    return out
