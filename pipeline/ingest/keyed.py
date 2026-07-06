from __future__ import annotations

import time

import pandas as pd
import requests

API_URL = "https://www.alphavantage.co/query"

# Alpha Vantage's free tier enforces roughly 1 request/second: back-to-back
# keyed requests (RSP, SPY, BTC in run_ingest) otherwise get a 200-with-body
# "Information" rate-limit response on all but the first (CI run 28816796515,
# observed 2026-07-06). _MIN_REQUEST_INTERVAL paces our own requests so we
# never trip that limit in the first place.
_MIN_REQUEST_INTERVAL = 1.5
_last_request_time = None


def _throttle() -> None:
    global _last_request_time
    now = time.monotonic()
    if _last_request_time is not None:
        remaining = _MIN_REQUEST_INTERVAL - (now - _last_request_time)
        if remaining > 0:
            time.sleep(remaining)
    _last_request_time = now


# Alpha Vantage symbols that use the digital-currency endpoint; everything else
# is treated as an equity/ETF symbol on TIME_SERIES_DAILY (see _fetch_equity).
_CRYPTO_SYMBOLS = {"BTC"}

# Free-tier responses are HTTP 200 with a JSON body carrying one of these keys
# for rate limits, premium-endpoint refusals, or bad symbols -- never parsed as
# data, never persisted with their (possibly key-echoing) message text.
_SOFT_FAILURE_KEYS = ("Note", "Information", "Error Message")


def fetch_alphavantage(series: str, api_key: str) -> pd.Series:
    if series in _CRYPTO_SYMBOLS:
        return _fetch_crypto(series, api_key)
    return _fetch_equity(series, api_key)


# Soft-failure messages are truncated to this many characters (after the key
# scrub) before being embedded in a raised label -- long enough to diagnose,
# short enough to never accidentally carry an entire unbounded response body.
_SOFT_FAILURE_EXCERPT_LEN = 200


def _get_json(params: dict, series: str, api_key: str) -> dict:
    """Shared request/parse path with the fred.py sanitized-error discipline:
    every raise happens outside the except block (so __context__ stays None
    and the key -- which rides in the query string -- can never leak via
    exception chaining), and we only ever quote our own static labels plus a
    key-scrubbed excerpt of soft-failure message bodies, never the raw
    response body or the raw exception message."""
    _throttle()
    failure = None
    resp = None
    try:
        resp = requests.get(API_URL, params=params, timeout=30)
    except requests.RequestException as exc:
        failure = f"Alpha Vantage request failed for {series}: {type(exc).__name__}"
    if failure is None and resp.status_code != 200:
        failure = f"Alpha Vantage HTTP {resp.status_code} for {series}"
    payload = None
    if failure is None:
        try:
            payload = resp.json()
        except ValueError:
            failure = f"Alpha Vantage returned non-JSON body for {series}"
    if failure is not None:
        raise RuntimeError(failure)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Alpha Vantage returned unexpected payload for {series}")
    for bad_key in _SOFT_FAILURE_KEYS:
        if bad_key in payload:
            text = str(payload[bad_key]).replace(api_key, "***")[:_SOFT_FAILURE_EXCERPT_LEN]
            raise RuntimeError(f"Alpha Vantage {bad_key} response for {series}: {text}")
    return payload


def _fetch_equity(series: str, api_key: str) -> pd.Series:
    # TIME_SERIES_DAILY_ADJUSTED is a premium endpoint ("this is a premium API
    # function" per Alpha Vantage docs); the free tier only offers
    # TIME_SERIES_DAILY (outputsize=compact -> latest ~100 observations,
    # which is plenty since run_ingest merges onto the committed deep
    # history -- see store.merge_observations). We deliberately use the raw
    # "4. close" rather than an adjusted close: yahoo.py stores
    # indicators.quote[0].close (also raw/unadjusted), so matching raw-to-raw
    # keeps Alpha Vantage and Yahoo observations splicing consistently
    # instead of silently mixing adjusted and unadjusted history.
    payload = _get_json({
        "function": "TIME_SERIES_DAILY",
        "symbol": series,
        "outputsize": "compact",
        "apikey": api_key,
    }, series, api_key)
    daily = payload.get("Time Series (Daily)")
    if not isinstance(daily, dict) or not daily:
        raise RuntimeError(f"Alpha Vantage returned no observations for {series}")
    dates, values = [], []
    for date, fields in daily.items():
        try:
            values.append(float(fields["4. close"]))
        except (KeyError, TypeError, ValueError):
            continue
        dates.append(date)
    if not values:
        raise RuntimeError(f"Alpha Vantage returned no usable observations for {series}")
    return pd.Series(values, index=pd.to_datetime(dates), name=series).sort_index()


def _fetch_crypto(series: str, api_key: str) -> pd.Series:
    payload = _get_json({
        "function": "DIGITAL_CURRENCY_DAILY",
        "symbol": series,
        "market": "USD",
        "apikey": api_key,
    }, series, api_key)
    daily = payload.get("Time Series (Digital Currency Daily)")
    if not isinstance(daily, dict) or not daily:
        raise RuntimeError(f"Alpha Vantage returned no observations for {series}")
    dates, values = [], []
    for date, fields in daily.items():
        close = fields.get("4. close")
        if close is None:
            continue
        try:
            values.append(float(close))
        except (TypeError, ValueError):
            continue
        dates.append(date)
    if not values:
        raise RuntimeError(f"Alpha Vantage returned no usable observations for {series}")
    return pd.Series(values, index=pd.to_datetime(dates), name=series).sort_index()
