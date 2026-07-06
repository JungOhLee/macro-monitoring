import pandas as pd
import pytest

from pipeline.ingest import yahoo

TIMESTAMPS = [1767387600, 1767646800, 1767733200]  # 2026-01-02, 2026-01-05, 2026-01-06 ~21:00 UTC


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def test_fetch_parses_and_drops_missing(monkeypatch):
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": TIMESTAMPS,
                    "indicators": {"quote": [{"close": [10.5, None, 11.0]}]},
                }
            ]
        }
    }
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured.update(url=url, params=params, headers=headers, timeout=timeout)
        return FakeResp(payload)

    monkeypatch.setattr(yahoo.requests, "get", fake_get)
    s = yahoo.fetch_yahoo("^GSPC")
    assert list(s.values) == [10.5, 11.0]
    assert list(s.index) == [pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-06")]
    assert captured["timeout"] == 30
    assert captured["params"]["interval"] == "1d"
    assert "period1" in captured["params"]


def test_http_error_raises(monkeypatch):
    monkeypatch.setattr(yahoo.requests, "get", lambda *a, **k: FakeResp({}, status=429))
    with pytest.raises(RuntimeError) as excinfo:
        yahoo.fetch_yahoo("^GSPC")
    assert "429" in str(excinfo.value)


def test_malformed_payload_raises(monkeypatch):
    monkeypatch.setattr(
        yahoo.requests, "get", lambda *a, **k: FakeResp({"chart": {"result": None}})
    )
    with pytest.raises(RuntimeError) as excinfo:
        yahoo.fetch_yahoo("^GSPC")
    assert "unexpected payload" in str(excinfo.value)


def test_duplicate_timestamps_keep_last(monkeypatch):
    """Two timestamps normalizing to the same date with different closes should keep the LAST."""
    # 1767646800 and 1767650400 both normalize to 2026-01-05
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1767646800, 1767650400],
                    "indicators": {"quote": [{"close": [10.5, 11.0]}]},
                }
            ]
        }
    }

    def fake_get(url, params=None, headers=None, timeout=None):
        return FakeResp(payload)

    monkeypatch.setattr(yahoo.requests, "get", fake_get)
    s = yahoo.fetch_yahoo("TEST")
    assert len(s) == 1
    assert s.iloc[0] == 11.0  # Keep the last close
    assert s.index[0] == pd.Timestamp("2026-01-05")


def test_all_none_closes_raises(monkeypatch):
    """Payload with all None closes should raise RuntimeError."""
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": TIMESTAMPS,
                    "indicators": {"quote": [{"close": [None, None, None]}]},
                }
            ]
        }
    }

    def fake_get(url, params=None, headers=None, timeout=None):
        return FakeResp(payload)

    monkeypatch.setattr(yahoo.requests, "get", fake_get)
    with pytest.raises(RuntimeError) as excinfo:
        yahoo.fetch_yahoo("TEST")
    assert "no data" in str(excinfo.value)
