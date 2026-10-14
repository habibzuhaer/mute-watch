"""Cycle / liveness checks for scanner, monitors, and dashboard."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pump_prep.config import ROOT
from pump_prep import graph_store as gs

# How long since last state update before we call the cycle "stale"
STALE_SEC = int(os.getenv("MUTE_CYCLE_STALE_SEC", "600"))

# Market-cap bands for the "money weight" filter (USD). Labels are English;
# the UI translates them via pump_prep.i18n_ui (money_any / money_unknown keys).
MONEY_BANDS: dict[str, dict[str, Any]] = {
    "any": {"label": "Any weight", "min": None, "max": None},
    "micro": {"label": "< $350K", "min": 0, "max": 350_000},
    "small": {"label": "$350K–$3M", "min": 350_000, "max": 3_000_000},
    "mid": {"label": "$3M–$10M", "min": 3_000_000, "max": 10_000_000},
    "large": {"label": "$10M–$60M", "min": 10_000_000, "max": 60_000_000},
    "mega": {"label": "≥ $60M", "min": 60_000_000, "max": None},
    "unknown": {"label": "mcap unknown", "min": None, "max": None},
}


def money_band(mcap: float | None) -> str:
    if mcap is None:
        return "unknown"
    try:
        n = float(mcap)
    except (TypeError, ValueError):
        return "unknown"
    if n < 350_000:
        return "micro"
    if n < 3_000_000:
        return "small"
    if n < 10_000_000:
        return "mid"
    if n < 60_000_000:
        return "large"
    return "mega"


def mcap_in_band(mcap: float | None, band: str) -> bool:
    band = (band or "any").strip().lower()
    if band in ("", "any", "all"):
        return True
    if band == "unknown":
        return mcap is None
    spec = MONEY_BANDS.get(band)
    if not spec:
        return True
    if mcap is None:
        return False
    lo, hi = spec.get("min"), spec.get("max")
    if lo is not None and mcap < lo:
        return False
    if hi is not None and mcap >= hi:
        return False
    return True


def enrich_signal_money(row: dict[str, Any], index: dict[str, Any] | None = None) -> dict[str, Any]:
    """Attach mcap / money_band ("money weight") from the token universe."""
    out = dict(row)
    if out.get("mcap") is None:
        mcap = gs.lookup_mcap(
            symbol=out.get("symbol"),
            token_id=out.get("token_id"),
            contract=out.get("contract"),
            index=index,
        )
    else:
        try:
            mcap = float(out["mcap"])
        except (TypeError, ValueError):
            mcap = None
    out["mcap"] = mcap
    out["mcap_fmt"] = gs.fmt_mcap(mcap)
    out["money_band"] = money_band(mcap)
    out["money_label"] = MONEY_BANDS.get(out["money_band"], {}).get("label") or out["money_band"]
    return out


def _pid_alive(pid_file: Path) -> tuple[bool, int | None]:
    if not pid_file.exists():
        return False, None
    try:
        pid = int(pid_file.read_text().strip())
    except Exception:
        return False, None
    try:
        os.kill(pid, 0)
        return True, pid
    except OSError:
        return False, pid


def _parse_iso(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        raw = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def check_cycle_health(*, now: float | None = None, stale_sec: int = STALE_SEC) -> dict[str, Any]:
    """Verify scanner/monitor cycles are alive and recently updated."""
    now = time.time() if now is None else now
    state = gs.load_state()
    updated_at = state.get("updated_at")
    updated_ts = _parse_iso(updated_at)
    age = None if updated_ts is None else max(0.0, now - updated_ts)

    scan_ok, scan_pid = _pid_alive(ROOT / "scanner.pid")
    dwf_ok, dwf_pid = _pid_alive(ROOT / "mute.pid")
    prep_ok, prep_pid = _pid_alive(ROOT / "mute_prep.pid")
    dash_ok, dash_pid = _pid_alive(ROOT / "dashboard.pid")

    cycles = int(state.get("cycles") or 0)
    expand_q = len(state.get("expand_queue") or [])
    done = len(state.get("done_tokens") or [])

    from pump_prep.i18n_ui import t as _t

    issues_en: list[str] = []
    issues_uk: list[str] = []
    if not scan_ok:
        issues_en.append(_t("en", "issue_scanner_down"))
        issues_uk.append(_t("uk", "issue_scanner_down"))
    elif age is not None and age > stale_sec:
        issues_en.append(_t("en", "issue_scanner_stale", age=int(age), stale=stale_sec))
        issues_uk.append(_t("uk", "issue_scanner_stale", age=int(age), stale=stale_sec))
    if not prep_ok and not dwf_ok:
        issues_en.append(_t("en", "issue_monitors_off"))
        issues_uk.append(_t("uk", "issue_monitors_off"))
    if not dash_ok:
        issues_en.append(_t("en", "issue_dashboard_down"))
        issues_uk.append(_t("uk", "issue_dashboard_down"))
    issues = issues_en  # backward-compatible default (English)

    if scan_ok and age is not None and age <= stale_sec:
        cycle_status = "ok"
    elif scan_ok:
        cycle_status = "stale"
    else:
        cycle_status = "stopped"

    return {
        "cycle_status": cycle_status,  # ok | stale | stopped
        "cycles": cycles,
        "updated_at": updated_at,
        "age_sec": None if age is None else round(age, 1),
        "stale_after_sec": stale_sec,
        "done_tokens": done,
        "expand_queue": expand_q,
        "last_token": state.get("last_token"),
        "pass2_tokens": len(state.get("pass2_tokens") or []),
        "last_pass2_cycle": state.get("last_pass2_cycle"),
        "processes": {
            "scanner": {"running": scan_ok, "pid": scan_pid},
            "dwf": {"running": dwf_ok, "pid": dwf_pid},
            "prep": {"running": prep_ok, "pid": prep_pid},
            "dashboard": {"running": dash_ok, "pid": dash_pid},
        },
        "issues": issues,
        "issues_i18n": {"en": issues_en, "uk": issues_uk},
        "ok": cycle_status == "ok" and not issues,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def signal_board(
    limit_act: int = 15,
    limit_watch: int = 15,
    *,
    money_band_filter: str = "any",
    min_mcap: float | None = None,
) -> dict[str, Any]:
    """Split recent signals into explicit ACT vs WATCH boards."""
    from pump_prep.signals import MIN_SCORE, WATCH_SCORE

    rows = gs.read_jsonl_tail(gs.SIGNAL_FILE, 400)
    mcap_idx = gs.token_mcap_index()
    rows = [enrich_signal_money(r, mcap_idx) for r in rows]

    # dedupe by symbol+entity+direction keeping highest score
    best: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = f"{r.get('symbol')}|{r.get('match_entity')}|{r.get('direction')}|{r.get('hash') or ''}"
        prev = best.get(key)
        if prev is None or (r.get("score") or 0) >= (prev.get("score") or 0):
            best[key] = r
    uniq = list(best.values())

    def _pass_money(r: dict[str, Any]) -> bool:
        mcap = r.get("mcap")
        if min_mcap is not None:
            if mcap is None or float(mcap) < float(min_mcap):
                return False
        return mcap_in_band(mcap if mcap is None else float(mcap), money_band_filter)

    uniq = [r for r in uniq if _pass_money(r)]

    def _sort_key(x: dict[str, Any]) -> tuple:
        return (-(x.get("score") or 0), -(x.get("mcap") or 0), x.get("saved_at") or "")

    act = sorted(
        [r for r in uniq if (r.get("tier") == "actionable") or ((r.get("score") or 0) >= MIN_SCORE)],
        key=_sort_key,
    )
    watch = sorted(
        [
            r
            for r in uniq
            if r.get("tier") == "watch"
            or (WATCH_SCORE <= (r.get("score") or 0) < MIN_SCORE)
        ],
        key=_sort_key,
    )
    # avoid duplicating act items in watch
    act_keys = {f"{r.get('symbol')}|{r.get('match_entity')}|{r.get('hash')}" for r in act}
    watch = [r for r in watch if f"{r.get('symbol')}|{r.get('match_entity')}|{r.get('hash')}" not in act_keys]

    tiers = {"actionable": 0, "watch": 0, "noise": 0}
    for r in rows:
        t = r.get("tier") or "noise"
        if t not in tiers:
            t = "noise"
        tiers[t] += 1

    band_counts: dict[str, int] = {k: 0 for k in MONEY_BANDS}
    for r in rows:
        b = r.get("money_band") or "unknown"
        band_counts[b] = band_counts.get(b, 0) + 1

    return {
        "min_score": MIN_SCORE,
        "watch_score": WATCH_SCORE,
        "tiers_sample": tiers,
        "money_band": money_band_filter,
        "min_mcap": min_mcap,
        "money_bands": {k: {"label": v["label"], "count": band_counts.get(k, 0)} for k, v in MONEY_BANDS.items()},
        "act": act[:limit_act],
        "watch": watch[:limit_watch],
        "act_count": len(act),
        "watch_count": len(watch),
        "mcap_index_size": mcap_idx.get("count") or 0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def write_cycles_json(path: Path | None = None) -> Path:
    path = path or (ROOT / "out" / "cycles_health.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cycles": check_cycle_health(),
        "board": signal_board(),
        "progress": gs.progress_snapshot(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
