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
  repo secret in CI), otherwise Yahoo - currently dormant pending a key.
- **Status:** Phase 1-2 complete (scoring, dashboard, alerts, narrative drafts).
  **Phase 3 complete:** role-aware composite + stress gauge, analog similarity
  with SVG radar, pre-crisis sequence tracker,
  [backtest page](https://jungohlee.github.io/macro-monitoring/backtest.html)
  with validation criteria and base rates, auto-generated indicator firing
  timelines on episode pages, margin-debt data (FINRA manual-source import),
  and Shiller CAPE + equity-risk-premium indicators (valuation pillar now
  averages Buffett indicator, CAPE, and ERP). Honest caveat: backtest
  validation currently passes 2 of 4 criteria (postcovid, 2019-quiet-control),
  with documented reasons for the other two (dotcom, gfc) - see the design
  doc §13 note. Phase 4 adds scraper-based indicators (AAII, put/call) and
  threshold tuning against the backtest.

*Monitoring context, not a trading signal.*
