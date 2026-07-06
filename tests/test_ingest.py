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


def make_av_reg(source_id="RSP"):
    return Registry(
        series=[Series("av", "alphavantage", source_id, "daily", 14, 0, 1)],
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


def test_alphavantage_no_key_goes_straight_to_yahoo(tmp_path, monkeypatch):
    """No ALPHAVANTAGE_KEY -> fetch_alphavantage must never be called."""
    monkeypatch.setattr(store.paths, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path / "state")

    def unexpected(*a, **k):
        raise AssertionError("fetch_alphavantage should not be called with no key")

    monkeypatch.setattr(ingest, "fetch_alphavantage", unexpected)
    monkeypatch.setattr(
        ingest, "fetch_yahoo",
        lambda sid: pd.Series([1.0], index=pd.to_datetime(["2026-07-03"]), name=sid),
    )
    fresh = ingest.run_ingest(make_av_reg(), api_key="K", av_api_key=None, now=pd.Timestamp("2026-07-05"))
    assert fresh["av"]["fetch_ok"] is True
    assert fresh["av"]["last_obs"] == "2026-07-03"


def test_alphavantage_key_present_success_skips_yahoo(tmp_path, monkeypatch):
    monkeypatch.setattr(store.paths, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path / "state")

    def unexpected(*a, **k):
        raise AssertionError("fetch_yahoo should not be called when Alpha Vantage succeeds")

    monkeypatch.setattr(
        ingest, "fetch_alphavantage",
        lambda sid, key: pd.Series([2.0], index=pd.to_datetime(["2026-07-04"]), name=sid),
    )
    monkeypatch.setattr(ingest, "fetch_yahoo", unexpected)
    fresh = ingest.run_ingest(make_av_reg(), api_key="K", av_api_key="AVKEY", now=pd.Timestamp("2026-07-05"))
    assert fresh["av"]["fetch_ok"] is True
    assert fresh["av"]["last_obs"] == "2026-07-04"


def test_alphavantage_key_present_failure_falls_back_to_yahoo(tmp_path, monkeypatch):
    """A keyed miss followed by a Yahoo success must count as an overall success."""
    monkeypatch.setattr(store.paths, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path / "state")

    def failing_av(sid, key):
        raise RuntimeError(f"Alpha Vantage Note response for {sid}")

    captured = {}

    def fake_yahoo(sid):
        captured["sid"] = sid
        return pd.Series([3.0], index=pd.to_datetime(["2026-07-02"]), name=sid)

    monkeypatch.setattr(ingest, "fetch_alphavantage", failing_av)
    monkeypatch.setattr(ingest, "fetch_yahoo", fake_yahoo)
    fresh = ingest.run_ingest(make_av_reg(source_id="RSP"), api_key="K", av_api_key="AVKEY", now=pd.Timestamp("2026-07-05"))
    assert fresh["av"]["fetch_ok"] is True
    assert fresh["av"]["last_obs"] == "2026-07-02"
    assert fresh["av"]["error"] is None
    assert captured["sid"] == "RSP"


def test_alphavantage_btc_symbol_maps_to_yahoo_btc_usd(tmp_path, monkeypatch):
    """BTC (Alpha Vantage crypto symbol) must fall back to Yahoo's BTC-USD ticker."""
    monkeypatch.setattr(store.paths, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path / "state")

    def failing_av(sid, key):
        raise RuntimeError("boom")

    captured = {}

    def fake_yahoo(sid):
        captured["sid"] = sid
        return pd.Series([4.0], index=pd.to_datetime(["2026-07-02"]), name=sid)

    monkeypatch.setattr(ingest, "fetch_alphavantage", failing_av)
    monkeypatch.setattr(ingest, "fetch_yahoo", fake_yahoo)
    fresh = ingest.run_ingest(make_av_reg(source_id="BTC"), api_key="K", av_api_key="AVKEY", now=pd.Timestamp("2026-07-05"))
    assert fresh["av"]["fetch_ok"] is True
    assert captured["sid"] == "BTC-USD"


def test_alphavantage_both_fail_reports_failure_and_scrubs_av_key(tmp_path, monkeypatch):
    monkeypatch.setattr(store.paths, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path / "state")

    def failing_av(sid, key):
        raise RuntimeError(f"Alpha Vantage Note response for {sid}")

    def failing_yahoo(sid):
        raise RuntimeError(f"Yahoo HTTP 429 for {sid}")

    monkeypatch.setattr(ingest, "fetch_alphavantage", failing_av)
    monkeypatch.setattr(ingest, "fetch_yahoo", failing_yahoo)
    fresh = ingest.run_ingest(make_av_reg(), api_key="K", av_api_key="AVSECRET", now=pd.Timestamp("2026-07-05"))
    assert fresh["av"]["fetch_ok"] is False
    assert "AVSECRET" not in json.dumps(fresh)
