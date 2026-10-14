"""CLI: python -m intel once|collect|status|ui|bootstrap"""

from __future__ import annotations

import argparse
import json
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="MUTE Intel — Solana+BNB families / pre-pump collect")
    p.add_argument(
        "command",
        nargs="?",
        default="once",
        choices=["once", "collect", "status", "ui", "bootstrap", "cluster", "hubs"],
    )
    p.add_argument("--hours", type=float, default=None, help="Collect window hours (default 12)")
    p.add_argument("--sleep", type=float, default=None, help="Seconds between cycles")
    p.add_argument("--no-bootstrap", action="store_true")
    p.add_argument("--fresh", action="store_true", help="Do not resume previous collect window")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "collect":
        from intel.orchestrator import run_collect

        return run_collect(
            hours=args.hours,
            sleep_sec=args.sleep,
            bootstrap=not args.no_bootstrap,
            resume=not args.fresh,
        )

    if args.command == "status":
        from intel.cycles import check_health
        from intel.orchestrator import build_snapshot

        snap = build_snapshot()
        snap["health"] = check_health()
        print(json.dumps(snap, ensure_ascii=False, indent=2, default=str))
        return 0
    if args.command == "hubs":
        from intel.hubs import deepen_hubs

        out = deepen_hubs(limit=7, prioritize=True)
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.command == "ui":
        from intel.orchestrator import build_snapshot
        from intel.ui import write_ui

        print(write_ui(build_snapshot()))
        return 0

    if args.command == "bootstrap":
        from intel.store import load_state, save_state
        from intel.orchestrator import bootstrap_queues

        st = load_state()
        out = bootstrap_queues(st)
        save_state(st)
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.command == "cluster":
        from intel.cluster.families import build_families
        from intel.detect.activity import run_detectors

        det = run_detectors()
        fam = build_families()
        print(json.dumps({"detect": det, "families": fam.get("stats")}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "once":
        from intel.orchestrator import run_once

        row = run_once(bootstrap=not args.no_bootstrap)
        print(json.dumps(row, ensure_ascii=False, indent=2, default=str))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
