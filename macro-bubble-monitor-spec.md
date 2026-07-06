# Macro & Market Bubble Monitor — System Spec (v2)

**Owner:** You (solo, personal use)
**Status:** Draft for review — v2 adds Crisis Episode Library & Sequencing Module
**Last updated:** 2026-07-04

---

## 1. Problem Statement

Signals of market froth (valuation extremes, leverage buildup, liquidity shifts, speculative behavior) are scattered across dozens of sources and are easy to miss until after a drawdown. A single dashboard that ingests key macro and market indicators daily, normalizes them into historical percentiles, and compares today's profile against pre-crisis profiles from past episodes would let you evaluate market risk in minutes instead of hours of manual chart-hunting.

## 2. Goals

1. **One glance = market risk read.** A daily-updated dashboard where the overall bubble/risk regime is readable in under 30 seconds.
2. **Historically grounded.** Every indicator expressed as a percentile vs. its own history (ideally 30+ years), not raw values, so "extreme" is objective.
3. **Composite bubble score (0–100)** combining valuation, leverage, liquidity, sentiment, and macro stress pillars.
4. **Crisis comparability.** Today's indicator profile can be compared side-by-side with the run-up to past crises (2000, 2007, 2020, 2021–22), including a "which episode and which stage does today most resemble" readout.
5. **Cycle-stage awareness.** The system tracks *where in the classic pre-crisis sequence* the market currently sits, not just how hot it is.
6. **Alerting.** Notify when any pillar or the composite crosses a threshold or the sequencing stage advances.
7. **Zero-maintenance ingestion.** Automated daily pulls from free APIs; no manual data entry.

## 3. Non-Goals (v1)

- **Trade execution / portfolio management** — monitoring only.
- **Intraday data** — bubbles form over months; daily/weekly/monthly is sufficient.
- **Single-stock analysis** — index/market-level only.
- **Crash prediction claims** — the analog module measures *similarity to past setups*, it does not output crash probabilities. ML forecasting is P2 at most.
- **Multi-user / auth / hosting for others.**

## 4. Indicator Catalog

Five pillars; each indicator normalized to a historical percentile (0–100), pillar scores averaged into the composite. Each indicator also carries a **role tag** — `timing`, `magnitude`, or `confirmation` — used by the sequencing module (Section 5).

### Pillar A — Valuation (weight 30%) — role: magnitude
| Indicator | Source | Frequency |
|---|---|---|
| Buffett Indicator (US market cap / GDP) | FRED (`WILL5000PRFC` / `GDP`) | Qtrly GDP, daily mkt cap |
| Shiller CAPE (S&P 500) | Shiller dataset (Yale CSV) or multpl scrape | Monthly |
| S&P 500 forward P/E | yfinance / scrape | Weekly |
| Equity risk premium (CAPE yield − 10Y real yield) | Derived, FRED `DFII10` | Monthly |
| Price-to-sales, S&P 500 | multpl / scrape | Monthly |

### Pillar B — Leverage & Credit (weight 25%) — role: timing
| Indicator | Source | Frequency |
|---|---|---|
| FINRA margin debt (level & YoY %) | FINRA monthly stats | Monthly |
| Margin debt / GDP | Derived | Monthly |
| High-yield credit spread | FRED `BAMLH0A0HYM2` | Daily |
| Household & corporate debt / GDP | FRED | Quarterly |
| Bank lending standards (SLOOS) | FRED `DRTSCILM` | Quarterly |

### Pillar C — Liquidity & Monetary (weight 20%) — role: timing
| Indicator | Source | Frequency |
|---|---|---|
| M2 YoY growth | FRED `M2SL` | Monthly |
| Fed balance sheet YoY | FRED `WALCL` | Weekly |
| Net liquidity (Fed BS − TGA − RRP) | FRED `WALCL`,`WTREGEN`,`RRPONTSYD` | Weekly |
| Real Fed Funds rate | FRED `FEDFUNDS`,`CPILFESL` | Monthly |
| 10Y–2Y and 10Y–3M yield curve | FRED `T10Y2Y`,`T10Y3M` | Daily |

### Pillar D — Sentiment & Speculation (weight 15%) — role: timing/confirmation
| Indicator | Source | Frequency |
|---|---|---|
| VIX level & term structure (VIX vs VIX3M) | yfinance `^VIX`,`^VIX3M` | Daily |
| Put/call ratio (CBOE equity) | CBOE / scrape | Daily |
| AAII bull-bear spread | AAII weekly CSV | Weekly |
| IPO/SPAC volume, % unprofitable IPOs | Manual/scrape | Quarterly |
| Crypto total market cap YoY | CoinGecko API | Daily |

