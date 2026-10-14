from __future__ import annotations

import argparse
import json
import logging
import sys

from mute.config import load_settings, load_wallets, resource_estimate
from mute.monitor import Monitor
from mute.telegram import send_telegram


def _setup_logging(log_dir) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    fh = logging.FileHandler(log_dir / "mute.log", encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MUTE — DWF Labs inbound alerts")
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "once", "estimate", "test-telegram", "wallets"],
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    _setup_logging(settings.log_dir)

    if args.command == "estimate":
        wallets = load_wallets(settings.addresses_file)
        est = resource_estimate(settings, wallets)
        est["mode"] = "parallel" if settings.parallel else "sequential"
        est["parallel_workers"] = settings.parallel_workers
        print(json.dumps(est, indent=2, ensure_ascii=False))
        return 0

    if args.command == "wallets":
        wallets = load_wallets(settings.addresses_file)
        for w in wallets:
            print(f"{w.get('family'):7}  {w.get('address')}  — {w.get('label')}")
        return 0

    if args.command == "test-telegram":
        ok = send_telegram(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            "<b>MUTE test</b>\nTelegram OK",
            dry_run=settings.dry_run,
        )
        print("ok" if ok else "failed")
        return 0 if ok else 1

    mon = Monitor(settings)
    if args.command == "once":
        mon.bootstrap_if_needed()
        n = mon.poll_once()
        print(f"alerts_sent={n}")
        return 0

    mon.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
