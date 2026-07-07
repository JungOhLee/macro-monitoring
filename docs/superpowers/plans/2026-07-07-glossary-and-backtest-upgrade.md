# Glossary & Backtest Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add plain-language definitions for every indicator (registry-driven, surfaced in the drill-down and the guide) and rebuild the Backtest page with a crisis report card, forward-return distributions, an alarm ledger, and a cost-of-caution simulator.

**Architecture:** Definitions live as a required `blurb:` field in `config/registry.yaml`, flow through `export.py` into `indicators.json`, and render in the drill-down and an auto-generated guide glossary. All new backtest numbers are pure functions in `pipeline/backtest.py` exported into `site/data/backtest.json` (existing keys untouched); the page's JS moves to a new `site/assets/backtest.js` that renders five sections.

**Tech Stack:** Python 3 (pandas, pytest, run via `venv/bin/python`), vanilla ES6 JS, vendored partial Plotly bundle (`scatter`, `bar`, `box`, `histogram`, `indicator` traces available — NO `table` trace).

**Spec:** `docs/superpowers/specs/2026-07-07-glossary-and-backtest-upgrade-design.md`

## Global Constraints

- Run tests with `venv/bin/python -m pytest tests/ -q` (or a single file with `-v`); run the pipeline CLI with `venv/bin/python -m pipeline <cmd>`.
- All `*_pct` values exported to `backtest.json` use the ×100 percent convention, rounded to 2 decimals (e.g. `12.68` means +12.68%).
- Existing `backtest.json` keys (`months`, `stage`, `engaged`, `composite`, `spx`, `episodes`, `criteria`, `base_rate`) must be unchanged — the dashboard (`app.js` `renderAnalogs`) reads `base_rate` from this file.
- No new Python or JS dependencies; no build step; site JS stays vanilla.
- Blurbs: 1–2 sentences *what it is* + 1 sentence *how to read it here*, ≤ ~60 words, plain language. Every `direction: invert` indicator's blurb MUST say that lower/more-negative raw values score a HIGHER froth percentile. No double-quote characters inside blurb strings (they are double-quoted YAML scalars) — use single quotes.
- JS syntax-check any edited JS file with `node --check <file>` before committing.
- Commit after every task with the message given in that task; end commit messages with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Required `blurb` field in the registry + all 28 blurbs

**Files:**
- Modify: `pipeline/registry.py` (Indicator dataclass ~line 27; `_validate` ~line 79)
- Modify: `config/registry.yaml` (all 28 entries under `indicators:`)
- Test: `tests/test_registry.py`

**Interfaces:**
- Produces: `Indicator.blurb: str | None = None` (new last field of the frozen dataclass); `load_registry()` raises `ValueError` containing `"missing blurb"` if any indicator lacks a non-empty blurb. Later tasks rely on `ind.blurb` existing on every registry indicator.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_registry.py`:

```python
def test_missing_blurb_rejected(tmp_path):
    bad = tmp_path / "registry.yaml"
    bad.write_text(
        "pillar_weights: {valuation: 1.0}\n" + _one_series_yaml() +
        "indicators:\n"
        "  - {id: x, name: X, pillar: valuation, role: timing, direction: normal, series: s, lag_days: 1}\n"
    )
    with pytest.raises(ValueError, match="missing blurb"):
        load_registry(bad)


def test_all_indicators_have_blurbs():
    reg = load_registry()
    for ind in reg.indicators:
        assert ind.blurb and len(ind.blurb.split()) >= 8, ind.id
```

Also fix the existing fixture that must now carry a blurb — in `test_context_role_and_pillar_pairing_accepted`, change the indicator line to:

```python
        "indicators:\n"
        "  - {id: x, name: X, pillar: context, role: context, direction: normal, series: s, lag_days: 1,\n"
        "     blurb: 'A test context indicator used to check role/pillar pairing.'}\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_registry.py -v`
Expected: `test_missing_blurb_rejected` FAILS (`DID NOT RAISE` / no "missing blurb" in message) and `test_all_indicators_have_blurbs` FAILS (blurb is None). All pre-existing tests still pass.

- [ ] **Step 3: Implement the dataclass field and validation**

In `pipeline/registry.py`, add `blurb` as the last field of `Indicator`:

```python
@dataclass(frozen=True)
class Indicator:
    id: str
    name: str
    pillar: str
    role: str
    direction: str
    lag_days: int
    series: str | None = None
    formula: str | None = None
    inputs: tuple[str, ...] | None = None
    blurb: str | None = None
```

In `_validate`, inside the `for i in reg.indicators:` loop (after the direction/role checks), add:

```python
        if not i.blurb or not i.blurb.strip():
            errors.append(f"{i.id}: missing blurb (plain-language definition is required)")
```

- [ ] **Step 4: Add blurbs to all 28 indicators in `config/registry.yaml`**

Each existing flow-style entry gets `blurb: "..."` appended inside its braces (change the closing `}` line to end with `,` and add a continuation line, keeping the two-space-deeper indent). Example of the mechanical form:

```yaml
  - {id: cape, name: "Shiller CAPE", pillar: valuation, role: magnitude, direction: normal, series: shiller_cape, lag_days: 20,
     blurb: "Robert Shiller's cyclically-adjusted price-to-earnings ratio: the S&P 500's price divided by its average inflation-adjusted earnings over the past 10 years, smoothing boom-bust earnings swings. Higher CAPE means pricier stocks versus their long-run earning power; it peaked near 44 in December 1999."}
```

The exact blurb text for every indicator (use verbatim):

