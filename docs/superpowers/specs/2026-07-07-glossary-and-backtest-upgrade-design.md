# Glossary & Backtest Upgrade — Design

Date: 2026-07-07
Status: approved by user (glossary approach + all four backtest features selected)

## Motivation

The dashboard's guide uses ~25 technical terms (Shiller CAPE, 10Y−3M spread, Sahm rule
gap, SLOOS, net liquidity…) without defining any of them; the user is not a finance
specialist and wants short plain-language definitions. Separately, the Backtest page
currently answers only "did the tracker catch past crises" (criteria checklist + one
chart) but none of the natural follow-ups: how early did it warn, what do readings mean
for subsequent returns, how often did it cry wolf, and what would acting on it have cost.

## Part A — Registry-driven glossary

### A1. `blurb` field in the registry

Every indicator in `config/registry.yaml` gets a `blurb:` string:

- Format: 1–2 sentences *what it is*, then 1 sentence *how to read it here*. Target
  ≤ ~60 words, plain language, no unexplained jargon.
- For every `direction: invert` indicator (10 of them), the blurb MUST state that a
  lower/more-negative raw value scores a HIGHER froth percentile, in words a
  non-specialist can follow. Example (10Y−3M): "The gap between 10-year and 3-month US
  Treasury yields. Below zero the curve is 'inverted' — short-term money costs more than
  long-term, a classic recession precursor. This indicator is inverted: a more negative
  spread scores a higher froth percentile."
- All 28 indicators get blurbs, including the 7 `role: context` ones.

`pipeline/registry.py`: `Indicator` dataclass gains `blurb: str | None = None`;
`_validate()` errors on a missing/empty blurb for every indicator, so no future
indicator can ship undefined. Test fixtures that build registries gain blurbs.

### A2. Export

`pipeline/export.py` adds `"blurb": ind.blurb` to each entry written to
`site/data/indicators.json`. No other schema change.

### A3. Drill-down surfacing

`site/assets/app.js` `renderIndicator()`: render the PRIMARY indicator's blurb as a
muted paragraph (class `indicator-blurb`) directly under the existing meta chips.
Compare-pinned extras do not repeat their blurbs (clutter).

### A4. Guide glossary (new section 11 in `site/guide.html`)

Two sub-parts:

1. **Concept terms** — hand-written prose entries (not indicator-specific):
   percentile, z-score, indicator "direction" / what an inverted indicator means,
   yield curve & inversion, credit spread, drawdown, 200-day moving average,
   market breadth, NBER recession, the "T−24m" episode-offset notation.
2. **Indicator glossary** — auto-rendered. A small inline script (the guide's first
   JS) fetches `data/indicators.json` and renders every indicator's name + blurb,
   grouped by pillar in fixed order (valuation, leverage, liquidity, sentiment, macro,
   context), alphabetical by display name within a pillar. The pillar label map is
   duplicated inline (deliberate: the guide stays standalone, does not load app.js).
   If the fetch fails, the section shows a "glossary unavailable offline" muted note
   instead of breaking the page.

Guide section 9 ("Backtest & honesty") also gains a sentence pointing at the new
report card, alarm ledger, and simulator.

## Part B — Backtest page rebuild

All new numbers are computed in `pipeline/backtest.py::run_backtest` and exported into
`site/data/backtest.json`. **Existing keys are unchanged** (`months`, `stage`,
`engaged`, `composite`, `spx`, `episodes`, `criteria`, `base_rate`) so the dashboard's
base-rate footnote keeps working. The page (`site/backtest.html`) becomes five
sections in this order: header prose, report card, replay chart (existing), forward
returns, alarm ledger, simulator.

### B0. New `backtest.json` keys

- `regime_bands`: copied from `thresholds["regime_bands"]` (needed client-side by B3
  and B5; the page fetches only backtest.json).
- `fedfunds`: monthly array aligned to `months` (raw FEDFUNDS level, `BME` resample
  last, null-padded; the effective rate is known ~real-time so no lag shift).
