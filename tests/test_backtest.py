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
