"""Orchestrator — control cycles for long collect (e.g. 12h × N)."""

from __future__ import annotations

import json
import logging
import signal
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from intel import wiki
from intel.cluster.families import build_families
from intel.config import (
    CYCLE_SLEEP_SEC,
    COLLECT_HOURS_DEFAULT,
    ENABLE_BNB,
    ENABLE_EVM_ADAPTER,
    ENABLE_SOL,
    EXPAND_HOP_MAX,
    MAX_NEW_NEIGHBORS,
    SEEDS_PER_CYCLE,
    STATE_FILE,
)
from intel.detect.activity import run_detectors
from intel.i18n import snapshot_i18n, t
from intel.ingest import bnb as bnb_ingest
from intel.ingest import solana as sol_ingest
from intel.ingest import evm_chain as evm_ingest
from intel.ingest.evm_adapter import import_graph_edges
from intel.hubs import deepen_hubs
from intel.store import (
    ack_batch,
    load_addresses,
    load_state,
    pop_batch,
    save_state,
    stats_snapshot,
    flush_addresses,
    upsert_address,
)
from intel import cycles as cycle_ctl
from intel.ui import write_ui

logger = logging.getLogger(__name__)
_STOP = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def bootstrap_queues(state: dict[str, Any]) -> dict[str, Any]:
    """Seed queues from legacy graph + watchlists + priority hubs."""
    imported = {"skipped": True}
    if ENABLE_EVM_ADAPTER:
        imported = import_graph_edges(limit=10000, state=state)
    hubs = {"skipped": True}
    try:
        hubs = deepen_hubs(limit=7, prioritize=True)
        # deepen_hubs saves state itself — reload
        state.clear()
        state.update(load_state())
    except Exception as exc:
        logger.warning("hubs deepen: %s", exc)
        hubs = {"error": str(exc)}
    save_state(state)
    return {"import": imported, "hubs": hubs}


