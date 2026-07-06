# Historical Episodes Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Six pre-2000 crises join the monitor — 1973/1980/1987/1990 as full library episodes (snapshots, analogs, narratives, timelines), 1929/1937 as chart markers — with unified named crisis markers on every chart and the backtest extended to 1987 with an honest 1990 criterion.

**Architecture:** Pure extension of existing machinery: `episodes.yaml` gains `library`/`criterion` flags; `build_snapshots` filters on `library`; export derives unified `crisis_markers` from episodes.yaml (thresholds' `episode_peaks` retired); app.js renders named hover markers (red = library, gray = marker-only); backtest replay start 1997→1987.

**Tech Stack:** unchanged. Suite baseline: **103 passed**.

## Global Constraints

- Repo `/Users/jolee/Library/CloudStorage/Dropbox/CodingProjects/macro-monitoring`, branch main, commit+push per task, CI green after every push; project venv.
- Coverage facts (verified live): qualified indicators at peak/T−24m — oil1973 8/8, volcker1980 9/9, black1987 11/10, rec1990 11/11, gd1929 1/1, rec1937 1/1. Peak dates verified against `data/raw/spx.csv` local maxima: 1929-09-16, 1937-03-10, 1973-01-11, 1980-11-28, 1987-08-25, 1990-07-16.
- `min_shared=8` analog gate means all four new library episodes are analog-eligible; 1929/1937 must never enter snapshots.
- After snapshots/backtest changes: `rebuild-episodes`, `seed-sequence`, `export`, `backtest` all re-run and their outputs committed; determinism (double-run byte-identical) must hold.
- Commit style: conventional prefix + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Episode config schema, snapshots, unified markers, backtest extension

**Files:**
- Modify: `config/episodes.yaml`, `config/thresholds.yaml`, `pipeline/compute/episodes.py`, `pipeline/export.py`, `pipeline/backtest.py`, `tests/test_episodes_lib.py`, `tests/test_export.py`, `tests/test_backtest.py`

**Interfaces:**
- `episodes.yaml` entries gain optional `library: false` (default true) and `criterion: false` (default true). New entries appended:

```yaml
  - {id: oil1973,     name: "1973-74 oil-shock bear",   peak: "1973-01-11", criterion: false}
  - {id: volcker1980, name: "Volcker double-dip",        peak: "1980-11-28", criterion: false}
  - {id: black1987,   name: "Black Monday 1987",         peak: "1987-08-25", criterion: false}
  - {id: rec1990,     name: "1990 recession bear",       peak: "1990-07-16"}
  - {id: gd1929,      name: "Great Depression crash",    peak: "1929-09-16", library: false, criterion: false}
  - {id: rec1937,     name: "1937 relapse",              peak: "1937-03-10", library: false, criterion: false}
```

(criterion defaults true for the original four; rec1990 gets a criterion because the extended replay covers it; oil1973/volcker1980/black1987 predate replay coverage or sit in its warm-up.)
- `build_snapshots` skips `library: false` episodes: inside the episode loop, `if ep.get("library") is False: continue`.
- Export: `history.json` gains `"crisis_markers": [{"date","name","library"}]` for ALL episodes sorted by date; `"episode_peaks"` becomes the same full date list (back-compat for drill-down shapes until Task 2 ships in the same wave); `episodes.json`'s `episodes` key keeps ALL entries (UI filters). `thresholds.yaml` loses `episode_peaks`; export no longer reads it.
- Backtest: `run_backtest(..., start="1987-01-30")` default; `evaluate_criteria` skips episodes with `criterion: false` (and keeps the existing control-episode branch); the backtest page's shaded windows derive from episodes that have criteria or are the control.
- `seed-sequence` replay start also becomes 1987-01-30 (single constant: add `REPLAY_START = "1987-01-30"` to `pipeline/backtest.py`, imported by the CLI seed command).

- [ ] **Step 1: Failing tests.**
  - `tests/test_episodes_lib.py::test_marker_only_episodes_excluded_from_snapshots`: EPI_CFG with one `library: false` entry whose peak sits inside fixture data → `build_snapshots` returns zero rows for it, non-zero for a sibling library entry.
  - `tests/test_export.py::test_crisis_markers_exported`: monkeypatched `load_episodes` returning 2 library + 1 marker-only → `history.json` has 3 `crisis_markers` sorted by date with correct `library` flags, and `episode_peaks` lists all 3 dates.
  - `tests/test_backtest.py::test_criterion_flag_skips_episode`: episodes list where one entry has `criterion: false` → no criterion row emitted for it; existing entries unaffected.

Write exact test code following the existing patterns in each file (fixtures/monkeypatching conventions already established there); run to confirm failures.

- [ ] **Step 2: Implement** the four code changes above (episodes.yaml, episodes.py one-line filter, export marker derivation, backtest criterion filter + REPLAY_START). In `export_site`, build markers as:

```python
    all_eps = sorted(epi_cfg["episodes"], key=lambda e: e["peak"])
    history["crisis_markers"] = [
        {"date": e["peak"], "name": e["name"], "library": e.get("library", True)} for e in all_eps
    ]
    history["episode_peaks"] = [e["peak"] for e in all_eps]
```

(remove the thresholds-based line and delete `episode_peaks` from `config/thresholds.yaml`).

- [ ] **Step 3: Suite green** (expect 106; report exact), then live rebuild in order: `rebuild-episodes` (report per-episode snapshot row counts — expect gd1929/rec1937 absent, four new episodes present with ≥6 indicators/offset pre-peak), `seed-sequence` (report headline — engaged/current_stage should remain 3/engaged; fired dates may shift with the longer replay warm-up — report per-stage), `export`, `backtest` (report ALL criteria verbatim — now five rows incl. `stage>=4 before rec1990 peak`; honest result, no tuning), double-run determinism check.
- [ ] **Step 4: Commit + push + CI green.** `feat: pre-2000 episodes — library/marker split, unified crisis markers, backtest to 1987`

### Task 2: Chart markers UI + navigation

**Files:**
- Modify: `site/assets/app.js`, `site/index.html`, `site/backtest.html`, `site/assets/style.css` (if needed)

**Interfaces:** consumes `history.crisis_markers`. `episodeShapes()` is replaced by `crisisShapes()` returning Plotly shapes (library → `#d64545` dotted; marker-only → `#8b93a3` dotted) and `crisisLabels(yPos)` returning ONE scatter trace (`mode:"markers"`, `hoverinfo:"text"`, invisible 6px markers at each crisis date at fixed y) whose hover text is the crisis name+date — added to the history chart and both drill-down charts so markers are hover-identifiable. Nav becomes two groups: `Crisis stories: 2000 dot-com · 2007 GFC · 2020 COVID · 2022 unwind — Earlier: 1973 oil shock · 1980 Volcker · 1987 Black Monday · 1990 recession`, plus Backtest link unchanged. backtest.html episode shading keeps using its own JSON (already carries all episodes — filter its shading to episodes with `criterion !== false` OR control, matching the criteria list).

- [ ] **Step 1:** Implement `crisisShapes()`/`crisisLabels()`; update `renderHistory` and `renderIndicator` to use them (labels trace y: history=97, drill-down pct=97, drill-down raw: skip labels trace — no fixed y-range; shapes only). Guard: if `HISTORY.crisis_markers` missing, fall back to old `episode_peaks` behavior.
- [ ] **Step 2:** Nav rewrite in index.html; backtest.html shading filter.
- [ ] **Step 3:** Browser verification (Playwright): history chart shows 10 markers with hover names (8 red incl. the 4 originals? — careful: originals are library episodes → red; 1929/1937 gray only visible when... history starts 1990! The score history chart begins 1990, so 1929/37/73/80/87 markers fall OUTSIDE its x-range — verify Plotly silently clips them (expected; "whenever possible"). Drill-down on Shiller CAPE (1881→) must show ALL 10 markers; Buffett (1947→) shows 8; VIX (1990→) shows 4+1990. Verify hover text works on the CAPE drill-down for 1929.) Zero new console errors.
- [ ] **Step 4:** Commit + push + CI green. `feat: named crisis markers across charts with library/marker distinction`

### Task 3: Narratives for the four new library episodes + live E2E

**Files:**
- Create: `episodes/oil1973.md`, `episodes/volcker1980.md`, `episodes/black1987.md`, `episodes/rec1990.md`

The four markdown files' content is pre-drafted and fact-checked (workflow `wf_43041041-92e`); the controller saves them to `.superpowers/sdd/narratives/<id>.md` — transcribe each verbatim to `episodes/<id>.md`.

- [ ] **Step 1:** Copy the four files in; `pipeline export` — verify `site/episodes/{oil1973,volcker1980,black1987,rec1990}.html` render with auto-timelines appended (snapshots exist from Task 1); spot-check one timeline row against `episode_snapshots.csv`.
- [ ] **Step 2:** Suite green (episode render tests unaffected — verify), commit + push + CI green. `feat: narratives for 1973, 1980, 1987, 1990 episodes`
- [ ] **Step 3:** Live E2E: all four new episode URLs 200; index nav shows both groups; analog card — report whether any new episode entered today's top-3; drill-down CAPE shows 1929 marker live.

## Plan Self-Review

Coverage: markers-everywhere ✔ (T1 data + T2 UI, clipping = "whenever possible" semantics); library episodes ✔ (T1 snapshots + T3 narratives; analogs/timelines free via existing machinery); backtest honesty ✔ (criterion flags, 1990 added, no tuning); single source for markers ✔ (episodes.yaml). Placeholders: none — T3 content arrives via controller-saved verified files. Type consistency: `crisis_markers` shape matches T2's reads; `library`/`criterion` defaults consistent (absent = true) across episodes.py/export/backtest.
