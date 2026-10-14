"""CLI: python -m agents orch|status|tick|nudge"""

from __future__ import annotations

import argparse
import json
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="MUTE swarm orch — bus + restart + reports")
    p.add_argument("command", nargs="?", default="status", choices=["orch", "status", "tick", "nudge", "wiki", "paper"])
    p.add_argument("--reason", default="manual")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "status":
        from agents.orch import build_snapshot

        print(json.dumps(build_snapshot(), ensure_ascii=False, indent=2, default=str))
        return 0

    if args.command == "tick":
        from agents.orch import tick

        print(json.dumps(tick(), ensure_ascii=False, indent=2, default=str))
        return 0

    if args.command == "nudge":
        from agents.orch import nudge_speak

        out = nudge_speak({"src": "cli", "kind": "manual", "level": "ACT", "ref": args.reason})
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.command == "wiki":
        from agents.wiki import rebuild

        snap = rebuild(reason=args.reason)
        brief = {k: snap.get(k) for k in ("built_at", "reason", "sources", "stats", "paper_opened")}
        print(json.dumps(brief, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.command == "paper":
        from agents import trades

        print(json.dumps(trades.snapshot(), ensure_ascii=False, indent=2, default=str))
        return 0

    if args.command == "orch":
        from agents.orch import run_forever

        return run_forever()

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