### Pillar E — Macro Stress & Breadth (weight 10%) — role: confirmation (breadth: timing)
| Indicator | Source | Frequency |
|---|---|---|
| Sahm rule gap | FRED `SAHMREALTIME` | Monthly |
| ISM Manufacturing PMI | scrape | Monthly |
| % of S&P 500 above 200-day MA | Computed via yfinance | Daily |
| S&P 500 distance from 200-day MA (%) | yfinance | Daily |
| USD index (DXY) trend | yfinance `DX-Y.NYB` | Daily |

### Composite Bubble Score
```
score = 0.30·A + 0.25·B + 0.20·C + 0.15·D + 0.10·E
```
Direction-inverted indicators defined in config (e.g., low VIX / tight HY spreads = froth). Regime bands: 0–40 **Cool**, 40–70 **Warm**, 70–85 **Frothy**, 85–100 **Bubble-risk**.

## 5. Crisis Episode Library & Sequencing Module (new in v2)

### 5.1 Episode Library
Store full indicator histories for a window of **T−24 months to T+12 months** around each market peak:

| Episode | Peak (T) | Type | Notes |
|---|---|---|---|
| Dot-com | Mar 2000 | Endogenous bubble | Textbook valuation + breadth divergence |
| GFC | Oct 2007 | Endogenous credit bubble | Best case study for credit/lending indicators |
| COVID | Feb 2020 | **Exogenous shock — control case** | Little froth beforehand; used to test false-negative behavior |
| Post-COVID froth | Jan 2022 | Endogenous liquidity bubble | Margin debt, SPAC/IPO, crypto signals strongest here |

For each episode, persist indicator **percentile snapshots** at T−24, T−18, T−12, T−9, T−6, T−3, T−1, T, T+6, T+12 months in an `episode_snapshots` table. Indicators lacking history for an episode (e.g., RRP before 2013) are marked N/A and excluded from that episode's comparisons.

### 5.2 Analog Similarity View
Daily job computes distance (cosine similarity on the vector of indicator percentiles, restricted to indicators available in both periods) between **today** and every episode snapshot. Dashboard shows:
- "Closest analog: **GFC at T−9 months** (similarity 0.87)" style readout, top-3 analogs.
- Radar/spider chart overlaying today's five pillar scores on any selected episode snapshot.
- Per-indicator table: today's percentile vs. the same indicator at each episode's T−6.

### 5.3 Sequencing State Machine
Encodes the classic pre-crisis ordering. Each stage has explicit trigger conditions evaluated daily; the dashboard shows the current stage, which stages have fired, and when.

| Stage | Name | Trigger (configurable) | Historical lead time to peak* |
|---|---|---|---|
| 1 | Valuation stretch | Pillar A > 80th pct for 6+ months | Years (magnitude signal only) |
| 2 | Leverage peak | Margin debt YoY rolls over from >85th pct | ~2–4 months (2000, 2007, 2021) |
| 3 | Policy/curve turn | 10Y–3M inverts, then **re-steepens** after inversion | Inversion ~6–16 months; re-steepening is the near-term danger zone |
| 4 | Credit widening | HY spread rises >100bp off its 12-month low | ~3–12 months (2007: spreads bottomed ~4 months before equity peak) |
| 5 | Breadth breakdown | Index within 2% of high while % above 200-DMA < 55% | Weeks–months (2000, 2021) |
| 6 | Price confirmation | Index closes <200-DMA and Sahm/VIX confirm | At/after peak (confirmation only) |

\* Approximate, based on 2–3 observations each — displayed in the UI with this caveat. COVID-2020 skipped stages 1–5 entirely; the UI must show "sequence not engaged" as a valid state rather than forcing a stage.

### 5.4 Role tags & how to read them
- **Timing** (curve re-steepening, credit spreads, SLOOS, margin-debt rollover, breadth divergence): the "look here now" signals when composite is elevated.
- **Magnitude** (CAPE, Buffett, ERP): predicts *how bad*, never *when*. Elevated for years pre-2000 — the UI should never present these as timing signals.
- **Confirmation** (Sahm, VIX spike, price <200-DMA): validates that the turn happened; used to declare regime change, not anticipate it.

## 6. System Architecture

```
[Scheduler: cron / GitHub Actions daily 06:00]
        │
        ▼
[Ingestion — Python: fredapi · yfinance · scrapers (FINRA, Shiller, AAII, CBOE)]
        │
        ▼
[Storage — SQLite/DuckDB]
  series_meta · observations · scores(date, pillar, value)
  episode_snapshots(episode, offset_months, series_id, percentile)
  sequence_state(date, stage, fired_stages, triggers)
        │
        ▼
[Compute — pandas]
  percentiles → pillar & composite scores → analog similarity → sequencing state machine
        │
        ├──▶ [Alerts] Telegram / ntfy.sh: regime change, pillar >90th pct, stage advance
        └──▶ [Dashboard — Streamlit] gauge · pillars · analog view · sequence tracker · drill-downs
```

