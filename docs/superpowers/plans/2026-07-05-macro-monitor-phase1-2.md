# Macro Monitor Phases 1–2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Working end-to-end monitor: daily GitHub Action ingests 23 raw series, scores 18 indicators into 5 pillars + composite, commits data, publishes a graphical static dashboard to GitHub Pages, and emails alerts via labeled GitHub issues.

**Architecture:** Python package `pipeline/` does ingest → compute → alerts → export; all state lives in committed CSVs/JSON (append-mostly); `site/` is a static Plotly dashboard reading pre-computed `site/data/*.json`. Spec: `docs/superpowers/specs/2026-07-05-macro-monitor-design.md`.

**Tech Stack:** Python 3.12, pandas ≥2.2, requests, PyYAML, python-dotenv, markdown, pytest; vendored `plotly.js-finance-dist-min`; GitHub Actions + Pages; `gh` CLI for issues.

## Global Constraints

- Repo root: `/Users/jolee/Library/CloudStorage/Dropbox/CodingProjects/macro-monitoring` (git repo, remote `JungOhLee/macro-monitoring`, branch `main`). Run all commands from repo root.
- Python ≥3.12. Install once with `pip install -e '.[dev]'` (Task 1 creates pyproject).
- `FRED_API_KEY` comes from `.env` locally (already present, gitignored) and the repo secret in CI. Never print or commit it.
- Full-history percentile window is **canonical**; rolling-20y is display-only. Windows are named `"full"` and `"rolling20y"` everywhere (CSV `window` column, JSON keys).
- A series enters scoring only with ≥10 years of history (`MIN_HISTORY_DAYS = 3652`).
- Raw CSVs are append-mostly: rows within a series' `revision_window_days` (measured back from the last *stored* observation date) may be rewritten; older stored rows are never modified.
- Percentiles are computed at each series' native frequency, then as-of joined (ffill) to the daily calendar. Never forward-fill a series before computing its percentile distribution.
- Regime bands (thresholds.yaml): score <40 `cool`, <70 `warm`, <85 `frothy`, else `bubble_risk`.
- Network-touching code must use `timeout=30` and raise on HTTP errors. Tests never hit the network (monkeypatch `requests.get`).
- Alerts create GitHub issues only when env `GITHUB_ACTIONS` is set; locally they print to stdout.
- Every commit message: conventional prefix (`feat:`, `test:`, `chore:`, `data:`, `docs:`) and ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- TDD: write the failing test first in every task that has testable logic.

## File Map (what exists after Phase 2)

| Path | Responsibility |
|---|---|
| `pyproject.toml` | Package + deps |
| `config/registry.yaml` | 23 raw series + 18 indicators + pillar weights |
| `config/thresholds.yaml` | Regime bands, score start date, alert settings |
| `pipeline/paths.py` | Repo-relative path constants |
| `pipeline/registry.py` | Typed config loading + validation |
| `pipeline/store.py` | Raw-CSV read/merge/write, freshness state |
| `pipeline/ingest/fred.py`, `stooq.py` | One fetcher per source → `pd.Series` |
| `pipeline/ingest/__init__.py` | `run_ingest`: all series, per-series isolation |
| `pipeline/compute/derived.py` | Named formulas building indicator series from raw series |
| `pipeline/compute/percentiles.py` | Expanding/rolling percentiles, z-scores, direction, 10y gate |
| `pipeline/compute/scores.py` | Pillar + composite frames, regime, append to CSVs |
| `pipeline/alerts.py` | Rule evaluation + gh-issue delivery (CI-gated) |
| `pipeline/export.py` | `site/data/*.json` (atomic writes) + episode page rendering |
| `pipeline/cli.py` | `python -m pipeline run\|export\|status\|alerts` |
| `pipeline/__main__.py` | CLI entry |
| `.github/workflows/daily.yml` | cron ×2 + dispatch + push; build & Pages deploy |
| `scripts/setup_repo.sh` | One-time: labels + Pages source |
| `site/index.html`, `site/assets/app.js`, `style.css` | Dashboard views 1–3, 6 + Phase-3 placeholders |
| `site/assets/plotly-finance.min.js` | Vendored Plotly partial bundle |
| `episodes/*.md` | Narrative drafts (4 episodes) |
| `tests/…` | One test module per pipeline module + `tests/fixtures/` |

Interface types used throughout: a **series** is a `pd.Series` with tz-naive ascending `DatetimeIndex`, `float` values, `.name` = series id; missing observations are absent rows (never NaN rows).

---

### Task 1: Scaffolding, config files, registry loader

**Files:**
- Create: `pyproject.toml`, `pipeline/__init__.py`, `pipeline/paths.py`, `pipeline/registry.py`, `config/registry.yaml`, `config/thresholds.yaml`, `tests/__init__.py`, `tests/test_registry.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `paths.ROOT/CONFIG/DATA_RAW/DATA_SCORES/DATA_STATE/SITE/SITE_DATA/EPISODES` (all `pathlib.Path`); `registry.load_registry() -> Registry`; `registry.load_thresholds() -> dict`; dataclasses `Series(id, source, source_id, frequency, staleness_budget_days, revision_window_days, lag_days)`, `Indicator(id, name, pillar, role, direction, series, formula, inputs, lag_days)` (for raw-backed indicators `series` is set and `formula/inputs` are `None`; for derived ones `series is None`); `Registry(series: list[Series], indicators: list[Indicator], pillar_weights: dict[str, float])` with helper `Registry.series_by_id: dict[str, Series]`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "macro-monitor-pipeline"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "pandas>=2.2",
    "requests>=2.32",
    "PyYAML>=6.0",
    "python-dotenv>=1.0",
    "markdown>=3.6",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.setuptools]
packages = ["pipeline", "pipeline.ingest", "pipeline.compute"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create package skeleton**

Create empty `pipeline/__init__.py`, `tests/__init__.py`, and `pipeline/paths.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"
DATA_RAW = DATA / "raw"
DATA_SCORES = DATA / "scores"
DATA_STATE = DATA / "state"
SITE = ROOT / "site"
SITE_DATA = SITE / "data"
EPISODES = ROOT / "episodes"
```

Create dirs `pipeline/ingest/` and `pipeline/compute/` with empty `__init__.py` files (the ingest one gets real code in Task 6).

- [ ] **Step 3: Write `config/registry.yaml`** (complete file — this is the system's central config)

```yaml
# Directions: "normal" = higher raw value -> higher froth/risk percentile;
# "invert" = lower raw value -> higher froth/risk percentile.
# staleness_budget_days per design §6; revision_window_days / lag_days per design §5/§10.

pillar_weights:
  valuation: 0.30
  leverage: 0.25
  liquidity: 0.20
  sentiment: 0.15
  macro: 0.10

series:
  # ---- FRED ----
  - {id: ncbeilq027s, source: fred, source_id: NCBEILQ027S, frequency: quarterly, staleness_budget_days: 160, revision_window_days: 370, lag_days: 75}
  - {id: gdp,         source: fred, source_id: GDP,         frequency: quarterly, staleness_budget_days: 150, revision_window_days: 370, lag_days: 30}
  - {id: cmdebt,      source: fred, source_id: CMDEBT,      frequency: quarterly, staleness_budget_days: 160, revision_window_days: 370, lag_days: 75}
  - {id: bcnsdodns,   source: fred, source_id: BCNSDODNS,   frequency: quarterly, staleness_budget_days: 160, revision_window_days: 370, lag_days: 75}
  - {id: drtscilm,    source: fred, source_id: DRTSCILM,    frequency: quarterly, staleness_budget_days: 130, revision_window_days: 100, lag_days: 20}
  - {id: m2sl,        source: fred, source_id: M2SL,        frequency: monthly,   staleness_budget_days: 45,  revision_window_days: 60,  lag_days: 14}
  - {id: walcl,       source: fred, source_id: WALCL,       frequency: weekly,    staleness_budget_days: 12,  revision_window_days: 14,  lag_days: 1}
  - {id: wtregen,     source: fred, source_id: WTREGEN,     frequency: daily,     staleness_budget_days: 7,   revision_window_days: 7,   lag_days: 1}
  - {id: rrpontsyd,   source: fred, source_id: RRPONTSYD,   frequency: daily,     staleness_budget_days: 7,   revision_window_days: 7,   lag_days: 1}
  - {id: fedfunds,    source: fred, source_id: FEDFUNDS,    frequency: monthly,   staleness_budget_days: 45,  revision_window_days: 30,  lag_days: 3}
  - {id: cpilfesl,    source: fred, source_id: CPILFESL,    frequency: monthly,   staleness_budget_days: 50,  revision_window_days: 60,  lag_days: 14}
  - {id: bamlh0a0hym2, source: fred, source_id: BAMLH0A0HYM2, frequency: daily,   staleness_budget_days: 7,   revision_window_days: 7,   lag_days: 1}
  - {id: t10y2y,      source: fred, source_id: T10Y2Y,      frequency: daily,     staleness_budget_days: 7,   revision_window_days: 7,   lag_days: 1}
  - {id: t10y3m,      source: fred, source_id: T10Y3M,      frequency: daily,     staleness_budget_days: 7,   revision_window_days: 7,   lag_days: 1}
  - {id: vixcls,      source: fred, source_id: VIXCLS,      frequency: daily,     staleness_budget_days: 7,   revision_window_days: 7,   lag_days: 1}
  - {id: dtwexbgs,    source: fred, source_id: DTWEXBGS,    frequency: daily,     staleness_budget_days: 10,  revision_window_days: 7,   lag_days: 1}
  - {id: dtwexm,      source: fred, source_id: DTWEXM,      frequency: weekly,    staleness_budget_days: 36500, revision_window_days: 0, lag_days: 1}  # discontinued 2019; splice donor only
  - {id: sahmrealtime, source: fred, source_id: SAHMREALTIME, frequency: monthly, staleness_budget_days: 70,  revision_window_days: 90,  lag_days: 35}
  - {id: cfnai,       source: fred, source_id: CFNAI,       frequency: monthly,   staleness_budget_days: 60,  revision_window_days: 400, lag_days: 25}
  # ---- Stooq ----
  - {id: spx,    source: stooq, source_id: ^spx,   frequency: daily, staleness_budget_days: 7,  revision_window_days: 7, lag_days: 1}
  - {id: rsp,    source: stooq, source_id: rsp.us, frequency: daily, staleness_budget_days: 7,  revision_window_days: 7, lag_days: 1}
  - {id: spy,    source: stooq, source_id: spy.us, frequency: daily, staleness_budget_days: 7,  revision_window_days: 7, lag_days: 1}
  - {id: btcusd, source: stooq, source_id: btcusd, frequency: daily, staleness_budget_days: 7,  revision_window_days: 7, lag_days: 1}

indicators:
  # ---- Pillar A: valuation ----
  - {id: buffett, name: "Buffett indicator (corp equities / GDP)", pillar: valuation, role: magnitude, direction: normal,
     formula: ratio, inputs: [ncbeilq027s, gdp], lag_days: 75}
  # ---- Pillar B: leverage ----
  - {id: hy_oas, name: "High-yield OAS", pillar: leverage, role: timing, direction: invert, series: bamlh0a0hym2, lag_days: 1}
  - {id: household_debt_gdp, name: "Household debt / GDP", pillar: leverage, role: timing, direction: normal,
     formula: ratio, inputs: [cmdebt, gdp], lag_days: 75}
  - {id: corporate_debt_gdp, name: "Corporate debt / GDP", pillar: leverage, role: timing, direction: normal,
     formula: ratio, inputs: [bcnsdodns, gdp], lag_days: 75}
  - {id: sloos_tightening, name: "SLOOS net tightening (C&I)", pillar: leverage, role: timing, direction: invert, series: drtscilm, lag_days: 20}
  # ---- Pillar C: liquidity ----
  - {id: m2_yoy, name: "M2 YoY %", pillar: liquidity, role: timing, direction: normal,
     formula: yoy, inputs: [m2sl], lag_days: 14}
  - {id: fed_bs_yoy, name: "Fed balance sheet YoY %", pillar: liquidity, role: timing, direction: normal,
     formula: yoy, inputs: [walcl], lag_days: 1}
  - {id: net_liquidity, name: "Net liquidity (Fed BS - TGA - RRP, $bn)", pillar: liquidity, role: timing, direction: normal,
     formula: net_liquidity, inputs: [walcl, wtregen, rrpontsyd], lag_days: 1}
  - {id: real_ffr, name: "Real Fed Funds rate", pillar: liquidity, role: timing, direction: invert,
     formula: real_rate, inputs: [fedfunds, cpilfesl], lag_days: 14}
  - {id: curve_10y2y, name: "10Y-2Y spread", pillar: liquidity, role: timing, direction: invert, series: t10y2y, lag_days: 1}
  - {id: curve_10y3m, name: "10Y-3M spread", pillar: liquidity, role: timing, direction: invert, series: t10y3m, lag_days: 1}
  # ---- Pillar D: sentiment ----
  - {id: vix, name: "VIX", pillar: sentiment, role: timing, direction: invert, series: vixcls, lag_days: 1}
  - {id: btc_yoy, name: "Bitcoin YoY %", pillar: sentiment, role: timing, direction: normal,
     formula: yoy, inputs: [btcusd], lag_days: 1}
  # ---- Pillar E: macro stress & breadth ----
  - {id: sahm, name: "Sahm rule gap", pillar: macro, role: confirmation, direction: normal, series: sahmrealtime, lag_days: 35}
  - {id: cfnai_act, name: "CFNAI activity (weak = stress)", pillar: macro, role: confirmation, direction: invert, series: cfnai, lag_days: 25}
  - {id: spx_200dma_dist, name: "S&P 500 distance from 200-DMA %", pillar: macro, role: confirmation, direction: invert,
     formula: dma_distance, inputs: [spx], lag_days: 1}
  - {id: rsp_spy_breadth, name: "Breadth: RSP/SPY vs its 200-DMA %", pillar: macro, role: timing, direction: invert,
     formula: ratio_dma_distance, inputs: [rsp, spy], lag_days: 1}
  - {id: dollar_spliced, name: "Trade-weighted dollar (spliced)", pillar: macro, role: confirmation, direction: normal,
     formula: splice, inputs: [dtwexbgs, dtwexm], lag_days: 1}
```

- [ ] **Step 4: Write `config/thresholds.yaml`**

```yaml
regime_bands:   # ascending upper bounds; last band has bound 100
  - {name: cool,        upper: 40}
  - {name: warm,        upper: 70}
  - {name: frothy,      upper: 85}
  - {name: bubble_risk, upper: 100}

score_start: "1990-01-01"   # first date scores are computed for

alerts:
  pillar_extreme_level: 90
  cooldown_days: 7
```

- [ ] **Step 5: Write the failing tests** — `tests/test_registry.py`

```python
import pytest
from pipeline.registry import load_registry, load_thresholds


