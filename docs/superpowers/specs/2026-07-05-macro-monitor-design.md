# Macro & Market Bubble Monitor — Validated Design

**Date:** 2026-07-05 (rev. 2 after adversarial design review)
**Status:** Approved design (supersedes the architecture sections and the affected data sources of `macro-bubble-monitor-spec.md` v2; that spec's pillar structure, weights, role tags, episode definitions, and success intent remain the source of truth)
**Owner:** jolee (solo, personal use)

---

## 1. Purpose

A daily-updated, historically grounded market-risk monitor. It ingests ~27 macro/market indicators, normalizes each to historical percentiles, rolls them into five pillar scores and a composite bubble score (0–100), compares today's profile against the run-ups to four past crises (2000, 2007, 2020, 2022), and tracks where the market sits in the classic pre-crisis sequence. The ultimate goal: understand *why* past crises happened and whether today's setup resembles any of them — readable in under 30 seconds from any device, in a fully graphical dashboard.

## 2. Decisions Made (2026-07-05)

| Decision | Choice | Rationale |
|---|---|---|
| Where ingestion runs | **GitHub Actions** (daily cron + manual trigger) | $0, never misses a run when the laptop sleeps; the repo itself is the deployment |
| Repo visibility & hosting | **Public repo + GitHub Pages** | Pages is free on public repos; all data is public-source; one URL from any device |
| Dashboard technology | **Static site (HTML + vendored Plotly partial bundle) reading pre-computed JSON** | GitHub Pages cannot run a Streamlit server; static loads fast on mobile; all intelligence stays in Python |
| Storage | **Append-mostly CSVs committed to the repo** (no committed SQLite) | Line-level diffs; git history stays small; binary DB files bloat history. "Append-mostly": rows inside a per-series revision window may be rewritten in place (see §5) |
| Alerts | **GitHub issues with typed labels → GitHub's own email notification** | Zero secrets/SMTP; browsable alert history; per-label 7-day cooldown |
| Percentile window | Compute **both** full-history and rolling-20-year. **Full-history is canonical** for all persisted scores, regime bands, alerts, sequencer triggers, episode snapshots, and analog vectors; rolling-20y is display-only (exported as parallel fields) | Resolves spec open question; mitigates structural-regime-drift risk without forking the system's logic |
| Analog distance | **Cosine similarity on full-history percentile vectors** first; Euclidean-on-z-scores comparison deferred to backtest phase | Per spec open question |
| Stored z-scores (spec P0-3) | **Superseded: computed in memory each run**, exported in `indicators.json` for the latest date only | Deterministic from raw history; storing them per-observation would bloat daily commits for zero information gain |
| Local access | A clone is fully self-sufficient **with zero credentials**: `site/data/*.json` is committed every run, so `git pull` + `python -m http.server -d site` shows the current dashboard; `pipeline export` also rebuilds it offline from committed CSVs | Viewing must never require an API key |
| Alerting kept in scope | Regime/pillar/stage alerts retained | Spec v2 Goal 6 and P0-9; user confirmed email as the channel |
| IPO/SPAC indicator | **Deferred to manual/P2** | Quarterly, manual-entry only; not worth blocking phases on |

Credentials: **one required secret, `FRED_API_KEY`** (free). Everything else (Stooq, Shiller, CBOE-forward, FINRA) is keyless. Alerts and commits use the workflow's built-in `GITHUB_TOKEN`.

### 2b. Data-source substitutions (design review, 2026-07-05)

The review verified each spec source's fetchability from a GitHub Actions runner. These substitutions are binding; `registry.yaml` records old → new for traceability.

| Spec source | Problem found | Replacement |
|---|---|---|
| Buffett numerator `WILL5000PRFC` | FRED removed all Wilshire series (June 2024); series is dead | **`NCBEILQ027S` / GDP** (corporate equities liability, quarterly, history to 1945). Optional Wilshire-site scrape in Phase 4 as a secondary variant |
| yfinance as a primary source | Yahoo aggressively 429-blocks datacenter/Actions IPs (chronic, not occasional) | **FRED `VIXCLS`** (VIX, 1990→), **FRED `DTWEXBGS` spliced with `DTWEXM`** (trade-weighted dollar, 1973→), **Stooq `^spx`** (S&P 500 price → 200-DMA distance; keyless, datacenter-tolerant). yfinance stays only as a pinned, best-effort fallback (e.g. `^VIX3M`), marked `best_effort: true` in the registry |
| % of S&P 500 above 200-DMA | Needs daily history for ~500 constituents + point-in-time membership — not freely fetchable | **Breadth-divergence proxy: RSP/SPY equal-weight vs cap-weight ratio** (Stooq, 2003→). Stage 5 trigger redefined accordingly (§8b). Excluded from dot-com episode comparisons per the no-history exclusion rule |
| S&P 500 forward P/E | No stable free source with history | **Dropped.** CAPE, price-to-sales, and ERP already cover valuation |
| ISM Manufacturing PMI | Removed from FRED (licensing); scraping ismworld.org is fragile/ToS-gray | **Chicago Fed National Activity Index `CFNAI`** (FRED, 1967→) |
| CBOE equity put/call CSV | Free historical CSV ends Oct 2019 | Seed from the free archive; **accumulate forward from CBOE's daily market-stats JSON** (cdn.cboe.com) in the repo — the splice date is recorded in the registry and shown in the drill-down |
| AAII weekly CSV | Historical file is member-only | One-time manual import of historical data + weekly scrape of the public current-week page. **This is the single exception to zero-manual-entry** |
| CoinGecko crypto market cap | Keyless tier rate-limits datacenter IPs; historical endpoint is paid | **BTC price YoY via Stooq** (keyless, history to 2010) as the crypto-froth proxy |
| IPO/SPAC volume | Manual only | Deferred (see §2) |

**Amendment 2026-07-06 (Task 6 implementation):** Stooq now serves a JavaScript anti-bot challenge to all non-browser clients (verified live from two contexts), making it unfetchable headlessly — the §2b substitutions relying on Stooq are amended: `spx` daily updates come from FRED `SP500` (trailing 10-year window) layered over a one-time committed deep-history seed (Yahoo `^GSPC`, 1927→); `rsp`/`spy`/`btcusd` come from Yahoo's v8 chart JSON API fetched with `range=max` each run (full-history fetches self-heal gaps; works from residential IPs, intermittently from Actions runners — 14-day staleness budgets absorb blocked stretches and any local `pipeline run` heals them). The Stooq ingest module was removed. Additionally, FRED's ICE BofA HY OAS series now carries only a trailing ~3-year window (license), so the scored credit-spread indicator is Moody's Baa−10Y spread (FRED BAA10Y, 1986→); the HY series remains ingested solely for the Phase 3 stage-4 trigger.

**Amendment 2026-07-06 (Phase 3 kickoff, user-approved):** The composite becomes **role-aware**, per spec v2 §5.4's own reading rules: only `timing` and `magnitude` indicators feed pillar scores and the composite (the anticipatory "bubble score"); `confirmation` indicators (Sahm, CFNAI, S&P-vs-200DMA, dollar) are excluded from it and instead aggregate into a separate **Confirmation/stress gauge** (0–100, mean froth of confirmation indicators) shown alongside the composite. Rationale: the v1 composite rose during crashes as stress signals fired, compressing the score range (Bubble-risk ≥85 never fired 1990–2026; Dec-2008 read "warm"). Regime bands stay as-is pending backtest validation. Score CSVs are regenerated under the new methodology (pre-change history retrievable from git). Dashboard additions in the same release: per-pillar tabs on the Score History chart, episode-peak markers on the indicator drill-down charts, and the stress gauge in the status strip.

**Amendment 2026-07-06 (Shiller CAPE + ERP landed, closing the last Phase 3 gap):** `pipeline/ingest/shiller.py` fetches Robert Shiller's `ie_data.xls` workbook and extracts the CAPE (P/E10) column from the "Data" sheet's multi-row header. Live-verified at implementation time: **shillerdata.com is the actively-maintained current host** (latest observation same-month) and is registered as primary; **econ.yale.edu is the legacy host**, observed nearly 3 years stale (last observation Sep 2023), and is kept only as a fallback used when the primary fails or its latest observation is >200 days old. The `ie_data.xls` date column is a fractional year where the digits after the decimal point are a zero-padded 2-digit month (e.g. `1871.1` = October, not "1/10th of a year") — parsed by formatting to a fixed 2-decimal string, not by float arithmetic. New series `shiller_cape` (monthly) and `dfii10` (FRED `DFII10`, 10Y TIPS real yield, daily since 2003) back two new valuation-pillar indicators: `cape` (direct CAPE percentile) and `erp` (equity risk premium = CAPE earnings yield `100/CAPE` minus the 10Y real yield; only defined from ~2003 onward since `DFII10` has no earlier history, so it starts qualifying for the percentile engine's 10-year gate around 2013-2014). The valuation pillar now averages Buffett + CAPE (+ ERP once qualifying), moving its full-history percentile only marginally (both Buffett and CAPE were already near their historical highs) but visibly changing the pre-2003 episode snapshots: **dotcom (2000) now has CAPE data at every T-offset** (CAPE history runs back to 1881) while ERP is correctly absent (no TIPS market existed then). Re-seeding the sequencer and backtest against the revised valuation-pillar history left today's headline sequence state unchanged (`engaged=true`, `current_stage=3`) and left the dotcom/gfc backtest criteria unchanged (still FAIL, for the same structural/cadence reasons as the §13 note), but **flipped the 2019-quiet-control criterion from FAIL to PASS** (0 engaged months in 2019 vs. 1 previously) — the blended valuation measure is less prone to the transient 126-consecutive-day stage-1 trigger that a Buffett-only valuation pillar hit in Dec 2019, taking the backtest from 1-of-4 to 2-of-4 passing. (Historical per-stage detail below current_stage — e.g. stage 4's recorded `fired_date` in the sequencer state — also shifted for some entries, purely as a downstream consequence of the valuation pillar's daily trajectory changing the exact months in which the sequencer's 20%-drawdown reset fired during the volatile 2022 bear market; this doesn't affect today's engaged/current_stage reading.)

**Amendment 2026-07-06 (historical episodes, user-requested):** The episode set expands beyond 2000. Episodes carry a `library` flag: **library episodes** get full treatment (snapshots at offsets, analog candidacy, narrative page, firing timeline) and require >=8 qualified indicators at pre-peak offsets; **marker-only episodes** appear as chart markers wherever the data reaches but have no snapshot page. Verified against live coverage: 1973-01-11 oil-shock bear (8 qualified), 1980-11-28 Volcker double-dip (9), 1987-08-25 Black Monday (11), 1990-07-16 recession bear (11) join as library episodes; 1929-09-16 Great Depression crash and 1937-03-10 relapse (CAPE-only coverage) join as marker-only. Crisis markers on all charts are unified: derived from `episodes.yaml` (single source; `thresholds.yaml` `episode_peaks` retired), exported as `crisis_markers` with names for hover labels, styled to distinguish library (red) from marker-only (gray). The backtest replay start moves 1997->1987 adding an honest 1990 criterion (stages 3/4 have raw data from 1982/1986; 1987 itself sits inside the warm-up window and gets no criterion).

**Amendment 2026-07-06 (Phase 4 Task 3 — regime bands recalibrated to historical score quantiles, UI single-sourcing):** The Phase 3 kickoff amendment above left the regime bands (cool<40, warm<70, frothy<85, bubble_risk>=85) "as-is pending backtest validation," noting Bubble-risk >=85 had never fired 1990-2026. They were spec guesses, never fit to the actual score distribution. Following Task 1's extension of `score_start` back to 1975-01-01, the full-window composite's empirical quantiles over its complete 1975-2026 history (~13,439 daily observations) were computed directly: **50th percentile = 64.09, 85th percentile = 76.33, 95th percentile = 82.96**. New bands, rounded to the nearest integer and anchored to these quantiles: **cool < 64** (50th=64.09), **warm < 76** (85th=76.33), **frothy < 83** (95th=82.96), **bubble_risk >= 83** (unchanged top bound of 100). Band *names* are unchanged; only the interior edges moved. `stress_bands`, `score_start`, and the sequencer block were untouched.

Honest before/after mapping (full-window composite; numeric scores unchanged by this task):
- Today (2026-07-06, score 65.76): **warm -> warm** (no change; 64 <= 65.76 < 76 both before and after).
- 2000-03-24 dotcom peak (score 71.01, 74.4th pctile): **frothy -> frothy**.
- 2021-11-08 postcovid-era high (score 74.53, 82.6th pctile): **frothy -> frothy**.
- 1987-08-25 Black Monday peak (score 68.22, 65.9th pctile): **warm -> warm**.
- 2007-10-09 GFC peak (score 71.71, 76.2nd pctile): **frothy -> frothy**.

A surprising finding surfaced during this recalibration, reported honestly rather than smoothed over: the Phase 3 note that "Bubble-risk >=85 never fired 1990-2026" was accurate for the shorter window that existed at the time it was written, but Task 1's subsequent extension of the full window back to 1975 changed the empirical picture — under the *old* 85-upper bubble_risk band, the full-window composite actually **did** cross into bubble_risk historically: 135 daily rows, intermittently from Oct-1995 through Jul-1998 (max 86.19 on 1998-06-09) plus one brief week 2007-02-16 to 2007-02-23. Under the *new* 83-upper band it fires more often and earlier across the same two eras (652 days total, intermittently Jul-1995 through Aug-1998 and Feb-2005 through Feb-2007) [span attribution corrected 2026-07-06 after task review: the original amendment text attributed the wider new-band spans to the old band and undercounted its rows] — i.e. bubble_risk is not a dead band under either the old or the recalibrated bands once the pre-1990 and 1990s history is included; it simply never fires in the post-2007 era covered by today's reading or the 2021 high.

Regime labels are stamped in two places: the `regime` column of `data/scores/composite.csv` (via `regime_for()` in `pipeline/compute/scores.py`) and every `site/data/*.json` export (`latest.json`'s `composite.<window>.regime`, plus `history.json`'s `regime_bands` field, which was already exported prior to this task). Both were regenerated under the new bands; the underlying numeric composite scores are byte-identical before and after (verified by a full local recompute from already-ingested raw data, diffed column-by-column against the pre-change CSV, then re-run a second time to confirm the regenerated artifacts are byte-for-byte deterministic).

`site/assets/app.js` no longer hardcodes 40/70/85: the gauge's axis ticks and step ranges, the pillar-bar color thresholds, and the Score History chart's band shading all read the three interior edges from `HISTORY.regime_bands` (loaded from `history.json`) via a shared `regimeEdges()` helper, falling back to the old 40/70/85 constants only if that field is ever absent from the data. The confirmation-stress gauge (`renderStress`, driven by `stress_bands`) was deliberately left untouched — it renders the backend-computed stress *label string* directly and never hardcoded numeric thresholds in the first place.

One side effect worth noting: because a single shared `regime_bands` array applies to both the `full` and `rolling20y` windows (by design, per the "full-history is canonical" decision above), today's rolling20y composite (58.82) flips from **warm** (old bands: 40<=58.82<70) to **cool** (new bands: 58.82<64). This is expected given the bands were calibrated only against the canonical full-history distribution, not a separate rolling-window distribution; the rolling20y label is a secondary display field, not what `alert:regime` or the sequencer evaluate.

Because the *full-window* composite's regime label for today (2026-07-06) does not change (warm -> warm), no `alert:regime` issue is expected from this specific transition on the next scheduled CI run. Had the recalibration flipped today's label, that would have produced one legitimate, expected one-time regime-change alert (comparing the last two rows of `data/scores/composite.csv`).

**Amendment 2026-07-06 (Phase 4 Task 4 — demeaned analog similarity for real discrimination):** The §2 decision "cosine similarity on full-history percentile vectors" (line: Analog distance) computed raw cosine on all-positive 0–100 percentile vectors, which floors similarity near ~0.70–1.0 regardless of how dissimilar two profiles actually are (any two vectors of positive numbers share the same orthant) — the backtest's own base-rate check showed the old 0.8 display threshold firing in every single replay month (474/474, 371 of them outside the 24-month pre-crisis windows), i.e. no real discrimination at all. `pipeline/compute/analogs.cosine` now subtracts 50.0 (the neutral percentile) from every element of both vectors before the dot/norm computation, so similarity spans the full [-1, 1] range (a zero-norm guard still returns `None` for a perfectly-neutral all-50s vector, whose demeaned form is all zeros); the Euclidean tiebreak needed no code change since subtracting the same constant from both operands of a squared difference cancels out and leaves it unchanged. Today's top-3 analogs dropped from a narrow, uninformatively-high band (dotcom T-24 0.9618, dotcom T-9 0.9466, gfc T-9 0.9439) to a visibly lower, more spread set (dotcom T-24 0.8157, gfc T-9 0.7064, gfc T-3 0.6924 — dotcom T-9 fell out of the top-3 entirely). The new base-rate/display threshold is anchored honestly to the demeaned distribution rather than chosen to flatter today's reading: `monthly_top1_similarities()` over the full 1987–2026 replay (474 months) has median=0.8433, p75=0.9475, p90=0.9819, and the 90th percentile rounded to 2dp (**0.98**) replaces the old, un-derived **0.8** in `run_backtest`'s `base_rate.threshold` (`site/assets/app.js`'s base-rate copy already reads this value from `backtest.json` rather than hardcoding it, so no UI code change was needed there). At the old 0.8 cut, demeaning alone dropped the outside-window count from 371/474 to 197/474 (inside stayed 103/474, unchanged); at the new 0.98 threshold the base rate is 11/474 outside pre-crisis windows vs. 40/474 inside — a real, if still small-n, skew toward the pre-crisis case. The five backtest criteria rows (stage-based, independent of analog similarity) are byte-identical before and after this change.

**Amendment 2026-07-06 (Phase 4 Task 5 — keyed market-data source with Yahoo fallback, dormant):** The §2b Task 6 amendment above noted `rsp`/`spy`/`btcusd` are Yahoo-only and only "intermittently" fetchable from Actions runners (429s). A new `pipeline/ingest/keyed.py` module adds Alpha Vantage as an optional primary source for these three: `fetch_alphavantage` calls `TIME_SERIES_DAILY_ADJUSTED` (RSP, SPY — adjusted close) or `DIGITAL_CURRENCY_DAILY` (BTC — USD close), following the same sanitized-error discipline as `fred.py` (raises happen outside `except` blocks so `__context__` stays `None`; error strings never quote the response body or exception message, only static labels, so the key — which rides in the query string — cannot leak via exception chaining or a persisted `freshness.json` string). Alpha Vantage's free tier answers HTTP 200 with a `Note`/`Information`/`Error Message` JSON key for rate limits, premium-endpoint refusals, and bad symbols; all three are treated as fetch failures, never parsed as data. `registry.yaml`'s `rsp`/`spy`/`btcusd` series now declare `source: alphavantage` (source_id RSP/SPY/BTC); dispatch in `pipeline/ingest/__init__.py` is keyed-then-fallback: no `ALPHAVANTAGE_KEY` env var -> straight to `fetch_yahoo` (today's behavior, byte-identical); key present -> try Alpha Vantage first, and on ANY failure (including the soft-failure JSON shapes) fall back to `fetch_yahoo` — a fallback success counts as a plain success, not a partial failure, so fetch-success-rate alerting can't double-count a keyed miss. **Status: dormant.** No `ALPHAVANTAGE_KEY` has been supplied yet — `.env` and GitHub secrets are untouched, so every environment (local and CI) takes the no-key path and behavior is unchanged from the Task 6 amendment. The workflow's "Run pipeline" step gained `ALPHAVANTAGE_KEY: ${{ secrets.ALPHAVANTAGE_KEY }}` (harmless while the secret is unset — GitHub Actions passes an empty string, which the dispatch treats identically to "absent"). When a key is eventually added, no further code change is needed to activate it.

## 3. Architecture

```
GitHub Actions (cron "17 11 * * *" ≈ 6–7am ET + catch-up cron "17 21 * * *" + workflow_dispatch)
  │  (pipeline is idempotent — the catch-up run no-ops if the morning run succeeded)
  │
  ├─ 0. Tests       pytest must pass before pipeline steps run
  ├─ 1. Ingest      one module per source; each series isolated — one failure
  │                 never aborts the run; freshness recorded per series
  ├─ 2. Compute     native-frequency percentiles (dual windows) → as-of join into
  │                 the daily vector → pillar scores → composite → analog
  │                 similarity → sequencing state machine
  ├─ 3. Alerts      evaluate rules (§8c) → open GitHub issue per typed label
  ├─ 4. Export      write site/data/*.json (everything the dashboard renders)
  ├─ 5. Commit      git pull --rebase; commit data/ + site/data/; "nothing to
  │                 commit" is success. freshness.json changes every run, so a
  │                 successful run always commits (keeps the 60-day scheduled-
  │                 workflow auto-disable timer permanently reset)
  └─ 6. Deploy      publish site/ to GitHub Pages (artifact deploy)
```

Notes established during review:
- Pushes made with `GITHUB_TOKEN` do not re-trigger the workflow — that is the desired non-recursive behavior; do not "fix" it.
- GitHub cron is best-effort (delays of 15–60 min at popular times; occasional drops). The off-peak minute and the catch-up cron are the mitigation; the reliability metric (§13) is worded to tolerate this.

## 4. Repository Layout

```
macro-monitoring/
├── .github/workflows/daily.yml     # permissions: contents+issues+pages+id-token write
├── config/
│   ├── registry.yaml               # per indicator: source, series id, pillar, frequency,
│   │                               #   direction (invert?), role tag, staleness_budget_days,
│   │                               #   revision_window_days, lag_days, best_effort, notes
│   ├── thresholds.yaml             # regime bands, stage triggers (§8b), alert rules (§8c)
│   └── episodes.yaml               # episode peak dates, snapshot offsets
├── pipeline/                       # Python 3.12 package
│   ├── ingest/                     # fred.py, stooq.py, shiller.py, cboe.py, finra.py, aaii.py, yahoo.py
│   ├── compute/
│   │   ├── percentiles.py          # dual-window percentile + z-score engine (in-memory)
│   │   ├── scores.py               # pillar + composite (equal-weight within pillar)
│   │   ├── analogs.py              # cosine similarity vs episode snapshots
│   │   └── sequencer.py            # pre-crisis stage state machine (§8b)
│   ├── alerts.py                   # rule evaluation → GitHub issue via gh
│   ├── export.py                   # site/data/*.json writer (atomic per file)
│   └── cli.py                      # run | export | backtest | rebuild-episodes | status
├── data/                           # committed
│   ├── raw/<series_id>.csv         # date,value — append-mostly (§5)
│   ├── scores/composite.csv        # date,window,score,regime
│   ├── scores/pillars.csv          # date,window,pillar,score
│   ├── snapshots/episode_snapshots.csv  # episode,offset_months,series_id,percentile
│   └── state/                      # freshness.json, sequence_state.json
├── site/                           # static dashboard (no build step)
│   ├── index.html                  # views 1–3, 6 (§7)
│   ├── episodes/<name>.html        # generated from episodes/*.md + data
│   ├── backtest.html               # Phase 3
│   ├── assets/                     # plotly partial bundle (vendored), app.js, style.css
│   └── data/*.json                 # generated AND committed each run (§2 local access)
├── episodes/                       # narrative markdown sources (§9)
├── tests/                          # pytest
├── docs/superpowers/specs/         # this document
├── macro-bubble-monitor-spec.md    # v2 spec: pillar structure & intent
└── pyproject.toml
```

Indicators are **equal-weighted within a pillar**; the registry's optional per-indicator weight defaults to 1.0 and exists only for future tuning. The registry is the definitive enumeration: one row per series that enters an average (e.g. margin-debt *level* and *YoY* are two rows).

## 5. Data Model

- **Raw observations** — `data/raw/<series_id>.csv`, columns `date,value`. Append-mostly: ingestion appends rows newer than the last stored date, and may rewrite in place rows within the series' `revision_window_days` (e.g. GDP 120, Sahm 60, most market series 0). Total size across all series ≈ single-digit MB; growth a few MB/year.
- **Frequency alignment** — percentiles are computed on each series **at its native frequency**; the latest percentile is carried forward (as-of join) into the daily indicator vector. Monthly/quarterly series are never forward-filled into their own percentile distributions.
- **Short-history rule** — a series enters scoring only once it has ≥10 years of history (spec P0-3 minimum); younger series are ingested and displayed in drill-downs but excluded from pillar averages, analog vectors, and episode comparisons until they qualify.
- **Derived scores** — daily rows appended to `composite.csv` / `pillars.csv` with a `window` column (`full` | `rolling20y`). Full-history is canonical (§2); the rolling rows exist to feed the display toggle.
- **Z-scores** — computed in memory; latest values exported in `indicators.json` (see §2 decision).
- **Episode snapshots** — built by `pipeline rebuild-episodes` from raw history using full-history percentiles as of each snapshot date. Indicators lacking history for an episode are excluded, never zero-filled.
- **State** — `freshness.json` (per-series last-success fetch, latest observation date, last error); `sequence_state.json` (per-stage fired/lapsed status with dates, current stage, engaged/not_engaged).
- **Site JSON** (committed each run) —
  - `latest.json`: composite + pillar scores (both windows), regime, top-3 analogs, **full sequence state (every stage's status + fire date, or not_engaged)**, per-series freshness summary.
  - `history.json`: composite + pillar time series, keyed by window.
  - `indicators.json`: per-indicator series, dual-window percentiles, latest z-score, metadata (role, direction, source, splice notes, staleness).
  - `episodes.json`: snapshot vectors, **episode pillar scores per offset** (derived by export.py from snapshot percentiles using registry weights with excluded-indicator reweighting — what the radar chart renders), and firing timelines.
  - `backtest.json` (Phase 3): replayed daily composite + stage series and the S&P 500 price series (`^spx` is a registered series — it already feeds the 200-DMA distance indicator).

## 6. Staleness & Data Health (definitions)

- **Fetch success** = the source call completed without error, even if it appended zero new rows (normal on weekends/holidays and for low-frequency series).
- **Stale** = a series' latest observation is older than its `staleness_budget_days` from the registry (defaults: daily → 5 business days, weekly → 12, monthly → 45, quarterly → 120; +publication lag where relevant).
- **Data-health issue** fires when: (a) any individual series exceeds its staleness budget (issue names the series; 7-day cooldown per series), or (b) fewer than 80% of *fetch attempts* succeed in a single run. Dashboard badges show per-series staleness continuously either way.
- Pillar scores degrade gracefully: computed from available indicators, re-weighted; the dashboard flags pillars running on partial data.

## 7. Dashboard — Graphical Views (explicit)

Fully graphical, mobile-friendly, rendered by a vendored **Plotly partial bundle** (scatter/bar/indicator/scatterpolar — a fraction of the full bundle's ~4 MB) from pre-computed JSON. Views:

1. **Status strip** — composite score **gauge** (0–100, colored by regime band Cool/Warm/Frothy/Bubble-risk), regime label, closest-analog readout ("GFC at T−9, similarity 0.87"), current sequence stage. In Phase 2 the analog and stage slots render as explicit "available in Phase 3" placeholders.
2. **Pillar bars** — five horizontal percentile bars with 1-month/3-month change arrows (change in pillar score points over 21/63 trading days), role-tag chips (timing / magnitude / confirmation), and partial-data flags.
3. **Score history chart** — composite + selectable pillar time series; regime bands shaded; vertical markers at the four episode peaks; full-history ↔ rolling-20y toggle (both series shipped in `history.json`).
4. **Analog view** (Phase 3) — radar/spider chart overlaying today's five pillar scores on any selected episode snapshot (episode pillar scores from `episodes.json`); top-3 analog cards **with one line of backtest-derived base-rate context** (e.g. "similarity ≥ 0.8 also occurred N times outside pre-crisis windows"— small-n caveat shown); per-indicator table (today vs each episode's T−6).
5. **Sequence tracker** (Phase 3) — visual stage pipeline (1→6) showing fired/current/pending/lapsed stages with dates; renders "sequence not engaged" as a first-class state.
6. **Indicator drill-down** — per indicator: raw-value chart and percentile chart with 80th/90th bands, freshness badge, role tag, direction note, source link, splice annotations (e.g. CBOE 2019 gap).
7. **Episode pages** — narrative (§9) interleaved with an auto-generated indicator-firing timeline and episode charts. Causal-chain drafts ship in Phase 2; timelines complete them in Phase 3.
8. **Backtest page** (Phase 3) — replayed composite score and sequencer stages overlaid on a log-scale S&P 500 chart with episode windows shaded, plus the §13 sanity-check results.

Footer on every page: *monitoring context, not a trading signal.*

## 8. Sequencer, Alerts

### 8a. Semantics
Stages evaluate independently every run and may fire in any order; **current stage = highest fired stage**. A stage **lapses** (marked lapsed, not erased — fire history is kept) if its condition has been false for 3 consecutive months. The sequence is **engaged** when ≥2 of stages 1–3 have fired; it resets to `not_engaged` when the index closes >20% below its peak (crisis realized) or when all stages have lapsed. All values below are initial settings in `thresholds.yaml`, expected to be tuned against the Phase 3 backtest.

### 8b. Initial stage triggers (thresholds.yaml)

| Stage | Trigger (initial values, configurable) |
|---|---|
| 1 Valuation stretch | Pillar A (full-history) > 80 for ≥126 consecutive trading days |
| 2 Leverage peak | Margin-debt YoY percentile > 85 at any point in past 12 months AND YoY has declined 2+ consecutive months from that high |
| 3 Policy/curve turn | 10Y–3M was < 0 within past 18 months for ≥1 month AND is now > +25 bp (re-steepened) |
| 4 Credit widening | HY OAS ≥ 100 bp above its rolling 12-month low |
| 5 Breadth breakdown | Index within 2% of 52-week high in past month while RSP/SPY breadth ratio sits at a 6-month low (divergence proxy — see §2b substitution) |
| 6 Price confirmation | Index closes < 200-DMA AND (Sahm gap ≥ 0.50 OR VIX ≥ 30) |

**Implementation note (2026-07-06):** stage 4 uses Moody's Baa−10Y (+60 bp off its 12-month low) instead of HY OAS +100 bp — FRED's HY series lacks pre-2023 history (license); revisit when a deep HY source exists.

**Amendment (2026-07-06, Phase 4 Task 2 — sequencer calibration, four evidence-backed rule fixes):**

1. **Stage 4 (credit widening) is now evaluated intra-window with ordering, not last-value-vs-window-min.** Evidence: the GFC's Baa−10Y spread crossed +60bp off its trailing 12-month low intra-month on 2007-09-10/11, but the backtest's month-end sampling missed it because the spread narrowed back before the month-end snapshot — a sampling-cadence artifact, not a detection failure (§13 note). Fix: fire if, anywhere within the lookback window, the series rises ≥ `widen` off its running (cumulative) minimum-to-date (`m = w.cummin(); fired = ((w - m) >= widen - 1e-9).any()` — the `1e-9` epsilon is normative, not cosmetic: the real 2007-09-11 graze is `2.13 - 1.53`, exactly +0.60 in the source data, but float64 subtraction yields `0.5999999999999999`, so a naive `>=` misses it), evaluated across every observation in the window rather than only the final one. `widen: 0.60` is unchanged — this fixes the mechanism, not the threshold. Ordering still matters: a high that precedes the window's eventual low does not count.
2. **Stage 5 (breadth breakdown) now tests "near 52-week-high" over the past ~21 observations (design §8b "in past month"), not just the as-of close.** A pullback into the final observation no longer erases a real divergence that was visible earlier within the month.
3. **Stage 6 (price confirmation) inputs now have staleness bounds:** the Sahm reading must be ≤75 days old and VIX ≤10 days old at as-of, else that input is treated as **not-hot** (not missing) — a stalled feed can no longer silently keep confirming a "hot" condition indefinitely.
4. **Engagement gained a credit-led path:** `engaged = (≥2 of stages 1–3 fired-and-not-lapsed) OR (stage 3 AND stage 4 concurrently raw-true at the same checkpoint)`, gated on the new `sequencer.credit_path` config flag (default `true`) so the alternate gate is a visible, documented switch rather than an implicit rule. Evidence: the 1990 recession's stage 4 fired through 1989 while only ever reaching one of stages 1–3, so the 2-of-3 gate structurally blocked engagement for a genuinely credit-led bear (§13 forensic history); stages 3 and 4 were concurrently raw-true at four consecutive month-end checkpoints (1990-01-31 through 1990-04-30), with stage 4 raw-true continuously since 1989-05-31.

Backtest effect (full detail and honest before/after in §13): gfc and rec1990 flip FAIL→PASS; dotcom is unchanged (still FAIL — nothing new fires pre-2000); the 2019 control stays PASS; postcovid stays PASS.

**Resolution (2026-07-06, same day):** Implementing all four changes exactly as originally specified above flipped the 2019 covid-control criterion from PASS to FAIL (1 engaged month, December 2019) via an emergent interaction between two independently pre-registered fixes, not a bug: the Q4-2018 Baa−10Y widening's un-lapsed residue — its "fired-and-not-lapsed" state surviving an exactly-92-day gap against the `>92` lapse rule — combined with the genuinely-true one-month December-2019 curve resteepening under item 4's original state-based credit path. Per the plan's binding pre-registered honesty gate ("2019 control MUST STAY PASS … if control flips FAIL, STOP and report, do not tune further"), work stopped before commit and the flip was reported in full, with no threshold tuning attempted. The credit path above was then narrowed to require stages 3 and 4 to be concurrently raw-true at the same checkpoint rather than merely un-lapsed — this matches the credit path's own originating 1990 evidence (concurrent Jan–Apr 1990 firing, cited above) rather than adjusting any threshold, and restores the 2019 control to PASS (0 engaged months) without touching `widen`, `lapse_days`, or any other calibrated value. Final criteria after the narrowed rule: dotcom unchanged FAIL; gfc PASS; 2019 control PASS; postcovid PASS; rec1990 PASS.

### 8c. Alert rules & label taxonomy
- `alert:regime` — composite regime band changes (full-history window).
- `alert:pillar-<name>` — a pillar's **score value crosses above 90** (scores are already percentile-scaled 0–100; this is a value test, not a percentile-of-scores test). One label per pillar so pillars don't suppress each other.
- `alert:stage-<n>` — stage *n* fires. Per-stage labels so consecutive stage advances are never swallowed by cooldown.
- `data-health` — per §6.
- Cooldown: no new issue under the same label within 7 days. Issues are created via `gh` with the workflow token. **Local runs skip issue creation** (alerts step is gated on the `GITHUB_ACTIONS` env var and prints to stdout instead) — a clone never needs a GitHub token.

## 9. Crisis Narrative Layer

Serves the "understand why" goal directly — and ships early because it *is* the ultimate goal. One markdown file per episode (`episodes/dotcom.md`, `gfc.md`, `covid.md`, `postcovid.md`): macro backdrop, causal chain, policy timeline, lessons. **Draft causal chains and policy timelines are written in Phase 2** (acceptance criterion: all four pages have at least a causal-chain draft); Phase 3 adds the auto-generated firing timeline (from episode snapshot data: which indicators crossed extremes at which T-offset) interleaved with the narrative. The analog view deep-links to the matching episode page at the matching stage.

## 10. Backtest

`pipeline backtest` replays percentiles, scores, and sequencer day-by-day over full history and emits `backtest.json` + the backtest page, checking the §13 sanity criteria. Point-in-time approximation: each replay day sees a series only after `observation_date + lag_days` (per-registry publication lag, e.g. GDP ~90 days, Sahm ~35, margin debt ~25). **Vintage revisions are out of scope** — replay uses latest-revision values; this is a documented limitation (§14), acceptable because triggers use coarse thresholds, not fine revisions-sensitive levels.

## 11. Error Handling

- Per-series ingestion wrapped individually; failures recorded in `freshness.json`, surfaced as badges and (past budget) data-health issues; the run continues.
- Export is atomic per file (write temp, rename) — a mid-run failure never publishes half-written JSON.
- Commit step: `git pull --rebase` before push; "nothing to commit" exits successfully.
- Workflow-level failure fails the Action → GitHub emails on workflow failure by default.

## 12. Testing

- **Unit (pytest):** percentile engine (dual windows, native-frequency + as-of join, short-history series, direction inversion, revision-window rewrites), score aggregation with missing indicators/pillars, analog cosine math with excluded indicators, sequencer transitions on synthetic fixtures shaped like each episode — including COVID staying `not_engaged` through 2019 and lapse/reset semantics.
- **Golden files:** export output for a fixed fixture dataset compared against checked-in JSON.
- **CI:** tests run before the daily pipeline steps and on every push (pushes by `GITHUB_TOKEN` don't re-trigger — by design).

## 13. Success Metrics (amended from spec §9)

- **Reliability:** ≥95% of calendar days end with a completed run (GitHub cron is best-effort; two cron slots/day mitigate) ; no series exceeds its staleness budget unalerted.
- **Backtest sanity:** replayed sequencer reaches stage ≥4 before the 2000, 2007, and 2022 peaks, and stays `not_engaged`/stage ≤2 through 2019 (COVID control). Stage-2 evaluation requires the FINRA/NYSE historical margin-debt import, which is therefore part of Phase 3, not Phase 4.
- **Usage & interpretability:** unchanged from spec §9.

**Phase 3 (superseded 2026-07-06 by the Phase 4 Task 2 recalibration below — kept as history) — Note (Phase 3 Task 9 — actual backtest results):** `pipeline backtest`'s monthly (business-month-end) replay checks the four §13 criteria against real history. Result: **1 of 4 pass.** Recorded honestly, with the forensic reason each one actually failed (not just that it failed):

- **dotcom (peak 2000-03): FAIL — structural.** Max stage reached in T-18m..T is 0. Engagement requires ≥2 of stages 1-3 fired-and-not-lapsed; only stage 1 (valuation pillar >80th, 126d) is ever true in this window. Stage 2 (margin-debt-YoY froth rollover) has no percentile data before 2008 (margin debt history starts 1997; the 10y-history qualification gate doesn't clear until 2007), and stage 3 (curve resteepen) never satisfies its `min_inverted_days: 21` condition pre-peak (the curve only inverted ~5 days, during the Sept 1998 LTCM episode, well short of the threshold). This is a data-availability/structural gap, not a model miss — the sequencer had one of three legs to stand on.
- **gfc (peak 2007-10): FAIL — cadence-dependent.** Max stage reached is 3 (stage 1 valuation + stage 3 curve resteepen both fire by mid-2007). Stage 4 (Baa-10Y spread widens ≥0.60 from its trailing-365d low) *does* cross true at daily resolution — the spread first clears the 0.60 widen threshold on 2007-09-10/11 — which would have pushed current_stage to 4 and passed the criterion. But the backtest samples month-end only, and by the 2007-09-28 business-month-end snapshot the spread had narrowed back below the threshold (the "graze" happened and receded mid-month); every monthly snapshot in the window reads stage 4 as false. This is a sampling-cadence artifact, not a detection failure.
- **2019-control (quiet-through-2019): FAIL — genuine, but the criterion may be the wrong bar.** 1 engaged month in 2019 (December), with the sequencer escalating through stage 3 (Dec 2019) -> stage 5 (Jan 2020) -> stage 6 (Feb 2020) ahead of the COVID peak. This is not spurious noise: stage 1 (valuation) and stage 3 (curve resteepening after 2019's inversion) were both genuinely true, reflecting the real 2018 "Volmageddon" vol spike and the real Sept-Oct 2019 repo-market stress — late-cycle phenomena that predate COVID but are real, not artifacts. The strict "zero engaged months in 2019" bar doesn't distinguish "detected real but unrelated late-cycle stress" from "false positive on the pandemic specifically"; see the covid.md episode-page caveat and the auto-timeline note added this task for the same reconciliation in the UI.
- **postcovid (peak 2022-01): PASS.** Max stage reached in T-18m..T is 6 (full chain, including stage-6 price confirmation).

**Phase 3 (superseded 2026-07-06 by the Phase 4 Task 2 recalibration below — kept as history) — Update (Shiller CAPE + ERP task): now 2 of 4 pass.** Re-running the backtest after the valuation pillar gained CAPE (+ERP) alongside Buffett: dotcom and gfc are unchanged (same FAIL, same reasons above — CAPE strengthens dotcom's pre-peak valuation reading but stage 1 was already firing there, so it doesn't unlock a second early-stage leg). **2019-control flips FAIL -> PASS** (0 engaged months in 2019, down from 1): blending in CAPE makes the valuation-pillar percentile slightly less persistent above the 80th-percentile/126-day stage-1 bar than the Buffett-only reading was, so stage 1 no longer combines with stage 3 to cross the ≥2-of-3 engagement bar in Dec 2019. **postcovid stays PASS** but the max stage reached in T-18m..T reads 5 instead of 6 — not a change to stage 6's own definition (it doesn't depend on valuation at all), but a downstream consequence of the shared "engaged + SPX >20% off its trailing high" reset, which unconditionally lapses *all* stages when it fires: the valuation pillar's changed daily trajectory shifted the exact months that reset triggered during 2022's volatility, so stage 6's fired-and-not-yet-relapsed window no longer overlaps the T-18m..T lookback the same way. Confirmed by directly diffing stage-by-stage monthly booleans between the old and new registries: stages' own per-month true/false readings are bit-for-bit identical; only the stateful lapse/reset history built on top of them (which is sensitive to valuation-driven engagement timing) differs.

**Phase 4 tuning targets flagged by this analysis:** (1) stage-4 spread-widening evaluated only at intra-month/daily resolution (or replayed on a finer cadence than monthly) so transient spread grazes aren't sampled away — alternatively, loosen `widen` from 0.60 toward ≈0.40 so the monthly grid still catches gradual widening; (2) the Z.1-sourced series (`ncbeilq027s`, `cmdebt` — Buffett ratio and household/corporate debt-to-GDP) are indexed by FRED at **period start** (e.g. a Q1 observation dated Jan 1) but published ~75 days after period **end**; `lag_days: 75` applied to a period-start timestamp understates the true publication lag by a full quarter and should be corrected to a period-start-aware convention (effectively lag_days ≈ 75 + quarter length) before these series are trusted in fine-grained backtest timing.

**Update (2026-07-06, Phase 4 Task 2 — sequencer calibration): now 4 of 5 pass.** The criteria set grew from four to five between the note above and this update: the historical-episodes amendment (§2b) extended the backtest replay back to 1987 and added an honest `rec1990` criterion. The sequencer calibration in §8b — stage 4's intra-window order-aware widening, stage 5's near-high-over-past-21-observations window, stage 6's staleness bounds, and the credit-led engagement path — then changes three of the five outcomes. Honest before/after (mechanics evaluated against the sequencer rules in effect at each point in time — this is not re-litigating old history under new rules, it's what each phase's actual implementation produced):

| criterion | before Phase 4 | after Phase 4 |
|---|---|---|
| dotcom (peak 2000-03) | FAIL (max stage 0 in T-18m..T) | FAIL (max stage 0) — unchanged, honest |
| gfc (peak 2007-10) | FAIL (max stage 3) | PASS (max stage 4) |
| 2019 control (quiet through 2019) | PASS (0 engaged months) | PASS (0 engaged months) |
| postcovid (peak 2022-01) | PASS (max stage 5, then 6 after Shiller CAPE landed) | PASS (max stage 6) |
| rec1990 (peak 1990-07) | FAIL (max stage 0) | PASS (max stage 4) |

dotcom's FAIL is unchanged for the same structural reason recorded above — stage 2 has no percentile data before 2008 (margin-debt history doesn't qualify until 2007) and stage 3 never satisfies `min_inverted_days: 21` pre-peak (the curve only inverted ~5 days, during 1998 LTCM). None of the four Task 2 fixes touch that gap, so the honest result stays FAIL rather than being tuned into a pass. gfc flips to PASS because the stage-4 intra-window fix now catches the 2007-09-10/11 Baa−10Y graze (2.13−1.53 = exactly +0.60) that month-end sampling, and naive float `>=` comparison, previously missed. rec1990 flips to PASS via the new credit-led engagement path: the 1990 recession's stage 4 (credit widening) had been true continuously since mid-1989 while the sequence only ever reached one of stages 1-3, so the ≥2-of-3 gate structurally blocked engagement for a genuinely credit-led bear; the concurrent-raw-true stage-3-and-4 path recognizes it without touching any threshold.

**Honesty-gate history — why rec1990's PASS took two attempts, recorded in full because the plan's pre-registered gate is exactly what caught it:** Implementing the credit-led path precisely as first specified — engage when stage 3 is raw-true and stage 4 is merely "fired-and-not-lapsed" (i.e. any un-lapsed residue, not necessarily concurrently true right now) — flipped the 2019-quiet-control criterion from PASS to FAIL (1 engaged month, December 2019). This was an emergent interaction between two independently-motivated, individually-correct fixes, not a bug in either one: the Q4-2018 Baa−10Y widening's un-lapsed state survived an exactly-92-day gap against the sequencer's `>92`-day lapse rule, and that un-lapsed stage-4 residue combined with the genuinely-true one-month December-2019 curve resteepening (stage 3) to satisfy the credit-led gate as originally worded. Per the plan's binding pre-registered honesty gate ("2019 control MUST STAY PASS … if control flips FAIL, STOP and report, do not tune further"), work stopped before commit and the flip was reported in full rather than patched around under time pressure. Forensics on the 1990 evidence that motivated the credit-led path in the first place showed stages 3 and 4 were **concurrently raw-true** at four consecutive month-end checkpoints (1990-01-31 through 1990-04-30) — not merely "stage 4 un-lapsed while stage 3 fires" — so the rule was narrowed to require concurrent raw-truth at the same checkpoint, matching its own originating evidence rather than adjusting any threshold (`widen`, `lapse_days`, and every other calibrated value are untouched by this narrowing). The narrowed rule restores the 2019 control to PASS (0 engaged months) while still passing rec1990. Full stage-by-stage mechanism and the exact rule text live in §8b.

**New conventions established this phase (full derivation in the §2b Task 3 and Task 4 amendments above — summarized here since this is the section that reads them against backtest honesty):** regime bands (cool<64, warm<76, frothy<83, bubble_risk>=83) are now fit to the full-window composite's own empirical quantiles (p50=64.09, p85=76.33, p95=82.96) rather than the original spec-guessed round numbers (40/70/85); the analog-similarity display/base-rate threshold (0.98) is likewise derived from the 90th percentile of the demeaned cosine similarity's monthly top-1-analog distribution over the full 474-month replay (median 0.8433, p75 0.9475), not chosen to flatter today's reading. Both are examples of the same discipline as the honesty-gate history above: numbers earned from the data's own distribution, reported even when inconvenient, rather than picked to make a criterion pass or a reading look better.

**1980-81 nuance — read pillars alongside the composite, not the composite alone:** extending `score_start` back to 1975 (Task 1) surfaces a case worth flagging explicitly, because it's the sharpest historical example in the current data of the composite masking a genuinely extreme individual pillar. Through 1980-81 (the Volcker double-dip), the **leverage pillar** alone reads elevated — 77.5 to 86.1 on its 0-100 scale, into the same frothy-to-bubble-risk color band the UI uses for pillar bars (`site/assets/app.js`'s `renderPillars` reuses `regimeEdges()` for pillar-bar coloring) — driven by genuinely then-record postwar household and corporate debt-to-GDP levels: `cmdebt` and `bcnsdodns` (the household- and corporate-debt inputs behind `household_debt_gdp`/`corporate_debt_gdp`) both carry FRED history back to 1945, so the full-history percentile reflects 35 years of real prior data, not a short-window artifact. Over the same stretch the **valuation pillar** reads near its historical floor (5.1-21.6) — Shiller CAPE was ~9.65 in November 1980 (the Volcker-peak month), among the cheapest readings in its 1881-present series — while liquidity is mixed. The **blended composite stays "cool" throughout 1980-81 on both windows** (it never crosses the 64 cool/warm edge; full-window scores range 37.8-54.6 across the period) because the cheap-valuation and mixed-liquidity pillars offset the hot leverage pillar in the equal-weighted average. This is not a data error — it is exactly why the dashboard ships pillar bars alongside the composite gauge (§7, view 2): a single blended number can and does mask a genuinely extreme pillar underneath it, and 1980-81 is the clearest instance of that in the monitor's own history.

Of the two Phase-3 tuning targets flagged just above: the stage-4 intra-month/daily-resolution issue is resolved by the Task 2 fix (order-aware `cummin` widening). The Z.1 period-start `lag_days` convention issue (`ncbeilq027s`, `cmdebt`, `bcnsdodns` all still carry `lag_days: 75` measured from a period-start timestamp) remains open and unaddressed by Phase 4 — a documented limitation carried forward, not a regression.

## 14. Risks

Inherited from spec §12 (small-n overfitting, structural regime drift, scraper rot, false confidence) — mitigations stand. Additions from review:

- **Non-FRED source fragility is the concentrated risk.** Mitigated by the §2b substitutions (FRED/Stooq-first), per-series isolation, staleness alerts, and best-effort flags.
- **Point-in-time approximation** (§10): lag-based replay without vintages slightly flatters backtest realism; documented on the backtest page.
- **Spliced series** (CBOE put/call, dollar index): methodology changes across splice dates; splice annotations shown in drill-downs.
- **Public dashboard URL:** world-readable; accepted — all content derives from public data.

## 15. Phasing

- **Phase 1 (weekend 1):** repo scaffolding, registry + thresholds config, FRED + Stooq ingestion of the 18 no-scraper indicators — Buffett ratio (`NCBEILQ027S`/GDP), HY OAS, household debt/GDP, corporate debt/GDP, SLOOS, M2 YoY, Fed balance-sheet YoY, net liquidity, real Fed Funds, 10Y–2Y, 10Y–3M, VIX (`VIXCLS`), dollar index (spliced), Sahm, `CFNAI`, S&P 200-DMA distance (`^spx`), RSP/SPY breadth, BTC YoY — percentile engine (dual windows, as-of join), composite score, CLI + tests, daily Action committing data. One-time repo setup checklist (§16).
- **Phase 2 (weekend 2):** dashboard views 1–3 & 6 (analog/stage slots as placeholders), Pages deployment, freshness badges, issue-based alerts, **draft narrative pages for all four episodes**.
- **Phase 3 (weekend 3):** episode library + `rebuild-episodes` (including one-time FINRA/NYSE historical margin-debt import), analog view (4), sequence tracker (5), backtest + page (8), narrative firing timelines (7), Shiller CAPE + ERP ingestion (Shiller ships an .xls workbook with multi-row headers — parse tolerantly; register econ.yale.edu and shillerdata.com as primary/fallback URLs). **Landed** (2026-07-06, closing the last Phase 3 gap caught by the final review): see the amendment at the end of §2b for source URLs, the qualifying date, and the resulting backtest/sequencer deltas.
- **Phase 4 (ongoing):** live scrapers (FINRA monthly with browser-like headers, CBOE forward-accumulation, AAII weekly public scrape), threshold tuning against backtest, optional weekly digest issue.

## 16. One-Time Setup Checklist (Phase 1)

1. Create GitHub repo (public), push, set **Pages source = GitHub Actions**.
2. Add secret `FRED_API_KEY` (free key from fred.stlouisfed.org).
3. Create issue labels: `alert:regime`, `alert:pillar-valuation`, `alert:pillar-leverage`, `alert:pillar-liquidity`, `alert:pillar-sentiment`, `alert:pillar-macro`, `alert:stage-1`…`alert:stage-6`, `data-health` (labels must exist before `gh issue create` uses them).
4. Workflow `permissions:` block: `contents: write`, `issues: write`, `pages: write`, `id-token: write`.
5. Verify alert email path: fire a test issue from the workflow; confirm the repo is Watched with email notifications on (own repos are auto-watched by default).
6. Local: `.env` with `FRED_API_KEY`; `python -m http.server -d site` to view; `pipeline export` rebuilds site JSON offline from committed CSVs.
