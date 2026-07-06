import json

import numpy as np
import pandas as pd
import pytest

from pipeline import export, store
from pipeline.registry import Indicator, Registry, Series

from tests.test_scores import BANDS, TH, make_raw, make_reg  # reuse fixtures

THX = TH

EPI_STUB = {
    "episodes": [
        {"id": "dotcom", "name": "Dot-com bust", "peak": "2000-03-24"},
        {"id": "gfc", "name": "Global Financial Crisis", "peak": "2007-10-09"},
    ],
    "offsets_months": [-24, -12, 0],
}


@pytest.fixture()
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(export.paths, "SITE_DATA", tmp_path / "site_data")
    monkeypatch.setattr(store.paths, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path / "state")
    for sid, s in make_raw(with_confirmation=True).items():
        store.write_series(sid, s)
    return tmp_path / "site_data"


def test_export_writes_three_files_with_contract(site, monkeypatch):
    import pipeline.registry as registry

    monkeypatch.setattr(registry, "load_episodes", lambda: EPI_STUB)
    payload = export.export_site(make_reg(with_confirmation=True), THX)
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
    assert history["crisis_markers"] == [
        {"date": "2000-03-24", "name": "Dot-com bust", "library": True},
        {"date": "2007-10-09", "name": "Global Financial Crisis", "library": True},
    ]
    assert len(history["full"]["dates"]) == len(history["full"]["composite"])
    assert set(history["full"]["pillars"]) <= {"valuation", "leverage", "sentiment"}

    assert indicators["i_up"]["latest"]["pct_full"] == 100.0
    assert indicators["i_up"]["pillar"] == "valuation"
    assert len(indicators["i_up"]["series"]["dates"]) <= 1000

    assert latest["stress"]["full"]["label"] in ("quiet", "elevated", "confirming")
    assert latest["stress"]["full"]["score"] == pytest.approx(100.0, abs=0.5)
    assert "stress" in history["full"]


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


def test_crisis_markers_exported(site, monkeypatch):
    import pipeline.registry as registry

    epi_cfg = {
        "episodes": [
            {"id": "b", "name": "Beta library", "peak": "2005-06-15"},
            {"id": "a", "name": "Alpha library", "peak": "2001-01-10"},
            {"id": "m", "name": "Marker only", "peak": "2003-03-03", "library": False},
        ],
        "offsets_months": [-12, -1, 0],
    }
    monkeypatch.setattr(registry, "load_episodes", lambda: epi_cfg)
    export.export_site(make_reg(), THX)
    history = json.loads((site / "history.json").read_text())

    assert history["crisis_markers"] == [
        {"date": "2001-01-10", "name": "Alpha library", "library": True},
        {"date": "2003-03-03", "name": "Marker only", "library": False},
        {"date": "2005-06-15", "name": "Beta library", "library": True},
    ]
    assert history["episode_peaks"] == ["2001-01-10", "2003-03-03", "2005-06-15"]


def test_export_writes_episodes_json(site, monkeypatch, tmp_path):
    import pipeline.compute.episodes as epimod
    monkeypatch.setattr(epimod, "load_snapshots", lambda: pd.DataFrame(
        [{"episode": "gfc", "offset_months": -6, "indicator_id": "i_up", "percentile": 91.0}]))
    export.export_site(make_reg(), THX)
    epi = json.loads((site / "episodes.json").read_text())
    assert epi["snapshots"]["gfc"]["-6"]["i_up"] == 91.0
    assert epi["timeline90"]["gfc"]["i_up"] == -6


def test_export_analogs_in_latest(site, monkeypatch):
    import pipeline.compute.episodes as epimod
    rows = [{"episode": "gfc", "offset_months": -6, "indicator_id": f"k{i}", "percentile": 50.0}
            for i in range(8)]
    rows += [{"episode": "gfc", "offset_months": -6, "indicator_id": "i_up", "percentile": 100.0},
             {"episode": "gfc", "offset_months": -6, "indicator_id": "i_down", "percentile": 99.0}]
    monkeypatch.setattr(epimod, "load_snapshots", lambda: pd.DataFrame(rows))
    payload = export.export_site(make_reg(), THX)
    # today's vector only has i_up/i_down (+gated i_young absent) => shared=2 < 8 -> no analogs
    assert payload["analogs"] is None


def test_export_today_vector_excludes_context_indicator(site, monkeypatch):
    # End-to-end check of the export-path exclusion: if the context indicator were
    # wrongly folded into today's live analog vector, "i_ctx" would bring the shared-key
    # count with `snaps` up to 8 (>= min_shared) and analogs would fire; properly
    # excluded, shared stays at 7 and analogs must stay None.
    import pipeline.compute.episodes as epimod

    store.write_series("ctx", make_raw(with_context=True)["ctx"])
    rows = [{"episode": "gfc", "offset_months": -6, "indicator_id": f"k{i}", "percentile": 50.0}
            for i in range(7)]
    rows.append({"episode": "gfc", "offset_months": -6, "indicator_id": "i_ctx", "percentile": 50.0})
    monkeypatch.setattr(epimod, "load_snapshots", lambda: pd.DataFrame(rows))

    payload = export.export_site(make_reg(with_context=True), THX)
    assert payload["analogs"] is None


def test_export_indicators_json_includes_context_indicator(site):
    store.write_series("ctx", make_raw(with_context=True)["ctx"])
    payload = export.export_site(make_reg(with_context=True), THX)
    indicators = json.loads((site / "indicators.json").read_text())
    assert "i_ctx" in indicators
    entry = indicators["i_ctx"]
    assert entry["pillar"] == "context"
    assert entry["role"] == "context"
    # drill-down needs both raw and percentile series/latest values, same shape as any
    # other indicator.
    assert entry["latest"]["value"] is not None
    assert entry["latest"]["pct_full"] == pytest.approx(100.0, abs=0.5)
    assert len(entry["series"]["dates"]) > 0
    assert len(entry["pct_series"]["dates"]) > 0
    # but it must be invisible to the payload's pillar rollups, which only cover the
    # five real pillars from pillar_weights.
    assert set(payload["pillars"]) == {"valuation", "leverage", "sentiment"}


def test_export_includes_spx_overlay(site, monkeypatch):
    import pipeline.registry as registry

    monkeypatch.setattr(registry, "load_episodes", lambda: EPI_STUB)
    reg = make_reg(with_confirmation=True)
    reg = Registry(
        series=reg.series + [Series("spx", "fred", "SP500", "daily", 7, 7, 1)],
        indicators=reg.indicators,
        pillar_weights=reg.pillar_weights,
    )
    idx = pd.date_range("1927-12-30", periods=1500, freq="D")
    spx = pd.Series(np.arange(1.0, len(idx) + 1) + 10.0, index=idx)
    store.write_series("spx", spx)

    export.export_site(reg, THX)
    history = json.loads((site / "history.json").read_text())

    spx_hist = history["spx"]
    assert len(spx_hist["dates"]) == len(spx_hist["values"])
    assert len(spx_hist["dates"]) <= 1000
    assert spx_hist["dates"][0].startswith("1927")
    assert all(v is not None and v > 0 for v in spx_hist["values"])
    # spx is the same series regardless of window -- lives at the top level.
    assert "spx" not in history["full"]


def test_downsample_never_exceeds_max():
    for n in (999, 1000, 1001, 2000, 2500, 3000, 5000, 10000):
        s = pd.Series(range(n), index=pd.date_range("1990-01-01", periods=n))
        out = export.downsample(s, 1000)
        assert len(out) <= 1000, n
        assert out.index[-1] == s.index[-1]
        assert out.iloc[-1] == s.iloc[-1]
