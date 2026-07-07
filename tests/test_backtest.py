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


def _report_fixture():
    months = pd.date_range("1998-01-30", "2003-12-31", freq="BME")
    stage = pd.Series(0, index=months)
    stage.loc["1999-06-30":"2000-01-31"] = 4
    engaged = pd.Series(False, index=months)
    engaged.loc["1999-03-31":"2000-03-31"] = True
    spx = pd.Series(100.0, index=months)
    # decline from the 2000-03 peak to a 50.0 trough at 2001-09, then partial recovery
    decline = np.linspace(97.0, 50.0, 18)          # 2000-04-28 .. 2001-09-28
    spx.iloc[27:45] = decline
    spx.iloc[45:] = 60.0
    return months, stage, engaged, spx


def test_report_card_lead_time_and_drawdown():
    _, stage, engaged, spx = _report_fixture()
    eps = [{"id": "dotcom", "name": "Dot-com bust", "peak": "2000-03-24",
            "report_note": "margin-debt data gap"}]
    rows = backtest.build_report_card(stage, engaged, spx, eps)
    assert len(rows) == 1
    r = rows[0]
    assert r["control"] is False
    assert r["first_engaged"] == "1999-03-31"
    assert r["first_stage4"] == "1999-06-30"
    assert r["lead_months"] == 9                      # 1999-06 -> 2000-03
    assert r["max_drawdown_pct"] == -50.0             # 100 -> 50
    assert r["months_to_trough"] == 18                # 2000-03 -> 2001-09
    assert r["note"] == "margin-debt data gap"


def test_report_card_never_fired_row_is_honest():
    months, _, _, spx = _report_fixture()
    stage = pd.Series(0, index=months)
    engaged = pd.Series(False, index=months)
    rows = backtest.build_report_card(stage, engaged, spx, [
        {"id": "dotcom", "name": "Dot-com bust", "peak": "2000-03-24"}])
    r = rows[0]
    assert r["first_engaged"] is None and r["first_stage4"] is None
    assert r["lead_months"] is None
    assert r["max_drawdown_pct"] == -50.0             # drawdown is about the market, not the tracker


def test_report_card_control_row_counts_2019():
    months = pd.date_range("2018-01-31", "2020-12-31", freq="BME")
    engaged = pd.Series(False, index=months)
    engaged.loc["2019-06-28":"2019-08-30"] = True
    stage = pd.Series(0, index=months)
    spx = pd.Series(100.0, index=months)
    rows = backtest.build_report_card(stage, engaged, spx, [
        {"id": "covid", "name": "COVID crash", "peak": "2020-02-19", "control": True}])
    r = rows[0]
    assert r["control"] is True and r["engaged_months"] == 3
    assert r["first_engaged"] is None and r["lead_months"] is None


def test_report_card_skips_criterion_false():
    months, stage, engaged, spx = _report_fixture()
    rows = backtest.build_report_card(stage, engaged, spx, [
        {"id": "black1987", "name": "Black Monday", "peak": "1987-08-25", "criterion": False}])
    assert rows == []