- `fwd_6m`, `fwd_12m`, `fwd_24m`: arrays aligned to `months`; simple price return in
  percent, `(spx[t+h]/spx[t] − 1) × 100`, computed on the monthly spx array; `null`
  where `t+h` is beyond available data (or spx is null). All `*_pct` fields in this
  file (including B4's) use this same ×100 percent convention.
- `report_card`: list per episode, see B2.
- `alarms`: list per engaged run, see B4.

### B1. Header prose

Short paragraph on the page explaining the replay: each month is re-scored using only
data knowable at that time (publication lags applied), the composite is shown
as-published, and nothing is fit after the fact.

### B2. Crisis report card

Table above the chart, one row per scored episode (dotcom, gfc, rec1990, postcovid)
plus the 2019 covid control row. Fields per row:

- `episode`, `name`, `peak`
- `first_engaged`: first month in the window peak−24m..peak where `engaged` is true
  (ISO date or null)
- `first_stage4`: first month in that window where `stage >= 4` (ISO date or null)
- `lead_months`: whole months from `first_stage4` to `peak` (null if never)
- `max_drawdown_pct`: S&P peak-to-trough % from the episode peak, trough = minimum
  monthly close within 36 months after the peak
- `months_to_trough`
- `control`: bool; `note`: free text (dotcom row: "never engaged — margin-debt series
  doesn't reach back far enough; curve re-steepened only after the peak")

The control row reports engaged-months-in-2019 instead of lead times. Episodes with
`criterion: false` (pre-1987 + thin-data 1929/1937) are excluded — the replay starts
1987-01-30. Rendered as an HTML table; failing/na cells display honestly ("never").

### B3. Forward returns — "what happened next"

Client-side grouping of the `fwd_*` arrays (no server-side stats):

- **By composite regime**: bucket each month by its as-published composite against
  `regime_bands` (cool/warm/frothy/bubble_risk). One Plotly grouped **bar** figure:
  x = regime group + an "all months" baseline group, one bar trace per horizon
  (6m/12m/24m), bar = median forward return, asymmetric `error_y` whiskers = the
  interquartile range. (Amended 2026-07-07 post-deploy: the original design said box
  plots, on a string-match "verification" that the vendored bundle included the box
  trace — a false positive. Runtime schema check shows the plotly-finance partial
  bundle registers only scatter/bar/histogram/funnel/waterfall/pie/funnelarea/
  indicator/ohlc/candlestick; an unregistered type silently coerces to scatter lines.
  Median-bars + IQR whiskers is the replacement, verified rendering on live data.)
- **By sequence stage**: same figure shape with buckets stage 0, stages 1–3, stage ≥ 4.
- Under each figure, a one-line text summary: % of months with a negative 12-month
  forward return per bucket vs. baseline.
- Printed caveats (visible, not tooltip): price-only returns exclude dividends;
  overlapping forward windows mean adjacent months are not independent samples;
  bucket sizes shown (n=…) because Frothy/Bubble-risk buckets are small.

### B4. Alarm ledger

Pipeline finds every maximal contiguous run of `engaged == true` in the replay and
classifies it:

- `in_window`: run overlaps peak−24m..peak of any non-control episode whose peak is
  ≥ replay start (dotcom, gfc, postcovid, rec1990, black1987). If a run overlaps
  several, attribute to the nearest subsequent peak.
- Fields: `start`, `end`, `months`, `in_window`, `episode` (id or null),
  `fwd_12m_pct` (S&P return 12 months from run start; null if beyond data),
  `max_dd_12m_pct` (worst drawdown vs. run-start level within the following 12
  months: `min(spx[start..start+12]) / spx[start] − 1`).

Rendered as a two-part table: "Warnings that preceded a crisis" and "False alarms",
each with what-happened-next columns. Zero false alarms renders an explicit "none in
474 months" line rather than an empty table.

### B5. Cost-of-caution simulator

Entirely client-side on backtest.html, computed from `spx`, `composite`, `stage`,
`fedfunds`, `regime_bands` already in backtest.json.

- **Controls**: trigger select — `composite ≥ warm-upper (frothy)`, `composite ≥
  frothy-upper (bubble risk)`, `stage ≥ 3`, `stage ≥ 4`, `composite ≥ frothy-upper OR
  stage ≥ 4` (default: `stage ≥ 4`); cash-fraction slider 0–100% (default 50%).
- **No look-ahead**: the position for month t's return uses the signal evaluated at
  month-end t−1. Cash earns the prior month-end fed funds rate / 12.
  `r_strat[t] = w_eq·(spx[t]/spx[t−1]−1) + (1−w_eq)·(fedfunds[t−1]/100/12)` with
  `w_eq = 1 − cashFrac` when triggered at t−1, else 1. Months with null inputs keep
  the prior weight and use r_cash = 0 fallback only if fedfunds is null.
- **Output**: log-scale equity curves (strategy vs. 100% S&P buy-and-hold, both
  starting at 1.0 at the first month with full inputs) + stats row: CAGR, max
  drawdown, % of months de-risked, final growth multiple for both.
- **Framing** (prominent, above the controls): educational exercise; price-only S&P
  (no dividends — understates equity returns), no taxes/costs/slippage; the expected
  honest lesson is that caution buys smaller drawdowns at the cost of compounding;
  not investment advice.

### Testing

Extend `tests/test_backtest.py` with synthetic-series tests:

- forward returns: geometric series → exact expected percentages, nulls at the tail
- alarm runs: synthetic engaged pattern → correct run boundaries, window
  classification, forward return/drawdown fields
- report card: synthetic stage/engaged series around a fake peak → first dates and
  lead months; control row; drawdown/trough math
- payload: new keys present, aligned lengths, existing keys unchanged
- registry: missing blurb raises in `_validate`; export writes `blurb` through

The simulator and glossary rendering are JS; keep the math thin and verify end-to-end
in the browser (drive the real page, check numbers against a hand computation for one
parameter setting) before completion.

### Touched files

`config/registry.yaml`, `pipeline/registry.py`, `pipeline/export.py`,
`pipeline/backtest.py`, `site/guide.html`, `site/backtest.html`,
`site/assets/app.js`, `site/assets/style.css` (table/control styles as needed),
`tests/test_backtest.py`, `tests/test_registry.py`, `tests/test_export.py`.

## Out of scope (possible future work)

- Dashboard-wide hover tooltips on pillar bars / context tiles / sequence stages
- Analog-similarity monthly replay chart (the series behind `base_rate` isn't exported)
- Threshold robustness explorer (stage/window what-if grid)
