# Macro Monitor Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Role-aware composite + stress gauge, dashboard upgrades (pillar tabs, crisis markers), episode snapshot library, analog similarity with radar, sequencing state machine, margin-debt data, backtest validation page, and auto-generated narrative timelines — all live on the existing site.

**Architecture:** Extends the deployed Phase 1–2 system in place. New compute modules (`episodes.py`, `analogs.py`, `sequencer.py`, `backtest.py`) follow the existing pattern: pure functions over `pd.Series`/`DataFrame`, persisted as git-friendly CSV/JSON, exported to `site/data/*.json`, rendered by vanilla JS. The radar chart is hand-rolled SVG (no Plotly bundle change).

**Tech Stack:** unchanged — Python 3.12, pandas ≥2.2 (venv has 3.0.3), pytest; vanilla JS + vendored plotly-finance; GitHub Actions.

## Global Constraints

- Repo root: `/Users/jolee/Library/CloudStorage/Dropbox/CodingProjects/macro-monitoring`, branch `main` (project pattern: commit to main, push at task end unless a task says otherwise; every push must leave CI green).
- Use the project venv (`source venv/bin/activate` or `./venv/bin/python`); bare `python3` is a broken Xcode 3.9.
- Suite baseline: **60 passed**. Every task ends with the full suite green.
- Full-history window remains **canonical** for alerts, analogs, snapshots, sequencer; rolling20y is display-only.
- **Role-aware composite (design amendment 2026-07-06):** only `timing` and `magnitude` indicators feed pillar scores and the composite; `confirmation` indicators feed only the separate stress gauge. Regime bands unchanged pending backtest.
- Windows are named `"full"` and `"rolling20y"`; scores rounded 2dp in CSVs; JSON floats 4dp via `_r`; no wall-clock in export (deterministic; `as_of` = max raw obs date).
- Episode peaks (canonical, already in thresholds.yaml): 2000-03-24, 2007-10-09, 2020-02-19 (control), 2022-01-03.
- Commit messages: conventional prefix + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Network code: `timeout=30`; tests never hit the network; never print/persist the FRED key.

## File Map (Phase 3 delta)

| Path | Responsibility |
|---|---|
| `pipeline/compute/scores.py` (modify) | Role-aware pillars/composite + stress series |
| `pipeline/export.py` (modify) | stress + analogs + sequence in latest.json; stress in history.json; episodes.json; timeline injection into episode pages |
| `site/assets/app.js`, `style.css`, `index.html` (modify) | Tabs, stress readout, drill-down markers, analog card + SVG radar + comparison table, sequence tracker, backtest nav |
| `config/episodes.yaml` (create) | Episode ids/names/peaks/control + snapshot offsets |
| `pipeline/compute/episodes.py` (create) | Snapshot builder (percentile profiles at offsets) + timeline extraction |
| `pipeline/compute/analogs.py` (create) | Cosine similarity: today vs every episode snapshot |
| `pipeline/compute/sequencer.py` (create) | Stage triggers + state machine + persistence |
| `pipeline/backtest.py` (create) | Historical sequencer replay + §13 criteria + base rates |
| `site/backtest.html` (create) | Backtest page |
| `data/snapshots/episode_snapshots.csv` (generated, committed) | episode,offset_months,indicator_id,percentile |
| `data/scores/stress.csv` (generated, committed) | date,window,score |
| `data/state/sequence_state.json` (generated, committed) | Stage state machine persistence |
| `config/registry.yaml` (modify) | `manual` source support + margin-debt series/indicator (Task 5) |
| `config/thresholds.yaml` (modify) | stress_bands, sequencer stage triggers |

Existing interfaces consumed throughout (from Phase 1–2, all stable): `Registry/Indicator` dataclasses; `compute_scores(reg, thresholds, raw, now=None) -> ScoreResult`; `IndicatorResult(series, froth_full, froth_rolling, zscore_latest, frequency)`; `store.read_series/write_series`; `derived.asof_align`; `percentiles.froth/expanding_percentile`; `export._r/_series_json/_atomic_write/downsample`; `alerts.Alert/evaluate_alerts/deliver`; CLI subcommand registration pattern in `pipeline/cli.py::main`.

---

### Task 1: Role-aware composite + stress gauge (scores + export + data regeneration)

**Files:**
- Modify: `pipeline/compute/scores.py`, `pipeline/export.py`, `config/thresholds.yaml`
- Test: `tests/test_scores.py` (extend), `tests/test_export.py` (extend)

**Interfaces:**
- Consumes: existing `ScoreResult`, `compute_scores`, `append_scores`, `export_site`.
- Produces: `ScoreResult.stress: pd.DataFrame` (columns `date, window, score`); `append_scores` returns `(n_comp, n_pil, n_stress)` and writes `data/scores/stress.csv`; `latest.json` gains `"stress": {<window>: {"score": float, "label": str} | null}`; `history.json` windows gain `"stress": [...]` aligned to `dates`; `latest.json` pillar `partial` counts only non-confirmation indicators. Thresholds gain `stress_bands`.

- [ ] **Step 1: Add stress bands to `config/thresholds.yaml`** (append at end)

```yaml
stress_bands:   # confirmation-indicator gauge; ascending upper bounds
  - {name: quiet,      upper: 40}
  - {name: elevated,   upper: 70}
  - {name: confirming, upper: 100}
```

- [ ] **Step 2: Write the failing tests.** In `tests/test_scores.py`, change `make_reg()` and add tests. Replace the existing `make_reg` with:

```python
def make_reg(with_confirmation=False):
    series = [
        Series("up", "fred", "UP", "monthly", 45, 0, 1),
        Series("down", "fred", "DOWN", "monthly", 45, 0, 1),
        Series("young", "fred", "YOUNG", "monthly", 45, 0, 1),
    ]
    indicators = [
        Indicator("i_up", "Up", "valuation", "magnitude", "normal", 1, series="up"),
        Indicator("i_down", "Down", "leverage", "timing", "invert", 1, series="down"),
        Indicator("i_young", "Young", "sentiment", "timing", "normal", 1, series="young"),
    ]
    if with_confirmation:
        series.append(Series("conf", "fred", "CONF", "monthly", 45, 0, 1))
        indicators.append(
            Indicator("i_conf", "Conf", "valuation", "confirmation", "normal", 1, series="conf"))
    return Registry(series=series, indicators=indicators,
                    pillar_weights={"valuation": 0.5, "leverage": 0.3, "sentiment": 0.2})
```

Add to `make_raw` support for the confirmation series — replace `make_raw` with:

```python
def make_raw(with_confirmation=False):
    idx = pd.date_range("2000-01-31", "2012-12-31", freq="ME")
    up = pd.Series(np.arange(1.0, len(idx) + 1), index=idx)
    down = pd.Series(-np.arange(1.0, len(idx) + 1), index=idx)
    young = pd.Series([1.0, 2.0], index=pd.to_datetime(["2012-11-30", "2012-12-31"]))
    raw = {"up": up, "down": down, "young": young}
    if with_confirmation:
        raw["conf"] = pd.Series(np.arange(1.0, len(idx) + 1), index=idx)  # always at max -> froth 100
    return raw
```

Add two tests:

```python
def test_confirmation_excluded_from_composite_and_pillars():
    reg = make_reg(with_confirmation=True)
    res = scores.compute_scores(reg, TH, make_raw(with_confirmation=True))
    # i_conf froth is ~100 and sits in the valuation pillar; if it leaked in,
    # valuation would exceed the i_up-only value. It must equal the i_up-only pillar.
    res_no_conf = scores.compute_scores(make_reg(), TH, make_raw())
    last = lambda r, p: r.pillars[(r.pillars.window == "full") & (r.pillars.pillar == p)].iloc[-1]["score"]
    assert last(res, "valuation") == pytest.approx(last(res_no_conf, "valuation"))
    comp = lambda r: r.composite[r.composite.window == "full"].iloc[-1]["score"]
    assert comp(res) == pytest.approx(comp(res_no_conf))


def test_stress_series_from_confirmation_only():
    reg = make_reg(with_confirmation=True)
    res = scores.compute_scores(reg, TH, make_raw(with_confirmation=True))
    st = res.stress[res.stress.window == "full"]
    assert not st.empty
    assert st.iloc[-1]["score"] == pytest.approx(100.0, abs=0.5)  # single conf indicator at max
    # no confirmation indicators -> empty stress frame with the right columns
    res2 = scores.compute_scores(make_reg(), TH, make_raw())
    assert list(res2.stress.columns) == ["date", "window", "score"]
    assert res2.stress.empty
```

And extend `test_append_scores_is_append_only` — change the two unpack lines and assertions:

```python
    n1, _, s1 = scores.append_scores(res)
    assert n1 > 0
    n2, m2, s2 = scores.append_scores(res)
    assert n2 == 0 and m2 == 0 and s2 == 0
```

(construct `res` in that test with `make_reg(with_confirmation=True)` / `make_raw(with_confirmation=True)` so `stress.csv` is exercised; add `assert (tmp_path / "stress.csv").exists()`).

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_scores.py -q`
Expected: FAIL — `TypeError` (make_reg signature) then attribute/unpack errors.

- [ ] **Step 4: Implement in `pipeline/compute/scores.py`.** Three changes:

(a) `ScoreResult` gains stress:

```python
@dataclass
class ScoreResult:
    composite: pd.DataFrame
    pillars: pd.DataFrame
    indicators: dict[str, IndicatorResult]
    stress: pd.DataFrame
```

(b) In `compute_scores`, pillar membership excludes confirmation, and stress is computed per window. Replace the members list-comp inside the window loop with:

```python
            members = [
                froth_daily[i.id][window]
                for i in reg.indicators
                if i.pillar == pillar and i.id in froth_daily and i.role != "confirmation"
            ]
```

and after the pillar/composite loop body (still inside `for window in WINDOWS:` — collect rows into a `stress_rows` list initialized alongside `comp_rows`):

```python
        conf_members = [
            froth_daily[i.id][window]
            for i in reg.indicators
            if i.role == "confirmation" and i.id in froth_daily
        ]
        if conf_members:
            stress_series = pd.concat(conf_members, axis=1).mean(axis=1).dropna()
            for dt, val in stress_series.items():
                stress_rows.append({"date": dt, "window": window, "score": round(float(val), 2)})
```

and the return becomes:

```python
    return ScoreResult(
        composite=pd.DataFrame(comp_rows, columns=["date", "window", "score", "regime"]),
        pillars=pd.DataFrame(pillar_rows, columns=["date", "window", "pillar", "score"]),
        indicators=indicators,
        stress=pd.DataFrame(stress_rows, columns=["date", "window", "score"]),
    )
