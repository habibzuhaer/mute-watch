#!/usr/bin/env python3
"""Export alert training dataset for LocalBrain / deepseek-r1:14b-alert fine-tune.

Reads: data/alerts/alerts.jsonl, data/graph/signals.jsonl, data/intel/signals.jsonl,
       data/rozvidka/findings.jsonl (if present)

Writes: data/alerts/dataset.jsonl (chat format for Ollama/OpenAI fine-tune)

Usage:
  PYTHONPATH=. python scripts/export_alert_dataset.py
  PYTHONPATH=. python scripts/export_alert_dataset.py --limit 500 --out data/alerts/dataset.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alerts.local_brain import LocalBrain, SYSTEM_EN, SYSTEM_UK
from alerts.levels import resolve_level, action_text
from alerts.normalize import (
    from_graph_signal,
    from_intel_prepump,
    from_intel_spike,
    from_live_prep,
    from_rozvidka_finding,
)


def _read_jsonl(path: Path, limit: int) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.open(encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
        if len(rows) >= limit:
            break
    return rows


def _assistant_row(activity: dict, lang: str) -> dict:
    level = resolve_level(activity)
    act = action_text(activity, level, lang)
    sym = activity.get("symbol") or activity.get("address_short") or "?"
    score = activity.get("score")
    return {
        "summary": f"{activity.get('activity_type')} {sym} score={score} {level}",
        "action_hint": act[:240],
        "urgency": "high" if level in {"CRITICAL", "ACT"} else "medium" if level == "WATCH" else "low",
        "noise": level == "NOISE",
        "level_override": None,
    }


def build_samples(*, limit_per_source: int = 200) -> list[dict]:
    brain = LocalBrain()
    samples: list[dict] = []

    graph_path = ROOT / "data" / "graph" / "signals.jsonl"
    for row in _read_jsonl(graph_path, limit_per_source):
        if not row.get("telegram_worthy") and int(row.get("score") or 0) < 40:
            continue
        act = from_graph_signal(row)
        for lang in ("en", "uk"):
            sys_msg = SYSTEM_UK if lang == "uk" else SYSTEM_EN
            user = brain.build_prompt(act, lang=lang, level=resolve_level(act))
            assistant = json.dumps(_assistant_row(act, lang), ensure_ascii=False)
            samples.append(
                {
                    "messages": [
                        {"role": "system", "content": sys_msg.split("ACTIVITY:")[0].strip()},
                        {"role": "user", "content": user.split("ACTIVITY:")[-1].strip()},
                        {"role": "assistant", "content": assistant},
                    ],
                    "meta": {"source": "graph", "lang": lang},
                }
            )

    intel_path = ROOT / "data" / "intel" / "signals.jsonl"
    for row in _read_jsonl(intel_path, limit_per_source):
        t = row.get("type")
        if t == "prepump":
            act = from_intel_prepump(row)
        elif t == "activity_spike":
            act = from_intel_spike(row)
        else:
            continue
        for lang in ("uk",):
            user_payload = json.dumps({"level": resolve_level(act), "activity": act}, ensure_ascii=False)
            assistant = json.dumps(_assistant_row(act, lang), ensure_ascii=False)
            samples.append(
                {
                    "messages": [
                        {"role": "system", "content": SYSTEM_UK.strip()},
                        {"role": "user", "content": user_payload},
                        {"role": "assistant", "content": assistant},
                    ],
                    "meta": {"source": "intel", "lang": lang},
                }
            )

    alert_journal = ROOT / "data" / "alerts" / "alerts.jsonl"
    for row in _read_jsonl(alert_journal, limit_per_source):
        if not row.get("text_preview"):
            continue
        samples.append(
            {
                "messages": [
                    {"role": "system", "content": SYSTEM_UK.strip()},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "level": row.get("level"),
                                "activity": {
                                    "activity_type": row.get("activity_type"),
                                    "source": row.get("source"),
                                    "score": row.get("score"),
                                    "symbol": row.get("symbol"),
                                },
                            },
                            ensure_ascii=False,
                        ),
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "summary": row.get("text_preview", "")[:120],
                                "action_hint": "See template action line",
                                "urgency": "medium",
                                "noise": False,
                                "level_override": None,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                "meta": {"source": "journal", "lang": "uk"},
            }
        )

    return samples


def main() -> int:
    ap = argparse.ArgumentParser(description="Export MUTE alert dataset for LocalBrain")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "alerts" / "dataset.jsonl")
    ap.add_argument("--limit", type=int, default=300, help="Per-source row limit")
    args = ap.parse_args()

    samples = build_samples(limit_per_source=args.limit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for s in samples:
            fh.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"Wrote {len(samples)} samples → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