def run_cycle(state: dict[str, Any], *, sess: requests.Session | None = None) -> dict[str, Any]:
    """One control cycle: pop seeds → ingest → detect → cluster → wiki."""
    sess = sess or requests.Session()
    cycle = int(state.get("cycle") or 0) + 1
    state["cycle"] = cycle
    t0 = time.time()
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    ok_batch = True

    batch = pop_batch(state, SEEDS_PER_CYCLE)
    save_state(state)  # checkpoint in_flight before network I/O
    # if empty, re-bootstrap lightly
    if not batch:
        bootstrap_queues(state)
        batch = pop_batch(state, SEEDS_PER_CYCLE)
        save_state(state)

    for item in batch:
        chain = (item.get("chain") or "").lower()
        addr = item.get("address") or ""
        hop = int(item.get("hop") or 0)
        if hop > EXPAND_HOP_MAX:
            continue
        try:
            if chain == "bnb" and ENABLE_BNB:
                r = evm_ingest.ingest_seed(
                    addr,
                    state,
                    chain_id=56,
                    hop=hop,
                    reason=item.get("reason") or "",
                    max_neighbors=MAX_NEW_NEIGHBORS,
                    sess=sess,
                )
                results.append(r)
            elif chain in {"ethereum", "eth"} and ENABLE_BNB:
                # ENABLE_BNB gates etherscan key; eth uses same API
                r = evm_ingest.ingest_seed(
                    addr,
                    state,
                    chain_id=1,
                    hop=hop,
                    reason=item.get("reason") or "",
                    max_neighbors=MAX_NEW_NEIGHBORS,
                    sess=sess,
                )
                results.append(r)
            elif chain == "solana" and ENABLE_SOL:
                r = sol_ingest.ingest_seed(
                    addr,
                    state,
                    hop=hop,
                    reason=item.get("reason") or "",
                    max_neighbors=MAX_NEW_NEIGHBORS,
                    sess=sess,
                )
                results.append(r)
            elif chain == "solana" and not ENABLE_SOL:
                continue
            else:
                upsert_address(chain or "ethereum", addr, tags=["queued_skip"])
        except Exception as exc:
            logger.exception("ingest %s %s", chain, addr[:12])
            errors.append(f"{chain}:{addr[:10]}:{exc}")
            ok_batch = False
            try:
                from agents.hooks import on_net_fail

                on_net_fail("intel", exc, hint="net_rpc")
            except Exception:
                pass

    ack_batch(state, batch, ok=ok_batch or bool(results))
    flush_addresses()
    det = run_detectors()
    try:
        from alerts.push import push_intel_detection

        push_intel_detection(det)
    except Exception:
        logger.debug("intel alert push skipped", exc_info=True)
    fam = build_families()
    flush_addresses()

    # wiki sync top prepump + family hubs
    cards = []
    addrs = load_addresses()
    for p in (det.get("prepump") or [])[:20]:
        key = p.get("key")
        if key and key in addrs:
            cards.append(addrs[key])
    for f in (fam.get("families") or [])[:15]:
        k = f.get("hub_key")
        if k and k in addrs:
            cards.append(addrs[k])
    wiki.ensure()
    wiki.sync_top(cards, limit=40)
    wiki.append(
        "journal",
        (
            f"cycle {cycle}: ingest={len(results)} edges+="
            f"{sum(r.get('edges_new') or 0 for r in results)} · "
            f"spikes={det.get('spike_n')} prepump={det.get('prepump_n')} · "
            f"families={fam.get('stats', {}).get('families')}"
        ),
        heading=f"{t('cycle')} {cycle}",
    )
    if det.get("spikes"):
        wiki.append(
            "tokens",
            "\n".join(
                f"- [{s.get('chain')}] {s.get('symbol')} tx={s.get('tx')} uniq={s.get('unique')} sc={s.get('score')}"
                for s in det["spikes"][:15]
            ),
            heading=t("spikes"),
        )
    if fam.get("families"):
        wiki.append(
            "clusters",
            "\n".join(
                f"- **{f.get('id')}** {f.get('short')} size={f.get('size')} tok×{f.get('token_n')}"
                for f in fam["families"][:20]
            ),
            heading=t("families"),
        )

    try:
        from agents.wiki import rebuild_safe

        rebuild_safe("intel-cycle")
    except Exception:
        logger.debug("unified wiki skipped", exc_info=True)

    st = stats_snapshot()
    state["last_cycle"] = {
        "cycle": cycle,
        "elapsed": round(time.time() - t0, 2),
        "ingest": results,
        "detect": {"spike_n": det.get("spike_n"), "prepump_n": det.get("prepump_n")},
        "families": fam.get("stats"),
        "stats": st,
        "errors": errors[-10:],
        "batch_n": len(batch),
        "ts": _now().isoformat(),
    }
    if errors:
        state.setdefault("errors", [])
        state["errors"] = (list(state["errors"]) + errors)[-50:]
    cycle_ctl.heartbeat(state)
    cycle_ctl.append_cycle(
        {
            "cycle": cycle,
            "elapsed": state["last_cycle"]["elapsed"],
            "batch_n": len(batch),
            "edges_new": sum(r.get("edges_new") or 0 for r in results),
            "neighbors": sum(r.get("neighbors") or 0 for r in results),
            "spike_n": det.get("spike_n"),
            "prepump_n": det.get("prepump_n"),
            "families": (fam.get("stats") or {}).get("families"),
            "queue": len(state.get("queue") or []),
            "addresses": st.get("addresses"),
            "edges": st.get("edges"),
            "by_chain": st.get("by_chain"),
            "errors": errors[:5],
            "chains": [r.get("chain") for r in results],
        }
    )
    save_state(state)
    try:
        from agents.hooks import beat

        beat("intel")
    except Exception:
        pass
    try:
        from agents.hooks import on_action

        on_action(
            "intel",
            "цикл",
            f"cycle {cycle}",
            detail=f"q={len(state.get('queue') or [])} spikes={det.get('spike_n')} prepump={det.get('prepump_n')}",
        )
    except Exception:
        pass

    snap = build_snapshot(state, det=det, fam=fam)
    write_ui(snap)
    return state["last_cycle"]


