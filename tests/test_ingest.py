import json

import pandas as pd

import pipeline.ingest as ingest
from pipeline import store
from pipeline.registry import Registry, Series


def make_reg():
    return Registry(
        series=[
            Series("good", "fred", "GOOD", "daily", 7, 0, 1),
            Series("bad", "fred", "BAD", "daily", 7, 0, 1),
            Series("mkt", "yahoo", "^mkt", "daily", 7, 0, 1),
        ],
        indicators=[],
        pillar_weights={"valuation": 1.0},
    )


def fake_fred(source_id, api_key):
    if source_id == "BAD":
        raise RuntimeError("boom")
    return pd.Series([1.0], index=pd.to_datetime(["2026-07-03"]), name=source_id)


def fake_yahoo(source_id):
    return pd.Series([2.0], index=pd.to_datetime(["2026-07-02"]), name=source_id)


def test_run_ingest_isolates_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(store.paths, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path / "state")
    monkeypatch.setattr(ingest, "fetch_fred", fake_fred)
    monkeypatch.setattr(ingest, "fetch_yahoo", fake_yahoo)
    now = pd.Timestamp("2026-07-05")
    fresh = ingest.run_ingest(make_reg(), api_key="K", now=now)
    assert fresh["good"]["fetch_ok"] is True
    assert fresh["good"]["last_obs"] == "2026-07-03"
    assert fresh["bad"]["fetch_ok"] is False
    assert "boom" in fresh["bad"]["error"]
    assert fresh["mkt"]["fetch_ok"] is True
    assert store.read_series("good").iloc[0] == 1.0
    assert store.read_series("bad").empty
    # failure must not lose previously stored data
    assert (tmp_path / "state" / "freshness.json").exists()


def test_stale_series(tmp_path, monkeypatch):
    reg = make_reg()
    now = pd.Timestamp("2026-07-05")
    fresh = {
        "good": {"last_fetch": "x", "fetch_ok": True, "last_obs": "2026-07-03", "error": None},
        "bad": {"last_fetch": "x", "fetch_ok": False, "last_obs": None, "error": "boom"},
        "mkt": {"last_fetch": "x", "fetch_ok": True, "last_obs": "2026-06-01", "error": None},
    }
    assert ingest.stale_series(reg, fresh, now) == ["bad", "mkt"]


def test_error_strings_scrub_api_key(tmp_path, monkeypatch):
    """freshness.json is committed to a public repo; error text must never contain the key."""
    monkeypatch.setattr(store.paths, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path / "state")

    def leaky_fred(source_id, api_key):
        raise RuntimeError(f"connection to /obs?api_key={api_key} refused")

    monkeypatch.setattr(ingest, "fetch_fred", leaky_fred)
    monkeypatch.setattr(ingest, "fetch_yahoo", lambda sid: pd.Series([1.0], index=pd.to_datetime(["2026-07-03"])))
    fresh = ingest.run_ingest(make_reg(), api_key="SECRETKEY123", now=pd.Timestamp("2026-07-05"))
    assert "SECRETKEY123" not in json.dumps(fresh)
    assert "***" in fresh["bad"]["error"]


def test_isolation_survives_corrupt_stored_csv(tmp_path, monkeypatch):
    """Fallback stored-series read must be guarded; corrupt CSV in exception handler can't crash the loop."""
    monkeypatch.setattr(store.paths, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path / "state")
    # Set up a garbage CSV for "bad" series
    (tmp_path / "raw").mkdir(parents=True)
    (tmp_path / "raw" / "bad.csv").write_text("not,a,csv\n1,2,3\n")

    def fred_with_bad_raises(source_id, api_key):
        if source_id == "BAD":
            raise RuntimeError("boom")
        return pd.Series([1.0], index=pd.to_datetime(["2026-07-03"]), name=source_id)

    monkeypatch.setattr(ingest, "fetch_fred", fred_with_bad_raises)
    monkeypatch.setattr(ingest, "fetch_yahoo", fake_yahoo)
    now = pd.Timestamp("2026-07-05")
    fresh = ingest.run_ingest(make_reg(), api_key="K", now=now)
    # Bad series should report failure but not crash
    assert fresh["bad"]["fetch_ok"] is False
    assert fresh["bad"]["last_obs"] is None
    # Good series should complete successfully
    assert fresh["good"]["fetch_ok"] is True
    assert fresh["good"]["last_obs"] == "2026-07-03"


def test_manual_source_skipped_and_fresh_from_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(store.paths, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path / "state")
    reg = Registry(
        series=[Series("man", "manual", "-", "monthly", 36500, 0, 25)],
        indicators=[], pillar_weights={"valuation": 1.0})
    store.write_series("man", pd.Series([1.0], index=pd.to_datetime(["2026-06-01"]), name="man"))
    fresh = ingest.run_ingest(reg, api_key="K", now=pd.Timestamp("2026-07-06"))
    assert fresh["man"]["fetch_ok"] is True
    assert fresh["man"]["last_obs"] == "2026-06-01"
    assert fresh["man"]["error"] is None
