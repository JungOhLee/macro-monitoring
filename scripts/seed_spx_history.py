"""One-time seed: deep S&P 500 history from Yahoo ^GSPC into data/raw/spx.csv.

FRED's SP500 series only carries a trailing 10-year window; the percentile
engine and episode library need history to the 1920s. Run once; thereafter
the daily pipeline appends from FRED SP500.

Note (2026-07-06): the actual seed for this repo (spx, plus rsp/spy/btcusd)
was performed via a browser-relayed Yahoo fetch, not by running this script
directly — Yahoo's query API was 429-ing headless/non-browser clients from
the ingest host at the time. This script remains the reproducible path for
re-seeding whenever Yahoo's chart API is reachable from wherever it's run.
"""
from pipeline import store
from pipeline.ingest.yahoo import fetch_yahoo

s = fetch_yahoo("^GSPC")
s.name = "spx"
store.write_series("spx", s)
print(f"seeded spx: {len(s)} rows, {s.index.min():%Y-%m-%d} .. {s.index.max():%Y-%m-%d}")
