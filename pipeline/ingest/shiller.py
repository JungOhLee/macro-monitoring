from __future__ import annotations

import io

import pandas as pd
import requests

# shillerdata.com is Robert Shiller's actively-maintained current site (verified live:
# updated monthly, latest observation within the current month at implementation time).
# econ.yale.edu is the legacy host and has been observed to lag by years, not months --
# kept only as a fallback so the series degrades gracefully rather than failing outright.
# The `ver=` cache-busting query param on the shillerdata.com CDN link is optional (verified:
# identical payload without it) and is intentionally omitted here for URL stability.
PRIMARY_URL = (
    "https://img1.wsimg.com/blobby/go/e5e77e0b-59d1-44d9-ab25-4763ac982e53/"
    "downloads/dd48d685-0157-4aa8-9ad3-375fd4eef22b/ie_data.xls"
)
FALLBACK_URL = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

# If the primary's latest observation is older than this, also try the fallback and
# keep whichever is fresher -- guards against a silently stale (but HTTP-200) file.
STALE_AFTER_DAYS = 200

SHEET_NAME = "Data"
DATE_COL = 0
HEADER_SCAN_ROWS = 10


def _shiller_date(x: float | str) -> pd.Timestamp:
    """Shiller's "Date" column is a fractional year where the digits after the
    decimal point are a zero-padded 2-digit MONTH, not a decimal fraction of a
    year -- e.g. 1871.1 means October 1871, not "1/10th of the way through
    1871". Float arithmetic on the raw value (e.g. round(frac * 12)) misreads
    this; formatting to a fixed 2-decimal string and parsing the digits
    directly is the only reliable approach."""
    s = f"{float(x):.2f}"
    year_s, _, month_s = s.partition(".")
    return pd.Timestamp(year=int(year_s), month=int(month_s), day=1)


def _find_cape_column(df: pd.DataFrame) -> int:
    """The "Data" sheet has multi-row headers (no single header row) with the
    CAPE/P-E10 column label split across several rows. Scan the first ~10 rows
    top-to-bottom, left-to-right for a cell that is exactly "CAPE" or contains
    "P/E10" -- excluding "TR CAPE" / "TR P/E10", the total-return variant in a
    later column, which also contains the substring "CAPE"."""
    n_rows = min(HEADER_SCAN_ROWS, df.shape[0])
    for r in range(n_rows):
        for c in range(df.shape[1]):
            cell = df.iat[r, c]
            if not isinstance(cell, str):
                continue
            text = cell.strip().upper()
            if "TR" in text:
                continue
            if text == "CAPE" or "P/E10" in text:
                return c
    raise RuntimeError("Shiller: could not locate a CAPE/P-E10 column in the header rows")


def parse_ie_bytes(content: bytes) -> pd.Series:
    df = pd.read_excel(io.BytesIO(content), sheet_name=SHEET_NAME, header=None, engine="xlrd")
    cape_col = _find_cape_column(df)
    dates, values = [], []
    for r in range(df.shape[0]):
        raw_date = df.iat[r, DATE_COL]
        raw_cape = df.iat[r, cape_col]
        if not isinstance(raw_date, (int, float)) or pd.isna(raw_date):
            continue
        if not isinstance(raw_cape, (int, float)) or pd.isna(raw_cape):
            continue
        dates.append(_shiller_date(raw_date))
        values.append(float(raw_cape))
    if not values:
        raise RuntimeError("Shiller: no CAPE observations parsed from workbook")
    s = pd.Series(values, index=pd.DatetimeIndex(dates), name="shiller_cape").sort_index()
    return s[~s.index.duplicated(keep="last")]


def _try_fetch(url: str) -> tuple[pd.Series | None, str | None]:
    try:
        resp = requests.get(url, headers=UA, timeout=30)
    except requests.RequestException as exc:
        return None, f"{type(exc).__name__} for {url}"
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code} for {url}"
    try:
        return parse_ie_bytes(resp.content), None
    except Exception as exc:  # sanitize -- no secrets in this URL, but keep messages clean
        return None, f"{type(exc).__name__}: {exc} for {url}"


def fetch_shiller(source_id: str) -> pd.Series:
    primary, primary_err = _try_fetch(PRIMARY_URL)
    stale = primary is not None and (
        pd.Timestamp.now().normalize() - primary.index.max()
    ).days > STALE_AFTER_DAYS
    fallback, fallback_err = (None, None)
    if primary is None or stale:
        fallback, fallback_err = _try_fetch(FALLBACK_URL)
    candidates = [s for s in (primary, fallback) if s is not None]
    if not candidates:
        raise RuntimeError(
            f"Shiller: fetch failed from both sources (primary: {primary_err}; fallback: {fallback_err})"
        )
    return max(candidates, key=lambda s: s.index.max())
