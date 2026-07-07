import numpy as np
import pandas as pd
import pytest

from pipeline import backtest


def test_lag_shift():
    s = pd.Series([1.0], index=pd.to_datetime(["2020-01-01"]))
    out = backtest.apply_lag(s, 30)
    assert out.index[0] == pd.Timestamp("2020-01-31")


def test_criteria_evaluation():
    months = pd.date_range("1998-01-31", "2023-12-29", freq="BME")
    stage = pd.Series(0, index=months)
    stage.loc["1999-06-30":"2000-03-31"] = 4      # hot before dot-com
    stage.loc["2007-01-31":"2007-10-31"] = 4      # hot before GFC
    stage.loc["2021-06-30":"2022-01-31"] = 4      # hot before 2022
    engaged = stage >= 2
    epi = [{"id": "dotcom", "peak": "2000-03-24"}, {"id": "gfc", "peak": "2007-10-09"},
           {"id": "covid", "peak": "2020-02-19", "control": True},
           {"id": "postcovid", "peak": "2022-01-03"}]
    crits = backtest.evaluate_criteria(stage, engaged, epi)
    by = {c["name"]: c["pass"] for c in crits}
    assert by["stage>=4 before dotcom peak"] is True
    assert by["stage>=4 before gfc peak"] is True
    assert by["stage>=4 before postcovid peak"] is True
    assert by["quiet through 2019 (covid control)"] is True
    # violate the control: engaged through 2019
    stage.loc["2019-01-31":"2019-12-31"] = 3
    crits2 = backtest.evaluate_criteria(stage, stage >= 2, epi)
    assert {c["name"]: c["pass"] for c in crits2}["quiet through 2019 (covid control)"] is False


def test_monthly_top1_similarities_basic():
    keys = [f"k{i}" for i in range(8)]
    months = pd.to_datetime(["2020-01-31", "2020-02-29"])
    froth = {k: pd.Series([80.0, 20.0], index=months) for k in keys}
    rows = [{"episode": "gfc", "offset_months": -6, "indicator_id": k, "percentile": 80.0} for k in keys]
    snaps = pd.DataFrame(rows)
    sims = backtest.monthly_top1_similarities(months, snaps, froth)
    assert len(sims) == 2
    assert sims[0] == pytest.approx(1.0)     # Jan: today == snapshot exactly
    assert sims[1] == pytest.approx(-1.0)    # Feb: today's demeaned vector is the exact opposite


def test_monthly_top1_similarities_none_when_no_analog_qualifies():
    months = pd.to_datetime(["2020-01-31"])
    froth: dict = {}
    snaps = pd.DataFrame(columns=["episode", "offset_months", "indicator_id", "percentile"])
    sims = backtest.monthly_top1_similarities(months, snaps, froth)
    assert sims == [None]


def test_criterion_flag_skips_episode():
    months = pd.date_range("1998-01-31", "2023-12-29", freq="BME")
    stage = pd.Series(0, index=months)
    stage.loc["1999-06-30":"2000-03-31"] = 4      # hot before dot-com
    stage.loc["2007-01-31":"2007-10-31"] = 4      # hot before gfc
    engaged = stage >= 2
    epi = [{"id": "dotcom", "peak": "2000-03-24"}, {"id": "gfc", "peak": "2007-10-09"},
           {"id": "marker_only", "peak": "1990-07-16", "criterion": False},
           {"id": "covid", "peak": "2020-02-19", "control": True}]
    crits = backtest.evaluate_criteria(stage, engaged, epi)
    names = {c["name"] for c in crits}
    assert "stage>=4 before marker_only peak" not in names
    # existing entries unaffected
    assert "stage>=4 before dotcom peak" in names
    assert "stage>=4 before gfc peak" in names
    assert "quiet through 2019 (covid control)" in names
    assert len(crits) == 3

def test_forward_returns_exact_and_null_tail():
    months = pd.date_range("2020-01-31", periods=4, freq="BME")
    spx = pd.Series([100.0, 110.0, 121.0, 133.1], index=months)
    assert backtest.forward_returns(spx, 1) == [10.0, 10.0, 10.0, None]
    assert backtest.forward_returns(spx, 2) == [21.0, 21.0, None, None]


def test_forward_returns_none_propagates():
    months = pd.date_range("2020-01-31", periods=3, freq="BME")
    spx = pd.Series([100.0, np.nan, 121.0], index=months)
    assert backtest.forward_returns(spx, 1) == [None, None, None]
    assert backtest.forward_returns(spx, 2) == [21.0, None, None]
