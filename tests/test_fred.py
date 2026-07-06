import pandas as pd
import pytest
import requests

from pipeline.ingest import fred


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_fetch_parses_and_drops_missing(monkeypatch):
    payload = {"observations": [
        {"date": "2026-01-01", "value": "1.5"},
        {"date": "2026-01-02", "value": "."},
        {"date": "2026-01-03", "value": "2.5"},
    ]}
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured.update(params=params, timeout=timeout, url=url)
        return FakeResp(payload)

    monkeypatch.setattr(fred.requests, "get", fake_get)
    s = fred.fetch_fred("T10Y3M", "KEY")
    assert list(s.values) == [1.5, 2.5]
    assert s.index[0] == pd.Timestamp("2026-01-01")
    assert captured["params"]["series_id"] == "T10Y3M"
    assert captured["params"]["api_key"] == "KEY"
    assert captured["timeout"] == 30


def test_fetch_empty_raises(monkeypatch):
    monkeypatch.setattr(fred.requests, "get", lambda *a, **k: FakeResp({"observations": []}))
    with pytest.raises(RuntimeError):
        fred.fetch_fred("XXX", "KEY")


def test_http_error_sanitized(monkeypatch):
    monkeypatch.setattr(
        fred.requests, "get", lambda *a, **k: FakeResp({"irrelevant": True}, status=403)
    )
    with pytest.raises(RuntimeError) as excinfo:
        fred.fetch_fred("XXX", "SECRETKEY")
    assert "api_key" not in str(excinfo.value)
    assert "403" in str(excinfo.value)
    assert "SECRETKEY" not in str(excinfo.value)
    assert excinfo.value.__context__ is None


def test_connection_error_sanitized(monkeypatch):
    def fake_get(*a, **k):
        raise requests.ConnectionError(
            "HTTPSConnectionPool(host='api.stlouisfed.org', port=443): "
            "Max retries exceeded with url: "
            "/fred/series/observations?series_id=X&api_key=TOPSECRET refused"
        )

    monkeypatch.setattr(fred.requests, "get", fake_get)
    with pytest.raises(RuntimeError) as excinfo:
        fred.fetch_fred("X", "TOPSECRET")
    assert "TOPSECRET" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


def test_non_json_body_sanitized(monkeypatch):
    class NonJsonResp(FakeResp):
        def json(self):
            raise ValueError("Expecting value")

    monkeypatch.setattr(
        fred.requests, "get", lambda *a, **k: NonJsonResp({}, status=200)
    )
    with pytest.raises(RuntimeError) as excinfo:
        fred.fetch_fred("XXX", "SECRETKEY")
    assert "non-JSON" in str(excinfo.value)
    assert "SECRETKEY" not in str(excinfo.value)
    assert excinfo.value.__context__ is None