def test_registry_loads_and_counts():
    reg = load_registry()
    assert len(reg.series) == 23
    assert len(reg.indicators) == 18
    assert abs(sum(reg.pillar_weights.values()) - 1.0) < 1e-9
    assert set(reg.pillar_weights) == {"valuation", "leverage", "liquidity", "sentiment", "macro"}


def test_indicator_references_resolve():
    reg = load_registry()
    ids = set(reg.series_by_id)
    for ind in reg.indicators:
        if ind.series is not None:
            assert ind.series in ids, ind.id
            assert ind.formula is None and ind.inputs is None
        else:
            assert ind.formula is not None
            for inp in ind.inputs:
                assert inp in ids, f"{ind.id} input {inp}"


def test_enums_valid():
    reg = load_registry()
    for ind in reg.indicators:
        assert ind.direction in ("normal", "invert")
        assert ind.role in ("timing", "magnitude", "confirmation")
        assert ind.pillar in reg.pillar_weights
    for s in reg.series:
        assert s.source in ("fred", "stooq")
        assert s.frequency in ("daily", "weekly", "monthly", "quarterly")


def test_unique_ids():
    reg = load_registry()
    sids = [s.id for s in reg.series]
    iids = [i.id for i in reg.indicators]
    assert len(sids) == len(set(sids))
    assert len(iids) == len(set(iids))


def test_thresholds_load():
    th = load_thresholds()
    assert th["regime_bands"][-1]["upper"] == 100
    assert th["alerts"]["cooldown_days"] == 7


def test_bad_registry_rejected(tmp_path):
    bad = tmp_path / "registry.yaml"
    bad.write_text(
        "pillar_weights: {valuation: 1.0}\n"
        "series: []\n"
        "indicators:\n"
        "  - {id: x, name: X, pillar: valuation, role: timing, direction: up, series: missing, lag_days: 1}\n"
    )
    with pytest.raises(ValueError):
        load_registry(bad)
```

- [ ] **Step 6: Install and run tests to verify they fail**

Run: `pip install -e '.[dev]' && pytest tests/test_registry.py -q`
Expected: FAIL — `ModuleNotFoundError` / `ImportError` on `pipeline.registry`.

- [ ] **Step 7: Write `pipeline/registry.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from pipeline import paths

VALID_SOURCES = ("fred", "stooq")
VALID_FREQ = ("daily", "weekly", "monthly", "quarterly")
VALID_DIRECTION = ("normal", "invert")
VALID_ROLE = ("timing", "magnitude", "confirmation")


@dataclass(frozen=True)
class Series:
    id: str
    source: str
    source_id: str
    frequency: str
    staleness_budget_days: int
    revision_window_days: int
    lag_days: int


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


@dataclass
class Registry:
    series: list[Series]
    indicators: list[Indicator]
    pillar_weights: dict[str, float]
    series_by_id: dict[str, Series] = field(init=False)

    def __post_init__(self) -> None:
        self.series_by_id = {s.id: s for s in self.series}


def load_registry(path: Path | None = None) -> Registry:
    raw = yaml.safe_load((path or paths.CONFIG / "registry.yaml").read_text())
    series = [Series(**s) for s in raw["series"]]
    indicators = [
        Indicator(**{**i, "inputs": tuple(i["inputs"]) if "inputs" in i else None})
        for i in raw["indicators"]
    ]
    reg = Registry(series=series, indicators=indicators, pillar_weights=raw["pillar_weights"])
    _validate(reg)
    return reg


def load_thresholds(path: Path | None = None) -> dict:
    return yaml.safe_load((path or paths.CONFIG / "thresholds.yaml").read_text())


def _validate(reg: Registry) -> None:
    errors: list[str] = []
    sids = [s.id for s in reg.series]
    if len(sids) != len(set(sids)):
        errors.append("duplicate series ids")
    iids = [i.id for i in reg.indicators]
    if len(iids) != len(set(iids)):
        errors.append("duplicate indicator ids")
    if abs(sum(reg.pillar_weights.values()) - 1.0) > 1e-9:
        errors.append("pillar weights must sum to 1.0")
    for s in reg.series:
        if s.source not in VALID_SOURCES:
            errors.append(f"{s.id}: bad source {s.source}")
        if s.frequency not in VALID_FREQ:
            errors.append(f"{s.id}: bad frequency {s.frequency}")
    known = set(sids)
    for i in reg.indicators:
        if i.direction not in VALID_DIRECTION:
            errors.append(f"{i.id}: bad direction {i.direction}")
        if i.role not in VALID_ROLE:
            errors.append(f"{i.id}: bad role {i.role}")
        if i.pillar not in reg.pillar_weights:
            errors.append(f"{i.id}: unknown pillar {i.pillar}")
        if (i.series is None) == (i.formula is None):
            errors.append(f"{i.id}: exactly one of series/formula required")
        if i.series is not None and i.series not in known:
            errors.append(f"{i.id}: unknown series {i.series}")
        if i.formula is not None:
            for inp in i.inputs or ():
                if inp not in known:
                    errors.append(f"{i.id}: unknown input {inp}")
    if errors:
        raise ValueError("; ".join(errors))
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_registry.py -q`
Expected: 6 passed.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml pipeline tests config
git commit -m "feat: project scaffolding, config registry, typed loader

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Raw-CSV store (append-mostly) and freshness state

**Files:**
- Create: `pipeline/store.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `pipeline.paths`
- Produces:
  - `read_series(series_id: str) -> pd.Series` — empty float Series (DatetimeIndex) if file absent
  - `write_series(series_id: str, s: pd.Series) -> None` — writes `data/raw/<id>.csv` with header `date,value`
  - `merge_observations(existing: pd.Series, fetched: pd.Series, revision_window_days: int) -> tuple[pd.Series, int]` — returns (merged, n_changed); enforces append-mostly rule
  - `load_freshness() -> dict`, `save_freshness(d: dict) -> None` — `data/state/freshness.json`, shape `{series_id: {"last_fetch": iso, "fetch_ok": bool, "last_obs": "YYYY-MM-DD"|None, "error": str|None}}`

- [ ] **Step 1: Write the failing tests** — `tests/test_store.py`

```python
import pandas as pd
import pytest

from pipeline import store


def s(pairs):
    idx = pd.to_datetime([p[0] for p in pairs])
    return pd.Series([float(p[1]) for p in pairs], index=idx)


def test_merge_appends_new_dates():
    existing = s([("2026-01-01", 1.0), ("2026-01-02", 2.0)])
    fetched = s([("2026-01-01", 1.0), ("2026-01-02", 2.0), ("2026-01-03", 3.0)])
    merged, changed = store.merge_observations(existing, fetched, revision_window_days=0)
    assert list(merged.values) == [1.0, 2.0, 3.0]
    assert changed == 1


def test_merge_rewrites_inside_revision_window():
    existing = s([("2026-01-01", 1.0), ("2026-03-01", 2.0)])
    fetched = s([("2026-01-01", 9.0), ("2026-03-01", 2.5)])
    merged, changed = store.merge_observations(existing, fetched, revision_window_days=30)
    # 2026-03-01 is within 30d of last stored obs (2026-03-01) -> rewritten;
    # 2026-01-01 is older -> stored value kept.
    assert merged["2026-01-01"] == 1.0
    assert merged["2026-03-01"] == 2.5
    assert changed == 1


def test_merge_never_deletes_stored_rows():
    existing = s([("2026-01-01", 1.0), ("2026-01-02", 2.0)])
    fetched = s([("2026-01-02", 2.0)])  # source dropped a row
    merged, changed = store.merge_observations(existing, fetched, revision_window_days=365)
    assert "2026-01-01" in merged.index.strftime("%Y-%m-%d")
    assert changed == 0


def test_merge_empty_existing():
    fetched = s([("2026-01-01", 1.0)])
    merged, changed = store.merge_observations(pd.Series(dtype=float), fetched, 0)
    assert changed == 1 and len(merged) == 1


def test_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(store.paths, "DATA_RAW", tmp_path)
    data = s([("2026-01-01", 1.5), ("2026-01-02", 2.5)])
    store.write_series("demo", data)
    back = store.read_series("demo")
    assert back.name == "demo"
    pd.testing.assert_index_equal(back.index, data.index)
    assert list(back.values) == [1.5, 2.5]
    assert store.read_series("missing").empty


def test_freshness_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path)
    d = {"demo": {"last_fetch": "2026-07-05T00:00:00Z", "fetch_ok": True, "last_obs": "2026-07-04", "error": None}}
    store.save_freshness(d)
    assert store.load_freshness() == d
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path / "nope")
    assert store.load_freshness() == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_store.py -q`
Expected: FAIL — `ImportError: cannot import name 'store'`.

- [ ] **Step 3: Write `pipeline/store.py`**

```python
from __future__ import annotations

import json

import pandas as pd

from pipeline import paths


def read_series(series_id: str) -> pd.Series:
    fp = paths.DATA_RAW / f"{series_id}.csv"
    if not fp.exists():
        return pd.Series(dtype=float, name=series_id)
    df = pd.read_csv(fp, parse_dates=["date"])
    s = pd.Series(df["value"].to_numpy(dtype=float), index=pd.DatetimeIndex(df["date"]), name=series_id)
    return s.sort_index()


def write_series(series_id: str, s: pd.Series) -> None:
    paths.DATA_RAW.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({"date": s.index.strftime("%Y-%m-%d"), "value": s.to_numpy()})
    df.to_csv(paths.DATA_RAW / f"{series_id}.csv", index=False)


def merge_observations(
    existing: pd.Series, fetched: pd.Series, revision_window_days: int
) -> tuple[pd.Series, int]:
    """Append-mostly merge. New dates are appended; dates within
    revision_window_days of the last stored observation may be rewritten;
    older stored values are kept even if the source restates them.
    Stored rows are never deleted."""
    fetched = fetched.dropna().sort_index()
    if existing.empty:
        return fetched, len(fetched)
    cutoff = existing.index.max() - pd.Timedelta(days=revision_window_days)
    merged = existing.copy()
    changed = 0
    for dt, val in fetched.items():
        if dt in merged.index:
            if dt >= cutoff and merged[dt] != val:
                merged[dt] = val
                changed += 1
        elif dt > existing.index.max() or dt >= cutoff:
            merged[dt] = val
            changed += 1
        # dates older than cutoff and not stored: ignored (history is frozen)
    merged = merged.sort_index()
    merged.name = existing.name or fetched.name
    return merged, changed


def load_freshness() -> dict:
    fp = paths.DATA_STATE / "freshness.json"
    if not fp.exists():
        return {}
    return json.loads(fp.read_text())


def save_freshness(d: dict) -> None:
    paths.DATA_STATE.mkdir(parents=True, exist_ok=True)
    (paths.DATA_STATE / "freshness.json").write_text(json.dumps(d, indent=1, sort_keys=True) + "\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_store.py -q`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add pipeline/store.py tests/test_store.py
git commit -m "feat: append-mostly raw CSV store and freshness state

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: FRED fetcher

**Files:**
- Create: `pipeline/ingest/fred.py`, `tests/test_fred.py`

**Interfaces:**
- Consumes: nothing internal (pure fetcher)
- Produces: `fetch_fred(source_id: str, api_key: str) -> pd.Series` — full history, missing FRED values (`"."`) dropped; raises `RuntimeError` on empty payload, `requests.HTTPError` on HTTP failure.

- [ ] **Step 1: Write the failing tests** — `tests/test_fred.py`

```python
import json

import pandas as pd
import pytest

from pipeline.ingest import fred


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_fetch_parses_and_drops_missing(monkeypatch):
    payload = {"observations": [
        {"date": "2026-01-01", "value": "1.5"},
        {"date": "2026-01-02", "value": "."},
        {"date": "2026-01-03", "value": "2.5"},
    ]}
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured.update(params=params, timeout=timeout, url=url)
        return FakeResp(payload)

    monkeypatch.setattr(fred.requests, "get", fake_get)
    s = fred.fetch_fred("T10Y3M", "KEY")
    assert list(s.values) == [1.5, 2.5]
    assert s.index[0] == pd.Timestamp("2026-01-01")
    assert captured["params"]["series_id"] == "T10Y3M"
    assert captured["params"]["api_key"] == "KEY"
    assert captured["timeout"] == 30


def test_fetch_empty_raises(monkeypatch):
    monkeypatch.setattr(fred.requests, "get", lambda *a, **k: FakeResp({"observations": []}))
    with pytest.raises(RuntimeError):
        fred.fetch_fred("XXX", "KEY")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_fred.py -q`
Expected: FAIL — `ImportError` on `pipeline.ingest.fred`.

- [ ] **Step 3: Write `pipeline/ingest/fred.py`**

```python
from __future__ import annotations

import pandas as pd
import requests

API_URL = "https://api.stlouisfed.org/fred/series/observations"


def fetch_fred(source_id: str, api_key: str) -> pd.Series:
    resp = requests.get(
        API_URL,
        params={
            "series_id": source_id,
            "api_key": api_key,
            "file_type": "json",
            "limit": 100000,
        },
        timeout=30,
    )
    resp.raise_for_status()
    obs = resp.json().get("observations", [])
    dates, values = [], []
    for o in obs:
        if o["value"] == ".":
            continue
        dates.append(o["date"])
        values.append(float(o["value"]))
    if not values:
        raise RuntimeError(f"FRED returned no observations for {source_id}")
    return pd.Series(values, index=pd.to_datetime(dates), name=source_id).sort_index()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_fred.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add pipeline/ingest/fred.py tests/test_fred.py
git commit -m "feat: FRED observations fetcher

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Stooq fetcher

**Files:**
- Create: `pipeline/ingest/stooq.py`, `tests/test_stooq.py`

**Interfaces:**
- Consumes: nothing internal
- Produces: `fetch_stooq(source_id: str) -> pd.Series` — daily Close column, full history; raises `RuntimeError` when Stooq returns a non-CSV body (it answers `200` with text like `No data` or an HTML error page).

- [ ] **Step 1: Write the failing tests** — `tests/test_stooq.py`

```python
import pandas as pd
import pytest

from pipeline.ingest import stooq

CSV = "Date,Open,High,Low,Close,Volume\n2026-01-02,10,11,9,10.5,100\n2026-01-03,10.5,12,10,11.0,200\n"


