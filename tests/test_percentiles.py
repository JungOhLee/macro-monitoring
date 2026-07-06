import numpy as np
import pandas as pd
import pytest

from pipeline.compute import percentiles as pct


def monthly(n, values=None, start="2000-01-31"):
    idx = pd.date_range(start, periods=n, freq="ME")
    vals = values if values is not None else np.arange(1.0, n + 1)
    return pd.Series(vals, index=idx)


def test_expanding_percentile_monotonic_series():
    s = monthly(5)
    out = pct.expanding_percentile(s)
    assert out.iloc[0] == pytest.approx(100.0)   # only obs -> rank 1/1
    assert out.iloc[-1] == pytest.approx(100.0)  # strictly increasing -> always the max
    s2 = monthly(5, values=[5.0, 4.0, 3.0, 2.0, 1.0])
    assert pct.expanding_percentile(s2).iloc[-1] == pytest.approx(20.0)  # min of 5 -> 1/5


def test_qualifying_mask_10y():
    s = monthly(121)  # Jan 2000 .. Jan 2010 month-ends
    mask = pct.qualifying_mask(s)
    assert not mask.iloc[0]
    assert not mask.iloc[100]
    assert mask.iloc[-1]  # 2010-01-31 is >= 10y after 2000-01-31


def test_rolling20y_needs_10y_of_obs():
    s = monthly(130)
    out = pct.rolling20y_percentile(s, "monthly")
    assert out.iloc[:119].isna().all()   # < 120 obs -> NaN
    assert not np.isnan(out.iloc[119])   # 120th obs -> defined
    assert out.iloc[-1] == pytest.approx(100.0)


def test_rolling20y_window_slides():
    # 21y of monthly data: first year eventually leaves the window
    vals = np.r_[np.full(12, 1000.0), np.arange(1.0, 241.0)]  # huge first year, then rising
    s = monthly(252, values=vals)
    out = pct.rolling20y_percentile(s, "monthly")
    # by the last obs the window is the trailing 240 obs = [13th..252nd];
    # the huge first year is gone, and the last value is the window max
    assert out.iloc[-1] == pytest.approx(100.0)


def test_froth_direction():
    p = pd.Series([10.0, 90.0])
    assert list(pct.froth(p, "normal")) == [10.0, 90.0]
    assert list(pct.froth(p, "invert")) == [90.0, 10.0]


def test_expanding_zscore():
    s = monthly(3, values=[1.0, 2.0, 3.0])
    z = pct.expanding_zscore(s)
    assert z.iloc[-1] == pytest.approx(1.0)  # (3-2)/1 with ddof=1