```

(c) `append_scores` writes stress and returns a triple:

```python
def append_scores(result: ScoreResult) -> tuple[int, int, int]:
    n_comp = _append(paths.DATA_SCORES / "composite.csv",
                     result.composite.sort_values(["date", "window"]))
    n_pil = _append(paths.DATA_SCORES / "pillars.csv",
                    result.pillars.sort_values(["date", "window", "pillar"]))
    n_stress = _append(paths.DATA_SCORES / "stress.csv",
                       result.stress.sort_values(["date", "window"]))
    return n_comp, n_pil, n_stress
```

Update the one caller in `pipeline/cli.py::cmd_run`:

```python
    n_comp, n_pil, n_stress = append_scores(result)
    ...
    print(f"scores: +{n_comp} composite rows, +{n_pil} pillar rows, +{n_stress} stress rows; "
          f"latest {latest['date']:%Y-%m-%d} composite={latest['score']} ({latest['regime']})")
```

- [ ] **Step 5: Export changes in `pipeline/export.py`.** Inside `export_site`:

(a) Pillar `partial` counts non-confirmation only — replace the two counting dicts:

```python
    per_pillar_total = {p: sum(1 for i in reg.indicators if i.pillar == p and i.role != "confirmation")
                        for p in reg.pillar_weights}
    per_pillar_active = {p: 0 for p in reg.pillar_weights}
    for ind in reg.indicators:
        r = result.indicators.get(ind.id)
        if ind.role != "confirmation" and r is not None and not r.froth_full.empty:
            per_pillar_active[ind.pillar] += 1
```

(b) After the `comp` dict is built, add stress to `latest`:

```python
    stress_bands = thresholds["stress_bands"]
    stress = {}
    for window in ("full", "rolling20y"):
        rows = result.stress[result.stress.window == window]
        if rows.empty:
            stress[window] = None
            continue
        val = float(rows.sort_values("date").iloc[-1]["score"])
        stress[window] = {"score": _r(val, 2), "label": regime_for(val, stress_bands)}
```

(import `regime_for` from `pipeline.compute.scores`), and add `"stress": stress,` to the `latest` dict.

(c) In the history block, alongside the pillar arrays add:

```python
        srows = result.stress[result.stress.window == window]
        if not srows.empty:
            saligned = srows.set_index("date")["score"].resample("W-FRI").last().reindex(weekly.index)
            history[window]["stress"] = [_r(v, 2) for v in saligned.to_numpy()]
```

(place after `history[window] = {...}` so the key exists to extend).

- [ ] **Step 6: Extend `tests/test_export.py`** — in `test_export_writes_three_files_with_contract`, using the confirmation-enabled fixtures (`make_reg(with_confirmation=True)`, seed raw including `conf`), add:

```python
    assert latest["stress"]["full"]["label"] in ("quiet", "elevated", "confirming")
    assert latest["stress"]["full"]["score"] == pytest.approx(100.0, abs=0.5)
    assert "stress" in history["full"]
```

Also add `stress_bands` to the `THX`/`TH` fixture dicts in `tests/test_scores.py`:

```python
TH = {..., "stress_bands": [{"name": "quiet", "upper": 40}, {"name": "elevated", "upper": 70},
                             {"name": "confirming", "upper": 100}]}
```

- [ ] **Step 7: Run tests**

Run: `pytest tests/test_scores.py tests/test_export.py -q && pytest -q`
Expected: all green (existing tests unaffected because the base fixtures contain no confirmation indicators; full suite 62–63 passed depending on added tests — report the exact number).

- [ ] **Step 8: Regenerate scores under the new methodology (live)**

```bash
rm data/scores/composite.csv data/scores/pillars.csv
./venv/bin/python -m pipeline run
./venv/bin/python -m pipeline export
```

Sanity before committing: print latest full composite (expect it to differ from 65.68 — the macro pillar now holds only breadth, so composite shifts), latest stress (expect a sane 0–100 value), and re-run the three plausibility epochs — **1999-12 and 2021-06 should still read elevated (≥70 ideally), and 2008-12 should now read LOWER than before (the whole point of the change)**. Print all six numbers in your report. If 2008-12 did not drop or the manias did not stay elevated, STOP and report BLOCKED with the numbers.

- [ ] **Step 9: Commit and push**

```bash
git add pipeline config tests data site/data
git commit -m "feat: role-aware composite — confirmation indicators feed a separate stress gauge

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push
```

Watch the push-path workflow green (`gh run watch --exit-status` on the newest run).

---

### Task 2: Dashboard — Score History tabs, stress readout, drill-down crisis markers

**Files:**
- Modify: `site/assets/app.js`, `site/assets/style.css`, `site/index.html`

**Interfaces:**
- Consumes: Task 1's `latest.json.stress` and `history.<window>.stress`; existing `HISTORY.episode_peaks`.
- Produces: UI only. No JSON contract changes.

- [ ] **Step 1: index.html** — inside the Score History card, replace the `card-head` block with:

```html
  <div class="card-head">
    <h2>Score history</h2>
    <label class="toggle"><input type="checkbox" id="window-toggle"> rolling 20y window</label>
  </div>
  <div class="tabs" id="history-tabs"></div>
```

and in the gauge card, after `<div id="regime-label"></div>` add:

```html
  <div id="stress-label" class="muted"></div>
```

- [ ] **Step 2: style.css** — append:

```css
.tabs { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px; }
.tabs button { background:var(--bg); color:var(--muted); border:1px solid var(--line);
               border-radius:15px; padding:3px 12px; font-size:.8rem; cursor:pointer; }
.tabs button.active { color:var(--text); border-color:var(--warm); }
```

- [ ] **Step 3: app.js.** Three changes.

(a) Add after the `PILLAR_LABEL` const:

```javascript
const HISTORY_TABS = [
  { key: "composite", label: "Composite" },
  { key: "valuation", label: "Valuation" },
  { key: "leverage", label: "Leverage" },
  { key: "liquidity", label: "Liquidity" },
  { key: "sentiment", label: "Sentiment" },
  { key: "macro", label: "Macro breadth" },
  { key: "stress", label: "Confirmation stress" },
];
let HTAB = "composite";
```

(b) In `boot()`, after `renderGauge(); renderPillars(); renderHistory(); initPicker();` add `initHistoryTabs(); renderStress();` and define:

```javascript
function initHistoryTabs() {
  const el = document.getElementById("history-tabs");
  for (const t of HISTORY_TABS) {
    const b = document.createElement("button");
    b.textContent = t.label;
    b.dataset.key = t.key;
    if (t.key === HTAB) b.classList.add("active");
    b.addEventListener("click", () => {
      HTAB = t.key;
      el.querySelectorAll("button").forEach(x => x.classList.toggle("active", x.dataset.key === HTAB));
      renderHistory();
    });
    el.appendChild(b);
  }
}

function renderStress() {
  const s = (LATEST.stress || {})[WIN] || (LATEST.stress || {}).full;
  const el = document.getElementById("stress-label");
  if (!s) { el.textContent = ""; return; }
  const color = s.label === "confirming" ? "#d64545" : s.label === "elevated" ? "#e0b83c" : "#4caf7d";
  el.innerHTML = `Confirmation stress: <span style="color:${color}">${s.score} (${s.label})</span>`;
}
```

Also call `renderStress()` inside the window-toggle change handler (alongside the existing three renders).

(c) Replace `renderHistory()` with a tab-aware version, and add markers to `renderIndicator`:

```javascript
function episodeShapes() {
  return HISTORY.episode_peaks.map(d => ({
    type: "line", x0: d, x1: d, y0: 0, y1: 1, yref: "paper",
    line: { color: "#d64545", width: 1, dash: "dot" } }));
}

function renderHistory() {
  const h = HISTORY[WIN];
  if (!h) return;
  const traces = [];
  if (HTAB === "composite") {
    traces.push({ x: h.dates, y: h.composite, name: "Composite",
                  line: { color: "#e6e9ef", width: 2.4 } });
    for (const [p, vals] of Object.entries(h.pillars))
      traces.push({ x: h.dates, y: vals, name: PILLAR_LABEL[p],
                    line: { width: 1 }, opacity: 0.55, visible: "legendonly" });
    if (h.stress) traces.push({ x: h.dates, y: h.stress, name: "Confirmation stress",
                                line: { width: 1, dash: "dot" }, opacity: 0.5, visible: "legendonly" });
  } else if (HTAB === "stress") {
    if (h.stress) traces.push({ x: h.dates, y: h.stress, name: "Confirmation stress",
                                line: { color: "#e07b3c", width: 2.2 } });
    traces.push({ x: h.dates, y: h.composite, name: "Composite (ref)",
                  line: { color: "#8b93a3", width: 1, dash: "dash" }, opacity: 0.6 });
  } else {
    const vals = h.pillars[HTAB];
    if (vals) traces.push({ x: h.dates, y: vals, name: PILLAR_LABEL[HTAB],
                            line: { color: "#6ea8fe", width: 2.2 } });
    traces.push({ x: h.dates, y: h.composite, name: "Composite (ref)",
                  line: { color: "#8b93a3", width: 1, dash: "dash" }, opacity: 0.6 });
  }
  const shapes = episodeShapes().map(s => ({ ...s, y0: 0, y1: 100, yref: "y" }));
  const bands = [[0,40,"rgba(76,175,125,.05)"],[40,70,"rgba(224,184,60,.05)"],
                 [70,85,"rgba(224,123,60,.06)"],[85,100,"rgba(214,69,69,.08)"]];
  for (const [y0,y1,c] of bands)
    shapes.push({ type:"rect", xref:"paper", x0:0, x1:1, y0, y1, fillcolor:c, line:{width:0} });
  Plotly.newPlot("history", traces,
    { ...PLOT_BASE, height: 340, shapes, yaxis: { range: [0, 100] },
      legend: { orientation: "h", y: -0.15 } }, CFG);
}
```

In `renderIndicator(id)`, add `shapes: episodeShapes()` to the raw chart's layout and merge the peak shapes into the pct chart's existing threshold-line shapes:

```javascript
  Plotly.newPlot("indicator-raw",
    [{ x: d.series.dates, y: d.series.values, name: "raw", line: { color: "#6ea8fe", width: 1.4 } }],
    { ...PLOT_BASE, height: 230, shapes: episodeShapes(),
      yaxis: { title: { text: "raw value", font: { size: 11 } } } }, CFG);
  Plotly.newPlot("indicator-pct",
    [{ x: d.pct_series.dates, y: d.pct_series.values, name: "froth pct", line: { color: "#e0b83c", width: 1.4 } }],
    { ...PLOT_BASE, height: 200, yaxis: { range: [0, 100] },
      shapes: [
        ...[80, 90].map(y => ({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y,
                                line: { color: "#d64545", width: 1, dash: "dot" } })),
        ...episodeShapes().map(s => ({ ...s, y0: 0, y1: 100, yref: "y" })),
      ] }, CFG);