def build_snapshot(
    state: dict[str, Any] | None = None,
    *,
    det: dict[str, Any] | None = None,
    fam: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = state or load_state()
    st = stats_snapshot()
    if fam is None:
        from intel.store import load_json, FAMILY_FILE

        fam = load_json(FAMILY_FILE, {})
    health = cycle_ctl.check_health()
    history = cycle_ctl.read_cycles(30)
    return {
        "ok": True,
        "version": "0.2",
        "i18n": snapshot_i18n(),
        "lang": __import__("intel.config", fromlist=["LANG"]).LANG,
        "name": t("name"),
        "subtitle": t("subtitle"),
        "goal": t("goal"),
        "health": health,
        "cycles": history,
        "state": {
            "cycle": state.get("cycle"),
            "queue": len(state.get("queue") or []),
            "done": len(state.get("done") or []),
            "in_flight": len(state.get("in_flight") or []),
            "collect_until": state.get("collect_until"),
            "collect_started_at": state.get("collect_started_at"),
            "collect_finished_at": state.get("collect_finished_at"),
            "collect_interrupted": state.get("collect_interrupted"),
            "sessions": (state.get("sessions") or [])[-8:],
            "last_cycle": state.get("last_cycle"),
            "errors": (state.get("errors") or [])[-8:],
            "running": health.get("running"),
            "heartbeat_at": state.get("heartbeat_at"),
        },
        "stats": st,
        "families": (fam.get("families") or [])[:15],
        "shared_tokens": (fam.get("shared_tokens") or [])[:15],
        "spikes": (det or {}).get("spikes") or [],
        "prepump": (det or {}).get("prepump") or [],
        "queue_preview": (state.get("queue") or [])[:12],
        "flags": {
            "bnb": ENABLE_BNB,
            "sol": ENABLE_SOL,
            "evm_adapter": ENABLE_EVM_ADAPTER,
        },
        "ts": _now().isoformat(),
    }


def run_collect(
    *,
    hours: float | None = None,
    sleep_sec: float | None = None,
    bootstrap: bool = True,
    resume: bool = True,
) -> int:
    """Long run with durable resume after kill / disconnect."""
    global _STOP
    hours = COLLECT_HOURS_DEFAULT if hours is None else hours
    sleep_sec = CYCLE_SLEEP_SEC if sleep_sec is None else sleep_sec

    def _stop(*_a: Any) -> None:
        global _STOP
        _STOP = True
        logger.info("stop requested — checkpoint")

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    state = load_state()
    session = cycle_ctl.begin_session(state, hours=hours, resume=resume)
    logger.info("session %s", session)

    if bootstrap and not (state.get("queue") or []):
        logger.info("bootstrap queues…")
        info = bootstrap_queues(state)
        logger.info("bootstrap %s", info)

    wiki.ensure()
    write_ui(build_snapshot(state))
    until = cycle_ctl._parse_iso(state.get("collect_until")) or (_now() + timedelta(hours=hours))
    logger.info(
        "intel collect resume=%s until=%s sleep=%ss bnb=%s sol=%s q=%s",
        session.get("status"),
        until.isoformat(),
        sleep_sec,
        ENABLE_BNB,
        ENABLE_SOL,
        len(state.get("queue") or []),
    )
    if not ENABLE_SOL:
        logger.info("Solana ingest off — public RPC (set HELIUS_API_KEY or private SOLANA_RPC_URL)")

    sess = requests.Session()
    try:
        while not _STOP and _now() < until:
            try:
                state = load_state()  # pick up external edits
                row = run_cycle(state, sess=sess)
                logger.info(
                    "cycle %s · %.1fs · q=%s · addr=%s · edges=%s",
                    row.get("cycle"),
                    row.get("elapsed"),
                    len(state.get("queue") or []),
                    (row.get("stats") or {}).get("addresses"),
                    (row.get("stats") or {}).get("edges"),
                )
            except Exception:
                logger.exception("cycle failed — will retry")
                state = load_state()
                cycle_ctl.recover_in_flight(state)
                save_state(state)
                try:
                    from agents.hooks import on_net_fail

                    on_net_fail("intel", "cycle failed", hint="net_rpc")
                except Exception:
                    pass
            for _ in range(int(max(1, sleep_sec))):
                if _STOP or _now() >= until:
                    break
                time.sleep(1)
                if _ % 15 == 0:
                    # light heartbeat while sleeping
                    st = load_state()
                    cycle_ctl.heartbeat(st)
    finally:
        state = load_state()
        if _STOP or _now() < until:
            cycle_ctl.mark_interrupted(state)
            logger.info("collect interrupted — state saved for resume")
        else:
            cycle_ctl.mark_finished(state)
            logger.info("collect finished cycles=%s", state.get("cycle"))
        write_ui(build_snapshot(state))
    return 0


def run_once(*, bootstrap: bool = True) -> dict[str, Any]:
    state = load_state()
    cycle_ctl.recover_in_flight(state)
    if bootstrap and not (state.get("queue") or []):
        bootstrap_queues(state)
    return run_cycle(state)