class FakeResp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_fetch_parses_close(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured.update(url=url, headers=headers, timeout=timeout)
        return FakeResp(CSV)

    monkeypatch.setattr(stooq.requests, "get", fake_get)
    s = stooq.fetch_stooq("^spx")
    assert list(s.values) == [10.5, 11.0]
    assert s.index[-1] == pd.Timestamp("2026-01-03")
    assert "s=%5Espx" in captured["url"] or "s=^spx" in captured["url"]
    assert captured["timeout"] == 30
    assert "Mozilla" in captured["headers"]["User-Agent"]


def test_no_data_raises(monkeypatch):
    monkeypatch.setattr(stooq.requests, "get", lambda *a, **k: FakeResp("No data"))
    with pytest.raises(RuntimeError):
        stooq.fetch_stooq("bogus")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_stooq.py -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Write `pipeline/ingest/stooq.py`**

```python
from __future__ import annotations

import io
from urllib.parse import quote

import pandas as pd
import requests

BASE = "https://stooq.com/q/d/l/?s={sym}&i=d"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) macro-monitor/0.1"}


def fetch_stooq(source_id: str) -> pd.Series:
    url = BASE.format(sym=quote(source_id))
    resp = requests.get(url, headers=UA, timeout=30)
    resp.raise_for_status()
    text = resp.text
    if not text.startswith("Date,"):
        raise RuntimeError(f"Stooq returned no data for {source_id}: {text[:80]!r}")
    df = pd.read_csv(io.StringIO(text), parse_dates=["Date"])
    s = pd.Series(df["Close"].to_numpy(dtype=float), index=pd.DatetimeIndex(df["Date"]), name=source_id)
    return s.dropna().sort_index()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_stooq.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add pipeline/ingest/stooq.py tests/test_stooq.py
git commit -m "feat: Stooq daily-close fetcher

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Derived-indicator formulas

**Files:**
- Create: `pipeline/compute/derived.py`, `tests/test_derived.py`

**Interfaces:**
- Consumes: `pipeline.registry.Indicator`
- Produces:
  - `FORMULAS: dict[str, Callable[..., pd.Series]]` with keys `ratio`, `yoy`, `net_liquidity`, `real_rate`, `dma_distance`, `ratio_dma_distance`, `splice` — each takes positional `pd.Series` args in the registry's `inputs` order
  - `build_indicator_series(ind: Indicator, raw: dict[str, pd.Series]) -> pd.Series` — returns the raw-backed series unchanged, or applies `FORMULAS[ind.formula]`
  - helper `asof_align(target_index, s) -> pd.Series` (last known value of `s` at each target date; NaN before first obs)

Semantics locked here (Task 8 and tests depend on them):
- `ratio(a, b)`: `a_asof / b_asof` evaluated on `a`'s index (numerator's native frequency).
- `yoy(s)`: percent change vs the value as-of exactly one year earlier (`DateOffset(years=1)`); NaN (dropped) for the first year.
- `net_liquidity(walcl, tga, rrp)`: on `walcl`'s index, `walcl/1000 - tga_asof - rrp_asof` (WALCL is $mn; TGA/RRP are $bn; result $bn). Missing RRP/TGA before their series start counts as 0 (pre-2003 there was no RRP facility).
- `real_rate(ff, cpi)`: on `ff`'s index, `ff - yoy(cpi)_asof`.
- `dma_distance(s)`: `(s / rolling_mean(s, 200 obs, min_periods=200) - 1) * 100`.
- `ratio_dma_distance(a, b)`: `dma_distance` of the inner-joined daily ratio `a/b`.
- `splice(primary, donor)`: at the first overlapping date, `factor = primary/donor`; result = `donor*factor` strictly before `primary`'s start, then `primary`. Raises `ValueError` if no overlap.

- [ ] **Step 1: Write the failing tests** — `tests/test_derived.py`

```python
import numpy as np
import pandas as pd
import pytest

from pipeline.compute import derived
from pipeline.registry import Indicator


def days(start, n, step_days=1):
    return pd.date_range(start, periods=n, freq=f"{step_days}D")


def test_ratio_asof_alignment():
    a = pd.Series([10.0, 20.0], index=pd.to_datetime(["2026-03-31", "2026-06-30"]))
    b = pd.Series([2.0, 4.0], index=pd.to_datetime(["2026-01-01", "2026-06-30"]))
    out = derived.FORMULAS["ratio"](a, b)
    assert out["2026-03-31"] == 5.0   # uses b as-of 2026-01-01
    assert out["2026-06-30"] == 5.0   # 20/4


def test_yoy_exact_year():
    idx = pd.to_datetime(["2025-01-31", "2025-06-30", "2026-01-31"])
    s = pd.Series([100.0, 110.0, 121.0], index=idx)
    out = derived.FORMULAS["yoy"](s)
    assert out["2026-01-31"] == pytest.approx(21.0)
    assert "2025-01-31" not in out.index  # no prior-year value


def test_net_liquidity_units_and_missing():
    walcl = pd.Series([8_000_000.0, 8_500_000.0], index=pd.to_datetime(["2002-12-18", "2026-01-07"]))
    tga = pd.Series([700.0], index=pd.to_datetime(["2026-01-06"]))
    rrp = pd.Series([500.0], index=pd.to_datetime(["2026-01-06"]))
    out = derived.FORMULAS["net_liquidity"](walcl, tga, rrp)
    assert out["2002-12-18"] == pytest.approx(8000.0)          # TGA/RRP treated as 0 pre-start
    assert out["2026-01-07"] == pytest.approx(8500.0 - 700 - 500)


def test_real_rate():
    ff = pd.Series([5.0], index=pd.to_datetime(["2026-01-31"]))
    cpi = pd.Series([100.0, 103.0], index=pd.to_datetime(["2025-01-31", "2026-01-31"]))
    out = derived.FORMULAS["real_rate"](ff, cpi)
    assert out["2026-01-31"] == pytest.approx(2.0)


def test_dma_distance():
    idx = days("2025-01-01", 210)
    s = pd.Series(100.0, index=idx)
    s.iloc[-1] = 110.0
    out = derived.FORMULAS["dma_distance"](s)
    assert len(out) == 11  # only dates with a full 200-obs window
    assert out.iloc[-1] == pytest.approx((110 / ((199 * 100 + 110) / 200) - 1) * 100)


def test_splice_scales_donor():
    donor = pd.Series([50.0, 60.0], index=pd.to_datetime(["2000-01-03", "2006-01-02"]))
    primary = pd.Series([120.0, 130.0], index=pd.to_datetime(["2006-01-02", "2026-01-02"]))
    out = derived.FORMULAS["splice"](primary, donor)
    assert out["2000-01-03"] == pytest.approx(100.0)  # 50 * (120/60)
    assert out["2006-01-02"] == 120.0
    assert out["2026-01-02"] == 130.0


def test_splice_no_overlap_raises():
    donor = pd.Series([1.0], index=pd.to_datetime(["2000-01-01"]))
    primary = pd.Series([2.0], index=pd.to_datetime(["2010-01-01"]))
    with pytest.raises(ValueError):
        derived.FORMULAS["splice"](primary, donor)


def test_build_indicator_series_raw_and_derived():
    raw = {
        "vixcls": pd.Series([15.0], index=pd.to_datetime(["2026-01-02"])),
        "m2sl": pd.Series([100.0, 105.0], index=pd.to_datetime(["2025-01-31", "2026-01-31"])),
    }
    raw_ind = Indicator(id="vix", name="VIX", pillar="sentiment", role="timing",
                        direction="invert", lag_days=1, series="vixcls")
    der_ind = Indicator(id="m2_yoy", name="M2 YoY", pillar="liquidity", role="timing",
                        direction="normal", lag_days=14, formula="yoy", inputs=("m2sl",))
    assert derived.build_indicator_series(raw_ind, raw).equals(raw["vixcls"])
    out = derived.build_indicator_series(der_ind, raw)
    assert out["2026-01-31"] == pytest.approx(5.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_derived.py -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Write `pipeline/compute/derived.py`**

```python
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.registry import Indicator


def asof_align(target_index: pd.DatetimeIndex, s: pd.Series) -> pd.Series:
    """Last known value of s at each target date (NaN before s starts)."""
    return s.sort_index().reindex(target_index, method="ffill")


def _ratio(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a / asof_align(a.index, b)).dropna()


def _yoy(s: pd.Series) -> pd.Series:
    s = s.sort_index()
    prior_dates = s.index - pd.DateOffset(years=1)
    prior = s.reindex(s.index.union(prior_dates)).sort_index().ffill().reindex(prior_dates)
    out = (s.to_numpy() / prior.to_numpy() - 1.0) * 100.0
    result = pd.Series(out, index=s.index)
    # drop points with no observation at/before one year earlier
    valid = prior_dates >= s.index[0]
    return result[valid].dropna()


def _net_liquidity(walcl: pd.Series, tga: pd.Series, rrp: pd.Series) -> pd.Series:
    tga_a = asof_align(walcl.index, tga).fillna(0.0)
    rrp_a = asof_align(walcl.index, rrp).fillna(0.0)
    return (walcl / 1000.0 - tga_a - rrp_a).dropna()


def _real_rate(ff: pd.Series, cpi: pd.Series) -> pd.Series:
    return (ff - asof_align(ff.index, _yoy(cpi))).dropna()


def _dma_distance(s: pd.Series) -> pd.Series:
    ma = s.rolling(200, min_periods=200).mean()
    return ((s / ma - 1.0) * 100.0).dropna()


def _ratio_dma_distance(a: pd.Series, b: pd.Series) -> pd.Series:
    joined = pd.concat([a, b], axis=1, join="inner")
    return _dma_distance(joined.iloc[:, 0] / joined.iloc[:, 1])


def _splice(primary: pd.Series, donor: pd.Series) -> pd.Series:
    primary, donor = primary.sort_index(), donor.sort_index()
    overlap = donor.index.intersection(primary.index)
    if overlap.empty:
        raise ValueError("splice: no overlapping dates between primary and donor")
    anchor = overlap[0]
    factor = primary[anchor] / donor[anchor]
    pre = donor[donor.index < primary.index[0]] * factor
    return pd.concat([pre, primary]).sort_index()


FORMULAS = {
    "ratio": _ratio,
    "yoy": _yoy,
    "net_liquidity": _net_liquidity,
    "real_rate": _real_rate,
    "dma_distance": _dma_distance,
    "ratio_dma_distance": _ratio_dma_distance,
    "splice": _splice,
}


def build_indicator_series(ind: Indicator, raw: dict[str, pd.Series]) -> pd.Series:
    if ind.series is not None:
        return raw[ind.series]
    args = [raw[i] for i in ind.inputs]
    out = FORMULAS[ind.formula](*args)
    out.name = ind.id
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_derived.py -q`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add pipeline/compute/derived.py tests/test_derived.py
git commit -m "feat: derived-indicator formula engine

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Ingest orchestrator + CLI skeleton

**Files:**
- Create: `pipeline/ingest/__init__.py` (replace empty file), `pipeline/cli.py`, `pipeline/__main__.py`, `tests/test_ingest.py`

**Interfaces:**
- Consumes: `registry.load_registry`, `store.*`, `fred.fetch_fred`, `stooq.fetch_stooq`
- Produces:
  - `run_ingest(reg: Registry, api_key: str, now: pd.Timestamp | None = None) -> dict` — fetches every series with per-series isolation, merges via `store.merge_observations`, writes CSVs, saves + returns the freshness dict
  - `stale_series(reg: Registry, freshness: dict, now: pd.Timestamp) -> list[str]` — ids whose `last_obs` is older than `staleness_budget_days` (or that have never succeeded)
  - CLI: `python -m pipeline status` (prints freshness table), `python -m pipeline run` (Phase-1 partial: ingest only — Task 8 extends it with scoring; Task 12 with alerts)

- [ ] **Step 1: Write the failing tests** — `tests/test_ingest.py`

```python
import json

import pandas as pd

import pipeline.ingest as ingest
from pipeline import store
from pipeline.registry import Registry, Series


def make_reg():
    return Registry(
        series=[
            Series("good", "fred", "GOOD", "daily", 7, 0, 1),
            Series("bad", "fred", "BAD", "daily", 7, 0, 1),
            Series("mkt", "stooq", "^mkt", "daily", 7, 0, 1),
        ],
        indicators=[],
        pillar_weights={"valuation": 1.0},
    )


def fake_fred(source_id, api_key):
    if source_id == "BAD":
        raise RuntimeError("boom")
    return pd.Series([1.0], index=pd.to_datetime(["2026-07-03"]), name=source_id)


def fake_stooq(source_id):
    return pd.Series([2.0], index=pd.to_datetime(["2026-07-02"]), name=source_id)


def test_run_ingest_isolates_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(store.paths, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path / "state")
    monkeypatch.setattr(ingest, "fetch_fred", fake_fred)
    monkeypatch.setattr(ingest, "fetch_stooq", fake_stooq)
    now = pd.Timestamp("2026-07-05")
    fresh = ingest.run_ingest(make_reg(), api_key="K", now=now)
    assert fresh["good"]["fetch_ok"] is True
    assert fresh["good"]["last_obs"] == "2026-07-03"
    assert fresh["bad"]["fetch_ok"] is False
    assert "boom" in fresh["bad"]["error"]
    assert fresh["mkt"]["fetch_ok"] is True
    assert store.read_series("good").iloc[0] == 1.0
    assert store.read_series("bad").empty
    # failure must not lose previously stored data
    assert (tmp_path / "state" / "freshness.json").exists()


def test_stale_series(tmp_path, monkeypatch):
    reg = make_reg()
    now = pd.Timestamp("2026-07-05")
    fresh = {
        "good": {"last_fetch": "x", "fetch_ok": True, "last_obs": "2026-07-03", "error": None},
        "bad": {"last_fetch": "x", "fetch_ok": False, "last_obs": None, "error": "boom"},
        "mkt": {"last_fetch": "x", "fetch_ok": True, "last_obs": "2026-06-01", "error": None},
    }
    assert ingest.stale_series(reg, fresh, now) == ["bad", "mkt"]


def test_error_strings_scrub_api_key(tmp_path, monkeypatch):
    """freshness.json is committed to a public repo; error text must never contain the key."""
    monkeypatch.setattr(store.paths, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path / "state")

    def leaky_fred(source_id, api_key):
        raise RuntimeError(f"connection to /obs?api_key={api_key} refused")

    monkeypatch.setattr(ingest, "fetch_fred", leaky_fred)
    monkeypatch.setattr(ingest, "fetch_stooq", lambda sid: pd.Series([1.0], index=pd.to_datetime(["2026-07-03"])))
    fresh = ingest.run_ingest(make_reg(), api_key="SECRETKEY123", now=pd.Timestamp("2026-07-05"))
    assert "SECRETKEY123" not in json.dumps(fresh)
    assert "***" in fresh["bad"]["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingest.py -q`
Expected: FAIL — `AttributeError` (no `run_ingest`).

- [ ] **Step 3: Write `pipeline/ingest/__init__.py`**

```python
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from pipeline import store
from pipeline.ingest.fred import fetch_fred
from pipeline.ingest.stooq import fetch_stooq
from pipeline.registry import Registry


def run_ingest(reg: Registry, api_key: str, now: pd.Timestamp | None = None) -> dict:
    now = now or pd.Timestamp(datetime.now(timezone.utc).date())
    fresh = store.load_freshness()
    for s in reg.series:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            fetched = fetch_fred(s.source_id, api_key) if s.source == "fred" else fetch_stooq(s.source_id)
            existing = store.read_series(s.id)
            merged, changed = store.merge_observations(existing, fetched, s.revision_window_days)
            if changed:
                store.write_series(s.id, merged)
            fresh[s.id] = {
                "last_fetch": stamp,
                "fetch_ok": True,
                "last_obs": merged.index.max().strftime("%Y-%m-%d"),
                "error": None,
            }
        except Exception as exc:  # per-series isolation: one failure never aborts the run
            err = f"{type(exc).__name__}: {exc}"
            if api_key:
                # freshness.json is committed to a public repo — never persist the key
                err = err.replace(api_key, "***")
            prev = fresh.get(s.id, {})
            fresh[s.id] = {
                "last_fetch": stamp,
                "fetch_ok": False,
                "last_obs": prev.get("last_obs"),
                "error": err,
            }
    store.save_freshness(fresh)
    return fresh


def stale_series(reg: Registry, freshness: dict, now: pd.Timestamp) -> list[str]:
    out = []
    for s in reg.series:
        rec = freshness.get(s.id)
        if rec is None or rec["last_obs"] is None:
            out.append(s.id)
            continue
        age = (now - pd.Timestamp(rec["last_obs"])).days
        if age > s.staleness_budget_days:
            out.append(s.id)
    return out
```

- [ ] **Step 4: Write `pipeline/cli.py` and `pipeline/__main__.py`**

`pipeline/cli.py`:

```python
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd
from dotenv import load_dotenv

from pipeline import store
from pipeline.ingest import run_ingest, stale_series
from pipeline.registry import load_registry


def _api_key() -> str:
    load_dotenv()
    key = os.environ.get("FRED_API_KEY")
    if not key:
        sys.exit("FRED_API_KEY not set (put it in .env or the environment)")
    return key


def cmd_run(args: argparse.Namespace) -> int:
    reg = load_registry()
    fresh = run_ingest(reg, api_key=_api_key())
    failed = [k for k, v in fresh.items() if not v["fetch_ok"]]
    print(f"ingest: {len(reg.series) - len(failed)}/{len(reg.series)} series ok"
          + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    reg = load_registry()
    fresh = store.load_freshness()
    now = pd.Timestamp.utcnow().tz_localize(None).normalize()
    stale = set(stale_series(reg, fresh, now))
    for s in reg.series:
        rec = fresh.get(s.id, {})
        flag = "STALE" if s.id in stale else "ok"
        print(f"{s.id:16} {rec.get('last_obs') or '-':12} {flag}")
    return 1 if stale else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run").set_defaults(fn=cmd_run)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    args = p.parse_args(argv)
    return args.fn(args)
```

`pipeline/__main__.py`:

```python
import sys

from pipeline.cli import main

sys.exit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_ingest.py -q && pytest -q`
Expected: 2 passed; full suite green.

- [ ] **Step 6: First real ingest (live network, uses `.env`)**

Run: `python -m pipeline run && python -m pipeline status`
Expected: `ingest: 23/23 series ok` (or ≥21/23 — Stooq occasionally hiccups; rerun once if so), then a status table with no `STALE` rows except possibly `dtwexm` (discontinued donor — its budget of 36500 keeps it `ok`). `data/raw/` now holds 23 CSVs (~4–6 MB total).

- [ ] **Step 7: Commit (code AND first data snapshot)**

```bash
git add pipeline tests data
git commit -m "feat: ingest orchestrator with per-series isolation, CLI, first data snapshot

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Percentile engine

**Files:**
- Create: `pipeline/compute/percentiles.py`, `tests/test_percentiles.py`

**Interfaces:**
- Consumes: nothing internal (pure functions on `pd.Series`)
- Produces:
  - `MIN_HISTORY_DAYS = 3652`
  - `expanding_percentile(s: pd.Series) -> pd.Series` — each value's percentile (0–100) within all history up to and including that date
  - `rolling20y_percentile(s: pd.Series, frequency: str) -> pd.Series` — percentile within a trailing 20-year observation window (per-frequency counts), NaN until the window holds ≥10 years of observations
  - `qualifying_mask(s: pd.Series) -> pd.Series` — bool; True where `date - s.index[0] >= MIN_HISTORY_DAYS` (the ≥10y gate)
  - `froth(pct: pd.Series, direction: str) -> pd.Series` — identity for `"normal"`, `100 - pct` for `"invert"`
  - `expanding_zscore(s: pd.Series) -> pd.Series`
  - `WINDOW_20Y = {"daily": 5040, "weekly": 1040, "monthly": 240, "quarterly": 80}` and `MIN_OBS_10Y = {"daily": 2520, "weekly": 520, "monthly": 120, "quarterly": 40}`

- [ ] **Step 1: Write the failing tests** — `tests/test_percentiles.py`

```python
import numpy as np
import pandas as pd
import pytest

from pipeline.compute import percentiles as pct


def monthly(n, values=None, start="2000-01-31"):
    idx = pd.date_range(start, periods=n, freq="ME")
    vals = values if values is not None else np.arange(1.0, n + 1)
    return pd.Series(vals, index=idx)


def test_expanding_percentile_monotonic_series():
    s = monthly(5)
    out = pct.expanding_percentile(s)
    assert out.iloc[0] == pytest.approx(100.0)   # only obs -> rank 1/1
    assert out.iloc[-1] == pytest.approx(100.0)  # strictly increasing -> always the max
    s2 = monthly(5, values=[5.0, 4.0, 3.0, 2.0, 1.0])
    assert pct.expanding_percentile(s2).iloc[-1] == pytest.approx(20.0)  # min of 5 -> 1/5


def test_qualifying_mask_10y():
    s = monthly(121)  # Jan 2000 .. Jan 2010 month-ends
    mask = pct.qualifying_mask(s)
    assert not mask.iloc[0]
    assert not mask.iloc[100]
    assert mask.iloc[-1]  # 2010-01-31 is >= 10y after 2000-01-31


def test_rolling20y_needs_10y_of_obs():
    s = monthly(130)
    out = pct.rolling20y_percentile(s, "monthly")
    assert out.iloc[:119].isna().all()   # < 120 obs -> NaN
    assert not np.isnan(out.iloc[119])   # 120th obs -> defined
    assert out.iloc[-1] == pytest.approx(100.0)


def test_rolling20y_window_slides():
    # 21y of monthly data: first year eventually leaves the window
    vals = np.r_[np.full(12, 1000.0), np.arange(1.0, 241.0)]  # huge first year, then rising
    s = monthly(252, values=vals)
    out = pct.rolling20y_percentile(s, "monthly")
    # by the last obs the window is the trailing 240 obs = [13th..252nd];
    # the huge first year is gone, and the last value is the window max
    assert out.iloc[-1] == pytest.approx(100.0)


def test_froth_direction():
    p = pd.Series([10.0, 90.0])
    assert list(pct.froth(p, "normal")) == [10.0, 90.0]
    assert list(pct.froth(p, "invert")) == [90.0, 10.0]


def test_expanding_zscore():
    s = monthly(3, values=[1.0, 2.0, 3.0])
    z = pct.expanding_zscore(s)
    assert z.iloc[-1] == pytest.approx(1.0)  # (3-2)/1 with ddof=1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_percentiles.py -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Write `pipeline/compute/percentiles.py`**

```python
from __future__ import annotations

import pandas as pd

MIN_HISTORY_DAYS = 3652  # 10 years

WINDOW_20Y = {"daily": 5040, "weekly": 1040, "monthly": 240, "quarterly": 80}
MIN_OBS_10Y = {"daily": 2520, "weekly": 520, "monthly": 120, "quarterly": 40}


def expanding_percentile(s: pd.Series) -> pd.Series:
    return s.expanding().rank(pct=True) * 100.0


def rolling20y_percentile(s: pd.Series, frequency: str) -> pd.Series:
    return s.rolling(WINDOW_20Y[frequency], min_periods=MIN_OBS_10Y[frequency]).rank(pct=True) * 100.0


def qualifying_mask(s: pd.Series) -> pd.Series:
    if s.empty:
        return pd.Series(dtype=bool)
    return pd.Series((s.index - s.index[0]).days >= MIN_HISTORY_DAYS, index=s.index)


def froth(pct: pd.Series, direction: str) -> pd.Series:
    return pct if direction == "normal" else 100.0 - pct


def expanding_zscore(s: pd.Series) -> pd.Series:
    mean = s.expanding().mean()
    std = s.expanding().std(ddof=1)
    return (s - mean) / std
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_percentiles.py -q`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add pipeline/compute/percentiles.py tests/test_percentiles.py
git commit -m "feat: dual-window percentile engine with 10y gate

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Pillar/composite scores, regime bands, full `pipeline run`

**Files:**
- Create: `pipeline/compute/scores.py`, `tests/test_scores.py`
- Modify: `pipeline/cli.py` (extend `cmd_run`, `cmd_status`)

**Interfaces:**
- Consumes: `derived.build_indicator_series`, `derived.asof_align`, `percentiles.*`, `registry.Registry`, `store`
- Produces:
  - `@dataclass IndicatorResult: series: pd.Series; froth_full: pd.Series; froth_rolling: pd.Series; zscore_latest: float | None; frequency: str` (froth series are at native frequency, already direction-adjusted, gated)
  - `@dataclass ScoreResult: composite: pd.DataFrame` (columns `date, window, score, regime`), `pillars: pd.DataFrame` (columns `date, window, pillar, score`), `indicators: dict[str, IndicatorResult]`
  - `indicator_frequency(ind: Indicator, reg: Registry) -> str` — raw-backed: its series' frequency; derived: frequency of `inputs[0]`
  - `regime_for(score: float, bands: list[dict]) -> str`
  - `compute_scores(reg: Registry, thresholds: dict, raw: dict[str, pd.Series], now: pd.Timestamp | None = None) -> ScoreResult`
  - `append_scores(result: ScoreResult) -> tuple[int, int]` — appends only rows newer than each CSV's last date; returns (new composite rows, new pillar rows). Scores rounded to 2 decimals. Files: `data/scores/composite.csv`, `data/scores/pillars.csv`.

Scoring rules (locked; tests encode them):
1. Per indicator: native-frequency series → expanding percentile (full) and rolling-20y percentile → apply ≥10y gate (full window uses `qualifying_mask`; rolling uses its own `min_periods`) → apply `froth()` direction.
2. As-of join (ffill) each froth series onto the business-day index `bdate_range(score_start, now)`.
3. Pillar score per day = mean of its available (non-NaN) indicators.
4. Composite per day = Σ(weight × pillar) / Σ(weight of available pillars) — missing pillars are re-weighted away.
5. Rows where composite is NaN (no pillar qualified yet) are dropped.
6. `now` defaults to the max date across all raw series.

- [ ] **Step 1: Write the failing tests** — `tests/test_scores.py`

```python
import numpy as np
import pandas as pd
import pytest

from pipeline import store
from pipeline.compute import scores
from pipeline.registry import Indicator, Registry, Series

BANDS = [
    {"name": "cool", "upper": 40},
    {"name": "warm", "upper": 70},
    {"name": "frothy", "upper": 85},
    {"name": "bubble_risk", "upper": 100},
]
TH = {"regime_bands": BANDS, "score_start": "2011-01-01", "alerts": {"pillar_extreme_level": 90, "cooldown_days": 7}}


def make_reg():
    return Registry(
        series=[
            Series("up", "fred", "UP", "monthly", 45, 0, 1),
            Series("down", "fred", "DOWN", "monthly", 45, 0, 1),
            Series("young", "fred", "YOUNG", "monthly", 45, 0, 1),
        ],
        indicators=[
            Indicator("i_up", "Up", "valuation", "magnitude", "normal", 1, series="up"),
            Indicator("i_down", "Down", "leverage", "timing", "invert", 1, series="down"),
            Indicator("i_young", "Young", "sentiment", "timing", "normal", 1, series="young"),
        ],
        pillar_weights={"valuation": 0.5, "leverage": 0.3, "sentiment": 0.2},
    )


def make_raw():
    # 12+ years monthly, ending 2012-12-31
    idx = pd.date_range("2000-01-31", "2012-12-31", freq="ME")
    up = pd.Series(np.arange(1.0, len(idx) + 1), index=idx)      # always at its max -> pct 100
    down = pd.Series(-np.arange(1.0, len(idx) + 1), index=idx)   # always at its min -> pct ~0, inverted -> ~100
    young = pd.Series([1.0, 2.0], index=pd.to_datetime(["2012-11-30", "2012-12-31"]))  # <10y: excluded
    return {"up": up, "down": down, "young": young}


def test_regime_for():
    assert scores.regime_for(10.0, BANDS) == "cool"
    assert scores.regime_for(40.0, BANDS) == "warm"
    assert scores.regime_for(84.9, BANDS) == "frothy"
    assert scores.regime_for(99.0, BANDS) == "bubble_risk"


def test_compute_scores_math_and_gating():
    res = scores.compute_scores(make_reg(), TH, make_raw())
    comp_full = res.composite[res.composite.window == "full"].set_index("date")
    last = comp_full.iloc[-1]
    # i_up froth = 100, i_down froth = 100 - small; sentiment pillar absent (young gated out)
    # composite = (0.5*100 + 0.3*~99.4) / 0.8  -> > 99
    assert last["score"] > 99.0
    assert last["regime"] == "bubble_risk"
    pil = res.pillars[(res.pillars.window == "full")]
    assert set(pil.pillar.unique()) == {"valuation", "leverage"}  # sentiment never qualifies
    assert "i_young" not in res.indicators or res.indicators["i_young"].froth_full.empty
    # rolling window rows exist too
    assert (res.composite.window == "rolling20y").any()


def test_composite_reweights_missing_pillars():
    reg = make_reg()
    raw = make_raw()
    res = scores.compute_scores(reg, TH, raw)
    comp = res.composite[res.composite.window == "full"].iloc[-1]["score"]
    # equals weighted mean over available pillars only
    pil = res.pillars[(res.pillars.window == "full") & (res.pillars.date == res.composite.date.max())]
    by = dict(zip(pil.pillar, pil.score))
    expected = (0.5 * by["valuation"] + 0.3 * by["leverage"]) / 0.8
    assert comp == pytest.approx(expected, abs=0.01)


def test_append_scores_is_append_only(tmp_path, monkeypatch):
    monkeypatch.setattr(store.paths, "DATA_SCORES", tmp_path)
    res = scores.compute_scores(make_reg(), TH, make_raw())
    n1, _ = scores.append_scores(res)
    assert n1 > 0
    n2, m2 = scores.append_scores(res)  # idempotent second run
    assert n2 == 0 and m2 == 0
    df = pd.read_csv(tmp_path / "composite.csv", parse_dates=["date"])
    assert list(df.columns) == ["date", "window", "score", "regime"]
    assert df.duplicated(subset=["date", "window"]).sum() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scores.py -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Write `pipeline/compute/scores.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from pipeline import paths, store
from pipeline.compute import percentiles as pctmod
from pipeline.compute.derived import asof_align, build_indicator_series
from pipeline.registry import Indicator, Registry

WINDOWS = ("full", "rolling20y")


@dataclass
class IndicatorResult:
    series: pd.Series
    froth_full: pd.Series
    froth_rolling: pd.Series
    zscore_latest: float | None
    frequency: str


@dataclass
class ScoreResult:
    composite: pd.DataFrame
    pillars: pd.DataFrame
    indicators: dict[str, IndicatorResult]


def indicator_frequency(ind: Indicator, reg: Registry) -> str:
    sid = ind.series if ind.series is not None else ind.inputs[0]
    return reg.series_by_id[sid].frequency


def regime_for(score: float, bands: list[dict]) -> str:
    for band in bands[:-1]:
        if score < band["upper"]:
            return band["name"]
    return bands[-1]["name"]


def compute_scores(
    reg: Registry, thresholds: dict, raw: dict[str, pd.Series], now: pd.Timestamp | None = None
) -> ScoreResult:
    if now is None:
        now = max(s.index.max() for s in raw.values() if not s.empty)
    start = pd.Timestamp(thresholds["score_start"])
    daily_index = pd.bdate_range(start, now)

    indicators: dict[str, IndicatorResult] = {}
    froth_daily: dict[str, dict[str, pd.Series]] = {}
    for ind in reg.indicators:
        try:
            series = build_indicator_series(ind, raw).dropna()
        except KeyError:
            continue
        if series.empty:
            continue
        freq = indicator_frequency(ind, reg)
        gate = pctmod.qualifying_mask(series)
        pf = pctmod.froth(pctmod.expanding_percentile(series)[gate], ind.direction)
        pr = pctmod.froth(pctmod.rolling20y_percentile(series, freq).dropna(), ind.direction)
        z = pctmod.expanding_zscore(series)
        indicators[ind.id] = IndicatorResult(
            series=series,
            froth_full=pf,
            froth_rolling=pr,
            zscore_latest=None if z.dropna().empty else float(z.dropna().iloc[-1]),
            frequency=freq,
        )
        if not pf.empty or not pr.empty:
            froth_daily[ind.id] = {
                "full": asof_align(daily_index, pf) if not pf.empty else pd.Series(index=daily_index, dtype=float),
                "rolling20y": asof_align(daily_index, pr) if not pr.empty else pd.Series(index=daily_index, dtype=float),
            }

    bands = thresholds["regime_bands"]
    weights = pd.Series(reg.pillar_weights, dtype=float)
    comp_rows, pillar_rows = [], []
    for window in WINDOWS:
        cols = {}
        for pillar in reg.pillar_weights:
            members = [
                froth_daily[i.id][window]
                for i in reg.indicators
                if i.pillar == pillar and i.id in froth_daily
            ]
            if members:
                cols[pillar] = pd.concat(members, axis=1).mean(axis=1)
        if not cols:
            continue
        pillar_df = pd.DataFrame(cols)
        avail_w = pillar_df.notna().mul(weights[pillar_df.columns], axis=1).sum(axis=1)
        comp = pillar_df.mul(weights[pillar_df.columns], axis=1).sum(axis=1) / avail_w
        comp = comp.dropna()
        for dt, val in comp.items():
            comp_rows.append({"date": dt, "window": window, "score": round(float(val), 2),
                              "regime": regime_for(float(val), bands)})
        stacked = pillar_df.stack().reset_index()
        stacked.columns = ["date", "pillar", "score"]
        for r in stacked.itertuples(index=False):
            pillar_rows.append({"date": r.date, "window": window, "pillar": r.pillar,
                                "score": round(float(r.score), 2)})

    return ScoreResult(
        composite=pd.DataFrame(comp_rows, columns=["date", "window", "score", "regime"]),
        pillars=pd.DataFrame(pillar_rows, columns=["date", "window", "pillar", "score"]),
        indicators=indicators,
    )


def _append(fp, df: pd.DataFrame, key_cols: list[str]) -> int:
    fp.parent.mkdir(parents=True, exist_ok=True)
    if fp.exists():
        existing = pd.read_csv(fp, parse_dates=["date"])
        last = existing["date"].max()
        new = df[df["date"] > last]
    else:
        new = df
    if new.empty:
        return 0
    out = new.copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out.to_csv(fp, mode="a", header=not fp.exists(), index=False)
    return len(new)


def append_scores(result: ScoreResult) -> tuple[int, int]:
    n_comp = _append(paths.DATA_SCORES / "composite.csv",
                     result.composite.sort_values(["date", "window"]), ["date", "window"])
    n_pil = _append(paths.DATA_SCORES / "pillars.csv",
                    result.pillars.sort_values(["date", "window", "pillar"]), ["date", "window", "pillar"])
    return n_comp, n_pil
```

Note the `_append` helper evaluates `fp.exists()` **before** `to_csv` in the same expression order shown — implementer: capture `existed = fp.exists()` in a variable first, then `header=not existed`, because `to_csv(mode="a")` creates the file. Write it as:

```python
def _append(fp, df: pd.DataFrame, key_cols: list[str]) -> int:
    fp.parent.mkdir(parents=True, exist_ok=True)
    existed = fp.exists()
    if existed:
        existing = pd.read_csv(fp, parse_dates=["date"])
        last = existing["date"].max()
        new = df[df["date"] > last]
    else:
        new = df
    if new.empty:
        return 0
    out = new.copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out.to_csv(fp, mode="a", header=not existed, index=False)
    return len(new)
```

- [ ] **Step 4: Extend the CLI** — in `pipeline/cli.py` replace `cmd_run` and `cmd_status` with:

```python
def cmd_run(args: argparse.Namespace) -> int:
    from pipeline.compute.scores import append_scores, compute_scores
    from pipeline.registry import load_thresholds

    reg = load_registry()
    fresh = run_ingest(reg, api_key=_api_key())
    failed = [k for k, v in fresh.items() if not v["fetch_ok"]]
    print(f"ingest: {len(reg.series) - len(failed)}/{len(reg.series)} series ok"
          + (f"; failed: {', '.join(failed)}" if failed else ""))
    raw = {s.id: store.read_series(s.id) for s in reg.series}
    result = compute_scores(reg, load_thresholds(), raw)
    n_comp, n_pil = append_scores(result)
    latest = result.composite[result.composite.window == "full"].iloc[-1]
    print(f"scores: +{n_comp} composite rows, +{n_pil} pillar rows; "
          f"latest {latest['date']:%Y-%m-%d} composite={latest['score']} ({latest['regime']})")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    import pandas as pd

    reg = load_registry()
    fresh = store.load_freshness()
    now = pd.Timestamp.utcnow().tz_localize(None).normalize()
    stale = set(stale_series(reg, fresh, now))
    for s in reg.series:
        rec = fresh.get(s.id, {})
        flag = "STALE" if s.id in stale else "ok"
        print(f"{s.id:16} {rec.get('last_obs') or '-':12} {flag}")
    comp_fp = paths.DATA_SCORES / "composite.csv"
    if comp_fp.exists():
        df = pd.read_csv(comp_fp)
        last = df[df.window == "full"].iloc[-1]
        print(f"\ncomposite (full): {last['score']} ({last['regime']}) as of {last['date']}")
    return 1 if stale else 0
```

Add `from pipeline import paths, store` to the imports at the top of `cli.py` (replacing the bare `from pipeline import store`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_scores.py -q && pytest -q`
Expected: 4 passed; full suite green.

- [ ] **Step 6: Full live run and sanity-check the numbers**

Run: `python -m pipeline run && python -m pipeline status`
Expected: composite/pillars CSVs appear under `data/scores/` with rows from ~1990s (full window; earliest dates limited by indicator availability) to the current week, both windows present, and `status` prints a plausible current composite (sanity: 2026 composite should NOT be <10 or >95; if it is, inspect per-indicator froth percentiles before proceeding — a direction sign error shows up exactly here).

- [ ] **Step 7: Commit (code and scores data)**

```bash
git add pipeline tests data
git commit -m "feat: pillar/composite scoring with dual windows and regime bands

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Site JSON export

**Files:**
- Create: `pipeline/export.py`, `tests/test_export.py`
- Modify: `config/thresholds.yaml` (add `episode_peaks`), `pipeline/cli.py` (add `export` subcommand)

**Interfaces:**
- Consumes: `compute_scores`, `stale_series`, `store`, `registry`
- Produces: `export_site(reg: Registry, thresholds: dict) -> dict` — reads committed raw CSVs (works offline, no API key), recomputes scores, atomically writes `site/data/latest.json`, `history.json`, `indicators.json`; returns the latest.json payload. All floats rounded to 4 dp; **no wall-clock timestamps** — the payload's `as_of` is the max raw-observation date (deterministic for the golden test). Helper `downsample(s: pd.Series, max_points: int = 1000) -> pd.Series` (every-nth thinning, always keeps the final point).

JSON contracts (the dashboard in Task 10 codes against exactly this):

```
latest.json = {
  "as_of": "YYYY-MM-DD",
  "composite": {"full": {"date", "score", "regime"}, "rolling20y": {...}},
  "pillars": {<pillar>: {"full": score|null, "rolling20y": score|null, "weight": w,
                          "delta_1m": pts|null, "delta_3m": pts|null, "partial": bool}},
  "analogs": null,            // Phase 3 placeholder
  "sequence": null,           // Phase 3 placeholder
  "freshness": {<series_id>: {"last_obs": "YYYY-MM-DD"|null, "stale": bool}}
}
history.json = {
  "episode_peaks": ["2000-03-24", "2007-10-09", "2020-02-19", "2022-01-03"],
  "regime_bands": [{"name", "upper"}, ...],
  <window>: {"dates": [...], "composite": [...], "pillars": {<pillar>: [...aligned to dates, null-padded...]}}
}   // weekly-downsampled (last business day per week)
indicators.json = {
  <indicator_id>: {"name", "pillar", "role", "direction", "frequency",
                    "last_obs": "YYYY-MM-DD", "stale": bool,
                    "latest": {"value", "pct_full", "pct_rolling"|null, "zscore"|null},
                    "series": {"dates": [...], "values": [...]},        // ≤1000 pts
                    "pct_series": {"dates": [...], "values": [...]}}    // froth full, ≤1000 pts
}
```

`delta_1m`/`delta_3m`: pillar score today minus 21/63 business days earlier (full window). `partial`: true when the pillar has fewer scoring indicators than the registry defines for it. Indicator `stale`: its **backing raw series** (raw-backed: `ind.series`; derived: `inputs[0]`) exceeds its staleness budget relative to `as_of`.

- [ ] **Step 1: Add episode peaks to `config/thresholds.yaml`** (append at end)

```yaml
episode_peaks: ["2000-03-24", "2007-10-09", "2020-02-19", "2022-01-03"]
```

- [ ] **Step 2: Write the failing tests** — `tests/test_export.py` (reuses Task 8's fixture shapes)

```python
import json

import pandas as pd
import pytest

from pipeline import export, store
from pipeline.registry import Indicator, Registry, Series

from tests.test_scores import BANDS, TH, make_raw, make_reg  # reuse fixtures

THX = {**TH, "episode_peaks": ["2000-03-24", "2007-10-09"]}


@pytest.fixture()
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(export.paths, "SITE_DATA", tmp_path / "site_data")
    monkeypatch.setattr(store.paths, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path / "state")
    for sid, s in make_raw().items():
        store.write_series(sid, s)
    return tmp_path / "site_data"


def test_export_writes_three_files_with_contract(site):
    payload = export.export_site(make_reg(), THX)
    latest = json.loads((site / "latest.json").read_text())
    history = json.loads((site / "history.json").read_text())
    indicators = json.loads((site / "indicators.json").read_text())

    assert latest == payload
    assert latest["as_of"] == "2012-12-31"
    assert latest["composite"]["full"]["regime"] == "bubble_risk"
    assert latest["analogs"] is None and latest["sequence"] is None
    assert latest["pillars"]["valuation"]["weight"] == 0.5
    assert latest["pillars"]["sentiment"]["full"] is None      # gated out -> no score
    assert latest["freshness"]["up"]["stale"] is False

    assert history["episode_peaks"] == ["2000-03-24", "2007-10-09"]
    assert len(history["full"]["dates"]) == len(history["full"]["composite"])
    assert set(history["full"]["pillars"]) <= {"valuation", "leverage", "sentiment"}

    assert indicators["i_up"]["latest"]["pct_full"] == 100.0
    assert indicators["i_up"]["pillar"] == "valuation"
    assert len(indicators["i_up"]["series"]["dates"]) <= 1000


def test_export_deterministic(site):
    p1 = export.export_site(make_reg(), THX)
    p2 = export.export_site(make_reg(), THX)
    assert p1 == p2


def test_downsample_keeps_last():
    s = pd.Series(range(2500), index=pd.date_range("2000-01-01", periods=2500))
    out = export.downsample(s, 1000)
    assert len(out) <= 1000
    assert out.index[-1] == s.index[-1]
    assert out.iloc[-1] == s.iloc[-1]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_export.py -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 4: Write `pipeline/export.py`**

```python
from __future__ import annotations

import json
import math

import pandas as pd

from pipeline import paths, store
from pipeline.compute.scores import compute_scores
from pipeline.ingest import stale_series
from pipeline.registry import Registry


def downsample(s: pd.Series, max_points: int = 1000) -> pd.Series:
    if len(s) <= max_points:
        return s
    step = math.ceil(len(s) / max_points)
    keep = s.iloc[::step]
    if keep.index[-1] != s.index[-1]:
        keep = pd.concat([keep, s.iloc[[-1]]])
    return keep


def _r(x, nd=4):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)


def _series_json(s: pd.Series, max_points: int = 1000) -> dict:
    ds = downsample(s.dropna(), max_points)
    return {"dates": [d.strftime("%Y-%m-%d") for d in ds.index],
            "values": [_r(v) for v in ds.to_numpy()]}


def _atomic_write(fp, obj) -> None:
    fp.parent.mkdir(parents=True, exist_ok=True)
    tmp = fp.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n")
    tmp.replace(fp)


def export_site(reg: Registry, thresholds: dict) -> dict:
    raw = {s.id: store.read_series(s.id) for s in reg.series}
    result = compute_scores(reg, thresholds, raw)
    as_of = max(s.index.max() for s in raw.values() if not s.empty)
    fresh = store.load_freshness()
    stale = set(stale_series(reg, fresh, as_of))

    # ---- latest.json ----
    comp = {}
    for window in ("full", "rolling20y"):
        rows = result.composite[result.composite.window == window]
        comp[window] = None if rows.empty else {
            "date": rows.iloc[-1]["date"].strftime("%Y-%m-%d"),
            "score": _r(rows.iloc[-1]["score"], 2),
            "regime": rows.iloc[-1]["regime"],
        }
    pillars = {}
    per_pillar_total = {p: sum(1 for i in reg.indicators if i.pillar == p) for p in reg.pillar_weights}
    per_pillar_active = {p: 0 for p in reg.pillar_weights}
    for ind in reg.indicators:
        r = result.indicators.get(ind.id)
        if r is not None and not r.froth_full.empty:
            per_pillar_active[ind.pillar] += 1
    for p, w in reg.pillar_weights.items():
        rows = result.pillars[(result.pillars.pillar == p)]
        entry = {"weight": w, "partial": per_pillar_active[p] < per_pillar_total[p]}
        for window in ("full", "rolling20y"):
            wr = rows[rows.window == window].sort_values("date")
            entry[window] = _r(wr.iloc[-1]["score"], 2) if not wr.empty else None
        full_rows = rows[rows.window == "full"].sort_values("date")
        for label, nback in (("delta_1m", 21), ("delta_3m", 63)):
            entry[label] = (
                _r(full_rows.iloc[-1]["score"] - full_rows.iloc[-1 - nback]["score"], 2)
                if len(full_rows) > nback else None
            )
        pillars[p] = entry
    latest = {
        "as_of": as_of.strftime("%Y-%m-%d"),
        "composite": comp,
        "pillars": pillars,
        "analogs": None,
        "sequence": None,
        "freshness": {
            s.id: {"last_obs": (raw[s.id].index.max().strftime("%Y-%m-%d") if not raw[s.id].empty else None),
                    "stale": s.id in stale}
            for s in reg.series
        },
    }

    # ---- history.json (weekly downsample) ----
    history: dict = {
        "episode_peaks": thresholds.get("episode_peaks", []),
        "regime_bands": thresholds["regime_bands"],
    }
    for window in ("full", "rolling20y"):
        cw = result.composite[result.composite.window == window].set_index("date")
        if cw.empty:
            continue
        weekly = cw["score"].resample("W-FRI").last().dropna()
        pw = {}
        for p in reg.pillar_weights:
            rows = result.pillars[(result.pillars.window == window) & (result.pillars.pillar == p)]
            if rows.empty:
                continue
            aligned = rows.set_index("date")["score"].resample("W-FRI").last().reindex(weekly.index)
            pw[p] = [_r(v, 2) for v in aligned.to_numpy()]
        history[window] = {
            "dates": [d.strftime("%Y-%m-%d") for d in weekly.index],
            "composite": [_r(v, 2) for v in weekly.to_numpy()],
            "pillars": pw,
        }

    # ---- indicators.json ----
    indicators = {}
    for ind in reg.indicators:
        r = result.indicators.get(ind.id)
        if r is None:
            continue
        backing = ind.series if ind.series is not None else ind.inputs[0]
        indicators[ind.id] = {
            "name": ind.name, "pillar": ind.pillar, "role": ind.role,
            "direction": ind.direction, "frequency": r.frequency,
            "last_obs": r.series.index.max().strftime("%Y-%m-%d"),
            "stale": backing in stale,
            "latest": {
                "value": _r(r.series.iloc[-1]),
                "pct_full": _r(r.froth_full.iloc[-1], 2) if not r.froth_full.empty else None,
                "pct_rolling": _r(r.froth_rolling.iloc[-1], 2) if not r.froth_rolling.empty else None,
                "zscore": _r(r.zscore_latest, 2),
            },
            "series": _series_json(r.series),
            "pct_series": _series_json(r.froth_full),
        }

    _atomic_write(paths.SITE_DATA / "latest.json", latest)
    _atomic_write(paths.SITE_DATA / "history.json", history)
    _atomic_write(paths.SITE_DATA / "indicators.json", indicators)
    return latest
```

- [ ] **Step 5: Add the CLI subcommand** — in `pipeline/cli.py` add:

```python
def cmd_export(args: argparse.Namespace) -> int:
    from pipeline.export import export_site
    from pipeline.registry import load_thresholds

    reg = load_registry()
    latest = export_site(reg, load_thresholds())
    print(f"export: site/data written, as_of {latest['as_of']}, "
          f"composite {latest['composite']['full']['score']} ({latest['composite']['full']['regime']})")
    return 0
```

and register it in `main()`: `sub.add_parser("export").set_defaults(fn=cmd_export)`.

- [ ] **Step 6: Run tests, then a live export**

Run: `pytest -q && python -m pipeline export && ls -la site/data && python -c "import json; d=json.load(open('site/data/latest.json')); print(d['composite']['full'], list(d['pillars']))"`
Expected: suite green; three JSON files (few hundred KB total); a plausible composite dict and 5 pillar keys.

- [ ] **Step 7: Commit**

```bash
git add pipeline tests config site/data
git commit -m "feat: site JSON export (latest/history/indicators), offline-capable

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: Static dashboard (views 1–3 & 6 + Phase-3 placeholders)

**Files:**
- Create: `site/index.html`, `site/assets/style.css`, `site/assets/app.js`, `site/assets/plotly-finance.min.js` (vendored), `site/.nojekyll`

**Interfaces:**
- Consumes: the three JSON contracts from Task 9, verbatim.
- Produces: the public dashboard. No build step; ES2020 vanilla JS.

- [ ] **Step 1: Vendor the Plotly finance partial bundle**

```bash
curl -fsSL https://cdn.jsdelivr.net/npm/plotly.js-finance-dist-min@2.35.2/plotly-finance.min.js -o site/assets/plotly-finance.min.js
touch site/.nojekyll
ls -la site/assets   # expect ~1.3 MB bundle
```

(The finance bundle includes `scatter`, `bar`, and `indicator` — everything Phase 2 renders. Phase 3's radar view will swap in a custom bundle.)

- [ ] **Step 2: Write `site/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Macro Bubble Monitor</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header>
  <h1>Macro Bubble Monitor</h1>
  <div id="asof" class="muted"></div>
</header>

<section id="status" class="card-row">
  <div class="card" id="gauge-card"><div id="gauge"></div><div id="regime-label"></div></div>
  <div class="card placeholder" id="analog-card">
    <h3>Closest crisis analog</h3><p class="muted">Available in Phase 3 (episode library)</p>
  </div>
  <div class="card placeholder" id="sequence-card">
    <h3>Pre-crisis sequence</h3><p class="muted">Available in Phase 3 (sequencing engine)</p>
  </div>
</section>

<section class="card">
  <div class="card-head"><h2>Pillars</h2><span class="muted">score 0–100 · Δ1m / Δ3m</span></div>
  <div id="pillars"></div>
</section>

<section class="card">
  <div class="card-head">
    <h2>Score history</h2>
    <label class="toggle"><input type="checkbox" id="window-toggle"> rolling 20y window</label>
  </div>
  <div id="history"></div>
</section>

<section class="card">
  <div class="card-head">
    <h2>Indicator drill-down</h2>
    <select id="indicator-picker"></select>
  </div>
  <div id="indicator-meta"></div>
  <div id="indicator-raw"></div>
  <div id="indicator-pct"></div>
</section>

<footer class="muted">Monitoring context, not a trading signal. Data: FRED, Stooq, public sources.
  <a href="https://github.com/JungOhLee/macro-monitoring">source</a></footer>

<script src="assets/plotly-finance.min.js"></script>
<script src="assets/app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Write `site/assets/style.css`**

```css
:root { --bg:#12151c; --card:#1b2029; --text:#e6e9ef; --muted:#8b93a3; --line:#2a3140;
        --cool:#4caf7d; --warm:#e0b83c; --frothy:#e07b3c; --bubble:#d64545; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font:15px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif; padding:0 16px 40px; }
header { display:flex; justify-content:space-between; align-items:baseline; padding:18px 4px; }
h1 { font-size:1.3rem; margin:0; } h2 { font-size:1.05rem; margin:0; } h3 { margin:0 0 6px; }
.muted { color:var(--muted); font-size:.85rem; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px;
        padding:14px; margin-bottom:16px; }
.card-row { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
            gap:16px; margin-bottom:16px; }
.card-row .card { margin-bottom:0; }
.card-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
.placeholder { opacity:.65; }
#regime-label { text-align:center; font-weight:600; font-size:1.05rem; }
.pillar-row { display:grid; grid-template-columns:150px 1fr 110px; gap:10px;
              align-items:center; padding:7px 0; border-bottom:1px solid var(--line); }
.pillar-row:last-child { border-bottom:none; }
.bar-track { background:var(--bg); border-radius:6px; height:18px; overflow:hidden; }
.bar-fill { height:100%; border-radius:6px; }
.chip { display:inline-block; font-size:.68rem; padding:1px 7px; border-radius:9px;
        border:1px solid var(--line); color:var(--muted); margin-left:6px; }
.delta { font-size:.8rem; color:var(--muted); text-align:right; }
.badge-stale { color:var(--bubble); font-weight:600; }
select { background:var(--card); color:var(--text); border:1px solid var(--line);
         border-radius:6px; padding:4px 8px; }
.toggle { font-size:.85rem; color:var(--muted); }
footer { margin-top:24px; font-size:.8rem; }
a { color:#6ea8fe; }
@media (max-width:640px){ .pillar-row { grid-template-columns:110px 1fr 70px; } }
```

- [ ] **Step 4: Write `site/assets/app.js`**

```javascript
const REGIME = {
  cool: ["Cool", "var(--cool)", "#4caf7d"],
  warm: ["Warm", "var(--warm)", "#e0b83c"],
  frothy: ["Frothy", "var(--frothy)", "#e07b3c"],
  bubble_risk: ["Bubble risk", "var(--bubble)", "#d64545"],
};
const PILLAR_LABEL = { valuation:"Valuation", leverage:"Leverage & credit",
  liquidity:"Liquidity & monetary", sentiment:"Sentiment & speculation", macro:"Macro stress & breadth" };
const PLOT_BASE = { paper_bgcolor:"#1b2029", plot_bgcolor:"#1b2029",
  font:{color:"#e6e9ef", size:12}, margin:{l:45,r:15,t:10,b:35} };
const CFG = { displayModeBar:false, responsive:true };

let LATEST, HISTORY, INDICATORS, WIN = "full";

async function boot() {
  [LATEST, HISTORY, INDICATORS] = await Promise.all(
    ["latest", "history", "indicators"].map(n => fetch(`data/${n}.json`).then(r => r.json())));
  document.getElementById("asof").textContent = `as of ${LATEST.as_of}`;
  renderGauge(); renderPillars(); renderHistory(); initPicker();
  document.getElementById("window-toggle").addEventListener("change", e => {
    WIN = e.target.checked ? "rolling20y" : "full";
    renderGauge(); renderPillars(); renderHistory();
  });
}

function comp() { return LATEST.composite[WIN] || LATEST.composite.full; }

function renderGauge() {
  const c = comp();
  const [label, , hex] = REGIME[c.regime];
  Plotly.newPlot("gauge", [{
    type: "indicator", mode: "gauge+number", value: c.score,
    gauge: {
      axis: { range: [0, 100], tickvals: [0, 40, 70, 85, 100] },
      bar: { color: hex },
      steps: [
        { range: [0, 40], color: "rgba(76,175,125,.25)" },
        { range: [40, 70], color: "rgba(224,184,60,.25)" },
        { range: [70, 85], color: "rgba(224,123,60,.25)" },
        { range: [85, 100], color: "rgba(214,69,69,.3)" },
      ],
    },
  }], { ...PLOT_BASE, height: 210, margin: {l:25,r:25,t:20,b:5} }, CFG);
  document.getElementById("regime-label").innerHTML =
    `<span style="color:${hex}">${label}</span> · composite ${c.score}`;
}

function renderPillars() {
  const el = document.getElementById("pillars");
  el.innerHTML = "";
  for (const [p, d] of Object.entries(LATEST.pillars)) {
    const score = d[WIN];
    const row = document.createElement("div");
    row.className = "pillar-row";
    const deltas = [d.delta_1m, d.delta_3m]
      .map(x => x == null ? "–" : (x > 0 ? "+" : "") + x.toFixed(1)).join(" / ");
    const color = score == null ? "#555" :
      score >= 85 ? "#d64545" : score >= 70 ? "#e07b3c" : score >= 40 ? "#e0b83c" : "#4caf7d";
    row.innerHTML =
      `<div>${PILLAR_LABEL[p]}${d.partial ? '<span class="chip">partial</span>' : ""}</div>` +
      `<div class="bar-track"><div class="bar-fill" style="width:${score ?? 0}%;background:${color}"></div></div>` +
      `<div class="delta">${score == null ? "n/a" : score.toFixed(1)}<br>${deltas}</div>`;
    el.appendChild(row);
  }
}

function renderHistory() {
  const h = HISTORY[WIN];
  if (!h) return;
  const traces = [{ x: h.dates, y: h.composite, name: "Composite",
                    line: { color: "#e6e9ef", width: 2.4 } }];
  for (const [p, vals] of Object.entries(h.pillars))
    traces.push({ x: h.dates, y: vals, name: PILLAR_LABEL[p],
                  line: { width: 1 }, opacity: 0.55, visible: "legendonly" });
  const shapes = HISTORY.episode_peaks.map(d => ({
    type: "line", x0: d, x1: d, y0: 0, y1: 100, line: { color: "#d64545", width: 1, dash: "dot" } }));
  const bands = [[0,40,"rgba(76,175,125,.05)"],[40,70,"rgba(224,184,60,.05)"],
                 [70,85,"rgba(224,123,60,.06)"],[85,100,"rgba(214,69,69,.08)"]];
  for (const [y0,y1,c] of bands)
    shapes.push({ type:"rect", xref:"paper", x0:0, x1:1, y0, y1, fillcolor:c, line:{width:0} });
  Plotly.newPlot("history", traces,
    { ...PLOT_BASE, height: 340, shapes, yaxis: { range: [0, 100] },
      legend: { orientation: "h", y: -0.15 } }, CFG);
}

function initPicker() {
  const sel = document.getElementById("indicator-picker");
  const ids = Object.keys(INDICATORS).sort((a, b) =>
    INDICATORS[a].pillar.localeCompare(INDICATORS[b].pillar));
  for (const id of ids) {
    const o = document.createElement("option");
    o.value = id;
    o.textContent = `${PILLAR_LABEL[INDICATORS[id].pillar]} · ${INDICATORS[id].name}`;
    sel.appendChild(o);
  }
  sel.addEventListener("change", () => renderIndicator(sel.value));
  renderIndicator(ids[0]);
}

function renderIndicator(id) {
  const d = INDICATORS[id];
  document.getElementById("indicator-meta").innerHTML =
    `<span class="chip">${d.role}</span><span class="chip">${d.direction}</span>` +
    `<span class="chip">${d.frequency}</span>` +
    `<span class="chip">pct ${d.latest.pct_full ?? "n/a"}</span>` +
    `<span class="chip">z ${d.latest.zscore ?? "n/a"}</span>` +
    (d.stale ? ' <span class="badge-stale">STALE</span>' : "") +
    ` <span class="muted">last obs ${d.last_obs}</span>`;
  Plotly.newPlot("indicator-raw",
    [{ x: d.series.dates, y: d.series.values, name: "raw", line: { color: "#6ea8fe", width: 1.4 } }],
    { ...PLOT_BASE, height: 230, yaxis: { title: { text: "raw value", font: { size: 11 } } } }, CFG);
  Plotly.newPlot("indicator-pct",
    [{ x: d.pct_series.dates, y: d.pct_series.values, name: "froth pct", line: { color: "#e0b83c", width: 1.4 } }],
    { ...PLOT_BASE, height: 200, yaxis: { range: [0, 100] },
      shapes: [80, 90].map(y => ({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y,
                                   line: { color: "#d64545", width: 1, dash: "dot" } })) }, CFG);
}

boot().catch(e => { document.body.insertAdjacentHTML("afterbegin",
  `<div class="card" style="border-color:#d64545">Failed to load data: ${e}</div>`); });
```

- [ ] **Step 5: Verify locally**

```bash
python -m pipeline export
python -m http.server 8123 -d site &
sleep 1 && curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8123/ http://localhost:8123/data/latest.json
```

Expected: `200` twice. Then open `http://localhost:8123` in a browser (use browser tools if available in the session): gauge shows the composite with regime color; five pillar bars (valuation flagged `partial` — CAPE/PS arrive in Phase 3, and sentiment likely `partial` too); history chart shows the composite line with four red dotted crisis markers; drill-down renders raw + percentile charts for every indicator with role/direction/staleness chips. Kill the server afterward (`kill %1`).

- [ ] **Step 6: Commit**

```bash
git add site
git commit -m "feat: static dashboard - gauge, pillars, history, drill-down

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 11: GitHub Actions workflow + one-time repo setup

**Files:**
- Create: `.github/workflows/daily.yml`, `scripts/setup_repo.sh`

**Interfaces:**
- Consumes: CLI commands `run`/`export`; repo secret `FRED_API_KEY` (already set).
- Produces: scheduled daily pipeline + Pages deployment. The `alerts` step is added by Task 12.

- [ ] **Step 1: Write `.github/workflows/daily.yml`**

```yaml
name: daily

on:
  schedule:
    - cron: "17 11 * * *"   # ~06:17 ET
    - cron: "17 21 * * *"   # catch-up; pipeline is idempotent
  workflow_dispatch:
  push:
    branches: [main]

permissions:
  contents: write
  issues: write
  pages: write
  id-token: write

concurrency:
  group: daily
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -e '.[dev]'
      - run: pytest -q
      - name: Run pipeline
        if: github.event_name != 'push'
        env:
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
        run: |
          python -m pipeline run
          python -m pipeline export
      - name: Commit data
        if: github.event_name != 'push'
        run: |
          git config user.name "github-actions"
          git config user.email "github-actions@users.noreply.github.com"
          git add data site/data
          git commit -m "data: daily update" || echo "nothing to commit"
          git pull --rebase origin main
          git push
      - name: Refresh site JSON for artifact (push builds)
        if: github.event_name == 'push'
        run: python -m pipeline export || true   # tolerate empty data on very first push
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site
  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: Write `scripts/setup_repo.sh`**

```bash
#!/usr/bin/env bash
# One-time repo setup: labels + Pages source. Idempotent.
set -euo pipefail
REPO="JungOhLee/macro-monitoring"

for label in "alert:regime|d64545|Composite regime band changed" \
             "alert:pillar-valuation|e07b3c|Valuation pillar >90" \
             "alert:pillar-leverage|e07b3c|Leverage pillar >90" \
             "alert:pillar-liquidity|e07b3c|Liquidity pillar >90" \
             "alert:pillar-sentiment|e07b3c|Sentiment pillar >90" \
             "alert:pillar-macro|e07b3c|Macro pillar >90" \
             "alert:stage-1|b60205|Seq stage 1 fired" "alert:stage-2|b60205|Seq stage 2 fired" \
             "alert:stage-3|b60205|Seq stage 3 fired" "alert:stage-4|b60205|Seq stage 4 fired" \
             "alert:stage-5|b60205|Seq stage 5 fired" "alert:stage-6|b60205|Seq stage 6 fired" \
             "data-health|fbca04|Series staleness / ingest failures"; do
  IFS="|" read -r name color desc <<<"$label"
  gh label create "$name" --repo "$REPO" --color "$color" --description "$desc" --force
done

# Pages: build via Actions workflow
gh api -X POST "repos/$REPO/pages" -f build_type=workflow 2>/dev/null \
  || gh api -X PUT "repos/$REPO/pages" -f build_type=workflow
echo "setup complete"
```

- [ ] **Step 3: Run setup and push**

```bash
chmod +x scripts/setup_repo.sh && ./scripts/setup_repo.sh
git add .github scripts
git commit -m "chore: daily workflow (cron x2 + dispatch + push) and repo setup script

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push
```

Expected: 13 labels created; Pages configured; push triggers the workflow's push-path (tests + deploy, no data commit).

- [ ] **Step 4: Trigger and watch a full scheduled-path run**

```bash
gh workflow run daily.yml --repo JungOhLee/macro-monitoring
sleep 10
gh run watch --repo JungOhLee/macro-monitoring --exit-status $(gh run list --repo JungOhLee/macro-monitoring --workflow daily.yml --limit 1 --json databaseId -q '.[0].databaseId')
```

Expected: run green (build + deploy). Then verify:

```bash
git pull   # the Action's data commit, if any new observations landed
curl -s -o /dev/null -w "%{http_code}\n" https://jungohlee.github.io/macro-monitoring/
curl -s https://jungohlee.github.io/macro-monitoring/data/latest.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['as_of'], d['composite']['full'])"
```

Expected: `200` and a current composite. **The dashboard weblink is now live.**

- [ ] **Step 5: Commit any local doc tweaks and confirm clean tree**

```bash
git status --short   # expect empty
```

---

### Task 12: Alerts (labeled GitHub issues, CI-gated)

**Files:**
- Create: `pipeline/alerts.py`, `tests/test_alerts.py`
- Modify: `pipeline/cli.py` (add `alerts` subcommand), `.github/workflows/daily.yml` (add alerts step)

**Interfaces:**
- Consumes: `data/scores/*.csv`, `store.load_freshness`, `ingest.stale_series`, thresholds
- Produces:
  - `@dataclass Alert: label: str; title: str; body: str`
  - `evaluate_alerts(reg: Registry, thresholds: dict, now: pd.Timestamp) -> list[Alert]` — three rules: (1) full-window composite regime changed between the last two scored dates → `alert:regime`; (2) a pillar's full-window score crossed above `pillar_extreme_level` (prev ≤ 90 < now) → `alert:pillar-<pillar>`; (3) any stale series → one `data-health` alert naming them all.
  - `deliver(alerts: list[Alert], cooldown_days: int) -> None` — outside Actions (`GITHUB_ACTIONS` unset): print only. In Actions: skip any alert whose label has an issue created within `cooldown_days` (via `gh issue list`), else `gh issue create`.
  - CLI `python -m pipeline alerts [--test]`; `--test` sends a synthetic `data-health` test issue (works in Actions; locally prints).

- [ ] **Step 1: Write the failing tests** — `tests/test_alerts.py`

```python
import pandas as pd
import pytest

from pipeline import alerts, store
from pipeline.registry import Registry, Series

TH = {"regime_bands": [{"name": "cool", "upper": 40}, {"name": "warm", "upper": 70},
                        {"name": "frothy", "upper": 85}, {"name": "bubble_risk", "upper": 100}],
      "score_start": "1990-01-01",
      "alerts": {"pillar_extreme_level": 90, "cooldown_days": 7}}


def reg_one():
    return Registry(series=[Series("s1", "fred", "S1", "daily", 7, 0, 1)], indicators=[],
                    pillar_weights={"valuation": 1.0})


def write_scores(tmp_path, comp_rows, pillar_rows):
    (tmp_path).mkdir(parents=True, exist_ok=True)
    pd.DataFrame(comp_rows, columns=["date", "window", "score", "regime"]).to_csv(tmp_path / "composite.csv", index=False)
    pd.DataFrame(pillar_rows, columns=["date", "window", "pillar", "score"]).to_csv(tmp_path / "pillars.csv", index=False)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(alerts.paths, "DATA_SCORES", tmp_path / "scores")
    monkeypatch.setattr(store.paths, "DATA_STATE", tmp_path / "state")
    store.save_freshness({"s1": {"last_fetch": "x", "fetch_ok": True, "last_obs": "2026-07-03", "error": None}})
    return tmp_path / "scores"


def test_regime_change_and_pillar_cross(env):
    write_scores(env,
        [["2026-07-02", "full", 69.0, "warm"], ["2026-07-03", "full", 71.0, "frothy"]],
        [["2026-07-02", "full", "valuation", 89.0], ["2026-07-03", "full", "valuation", 91.0]])
    out = alerts.evaluate_alerts(reg_one(), TH, pd.Timestamp("2026-07-05"))
    labels = [a.label for a in out]
    assert "alert:regime" in labels
    assert "alert:pillar-valuation" in labels
    regime = next(a for a in out if a.label == "alert:regime")
    assert "warm" in regime.body and "frothy" in regime.title


def test_no_alerts_when_steady(env):
    write_scores(env,
        [["2026-07-02", "full", 50.0, "warm"], ["2026-07-03", "full", 51.0, "warm"]],
        [["2026-07-02", "full", "valuation", 50.0], ["2026-07-03", "full", "valuation", 51.0]])
    assert alerts.evaluate_alerts(reg_one(), TH, pd.Timestamp("2026-07-05")) == []


def test_stale_series_alert(env):
    write_scores(env,
        [["2026-07-03", "full", 50.0, "warm"]],
        [["2026-07-03", "full", "valuation", 50.0]])
    out = alerts.evaluate_alerts(reg_one(), TH, pd.Timestamp("2026-08-01"))  # s1 obs is 29d old, budget 7
    assert [a.label for a in out] == ["data-health"]
    assert "s1" in out[0].body


def test_deliver_local_prints_not_calls_gh(env, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    called = []
    monkeypatch.setattr(alerts.subprocess, "run", lambda *a, **k: called.append(a))
    alerts.deliver([alerts.Alert("alert:regime", "t", "b")], 7)
    assert called == []
    assert "alert:regime" in capsys.readouterr().out


def test_deliver_ci_respects_cooldown(env, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    calls = []

    class R:
        def __init__(self, out):
            self.stdout = out
            self.returncode = 0

    def fake_run(cmd, capture_output=True, text=True, check=False):
        calls.append(cmd)
        if "list" in cmd:
            # first label: recent issue exists; second: none
            return R("[]" if "alert:pillar-valuation" in cmd else '[{"number": 5}]')
        return R("")

    monkeypatch.setattr(alerts.subprocess, "run", fake_run)
    alerts.deliver([alerts.Alert("alert:regime", "t1", "b1"),
                    alerts.Alert("alert:pillar-valuation", "t2", "b2")], 7)
    creates = [c for c in calls if "create" in c]
    assert len(creates) == 1
    assert "alert:pillar-valuation" in " ".join(creates[0])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_alerts.py -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Write `pipeline/alerts.py`**

```python
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

import pandas as pd

from pipeline import paths, store
from pipeline.ingest import stale_series
from pipeline.registry import Registry


@dataclass
class Alert:
    label: str
    title: str
    body: str


def _last_two(df: pd.DataFrame, value_col: str) -> tuple:
    d = df.sort_values("date")
    if len(d) < 2:
        return (None, None)
    return d.iloc[-2][value_col], d.iloc[-1][value_col]


def evaluate_alerts(reg: Registry, thresholds: dict, now: pd.Timestamp) -> list[Alert]:
    out: list[Alert] = []
    comp_fp = paths.DATA_SCORES / "composite.csv"
    pil_fp = paths.DATA_SCORES / "pillars.csv"
    level = thresholds["alerts"]["pillar_extreme_level"]

    if comp_fp.exists():
        comp = pd.read_csv(comp_fp, parse_dates=["date"])
        comp = comp[comp.window == "full"]
        prev, cur = _last_two(comp, "regime")
        if prev is not None and prev != cur:
            score = comp.sort_values("date").iloc[-1]["score"]
            out.append(Alert(
                "alert:regime",
                f"Regime change: {prev} -> {cur} (composite {score})",
                f"Full-window composite moved from **{prev}** to **{cur}** "
                f"(score {score}). Dashboard: https://jungohlee.github.io/macro-monitoring/",
            ))

    if pil_fp.exists():
        pil = pd.read_csv(pil_fp, parse_dates=["date"])
        pil = pil[pil.window == "full"]
        for pillar, grp in pil.groupby("pillar"):
            prev, cur = _last_two(grp, "score")
            if prev is not None and prev <= level < cur:
                out.append(Alert(
                    f"alert:pillar-{pillar}",
                    f"Pillar extreme: {pillar} crossed {level} (now {cur})",
                    f"The **{pillar}** pillar score crossed above {level}: {prev} -> {cur}.",
                ))

    stale = stale_series(reg, store.load_freshness(), now)
    if stale:
        out.append(Alert(
            "data-health",
            f"Data health: {len(stale)} stale series",
            "Series past their staleness budget: " + ", ".join(stale),
        ))
    return out


def deliver(alerts: list[Alert], cooldown_days: int) -> None:
    in_ci = bool(os.environ.get("GITHUB_ACTIONS"))
    since = (pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=cooldown_days)).strftime("%Y-%m-%d")
    for a in alerts:
        if not in_ci:
            print(f"[alert] {a.label}: {a.title}\n        {a.body}")
            continue
        listed = subprocess.run(
            ["gh", "issue", "list", "--label", a.label, "--state", "all",
             "--search", f"created:>={since}", "--json", "number"],
            capture_output=True, text=True, check=False,
        )
        try:
            recent = json.loads(listed.stdout or "[]")
        except json.JSONDecodeError:
            recent = []
        if recent:
            print(f"[alert] cooldown active for {a.label}, skipping")
            continue
        subprocess.run(
            ["gh", "issue", "create", "--title", a.title, "--body", a.body, "--label", a.label],
            capture_output=True, text=True, check=False,
        )
        print(f"[alert] issue created: {a.label}: {a.title}")
```

- [ ] **Step 4: Add the CLI subcommand** — in `pipeline/cli.py`:

```python
def cmd_alerts(args: argparse.Namespace) -> int:
    import pandas as pd

    from pipeline.alerts import Alert, deliver, evaluate_alerts
    from pipeline.registry import load_thresholds

    th = load_thresholds()
    if args.test:
        deliver([Alert("data-health", "Test alert - please ignore",
                       "Verifying the alert email path. Close me.")], cooldown_days=0)
        return 0
    reg = load_registry()
    now = pd.Timestamp.utcnow().tz_localize(None).normalize()
    found = evaluate_alerts(reg, th, now)
    deliver(found, th["alerts"]["cooldown_days"])
    print(f"alerts: {len(found)} rule(s) fired")
    return 0
```

Register in `main()`:

```python
ap = sub.add_parser("alerts")
ap.add_argument("--test", action="store_true")
ap.set_defaults(fn=cmd_alerts)
```

- [ ] **Step 5: Wire into the workflow** — in `.github/workflows/daily.yml`, inside the `Run pipeline` step, extend the `run:` block to:

```yaml
        env:
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
          GH_TOKEN: ${{ github.token }}
        run: |
          python -m pipeline run
          python -m pipeline alerts
          python -m pipeline export
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_alerts.py -q && pytest -q`
Expected: 5 passed; suite green. Also run `python -m pipeline alerts` locally — prints (no issue created).

- [ ] **Step 7: Commit**

```bash
git add pipeline/alerts.py tests/test_alerts.py pipeline/cli.py .github
git commit -m "feat: rule-based alerts as labeled GitHub issues with cooldown

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 13: Crisis narrative draft pages

**Files:**
- Create: `episodes/dotcom.md`, `episodes/gfc.md`, `episodes/covid.md`, `episodes/postcovid.md`
- Modify: `pipeline/export.py` (add `render_episodes()`), `pipeline/cli.py` (call it in `cmd_export`), `site/index.html` (nav links)
- Test: `tests/test_episodes.py`

**Interfaces:**
- Consumes: `markdown` package, `paths.EPISODES`, `paths.SITE`
- Produces: `render_episodes() -> list[str]` — converts each `episodes/*.md` to `site/episodes/<name>.html` wrapped in the dashboard chrome; returns rendered names. Phase 3 will append auto-generated firing timelines to these pages.

- [ ] **Step 1: Write the four narrative drafts.** Each file follows the same skeleton — `# title`, `## The setup`, `## The causal chain`, `## The turn`, `## What it looked like in the indicators`, `## Lessons for the monitor`. Write these exact drafts (they are v1 content the user will edit):

`episodes/dotcom.md`:

```markdown
# Dot-com bust (peak: March 2000)

**Type: endogenous valuation bubble.** The cleanest historical example of valuation
and breadth signals working as designed.

## The setup
Five years of 20%+ annual S&P returns, retail brokerage accounts tripling, and a
new-era narrative ("the internet changes everything") that justified any price.
CAPE passed its 1929 record in 1997 and kept climbing to 44 by December 1999.
The Fed added liquidity ahead of Y2K, juicing the final melt-up.

## The causal chain
Cheap capital -> IPO mania (1999: ~480 IPOs, most unprofitable) -> index
concentration in tech (tech = 33% of S&P cap) -> valuation detached from
earnings -> Fed hikes 1999-2000 (4.75% -> 6.5%) -> marginal buyer exhausted ->
capex bust feeds back into the real economy.

## The turn
Breadth broke first: the NYSE advance-decline line peaked in April 1998, two
years before the index. The 10Y-3M curve inverted July 2000. NASDAQ peaked
March 10, 2000; the S&P went sideways until September, then fell 49% over two
years. No credit crisis - banks were fine; it was an equity-valuation event.

## What it looked like in the indicators
- Valuation pillar: extreme (>95th pct) for ~3 years before the peak - magnitude, not timing.
- Breadth divergence: 1998-2000, the classic stage-5 signal.
- Credit spreads: only widened after the peak - confirms this was not a credit bubble.
- Margin debt YoY: peaked March 2000, the month of the top.

## Lessons for the monitor
Valuation alone is years early. The tradable signal was breadth + margin-debt
rollover + curve inversion stacking on top of extreme valuation.
```

`episodes/gfc.md`:

```markdown
# Global Financial Crisis (peak: October 2007)

**Type: endogenous credit bubble.** The best case study for the leverage and
credit pillars; equity valuation was NOT extreme.

## The setup
Post-2001 the Fed held rates at 1% into a recovering economy. Housing became
the speculative asset: subprime origination tripled 2002-2006, securitization
(MBS/CDO) spread the exposure through the global banking system with 30:1
leverage, and rating agencies stamped it AAA.

## The causal chain
Low rates -> housing credit boom -> securitization amplifies and hides leverage ->
home prices stall (mid-2006) -> subprime defaults -> mark-to-market losses in
levered holders -> funding runs (Bear Stearns June 2007 funds, ABCP freeze
August 2007) -> credit contraction -> recession -> equity collapse.

## The turn
Credit turned a full year before equities: HY spreads bottomed June 2007 at
~240bp and were 200bp wider by October when the S&P made its high. The curve
had inverted in 2006 and re-steepened through 2007 - the classic stage-3
danger signal. Lending standards (SLOOS) tightened sharply from Q3 2007.
S&P fell 57% peak-to-trough; the system nearly failed in September 2008.

## What it looked like in the indicators
- CAPE was ~27 - elevated, not extreme. A valuation-only monitor missed 2007.
- Household debt/GDP: all-time high, rising 5pp/yr - the true magnitude signal.
- HY spreads: stage-4 widening began ~4 months before the equity peak.
- SLOOS: swung from loose to tightening in two quarters.

## Lessons for the monitor
Watch the credit pillar when valuation looks "fine". Spreads and lending
standards led equities by months; the sequencing was textbook stages 2-3-4.
```

`episodes/covid.md`:

```markdown
# COVID crash (peak: February 2020)

**Type: exogenous shock - the control case.** The monitor should NOT have been
flashing before this one; a system that "predicted" COVID is overfit.

## The setup
Late-cycle but unremarkable: valuations moderately high (CAPE ~31), credit
spreads tight, leverage normal, the Fed had just cut three times in 2019 after
the repo stress. No speculative mania comparable to 1999 or 2006.

## The causal chain
Pandemic -> simultaneous global sudden stop in activity -> dash-for-cash
liquidation of everything (even Treasuries sold off in mid-March) -> fastest
30% drawdown in history (22 trading days) -> unprecedented fiscal + monetary
response -> fastest recovery in history (5 months to new highs).

## The turn
There was no endogenous turn. The 2019 curve inversion "worked" only by
coincidence. Breadth, margin debt, and credit gave no meaningful advance
warning. VIX went 15 -> 82 in four weeks - pure confirmation, zero anticipation.

## What it looked like in the indicators
- Composite score in Jan 2020: mid-range. Correctly "not engaged".
- Stage sequence: stages 1-5 had not fired as a chain.
- The crash and recovery were both policy-scale events, not cycle-scale.

## Lessons for the monitor
This episode defines the false-positive test: the sequencer must stay
"not engaged" through 2019 in backtests. Exogenous shocks cannot be predicted
by froth indicators - the monitor measures vulnerability, not asteroid strikes.
```

`episodes/postcovid.md`:

```markdown
# Post-COVID froth unwind (peak: January 2022)

**Type: endogenous liquidity bubble.** The purest liquidity-and-sentiment episode;
speculation metrics hit records that 1999 never touched.

## The setup
$5T of fiscal transfers + QE at $120bn/month + rates at zero met a locked-down
population with brokerage apps. M2 grew 27% YoY (fastest ever). SPACs raised
more in 2020-21 than all prior years combined; crypto market cap went
$200bn -> $3T; margin debt rose 70% YoY into late 2021.

## The causal chain
Pandemic stimulus -> excess liquidity -> asset melt-up across every risk class ->
inflation breaks out (CPI 7% by Dec 2021) -> Fed forced to pivot (Nov 2021
taper, then fastest hiking cycle since 1980) -> liquidity drains -> longest-
duration assets (unprofitable tech, crypto, SPACs) collapse first -> index
peaks Jan 3, 2022 and falls 25%; speculative names fall 70-90%.

## The turn
Liquidity signals led: M2 growth peaked Feb 2021, margin debt YoY rolled over
from its extreme in late 2021 (stage 2), breadth deteriorated all through H2
2021 while the index made highs on mega-caps (stage 5). The Fed pivot was the
trigger; the vulnerability was a year in the making.

## What it looked like in the indicators
- Liquidity pillar: record readings through 2021, rolling over from Nov 2021.
- Sentiment pillar: crypto YoY, IPO/SPAC volume at all-time extremes.
- Valuation: high but below 2000 - again magnitude, not timing.
- HY spreads: quiet until late - this cycle's stage 4 came late because the
  shock was rate-driven, not credit-driven.

## Lessons for the monitor
Liquidity-driven bubbles end when the liquidity does: the pivot from QE to
tightening was the operative signal. Watch pillar C rollovers from extremes,
confirmed by breadth divergence.
```

- [ ] **Step 2: Write the failing test** — `tests/test_episodes.py`

```python
from pipeline import export


def test_render_episodes(tmp_path, monkeypatch):
    monkeypatch.setattr(export.paths, "EPISODES", tmp_path / "episodes")
    monkeypatch.setattr(export.paths, "SITE", tmp_path / "site")
    (tmp_path / "episodes").mkdir()
    (tmp_path / "episodes" / "demo.md").write_text("# Demo Crisis\n\nBody **bold**.\n")
    names = export.render_episodes()
    assert names == ["demo"]
    html = (tmp_path / "site" / "episodes" / "demo.html").read_text()
    assert "<h1>Demo Crisis</h1>" in html
    assert "<strong>bold</strong>" in html
    assert "../assets/style.css" in html
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_episodes.py -q`
Expected: FAIL — no `render_episodes`.

- [ ] **Step 4: Add `render_episodes` to `pipeline/export.py`**

```python
EPISODE_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} - Macro Bubble Monitor</title>
<link rel="stylesheet" href="../assets/style.css"></head>
<body><header><h1><a href="../index.html" style="text-decoration:none;color:inherit">&larr; Macro Bubble Monitor</a></h1></header>
<article class="card">{body}</article>
<footer class="muted">Monitoring context, not a trading signal.</footer>
</body></html>
"""


def render_episodes() -> list[str]:
    import markdown

    outdir = paths.SITE / "episodes"
    names = []
    for md_file in sorted(paths.EPISODES.glob("*.md")):
        text = md_file.read_text()
        title = text.splitlines()[0].lstrip("# ").strip()
        body = markdown.markdown(text)
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / f"{md_file.stem}.html").write_text(
            EPISODE_TEMPLATE.format(title=title, body=body))
        names.append(md_file.stem)
    return names
```

In `pipeline/cli.py` `cmd_export`, after `export_site(...)` add:

```python
    from pipeline.export import render_episodes
    names = render_episodes()
    print(f"episodes: rendered {', '.join(names) or 'none'}")
```

- [ ] **Step 5: Link from the dashboard** — in `site/index.html`, inside `<header>` after the `asof` div, add:

```html
  <nav class="muted">
    Crisis stories:
    <a href="episodes/dotcom.html">2000 dot-com</a> ·
    <a href="episodes/gfc.html">2007 GFC</a> ·
    <a href="episodes/covid.html">2020 COVID</a> ·
    <a href="episodes/postcovid.html">2022 unwind</a>
  </nav>
```

- [ ] **Step 6: Run tests and a local render**

Run: `pytest -q && python -m pipeline export && ls site/episodes/`
Expected: suite green; four HTML files.

- [ ] **Step 7: Commit**

```bash
git add episodes pipeline site tests/test_episodes.py
git commit -m "feat: crisis narrative draft pages rendered into the site

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 14: End-to-end validation and README

**Files:**
- Create: `README.md`
- No code changes — this task proves the whole system live.

- [ ] **Step 1: Write `README.md`**

```markdown
# Macro Bubble Monitor

**Live dashboard: https://jungohlee.github.io/macro-monitoring/**

A personal macro-economy monitor: 18 indicators across five pillars
(valuation, leverage, liquidity, sentiment, macro stress), each expressed as a
historical percentile and combined into a 0-100 composite bubble score -
updated daily by GitHub Actions, with crisis-comparison context.

- **Spec:** [`macro-bubble-monitor-spec.md`](macro-bubble-monitor-spec.md) (v2) +
  [validated design](docs/superpowers/specs/2026-07-05-macro-monitor-design.md)
- **How it works:** Actions cron -> FRED/Stooq ingest -> percentile scoring ->
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
```

- [ ] **Step 2: Push and watch the full scheduled path end-to-end**

```bash
git add README.md && git commit -m "docs: README with live link and usage

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" && git push
gh workflow run daily.yml --repo JungOhLee/macro-monitoring
sleep 10
gh run watch --repo JungOhLee/macro-monitoring --exit-status $(gh run list --repo JungOhLee/macro-monitoring --workflow daily.yml --limit 1 --json databaseId -q '.[0].databaseId')
```

Expected: green build + deploy.

- [ ] **Step 3: Verify the live site serves current data + episode pages**

```bash
curl -s https://jungohlee.github.io/macro-monitoring/data/latest.json | python3 -c "import json,sys; d=json.load(sys.stdin); print('as_of', d['as_of']); print('composite', d['composite']['full'])"
curl -s -o /dev/null -w "%{http_code}\n" https://jungohlee.github.io/macro-monitoring/episodes/gfc.html
```

Expected: today's-ish `as_of`, plausible composite, `200`.

- [ ] **Step 4: Fire the alert-path test and verify email**

```bash
gh workflow run daily.yml --repo JungOhLee/macro-monitoring   # ensures gh auth context exists in CI
GITHUB_ACTIONS= python -m pipeline alerts --test              # local: prints only (sanity)
gh issue create --repo JungOhLee/macro-monitoring --title "Test alert - please ignore" --body "Verifying alert email path. Close me." --label data-health
```

Expected: issue appears; **the user should confirm the notification email arrived**, then: `gh issue close <n> --repo JungOhLee/macro-monitoring`.

- [ ] **Step 5: Final sanity**

```bash
git pull && pytest -q && git log --oneline | head -20 && python -m pipeline status
```

Expected: suite green, clean linear history of task commits, status shows no unexpected STALE rows. Report the live URL and composite reading to the user.

---

## Plan Self-Review (performed at write time)

1. **Spec coverage (Phases 1–2):** registry-driven config ✔ (T1), isolated ingestion + freshness ✔ (T2/T6), dual-window percentiles + 10y gate + native-frequency/as-of ✔ (T7/T8), reweighted pillar/composite + regime ✔ (T8), append-mostly storage with revision windows ✔ (T2), offline export + committed site JSON ✔ (T9), dashboard views 1–3/6 with Phase-3 placeholder slots, staleness badges, role chips, window toggle, crisis markers ✔ (T10), workflow with off-peak double cron, permissions, no-commit tolerance, Pages artifact deploy ✔ (T11), labeled-issue alerts with per-label cooldown + CI gating ✔ (T12), narrative drafts shipped in Phase 2 per design §9 ✔ (T13), one-time setup checklist §16 ✔ (T11 script + T14 verification). Deferred to Phase 3+ by design: analogs, sequencer, backtest, z-score Euclidean comparison, Shiller/FINRA/AAII/CBOE sources.
2. **Placeholder scan:** none — every step has full code/commands. The two intentional UI "placeholders" are product features (Phase-3 slots), not plan gaps.
3. **Type consistency:** `Series`/`Indicator` field order matches all positional constructions (T1↔T6/T8/T12); `merge_observations(existing, fetched, revision_window_days)` consistent (T2↔T6); `froth_full/froth_rolling` names consistent (T8↔T9); JSON contract keys in T9 match every `app.js` accessor in T10 (`composite[WIN].score/regime`, `pillars[p][WIN]/delta_1m/delta_3m/partial`, `history[WIN].dates/composite/pillars`, indicator `latest.pct_full/zscore`, `series.dates/values`, `pct_series`); label taxonomy in T11 setup script matches labels emitted in T12.
```
