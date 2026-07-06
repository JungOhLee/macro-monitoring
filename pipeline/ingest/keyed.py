from __future__ import annotations

import pandas as pd
import requests

API_URL = "https://www.alphavantage.co/query"

# Alpha Vantage symbols that use the digital-currency endpoint; everything else
# is treated as an equity/ETF symbol on TIME_SERIES_DAILY_ADJUSTED.
_CRYPTO_SYMBOLS = {"BTC"}

# Free-tier responses are HTTP 200 with a JSON body carrying one of these keys
# for rate limits, premium-endpoint refusals, or bad symbols -- never parsed as
# data, never persisted with their (possibly key-echoing) message text.
_SOFT_FAILURE_KEYS = ("Note", "Information", "Error Message")


def fetch_alphavantage(series: str, api_key: str) -> pd.Series:
    if series in _CRYPTO_SYMBOLS:
        return _fetch_crypto(series, api_key)
    return _fetch_equity(series, api_key)


def _get_json(params: dict, series: str) -> dict:
    """Shared request/parse path with the fred.py sanitized-error discipline:
    every raise happens outside the except block (so __context__ stays None
    and the key -- which rides in the query string -- can never leak via
    exception chaining), and we only ever quote our own static labels, never
    the response body or the raw exception message."""
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
            raise RuntimeError(f"Alpha Vantage {bad_key} response for {series}")
    return payload


def _fetch_equity(series: str, api_key: str) -> pd.Series:
    payload = _get_json({
        "function": "TIME_SERIES_DAILY_ADJUSTED",
        "symbol": series,
        "outputsize": "full",
        "apikey": api_key,
    }, series)
    daily = payload.get("Time Series (Daily)")
    if not isinstance(daily, dict) or not daily:
        raise RuntimeError(f"Alpha Vantage returned no observations for {series}")
    dates, values = [], []
    for date, fields in daily.items():
        try:
            values.append(float(fields["5. adjusted close"]))
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
    }, series)
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
