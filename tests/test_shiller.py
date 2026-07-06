import pandas as pd
import pytest

from pipeline.ingest import shiller


def test_shiller_date_january():
    assert shiller._shiller_date(1871.01) == pd.Timestamp("1871-01-01")


def test_shiller_date_october_not_tenth_of_year():
    # The critical gotcha: .1 means October, NOT "1/10th of the way through the year".
    assert shiller._shiller_date(1871.1) == pd.Timestamp("1871-10-01")


def test_shiller_date_december():
    assert shiller._shiller_date(2025.12) == pd.Timestamp("2025-12-01")


def test_shiller_date_accepts_string():
    assert shiller._shiller_date("2026.07") == pd.Timestamp("2026-07-01")


def test_shiller_date_single_digit_months():
    for month in range(1, 10):
        assert shiller._shiller_date(float(f"2000.0{month}")) == pd.Timestamp(f"2000-0{month}-01")


def test_find_cape_column_picks_cape_not_total_return_variant():
    # Mimics the real sheet's multi-row header: CAPE at col 2, "TR CAPE" (total
    # return variant, also contains "CAPE") at col 4 -- must pick the former.
    df = pd.DataFrame(
        [
            ["Date", "P", "Earnings Ratio", "", "Earnings Ratio"],
            ["", "", "P/E10 or", "", "TR P/E10 or"],
            ["", "", "CAPE", "", "TR CAPE"],
            [1871.01, 4.44, float("nan"), "", float("nan")],
        ]
    )
    assert shiller._find_cape_column(df) == 2


def test_find_cape_column_missing_raises():
    df = pd.DataFrame([["Date", "P", "D"], [1871.01, 4.44, 0.26]])
    with pytest.raises(RuntimeError):
        shiller._find_cape_column(df)


def test_fetch_shiller_uses_primary_when_fresh(monkeypatch):
    fresh_cape = pd.Series(
        [30.0, 31.0],
        index=pd.to_datetime([pd.Timestamp.now().normalize() - pd.Timedelta(days=20),
                               pd.Timestamp.now().normalize() - pd.Timedelta(days=1)]),
    )

    def fake_try_fetch(url):
        if url == shiller.PRIMARY_URL:
            return fresh_cape, None
        raise AssertionError("fallback should not be fetched when primary is fresh")

    monkeypatch.setattr(shiller, "_try_fetch", fake_try_fetch)
    out = shiller.fetch_shiller("-")
    assert out.equals(fresh_cape)


def test_fetch_shiller_falls_back_when_primary_stale(monkeypatch):
    stale_cape = pd.Series([20.0], index=pd.to_datetime(["2020-01-01"]))
    fresh_cape = pd.Series([30.0], index=[pd.Timestamp.now().normalize() - pd.Timedelta(days=1)])

    def fake_try_fetch(url):
        if url == shiller.PRIMARY_URL:
            return stale_cape, None
        return fresh_cape, None

    monkeypatch.setattr(shiller, "_try_fetch", fake_try_fetch)
    out = shiller.fetch_shiller("-")
    assert out.equals(fresh_cape)


def test_fetch_shiller_falls_back_when_primary_fails(monkeypatch):
    fresh_cape = pd.Series([30.0], index=[pd.Timestamp.now().normalize() - pd.Timedelta(days=1)])

    def fake_try_fetch(url):
        if url == shiller.PRIMARY_URL:
            return None, "boom"
        return fresh_cape, None

    monkeypatch.setattr(shiller, "_try_fetch", fake_try_fetch)
    out = shiller.fetch_shiller("-")
    assert out.equals(fresh_cape)


def test_fetch_shiller_raises_when_both_fail(monkeypatch):
    def fake_try_fetch(url):
        return None, f"boom for {url}"

    monkeypatch.setattr(shiller, "_try_fetch", fake_try_fetch)
    with pytest.raises(RuntimeError) as excinfo:
        shiller.fetch_shiller("-")
    assert "both sources" in str(excinfo.value)
