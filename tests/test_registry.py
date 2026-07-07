import pytest
from pipeline.registry import context_ids, load_registry, load_thresholds


def test_registry_loads_and_counts():
    reg = load_registry()
    # 2026-07-06: usrec added as a raw shading-input series (NBER recession dating,
    # no indicator references it -- same pattern as spx) -- see the macro backdrop
    # strip amendment in docs/superpowers/specs/2026-07-05-macro-monitor-design.md.
    assert len(reg.series) == 33
    assert len(reg.indicators) == 28
    assert abs(sum(reg.pillar_weights.values()) - 1.0) < 1e-9
    assert set(reg.pillar_weights) == {"valuation", "leverage", "liquidity", "sentiment", "macro"}


def test_indicator_references_resolve():
    reg = load_registry()
    ids = set(reg.series_by_id)
    for ind in reg.indicators:
        if ind.series is not None:
            assert ind.series in ids, ind.id
            assert ind.formula is None and ind.inputs is None
        else:
            assert ind.formula is not None
            for inp in ind.inputs:
                assert inp in ids, f"{ind.id} input {inp}"


def test_enums_valid():
    reg = load_registry()
    for ind in reg.indicators:
        assert ind.direction in ("normal", "invert")
        assert ind.role in ("timing", "magnitude", "confirmation", "context")
        if ind.role == "context":
            assert ind.pillar == "context"  # context indicators sit outside pillar_weights
        else:
            assert ind.pillar in reg.pillar_weights
    for s in reg.series:
        assert s.source in ("fred", "yahoo", "manual", "shiller", "alphavantage")
        assert s.frequency in ("daily", "weekly", "monthly", "quarterly")


def test_context_indicators_present_and_identified():
    # 2026-07-06: CPI/PPI/hiring/policy-rate "market status" context indicators, added
    # display-only -- see docs/superpowers/specs/2026-07-05-macro-monitor-design.md.
    reg = load_registry()
    assert context_ids(reg) == {
        "cpi_yoy", "core_cpi_yoy", "ppi_yoy", "payrolls_yoy",
        "unemployment", "job_openings", "fed_funds",
    }
    for ind_id in context_ids(reg):
        ind = next(i for i in reg.indicators if i.id == ind_id)
        assert ind.role == "context"
        assert ind.pillar == "context"
        assert ind.direction == "normal"


def test_unique_ids():
    reg = load_registry()
    sids = [s.id for s in reg.series]
    iids = [i.id for i in reg.indicators]
    assert len(sids) == len(set(sids))
    assert len(iids) == len(set(iids))


def test_thresholds_load():
    th = load_thresholds()
    assert th["regime_bands"][-1]["upper"] == 100
    assert th["alerts"]["cooldown_days"] == 7


def test_regime_bands_calibrated_to_historical_quantiles():
    # Anchored to the 1975-2026 full-window composite quantiles: 50th=64.09,
    # 85th=76.33, 95th=82.96 (rounded to nearest integer). See docs/superpowers/
    # specs/2026-07-05-macro-monitor-design.md amendment dated 2026-07-06.
    th = load_thresholds()
    assert th["regime_bands"] == [
        {"name": "cool", "upper": 64},
        {"name": "warm", "upper": 76},
        {"name": "frothy", "upper": 83},
        {"name": "bubble_risk", "upper": 100},
    ]


def test_bad_registry_rejected(tmp_path):
    bad = tmp_path / "registry.yaml"
    bad.write_text(
        "pillar_weights: {valuation: 1.0}\n"
        "series: []\n"
        "indicators:\n"
        "  - {id: x, name: X, pillar: valuation, role: timing, direction: up, series: missing, lag_days: 1}\n"
    )
    with pytest.raises(ValueError):
        load_registry(bad)


def _one_series_yaml() -> str:
    return ("series:\n"
            "  - {id: s, source: fred, source_id: S, frequency: monthly, "
            "staleness_budget_days: 1, revision_window_days: 1, lag_days: 1}\n")


def test_context_role_requires_context_pillar(tmp_path):
    bad = tmp_path / "registry.yaml"
    bad.write_text(
        "pillar_weights: {valuation: 1.0}\n" + _one_series_yaml() +
        "indicators:\n"
        "  - {id: x, name: X, pillar: valuation, role: context, direction: normal, series: s, lag_days: 1}\n"
    )
    with pytest.raises(ValueError, match="context"):
        load_registry(bad)


def test_context_pillar_requires_context_role(tmp_path):
    bad = tmp_path / "registry.yaml"
    bad.write_text(
        "pillar_weights: {valuation: 1.0}\n" + _one_series_yaml() +
        "indicators:\n"
        "  - {id: x, name: X, pillar: context, role: timing, direction: normal, series: s, lag_days: 1}\n"
    )
    with pytest.raises(ValueError, match="unknown pillar"):
        load_registry(bad)


def test_context_role_and_pillar_pairing_accepted(tmp_path):
    ok = tmp_path / "registry.yaml"
    ok.write_text(
        "pillar_weights: {valuation: 1.0}\n" + _one_series_yaml() +
        "indicators:\n"
        "  - {id: x, name: X, pillar: context, role: context, direction: normal, series: s, lag_days: 1,\n"
        "     blurb: 'A test context indicator used to check role/pillar pairing.'}\n"
    )
    reg = load_registry(ok)
    assert reg.indicators[0].pillar == "context"
    assert reg.indicators[0].role == "context"
    assert context_ids(reg) == {"x"}


def test_missing_blurb_rejected(tmp_path):
    bad = tmp_path / "registry.yaml"
    bad.write_text(
        "pillar_weights: {valuation: 1.0}\n" + _one_series_yaml() +
        "indicators:\n"
        "  - {id: x, name: X, pillar: valuation, role: timing, direction: normal, series: s, lag_days: 1}\n"
    )
    with pytest.raises(ValueError, match="missing blurb"):
        load_registry(bad)


def test_all_indicators_have_blurbs():
    reg = load_registry()
    for ind in reg.indicators:
        assert ind.blurb and len(ind.blurb.split()) >= 8, ind.id


def test_invert_indicator_blurbs_state_the_flip():
    # Every direction:invert blurb must tell the reader that a lower/negative raw
    # value scores a HIGHER froth percentile -- the word HIGHER is the marker the
    # registry blurbs use for this (see the glossary design, 2026-07-07).
    reg = load_registry()
    for ind in reg.indicators:
        if ind.direction == "invert":
            assert "HIGHER" in ind.blurb, ind.id