Stack: Python 3.11+, `fredapi`, `yfinance`, `pandas`, SQLite, Streamlit, cron or GitHub Actions. Cost: $0.

## 7. User Stories

- As the sole user, I want the dashboard to show composite score, pillar scores, and their trends, so I can judge regime in one glance.
- As the sole user, I want to see which past crisis run-up today most resembles and at what stage, so I have historical context instead of a bare number.
- As the sole user, I want a sequence tracker showing which classic pre-crisis stages have fired and when, so I know *which indicators to watch next* rather than watching everything equally.
- As the sole user, I want each indicator's role (timing/magnitude/confirmation) visible in the UI, so I don't misread a magnitude signal (CAPE) as a timing signal.
- As the sole user, I want alerts on regime change, pillar extremes, and sequence-stage advances.
- As the sole user, I want stale-data badges per series, so broken scrapers can't silently corrupt scores.
- As the sole user, I want to add indicators and edit stage-trigger thresholds via config, not code.

## 8. Requirements

### Must-Have (P0)
1. **Config-driven indicator registry** (source, series ID, frequency, direction, pillar, weight, **role tag**).
2. **Daily automated ingestion** with per-series freshness tracking; one failure doesn't abort the run.
3. **Percentile normalization** (full history, min 10 years) + stored z-scores.
4. **Composite + pillar scores** persisted daily.
5. **Episode library**: snapshots for the 4 episodes at defined offsets, built once from historical data with a rebuild command.
   - [ ] Indicators without history for an episode are excluded, not zero-filled
6. **Analog similarity view**: top-3 closest episode snapshots + radar overlay + per-indicator comparison table.
7. **Sequencing state machine** with config-defined triggers, persisted state, and "sequence not engaged" as a first-class state.
8. **Dashboard**: gauge, pillar bars, analog view, sequence tracker, indicator drill-downs, freshness badges, role-tag labels.
9. **Alerts** (Telegram or ntfy.sh): regime change, pillar >90th pct, stage advance; 7-day cooldown per alert type.

### Nice-to-Have (P1)
- Backtest replay: run score + sequencer over full history and overlay on S&P 500 to validate against all 4 episodes.
- Weekly email digest (score, movers, stage status).
- Pillar correlation matrix (double-counting check).
- User-defined custom episodes (e.g., 1990 Japan for study).

### Future (P2)
- International market composites; housing pillar.
- ML regime classifier — only after the rule-based sequencer is validated.
- LLM-generated daily commentary.

## 9. Success Metrics

- **Reliability:** ≥ 99% scheduled runs complete; no series stale >7 days unalerted.
- **Backtest sanity:** replayed sequencer reaches stage ≥4 before the 2000, 2007, and 2022 peaks, and stays at "not engaged"/stage ≤2 through 2019 (COVID control) — evaluated once in Phase 3.
- **Usage:** checked ≥3×/week in month 1; <30 min/month maintenance after.
- **Interpretability:** you can explain any day's analog readout from the per-indicator table alone.

## 10. Timeline & Phasing

- **Phase 1 (weekend 1):** FRED + yfinance ingestion, SQLite schema, percentile engine, composite score, CLI output (~15 indicators; skip scrapers).
- **Phase 2 (weekend 2):** Streamlit dashboard + Telegram alerts + scheduling.
- **Phase 3 (weekend 3):** Episode library build + analog similarity view + sequencing state machine + backtest replay validation.
- **Phase 4 (ongoing):** scraper indicators (FINRA, AAII, Shiller), weekly digest, threshold tuning.

Note: the episode library needs deep history — prefer FRED series with pre-2000 coverage; margin debt pre-2010 requires FINRA/NYSE historical file (one-time manual import is acceptable).

## 11. Open Questions

- **(You, blocking):** Local cron vs. GitHub Actions? Determines storage.
- **(You, non-blocking):** Percentile window — full history vs. rolling 20-year? Compute both; display full-history by default.
- **(You, non-blocking):** Analog distance metric — cosine on percentiles vs. Euclidean on z-scores? Start cosine; compare in backtest.
- **(Data, non-blocking):** Pre-2000 availability of HY spreads (FRED starts 1996) and margin debt — episode comparisons for dot-com will use a reduced indicator set; confirm it's still ≥15 indicators.

## 12. Risks

- **Small-n overfitting:** only 3 endogenous episodes + 1 control. Stage triggers tuned to fit these perfectly will be curve-fit. Mitigation: keep triggers simple/round-number, document rationale, treat lead times as ranges not points.
- **Structural regime drift:** valuations are structurally higher post-1995; full-history percentiles may read "frothy" permanently. Mitigation: dual full-history/rolling-20y percentiles.
- **Scraper rot:** stale badges + graceful pillar degradation.
- **False confidence:** analog similarity is pattern-matching, not probability. Dashboard footer states: *monitoring context, not a trading signal.*
