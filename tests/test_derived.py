import numpy as np
import pandas as pd
import pytest

from pipeline.compute import derived
from pipeline.registry import Indicator


def days(start, n, step_days=1):
    return pd.date_range(start, periods=n, freq=f"{step_days}D")


def test_ratio_asof_alignment():
    a = pd.Series([10.0, 20.0], index=pd.to_datetime(["2026-03-31", "2026-06-30"]))
    b = pd.Series([2.0, 4.0], index=pd.to_datetime(["2026-01-01", "2026-06-30"]))
    out = derived.FORMULAS["ratio"](a, b)
    assert out["2026-03-31"] == 5.0   # uses b as-of 2026-01-01
    assert out["2026-06-30"] == 5.0   # 20/4


def test_yoy_exact_year():
    idx = pd.to_datetime(["2025-01-31", "2025-06-30", "2026-01-31"])
    s = pd.Series([100.0, 110.0, 121.0], index=idx)
    out = derived.FORMULAS["yoy"](s)
    assert out["2026-01-31"] == pytest.approx(21.0)
    assert "2025-01-31" not in out.index  # no prior-year value


def test_net_liquidity_units_and_missing():
    walcl = pd.Series([8_000_000.0, 8_500_000.0], index=pd.to_datetime(["2002-12-18", "2026-01-07"]))
    tga = pd.Series([700.0], index=pd.to_datetime(["2026-01-06"]))
    rrp = pd.Series([500.0], index=pd.to_datetime(["2026-01-06"]))
    out = derived.FORMULAS["net_liquidity"](walcl, tga, rrp)
    assert out["2002-12-18"] == pytest.approx(8000.0)          # TGA/RRP treated as 0 pre-start
    assert out["2026-01-07"] == pytest.approx(8500.0 - 700 - 500)


def test_real_rate():
    ff = pd.Series([5.0], index=pd.to_datetime(["2026-01-31"]))
    cpi = pd.Series([100.0, 103.0], index=pd.to_datetime(["2025-01-31", "2026-01-31"]))
    out = derived.FORMULAS["real_rate"](ff, cpi)
    assert out["2026-01-31"] == pytest.approx(2.0)


def test_dma_distance():
    idx = days("2025-01-01", 210)
    s = pd.Series(100.0, index=idx)
    s.iloc[-1] = 110.0
    out = derived.FORMULAS["dma_distance"](s)
    assert len(out) == 11  # only dates with a full 200-obs window
    assert out.iloc[-1] == pytest.approx((110 / ((199 * 100 + 110) / 200) - 1) * 100)


def test_splice_scales_donor():
    donor = pd.Series([50.0, 60.0], index=pd.to_datetime(["2000-01-03", "2006-01-02"]))
    primary = pd.Series([120.0, 130.0], index=pd.to_datetime(["2006-01-02", "2026-01-02"]))
    out = derived.FORMULAS["splice"](primary, donor)
    assert out["2000-01-03"] == pytest.approx(100.0)  # 50 * (120/60)
    assert out["2006-01-02"] == 120.0
    assert out["2026-01-02"] == 130.0


def test_splice_no_overlap_raises():
    donor = pd.Series([1.0], index=pd.to_datetime(["2000-01-01"]))
    primary = pd.Series([2.0], index=pd.to_datetime(["2010-01-01"]))
    with pytest.raises(ValueError):
        derived.FORMULAS["splice"](primary, donor)


def test_build_indicator_series_raw_and_derived():
    raw = {
        "vixcls": pd.Series([15.0], index=pd.to_datetime(["2026-01-02"])),
        "m2sl": pd.Series([100.0, 105.0], index=pd.to_datetime(["2025-01-31", "2026-01-31"])),
    }
    raw_ind = Indicator(id="vix", name="VIX", pillar="sentiment", role="timing",
                        direction="invert", lag_days=1, series="vixcls")
    der_ind = Indicator(id="m2_yoy", name="M2 YoY", pillar="liquidity", role="timing",
                        direction="normal", lag_days=14, formula="yoy", inputs=("m2sl",))
    assert derived.build_indicator_series(raw_ind, raw).equals(raw["vixcls"])
    out = derived.build_indicator_series(der_ind, raw)
    assert out["2026-01-31"] == pytest.approx(5.0)
