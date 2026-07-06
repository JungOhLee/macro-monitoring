# Macro Bubble Monitor

**Live dashboard: https://jungohlee.github.io/macro-monitoring/**

A personal macro-economy monitor: 18 indicators across five pillars
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
  `python -m pipeline run && python -m pipeline export`.
- **Status:** Phase 1-2 complete (scoring, dashboard, alerts, narrative drafts).
  Phase 3 adds the episode library, analog similarity, sequencing state machine,
  and backtest. Phase 4 adds scraper-based indicators (margin debt, AAII, put/call).

*Monitoring context, not a trading signal.*
