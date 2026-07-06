# Macro & Market Bubble Monitor — Validated Design

**Date:** 2026-07-05 (rev. 2 after adversarial design review)
**Status:** Approved design (supersedes the architecture sections and the affected data sources of `macro-bubble-monitor-spec.md` v2; that spec's pillar structure, weights, role tags, episode definitions, and success intent remain the source of truth)
**Owner:** jolee (solo, personal use)

---

## 1. Purpose

A daily-updated, historically grounded market-risk monitor. It ingests ~25 macro/market indicators, normalizes each to historical percentiles, rolls them into five pillar scores and a composite bubble score (0–100), compares today's profile against the run-ups to four past crises (2000, 2007, 2020, 2022), and tracks where the market sits in the classic pre-crisis sequence. The ultimate goal: understand *why* past crises happened and whether today's setup resembles any of them — readable in under 30 seconds from any device, in a fully graphical dashboard.

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

**Amendment 2026-07-06 (Task 6 implementation):** Stooq now serves a JavaScript anti-bot challenge to all non-browser clients (verified live from two contexts), making it unfetchable headlessly — the §2b substitutions relying on Stooq are amended: `spx` daily updates come from FRED `SP500` (trailing 10-year window) layered over a one-time committed deep-history seed (Yahoo `^GSPC`, 1927→); `rsp`/`spy`/`btcusd` come from Yahoo's v8 chart JSON API fetched with `range=max` each run (full-history fetches self-heal gaps; works from residential IPs, intermittently from Actions runners — 14-day staleness budgets absorb blocked stretches and any local `pipeline run` heals them). The Stooq ingest module was removed.

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

## 14. Risks

Inherited from spec §12 (small-n overfitting, structural regime drift, scraper rot, false confidence) — mitigations stand. Additions from review:

- **Non-FRED source fragility is the concentrated risk.** Mitigated by the §2b substitutions (FRED/Stooq-first), per-series isolation, staleness alerts, and best-effort flags.
- **Point-in-time approximation** (§10): lag-based replay without vintages slightly flatters backtest realism; documented on the backtest page.
- **Spliced series** (CBOE put/call, dollar index): methodology changes across splice dates; splice annotations shown in drill-downs.
- **Public dashboard URL:** world-readable; accepted — all content derives from public data.

## 15. Phasing

- **Phase 1 (weekend 1):** repo scaffolding, registry + thresholds config, FRED + Stooq ingestion of the 18 no-scraper indicators — Buffett ratio (`NCBEILQ027S`/GDP), HY OAS, household debt/GDP, corporate debt/GDP, SLOOS, M2 YoY, Fed balance-sheet YoY, net liquidity, real Fed Funds, 10Y–2Y, 10Y–3M, VIX (`VIXCLS`), dollar index (spliced), Sahm, `CFNAI`, S&P 200-DMA distance (`^spx`), RSP/SPY breadth, BTC YoY — percentile engine (dual windows, as-of join), composite score, CLI + tests, daily Action committing data. One-time repo setup checklist (§16).
- **Phase 2 (weekend 2):** dashboard views 1–3 & 6 (analog/stage slots as placeholders), Pages deployment, freshness badges, issue-based alerts, **draft narrative pages for all four episodes**.
- **Phase 3 (weekend 3):** episode library + `rebuild-episodes` (including one-time FINRA/NYSE historical margin-debt import), analog view (4), sequence tracker (5), backtest + page (8), narrative firing timelines (7), Shiller CAPE + ERP ingestion (Shiller ships an .xls workbook with multi-row headers — parse tolerantly; register econ.yale.edu and shillerdata.com as primary/fallback URLs).
- **Phase 4 (ongoing):** live scrapers (FINRA monthly with browser-like headers, CBOE forward-accumulation, AAII weekly public scrape), threshold tuning against backtest, optional weekly digest issue.

## 16. One-Time Setup Checklist (Phase 1)

1. Create GitHub repo (public), push, set **Pages source = GitHub Actions**.
2. Add secret `FRED_API_KEY` (free key from fred.stlouisfed.org).
3. Create issue labels: `alert:regime`, `alert:pillar-valuation`, `alert:pillar-leverage`, `alert:pillar-liquidity`, `alert:pillar-sentiment`, `alert:pillar-macro`, `alert:stage-1`…`alert:stage-6`, `data-health` (labels must exist before `gh issue create` uses them).
4. Workflow `permissions:` block: `contents: write`, `issues: write`, `pages: write`, `id-token: write`.
5. Verify alert email path: fire a test issue from the workflow; confirm the repo is Watched with email notifications on (own repos are auto-watched by default).
6. Local: `.env` with `FRED_API_KEY`; `python -m http.server -d site` to view; `pipeline export` rebuilds site JSON offline from committed CSVs.
