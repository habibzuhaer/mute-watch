"""Unified known-address registry: seeds + DWF + mm_extra + discovered + CEX."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pump_prep.bridge_labels import BRIDGE_CONTRACTS
from pump_prep.cex_labels import CEX_HOT_WALLETS
from pump_prep.config import ROOT, SEEDS_FILE
from pump_prep.seeds import load_seeds

DISCOVERED_FILE = Path(
    __import__("os").getenv(
        "MUTE_DISCOVERED_LABELS",
        str(ROOT / "data" / "graph" / "discovered_labels.json"),
    )
)
MM_EXTRA = ROOT / "addresses" / "mm_extra.json"
DWF_FILE = ROOT / "addresses" / "dwf_labs.json"


def _put(
    known: dict[str, dict[str, Any]],
    addr: str,
    *,
    entity: str,
    label: str,
    role: str,
    source: str = "",
    overwrite: bool = False,
) -> None:
    if not addr or not addr.startswith("0x") or len(addr) != 42:
        return
    key = addr.lower()
    if key in known and not overwrite:
        return
    known[key] = {
        "entity": entity,
        "label": label,
        "role": role,
        "source": source,
    }


def load_known() -> dict[str, dict[str, Any]]:
    """address(lower) -> {entity, label, role, source}."""
    known: dict[str, dict[str, Any]] = {}

    try:
        for s in load_seeds(SEEDS_FILE):
            role = "seed"
            ent = (s.entity or "").lower()
            if "wintermute" in ent or "compare" in ent:
                role = "control"
            elif "gotbit" in ent or "cls" in ent or "zm" in ent:
                role = "mm"
            _put(
                known,
                s.address,
                entity=s.entity,
                label=s.label,
                role=role,
                source=s.source,
                overwrite=True,
            )
    except Exception:
        pass

    if DWF_FILE.exists():
        for w in json.loads(DWF_FILE.read_text()).get("wallets") or []:
            _put(
                known,
                (w.get("address") or "").strip(),
                entity=w.get("entity") or "DWF Labs",
                label=w.get("label") or "DWF",
                role="seed",
                source=w.get("source") or "",
            )

    if MM_EXTRA.exists():
        for w in json.loads(MM_EXTRA.read_text()).get("wallets") or []:
            if (w.get("entity") or "") == "_skip":
                continue
            role = (w.get("role") or "watch").lower()
            if role == "skip":
                continue
            _put(
                known,
                (w.get("address") or "").strip(),
                entity=w.get("entity") or "Extra",
                label=w.get("label") or w.get("entity") or "extra",
                role=role if role in ("cex", "mm", "fund", "seed", "control", "watch", "infra", "cex_hist") else "watch",
                source=w.get("source") or "mm_extra",
            )

    if DISCOVERED_FILE.exists():
        try:
            data = json.loads(DISCOVERED_FILE.read_text())
            for w in data.get("wallets") or []:
                _put(
                    known,
                    (w.get("address") or "").strip(),
                    entity=w.get("entity") or "Discovered",
                    label=w.get("label") or "discovered",
                    role=w.get("role") or "watch",
                    source=w.get("source") or "discovered",
                    overwrite=False,
                )
        except Exception:
            pass

    for addr, name in CEX_HOT_WALLETS.items():
        _put(
            known,
            addr,
            entity=name,
            label=f"{name} hot",
            role="cex",
            source="cex_labels",
        )

    for addr, name in BRIDGE_CONTRACTS.items():
        _put(
            known,
            addr,
            entity=name,
            label=f"{name} bridge",
            role="bridge",
            source="bridge_labels",
            overwrite=False,
        )

    return known


def save_discovered(wallets: list[dict[str, Any]]) -> Path:
    DISCOVERED_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    if DISCOVERED_FILE.exists():
        try:
            existing = list(json.loads(DISCOVERED_FILE.read_text()).get("wallets") or [])
        except Exception:
            existing = []
    by_addr = {
        (w.get("address") or "").lower(): w
        for w in existing
        if (w.get("address") or "").startswith("0x")
    }
    for w in wallets:
        addr = (w.get("address") or "").lower()
        if not addr.startswith("0x"):
            continue
        by_addr[addr] = {**by_addr.get(addr, {}), **w, "address": addr}
    payload = {
        "purpose": "auto_discovered_from_graph",
        "updated": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "wallets": list(by_addr.values()),
    }
    DISCOVERED_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return DISCOVERED_FILE
