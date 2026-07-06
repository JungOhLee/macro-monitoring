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
