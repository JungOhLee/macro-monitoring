import pytest
from pipeline.registry import load_registry, load_thresholds


def test_registry_loads_and_counts():
    reg = load_registry()
    assert len(reg.series) == 27
    assert len(reg.indicators) == 21
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
        assert ind.role in ("timing", "magnitude", "confirmation")
        assert ind.pillar in reg.pillar_weights
    for s in reg.series:
        assert s.source in ("fred", "yahoo", "manual", "shiller", "alphavantage")
        assert s.frequency in ("daily", "weekly", "monthly", "quarterly")


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
