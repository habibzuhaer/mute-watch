#!/usr/bin/env python3
"""Local control panel for MUTE — serves dashboard HTML + start/stop/scan APIs.

Bind: 127.0.0.1 only. No auth — do not expose to the internet.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
HOST = os.getenv("MUTE_DASH_HOST", "127.0.0.1")
PORT = int(os.getenv("MUTE_DASH_PORT", "8765"))

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


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


def _port_listening(port: int) -> bool:
    try:
        import socket

        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def _http_ok(url: str) -> bool:
    try:
        import urllib.request

        with urllib.request.urlopen(url, timeout=1.5) as resp:  # noqa: S310
            return 200 <= int(getattr(resp, "status", 200)) < 500
    except Exception:
        return False


def _dashboard_healthy() -> tuple[bool, int | None, str]:
    """Never probe our own HTTP from inside a request — that orphans/deadlocks threads."""
    ok, pid = _pid_alive(ROOT / "dashboard.pid")
    if not ok:
        return False, pid, "stopped"
    if pid == os.getpid():
        return True, pid, "healthy"
    return True, pid, "running"


def _py() -> str:
    venv = ROOT / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


_status_cache_lock = threading.Lock()
_status_cache: dict[str, Any] = {"ts": 0.0, "payload": None}


def _status() -> dict:
    now = time.time()
    with _status_cache_lock:
        cached = _status_cache.get("payload")
        if cached is not None and now - float(_status_cache.get("ts") or 0) < 2.0:
            return cached

    dwf_ok, dwf_pid = _pid_alive(ROOT / "mute.pid")
    prep_ok, prep_pid = _pid_alive(ROOT / "mute_prep.pid")
    dash_ok, dash_pid, dash_state = _dashboard_healthy()
    scan_ok, scan_pid = _pid_alive(ROOT / "scanner.pid")
    roz_ok, roz_pid = _pid_alive(ROOT / "rozvidka.pid")
    intel_ok, intel_pid = _pid_alive(ROOT / "intel.pid")
    orch_ok, orch_pid = _pid_alive(ROOT / "orch.pid")
    reports = {
        "hub": (ROOT / "pump_prep" / "out" / "signals_hub.html").exists(),
        "deployer": (ROOT / "pump_prep" / "out" / "deployer_trace.html").exists(),
        "prep": (ROOT / "pump_prep" / "out" / "pump_prep_report.html").exists(),
        "graph": (ROOT / "pump_prep" / "out" / "graph_live.html").exists(),
        "rozvidka": (OUT / "rozvidka.html").exists(),
        "intel": (OUT / "intel.html").exists(),
        "intel_cycles": (OUT / "intel_cycles_health.json").exists(),
        "rozvidka_cycles": (OUT / "rozvidka_cycles_health.json").exists(),
        "mm": (ROOT / "crypto_funds_tracker" / "out" / "mm_pump_dump_watchlist.html").exists(),
        "tokens_350k": (ROOT / "crypto_funds_tracker" / "out" / "tokens_mcap_350k_60m.html").exists(),
        "tokens_3m": (ROOT / "crypto_funds_tracker" / "out" / "tokens_mcap_3m_800m.html").exists(),
        "funds": (ROOT / "crypto_funds_tracker" / "out" / "crypto_funds_report.html").exists(),
    }
    graph: dict = {}
    progress: dict = {}
    trades: dict = {}
    cycles: dict = {}
    board: dict = {}
    try:
        sys.path.insert(0, str(ROOT))
        from pump_prep import graph_store as gs  # noqa: WPS433
        from pump_prep.clusters import trade_stats  # noqa: WPS433
        from pump_prep.cycles import check_cycle_health, signal_board  # noqa: WPS433

        graph = gs.aggregate_summary().get("state") or {}
        progress = gs.progress_snapshot()
        trades = trade_stats()
        cycles = check_cycle_health()
        board = signal_board(limit_act=100, limit_watch=100)
    except Exception as e:
        graph = {"error": str(e)}
        progress = {"error": str(e)}
        trades = {"error": str(e)}
        cycles = {"error": str(e)}
        board = {"error": str(e)}
    with _jobs_lock:
        jobs = {k: {**v, "log_tail": _tail(v.get("log"))} for k, v in list(_jobs.items())[-8:]}
    intel_health: dict = {}
    roz_health: dict = {}
    orch_snap: dict = {}
    try:
        from intel.cycles import check_health as intel_check  # noqa: WPS433

        intel_health = intel_check()
    except Exception as e:
        intel_health = {"error": str(e)}
    try:
        from rozvidka.cycles import check_health as roz_check  # noqa: WPS433

        roz_health = roz_check()
    except Exception as e:
        roz_health = {"error": str(e)}
    try:
        from agents.orch import build_snapshot as orch_snapshot  # noqa: WPS433

        orch_snap = orch_snapshot()
    except Exception as e:
        orch_snap = {"ok": False, "error": str(e), "line": "орк —"}
    payload = {
        "ok": True,
        "root": str(ROOT),
        "dwf": {"running": dwf_ok, "pid": dwf_pid},
        "prep": {"running": prep_ok, "pid": prep_pid},
        "scanner": {"running": scan_ok, "pid": scan_pid},
        "rozvidka": {"running": roz_ok, "pid": roz_pid},
        "intel": {"running": intel_ok, "pid": intel_pid},
        "orch": {"running": orch_ok, "pid": orch_pid, **{k: v for k, v in orch_snap.items() if k not in {"running", "pid"}}},
        "intel_health": intel_health,
        "rozvidka_health": roz_health,
        "dashboard": {"running": dash_ok, "pid": dash_pid, "state": dash_state},
        "reports": reports,
        "graph": graph,
        "progress": progress,
        "trades": trades,
        "cycles": cycles,
        "board": board,
        "jobs": jobs,
        "ts": time.time(),
    }
    with _status_cache_lock:
        _status_cache["ts"] = time.time()
        _status_cache["payload"] = payload
    return payload


def _tail(path: str | None, n: int = 30) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return ""


def _run_script(name: str, args: list[str], log_name: str) -> dict:
    log = ROOT / "logs" / log_name
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(args)} ===\n")
    proc = subprocess.Popen(
        args,
        cwd=str(ROOT),
        stdout=log.open("a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    job_id = f"{name}-{int(time.time())}"
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id,
            "name": name,
            "pid": proc.pid,
            "log": str(log),
            "started": time.time(),
            "running": True,
        }

    def _wait() -> None:
        proc.wait()
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["running"] = False
                _jobs[job_id]["exit"] = proc.returncode

    threading.Thread(target=_wait, daemon=True).start()
    return {"ok": True, "job_id": job_id, "pid": proc.pid, "log": str(log)}


def _action(name: str) -> dict:
    py = _py()
    if name == "start_dwf":
        r = subprocess.run(["bash", str(ROOT / "scripts" / "start.sh")], cwd=str(ROOT), capture_output=True, text=True)
        return {"ok": r.returncode == 0, "out": (r.stdout or "") + (r.stderr or "")}
    if name == "stop_dwf":
        r = subprocess.run(["bash", str(ROOT / "scripts" / "stop.sh")], cwd=str(ROOT), capture_output=True, text=True)
        return {"ok": True, "out": (r.stdout or "") + (r.stderr or "")}
    if name == "start_prep":
        r = subprocess.run(
            ["bash", str(ROOT / "scripts" / "start_prep.sh")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        return {"ok": r.returncode == 0, "out": (r.stdout or "") + (r.stderr or "")}
    if name == "stop_prep":
        pid_file = ROOT / "mute_prep.pid"
        alive, pid = _pid_alive(pid_file)
        if alive and pid:
            os.kill(pid, 15)
            pid_file.unlink(missing_ok=True)
            return {"ok": True, "out": f"stopped prep pid={pid}"}
        pid_file.unlink(missing_ok=True)
        return {"ok": True, "out": "prep not running"}
    if name == "start_scanner":
        r = subprocess.run(
            ["bash", str(ROOT / "scripts" / "start_scanner.sh")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        return {"ok": r.returncode == 0, "out": (r.stdout or "") + (r.stderr or "")}
    if name == "stop_scanner":
        r = subprocess.run(
            ["bash", str(ROOT / "scripts" / "stop_scanner.sh")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        return {"ok": True, "out": (r.stdout or "") + (r.stderr or "")}
    if name == "graph_html":
        return _run_script(
            "graph_html",
            [_py(), "-m", "pump_prep", "graph-html"],
            "job_graph_html.log",
        )
    if name == "backfill_signals":
        return _run_script(
            "backfill_signals",
            [_py(), "-m", "pump_prep", "backfill-signals"],
            "job_backfill_signals.log",
        )
    if name == "rebuild_hub":
        return _run_script(
            "rebuild_hub",
            [_py(), "-m", "pump_prep", "hub"],
            "job_hub.log",
        )
    if name == "rebuild_panel":
        return _run_script(
            "rebuild_panel",
            [_py(), "-m", "pump_prep", "panel"],
            "job_panel.log",
        )
    if name == "rebuild_wiki":
        try:
            sys.path.insert(0, str(ROOT))
            from agents.wiki import rebuild

            snap = rebuild(reason="panel")
            return {"ok": True, "stats": snap.get("stats"), "built_at": snap.get("built_at")}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if name == "check_cycles":
        r = subprocess.run(
            [_py(), "-c", "from pump_prep.cycles import check_cycle_health, write_cycles_json; import json; p=write_cycles_json(); print(json.dumps(check_cycle_health(), ensure_ascii=False, indent=2)); print(p)"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
        )
        return {"ok": r.returncode == 0, "out": (r.stdout or "") + (r.stderr or "")}
    if name == "start_all":
        a = _action("start_dwf")
        b = _action("start_prep")
        c = _action("start_scanner")
        return {"ok": a.get("ok") and b.get("ok"), "dwf": a, "prep": b, "scanner": c}
    if name == "stop_all":
        a = _action("stop_dwf")
        b = _action("stop_prep")
        c = _action("stop_scanner")
        return {"ok": True, "dwf": a, "prep": b, "scanner": c}
    if name == "start_all_full":
        return {
            "ok": True,
            "dwf": _action("start_dwf"),
            "prep": _action("start_prep"),
            "scanner": _action("start_scanner"),
            "intel": _action("start_intel_2h"),
            "rozvidka": _action("start_rozvidka"),
            "orch": _action("start_orch"),
        }
    if name == "stop_all_full":
        return {
            "ok": True,
            "dwf": _action("stop_dwf"),
            "prep": _action("stop_prep"),
            "scanner": _action("stop_scanner"),
            "intel": _action("stop_intel"),
            "rozvidka": _action("stop_rozvidka"),
            "orch": _action("stop_orch"),
        }
    if name == "run_prep":
        return _run_script("pump_prep", [py, "-m", "pump_prep", "run", "--days", "14"], "job_prep.log")
    if name == "run_deployers":
        return _run_script(
            "deployers",
            [py, "-m", "pump_prep", "deployers", "--limit", "40", "--max-age", "365"],
            "job_deployers.log",
        )
    if name == "run_scans":
        # sequential chain in one background shell
        log = ROOT / "logs" / "job_scans.log"
        cmd = (
            f"cd {ROOT} && PYTHONPATH={ROOT} {py} -m pump_prep run --days 14 && "
            f"PYTHONPATH={ROOT} {py} -m pump_prep deployers --limit 40 --max-age 365"
        )
        return _run_script("scans", ["bash", "-lc", cmd], "job_scans.log")
    if name == "test_telegram":
        r = subprocess.run([py, "-m", "mute", "test-telegram"], cwd=str(ROOT), capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(ROOT)})
        return {"ok": r.returncode == 0, "out": (r.stdout or "") + (r.stderr or "")}
    if name == "start_orch":
        r = subprocess.run(
            ["bash", str(ROOT / "scripts" / "start_orch.sh")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        return {"ok": r.returncode == 0, "out": (r.stdout or "") + (r.stderr or "")}
    if name == "stop_orch":
        r = subprocess.run(
            ["bash", str(ROOT / "scripts" / "stop_orch.sh")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        return {"ok": True, "out": (r.stdout or "") + (r.stderr or "")}
    if name == "start_rozvidka":
        r = subprocess.run(
            ["bash", str(ROOT / "scripts" / "start_rozvidka.sh")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        return {"ok": r.returncode == 0, "out": (r.stdout or "") + (r.stderr or "")}
    if name == "stop_rozvidka":
        r = subprocess.run(
            ["bash", str(ROOT / "scripts" / "stop_rozvidka.sh")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        return {"ok": True, "out": (r.stdout or "") + (r.stderr or "")}
    if name == "rozvidka_once":
        return _run_script(
            "rozvidka_once",
            [_py(), "-m", "rozvidka", "once"],
            "job_rozvidka_once.log",
        )
    if name == "rozvidka_once_nolm":
        return _run_script(
            "rozvidka_once_nolm",
            [_py(), "-m", "rozvidka", "once", "--no-llm"],
            "job_rozvidka_once_nolm.log",
        )
    if name == "rozvidka_ui":
        return _run_script(
            "rozvidka_ui",
            [_py(), "-m", "rozvidka", "ui"],
            "job_rozvidka_ui.log",
        )
    if name == "start_intel":
        r = subprocess.run(
            ["bash", str(ROOT / "scripts" / "start_intel.sh")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
        )
        return {"ok": r.returncode == 0, "out": (r.stdout or "") + (r.stderr or "")}
    if name in {"start_intel_2h", "start_intel_12h"}:
        hours = "2" if name == "start_intel_2h" else "12"
        r = subprocess.run(
            ["bash", str(ROOT / "scripts" / "start_intel.sh")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PYTHONPATH": str(ROOT),
                "INTEL_COLLECT_HOURS": hours,
                "INTEL_FRESH": "1",
            },
        )
        return {"ok": r.returncode == 0, "out": (r.stdout or "") + (r.stderr or "")}
    if name == "intel_hubs":
        return _run_script(
            "intel_hubs",
            [_py(), "-m", "intel", "hubs"],
            "job_intel_hubs.log",
        )
    if name == "stop_intel":
        r = subprocess.run(
            ["bash", str(ROOT / "scripts" / "stop_intel.sh")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        return {"ok": True, "out": (r.stdout or "") + (r.stderr or "")}
    if name == "intel_once":
        return _run_script(
            "intel_once",
            [_py(), "-m", "intel", "once"],
            "job_intel_once.log",
        )
    if name == "intel_ui":
        return _run_script(
            "intel_ui",
            [_py(), "-m", "intel", "ui"],
            "job_intel_ui.log",
        )
    return {"ok": False, "error": f"unknown action {name}"}


REPORT_MAP = {
    "/reports/signals_hub.html": ROOT / "pump_prep" / "out" / "signals_hub.html",
    "/reports/deployer_trace.html": ROOT / "pump_prep" / "out" / "deployer_trace.html",
    "/reports/pump_prep_report.html": ROOT / "pump_prep" / "out" / "pump_prep_report.html",
    "/reports/graph_live.html": ROOT / "pump_prep" / "out" / "graph_live.html",
    "/reports/mm_pump_dump_watchlist.html": ROOT / "crypto_funds_tracker" / "out" / "mm_pump_dump_watchlist.html",
    "/reports/tokens_mcap_350k_60m.html": ROOT / "crypto_funds_tracker" / "out" / "tokens_mcap_350k_60m.html",
    "/reports/tokens_mcap_3m_800m.html": ROOT / "crypto_funds_tracker" / "out" / "tokens_mcap_3m_800m.html",
    "/reports/crypto_funds_report.html": ROOT / "crypto_funds_tracker" / "out" / "crypto_funds_report.html",
    "/cycles_health.json": OUT / "cycles_health.json",
    "/intel_cycles_health.json": OUT / "intel_cycles_health.json",
    "/rozvidka_cycles_health.json": OUT / "rozvidka_cycles_health.json",
    "/i18n.json": OUT / "i18n.json",
    "/kanban.html": OUT / "kanban.html",
    "/kanban": OUT / "kanban.html",
    "/orch.html": OUT / "kanban.html",
    "/wiki.html": OUT / "wiki.html",
    "/wiki": OUT / "wiki.html",
    "/rozvidka.html": OUT / "rozvidka.html",
    "/rozvidka": OUT / "rozvidka.html",
    "/api/rozvidka.json": ROOT / "data" / "rozvidka" / "snapshot.json",
    "/intel.html": OUT / "intel.html",
    "/intel": OUT / "intel.html",
    "/": OUT / "dashboard.html",
    "/dashboard.html": OUT / "dashboard.html",
    "/index.html": OUT / "dashboard.html",
    "/panel": OUT / "dashboard.html",
    "/panel.html": OUT / "dashboard.html",
    "/launch.html": OUT / "launch.html",
    "/launch": OUT / "launch.html",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # quieter
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, content_type: str = "text/html; charset=utf-8") -> None:
        if not path.exists():
            self._json(404, {"ok": False, "error": f"missing {path.name}"})
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self._cors()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/api/ping":
            self._json(200, {"ok": True, "pong": True, "pid": os.getpid(), "ts": time.time()})
            return
        if path == "/api/status":
            self._json(200, _status())
            return
        if path == "/api/kanban":
            try:
                sys.path.insert(0, str(ROOT))
                from agents.board import snapshot  # noqa: WPS433

                self._json(200, snapshot())
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return
        if path == "/api/wiki":
            try:
                sys.path.insert(0, str(ROOT))
                from agents.wiki import load_snapshot, write_ui as write_wiki
                from agents import trades

                snap = load_snapshot()
                if not snap.get("families"):
                    from agents.wiki import rebuild_safe

                    snap = rebuild_safe("api") or snap
                write_wiki(snap or None)
                paper = trades.snapshot(20)
                self._json(200, {**(snap or {}), "paper": paper, "ok": True})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return
        if path == "/api/orch":
            try:
                sys.path.insert(0, str(ROOT))
                from agents.orch import build_snapshot  # noqa: WPS433

                self._json(200, build_snapshot())
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return
        if path == "/api/rozvidka":
            try:
                sys.path.insert(0, str(ROOT))
                from rozvidka.runtime import build_snapshot  # noqa: WPS433

                self._json(200, build_snapshot())
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return
        if path == "/api/intel":
            try:
                sys.path.insert(0, str(ROOT))
                from intel.orchestrator import build_snapshot  # noqa: WPS433

                self._json(200, build_snapshot())
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return
        if path in REPORT_MAP:
            self._file(REPORT_MAP[path])
            return
        if path.startswith("/out/"):
            rel = path[len("/out/") :]
            self._file(OUT / rel)
            return
        self._json(404, {"ok": False, "error": "not found", "path": path})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "error": "bad json"})
            return

        if parsed.path == "/api/kanban":
            try:
                sys.path.insert(0, str(ROOT))
                from agents.board import ack, ack_all, add, done, follow, move, snapshot  # noqa: WPS433

                op = (body.get("op") or "").strip()
                if op == "ack_all":
                    self._json(200, ack_all())
                    return
                if op == "sync":
                    self._json(200, snapshot())
                    return
                if op == "add":
                    title = str(body.get("title") or "").strip()
                    if not title:
                        self._json(400, {"ok": False, "error": "title"})
                        return
                    self._json(
                        200,
                        {
                            "ok": True,
                            "card": add(
                                str(body.get("src") or "orch"),
                                title,
                                kind=str(body.get("kind") or "нотатка"),
                                detail=str(body.get("detail") or ""),
                                status=str(body.get("status") or "backlog"),
                            ),
                        },
                    )
                    return
                hid = (body.get("id") or "").strip()
                if op == "ack" and hid:
                    self._json(200, ack(hid))
                    return
                if op == "done" and hid:
                    self._json(200, done(hid))
                    return
                if op == "follow" and hid:
                    self._json(200, follow(hid))
                    return
                if op == "move" and hid:
                    st = str(body.get("status") or body.get("col") or "").strip()
                    if not st:
                        self._json(400, {"ok": False, "error": "status"})
                        return
                    self._json(200, move(hid, st))
                    return
                self._json(400, {"ok": False, "error": "op ack|ack_all|move|done|add|follow|sync"})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if parsed.path == "/api/paper":
            try:
                sys.path.insert(0, str(ROOT))
                from agents import trades

                op = (body.get("op") or "open").strip()
                if op == "real":
                    self._json(200, trades.promote_real(str(body.get("id") or "")))
                    return
                if op == "open":
                    row = trades.open_paper(
                        family_id=str(body.get("family_id") or ""),
                        symbol=str(body.get("symbol") or ""),
                        move=body.get("move") if isinstance(body.get("move"), dict) else None,
                        note=str(body.get("note") or ""),
                        source="api",
                    )
                    self._json(200, {"ok": True, "trade": row})
                    return
                self._json(400, {"ok": False, "error": "op open|real"})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if parsed.path == "/api/trade":
            try:
                sys.path.insert(0, str(ROOT))
                from pump_prep.clusters import add_trade  # noqa: WPS433

                row = add_trade(**body)
                self._json(200, {"ok": True, "trade": row})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if parsed.path != "/api/action":
            self._json(404, {"ok": False, "error": "not found"})
            return
        action = (body.get("action") or "").strip()
        if not action:
            self._json(400, {"ok": False, "error": "action required"})
            return
        try:
            result = _action(action)
            self._json(200, result)
        except Exception as e:
            self._json(500, {"ok": False, "error": str(e)})


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)

    class ReusableServer(ThreadingHTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    httpd = ReusableServer((HOST, PORT), Handler)
    httpd.timeout = 1.0
    # Avoid orphan threads hanging forever on half-closed probes
    Handler.timeout = 8
    print(f"MUTE dashboard http://{HOST}:{PORT}/", flush=True)
    print("Ctrl+C to stop", flush=True)
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nbye", flush=True)
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
