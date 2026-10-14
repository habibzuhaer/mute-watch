from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Seed:
    address: str
    family: str  # evm / tron / solana
    entity: str
    label: str
    role: str = ""
    priority: int = 2
    source: str = ""


def load_seeds(path: Path) -> list[Seed]:
    data = json.loads(path.read_text(encoding="utf-8"))
    seeds: list[Seed] = []
    seen: set[str] = set()

    wallets = data.get("wallets") or []
    if wallets:
        for w in wallets:
            addr = (w.get("address") or "").strip()
            if not addr:
                continue
            key = addr.lower() if addr.startswith("0x") else addr
            if key in seen:
                continue
            seen.add(key)
            family = (w.get("family") or w.get("chain") or "evm").lower()
            if family == "evm" or family.startswith("eth"):
                family = "evm"
            seeds.append(
                Seed(
                    address=addr,
                    family=family,
                    entity=w.get("entity") or "Unknown",
                    label=w.get("label") or addr[:12],
                    role=w.get("role") or "",
                    priority=int(w.get("priority") or 2),
                    source=w.get("source") or "",
                )
            )
        return seeds

    for entity, items in (data.get("entities") or {}).items():
        for item in items or []:
            addr = (item.get("address") or "").strip()
            if not addr:
                continue
            key = addr.lower() if addr.startswith("0x") else addr
            if key in seen:
                continue
            seen.add(key)
            chain = (item.get("chain") or "evm").lower()
            family = "evm" if chain == "evm" else chain
            seeds.append(
                Seed(
                    address=addr,
                    family=family,
                    entity=entity,
                    label=item.get("role") or addr[:12],
                    role=item.get("role") or "",
                    priority=2,
                    source=item.get("source") or "",
                )
            )
    if not seeds:
        raise ValueError(f"No seeds in {path}")
    return seeds


def seed_index(seeds: list[Seed]) -> dict[str, Seed]:
    out: dict[str, Seed] = {}
    for s in seeds:
        key = s.address.lower() if s.address.startswith("0x") else s.address
        out[key] = s
    return out


def as_dict(seed: Seed) -> dict[str, Any]:
    return {
        "address": seed.address,
        "family": seed.family,
        "entity": seed.entity,
        "label": seed.label,
        "role": seed.role,
        "priority": seed.priority,
        "source": seed.source,
    }
