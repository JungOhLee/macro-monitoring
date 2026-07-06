import pandas as pd
import pytest

from pipeline.ingest import stooq

CSV = "Date,Open,High,Low,Close,Volume\n2026-01-02,10,11,9,10.5,100\n2026-01-03,10.5,12,10,11.0,200\n"


class FakeResp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_fetch_parses_close(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured.update(url=url, headers=headers, timeout=timeout)
        return FakeResp(CSV)

    monkeypatch.setattr(stooq.requests, "get", fake_get)
    s = stooq.fetch_stooq("^spx")
    assert list(s.values) == [10.5, 11.0]
    assert s.index[-1] == pd.Timestamp("2026-01-03")
    assert "s=%5Espx" in captured["url"] or "s=^spx" in captured["url"]
    assert captured["timeout"] == 30
    assert "Mozilla" in captured["headers"]["User-Agent"]


def test_no_data_raises(monkeypatch):
    monkeypatch.setattr(stooq.requests, "get", lambda *a, **k: FakeResp("No data"))
    with pytest.raises(RuntimeError):
        stooq.fetch_stooq("bogus")
