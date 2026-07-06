import pandas as pd

from pipeline import store


def s(pairs):
    idx = pd.to_datetime([p[0] for p in pairs])
    return pd.Series([float(p[1]) for p in pairs], index=idx)


def test_merge_appends_new_dates():
    existing = s([("2026-01-01", 1.0), ("2026-01-02", 2.0)])
    fetched = s([("2026-01-01", 1.0), ("2026-01-02", 2.0), ("2026-01-03", 3.0)])
    merged, changed = store.merge_observations(existing, fetched, revision_window_days=0)
    assert list(merged.values) == [1.0, 2.0, 3.0]
    assert changed == 1


def test_merge_rewrites_inside_revision_window():
    existing = s([("2026-01-01", 1.0), ("2026-03-01", 2.0)])
    fetched = s([("2026-01-01", 9.0), ("2026-03-01", 2.5)])
    merged, changed = store.merge_observations(existing, fetched, revision_window_days=30)
    # 2026-03-01 is within 30d of last stored obs (2026-03-01) -> rewritten;
    # 2026-01-01 is older -> stored value kept.
    assert merged["2026-01-01"] == 1.0
    assert merged["2026-03-01"] == 2.5
    assert changed == 1


def test_merge_never_deletes_stored_rows():
    existing = s([("2026-01-01", 1.0), ("2026-01-02", 2.0)])
    fetched = s([("2026-01-02", 2.0)])  # source dropped a row
    merged, changed = store.merge_observations(existing, fetched, revision_window_days=365)
    assert "2026-01-01" in merged.index.strftime("%Y-%m-%d")
    assert changed == 0


def test_merge_empty_existing():
    fetched = s([("2026-01-01", 1.0)])
    existing = pd.Series(dtype=float, index=pd.DatetimeIndex([]), name="demo")
    merged, changed = store.merge_observations(existing, fetched, 0)
    assert changed == 1 and len(merged) == 1
    assert merged.name == "demo"


def test_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(store.paths, "DATA_RAW", tmp_path)
    data = s([("2026-01-01", 1.5), ("2026-01-02", 2.5)])
    store.write_series("demo", data)
    back = store.read_series("demo")
    assert back.name == "demo"
    pd.testing.assert_index_equal(back.index, data.index)
    assert list(back.values) == [1.5, 2.5]
    missing = store.read_series("missing")
    assert missing.empty
    assert isinstance(missing.index, pd.DatetimeIndex)
    assert missing.name == "missing"


def test_freshness_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path)
    d = {"demo": {"last_fetch": "2026-07-05T00:00:00Z", "fetch_ok": True, "last_obs": "2026-07-04", "error": None}}
    store.save_freshness(d)
    assert store.load_freshness() == d
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path / "nope")
    assert store.load_freshness() == {}