```

- [ ] **Step 4: Verify in a real browser** — `python -m http.server 8123 -d site`, load with Playwright (as Task 10 Phase 1-2 did): click each of the 7 tabs and confirm the chart re-renders without console errors; confirm the stress readout shows under the gauge; select an indicator with pre-2000 history (e.g. the Buffett indicator) and confirm 4 red dotted vertical lines appear on both drill-down charts. Kill server, clean any `.playwright-mcp/` artifacts.

- [ ] **Step 5: Commit and push; watch workflow green**

```bash
git add site
git commit -m "feat: score-history pillar/stress tabs, stress readout, crisis markers on drill-down

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push
```

---

### Task 3: Episode snapshot library

**Files:**
- Create: `config/episodes.yaml`, `pipeline/compute/episodes.py`, `tests/test_episodes_lib.py`
- Modify: `pipeline/cli.py` (add `rebuild-episodes`), `pipeline/export.py` (episodes.json), `pipeline/registry.py` (loader)

**Interfaces:**
- Consumes: `compute_scores(...).indicators[id].froth_full` (native-frequency, direction-adjusted, gated percentile series).
- Produces:
  - `registry.load_episodes() -> dict` (raw YAML: `episodes: list[{id,name,peak,control?}]`, `offsets_months: list[int]`)
  - `episodes.build_snapshots(reg, thresholds, raw, epi_cfg) -> pd.DataFrame` columns `episode, offset_months, indicator_id, percentile` — percentile = `froth_full.asof(peak + DateOffset(months=offset))`, row omitted when NaN/unavailable (exclusion, never zero-fill)
  - `episodes.pillar_scores_from_snapshots(reg, snaps) -> pd.DataFrame` columns `episode, offset_months, pillar, score` — mean of available non-confirmation indicators per pillar (reweighting by omission)
  - `episodes.firing_timeline(snaps, level=80) -> pd.DataFrame` columns `episode, indicator_id, first_offset` — earliest offset where percentile ≥ level (NaN row omitted)
  - CSV persisted at `data/snapshots/episode_snapshots.csv`; `site/data/episodes.json` per the contract in Step 6.

- [ ] **Step 1: Write `config/episodes.yaml`**

```yaml
episodes:
  - {id: dotcom,    name: "Dot-com bust",            peak: "2000-03-24"}
  - {id: gfc,       name: "Global Financial Crisis", peak: "2007-10-09"}
  - {id: covid,     name: "COVID crash",             peak: "2020-02-19", control: true}
  - {id: postcovid, name: "Post-COVID unwind",       peak: "2022-01-03"}
offsets_months: [-24, -18, -12, -9, -6, -3, -1, 0, 6, 12]
```

- [ ] **Step 2: Loader in `pipeline/registry.py`** — add:

```python
def load_episodes(path: Path | None = None) -> dict:
    return yaml.safe_load((path or paths.CONFIG / "episodes.yaml").read_text())
```

(add `from pipeline import paths` import if not present — it is not currently; use the same pattern as `load_registry`.)

- [ ] **Step 3: Write the failing tests** — `tests/test_episodes_lib.py`:

```python
import pandas as pd
import pytest

from pipeline.compute import episodes as epi
from tests.test_scores import TH, make_raw, make_reg

EPI_CFG = {
    "episodes": [
        {"id": "boom", "name": "Boom", "peak": "2011-06-30"},
        {"id": "early", "name": "Too early", "peak": "2001-06-30"},
    ],
    "offsets_months": [-12, -1, 0],
}


def test_build_snapshots_asof_and_exclusion():
    reg = make_reg()
    snaps = epi.build_snapshots(reg, TH, make_raw(), EPI_CFG)
    assert set(snaps.columns) == {"episode", "offset_months", "indicator_id", "percentile"}
    boom = snaps[snaps.episode == "boom"]
    # monotone-up series: percentile ~100 at every offset once qualified (10y gate passes mid-2010)
    row = boom[(boom.offset_months == 0) & (boom.indicator_id == "i_up")]
    assert row.iloc[0]["percentile"] == pytest.approx(100.0, abs=0.5)
    # i_young has <10y history: excluded everywhere, never zero-filled
    assert boom[boom.indicator_id == "i_young"].empty
    # 'early' episode predates qualification (gate passes 2010): no rows at all
    assert snaps[snaps.episode == "early"].empty


def test_pillar_scores_reweighted():
    reg = make_reg()
    snaps = epi.build_snapshots(reg, TH, make_raw(), EPI_CFG)
    ps = epi.pillar_scores_from_snapshots(reg, snaps)
    boom0 = ps[(ps.episode == "boom") & (ps.offset_months == 0)]
    assert set(boom0.pillar) == {"valuation", "leverage"}  # sentiment excluded (i_young gated)
    val = boom0[boom0.pillar == "valuation"].iloc[0]["score"]
    assert val == pytest.approx(100.0, abs=0.5)


def test_firing_timeline_first_crossing():
    snaps = pd.DataFrame([
        {"episode": "e", "offset_months": -12, "indicator_id": "a", "percentile": 70.0},
        {"episode": "e", "offset_months": -1, "indicator_id": "a", "percentile": 85.0},
        {"episode": "e", "offset_months": 0, "indicator_id": "a", "percentile": 95.0},
        {"episode": "e", "offset_months": -12, "indicator_id": "b", "percentile": 10.0},
    ])
    tl = epi.firing_timeline(snaps, level=80)
    assert tl[(tl.indicator_id == "a")].iloc[0]["first_offset"] == -1
    assert tl[tl.indicator_id == "b"].empty
```

- [ ] **Step 4: Run to verify fail**, then **implement `pipeline/compute/episodes.py`:**

```python
from __future__ import annotations

import pandas as pd

from pipeline import paths
from pipeline.compute.scores import compute_scores
from pipeline.registry import Registry


def build_snapshots(reg: Registry, thresholds: dict, raw: dict, epi_cfg: dict) -> pd.DataFrame:
    result = compute_scores(reg, thresholds, raw)
    rows = []
    for ep in epi_cfg["episodes"]:
        peak = pd.Timestamp(ep["peak"])
        for off in epi_cfg["offsets_months"]:
            snap_date = peak + pd.DateOffset(months=off)
            for ind_id, ir in result.indicators.items():
                if ir.froth_full.empty:
                    continue
                val = ir.froth_full.asof(snap_date)
                if pd.isna(val):
                    continue  # exclusion, never zero-fill
                rows.append({"episode": ep["id"], "offset_months": off,
                             "indicator_id": ind_id, "percentile": round(float(val), 2)})
    return pd.DataFrame(rows, columns=["episode", "offset_months", "indicator_id", "percentile"])


def pillar_scores_from_snapshots(reg: Registry, snaps: pd.DataFrame) -> pd.DataFrame:
    roles = {i.id: i.role for i in reg.indicators}
    pillars = {i.id: i.pillar for i in reg.indicators}
    df = snaps[snaps.indicator_id.map(roles).ne("confirmation")].copy()
    df["pillar"] = df.indicator_id.map(pillars)
    out = (df.groupby(["episode", "offset_months", "pillar"])["percentile"]
             .mean().round(2).reset_index().rename(columns={"percentile": "score"}))
    return out


def firing_timeline(snaps: pd.DataFrame, level: float = 80) -> pd.DataFrame:
    hot = snaps[snaps.percentile >= level]
    out = (hot.groupby(["episode", "indicator_id"])["offset_months"]
              .min().reset_index().rename(columns={"offset_months": "first_offset"}))
    return out


def save_snapshots(snaps: pd.DataFrame) -> None:
    fp = paths.DATA / "snapshots" / "episode_snapshots.csv"
    fp.parent.mkdir(parents=True, exist_ok=True)
    snaps.to_csv(fp, index=False)


def load_snapshots() -> pd.DataFrame:
    fp = paths.DATA / "snapshots" / "episode_snapshots.csv"
    if not fp.exists():
        return pd.DataFrame(columns=["episode", "offset_months", "indicator_id", "percentile"])
    return pd.read_csv(fp)
```

- [ ] **Step 5: CLI** — in `pipeline/cli.py` add:

```python
def cmd_rebuild_episodes(args: argparse.Namespace) -> int:
    from pipeline import store
    from pipeline.compute.episodes import build_snapshots, save_snapshots
    from pipeline.registry import load_episodes, load_thresholds

    reg = load_registry()
    raw = {s.id: store.read_series(s.id) for s in reg.series}
    snaps = build_snapshots(reg, load_thresholds(), raw, load_episodes())
    save_snapshots(snaps)
    print(f"episodes: {snaps.episode.nunique()} episodes, {len(snaps)} snapshot rows")
    return 0
```

register: `sub.add_parser("rebuild-episodes").set_defaults(fn=cmd_rebuild_episodes)`.

- [ ] **Step 6: episodes.json in `pipeline/export.py`.** Add to `export_site` (before the final `_atomic_write` calls):

```python
    # ---- episodes.json ----
    from pipeline.compute.episodes import firing_timeline, load_snapshots, pillar_scores_from_snapshots
    from pipeline.registry import load_episodes

    epi_cfg = load_episodes()
    snaps = load_snapshots()
    episodes_payload: dict = {
        "episodes": epi_cfg["episodes"],
        "offsets": epi_cfg["offsets_months"],
        "snapshots": {}, "pillar_scores": {}, "timeline80": {}, "timeline90": {},
    }
    if not snaps.empty:
        for ep_id, grp in snaps.groupby("episode"):
            episodes_payload["snapshots"][ep_id] = {
                str(off): dict(zip(g.indicator_id, g.percentile))
                for off, g in grp.groupby("offset_months")
            }
        ps = pillar_scores_from_snapshots(reg, snaps)
        for ep_id, grp in ps.groupby("episode"):
            episodes_payload["pillar_scores"][ep_id] = {
                str(off): dict(zip(g.pillar, g.score))
                for off, g in grp.groupby("offset_months")
            }
        for level, key in ((80, "timeline80"), (90, "timeline90")):
            tl = firing_timeline(snaps, level)
            for ep_id, grp in tl.groupby("episode"):
                episodes_payload[key][ep_id] = dict(zip(grp.indicator_id, grp.first_offset.astype(int)))
    _atomic_write(paths.SITE_DATA / "episodes.json", episodes_payload)
```

Add a test in `tests/test_export.py`:

```python
def test_export_writes_episodes_json(site, monkeypatch, tmp_path):
    import pipeline.compute.episodes as epimod
    monkeypatch.setattr(epimod, "load_snapshots", lambda: pd.DataFrame(
        [{"episode": "gfc", "offset_months": -6, "indicator_id": "i_up", "percentile": 91.0}]))
    export.export_site(make_reg(), THX)
    epi = json.loads((site / "episodes.json").read_text())
    assert epi["snapshots"]["gfc"]["-6"]["i_up"] == 91.0
    assert epi["timeline90"]["gfc"]["i_up"] == -6
