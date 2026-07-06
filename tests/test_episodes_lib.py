import pandas as pd
import pytest

from pipeline.compute import episodes as epi
from tests.test_scores import TH, make_raw, make_reg

EPI_CFG = {
    "episodes": [
        {"id": "boom", "name": "Boom", "peak": "2011-06-30"},
        {"id": "early", "name": "Too early", "peak": "2001-06-30"},
    ],
    "offsets_months": [-12, -1, 0],
}


def test_build_snapshots_asof_and_exclusion():
    reg = make_reg()
    snaps = epi.build_snapshots(reg, TH, make_raw(), EPI_CFG)
    assert set(snaps.columns) == {"episode", "offset_months", "indicator_id", "percentile"}
    boom = snaps[snaps.episode == "boom"]
    # monotone-up series: percentile ~100 at every offset once qualified (10y gate passes mid-2010)
    row = boom[(boom.offset_months == 0) & (boom.indicator_id == "i_up")]
    assert row.iloc[0]["percentile"] == pytest.approx(100.0, abs=0.5)
    # i_young has <10y history: excluded everywhere, never zero-filled
    assert boom[boom.indicator_id == "i_young"].empty
    # 'early' episode predates qualification (gate passes 2010): no rows at all
    assert snaps[snaps.episode == "early"].empty


def test_pillar_scores_reweighted():
    reg = make_reg()
    snaps = epi.build_snapshots(reg, TH, make_raw(), EPI_CFG)
    ps = epi.pillar_scores_from_snapshots(reg, snaps)
    boom0 = ps[(ps.episode == "boom") & (ps.offset_months == 0)]
    assert set(boom0.pillar) == {"valuation", "leverage"}  # sentiment excluded (i_young gated)
    val = boom0[boom0.pillar == "valuation"].iloc[0]["score"]
    assert val == pytest.approx(100.0, abs=0.5)


def test_confirmation_excluded_from_pillar_scores():
    reg = make_reg(with_confirmation=True)
    raw = make_raw(with_confirmation=True)
    snaps = epi.build_snapshots(reg, TH, raw, EPI_CFG)
    # the confirmation-role indicator does show up in the raw snapshot library...
    assert "i_conf" in snaps.indicator_id.unique()
    ps = epi.pillar_scores_from_snapshots(reg, snaps)
    # ...but must never surface in a reweighted pillar row
    assert set(ps.pillar.unique()) == {"valuation", "leverage"}

    reg_no_conf = make_reg()
    snaps_no_conf = epi.build_snapshots(reg_no_conf, TH, make_raw(), EPI_CFG)
    ps_no_conf = epi.pillar_scores_from_snapshots(reg_no_conf, snaps_no_conf)

    val_with_conf = ps[(ps.episode == "boom") & (ps.offset_months == 0)
                       & (ps.pillar == "valuation")].iloc[0]["score"]
    val_no_conf = ps_no_conf[(ps_no_conf.episode == "boom") & (ps_no_conf.offset_months == 0)
                             & (ps_no_conf.pillar == "valuation")].iloc[0]["score"]
    assert val_with_conf == pytest.approx(val_no_conf)


def test_marker_only_episodes_excluded_from_snapshots():
    reg = make_reg()
    cfg = {
        "episodes": [
            {"id": "marker_only", "name": "Marker only", "peak": "2011-06-30", "library": False},
            {"id": "sibling", "name": "Sibling library episode", "peak": "2012-06-30"},
        ],
        "offsets_months": [-12, -1, 0],
    }
    snaps = epi.build_snapshots(reg, TH, make_raw(), cfg)
    assert snaps[snaps.episode == "marker_only"].empty
    assert not snaps[snaps.episode == "sibling"].empty


def test_firing_timeline_first_crossing():
    snaps = pd.DataFrame([
        {"episode": "e", "offset_months": -12, "indicator_id": "a", "percentile": 70.0},
        {"episode": "e", "offset_months": -1, "indicator_id": "a", "percentile": 85.0},
        {"episode": "e", "offset_months": 0, "indicator_id": "a", "percentile": 95.0},
        {"episode": "e", "offset_months": -12, "indicator_id": "b", "percentile": 10.0},
    ])
    tl = epi.firing_timeline(snaps, level=80)
    assert tl[(tl.indicator_id == "a")].iloc[0]["first_offset"] == -1
    assert tl[tl.indicator_id == "b"].empty
