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