```

(note: `export.py` imports `load_snapshots` inside the function from `pipeline.compute.episodes`; monkeypatching the module attribute works because the import re-resolves it at call time via the module namespace — verify, and if the local import binds early, monkeypatch `pipeline.compute.episodes.load_snapshots` BEFORE calling export as shown, which is exactly what the local import will pick up.)

- [ ] **Step 7: Run tests, then live rebuild**

```bash
pytest -q                       # expect all green (report count)
./venv/bin/python -m pipeline rebuild-episodes
./venv/bin/python -m pipeline export
```

Sanity: print snapshot counts per episode (dotcom will have the fewest indicators — many series lack 10y-qualified history by 1998–2000; expect ≥6 rows per offset for dotcom, more for later episodes; if dotcom has <5 qualified indicators at T−12, note it in the report but proceed — exclusion is by design). Spot-check: gfc @ T−6 should show elevated leverage-pillar percentiles (household_debt_gdp near 100).

- [ ] **Step 8: Commit and push (code + data/snapshots + site/data), watch green.** Message: `feat: episode snapshot library with reweighted pillar profiles and firing timelines`.

---

### Task 4: Analog similarity + radar + comparison table

**Files:**
- Create: `pipeline/compute/analogs.py`, `tests/test_analogs.py`
- Modify: `pipeline/export.py` (latest.json analogs), `site/assets/app.js`, `site/index.html`, `site/assets/style.css`

**Interfaces:**
- Consumes: `episodes.load_snapshots()`; `ScoreResult.indicators` (today's froth_full latest values).
- Produces:
  - `analogs.cosine(a: dict[str, float], b: dict[str, float], min_shared: int = 8) -> float | None` — cosine similarity over shared keys, None if fewer than `min_shared`
  - `analogs.top_analogs(today: dict[str, float], snaps: pd.DataFrame, k: int = 3) -> list[dict]` — `[{episode, offset_months, similarity, n_shared}]` sorted desc, pre-peak offsets only (`offset_months <= 0`)
  - `latest.json.analogs` becomes `{"top": [{episode, name, offset_months, similarity, n_shared}], "today_vector_size": int} | null`
  - UI: analog card shows top-3 + SVG radar (today vs selected analog) + per-indicator table (today vs episode@selected offset), deep link to `episodes/<id>.html`.

- [ ] **Step 1: Failing tests** — `tests/test_analogs.py`:

```python
import pandas as pd
import pytest

from pipeline.compute import analogs


def test_cosine_identical_and_orthogonalish():
    a = {"x": 90.0, "y": 10.0, "z": 50.0, "w": 30.0, "v": 70.0, "u": 20.0, "t": 60.0, "s": 40.0}
    assert analogs.cosine(a, dict(a)) == pytest.approx(1.0)
    b = {k: 100.0 - v for k, v in a.items()}
    assert analogs.cosine(a, b) < analogs.cosine(a, dict(a))


def test_cosine_min_shared():
    a = {"x": 1.0, "y": 2.0}
    assert analogs.cosine(a, a, min_shared=8) is None
    assert analogs.cosine(a, a, min_shared=2) == pytest.approx(1.0)


def test_top_analogs_prepeak_only_and_sorted():
    keys = [f"k{i}" for i in range(8)]
    today = {k: 80.0 for k in keys}
    rows = []
    for off, scale in ((-6, 80.0), (6, 80.0), (-12, 20.0)):
        for k in keys:
            rows.append({"episode": "gfc", "offset_months": off, "indicator_id": k, "percentile": scale})
    snaps = pd.DataFrame(rows)
    top = analogs.top_analogs(today, snaps, k=3)
    assert all(t["offset_months"] <= 0 for t in top)           # +6 excluded
    assert top[0]["offset_months"] == -6                        # exact match ranks first
    assert top[0]["similarity"] == pytest.approx(1.0)
    assert top[0]["n_shared"] == 8
```

- [ ] **Step 2: Implement `pipeline/compute/analogs.py`:**

```python
from __future__ import annotations

import math

import pandas as pd


def cosine(a: dict[str, float], b: dict[str, float], min_shared: int = 8) -> float | None:
    shared = sorted(set(a) & set(b))
    if len(shared) < min_shared:
        return None
    va = [a[k] for k in shared]
    vb = [b[k] for k in shared]
    dot = sum(x * y for x, y in zip(va, vb))
    na = math.sqrt(sum(x * x for x in va))
    nb = math.sqrt(sum(y * y for y in vb))
    if na == 0 or nb == 0:
        return None
    return dot / (na * nb)


def top_analogs(today: dict[str, float], snaps: pd.DataFrame, k: int = 3) -> list[dict]:
    out = []
    pre = snaps[snaps.offset_months <= 0]
    for (ep, off), grp in pre.groupby(["episode", "offset_months"]):
        vec = dict(zip(grp.indicator_id, grp.percentile))
        sim = cosine(today, vec)
        if sim is None:
            continue
        out.append({"episode": ep, "offset_months": int(off),
                    "similarity": round(sim, 4), "n_shared": len(set(today) & set(vec))})
    return sorted(out, key=lambda d: -d["similarity"])[:k]
```

- [ ] **Step 3: Export wiring** — in `export_site`, replace `"analogs": None,` with a computed block (placed before building `latest`):

```python
    from pipeline.compute.analogs import top_analogs

    today_vec = {
        ind_id: float(r.froth_full.iloc[-1])
        for ind_id, r in result.indicators.items() if not r.froth_full.empty
    }
    analog_top = top_analogs(today_vec, snaps) if not snaps.empty else []
    ep_names = {e["id"]: e["name"] for e in epi_cfg["episodes"]}
    analogs_payload = None
    if analog_top:
        analogs_payload = {
            "top": [{**t, "name": ep_names.get(t["episode"], t["episode"])} for t in analog_top],
            "today_vector_size": len(today_vec),
        }
```

(Reorder: the episodes.json block from Task 3 must run before `latest` is assembled so `snaps`/`epi_cfg` exist; move both computations above the `latest = {...}` construction and use `"analogs": analogs_payload,` in it.) Add a test to `tests/test_export.py`:

```python
def test_export_analogs_in_latest(site, monkeypatch):
    import pipeline.compute.episodes as epimod
    rows = [{"episode": "gfc", "offset_months": -6, "indicator_id": f"k{i}", "percentile": 50.0}
            for i in range(8)]
    rows += [{"episode": "gfc", "offset_months": -6, "indicator_id": "i_up", "percentile": 100.0},
             {"episode": "gfc", "offset_months": -6, "indicator_id": "i_down", "percentile": 99.0}]
    monkeypatch.setattr(epimod, "load_snapshots", lambda: pd.DataFrame(rows))
    payload = export.export_site(make_reg(), THX)
    # today's vector only has i_up/i_down (+gated i_young absent) => shared=2 < 8 -> no analogs
    assert payload["analogs"] is None
```

and a positive-path variant where the snapshot rows use the fixture's real indicator ids padded by lowering min_shared — simplest: also assert in the same test that `top_analogs` with `min_shared` default correctly returns [] for tiny vectors (already covered in unit tests; the export-level negative test suffices here).

- [ ] **Step 4: UI.** In `site/index.html` replace the analog placeholder card body:

```html
  <div class="card" id="analog-card">
    <h3>Closest crisis analog</h3>
    <div id="analog-list" class="muted">No analog data yet.</div>
    <svg id="radar" viewBox="0 0 300 260" style="width:100%;max-width:340px;display:block;margin:8px auto"></svg>
    <div id="analog-table"></div>
  </div>
```

In `style.css` append:

```css
#analog-list .analog-row { cursor:pointer; padding:3px 6px; border-radius:6px; }
#analog-list .analog-row.sel { background:var(--bg); color:var(--text); }
#analog-table table { width:100%; font-size:.78rem; border-collapse:collapse; margin-top:8px; }
#analog-table td, #analog-table th { padding:2px 6px; border-bottom:1px solid var(--line); text-align:right; }
#analog-table td:first-child, #analog-table th:first-child { text-align:left; }
```

In `app.js`: load `episodes.json` in `boot()` (`EPISODES` global, add to the Promise.all list reading `data/episodes.json`), then add:

```javascript
let SEL_ANALOG = 0;

function renderAnalogs() {
  const a = LATEST.analogs;
  const list = document.getElementById("analog-list");
  if (!a || !a.top.length) { list.textContent = "No analog data yet."; return; }
  list.innerHTML = a.top.map((t, i) =>
    `<div class="analog-row ${i === SEL_ANALOG ? "sel" : ""}" data-i="${i}">` +
    `${i + 1}. <a href="episodes/${t.episode}.html">${t.name}</a> at T${t.offset_months >= 0 ? "+" : ""}${t.offset_months}m ` +
    `— similarity ${(t.similarity * 100).toFixed(0)}% <span class="muted">(${t.n_shared} shared)</span></div>`).join("");
  list.querySelectorAll(".analog-row").forEach(row =>
    row.addEventListener("click", e => {
      if (e.target.tagName === "A") return;
      SEL_ANALOG = +row.dataset.i;
      renderAnalogs(); renderRadar(); renderAnalogTable();
    }));
}

function radarPoints(scores, cx, cy, rmax) {
  const axes = ["valuation", "leverage", "liquidity", "sentiment", "macro"];
  return axes.map((p, i) => {
    const v = (scores[p] ?? 0) / 100;
    const ang = -Math.PI / 2 + (i * 2 * Math.PI) / axes.length;
    return [cx + rmax * v * Math.cos(ang), cy + rmax * v * Math.sin(ang)];
  });
}

function renderRadar() {
  const svg = document.getElementById("radar");
  const a = LATEST.analogs;
  svg.innerHTML = "";
  if (!a || !a.top.length) return;
  const t = a.top[SEL_ANALOG];
  const ep = (EPISODES.pillar_scores[t.episode] || {})[String(t.offset_months)] || {};
  const today = {};
  for (const [p, d] of Object.entries(LATEST.pillars)) today[p] = d.full ?? 0;
  const cx = 150, cy = 135, rmax = 100;
  const axes = ["valuation", "leverage", "liquidity", "sentiment", "macro"];
  let grid = "";
  for (const frac of [0.25, 0.5, 0.75, 1]) {
    const ring = radarPoints(Object.fromEntries(axes.map(p => [p, frac * 100])), cx, cy, rmax);
    grid += `<polygon points="${ring.map(p => p.join(",")).join(" ")}" fill="none" stroke="#2a3140" stroke-width="1"/>`;
  }
  const labels = axes.map((p, i) => {
    const ang = -Math.PI / 2 + (i * 2 * Math.PI) / axes.length;
    const x = cx + (rmax + 16) * Math.cos(ang), y = cy + (rmax + 16) * Math.sin(ang);
    return `<text x="${x}" y="${y}" fill="#8b93a3" font-size="10" text-anchor="middle">${PILLAR_LABEL[p].split(" ")[0]}</text>`;
  }).join("");
  const poly = (scores, color, fillOp) => {
    const pts = radarPoints(scores, cx, cy, rmax).map(p => p.join(",")).join(" ");
    return `<polygon points="${pts}" fill="${color}" fill-opacity="${fillOp}" stroke="${color}" stroke-width="1.6"/>`;
  };
  svg.innerHTML = grid + labels + poly(ep, "#d64545", 0.18) + poly(today, "#6ea8fe", 0.25) +
    `<text x="8" y="14" fill="#6ea8fe" font-size="10">today</text>` +
    `<text x="8" y="28" fill="#d64545" font-size="10">${t.episode} T${t.offset_months}m</text>`;
}

