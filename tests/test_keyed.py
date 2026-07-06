import pandas as pd
import pytest
import requests

from pipeline.ingest import keyed


@pytest.fixture(autouse=True)
def _reset_throttle_state(monkeypatch):
    # Every test starts with a clean throttle clock so that _get_json's
    # unconditional _throttle() call never triggers a real time.sleep just
    # because an earlier test in this run happened to touch the module-level
    # _last_request_time within the last 1.5s.
    monkeypatch.setattr(keyed, "_last_request_time", None)


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def test_fetch_equity_parses_close(monkeypatch):
    # Free-tier TIME_SERIES_DAILY shape: no "5. adjusted close" field (that
    # lives only on the premium TIME_SERIES_DAILY_ADJUSTED endpoint).
    payload = {
        "Meta Data": {"2. Symbol": "RSP"},
        "Time Series (Daily)": {
            "2026-01-03": {
                "1. open": "150.0", "2. high": "151.0", "3. low": "149.0",
                "4. close": "150.5", "5. volume": "1000000",
            },
            "2026-01-02": {
                "1. open": "148.0", "2. high": "149.5", "3. low": "147.5",
                "4. close": "149.0", "5. volume": "900000",
            },
        },
    }
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured.update(url=url, params=params, timeout=timeout)
        return FakeResp(payload)

    monkeypatch.setattr(keyed.requests, "get", fake_get)
    s = keyed.fetch_alphavantage("RSP", "KEY")
    assert list(s.values) == [149.0, 150.5]
    assert list(s.index) == [pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-03")]
    assert captured["params"]["function"] == "TIME_SERIES_DAILY"
    assert captured["params"]["outputsize"] == "compact"
    assert captured["params"]["symbol"] == "RSP"
    assert captured["params"]["apikey"] == "KEY"
    assert captured["timeout"] == 30


def test_fetch_crypto_parses_close(monkeypatch):
    payload = {
        "Meta Data": {"2. Digital Currency Code": "BTC"},
        "Time Series (Digital Currency Daily)": {
            "2026-01-03": {"1. open": "44000.0", "2. high": "45500.0",
                            "3. low": "43800.0", "4. close": "45000.12",
                            "5. volume": "12345.6"},
            "2026-01-02": {"1. open": "43000.0", "2. high": "44200.0",
                            "3. low": "42800.0", "4. close": "44000.0",
                            "5. volume": "10000.0"},
        },
    }

    def fake_get(url, params=None, timeout=None):
        return FakeResp(payload)

    monkeypatch.setattr(keyed.requests, "get", fake_get)
    s = keyed.fetch_alphavantage("BTC", "KEY")
    assert list(s.values) == [44000.0, 45000.12]
    assert list(s.index) == [pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-03")]


def test_rate_limit_note_raises(monkeypatch):
    payload = {
        "Note": "Thank you for using Alpha Vantage! Our standard API rate limit is "
                 "25 requests per day."
    }
    monkeypatch.setattr(keyed.requests, "get", lambda *a, **k: FakeResp(payload))
    with pytest.raises(RuntimeError) as excinfo:
        keyed.fetch_alphavantage("RSP", "KEY")
    assert "Note" in str(excinfo.value)


def test_premium_information_raises(monkeypatch):
    payload = {
        "Information": "This is a premium endpoint. Please subscribe to any of "
                        "the premium plans."
    }
    monkeypatch.setattr(keyed.requests, "get", lambda *a, **k: FakeResp(payload))
    with pytest.raises(RuntimeError) as excinfo:
        keyed.fetch_alphavantage("SPY", "KEY")
    assert "Information" in str(excinfo.value)


def test_bad_symbol_error_message_raises(monkeypatch):
    payload = {"Error Message": "Invalid API call. Please retry or visit the "
                                  "documentation."}
    monkeypatch.setattr(keyed.requests, "get", lambda *a, **k: FakeResp(payload))
    with pytest.raises(RuntimeError) as excinfo:
        keyed.fetch_alphavantage("XXXX", "KEY")
    assert "Error Message" in str(excinfo.value)


def test_empty_time_series_raises(monkeypatch):
    monkeypatch.setattr(
        keyed.requests, "get", lambda *a, **k: FakeResp({"Time Series (Daily)": {}})
    )
    with pytest.raises(RuntimeError):
        keyed.fetch_alphavantage("RSP", "KEY")


def test_http_error_sanitized(monkeypatch):
    monkeypatch.setattr(
        keyed.requests, "get", lambda *a, **k: FakeResp({"irrelevant": True}, status=403)
    )
    with pytest.raises(RuntimeError) as excinfo:
        keyed.fetch_alphavantage("RSP", "SECRETKEY")
    assert "apikey" not in str(excinfo.value)
    assert "SECRETKEY" not in str(excinfo.value)
    assert "403" in str(excinfo.value)
    assert excinfo.value.__context__ is None


def test_connection_error_sanitized(monkeypatch):
    def fake_get(*a, **k):
        raise requests.ConnectionError(
            "HTTPSConnectionPool(host='www.alphavantage.co', port=443): "
            "Max retries exceeded with url: "
            "/query?function=TIME_SERIES_DAILY&symbol=RSP&apikey=TOPSECRET refused"
        )

    monkeypatch.setattr(keyed.requests, "get", fake_get)
    with pytest.raises(RuntimeError) as excinfo:
        keyed.fetch_alphavantage("RSP", "TOPSECRET")
    assert "TOPSECRET" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


def test_non_json_body_sanitized(monkeypatch):
    class NonJsonResp(FakeResp):
        def json(self):
            raise ValueError("Expecting value")

    monkeypatch.setattr(
        keyed.requests, "get", lambda *a, **k: NonJsonResp({}, status=200)
    )
    with pytest.raises(RuntimeError) as excinfo:
        keyed.fetch_alphavantage("RSP", "SECRETKEY")
    assert "non-JSON" in str(excinfo.value)
    assert "SECRETKEY" not in str(excinfo.value)
    assert excinfo.value.__context__ is None


def test_note_payload_never_leaks_key_even_if_echoed(monkeypatch):
    """Defense in depth: even if Alpha Vantage's own message text echoed the
    key, our error strings scrub it to '***' before including the (now-safe)
    message excerpt -- the key itself never appears verbatim, but the
    surrounding diagnostic text is preserved for debugging."""
    payload = {"Note": "your key SNEAKYKEY123 has been used too many times"}
    monkeypatch.setattr(keyed.requests, "get", lambda *a, **k: FakeResp(payload))
    with pytest.raises(RuntimeError) as excinfo:
        keyed.fetch_alphavantage("RSP", "SNEAKYKEY123")
    msg = str(excinfo.value)
    assert "SNEAKYKEY123" not in msg
    assert "***" in msg
    assert "has been used too many times" in msg


def test_throttle_first_call_does_not_sleep(monkeypatch):
    monkeypatch.setattr(keyed, "_last_request_time", None)
    monkeypatch.setattr(keyed.time, "monotonic", lambda: 100.0)
    sleeps = []
    monkeypatch.setattr(keyed.time, "sleep", lambda secs: sleeps.append(secs))
    keyed._throttle()
    assert sleeps == []
    assert keyed._last_request_time == 100.0


def test_throttle_immediate_second_call_sleeps_remaining_interval(monkeypatch):
    monkeypatch.setattr(keyed, "_last_request_time", 100.0)
    monkeypatch.setattr(keyed.time, "monotonic", lambda: 100.0)
    sleeps = []
    monkeypatch.setattr(keyed.time, "sleep", lambda secs: sleeps.append(secs))
    keyed._throttle()
    assert sleeps == [pytest.approx(1.5)]


def test_throttle_call_after_interval_elapsed_does_not_sleep(monkeypatch):
    monkeypatch.setattr(keyed, "_last_request_time", 100.0)
    monkeypatch.setattr(keyed.time, "monotonic", lambda: 102.0)
    sleeps = []
    monkeypatch.setattr(keyed.time, "sleep", lambda secs: sleeps.append(secs))
    keyed._throttle()
    assert sleeps == []
    assert keyed._last_request_time == 102.0


def test_soft_failure_excerpt_is_truncated(monkeypatch):
    """A message longer than 200 chars is truncated so we never embed an
    unbounded response body in a raised label."""
    long_text = "Information: " + ("x" * 300)
    payload = {"Information": long_text}
    monkeypatch.setattr(keyed.requests, "get", lambda *a, **k: FakeResp(payload))
    with pytest.raises(RuntimeError) as excinfo:
        keyed.fetch_alphavantage("SPY", "KEY")
    msg = str(excinfo.value)
    # Everything after "Alpha Vantage Information response for SPY: " is the
    # excerpt; it must be capped at 200 chars.
    prefix = "Alpha Vantage Information response for SPY: "
    assert msg.startswith(prefix)
    excerpt = msg[len(prefix):]
    assert len(excerpt) == 200
    assert long_text.startswith(excerpt)
