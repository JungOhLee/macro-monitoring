from __future__ import annotations

import argparse
import os
import sys

import pandas as pd
from dotenv import load_dotenv

from pipeline import paths, store
from pipeline.ingest import run_ingest, stale_series
from pipeline.registry import load_registry


def _api_key() -> str:
    load_dotenv()
    key = os.environ.get("FRED_API_KEY")
    if not key:
        sys.exit("FRED_API_KEY not set (put it in .env or the environment)")
    return key


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
    n_comp, n_pil, n_stress = append_scores(result)
    latest = result.composite[result.composite.window == "full"].iloc[-1]
    print(f"scores: +{n_comp} composite rows, +{n_pil} pillar rows, +{n_stress} stress rows; "
          f"latest {latest['date']:%Y-%m-%d} composite={latest['score']} ({latest['regime']})")

    from pipeline.compute.sequencer import evaluate_stages, load_state, save_state, update_state

    th = load_thresholds()
    asof = max(s.index.max() for s in raw.values() if not s.empty)
    fired = evaluate_stages(reg, th, raw, result, asof)
    seq_state = update_state(load_state(), fired, asof, raw.get("spx"), th["sequencer"])
    save_state(seq_state)
    print(f"sequencer: engaged={seq_state['engaged']} current_stage={seq_state['current_stage']}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    import pandas as pd

    reg = load_registry()
    fresh = store.load_freshness()
    now = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
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


def cmd_alerts(args: argparse.Namespace) -> int:
    import pandas as pd

    from pipeline.alerts import Alert, deliver, evaluate_alerts
    from pipeline.registry import load_thresholds

    th = load_thresholds()
    if args.test:
        failed = deliver([Alert("data-health", "Test alert - please ignore",
                       "Verifying the alert email path. Close me.")], cooldown_days=0)
        return 1 if failed else 0
    reg = load_registry()
    now = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    found = evaluate_alerts(reg, th, now)
    failed = deliver(found, th["alerts"]["cooldown_days"])
    print(f"alerts: {len(found)} rule(s) fired")
    return 1 if failed else 0


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


def cmd_export(args: argparse.Namespace) -> int:
    from pipeline.export import export_site, render_episodes
    from pipeline.registry import load_thresholds

    reg = load_registry()
    latest = export_site(reg, load_thresholds())
    print(f"export: site/data written, as_of {latest['as_of']}, "
          f"composite {latest['composite']['full']['score']} ({latest['composite']['full']['regime']})")
    names = render_episodes()
    print(f"episodes: rendered {', '.join(names) or 'none'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run").set_defaults(fn=cmd_run)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("export").set_defaults(fn=cmd_export)
    sub.add_parser("rebuild-episodes").set_defaults(fn=cmd_rebuild_episodes)
    sub.add_parser("backtest").set_defaults(fn=cmd_backtest)
    ap = sub.add_parser("alerts")
    ap.add_argument("--test", action="store_true")
    ap.set_defaults(fn=cmd_alerts)
    args = p.parse_args(argv)
    return args.fn(args)