function renderAnalogTable() {
  const el = document.getElementById("analog-table");
  const a = LATEST.analogs;
  if (!a || !a.top.length) { el.innerHTML = ""; return; }
  const t = a.top[SEL_ANALOG];
  const snap = (EPISODES.snapshots[t.episode] || {})[String(t.offset_months)] || {};
  const rows = Object.keys(snap).filter(id => INDICATORS[id])
    .sort((x, y) => (snap[y] - (INDICATORS[y].latest.pct_full ?? 0)) - (snap[x] - (INDICATORS[x].latest.pct_full ?? 0)))
    .map(id => `<tr><td>${INDICATORS[id].name}</td>` +
      `<td>${INDICATORS[id].latest.pct_full ?? "–"}</td><td>${snap[id]}</td></tr>`).join("");
  el.innerHTML = `<table><tr><th>Indicator</th><th>today pct</th><th>${t.episode} T${t.offset_months}m</th></tr>${rows}</table>`;
}
```

Call `renderAnalogs(); renderRadar(); renderAnalogTable();` in `boot()`. Remove the `placeholder` class from the analog card.

- [ ] **Step 5: Tests + live verify + browser check** — `pytest -q` green; `pipeline export`; Playwright: analog card shows top-3, radar draws two polygons, clicking the 2nd analog re-renders, table sorts by gap. Commit (`feat: analog similarity with SVG radar and comparison table`), push, watch green.

---

### Task 5: Margin debt (best-effort acquisition + manual-source support)

**Files:**
- Modify: `pipeline/registry.py` (allow `manual` source), `pipeline/ingest/__init__.py` (skip manual), `config/registry.yaml`
- Test: `tests/test_ingest.py` (extend), `tests/test_registry.py` (counts)

**Interfaces:**
- Produces: registry supports `source: manual` — `run_ingest` skips fetch, records freshness from the stored CSV (fetch_ok true, "manual source"); series `margin_debt` (monthly, staleness budget 36500 for now — manual data doesn't rot on a schedule we control) + indicator `margin_debt_yoy` (leverage, timing, normal, `formula: yoy, inputs: [margin_debt]`). The sequencer (Task 6) reads `margin_debt_yoy` froth if present.

**Reality note for the implementer:** FINRA's site sits behind Akamai and its data API needs registration; the deep history (NYSE 1959→2010 + FINRA 2010→) is not reliably fetchable headlessly. This task therefore: (a) builds the `manual` plumbing and registers the series; (b) ATTEMPTS acquisition from FINRA's public endpoints with browser-like headers (10-minute timebox); (c) if blocked, writes an EMPTY-safe state — `data/raw/margin_debt.csv` absent is fine; the yoy indicator simply never qualifies, exports omit it, the sequencer reports stage 2 `no_data`, and the controller/user is told exactly what manual file to drop in (`data/raw/margin_debt.csv`, columns `date,value`, monthly, values in $ millions). Do NOT fabricate or approximate data.

- [ ] **Step 1: Failing tests.** `tests/test_registry.py`: series count 24 → 25, and source enum accepts `manual` (extend `test_enums_valid` expectation set). `tests/test_ingest.py` add:

```python
def test_manual_source_skipped_and_fresh_from_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(store.paths, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path / "state")
    reg = Registry(
        series=[Series("man", "manual", "-", "monthly", 36500, 0, 25)],
        indicators=[], pillar_weights={"valuation": 1.0})
    store.write_series("man", pd.Series([1.0], index=pd.to_datetime(["2026-06-01"]), name="man"))
    fresh = ingest.run_ingest(reg, api_key="K", now=pd.Timestamp("2026-07-06"))
    assert fresh["man"]["fetch_ok"] is True
    assert fresh["man"]["last_obs"] == "2026-06-01"
    assert fresh["man"]["error"] is None
```

- [ ] **Step 2: Implement.** `pipeline/registry.py`: `VALID_SOURCES = ("fred", "yahoo", "manual")`. `pipeline/ingest/__init__.py` — at the top of the per-series loop:

```python
        if s.source == "manual":
            stored = store.read_series(s.id)
            fresh[s.id] = {
                "last_fetch": stamp, "fetch_ok": True,
                "last_obs": stored.index.max().strftime("%Y-%m-%d") if not stored.empty else None,
                "error": None,
            }
            continue
```

`config/registry.yaml` — add series + indicator:

```yaml
  # ---- Manual (see docs: FINRA/NYSE margin debt; drop data/raw/margin_debt.csv, date,value in $mn) ----
  - {id: margin_debt, source: manual, source_id: "-", frequency: monthly, staleness_budget_days: 36500, revision_window_days: 0, lag_days: 25}
```

```yaml
  - {id: margin_debt_yoy, name: "FINRA margin debt YoY %", pillar: leverage, role: timing, direction: normal,
     formula: yoy, inputs: [margin_debt], lag_days: 25}
```

(indicator count 18 → 19; update `tests/test_registry.py` count assertion.)

- [ ] **Step 3: Timeboxed acquisition attempt.** Try, in order, printing status for the report: (a) `https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx` style file URLs found from `https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics` (fetch the page with browser UA, look for xlsx/csv links); (b) FINRA query API `https://api.finra.org/data/group/otcMarket/name/marginDebt` (may 403 without key). If any yields monthly margin-debt data: parse to `date,value` ($mn), write via `store.write_series("margin_debt", s)`, note provenance in the report. If all blocked within the timebox: leave no CSV, and state clearly in your final message that margin data is pending manual/controller acquisition.

- [ ] **Step 4: Suite green (`pytest -q` — expect prior count +1), `pipeline run` (manual series must not break ingest; status shows margin_debt ok-or-absent), commit and push:** `feat: manual-source support + margin-debt series (data pending acquisition)`.

---

### Task 6: Sequencing state machine

**Files:**
- Create: `pipeline/compute/sequencer.py`, `tests/test_sequencer.py`
- Modify: `config/thresholds.yaml`, `pipeline/cli.py` (run wiring), `pipeline/export.py` (sequence in latest.json), `pipeline/alerts.py` (stage alerts), `site/assets/app.js` + `index.html` (tracker UI)

**Interfaces:**
- Consumes: raw series (`spx`, `t10y3m`, `baa10y`, `sahmrealtime`, `vixcls`), indicator froth series (`margin_debt_yoy` via `ScoreResult.indicators`), pillar scores (valuation, full window).
- Produces:
  - thresholds.yaml `sequencer:` block (below)
  - `sequencer.evaluate_stages(reg, thresholds, raw, result, asof) -> dict[int, bool | None]` — None = no data for that stage
  - `sequencer.update_state(prev: dict, fired: dict[int, bool | None], asof: pd.Timestamp, spx: pd.Series, cfg: dict) -> dict` — persistable state (schema below)
  - state JSON at `data/state/sequence_state.json`:
    ```
    {"as_of": "YYYY-MM-DD", "engaged": bool, "current_stage": int|0,
     "stages": {"1": {"fired": bool|null, "fired_date": str|null, "lapsed": bool, "last_true": str|null}, ... "6": {...}}}
    ```
  - `latest.json.sequence` = that state verbatim
  - alerts: newly fired stage n → `Alert(f"alert:stage-{n}", ...)`
  - UI: tracker pipeline replacing the placeholder card.

- [ ] **Step 1: thresholds.yaml sequencer block** (append; initial values from design §8b, stage 4 amended to Baa +60bp because HY OAS lacks deep history — record this in the design doc per Step 7):

```yaml
sequencer:
  engaged_min_stages: 2        # of stages 1-3 fired (not lapsed)
  lapse_days: 92               # stage un-fires after condition false this long
  reset_drawdown_pct: 20       # index falls 20% below its post-engagement high -> reset to not engaged
  stages:
    "1": {rule: pillar_above, pillar: valuation, level: 80, min_days: 126}
    "2": {rule: froth_rollover, indicator: margin_debt_yoy, level: 85, lookback_days: 365, decline_obs: 2}
    "3": {rule: curve_resteepen, series: t10y3m, lookback_days: 548, min_inverted_days: 21, resteepen_level: 0.25}
    "4": {rule: spread_widening, series: baa10y, low_lookback_days: 365, widen: 0.60}
    "5": {rule: breadth_divergence, index: spx, breadth: rsp_spy_breadth, near_high_pct: 2.0, high_lookback_days: 365, breadth_low_days: 126}
    "6": {rule: price_confirmation, index: spx, dma_days: 200, sahm_series: sahmrealtime, sahm_level: 0.5, vix_series: vixcls, vix_level: 30}
```

- [ ] **Step 2: Failing tests** — `tests/test_sequencer.py` (synthetic series shaped per stage; all evaluated at a fixed `asof`):

