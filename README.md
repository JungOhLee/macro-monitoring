# Macro Bubble Monitor

**Live dashboard: https://jungohlee.github.io/macro-monitoring/**

A personal macro-economy monitor: 21 indicators across five pillars
(valuation, leverage, liquidity, sentiment, macro stress), each expressed as a
historical percentile and combined into a 0-100 composite bubble score -
updated daily by GitHub Actions, with crisis-comparison context.

- **Spec:** [`macro-bubble-monitor-spec.md`](macro-bubble-monitor-spec.md) (v2) +
  [validated design](docs/superpowers/specs/2026-07-05-macro-monitor-design.md)
- **How it works:** Actions cron -> FRED/Yahoo ingest -> percentile scoring ->
  `data/` CSVs committed -> static site JSON -> GitHub Pages. Alerts arrive as
  labeled GitHub issues (which email the owner).
- **Local use:** clone; `pip install -e '.[dev]'`; view with
  `python -m http.server -d site` (no credentials needed). To refresh data
  yourself: put a free FRED key in `.env` (`FRED_API_KEY=...`) and run
  `python -m pipeline run && python -m pipeline export`. `rsp`/`spy`/`btcusd`
  use Alpha Vantage when `ALPHAVANTAGE_KEY` is set (in `.env` locally or as a
  repo secret in CI, where it's active as of 2026-07-06); RSP/SPY fetch the
  free-tier `TIME_SERIES_DAILY` endpoint (`outputsize=compact`, raw `"4.
  close"`) rather than the premium `TIME_SERIES_DAILY_ADJUSTED` - matching
  Yahoo's own raw (unadjusted) close so the two sources splice consistently
  onto one history instead of mixing adjusted and unadjusted observations.
  Without a key (or on any Alpha Vantage failure), all three fall back to
  Yahoo's v8 chart API, which works from residential IPs but 429s
  intermittently from GitHub Actions runners - 14-day staleness budgets
  absorb the blocked stretches.
- **Status:** Phase 1-2 complete (scoring, dashboard, alerts, narrative drafts).
  **Phase 3 complete:** role-aware composite + stress gauge, analog similarity
  with SVG radar, pre-crisis sequence tracker,
  [backtest page](https://jungohlee.github.io/macro-monitoring/backtest.html)
  with validation criteria and base rates, auto-generated indicator firing
  timelines on episode pages, margin-debt data (FINRA manual-source import),
  and Shiller CAPE + equity-risk-premium indicators (valuation pillar now
  averages Buffett indicator, CAPE, and ERP). **Phase 4 complete:** scored
  history extended back to 1975, sequencer calibration (intra-window credit
  widening, breadth near-high window, staleness-bound price confirmation,
  credit-led engagement path), regime bands refit to the composite's own
  historical quantiles (cool<64, warm<76, frothy<83, bubble_risk>=83, vs. the
  original spec-guessed 40/70/85), analog similarity now demeaned before
  cosine so it actually discriminates (display/base-rate threshold 0.98,
  itself the 90th percentile of the demeaned similarity distribution), and a
  dormant Alpha Vantage path for the Yahoo-sourced indicators above. Honest
  caveat: backtest validation now passes 4 of 5 criteria (gfc, 2019-quiet-
  control, postcovid, rec1990), with dotcom's FAIL unchanged for a documented
  structural/data-availability reason - see the design doc §13 note (which
  also records a mid-task honesty-gate stop-and-fix on the 2019 control, and
  a nuance on reading the 1980-81 Volcker period's leverage pillar alongside,
  not instead of, the composite). Ongoing: scraper-based indicators (AAII,
  put/call) remain manual/partial.

*Monitoring context, not a trading signal.*