| id | blurb |
|----|-------|
| buffett | The total market value of US corporate equities divided by GDP — how big the stock market is relative to the real economy beneath it. Higher means stocks are more expensive by this yardstick, so a higher value scores a higher froth percentile. |
| cape | Robert Shiller's cyclically-adjusted price-to-earnings ratio: the S&P 500's price divided by its average inflation-adjusted earnings over the past 10 years, smoothing boom-bust earnings swings. Higher CAPE means pricier stocks versus their long-run earning power; it peaked near 44 in December 1999. |
| erp | Equity risk premium: the extra annual return stocks are priced to deliver over safe inflation-protected government bonds (CAPE earnings yield minus the 10-year real Treasury yield). A thin premium means stocks offer little reward for their risk — this indicator is inverted, so a LOWER premium scores a HIGHER froth percentile. |
| baa_spread | The extra yield investors demand for medium-quality (Baa-rated) corporate bonds over 10-year Treasuries. Tight spreads mean lenders are relaxed and credit flows freely — typical boom behavior — so this indicator is inverted: a NARROWER spread scores a HIGHER froth percentile. |
| household_debt_gdp | Total US household debt (mortgages, cards, loans) divided by GDP. The higher it is, the more stretched family balance sheets are and the more a downturn feeds on itself; it peaked near 100% of GDP just before the 2008 crisis. |
| corporate_debt_gdp | Debt of US non-financial businesses divided by GDP. High corporate leverage means more companies are vulnerable to falling profits or rising rates — fuel that can turn an ordinary slowdown into a credit bust. |
| sloos_tightening | From the Fed's Senior Loan Officer Opinion Survey: the net share of banks tightening standards on business loans. Negative means banks are loosening and credit is easy — boom behavior — so this indicator is inverted: EASIER lending scores a HIGHER froth percentile. |
| m2_yoy | Year-over-year growth of the M2 money supply (cash, checking, savings and similar deposits). Fast money growth means abundant liquidity that can chase asset prices; it spiked above 25% in 2020-21 ahead of the post-COVID inflation. |
| fed_bs_yoy | Year-over-year growth of the Federal Reserve's total assets. When the Fed buys bonds ('quantitative easing') its balance sheet swells and newly created money flows toward markets, so faster growth means easier conditions and a higher froth percentile. |
| net_liquidity | The Fed's balance sheet minus the Treasury's cash account (TGA) and money parked back at the Fed overnight (reverse repos, RRP) — a rough gauge of how much central-bank money is actually free to slosh around markets rather than sitting idle. |
| real_ffr | The Fed's policy rate minus core inflation — the true, inflation-adjusted cost of overnight money. When negative, borrowing is effectively free in real terms and speculation is cheap to fund; this indicator is inverted, so a LOWER real rate scores a HIGHER froth percentile. |
| curve_10y2y | The 10-year Treasury yield minus the 2-year — the classic yield-curve slope. Below zero ('inversion') means markets expect rate cuts ahead, historically a recession warning 6-24 months early. Inverted indicator: a more NEGATIVE spread scores a HIGHER froth percentile. |
| curve_10y3m | The 10-year Treasury yield minus the 3-month bill — the yield-curve measure with the best recession-forecasting record. Below zero the curve is inverted: short-term money pays more than long-term, meaning markets expect trouble. Inverted indicator: deeper inversion scores a HIGHER froth percentile. |
| vix | The market's expectation of S&P 500 volatility over the next 30 days, implied by option prices — the 'fear gauge'. A low VIX signals complacency, which is when bubbles inflate, so this indicator is inverted: CALM markets score a HIGHER froth percentile. |
| btc_yoy | Bitcoin's price change over the past year, used here purely as a speculative-appetite thermometer. Triple-digit yearly gains signal the kind of 'risk-on' euphoria that accompanied past manias. |
| sahm | Claudia Sahm's recession rule: how far the 3-month average unemployment rate has risen above its low of the past 12 months. A gap of 0.5 points or more has marked the start of every US recession since 1970. A confirmation signal — it fires as a downturn begins, not before. |
| cfnai_act | The Chicago Fed National Activity Index, a weighted blend of 85 monthly indicators of production, jobs, spending and housing. Zero means trend growth; deeply negative means contraction. Inverted here: WEAKER activity scores HIGHER, and like the Sahm rule it confirms a downturn rather than predicting one. |
| spx_200dma_dist | How far the S&P 500 sits above or below its own 200-day moving average, the standard long-term trend line. A break below it is a classic sign the uptrend has cracked. Inverted indicator: a deeper break BELOW trend scores a HIGHER percentile — this confirms stress rather than predicting it. |
| rsp_spy_breadth | Compares the equal-weighted S&P 500 (RSP) against the ordinary cap-weighted index (SPY) relative to its own 200-day trend. When the ratio sinks, gains are carried by a few giant stocks while the average stock lags — 'narrow breadth', a classic late-cycle divergence. Inverted: NARROWER breadth scores HIGHER. |
| dollar_spliced | The dollar's value against a trade-weighted basket of other currencies (two official series spliced at 2019). A sharply stronger dollar tightens global finance — foreign borrowers of dollars get squeezed — and often accompanies stress episodes. A confirmation-side input, not a bubble ingredient. |
| margin_debt_yoy | Year-over-year change in margin debt — money borrowed against brokerage accounts to buy more securities. Rapid growth means investors are leveraging up to chase the rally, one of the most reliable late-bubble behaviors; it peaked just before the 2000 and 2007 tops. |
| cpi_yoy | The Consumer Price Index's change over the past year — headline inflation, the everyday cost of living including food and energy. Display-only context: it shapes what the Fed does but is not part of any score on this site. |
| core_cpi_yoy | CPI inflation excluding volatile food and energy prices — the 'core' measure the Fed watches to judge underlying inflation pressure. Display-only context, excluded from all scores. |
| ppi_yoy | Producer Price Index inflation: the change in prices businesses receive, often an early hint of consumer inflation ahead as costs pass through supply chains. Display-only context, excluded from all scores. |
| payrolls_yoy | Year-over-year growth in nonfarm payrolls — the total count of US jobs from the monthly employment report. Around +1.5-2% is healthy; near zero or negative signals a stalling economy. Display-only context, excluded from all scores. |
| unemployment | The share of the labor force actively looking for work. It moves slowly but rarely rises just a little — once it turns decisively up, a recession is usually already under way (the Sahm rule formalizes exactly this). Display-only context, excluded from all scores. |
| job_openings | Unfilled job openings from the JOLTS survey — a gauge of how hot labor demand is. Falling openings are usually the first crack in a cooling job market, showing up before layoffs do. Display-only context, excluded from all scores. |
| fed_funds | The Federal Reserve's policy interest rate — the overnight rate banks charge each other, which anchors borrowing costs across the economy. Rising means the Fed is braking, falling means stimulating. Display-only context; its inflation-adjusted version (the real Fed funds rate) IS scored in the liquidity pillar. |

- [ ] **Step 5: Run the tests**

Run: `venv/bin/python -m pytest tests/test_registry.py -v`
Expected: ALL PASS (including the two new tests and the fixed pairing test).

- [ ] **Step 6: Run the full suite to catch fixture fallout**

Run: `venv/bin/python -m pytest tests/ -q`
Expected: ALL PASS. (Direct `Indicator(...)` constructions in other tests use positional args and are unaffected — `blurb` defaults to `None` and only `load_registry` validates it.)

- [ ] **Step 7: Commit**

```bash
git add pipeline/registry.py config/registry.yaml tests/test_registry.py
git commit -m "feat: required plain-language blurb for every registry indicator"
```

---

### Task 2: Export blurbs into indicators.json

**Files:**
- Modify: `pipeline/export.py` (~line 210, the `indicators[ind.id] = {...}` dict)
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: `Indicator.blurb` from Task 1.
- Produces: every entry in `site/data/indicators.json` has a `"blurb"` key (string or `null`). Tasks 3 and 4 read `d.blurb` from this JSON.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_export.py` (note: `Registry`, `Indicator` are already imported at the top; add `from dataclasses import replace` to the imports):

```python
def test_export_indicators_include_blurb(site):
    reg = make_reg()
    reg = Registry(
        series=reg.series,
        indicators=[replace(i, blurb=f"About {i.id}.") for i in reg.indicators],
        pillar_weights=reg.pillar_weights,
    )
    export.export_site(reg, THX)
    indicators = json.loads((site / "indicators.json").read_text())
    assert indicators["i_up"]["blurb"] == "About i_up."