```python
import json

import numpy as np
import pandas as pd
import pytest

from pipeline.compute import sequencer as seq

ASOF = pd.Timestamp("2026-07-01")
CFG = {
    "engaged_min_stages": 2, "lapse_days": 92, "reset_drawdown_pct": 20,
    "stages": {
        "3": {"rule": "curve_resteepen", "series": "t10y3m", "lookback_days": 548,
               "min_inverted_days": 21, "resteepen_level": 0.25},
        "4": {"rule": "spread_widening", "series": "baa10y", "low_lookback_days": 365, "widen": 0.60},
        "6": {"rule": "price_confirmation", "index": "spx", "dma_days": 200,
               "sahm_series": "sahmrealtime", "sahm_level": 0.5,
               "vix_series": "vixcls", "vix_level": 30},
    },
}


def days(n, end=ASOF):
    return pd.date_range(end=end, periods=n, freq="B")


def test_curve_resteepen_fires_after_inversion():
    idx = days(400)
    vals = np.full(len(idx), 1.0)
    vals[100:160] = -0.3          # inverted ~60 business days, within lookback
    vals[-30:] = 0.30             # re-steepened above 0.25
    raw = {"t10y3m": pd.Series(vals, index=idx)}
    fired = seq._stage_curve_resteepen(CFG["stages"]["3"], raw, ASOF)
    assert fired is True
    # never inverted -> False
    raw2 = {"t10y3m": pd.Series(np.full(len(idx), 1.0), index=idx)}
    assert seq._stage_curve_resteepen(CFG["stages"]["3"], raw2, ASOF) is False


def test_spread_widening():
    idx = days(300)
    vals = np.full(len(idx), 1.50)
    vals[-5:] = 2.30              # 12m low 1.50, now +0.80 -> fired
    raw = {"baa10y": pd.Series(vals, index=idx)}
    assert seq._stage_spread_widening(CFG["stages"]["4"], raw, ASOF) is True
    vals[-5:] = 1.80              # only +0.30 -> not fired
    raw = {"baa10y": pd.Series(vals, index=idx)}
    assert seq._stage_spread_widening(CFG["stages"]["4"], raw, ASOF) is False


def test_price_confirmation_needs_both_conditions():
    idx = days(300)
    spx = pd.Series(np.linspace(5000, 4000, len(idx)), index=idx)   # below its 200dma
    vix_hot = {"spx": spx, "vixcls": pd.Series([35.0], index=[ASOF]),
               "sahmrealtime": pd.Series([0.1], index=[ASOF - pd.Timedelta(days=40)])}
    assert seq._stage_price_confirmation(CFG["stages"]["6"], vix_hot, ASOF) is True
    calm = {"spx": spx, "vixcls": pd.Series([12.0], index=[ASOF]),
            "sahmrealtime": pd.Series([0.1], index=[ASOF - pd.Timedelta(days=40)])}
    assert seq._stage_price_confirmation(CFG["stages"]["6"], calm, ASOF) is False


def test_missing_data_returns_none():
    assert seq._stage_spread_widening(CFG["stages"]["4"], {}, ASOF) is None


def test_update_state_fire_lapse_and_engage():
    spx = pd.Series(np.full(300, 5000.0), index=days(300))
    state = seq.new_state()
    fired = {1: True, 2: None, 3: True, 4: False, 5: False, 6: False}
    state = seq.update_state(state, fired, ASOF, spx, CFG)
    assert state["engaged"] is True                     # stages 1+3 of 1-3 fired
    assert state["current_stage"] == 3
    assert state["stages"]["1"]["fired"] is True
    assert state["stages"]["2"]["fired"] is None        # no data
    # condition goes false long enough -> lapse
    later = ASOF + pd.Timedelta(days=120)
    fired_off = {1: False, 2: None, 3: False, 4: False, 5: False, 6: False}
    state = seq.update_state(state, fired_off, later, spx, CFG)
    assert state["stages"]["1"]["lapsed"] is True
    assert state["engaged"] is False


def test_update_state_reset_on_drawdown():
    idx = days(300)
    vals = np.full(len(idx), 5000.0)
    vals[-10:] = 3800.0                                  # >20% below post-engagement high
    spx = pd.Series(vals, index=idx)
    state = seq.new_state()
    state = seq.update_state(state, {1: True, 2: True, 3: True, 4: True, 5: True, 6: True}, ASOF, spx, CFG)
    assert state["engaged"] is False                     # reset: crisis realized
    assert state["current_stage"] == 0
```

- [ ] **Step 3: Implement `pipeline/compute/sequencer.py`:**

```python
from __future__ import annotations

import json

import pandas as pd

from pipeline import paths

STAGE_IDS = (1, 2, 3, 4, 5, 6)


def _win(s: pd.Series, asof: pd.Timestamp, days: int) -> pd.Series:
    s = s[s.index <= asof]
    return s[s.index >= asof - pd.Timedelta(days=days)]


def _stage_pillar_above(cfg, pillars_full: pd.Series, asof) -> bool | None:
    """pillars_full: daily full-window score series for the configured pillar."""
    if pillars_full is None or pillars_full.empty:
        return None
    w = _win(pillars_full, asof, cfg["min_days"] * 2)
    if len(w) < cfg["min_days"]:
        return None
    return bool((w.tail(cfg["min_days"]) > cfg["level"]).all())


def _stage_froth_rollover(cfg, froth: pd.Series, asof) -> bool | None:
    if froth is None or froth.empty:
        return None
    w = _win(froth, asof, cfg["lookback_days"])
    if w.empty:
        return None
    if w.max() <= cfg["level"]:
        return False
    tail = w.tail(cfg["decline_obs"] + 1)
    if len(tail) < cfg["decline_obs"] + 1:
        return False
    return bool(tail.is_monotonic_decreasing and tail.iloc[-1] < w.max())


def _stage_curve_resteepen(cfg, raw: dict, asof) -> bool | None:
    s = raw.get(cfg["series"])
    if s is None or s.empty:
        return None
    w = _win(s, asof, cfg["lookback_days"])
    if w.empty:
        return None
    inverted_days = int((w < 0).sum())
    now = w.iloc[-1]
    return bool(inverted_days >= cfg["min_inverted_days"] and now > cfg["resteepen_level"])


def _stage_spread_widening(cfg, raw: dict, asof) -> bool | None:
    s = raw.get(cfg["series"])
    if s is None or s.empty:
        return None
    w = _win(s, asof, cfg["low_lookback_days"])
    if w.empty:
        return None
    return bool(w.iloc[-1] >= w.min() + cfg["widen"])


def _stage_breadth_divergence(cfg, raw: dict, breadth_raw: pd.Series | None, asof) -> bool | None:
    idx_s = raw.get(cfg["index"])
    if idx_s is None or idx_s.empty or breadth_raw is None or breadth_raw.empty:
        return None
    w = _win(idx_s, asof, cfg["high_lookback_days"])
    b = _win(breadth_raw, asof, cfg["breadth_low_days"])
    if w.empty or b.empty:
        return None
    near_high = w.iloc[-1] >= w.max() * (1 - cfg["near_high_pct"] / 100.0)
    breadth_at_low = b.iloc[-1] <= b.min() + 1e-9
    return bool(near_high and breadth_at_low)


def _stage_price_confirmation(cfg, raw: dict, asof) -> bool | None:
    idx_s = raw.get(cfg["index"])
    if idx_s is None or len(idx_s[idx_s.index <= asof]) < cfg["dma_days"]:
        return None
    upto = idx_s[idx_s.index <= asof]
    below_dma = upto.iloc[-1] < upto.rolling(cfg["dma_days"]).mean().iloc[-1]
    sahm = raw.get(cfg["sahm_series"])
    vix = raw.get(cfg["vix_series"])
    sahm_hot = (sahm is not None and not sahm[sahm.index <= asof].empty
                and sahm[sahm.index <= asof].iloc[-1] >= cfg["sahm_level"])
    vix_hot = (vix is not None and not vix[vix.index <= asof].empty
               and vix[vix.index <= asof].iloc[-1] >= cfg["vix_level"])
    return bool(below_dma and (sahm_hot or vix_hot))


def evaluate_stages(reg, thresholds, raw, result, asof) -> dict[int, bool | None]:
    cfg = thresholds["sequencer"]["stages"]
    pillars_full = None
    if result is not None:
        pf = result.pillars[(result.pillars.window == "full")
                            & (result.pillars.pillar == cfg["1"]["pillar"])]
        if not pf.empty:
            pillars_full = pf.set_index("date")["score"]
    froth = None
    if result is not None and cfg["2"]["indicator"] in result.indicators:
        froth = result.indicators[cfg["2"]["indicator"]].froth_full
    breadth = None
    if result is not None and cfg["5"]["breadth"] in result.indicators:
        breadth = result.indicators[cfg["5"]["breadth"]].series
    return {
        1: _stage_pillar_above(cfg["1"], pillars_full, asof),
        2: _stage_froth_rollover(cfg["2"], froth, asof),
        3: _stage_curve_resteepen(cfg["3"], raw, asof),
        4: _stage_spread_widening(cfg["4"], raw, asof),
        5: _stage_breadth_divergence(cfg["5"], raw, breadth, asof),
        6: _stage_price_confirmation(cfg["6"], raw, asof),
    }


def new_state() -> dict:
    return {"as_of": None, "engaged": False, "current_stage": 0,
            "stages": {str(n): {"fired": None, "fired_date": None, "lapsed": False, "last_true": None}
                        for n in STAGE_IDS}}


def update_state(prev: dict, fired: dict[int, bool | None], asof: pd.Timestamp,
                 spx: pd.Series, cfg: dict) -> dict:
    state = json.loads(json.dumps(prev))  # deep copy
    date_s = asof.strftime("%Y-%m-%d")
    state["as_of"] = date_s
    for n in STAGE_IDS:
        st = state["stages"][str(n)]
        f = fired.get(n)
        if f is True:
            if st["fired"] is not True or st["lapsed"]:
                st["fired"], st["fired_date"], st["lapsed"] = True, date_s, False
            st["last_true"] = date_s
        elif f is False:
            if st["fired"] is None:
                st["fired"] = False
            if st["fired"] is True and st["last_true"]:
                gap = (asof - pd.Timestamp(st["last_true"])).days
                if gap > cfg["lapse_days"]:
                    st["lapsed"] = True
        # f is None -> leave state untouched (no data)
    active = [n for n in STAGE_IDS
              if state["stages"][str(n)]["fired"] is True and not state["stages"][str(n)]["lapsed"]]
    early = [n for n in active if n <= 3]
    state["engaged"] = len(early) >= cfg["engaged_min_stages"]
    state["current_stage"] = max(active) if state["engaged"] and active else 0
    # reset: crisis realized (drawdown from 12m high beyond threshold)
    if state["engaged"] and spx is not None and not spx.empty:
        w = _win(spx, asof, 365)
        if not w.empty and w.iloc[-1] <= w.max() * (1 - cfg["reset_drawdown_pct"] / 100.0):
            for n in STAGE_IDS:
                state["stages"][str(n)]["lapsed"] = True
            state["engaged"] = False
            state["current_stage"] = 0
    return state


def load_state() -> dict:
    fp = paths.DATA_STATE / "sequence_state.json"
    if not fp.exists():
        return new_state()
    return json.loads(fp.read_text())


def save_state(state: dict) -> None:
    paths.DATA_STATE.mkdir(parents=True, exist_ok=True)
    (paths.DATA_STATE / "sequence_state.json").write_text(json.dumps(state, indent=1) + "\n")
```

- [ ] **Step 4: Wire into `cmd_run`** (after `append_scores`):

```python
    from pipeline.compute.sequencer import evaluate_stages, load_state, save_state, update_state
    from pipeline.registry import load_thresholds as _lt
    th = load_thresholds()
    asof = max(s.index.max() for s in raw.values() if not s.empty)
    fired = evaluate_stages(reg, th, raw, result, asof)
    seq_state = update_state(load_state(), fired, asof, raw.get("spx"), th["sequencer"])
    save_state(seq_state)
    print(f"sequencer: engaged={seq_state['engaged']} current_stage={seq_state['current_stage']}")
```

