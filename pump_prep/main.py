"""Early pump-prep scanner: seed MM wallets → signals + address graph → HTML."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from pump_prep.analyze import analyze
from pump_prep.config import ETHERSCAN_API_KEY, LOOKBACK_DAYS, OUT_DIR, SEEDS_FILE
from pump_prep.report import write_html


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pump prep address/graph scanner")
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "report-only", "deployers", "continuous", "graph-html", "backfill-signals", "rewrite-i18n", "hub", "clusters", "panel"],
    )
    parser.add_argument("sub", nargs="?", default=None, help="continuous status|html")
    parser.add_argument("--days", type=int, default=LOOKBACK_DAYS)
    parser.add_argument("--no-expand", action="store_true", help="Skip 1-hop counterparty expand")
    parser.add_argument("--seeds", default=str(SEEDS_FILE))
    parser.add_argument("--limit", type=int, default=40, help="Tokens for deployer trace")
    parser.add_argument("--max-age", type=int, default=365, help="Max token age days (0=any)")
    parser.add_argument("--sleep", type=float, default=2.0, help="Continuous scanner pause between tokens")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "continuous":
        from pump_prep.continuous import run_forever, write_graph_html
        from pump_prep import graph_store as gs

        if args.sub == "status":
            print(__import__("json").dumps(gs.aggregate_summary()["state"], indent=2, ensure_ascii=False))
            return 0
        if args.sub == "html":
            print(write_graph_html())
            return 0
        return run_forever(sleep_sec=args.sleep)

    if args.command == "graph-html":
        from pump_prep.continuous import write_graph_html

        print(write_graph_html())
        return 0

    if args.command == "backfill-signals":
        from pump_prep.continuous import backfill_signals, write_graph_html

        n = backfill_signals()
        out = write_graph_html()
        logging.info("Backfilled %s signals → %s", n, out)
        print(out)
        return 0

    if args.command == "rewrite-i18n":
        from pump_prep.continuous import rewrite_signals_i18n, write_graph_html
        from pump_prep.hub import rebuild_all
        from pump_prep.i18n_ui import write_static_packs
        from pump_prep.panel import write_dashboard_html

        n = rewrite_signals_i18n()
        graph = write_graph_html()
        paths = rebuild_all()
        panel = write_dashboard_html()
        packs = write_static_packs()
        logging.info(
            "Rewrote %s signals · graph=%s hub=%s panel=%s packs=%s",
            n,
            graph,
            paths.get("hub"),
            panel,
            packs,
        )
        print(f"signals={n}\ngraph={graph}\nhub={paths.get('hub')}\npanel={panel}")
        return 0

    if args.command == "hub":
        from pump_prep.hub import rebuild_all
        from pump_prep.panel import write_dashboard_html

        paths = rebuild_all()
        panel = write_dashboard_html()
        logging.info("Hub rebuilt %s panel=%s", paths, panel)
        print(paths["hub"])
        return 0

    if args.command == "panel":
        from pump_prep.panel import write_dashboard_html
        from pump_prep.cycles import write_cycles_json

        p = write_dashboard_html()
        c = write_cycles_json()
        logging.info("Panel %s cycles %s", p, c)
        print(p)
        return 0

    if args.command == "clusters":
        from pump_prep.clusters import build_deployer_clusters

        data = build_deployer_clusters()
        logging.info(
            "Clusters=%s repeat=%s pump_dep=%s promoted=%s",
            data.get("cluster_count"),
            data.get("repeat_deployers"),
            data.get("pump_deployers"),
            data.get("promoted_labels"),
        )
        print(json.dumps({k: data[k] for k in ("cluster_count", "repeat_deployers", "pump_deployers", "promoted_labels", "generated_at")}, indent=2))
        return 0

    if args.command == "deployers":
        from pump_prep.deployer_trace import analyze_deployers, write_deployer_html

        if not ETHERSCAN_API_KEY:
            logging.error("Set ETHERSCAN_API_KEY in .env")
            return 1
        max_age = None if args.max_age == 0 else args.max_age
        data = analyze_deployers(limit=args.limit, max_age_days=max_age)
        out = write_deployer_html(data)
        logging.info(
            "Deployers resolved=%s matches=%s → %s",
            data.get("tokens_resolved"),
            data.get("stats", {}).get("match_flows"),
            out,
        )
        print(out)
        return 0

    if args.command == "run":
        if not ETHERSCAN_API_KEY:
            logging.error("Set ETHERSCAN_API_KEY in .env")
            return 1
        data = analyze(
            seeds_path=__import__("pathlib").Path(args.seeds),
            lookback_days=args.days,
            expand=not args.no_expand,
        )
    else:
        import json
        from pathlib import Path

        p = OUT_DIR / "pump_prep_data.json"
        if not p.exists():
            logging.error("No %s — run first", p)
            return 1
        data = json.loads(p.read_text(encoding="utf-8"))

    out = write_html(data)
    logging.info(
        "Done signals=%s addresses=%s edges=%s → %s",
        len(data.get("signals") or []),
        len(data.get("addresses") or []),
        len(data.get("edges") or []),
        out,
    )
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