def test_export_blurb_key_present_even_when_unset(site):
    # Fixture registries built directly (not via load_registry) may carry blurb=None;
    # the key must still exist so the frontend can guard on d.blurb uniformly.
    export.export_site(make_reg(), THX)
    indicators = json.loads((site / "indicators.json").read_text())
    assert "blurb" in indicators["i_up"] and indicators["i_up"]["blurb"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_export.py -v -k blurb`
Expected: both FAIL with `KeyError: 'blurb'`.

- [ ] **Step 3: Implement**

In `pipeline/export.py`, in the `indicators[ind.id] = {` dict (currently starting `"name": ind.name, "pillar": ind.pillar, ...`), add one line after `"direction": ind.direction, "frequency": r.frequency,`:

```python
            "blurb": ind.blurb,
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/python -m pytest tests/test_export.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/export.py tests/test_export.py
git commit -m "feat: export indicator blurbs to indicators.json"
```

---

### Task 3: Show the blurb in the drill-down

**Files:**
- Modify: `site/assets/app.js` (`renderIndicator`, ~line 330)
- Modify: `site/assets/style.css`

**Interfaces:**
- Consumes: `INDICATORS[id].blurb` (string or null) from Task 2's JSON.

- [ ] **Step 1: Implement the blurb paragraph**

In `site/assets/app.js` `renderIndicator()`, extend the `indicator-meta` innerHTML assignment — change:

```js
  document.getElementById("indicator-meta").innerHTML =
    `<span class="chip">${d.role}</span><span class="chip">${d.direction}</span>` +
    `<span class="chip">${d.frequency}</span>` +
    `<span class="chip">pct ${d.latest.pct_full ?? "n/a"}</span>` +
    `<span class="chip">z ${d.latest.zscore ?? "n/a"}</span>` +
    (d.stale ? ' <span class="badge-stale">STALE</span>' : "") +
    ` <span class="muted">last obs ${d.last_obs}</span>`;
```

to:

```js
  document.getElementById("indicator-meta").innerHTML =
    `<span class="chip">${d.role}</span><span class="chip">${d.direction}</span>` +
    `<span class="chip">${d.frequency}</span>` +
    `<span class="chip">pct ${d.latest.pct_full ?? "n/a"}</span>` +
    `<span class="chip">z ${d.latest.zscore ?? "n/a"}</span>` +
    (d.stale ? ' <span class="badge-stale">STALE</span>' : "") +
    ` <span class="muted">last obs ${d.last_obs}</span>` +
    // definition for the PRIMARY indicator only -- pinned compare extras would repeat
    // near-identical prose and crowd the chart.
    (d.blurb ? `<p class="indicator-blurb muted">${d.blurb}</p>` : "");
```

Append to `site/assets/style.css`:

```css
.indicator-blurb { margin:8px 0 4px; max-width:75ch; }
```

- [ ] **Step 2: Syntax check**

Run: `node --check site/assets/app.js`
Expected: no output (exit 0).

- [ ] **Step 3: Visual smoke check**

Run: `python3 -m http.server 8213 --directory site &` then open `http://localhost:8213/` in a browser, pick any indicator in the drill-down. Expected: a muted definition paragraph under the meta chips. (If `indicators.json` predates Task 2, blurbs are absent until Task 11 regenerates data — in that case just confirm no JS error and move on; kill the server after.)

- [ ] **Step 4: Commit**

```bash
git add site/assets/app.js site/assets/style.css
git commit -m "feat: show indicator definition in the drill-down"
```

---

### Task 4: Guide glossary — concept terms + auto-rendered indicator glossary

**Files:**
- Modify: `site/guide.html` (new section 11 before `</article>`; one sentence added to section 9)
- Modify: `site/assets/style.css` (dt/dd styles)

**Interfaces:**
- Consumes: `data/indicators.json` entries `{name, pillar, blurb}` from Task 2.

- [ ] **Step 1: Add the glossary section**

In `site/guide.html`, insert immediately before `</article>` (after the section-10 paragraph):

```html
<h2>11. Glossary</h2>
<h3>Concepts used throughout</h3>
<dl>
<dt>Percentile</dt>
<dd>Where today's value ranks against every past value of the same series: 90th percentile
means higher than 90% of history. All "froth" scores on this site are percentiles, so every
indicator is measured against its own past rather than in raw units.</dd>
<dt>Z-score</dt>
<dd>How many standard deviations today's value sits from its historical average; beyond
&plusmn;2 is rare territory. Shown as a chip in the indicator drill-down.</dd>
<dt>Direction ("inverted" indicators)</dt>
<dd>For most indicators a higher raw value means more froth. For inverted ones (VIX, credit
spreads, the two yield-curve spreads, the real Fed funds rate, the equity risk premium,
SLOOS, breadth, S&amp;P vs 200-DMA) it's the low or negative readings that signal froth or
stress, so their percentile flips the raw ranking. Each indicator's glossary entry below
says which way it points.</dd>
<dt>Yield curve &amp; inversion</dt>
<dd>The yield curve is the lineup of Treasury interest rates from short to long maturities.
Normally long rates are higher. When short rates exceed long ones the curve is "inverted"
&mdash; historically the most reliable US recession precursor, though with long and variable
lead times.</dd>
<dt>Credit spread</dt>
<dd>The extra yield a riskier borrower must pay over Treasuries. Wide spreads = fear and
tight credit; narrow spreads = complacency and easy credit.</dd>
<dt>Drawdown</dt>
<dd>The percentage fall from a peak to a later low. "Max drawdown" is the worst such fall
over a period &mdash; the number that measures how painful a crash was.</dd>
<dt>200-day moving average (200-DMA)</dt>
<dd>The average of the last 200 trading days' closing prices &mdash; the standard dividing
line between a long-term uptrend (price above) and downtrend (price below).</dd>
<dt>Market breadth</dt>
<dd>How widely shared a rally is across stocks. Narrow breadth &mdash; a few giant companies
carrying the index while the average stock lags &mdash; is a classic late-cycle warning.</dd>
<dt>NBER recession</dt>
<dd>The "official" US recession dates, declared retrospectively by the National Bureau of
Economic Research. Chart shading only &mdash; descriptive history, not a signal.</dd>
<dt>T&minus;24m notation</dt>
<dd>Months before an episode's market peak: "dotcom T&minus;24" means the state of things 24
months before the March 2000 top; "T+6" means six months after it.</dd>
</dl>
<h3>Indicator glossary</h3>
<p class="muted">Generated from the same indicator registry that drives every score on this
site, so it always matches what the dashboard is actually computing.</p>
<div id="glossary" class="muted">Loading definitions&hellip;</div>
<script>
const PILLAR_ORDER = ["valuation", "leverage", "liquidity", "sentiment", "macro", "context"];
const PILLAR_LABEL = { valuation: "Valuation", leverage: "Leverage & credit",
  liquidity: "Liquidity & monetary", sentiment: "Sentiment & speculation",
  macro: "Macro stress & breadth", context: "Context (not scored)" };
fetch("data/indicators.json").then(r => r.json()).then(inds => {
  const byPillar = new Map(PILLAR_ORDER.map(p => [p, []]));
  for (const d of Object.values(inds)) {
    if (d.blurb && byPillar.has(d.pillar)) byPillar.get(d.pillar).push(d);
  }
  document.getElementById("glossary").outerHTML = PILLAR_ORDER.map(p => {
    const entries = byPillar.get(p).sort((a, b) => a.name.localeCompare(b.name));
    if (!entries.length) return "";
    return `<h4>${PILLAR_LABEL[p]}</h4><dl>` + entries.map(d =>
      `<dt>${d.name}</dt><dd>${d.blurb}</dd>`).join("") + "</dl>";
  }).join("");
}).catch(() => {
  document.getElementById("glossary").textContent =
    "Glossary unavailable (couldn't load indicator data).";
});
</script>
```

- [ ] **Step 2: Point section 9 at the new backtest features**

In `site/guide.html` section 9, after the sentence ending `...never adjusted after the fact just to turn a failing check green.` append:

```html
Beyond the pass/fail criteria, the Backtest page also shows a per-crisis report card (when
the tracker engaged and how much lead time it gave), a full ledger of engaged stretches
including false alarms, the S&amp;P 500 returns that historically followed each composite
band and tracker stage, and a deliberately crude "cost of caution" simulator showing what
acting on these signals would have saved &mdash; or cost &mdash; versus simply holding on.
```

- [ ] **Step 3: Style the definition lists**

Append to `site/assets/style.css`:

```css
article dt { font-weight:600; margin-top:10px; }
article dd { margin:2px 0 6px; color:var(--muted); }
article h4 { margin:14px 0 2px; font-size:.95rem; }
```

- [ ] **Step 4: Visual check**

Serve (`python3 -m http.server 8213 --directory site`), open `http://localhost:8213/guide.html`. Expected: section 11 with concept terms, and either the rendered per-pillar glossary (if indicators.json already has blurbs) or the fallback text — no console errors either way. Kill the server.

- [ ] **Step 5: Commit**

```bash
git add site/guide.html site/assets/style.css
git commit -m "feat: guide glossary -- concept terms plus auto-rendered indicator definitions"
```

---

### Task 5: Forward returns, fed funds, and regime bands in backtest.json

**Files:**
- Modify: `pipeline/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Produces: `forward_returns(spx_m: pd.Series, horizon_months: int) -> list[float | None]` (positional month-shift on a monthly series; percent ×100 rounded to 2). New payload keys: `regime_bands` (list of `{name, upper}`), `fedfunds` (list of float|None aligned to `months`), `fwd_6m`, `fwd_12m`, `fwd_24m` (lists aligned to `months`). Tasks 9–10 read these from backtest.json.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backtest.py`:

```python
def test_forward_returns_exact_and_null_tail():
    months = pd.date_range("2020-01-31", periods=4, freq="BME")
    spx = pd.Series([100.0, 110.0, 121.0, 133.1], index=months)
    assert backtest.forward_returns(spx, 1) == [10.0, 10.0, 10.0, None]
    assert backtest.forward_returns(spx, 2) == [21.0, 21.0, None, None]


def test_forward_returns_none_propagates():
    months = pd.date_range("2020-01-31", periods=3, freq="BME")
    spx = pd.Series([100.0, np.nan, 121.0], index=months)
    assert backtest.forward_returns(spx, 1) == [None, None, None]
    assert backtest.forward_returns(spx, 2) == [21.0, None, None]
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_backtest.py -v -k forward`
Expected: FAIL with `AttributeError: module 'pipeline.backtest' has no attribute 'forward_returns'`.

- [ ] **Step 3: Implement**

Add to `pipeline/backtest.py` (after `apply_lag`):

```python
def forward_returns(spx_m: pd.Series, horizon_months: int) -> list[float | None]:
    """Simple S&P price return over the next `horizon_months` entries of a monthly
    (BME-indexed) series, as percent x100 rounded to 2dp; None where the horizon runs
    past the end of the data or either endpoint is missing. Positional shift, not
    calendar arithmetic -- the input is already one row per month-end."""
    arr = spx_m.to_numpy(dtype=float)
    out: list[float | None] = []
    for i in range(len(arr)):
        j = i + horizon_months
        if j >= len(arr) or pd.isna(arr[i]) or pd.isna(arr[j]):
            out.append(None)
        else:
            out.append(round((arr[j] / arr[i] - 1.0) * 100.0, 2))
    return out
```

In `run_backtest`, after the existing `spx = raw["spx"].resample("BME").last().reindex(months)` line, add:

```python
    ff = raw.get("fedfunds")
    ff_m = (ff.resample("BME").last().reindex(months)
            if ff is not None and not ff.empty else pd.Series(index=months, dtype=float))
```

and extend the returned payload dict with (before the `"base_rate"` entry):

```python
        "regime_bands": thresholds["regime_bands"],
        "fedfunds": [None if pd.isna(v) else round(float(v), 2) for v in ff_m],
        "fwd_6m": forward_returns(spx, 6),
        "fwd_12m": forward_returns(spx, 12),
        "fwd_24m": forward_returns(spx, 24),
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/python -m pytest tests/test_backtest.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/backtest.py tests/test_backtest.py
git commit -m "feat: forward returns, fed funds, and regime bands in backtest payload"
```

---

### Task 6: Crisis report card

**Files:**
- Modify: `pipeline/backtest.py`
- Modify: `config/episodes.yaml` (dotcom `report_note`)
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `stage_s`, `engaged_s`, `spx` monthly series already built in `run_backtest`.
- Produces: `build_report_card(stage: pd.Series, engaged: pd.Series, spx_m: pd.Series, episodes: list[dict]) -> list[dict]` returning JSON-ready rows: `{episode, name, peak, control, first_engaged: str|None, first_stage4: str|None, lead_months: int|None, max_drawdown_pct: float|None, months_to_trough: int|None, engaged_months: int|None, note: str}`. Payload key `report_card`. Task 8's `renderReportCard` reads these fields.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backtest.py`:

```python
def _report_fixture():
    months = pd.date_range("1998-01-30", "2003-12-31", freq="BME")
    stage = pd.Series(0, index=months)
    stage.loc["1999-06-30":"2000-01-31"] = 4
    engaged = pd.Series(False, index=months)
    engaged.loc["1999-03-31":"2000-03-31"] = True
    spx = pd.Series(100.0, index=months)
    # decline from the 2000-03 peak to a 50.0 trough at 2001-09, then partial recovery
    decline = np.linspace(97.0, 50.0, 18)          # 2000-04-28 .. 2001-09-28
    spx.iloc[27:45] = decline
    spx.iloc[45:] = 60.0
    return months, stage, engaged, spx


def test_report_card_lead_time_and_drawdown():
    _, stage, engaged, spx = _report_fixture()
    eps = [{"id": "dotcom", "name": "Dot-com bust", "peak": "2000-03-24",
            "report_note": "margin-debt data gap"}]
    rows = backtest.build_report_card(stage, engaged, spx, eps)
    assert len(rows) == 1
    r = rows[0]
    assert r["control"] is False
    assert r["first_engaged"] == "1999-03-31"
    assert r["first_stage4"] == "1999-06-30"
    assert r["lead_months"] == 9                      # 1999-06 -> 2000-03
    assert r["max_drawdown_pct"] == -50.0             # 100 -> 50
    assert r["months_to_trough"] == 18                # 2000-03 -> 2001-09
    assert r["note"] == "margin-debt data gap"


def test_report_card_never_fired_row_is_honest():
    months, _, _, spx = _report_fixture()
    stage = pd.Series(0, index=months)
    engaged = pd.Series(False, index=months)
    rows = backtest.build_report_card(stage, engaged, spx, [
        {"id": "dotcom", "name": "Dot-com bust", "peak": "2000-03-24"}])
    r = rows[0]
    assert r["first_engaged"] is None and r["first_stage4"] is None
    assert r["lead_months"] is None
    assert r["max_drawdown_pct"] == -50.0             # drawdown is about the market, not the tracker


def test_report_card_control_row_counts_2019():
    months = pd.date_range("2018-01-31", "2020-12-31", freq="BME")
    engaged = pd.Series(False, index=months)
    engaged.loc["2019-06-28":"2019-08-30"] = True
    stage = pd.Series(0, index=months)
    spx = pd.Series(100.0, index=months)
    rows = backtest.build_report_card(stage, engaged, spx, [
        {"id": "covid", "name": "COVID crash", "peak": "2020-02-19", "control": True}])
    r = rows[0]
    assert r["control"] is True and r["engaged_months"] == 3
    assert r["first_engaged"] is None and r["lead_months"] is None


def test_report_card_skips_criterion_false():
    months, stage, engaged, spx = _report_fixture()
    rows = backtest.build_report_card(stage, engaged, spx, [
        {"id": "black1987", "name": "Black Monday", "peak": "1987-08-25", "criterion": False}])
    assert rows == []
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_backtest.py -v -k report_card`
Expected: FAIL with `AttributeError: ... no attribute 'build_report_card'`.

- [ ] **Step 3: Implement**

Add to `pipeline/backtest.py`:

```python
def _months_between(a: pd.Timestamp, b: pd.Timestamp) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def build_report_card(stage: pd.Series, engaged: pd.Series, spx_m: pd.Series,
                      episodes: list[dict]) -> list[dict]:
    """One JSON-ready row per scored episode: when the tracker first engaged / first
    reached stage 4 inside the peak-24m..peak window, the lead time that gave, and what
    the market then did (peak-to-trough on monthly closes, trough within 36 months).
    The covid control row reports engaged-months-in-2019 instead of lead times.
    Episodes with criterion: false are excluded, same rule as evaluate_criteria."""
    rows = []
    for ep in episodes:
        if ep.get("criterion") is False:
            continue
        peak = pd.Timestamp(ep["peak"])
        base = {"episode": ep["id"], "name": ep.get("name", ep["id"]), "peak": ep["peak"],
                "control": bool(ep.get("control", False)), "first_engaged": None,
                "first_stage4": None, "lead_months": None, "max_drawdown_pct": None,
                "months_to_trough": None, "engaged_months": None,
                "note": ep.get("report_note", "")}
        if ep.get("control"):
            window = engaged[(engaged.index >= "2019-01-01") & (engaged.index <= "2019-12-31")]
            base["engaged_months"] = int(window.sum())
            rows.append(base)
            continue
        in_win = (stage.index >= peak - pd.DateOffset(months=24)) & (stage.index <= peak)
        eng_dates = engaged.index[in_win & engaged.to_numpy(dtype=bool)]
        st4_dates = stage.index[in_win & (stage.to_numpy() >= 4)]
        if len(eng_dates):
            base["first_engaged"] = eng_dates[0].strftime("%Y-%m-%d")
        if len(st4_dates):
            base["first_stage4"] = st4_dates[0].strftime("%Y-%m-%d")
            base["lead_months"] = _months_between(st4_dates[0], peak)
        at_peak = spx_m[spx_m.index <= peak].dropna()
        after = spx_m[(spx_m.index > peak) & (spx_m.index <= peak + pd.DateOffset(months=36))].dropna()
        if not at_peak.empty and not after.empty:
            level = float(at_peak.iloc[-1])
            trough_date = after.idxmin()
            base["max_drawdown_pct"] = round((float(after.min()) / level - 1.0) * 100.0, 1)
            base["months_to_trough"] = _months_between(peak, trough_date)
        rows.append(base)
    return rows
```

In `run_backtest`'s payload dict add (next to the Task 5 keys):

```python
        "report_card": build_report_card(stage_s, engaged_s, spx, epi_cfg["episodes"]),
```

In `config/episodes.yaml`, change the dotcom line to:

```yaml
  - {id: dotcom,    name: "Dot-com bust",            peak: "2000-03-24",
     report_note: "Never engaged before the peak: the margin-debt series doesn't reach back far enough, and the yield curve re-steepened only after March 2000."}
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/python -m pytest tests/test_backtest.py tests/test_episodes_lib.py tests/test_episodes.py -q`
Expected: ALL PASS (episode tests confirm the yaml edit didn't break loading).

- [ ] **Step 5: Commit**

```bash
git add pipeline/backtest.py config/episodes.yaml tests/test_backtest.py
git commit -m "feat: per-crisis report card in backtest payload"
```

---

### Task 7: Alarm ledger

**Files:**
- Modify: `pipeline/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `engaged_s`, `spx` monthly series in `run_backtest`.
- Produces: `find_alarm_runs(engaged: pd.Series, spx_m: pd.Series, episodes: list[dict], replay_start: str = REPLAY_START) -> list[dict]` returning `{start, end, months, in_window: bool, episode: str|None, fwd_12m_pct: float|None, max_dd_12m_pct: float|None}` per contiguous engaged run. Payload key `alarms`. Task 8's `renderAlarms` reads these fields.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backtest.py`:

```python
def test_alarm_runs_detection_and_classification():
    months = pd.date_range("1999-01-29", "2001-12-31", freq="BME")   # 36 month-ends
    engaged = pd.Series(False, index=months)
    engaged.iloc[2:5] = True     # 1999-03..1999-05: ends BEFORE the window opens -> false alarm
    engaged.iloc[20:23] = True   # 2000-09..2000-11: inside window -> warning
    engaged.iloc[33:] = True     # 2001-10..2001-12: starts AFTER the peak -> false alarm
    spx = pd.Series([100.0 * 1.01 ** i for i in range(36)], index=months)
    eps = [{"id": "ep1", "name": "Episode 1", "peak": "2001-06-15"}]
    runs = backtest.find_alarm_runs(engaged, spx, eps, replay_start="1999-01-01")
    assert [(r["start"], r["end"], r["months"]) for r in runs] == [
        ("1999-03-31", "1999-05-31", 3),
        ("2000-09-29", "2000-11-30", 3),
        ("2001-10-31", "2001-12-31", 3),
    ]
    assert [r["in_window"] for r in runs] == [False, True, False]
    assert runs[1]["episode"] == "ep1" and runs[0]["episode"] is None
    # rising 1%/mo market: +12m return ~12.68%, worst dip from a rising start is 0
    assert runs[0]["fwd_12m_pct"] == pytest.approx(12.68, abs=0.01)
    assert runs[0]["max_dd_12m_pct"] == 0.0
    # last run starts at index 33; 33+12 is past the end -> fwd unknown, dd over what exists
    assert runs[2]["fwd_12m_pct"] is None
    assert runs[2]["max_dd_12m_pct"] == 0.0


def test_alarm_runs_empty_when_never_engaged():
    months = pd.date_range("1999-01-29", periods=12, freq="BME")
    engaged = pd.Series(False, index=months)
    spx = pd.Series(100.0, index=months)
    assert backtest.find_alarm_runs(engaged, spx, [], replay_start="1999-01-01") == []


def test_alarm_runs_ignore_control_and_pre_replay_episodes():
    months = pd.date_range("1999-01-29", "2000-12-29", freq="BME")
    engaged = pd.Series(True, index=months)   # one giant run
    spx = pd.Series(100.0, index=months)
    eps = [{"id": "old", "name": "Old", "peak": "1990-07-16"},
           {"id": "ctl", "name": "Control", "peak": "2000-06-15", "control": True}]
    runs = backtest.find_alarm_runs(engaged, spx, eps, replay_start="1999-01-01")
    assert len(runs) == 1 and runs[0]["in_window"] is False and runs[0]["episode"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_backtest.py -v -k alarm`
Expected: FAIL with `AttributeError: ... no attribute 'find_alarm_runs'`.

- [ ] **Step 3: Implement**

Add to `pipeline/backtest.py`:

```python
def find_alarm_runs(engaged: pd.Series, spx_m: pd.Series, episodes: list[dict],
                    replay_start: str = REPLAY_START) -> list[dict]:
    """Every maximal contiguous engaged==True run, classified against the peak-24m..peak
    windows of non-control episodes whose peak falls inside the replay (criterion-false
    episodes like black1987 still count as windows here -- an engaged run before a real
    crash isn't a false alarm just because the criteria table skips that episode).
    Attribution prefers the nearest peak on/after the run start. fwd_12m_pct is None when
    12 months of future don't exist yet; max_dd_12m_pct uses whatever future does exist."""
    start_ts = pd.Timestamp(replay_start)
    windows = [(ep["id"], pd.Timestamp(ep["peak"]) - pd.DateOffset(months=24), pd.Timestamp(ep["peak"]))
               for ep in episodes
               if not ep.get("control") and pd.Timestamp(ep["peak"]) >= start_ts]
    flags = engaged.astype(bool)
    bounds: list[tuple] = []
    run_start = prev = None
    for date, flag in flags.items():
        if flag and run_start is None:
            run_start = date
        if not flag and run_start is not None:
            bounds.append((run_start, prev))
            run_start = None
        prev = date
    if run_start is not None:
        bounds.append((run_start, prev))

    arr = spx_m.to_numpy(dtype=float)
    out = []
    for s, e in bounds:
        overlapping = [(wid, wpeak) for wid, wstart, wpeak in windows if s <= wpeak and e >= wstart]
        episode = None
        if overlapping:
            on_or_after = [w for w in overlapping if w[1] >= s]
            episode = min(on_or_after or overlapping, key=lambda w: abs((w[1] - s).days))[0]
        i = int(spx_m.index.get_loc(s))
        j = i + 12
        fwd = dd = None
        if not pd.isna(arr[i]):
            if j < len(arr) and not pd.isna(arr[j]):
                fwd = round((arr[j] / arr[i] - 1.0) * 100.0, 2)
            seg = arr[i: min(j, len(arr) - 1) + 1]
            seg = seg[~pd.isna(seg)]
            if len(seg):
                dd = round((float(seg.min()) / arr[i] - 1.0) * 100.0, 2)
        out.append({"start": s.strftime("%Y-%m-%d"), "end": e.strftime("%Y-%m-%d"),
                    "months": _months_between(s, e) + 1, "in_window": episode is not None,
                    "episode": episode, "fwd_12m_pct": fwd, "max_dd_12m_pct": dd})
    return out
```

In `run_backtest`'s payload dict add:

```python
        "alarms": find_alarm_runs(engaged_s, spx, epi_cfg["episodes"]),
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/python -m pytest tests/test_backtest.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/backtest.py tests/test_backtest.py
git commit -m "feat: alarm ledger (engaged runs classified vs crisis windows) in backtest payload"
```

---

### Task 8: Backtest page restructure — report card, alarm ledger, prose

**Files:**
- Rewrite: `site/backtest.html`
- Create: `site/assets/backtest.js`
- Modify: `site/assets/style.css`

**Interfaces:**
- Consumes: `report_card` (Task 6), `alarms` (Task 7), plus existing `months/spx/composite/stage/episodes/criteria` keys.
- Produces: `site/assets/backtest.js` with a single `fetch("data/backtest.json")` boot calling `renderReportCard(bt)`, `renderChart(bt)`, `renderCriteria(bt)`, `renderAlarms(bt)`. Tasks 9–10 append `renderForwardReturns(bt)` / `initSimulator(bt)` and add their calls to this boot chain. Shared helpers `DARK`, `CFG`, `fmtPct` defined here and reused by Tasks 9–10.

- [ ] **Step 1: Rewrite `site/backtest.html`**

Replace the whole file with:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backtest - Macro Bubble Monitor</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header><h1><a href="index.html" style="text-decoration:none;color:inherit">&larr; Macro Bubble Monitor</a></h1>
<div class="muted">Sequencer replay (monthly, publication-lag adjusted) · composite shown as published</div></header>
<section class="card"><p>Every month since January 1987 is re-scored using only information that was
available at the time: each data series is shifted by its real-world publication lag, percentiles are
computed against history up to that month only, and the composite is shown as it was published. The
sequence tracker is then replayed month by month against that reconstructed past. Nothing on this page
is fitted after the fact &mdash; thresholds only change when new evidence is written down in advance
(see <a href="guide.html">the guide</a>).</p></section>
<section class="card"><h2>Crisis report card</h2><div id="bt-report"></div></section>
<section class="card"><div id="bt-chart"></div></section>
<section class="card"><h2>Validation criteria</h2><div id="bt-criteria"></div></section>
<section class="card"><h2>What happened next</h2>
<p class="muted">S&amp;P 500 price return over the following 6 / 12 / 24 months, grouped by what this
site's gauges said at the time. Price only &mdash; dividends excluded; adjacent months share most of
their forward window, so these are not independent samples.</p>
<div id="bt-fwd-regime"></div><div id="bt-fwd-stage"></div><div id="bt-fwd-note" class="muted"></div></section>
<section class="card"><h2>Alarm ledger</h2>
<p class="muted">Every stretch where the sequence tracker was &ldquo;engaged&rdquo;, split by whether a
real crisis window (24 months before a past peak) followed. What the market did next is shown either
way &mdash; false alarms included, per the site's honesty rule.</p>
<div id="bt-alarms"></div></section>
<section class="card"><h2>Cost of caution &mdash; a toy exercise</h2>
<p class="muted">Educational replay, not investment advice: S&amp;P prices exclude dividends (which
understates equity returns), there are no taxes or trading costs, and the rule is deliberately crude.
The honest historical lesson is usually that caution buys smaller drawdowns at the price of compounding.</p>
<div class="sim-controls">
<label>De-risk when <select id="sim-trigger"></select></label>
<label>moving <input type="range" id="sim-cash" min="0" max="100" step="5" value="50">
<span id="sim-cash-label">50%</span> to cash (earning the fed funds rate)</label>
</div>
<div id="bt-sim-chart"></div><div id="bt-sim-stats"></div></section>
<footer class="muted">Monitoring context, not a trading signal.</footer>
<script src="assets/plotly-finance.min.js"></script>
<script src="assets/backtest.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create `site/assets/backtest.js`**

```js
const DARK = { paper_bgcolor: "#1b2029", plot_bgcolor: "#1b2029", font: { color: "#e6e9ef", size: 12 } };
const CFG = { displayModeBar: false, responsive: true };
const fmtPct = v => v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;

function renderReportCard(bt) {
  const rows = bt.report_card.map(r => {
    if (r.control) {
      return `<tr><td>${r.name}</td><td>${r.peak}</td>` +
             `<td colspan="5">${r.engaged_months} engaged month${r.engaged_months === 1 ? "" : "s"} in 2019 (control target: 0)</td>` +
             `<td>${r.note || ""}</td></tr>`;
    }
    return `<tr><td>${r.name}</td><td>${r.peak}</td><td>${r.first_engaged ?? "never"}</td>` +
           `<td>${r.first_stage4 ?? "never"}</td><td>${r.lead_months ?? "–"}</td>` +
           `<td>${fmtPct(r.max_drawdown_pct)}</td><td>${r.months_to_trough ?? "–"}</td><td>${r.note || ""}</td></tr>`;
  }).join("");
  document.getElementById("bt-report").innerHTML =
    `<table class="bt-table"><tr><th>Episode</th><th>Peak</th><th>First engaged</th>` +
    `<th>First stage ≥ 4</th><th>Lead (months)</th><th>Drawdown after peak</th>` +
    `<th>Months to trough</th><th>Note</th></tr>${rows}</table>`;
}

// The 3-row replay figure, unchanged from the previous inline version of this page.
function renderChart(bt) {
  const shapes = bt.episodes.filter(e => e.criterion !== false || e.control).map(e => {
    const peak = new Date(e.peak); const start = new Date(peak); start.setMonth(start.getMonth() - 24);
    return { type: "rect", x0: start.toISOString().slice(0, 10), x1: e.peak, y0: 0, y1: 1,
             yref: "paper", fillcolor: "rgba(214,69,69,.08)", line: { width: 0 } };
  });
  Plotly.newPlot("bt-chart", [
    { x: bt.months, y: bt.spx, name: "S&P 500 (log)", yaxis: "y", line: { color: "#e6e9ef", width: 1.4 } },
    { x: bt.months, y: bt.composite, name: "Composite", yaxis: "y2", line: { color: "#e0b83c", width: 1.2 } },
    { x: bt.months, y: bt.stage, name: "Sequence stage", yaxis: "y3", line: { color: "#d64545", width: 1.2, shape: "hv" } },
  ], { ...DARK, height: 520, shapes, grid: { rows: 3, columns: 1, roworder: "top to bottom" },
       yaxis: { type: "log", title: { text: "S&P 500" } },
       yaxis2: { range: [0, 100], title: { text: "score" } },
       yaxis3: { range: [0, 6.5], dtick: 1, title: { text: "stage" } },
       legend: { orientation: "h", y: -0.08 } }, CFG);
}

function renderCriteria(bt) {
  document.getElementById("bt-criteria").innerHTML = "<ul>" + bt.criteria.map(c =>
    `<li>${c.pass ? "✅" : "❌"} ${c.name} <span class="muted">(${c.detail})</span></li>`).join("") + "</ul>";
}

function renderAlarms(bt) {
  const head = `<tr><th>Engaged from</th><th>To</th><th>Months</th><th>Episode</th>` +
               `<th>S&P +12m later</th><th>Worst dip within 12m</th></tr>`;
  const row = a => `<tr><td>${a.start}</td><td>${a.end}</td><td>${a.months}</td>` +
    `<td>${a.episode ?? "–"}</td><td>${fmtPct(a.fwd_12m_pct)}</td><td>${fmtPct(a.max_dd_12m_pct)}</td></tr>`;
  const warn = bt.alarms.filter(a => a.in_window), fals = bt.alarms.filter(a => !a.in_window);
  document.getElementById("bt-alarms").innerHTML =
    `<h3>Warnings that preceded a crisis</h3>` +
    (warn.length ? `<table class="bt-table">${head}${warn.map(row).join("")}</table>`
                 : `<p class="muted">None.</p>`) +
    `<h3>False alarms</h3>` +
    (fals.length ? `<table class="bt-table">${head}${fals.map(row).join("")}</table>`
                 : `<p class="muted">None in ${bt.months.length} replayed months.</p>`);
}

fetch("data/backtest.json").then(r => r.json()).then(bt => {
  renderReportCard(bt);
  renderChart(bt);
  renderCriteria(bt);
  renderAlarms(bt);
});
```

- [ ] **Step 3: Add table/control styles**

Append to `site/assets/style.css`:

```css
.bt-table { width:100%; font-size:.85rem; border-collapse:collapse; margin:10px 0; }
.bt-table td, .bt-table th { padding:4px 8px; border-bottom:1px solid var(--line); text-align:left; }
.sim-controls { display:flex; flex-wrap:wrap; gap:16px; align-items:center; margin:10px 0; }
.sim-controls label { font-size:.85rem; color:var(--muted); }
```

- [ ] **Step 4: Syntax check**

Run: `node --check site/assets/backtest.js` — expected exit 0.
Do NOT visually check the page yet: until Task 11 regenerates `backtest.json`, `bt.report_card` is undefined and the fetch handler throws before anything renders. The full visual pass happens in Task 11.

- [ ] **Step 5: Commit**

```bash
git add site/backtest.html site/assets/backtest.js site/assets/style.css
git commit -m "feat: backtest page restructure -- report card, alarm ledger, replay prose"
```

---

### Task 9: Forward-return box plots

**Files:**
- Modify: `site/assets/backtest.js`

**Interfaces:**
- Consumes: `fwd_6m/fwd_12m/fwd_24m`, `composite`, `stage`, `regime_bands` from backtest.json (Task 5); `DARK`/`CFG` from Task 8.
- Produces: `renderForwardReturns(bt)`, called from the boot chain.

- [ ] **Step 1: Implement**

Add to `site/assets/backtest.js` (before the fetch boot):

```js
function regimeOf(score, bands) {
  if (score == null) return null;
  for (const b of bands) if (score <= b.upper) return b.name;
  return bands[bands.length - 1].name;
}

// One grouped-box figure: x = group label, one box trace per horizon.
function fwdBoxFigure(elId, groups, bt, title) {
  const horizons = [["fwd_6m", "6m"], ["fwd_12m", "12m"], ["fwd_24m", "24m"]];
  const traces = horizons.map(([key, label]) => {
    const x = [], y = [];
    for (const g of groups) for (const i of g.idx) {
      const v = bt[key][i];
      if (v != null) { x.push(g.label); y.push(v); }
    }
    return { type: "box", name: label, x, y, boxpoints: false };
  });
  Plotly.newPlot(elId, traces, { ...DARK, boxmode: "group", height: 330,
    margin: { l: 45, r: 15, t: 30, b: 60 }, title: { text: title, font: { size: 13 } },
    yaxis: { title: { text: "forward return %" }, zeroline: true, zerolinecolor: "#8b93a3" },
    legend: { orientation: "h", y: -0.25 } }, CFG);
}

function pctNegative12m(bt, idx) {
  const vals = idx.map(i => bt.fwd_12m[i]).filter(v => v != null);
  return vals.length ? Math.round(100 * vals.filter(v => v < 0).length / vals.length) : null;
}

function renderForwardReturns(bt) {
  const n = bt.months.length;
  const all = { label: `all (n=${n})`, idx: [...Array(n).keys()] };

  const regimeGroups = bt.regime_bands.map(b => ({ name: b.name, label: b.name.replace("_", " "), idx: [] }));
  bt.composite.forEach((c, i) => {
    const r = regimeOf(c, bt.regime_bands);
    if (r) regimeGroups.find(g => g.name === r).idx.push(i);
  });
  regimeGroups.forEach(g => { g.label = `${g.label} (n=${g.idx.length})`; });
  fwdBoxFigure("bt-fwd-regime", [all, ...regimeGroups], bt,
               "S&P 500 forward returns by composite regime at the time");

  const stageGroups = [
    { label: "stage 0", test: s => s === 0 },
    { label: "stage 1–3", test: s => s >= 1 && s <= 3 },
    { label: "stage ≥ 4", test: s => s >= 4 },
  ].map(g => ({ label: g.label, idx: bt.stage.map((s, i) => g.test(s) ? i : -1).filter(i => i >= 0) }));
  stageGroups.forEach(g => { g.label = `${g.label} (n=${g.idx.length})`; });
  fwdBoxFigure("bt-fwd-stage", [all, ...stageGroups], bt,
               "S&P 500 forward returns by sequence stage at the time");

  const noteParts = [all, ...regimeGroups, ...stageGroups].map(g => {
    const p = pctNegative12m(bt, g.idx);
    return p == null ? null : `${g.label}: ${p}% of 12-month windows negative`;
  }).filter(Boolean);
  document.getElementById("bt-fwd-note").textContent = noteParts.join(" · ");
}
```

Then extend the boot chain — change the fetch handler to:

```js
fetch("data/backtest.json").then(r => r.json()).then(bt => {
  renderReportCard(bt);
  renderChart(bt);
  renderCriteria(bt);
  renderForwardReturns(bt);
  renderAlarms(bt);
});
```

- [ ] **Step 2: Syntax check**

Run: `node --check site/assets/backtest.js` — expected exit 0.

- [ ] **Step 3: Commit**

```bash
git add site/assets/backtest.js
git commit -m "feat: forward-return distributions by regime and stage on backtest page"
```

---

### Task 10: Cost-of-caution simulator

**Files:**
- Modify: `site/assets/backtest.js`

**Interfaces:**
- Consumes: `spx`, `composite`, `stage`, `fedfunds`, `regime_bands`, `months` from backtest.json; `DARK`/`CFG`/`fmtPct` from Task 8; the `#sim-trigger`, `#sim-cash`, `#sim-cash-label`, `#bt-sim-chart`, `#bt-sim-stats` elements from Task 8's HTML.
- Produces: `initSimulator(bt)`, called from the boot chain.

- [ ] **Step 1: Implement**

Add to `site/assets/backtest.js`:

```js
// Trigger tests take the month index whose END-OF-MONTH signal decides the NEXT month's
// position (the caller passes t-1) -- no look-ahead by construction.
function triggerDefs(bt) {
  const warmUpper = bt.regime_bands[1].upper;    // above this = Frothy or worse
  const frothyUpper = bt.regime_bands[2].upper;  // above this = Bubble risk
  return [
    { key: "stage4", label: "sequence stage ≥ 4", test: i => bt.stage[i] >= 4 },
    { key: "stage3", label: "sequence stage ≥ 3", test: i => bt.stage[i] >= 3 },
    { key: "frothy", label: `composite Frothy or worse (> ${warmUpper})`,
      test: i => bt.composite[i] != null && bt.composite[i] > warmUpper },
    { key: "bubble", label: `composite Bubble risk (> ${frothyUpper})`,
      test: i => bt.composite[i] != null && bt.composite[i] > frothyUpper },
    { key: "either", label: `Bubble risk OR stage ≥ 4`,
      test: i => (bt.composite[i] != null && bt.composite[i] > frothyUpper) || bt.stage[i] >= 4 },
  ];
}

function runSim(bt, test, cashFrac) {
  let first = bt.spx.findIndex(v => v != null);
  const dates = [bt.months[first]], strat = [1], hold = [1];
  let months = 0, deRisked = 0;
  for (let t = first + 1; t < bt.months.length; t++) {
    if (bt.spx[t] == null || bt.spx[t - 1] == null) break;
    const rEq = bt.spx[t] / bt.spx[t - 1] - 1;
    const rCash = bt.fedfunds[t - 1] != null ? bt.fedfunds[t - 1] / 100 / 12 : 0;
    const on = test(t - 1);
    const wEq = on ? 1 - cashFrac : 1;
    strat.push(strat[strat.length - 1] * (1 + wEq * rEq + (1 - wEq) * rCash));
    hold.push(hold[hold.length - 1] * (1 + rEq));
    dates.push(bt.months[t]);
    months++; if (on) deRisked++;
  }
  return { dates, strat, hold, months, deRisked };
}

function simStats(curve, months) {
  const final = curve[curve.length - 1];
  const cagr = (Math.pow(final, 12 / months) - 1) * 100;
  let peak = -Infinity, dd = 0;
  for (const v of curve) { if (v > peak) peak = v; dd = Math.min(dd, v / peak - 1); }
  return { final, cagr, dd: dd * 100 };
}

function renderSim(bt, triggers) {
  const trig = triggers.find(t => t.key === document.getElementById("sim-trigger").value);
  const cashFrac = +document.getElementById("sim-cash").value / 100;
  document.getElementById("sim-cash-label").textContent = `${Math.round(cashFrac * 100)}%`;
  const r = runSim(bt, trig.test, cashFrac);
  Plotly.newPlot("bt-sim-chart", [
    { x: r.dates, y: r.hold, name: "Buy & hold", line: { color: "#8b93a3", width: 1.3 } },
    { x: r.dates, y: r.strat, name: "De-risking rule", line: { color: "#6ea8fe", width: 1.6 } },
  ], { ...DARK, height: 340, margin: { l: 50, r: 15, t: 10, b: 35 },
       yaxis: { type: "log", title: { text: "growth of $1 (log)" } },
       legend: { orientation: "h", y: -0.12 } }, CFG);
  const s = simStats(r.strat, r.months), h = simStats(r.hold, r.months);
  document.getElementById("bt-sim-stats").innerHTML =
    `<table class="bt-table"><tr><th></th><th>CAGR</th><th>Max drawdown</th>` +
    `<th>Growth of $1</th><th>Months de-risked</th></tr>` +
    `<tr><td>De-risking rule</td><td>${fmtPct(s.cagr)}</td><td>${fmtPct(s.dd)}</td>` +
    `<td>${s.final.toFixed(1)}×</td><td>${r.deRisked} of ${r.months} (${Math.round(100 * r.deRisked / r.months)}%)</td></tr>` +
    `<tr><td>Buy &amp; hold</td><td>${fmtPct(h.cagr)}</td><td>${fmtPct(h.dd)}</td>` +
    `<td>${h.final.toFixed(1)}×</td><td>0</td></tr></table>`;
}

function initSimulator(bt) {
  const triggers = triggerDefs(bt);
  const sel = document.getElementById("sim-trigger");
  sel.innerHTML = triggers.map(t => `<option value="${t.key}">${t.label}</option>`).join("");
  sel.value = "stage4";
  sel.addEventListener("change", () => renderSim(bt, triggers));
  document.getElementById("sim-cash").addEventListener("input", () => renderSim(bt, triggers));
  renderSim(bt, triggers);
}
```

Add `initSimulator(bt);` as the last call in the fetch boot chain.

- [ ] **Step 2: Syntax check**

Run: `node --check site/assets/backtest.js` — expected exit 0.

- [ ] **Step 3: Commit**

```bash
git add site/assets/backtest.js
git commit -m "feat: cost-of-caution simulator on backtest page"
```

---

### Task 11: Regenerate data, full suite, end-to-end browser verification

**Files:**
- Regenerate: `site/data/backtest.json`, `site/data/indicators.json` (+ sibling exports)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Full test suite**

Run: `venv/bin/python -m pytest tests/ -q`
Expected: ALL PASS.

- [ ] **Step 2: Regenerate site data**

```bash
venv/bin/python -m pipeline export
venv/bin/python -m pipeline backtest
```

Expected: both exit 0. Then validate the new payload shape:

```bash
venv/bin/python - <<'EOF'
import json
bt = json.load(open("site/data/backtest.json"))
n = len(bt["months"])
for k in ("regime_bands", "fedfunds", "fwd_6m", "fwd_12m", "fwd_24m", "report_card", "alarms"):
    assert k in bt, k
for k in ("fedfunds", "fwd_6m", "fwd_12m", "fwd_24m"):
    assert len(bt[k]) == n, k
assert bt["fwd_24m"][-1] is None                      # tail horizon must be unknown
assert any(r["episode"] == "gfc" for r in bt["report_card"])
inds = json.load(open("site/data/indicators.json"))
assert all(v.get("blurb") for v in inds.values()), "every exported indicator has a blurb"
print("payload OK:", n, "months,", len(bt["alarms"]), "alarm runs")
EOF
```

Expected: `payload OK: ...` printed.

- [ ] **Step 3: Browser verification (use the `verify` skill / claude-in-chrome if available)**

Serve: `python3 -m http.server 8213 --directory site`

1. `index.html`: pick "Shiller CAPE" in the drill-down → definition paragraph appears; no console errors.
2. `guide.html`: section 11 shows concept terms and the per-pillar indicator glossary with all 28 entries.
3. `backtest.html`: all six cards render — report card table (GFC row shows a first-stage-4 date and a negative drawdown; dot-com row shows "never" + the data-gap note), replay chart, criteria list, two box-plot figures with n= labels, alarm ledger tables, simulator with working slider/select.
4. Simulator hand-check: set trigger "sequence stage ≥ 4", cash 100%. In the browser console run a spot check that a de-risked month grew at the cash rate:

```js
fetch("data/backtest.json").then(r => r.json()).then(bt => {
  const t = bt.stage.findIndex(s => s >= 4) + 1;   // first month POSITIONED after a stage>=4 signal
  console.log("expected monthly cash return:", bt.fedfunds[t - 1] / 100 / 12,
              "equity move that month:", bt.spx[t] / bt.spx[t - 1] - 1);
});
```

Confirm the stats table's de-risked CAGR is below buy-and-hold CAGR but with a smaller max drawdown (the expected honest lesson), and that numbers change when the slider moves. Kill the server.

- [ ] **Step 4: Commit regenerated data**

```bash
git add site/data/
git commit -m "chore: regenerate site data with blurbs and backtest upgrade payload"
```