Alerts — in `evaluate_alerts`, after the pillar rule, add stage-advance detection (state file diff persisted by run; alert on stages whose `fired_date == state['as_of']`):

```python
    from pipeline.compute.sequencer import load_state
    seq_state = load_state()
    if seq_state.get("as_of"):
        for n_str, st in seq_state["stages"].items():
            if st.get("fired") is True and st.get("fired_date") == seq_state["as_of"] and not st.get("lapsed"):
                out.append(Alert(
                    f"alert:stage-{n_str}",
                    f"Sequence stage {n_str} fired",
                    f"Pre-crisis sequence stage {n_str} fired on {seq_state['as_of']}. "
                    f"Engaged: {seq_state['engaged']}, current stage: {seq_state['current_stage']}.",
                ))
```

Export — replace `"sequence": None,` with `"sequence": load_state() if (paths.DATA_STATE / "sequence_state.json").exists() else None,` (import at top of the function alongside other episode imports).

- [ ] **Step 5: Tracker UI.** Replace the sequence placeholder card in `index.html`:

```html
  <div class="card" id="sequence-card">
    <h3>Pre-crisis sequence</h3>
    <div id="sequence-banner" class="muted"></div>
    <div id="sequence-track"></div>
  </div>
```

`style.css` append:

```css
#sequence-track { display:flex; gap:4px; margin-top:8px; }
.stage { flex:1; text-align:center; font-size:.7rem; padding:6px 2px; border-radius:6px;
         border:1px solid var(--line); color:var(--muted); }
.stage.fired { border-color:var(--bubble); color:var(--text); background:rgba(214,69,69,.12); }
.stage.lapsed { border-color:var(--warm); opacity:.6; }
.stage.nodata { border-style:dashed; }
```

`app.js` add + call in `boot()`:

```javascript
const STAGE_NAMES = ["Valuation", "Leverage peak", "Curve turn", "Credit widen", "Breadth break", "Confirmed"];

function renderSequence() {
  const s = LATEST.sequence;
  const banner = document.getElementById("sequence-banner");
  const track = document.getElementById("sequence-track");
  if (!s) { banner.textContent = "Available after first scheduled run."; return; }
  banner.innerHTML = s.engaged
    ? `<span style="color:var(--frothy)">Sequence engaged</span> — current stage ${s.current_stage}`
    : "Sequence not engaged — no pre-crisis pattern in progress.";
  track.innerHTML = STAGE_NAMES.map((name, i) => {
    const st = s.stages[String(i + 1)] || {};
    let cls = "stage";
    if (st.fired === true && !st.lapsed) cls += " fired";
    else if (st.lapsed) cls += " lapsed";
    else if (st.fired === null) cls += " nodata";
    const sub = st.fired === true ? (st.fired_date || "") : st.fired === null ? "no data" : "";
    return `<div class="${cls}">${i + 1}. ${name}<br><span class="muted">${sub}</span></div>`;
  }).join("");
}
```

Remove the `placeholder` class from the card.

- [ ] **Step 6: Suite + live.** `pytest -q` green (report count). `./venv/bin/python -m pipeline run && ./venv/bin/python -m pipeline export`. Sanity: print the sequence state — given mid-2026 conditions expect `engaged` likely False with stages mostly False/None (stage 2 `no data` unless Task 5 acquired margin data); any stage firing TODAY should be justified by the data (if stage 3 or 4 fires, print the underlying series values proving the trigger; the 2025-26 curve history did invert and re-steepen — a stage-3 fire may be legitimate; verify against t10y3m values, not vibes).

- [ ] **Step 7: Design-doc note + commit + push.** Append one sentence to the design §8b table area... precisely: add under the §8b table: `**Implementation note (2026-07-06):** stage 4 uses Moody's Baa−10Y (+60 bp off its 12-month low) instead of HY OAS +100 bp — FRED's HY series lacks pre-2023 history (license); revisit when a deep HY source exists.` Commit: `feat: pre-crisis sequencing state machine with tracker UI and stage alerts`. Push, watch green.

---

### Task 7: Backtest replay + page + base rates

**Files:**
- Create: `pipeline/backtest.py`, `tests/test_backtest.py`, `site/backtest.html`
- Modify: `pipeline/cli.py` (backtest subcommand), `site/index.html` (nav link), `site/assets/app.js` (base-rate line in analog card)

**Interfaces:**
- Consumes: `evaluate_stages`, `update_state`, `new_state` (Task 6); `compute_scores`; scores CSVs; `analogs.top_analogs`; snapshots.
- Produces: `backtest.run_backtest(reg, thresholds, raw, epi_cfg, start="1997-01-31") -> dict` payload; `site/data/backtest.json`:
  ```
  {"months": [...YYYY-MM-DD...], "stage": [...int...], "engaged": [...bool...],
   "composite": [...], "spx": [...],
   "episodes": [{id, name, peak, control}],
   "criteria": [{"name": str, "pass": bool, "detail": str}],
   "base_rate": {"threshold": 0.8, "n_high_outside": int, "n_high_inside": int, "n_months": int}}
  ```
- Replay is **monthly** (business month-end steps) — documented deviation from "day-by-day" (design §10): stage conditions move at monthly cadence; daily replay adds 20× compute for no decision value. Lag realism: each series is shifted by its registry `lag_days` before evaluation (`s_lagged` index = obs index + lag), implementing §10's point-in-time approximation.

- [ ] **Step 1: Failing tests** — `tests/test_backtest.py`:

```python
import numpy as np
import pandas as pd
import pytest

from pipeline import backtest


def test_lag_shift():
    s = pd.Series([1.0], index=pd.to_datetime(["2020-01-01"]))
    out = backtest.apply_lag(s, 30)
    assert out.index[0] == pd.Timestamp("2020-01-31")


def test_criteria_evaluation():
    months = pd.date_range("1998-01-31", "2023-12-29", freq="BME")
    stage = pd.Series(0, index=months)
    stage.loc["1999-06-30":"2000-03-31"] = 4      # hot before dot-com
    stage.loc["2007-01-31":"2007-10-31"] = 4      # hot before GFC
    stage.loc["2021-06-30":"2022-01-31"] = 4      # hot before 2022
    engaged = stage >= 2
    epi = [{"id": "dotcom", "peak": "2000-03-24"}, {"id": "gfc", "peak": "2007-10-09"},
           {"id": "covid", "peak": "2020-02-19", "control": True},
           {"id": "postcovid", "peak": "2022-01-03"}]
    crits = backtest.evaluate_criteria(stage, engaged, epi)
    by = {c["name"]: c["pass"] for c in crits}
    assert by["stage>=4 before dotcom peak"] is True
    assert by["stage>=4 before gfc peak"] is True
    assert by["stage>=4 before postcovid peak"] is True
    assert by["quiet through 2019 (covid control)"] is True
    # violate the control: engaged through 2019
    stage.loc["2019-01-31":"2019-12-31"] = 3
    crits2 = backtest.evaluate_criteria(stage, stage >= 2, epi)
    assert {c["name"]: c["pass"] for c in crits2}["quiet through 2019 (covid control)"] is False
```

- [ ] **Step 2: Implement `pipeline/backtest.py`:**

```python
from __future__ import annotations

import pandas as pd

from pipeline import paths, store
from pipeline.compute.analogs import top_analogs
from pipeline.compute.episodes import load_snapshots
from pipeline.compute.scores import compute_scores
from pipeline.compute.sequencer import evaluate_stages, new_state, update_state


def apply_lag(s: pd.Series, lag_days: int) -> pd.Series:
    out = s.copy()
    out.index = out.index + pd.Timedelta(days=lag_days)
    return out


def evaluate_criteria(stage: pd.Series, engaged: pd.Series, episodes: list[dict]) -> list[dict]:
    crits = []
    for ep in episodes:
        peak = pd.Timestamp(ep["peak"])
        if ep.get("control"):
            window = engaged[(engaged.index >= "2019-01-01") & (engaged.index <= "2019-12-31")]
            ok = bool((~window).all()) if not window.empty else False
            crits.append({"name": "quiet through 2019 (covid control)", "pass": ok,
                          "detail": f"{int(window.sum())} engaged months in 2019"})
            continue
        pre = stage[(stage.index >= peak - pd.DateOffset(months=18)) & (stage.index <= peak)]
        ok = bool((pre >= 4).any()) if not pre.empty else False
        crits.append({"name": f"stage>=4 before {ep['id']} peak", "pass": ok,
                      "detail": f"max stage {int(pre.max()) if not pre.empty else -1} in T-18m..T"})
    return crits


def run_backtest(reg, thresholds, raw, epi_cfg, start: str = "1997-01-31") -> dict:
    lagged = {}
    lag_by_id = {s.id: s.lag_days for s in reg.series}
    for sid, s in raw.items():
        lagged[sid] = apply_lag(s, lag_by_id.get(sid, 0)) if not s.empty else s
    months = pd.date_range(start, max(s.index.max() for s in raw.values() if not s.empty), freq="BME")
    state = new_state()
    stages, engaged = [], []
    result = compute_scores(reg, thresholds, lagged)
    for m in months:
        fired = evaluate_stages(reg, thresholds, lagged, result, m)
        state = update_state(state, fired, m, lagged.get("spx"), thresholds["sequencer"])
        stages.append(state["current_stage"])
        engaged.append(state["engaged"])
    stage_s = pd.Series(stages, index=months)
    engaged_s = pd.Series(engaged, index=months)

    comp = pd.read_csv(paths.DATA_SCORES / "composite.csv", parse_dates=["date"])
    comp = comp[comp.window == "full"].set_index("date")["score"]
    comp_m = comp.resample("BME").last().reindex(months)
    spx = raw["spx"].resample("BME").last().reindex(months)

    snaps = load_snapshots()
    n_high_out, n_high_in = 0, 0
    peaks = [pd.Timestamp(e["peak"]) for e in epi_cfg["episodes"] if not e.get("control")]
    if not snaps.empty:
        froth = {i: r.froth_full for i, r in result.indicators.items() if not r.froth_full.empty}
        for m in months:
            vec = {i: float(f.asof(m)) for i, f in froth.items() if not pd.isna(f.asof(m))}
            top = top_analogs(vec, snaps, k=1)
            if top and top[0]["similarity"] >= 0.8:
                inside = any(p - pd.DateOffset(months=24) <= m <= p for p in peaks)
                n_high_in += inside
                n_high_out += not inside
    return {
        "months": [m.strftime("%Y-%m-%d") for m in months],
        "stage": [int(x) for x in stage_s],
        "engaged": [bool(x) for x in engaged_s],
        "composite": [None if pd.isna(v) else round(float(v), 2) for v in comp_m],
        "spx": [None if pd.isna(v) else round(float(v), 2) for v in spx],
        "episodes": epi_cfg["episodes"],
        "criteria": evaluate_criteria(stage_s, engaged_s, epi_cfg["episodes"]),
        "base_rate": {"threshold": 0.8, "n_high_outside": int(n_high_out),
                       "n_high_inside": int(n_high_in), "n_months": len(months)},
    }
```

