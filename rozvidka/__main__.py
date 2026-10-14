"""CLI: python -m rozvidka once|loop|ui|status"""

from __future__ import annotations

import argparse
import json
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Розвідка — autonomous MUTE cycle + DeepSeek")
    parser.add_argument(
        "command",
        nargs="?",
        default="once",
        choices=["once", "loop", "ui", "status", "wiki", "relations", "profit"],
    )
    parser.add_argument("--no-llm", action="store_true", help="Skip DeepSeek; rule-based narrative")
    parser.add_argument("--sleep", type=float, default=None, help="Seconds between turns")
    parser.add_argument("--page", default="memory", help="wiki page for wiki command")
    parser.add_argument(
        "--expand",
        action="store_true",
        help="Opt-in Etherscan expand (rewrites data/rozvidka/db)",
    )
    parser.add_argument("--no-expand", action="store_true", help="Read-only families (default)")
    parser.add_argument("--expand-limit", type=int, default=None, help="How many profit seeds to expand")
    args = parser.parse_args(argv)

    from rozvidka.config import EXPAND_DEFAULT

    if args.no_expand:
        do_expand = False
    elif args.expand:
        do_expand = True
    else:
        do_expand = EXPAND_DEFAULT

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "status":
        from rozvidka.runtime import build_snapshot

        print(json.dumps(build_snapshot(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "ui":
        from rozvidka.runtime import build_snapshot
        from rozvidka.ui import write_ui

        path = write_ui(build_snapshot())
        print(path)
        return 0

    if args.command == "wiki":
        from rozvidka import wiki

        wiki.ensure()
        print(wiki.read_page(args.page))
        return 0

    if args.command == "profit":
        from rozvidka.profit import run_profit_pipeline

        out = run_profit_pipeline(
            do_expand=do_expand,
            expand_limit=args.expand_limit,
        )
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.command == "relations":
        from rozvidka.relations import run_family_pass

        out = run_family_pass(
            wiki_sync=True,
            do_expand=do_expand,
            expand_limit=args.expand_limit,
        )
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.command == "once":
        from rozvidka.runtime import run_one_turn

        row = run_one_turn(use_llm=not args.no_llm, do_expand=do_expand)
        print(json.dumps(row, ensure_ascii=False, indent=2))
        return 0

    if args.command == "loop":
        from rozvidka.runtime import run_forever

        return run_forever(
            sleep_sec=args.sleep,
            use_llm=not args.no_llm,
            do_expand=do_expand,
        )

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
