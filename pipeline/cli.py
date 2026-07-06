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
    now = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
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