CLI:

```python
def cmd_backtest(args: argparse.Namespace) -> int:
    from pipeline.backtest import run_backtest
    from pipeline.export import _atomic_write
    from pipeline.registry import load_episodes, load_thresholds

    reg = load_registry()
    raw = {s.id: store.read_series(s.id) for s in reg.series}
    payload = run_backtest(reg, load_thresholds(), raw, load_episodes())
    _atomic_write(paths.SITE_DATA / "backtest.json", payload)
    for c in payload["criteria"]:
        print(f"{'PASS' if c['pass'] else 'FAIL'}  {c['name']}  ({c['detail']})")
    br = payload["base_rate"]
    print(f"base rate: similarity>={br['threshold']} in {br['n_high_outside']} months outside "
          f"pre-crisis windows, {br['n_high_inside']} inside, of {br['n_months']}")
    return 0
```

register `sub.add_parser("backtest").set_defaults(fn=cmd_backtest)`.

- [ ] **Step 3: `site/backtest.html`** (same chrome as episode pages; loads plotly + a small inline script):

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
<div class="muted">Sequencer &amp; score replay (monthly, publication-lag adjusted)</div></header>
<section class="card"><div id="bt-chart"></div></section>
<section class="card"><h2>Validation criteria</h2><div id="bt-criteria"></div></section>
<footer class="muted">Monitoring context, not a trading signal.</footer>
<script src="assets/plotly-finance.min.js"></script>
<script>
fetch("data/backtest.json").then(r => r.json()).then(bt => {
  const shapes = bt.episodes.filter(e => !e.control).map(e => {
    const peak = new Date(e.peak); const start = new Date(peak); start.setMonth(start.getMonth() - 24);
    return { type: "rect", x0: start.toISOString().slice(0,10), x1: e.peak, y0: 0, y1: 1,
             yref: "paper", fillcolor: "rgba(214,69,69,.08)", line: { width: 0 } };
  });
  Plotly.newPlot("bt-chart", [
    { x: bt.months, y: bt.spx, name: "S&P 500 (log)", yaxis: "y", line: { color: "#e6e9ef", width: 1.4 } },
    { x: bt.months, y: bt.composite, name: "Composite", yaxis: "y2", line: { color: "#e0b83c", width: 1.2 } },
    { x: bt.months, y: bt.stage, name: "Sequence stage", yaxis: "y3", line: { color: "#d64545", width: 1.2, shape: "hv" } },
  ], { paper_bgcolor: "#1b2029", plot_bgcolor: "#1b2029", font: { color: "#e6e9ef", size: 12 },
       height: 520, shapes, grid: { rows: 3, columns: 1, roworder: "top to bottom" },
       yaxis: { type: "log", title: { text: "S&P 500" } },
       yaxis2: { range: [0, 100], title: { text: "score" } },
       yaxis3: { range: [0, 6.5], dtick: 1, title: { text: "stage" } },
       legend: { orientation: "h", y: -0.08 } }, { displayModeBar: false, responsive: true });
  document.getElementById("bt-criteria").innerHTML = "<ul>" + bt.criteria.map(c =>
    `<li>${c.pass ? "✅" : "❌"} ${c.name} <span class="muted">(${c.detail})</span></li>`).join("") + "</ul>";
});
</script>
</body>
</html>
```

Add to `index.html` nav: ` · <a href="backtest.html">Backtest</a>` and in `app.js` `renderAnalogs`, after the list HTML, fetch base rate lazily:

```javascript
  fetch("data/backtest.json").then(r => r.ok ? r.json() : null).then(bt => {
    if (!bt) return;
    const br = bt.base_rate;
    list.insertAdjacentHTML("beforeend",
      `<div class="muted" style="margin-top:6px;font-size:.75rem">Base rate: similarity ≥ ${br.threshold * 100}% occurred in ` +
      `${br.n_high_outside} of ${br.n_months} months OUTSIDE pre-crisis windows (small-sample caveat).</div>`);
  }).catch(() => {});
```

- [ ] **Step 4: Run + honesty gate.** `pytest -q` green; `./venv/bin/python -m pipeline backtest` — print all criteria results in your report. **Do NOT tune thresholds to force passes in this task.** If criteria fail (plausible: dotcom lacks qualified breadth/margin data; stage 2 may be no-data), report the honest result — threshold tuning is a documented follow-up, and the criteria evaluation notes which stages were data-limited. Commit (`feat: backtest replay with validation criteria and base rates`), push, watch green; verify live `https://jungohlee.github.io/macro-monitoring/backtest.html` returns 200 and renders.

---

### Task 8: Narrative firing timelines

**Files:**
- Modify: `pipeline/export.py` (`render_episodes` injects auto-generated timeline), `tests/test_episodes.py` (extend)

**Interfaces:**
- Consumes: `episodes.load_snapshots`, `episodes.firing_timeline`, `load_episodes`, indicator names from the registry.
- Produces: each `site/episodes/<id>.html` gains an "Indicator timeline (auto-generated)" section between the markdown body and the footer, when snapshot data exists for that episode id.

- [ ] **Step 1: Failing test** — extend `tests/test_episodes.py`:

```python
def test_render_episodes_injects_timeline(tmp_path, monkeypatch):
    import pandas as pd

    import pipeline.compute.episodes as epimod
    from pipeline import export

    monkeypatch.setattr(export.paths, "EPISODES", tmp_path / "episodes")
    monkeypatch.setattr(export.paths, "SITE", tmp_path / "site")
    (tmp_path / "episodes").mkdir()
    (tmp_path / "episodes" / "gfc.md").write_text("# GFC\n\nBody.\n")
    snaps = pd.DataFrame([
        {"episode": "gfc", "offset_months": -12, "indicator_id": "household_debt_gdp", "percentile": 95.0},
        {"episode": "gfc", "offset_months": -3, "indicator_id": "vix", "percentile": 88.0},
    ])
    monkeypatch.setattr(epimod, "load_snapshots", lambda: snaps)
    export.render_episodes()
    html = (tmp_path / "site" / "episodes" / "gfc.html").read_text()
    assert "Indicator timeline" in html
    assert "T−12m" in html or "T-12m" in html
    assert "household_debt_gdp" in html or "Household" in html
```

- [ ] **Step 2: Implement.** In `render_episodes`, before writing each file, build the timeline block:

```python
def _timeline_html(ep_id: str) -> str:
    from pipeline.compute.episodes import firing_timeline, load_snapshots
    from pipeline.registry import load_registry

    snaps = load_snapshots()
    if snaps.empty or ep_id not in set(snaps.episode):
        return ""
    names = {i.id: i.name for i in load_registry().indicators}
    rows_html = []
    for level in (80, 90):
        tl = firing_timeline(snaps, level)
        tl = tl[tl.episode == ep_id].sort_values("first_offset")
        for r in tl.itertuples(index=False):
            rows_html.append(
                f"<tr><td>{names.get(r.indicator_id, r.indicator_id)}</td>"
                f"<td>&ge;{level}th pct</td><td>T{'+' if r.first_offset >= 0 else '&minus;'}{abs(int(r.first_offset))}m</td></tr>")
    if not rows_html:
        return ""
    return ("<h2>Indicator timeline (auto-generated)</h2>"
            "<p class='muted'>First snapshot offset at which each indicator crossed the given "
            "froth percentile, from the episode library. Sparse for early episodes where "
            "fewer indicators have 10y of history.</p>"
            "<table>" + "".join(rows_html) + "</table>")
```

and in the loop: `body = markdown.markdown(text) + _timeline_html(md_file.stem)`.

(`registry.load_registry()` inside `_timeline_html` reads the real config — in the test the fixture indicators aren't registered, so `names.get` falls back to the raw id; that's what the test asserts. Guard: wrap the `load_registry()` call in try/except falling back to `{}` names so the unit test never depends on real config validity.)

- [ ] **Step 3: `pytest -q` green; `pipeline export`; open one episode page locally and confirm the table renders after the narrative. Commit (`feat: auto-generated indicator firing timelines on episode pages`), push, watch green, curl the live gfc page and grep for "Indicator timeline".**

---

### Task 9: E2E validation + docs + final review prep

**Files:**
- Modify: `README.md` (status section), design doc (§13 backtest results note)

- [ ] **Step 1:** README status line: Phase 3 complete (role-aware composite + stress gauge, analogs + radar, sequence tracker, backtest page, timelines); add backtest.html link.
- [ ] **Step 2:** Append to the design doc under §13: a dated note recording the actual backtest criteria results (pass/fail per criterion, honest).
- [ ] **Step 3:** Live E2E: dispatch the workflow (`gh workflow run daily.yml`), watch green, then verify: index 200 with tabs + stress + analog card + tracker rendering (Playwright pass over the live URL); backtest.html 200; an episode page shows the timeline; latest.json has stress/analogs/sequence non-null (sequence non-null after the run commits state).
- [ ] **Step 4:** Commit docs (`docs: Phase 3 status + backtest results`), push, watch green.
- [ ] **Step 5:** Hand back to controller for the final whole-branch review (Phase 3 range).

---

## Plan Self-Review (performed at write time)

1. **Spec coverage:** role-aware composite + stress (amendment) → T1; tabs/markers/stress UI → T2; episode library §5/§2 snapshots+exclusion → T3; analogs §5.2 cosine + radar + table + deep links → T4; margin debt (§13 stage-2 dependency, §2b FINRA) → T5 best-effort with honest degradation; sequencer §8a/§8b (stage 4 amended Baa+60bp, documented) + stage alerts §8c + tracker §7.5 → T6; backtest §10/§13 + base-rate §7.4 → T7; timelines §9 → T8; §13 results recorded → T9. Radar uses SVG (no bundle change) — §7.4's "radar/spider chart" satisfied.
2. **Placeholder scan:** none — every step has full code or exact commands. T5's acquisition step is genuinely conditional (external dependency) with both branches fully specified.
3. **Type consistency:** `ScoreResult.stress` (T1) consumed by export T1/T3-ordering; `append_scores` 3-tuple caller updated in T1; `load_snapshots/firing_timeline/pillar_scores_from_snapshots` signatures consistent across T3/T4/T7/T8; sequencer stage functions consistent between tests and module (T6); `evaluate_stages(reg, thresholds, raw, result, asof)` matches T7's replay call; state schema identical in T6 update_state/new_state, export, alerts, and app.js `renderSequence`; `episodes.json` keys in T3 export match app.js reads in T4 (`snapshots`, `pillar_scores`, keyed by `String(offset)`).
```