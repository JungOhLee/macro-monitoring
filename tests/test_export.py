import json

import pandas as pd
import pytest

from pipeline import export, store
from pipeline.registry import Indicator, Registry, Series

from tests.test_scores import BANDS, TH, make_raw, make_reg  # reuse fixtures

THX = {**TH, "episode_peaks": ["2000-03-24", "2007-10-09"]}


@pytest.fixture()
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(export.paths, "SITE_DATA", tmp_path / "site_data")
    monkeypatch.setattr(store.paths, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path / "state")
    for sid, s in make_raw().items():
        store.write_series(sid, s)
    return tmp_path / "site_data"


def test_export_writes_three_files_with_contract(site):
    payload = export.export_site(make_reg(), THX)
    latest = json.loads((site / "latest.json").read_text())
    history = json.loads((site / "history.json").read_text())
    indicators = json.loads((site / "indicators.json").read_text())

    assert latest == payload
    assert latest["as_of"] == "2012-12-31"
    assert latest["composite"]["full"]["regime"] == "bubble_risk"
    assert latest["analogs"] is None and latest["sequence"] is None
    assert latest["pillars"]["valuation"]["weight"] == 0.5
    assert latest["pillars"]["sentiment"]["full"] is None      # gated out -> no score
    assert latest["freshness"]["up"]["stale"] is False

    assert history["episode_peaks"] == ["2000-03-24", "2007-10-09"]
    assert len(history["full"]["dates"]) == len(history["full"]["composite"])
    assert set(history["full"]["pillars"]) <= {"valuation", "leverage", "sentiment"}

    assert indicators["i_up"]["latest"]["pct_full"] == 100.0
    assert indicators["i_up"]["pillar"] == "valuation"
    assert len(indicators["i_up"]["series"]["dates"]) <= 1000


def test_export_deterministic(site):
    p1 = export.export_site(make_reg(), THX)
    p2 = export.export_site(make_reg(), THX)
    assert p1 == p2


def test_downsample_keeps_last():
    s = pd.Series(range(2500), index=pd.date_range("2000-01-01", periods=2500))
    out = export.downsample(s, 1000)
    assert len(out) <= 1000
    assert out.index[-1] == s.index[-1]
    assert out.iloc[-1] == s.iloc[-1]
